"""Отправка фото и предзагрузка."""

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.config import BotConfig
from bot.database import Database
from bot.handlers.caption_formatter import CaptionFormatter
from bot.handlers.image_selector import ImageSelector
from bot.performance import PerformanceTimer
from bot.stash_client import StashClient, StashImage

if TYPE_CHECKING:
    from bot.voting import VotingManager

logger = logging.getLogger(__name__)


class PhotoSender:
    """Класс для отправки фото и предзагрузки."""

    def __init__(
        self,
        config: BotConfig,
        stash_client: StashClient,
        database: Database,
        image_selector: ImageSelector,
        caption_formatter: CaptionFormatter,
        voting_manager: Optional["VotingManager"] = None,
        application=None,
        last_sent_images: dict[int, StashImage] | None = None,
        last_sent_image_id: dict[int, str] | None = None,
    ):
        """
        Инициализация отправителя фото.

        Args:
            config: Конфигурация бота
            stash_client: Клиент StashApp
            database: База данных
            image_selector: Селектор изображений
            caption_formatter: Форматтер подписей
            voting_manager: Менеджер голосования (опционально)
            application: Telegram Application (опционально)
            last_sent_images: Кэш последних отправленных изображений (для голосования)
            last_sent_image_id: Кэш ID последних отправленных изображений (для голосования)
        """
        self.config = config
        self.stash_client = stash_client
        self.database = database
        self.image_selector = image_selector
        self.caption_formatter = caption_formatter
        self.voting_manager = voting_manager
        self.application = application
        self._last_sent_images = last_sent_images or {}
        self._last_sent_image_id = last_sent_image_id or {}

        # Кэш для предзагрузки
        self._prefetched_image: dict[str, Any] | None = None
        self._prefetch_lock: asyncio.Lock = asyncio.Lock()

    def _should_show_threshold_notification(self, gallery_id: str) -> bool:
        """
        Проверка, нужно ли показать уведомление о достижении порога исключения.

        Args:
            gallery_id: ID галереи

        Returns:
            bool: True если порог достигнут И уведомление еще не показывалось
        """
        if not self.voting_manager or not gallery_id:
            return False

        try:
            # Проверяем, достигнут ли порог
            threshold_reached, _ = self.voting_manager.check_exclusion_threshold(
                gallery_id
            )

            if not threshold_reached:
                return False

            # Проверяем, показывалось ли уже уведомление
            notification_shown = self.database.is_threshold_notification_shown(
                gallery_id
            )

            # Показываем уведомление только если порог достигнут И уведомление еще не показывалось
            return not notification_shown

        except Exception as e:
            logger.warning(
                f"Ошибка при проверке показа уведомления о пороге для галереи {gallery_id}: {e}"
            )
            return False

    async def send_random_photo(
        self,
        chat_id: int,
        user_id: int | None = None,
        context: ContextTypes.DEFAULT_TYPE | None = None,
        use_high_quality: bool = False,
    ) -> bool:
        """
        Отправка случайного фото из кеша (только из StashApp).

        Args:
            chat_id: ID чата для отправки
            user_id: ID пользователя (для статистики)
            context: Контекст бота (опционально)
            use_high_quality: Игнорируется (всегда используется file_id из кеша)

        Returns:
            bool: True если отправка успешна
        """
        timer = PerformanceTimer("Send random photo")
        timer.start()

        try:
            # Получаем список недавно отправленных ID для исключения
            recent_ids = self.database.get_recent_image_ids(
                self.config.history.avoid_recent_days
            )

            # Получаем случайное изображение из кеша (только с telegram_file_id)
            image = await self.image_selector.get_random_image_from_cache(recent_ids)

            if not image:
                logger.warning("⚠️ Кеш пуст или не найдено подходящих изображений")
                if context:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⏳ Кеш пуст. Подождите, пока изображения будут предзагружены в служебный канал.",
                    )
                return False

            # Получаем file_id из объекта изображения (уже загружен из кеша)
            file_id = image.telegram_file_id

            if not file_id:
                logger.warning(
                    f"⚠️ telegram_file_id не найден для изображения {image.id} в объекте (должен быть в details)"
                )
                if context:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⏳ Изображение не в кеше. Подождите, пока оно будет предзагружено.",
                    )
                return False

            timer.checkpoint("Get from cache")

            # Определяем, было ли изображение предзагружено из служебного канала
            is_preloaded_from_cache = file_id is not None
            logger.info(
                f"Image {image.id}: file_id={'YES' if file_id else 'NO'}, is_preloaded_from_cache={is_preloaded_from_cache}"
            )

            # Проверка достижения порога и формирование подписи
            should_show_threshold = False
            if image.gallery_id:
                should_show_threshold = self._should_show_threshold_notification(
                    image.gallery_id
                )

            if should_show_threshold:
                # Используем формат с порогом
                gallery_stats = self.database.get_gallery_statistics(image.gallery_id)
                if gallery_stats:
                    caption = self.caption_formatter.format_threshold_caption(
                        image, gallery_stats, is_preloaded_from_cache
                    )
                    # Отмечаем уведомление как показанное
                    self.database.mark_threshold_notification_shown(image.gallery_id)
                else:
                    # Fallback на обычный формат, если статистики нет
                    caption = self.caption_formatter.format_caption(
                        image, is_preloaded_from_cache
                    )
            else:
                # Обычный формат
                caption = self.caption_formatter.format_caption(
                    image, is_preloaded_from_cache
                )

            # Создание кнопок для голосования
            keyboard = [
                [
                    InlineKeyboardButton("👍", callback_data=f"vote_up_{image.id}"),
                    InlineKeyboardButton("👎", callback_data=f"vote_down_{image.id}"),
                ]
            ]

            # Добавление кнопки исключения, если порог достигнут
            gallery_title = image.get_gallery_title()
            if should_show_threshold and image.gallery_id and gallery_title:
                exclude_button_text = f'🚫 Исключить "{gallery_title}"'
                # Ограничиваем длину текста кнопки (Telegram имеет лимит)
                if len(exclude_button_text) > 64:
                    exclude_button_text = f'🚫 Исключить "{gallery_title[:50]}..."'
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            exclude_button_text,
                            callback_data=f"exclude_gallery_{image.gallery_id}",
                        )
                    ]
                )

            reply_markup = InlineKeyboardMarkup(keyboard)

            # Отправка фото используя file_id
            sent_message = None

            try:
                if context:
                    sent_message = await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=file_id,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )
                else:
                    # Для планировщика используем application
                    if self.application:
                        sent_message = await self.application.bot.send_photo(
                            chat_id=chat_id,
                            photo=file_id,
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=reply_markup,
                        )

            except asyncio.CancelledError:
                # Пробрасываем CancelledError дальше
                raise
            except TelegramError as e:
                # Если file_id недействителен, логируем ошибку
                logger.error(
                    f"file_id недействителен для {image.id}: {e}. "
                    "Изображение нужно перезагрузить в кеш."
                )
                if context:
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text="❌ Не удалось отправить изображение. Попробуйте позже.",
                        )
                    except asyncio.CancelledError:
                        raise
                return False

            timer.checkpoint("Send to Telegram")

            # Получаем file_id из ответа для обновления в StashApp (если изменился)
            if sent_message and sent_message.photo:
                new_file_id = sent_message.photo[-1].file_id
                # Обновляем в StashApp если file_id изменился
                if new_file_id != file_id:
                    await self.stash_client.save_telegram_file_id(image.id, new_file_id)
                    logger.debug(
                        f"Обновлен file_id для изображения {image.id} в StashApp"
                    )

            # Сохранение в базу данных (только для статистики, без file_id)
            self.database.add_sent_photo(
                image_id=image.id,
                user_id=user_id,
                title=image.title,
                file_id_high_quality=None,  # Больше не сохраняем в БД
            )
            timer.checkpoint("Save to database")

            # Сохранение изображения в кэш для обработки голосования
            if user_id:
                self._last_sent_images[user_id] = image
                self._last_sent_image_id[user_id] = image.id

            # Проверка размера кеша и пополнение при необходимости
            if self.config.cache:
                asyncio.create_task(self._check_and_refill_cache())

            timer.end()
            logger.info(f"Фото успешно отправлено: {image.id} (из кеша)")
            return True

        except asyncio.CancelledError:
            # Пробрасываем CancelledError дальше - это нормальная часть механизма отмены задач
            timer.end()
            logger.debug("Отправка фото отменена")
            raise
        except TelegramError as e:
            logger.error(f"Ошибка Telegram при отправке фото: {e}")
            timer.end()
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при отправке фото: {e}")
            timer.end()
            return False

    async def _check_and_refill_cache(self):
        """
        Проверка размера кеша и пополнение при необходимости.

        Выполняется в фоновом режиме после отправки фото.
        """
        try:
            if not self.config.cache:
                return

            cache_size = await self.stash_client.get_cache_size()
            min_cache_size = self.config.cache.min_cache_size

            if cache_size < min_cache_size:
                deficit = min_cache_size - cache_size
                logger.info(
                    f"Размер кеша: {cache_size}/{min_cache_size}. "
                    f"Нужно пополнить на {deficit} изображений"
                )
                # Пополнение будет выполнено планировщиком
                # Здесь только логируем для информации
        except Exception as e:
            logger.error(f"Ошибка при проверке размера кеша: {e}")

    async def preload_image_to_cache(
        self, image: StashImage, use_high_quality: bool = True
    ):
        """
        Предзагрузка изображения в служебный канал для получения file_id.

        Сохраняет file_id в StashApp (кастомное поле telegram_file_id).

        Args:
            image: Объект изображения StashImage
            use_high_quality: Если True, использует high quality версию
        """
        if not self.config.telegram.cache_channel_id:
            logger.debug("Предзагрузка в канал отключена: cache_channel_id не указан")
            return

        if not self.application:
            logger.warning(
                "Не удалось предзагрузить изображение: application не инициализирован"
            )
            return

        try:
            # Проверяем, не сохранен ли уже file_id в StashApp
            # Используем telegram_file_id из объекта, если он уже загружен
            existing_file_id = image.telegram_file_id
            if existing_file_id:
                logger.debug(
                    f"telegram_file_id для изображения {image.id} уже сохранен в StashApp (details не пусто), пропускаем предзагрузку"
                )
                return

            # Скачивание изображения с выбранным качеством
            image_url = image.get_image_url(use_high_quality=use_high_quality)
            image_data = await self.stash_client.download_image(image_url)

            if not image_data:
                logger.warning(
                    f"Не удалось скачать изображение {image.id} для предзагрузки в канал"
                )
                return

            # Отправка в служебный канал
            sent_message = await self.application.bot.send_photo(
                chat_id=self.config.telegram.cache_channel_id, photo=image_data
            )

            # Получение file_id из ответа (берем самый большой размер)
            file_id = sent_message.photo[-1].file_id

            # Сохранение file_id в StashApp
            success = await self.stash_client.save_telegram_file_id(image.id, file_id)

            if success:
                logger.info(
                    f"✅ Предзагружено изображение {image.id} в служебный канал "
                    f"({'high quality' if use_high_quality else 'thumbnail'}, "
                    f"{len(image_data) / 1024:.1f} KB, file_id={file_id[:20]}...)"
                )
            else:
                logger.warning(
                    f"⚠️ Предзагружено изображение {image.id}, но не удалось сохранить file_id в StashApp"
                )

        except TelegramError as e:
            logger.error(
                f"Ошибка Telegram при предзагрузке изображения {image.id} в канал: {e}"
            )
        except Exception as e:
            logger.error(
                f"Неожиданная ошибка при предзагрузке изображения {image.id} в канал: {e}"
            )
