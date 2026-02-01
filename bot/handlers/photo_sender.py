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
        Отправка случайного фото.

        Args:
            chat_id: ID чата для отправки
            user_id: ID пользователя (для статистики)
            context: Контекст бота (опционально)
            use_high_quality: Если True, использует preview качество (для автоматических задач)
                            Если False, использует thumbnail (быстро, для ручных команд)

        Returns:
            bool: True если отправка успешна
        """
        timer = PerformanceTimer("Send random photo")
        timer.start()

        try:
            # Проверка наличия предзагруженного изображения
            image = None
            image_data = None
            used_prefetch = False
            cached_file_id = None  # file_id из кеша БД

            if self._prefetched_image and not use_high_quality:
                # Предзагруженное изображение используется только для ручных команд (низкое качество)
                # Для автоматических задач (высокое качество) всегда загружаем новое
                # Проверяем, что предзагруженное изображение еще актуально
                recent_ids = self.database.get_recent_image_ids(
                    self.config.history.avoid_recent_days
                )
                prefetched_image = self._prefetched_image["image"]

                if prefetched_image.id not in recent_ids:
                    logger.info("⚡ Используется предзагруженное изображение")
                    image = prefetched_image
                    image_data = self._prefetched_image["image_data"]
                    self._prefetched_image = None  # Очистка кэша
                    used_prefetch = True
                    # Проверяем наличие file_id в кеше для предзагруженного изображения
                    cached_file_id = self.database.get_file_id(
                        image.id, use_high_quality=True
                    )
                    timer.checkpoint("Use prefetched image")
                else:
                    logger.info(
                        "⚠️ Предзагруженное изображение устарело, загружаем новое"
                    )
                    self._prefetched_image = None  # Очистка устаревшего кэша
                    timer.checkpoint("Clear stale cache")

            # Если нет предзагруженного изображения, загружаем обычным способом
            if not image or not image_data:
                # Получение списка недавно отправленных ID
                recent_ids = self.database.get_recent_image_ids(
                    self.config.history.avoid_recent_days
                )
                timer.checkpoint("Get recent IDs from DB")

                logger.info(
                    f"Запрос случайного фото (исключая {len(recent_ids)} недавних)"
                )

                # Получение списка фильтров для метрик
                if self.voting_manager:
                    timer.checkpoint("Get filtering lists from DB")

                # Получение случайного изображения с учетом предпочтений
                image = await self.image_selector.get_random_image(recent_ids)
                timer.checkpoint("Get random image")

                if not image:
                    logger.error("Не удалось получить случайное изображение")
                    if context:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text="❌ Не удалось получить изображение из StashApp. Попробуйте позже.",
                        )
                    return False

                # Автоматически добавляем галерею в базу, если её там еще нет
                # Это нужно для того, чтобы все галереи участвовали во взвешенном выборе
                if image.gallery_id and image.gallery_title:
                    try:
                        gallery_created = self.database.ensure_gallery_exists(
                            image.gallery_id, image.gallery_title
                        )
                        if gallery_created:
                            # Инвалидируем кэш весов, если галерея была создана
                            if self.voting_manager:
                                self.voting_manager.invalidate_weights_cache()
                            logger.debug(
                                f"Галерея '{image.gallery_title}' добавлена в базу с весом 1.0"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Ошибка при инициализации галереи {image.gallery_id}: {e}"
                        )

                # Проверка наличия file_id в кеше
                # Для ручных запросов и крон-задач используем file_id_high_quality если есть
                cached_file_id = self.database.get_file_id(
                    image.id, use_high_quality=True
                )

                if cached_file_id:
                    logger.info(
                        f"⚡ Используется кешированный file_id_high_quality для image_id={image.id}"
                    )
                    image_data = None  # Не нужно скачивать файл
                    timer.checkpoint("Get cached file_id")
                else:
                    # Скачивание изображения с выбранным качеством
                    image_url = image.get_image_url(use_high_quality)
                    image_data = await self.stash_client.download_image(image_url)
                    timer.checkpoint("Download image")

                    if not image_data:
                        logger.error(f"Не удалось скачать изображение {image.id}")
                        if context:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text="❌ Не удалось скачать изображение. Попробуйте позже.",
                            )
                        return False

            # Определяем, было ли изображение предзагружено из служебного канала
            if cached_file_id is None:
                cached_file_id = self.database.get_file_id(
                    image.id, use_high_quality=True
                )
            is_preloaded_from_cache = cached_file_id is not None
            logger.info(
                f"Image {image.id}: cached_file_id={'YES' if cached_file_id else 'NO'}, is_preloaded_from_cache={is_preloaded_from_cache}"
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
            if should_show_threshold and image.gallery_id and image.gallery_title:
                exclude_button_text = f'🚫 Исключить "{image.gallery_title}"'
                # Ограничиваем длину текста кнопки (Telegram имеет лимит)
                if len(exclude_button_text) > 64:
                    exclude_button_text = (
                        f'🚫 Исключить "{image.gallery_title[:50]}..."'
                    )
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            exclude_button_text,
                            callback_data=f"exclude_gallery_{image.gallery_id}",
                        )
                    ]
                )

            reply_markup = InlineKeyboardMarkup(keyboard)

            # Отправка фото
            sent_message = None
            file_id_to_save = None

            try:
                if context:
                    # Используем file_id если есть, иначе image_data
                    photo_source = cached_file_id if cached_file_id else image_data
                    sent_message = await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo_source,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )
                else:
                    # Для планировщика используем application
                    if self.application:
                        photo_source = cached_file_id if cached_file_id else image_data
                        sent_message = await self.application.bot.send_photo(
                            chat_id=chat_id,
                            photo=photo_source,
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=reply_markup,
                        )

                # Получаем file_id из ответа для сохранения
                if sent_message and sent_message.photo:
                    file_id_to_save = sent_message.photo[-1].file_id

            except asyncio.CancelledError:
                # Пробрасываем CancelledError дальше
                raise
            except TelegramError as e:
                # Если file_id недействителен, пробуем загрузить файл
                if cached_file_id and "file_id" in str(e).lower():
                    logger.warning(
                        f"file_id недействителен для {image.id}, загружаем файл: {e}"
                    )
                    # Загружаем файл заново
                    image_url = image.get_image_url(use_high_quality)
                    image_data = await self.stash_client.download_image(image_url)
                    if not image_data:
                        logger.error(
                            f"Не удалось скачать изображение {image.id} после ошибки file_id"
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

                    # Повторная отправка с файлом
                    try:
                        if context:
                            sent_message = await context.bot.send_photo(
                                chat_id=chat_id,
                                photo=image_data,
                                caption=caption,
                                parse_mode="HTML",
                                reply_markup=reply_markup,
                            )
                        else:
                            if self.application:
                                sent_message = await self.application.bot.send_photo(
                                    chat_id=chat_id,
                                    photo=image_data,
                                    caption=caption,
                                    parse_mode="HTML",
                                    reply_markup=reply_markup,
                                )

                        if sent_message and sent_message.photo:
                            file_id_to_save = sent_message.photo[-1].file_id
                    except asyncio.CancelledError:
                        raise
                else:
                    raise

            timer.checkpoint("Send to Telegram")

            # Сохранение изображения в кэш для обработки голосования
            if user_id:
                self._last_sent_images[user_id] = image

            # Сохранение file_id в БД если еще не сохранен
            if file_id_to_save:
                if use_high_quality:
                    # Сохраняем file_id_high_quality
                    existing_file_id = self.database.get_file_id(
                        image.id, use_high_quality=True
                    )
                    if not existing_file_id:
                        self.database.save_file_id(
                            image.id, file_id_to_save, use_high_quality=True
                        )
                else:
                    # Для ручных запросов
                    if cached_file_id:
                        # Использовали file_id_high_quality из кеша
                        # Проверяем, сохранен ли он в БД, если нет - сохраняем
                        existing_file_id_hq = self.database.get_file_id(
                            image.id, use_high_quality=True
                        )
                        if not existing_file_id_hq:
                            # Сохраняем file_id_high_quality (может отличаться от file_id_to_save)
                            self.database.save_file_id(
                                image.id, cached_file_id, use_high_quality=True
                            )
                    else:
                        # Загрузили thumbnail, сохраняем file_id
                        existing_file_id = self.database.get_file_id(
                            image.id, use_high_quality=False
                        )
                        if not existing_file_id:
                            self.database.save_file_id(
                                image.id, file_id_to_save, use_high_quality=False
                            )

            # Определяем file_id_high_quality для сохранения в add_sent_photo
            file_id_high_quality_to_save = None

            if use_high_quality:
                # Для высокого качества: используем cached_file_id если есть, иначе file_id_to_save
                file_id_high_quality_to_save = (
                    cached_file_id if cached_file_id else file_id_to_save
                )
            else:
                # Для ручных запросов: если есть cached_file_id (это file_id_high_quality), сохраняем его
                if cached_file_id:
                    file_id_high_quality_to_save = cached_file_id

            logger.info(
                f"Image {image.id}: file_id_high_quality_to_save={'YES' if file_id_high_quality_to_save else 'NO'}, cached_file_id={'YES' if cached_file_id else 'NO'}"
            )

            # Сохранение в базу данных
            self.database.add_sent_photo(
                image_id=image.id,
                user_id=user_id,
                title=image.title,
                file_id_high_quality=file_id_high_quality_to_save,
            )
            timer.checkpoint("Save to database")

            # Запуск фоновой предзагрузки следующего изображения
            # Только если была команда от пользователя (не планировщик)
            if user_id:
                asyncio.create_task(self.prefetch_next_image())
                logger.debug("🔄 Запущена фоновая предзагрузка следующего изображения")

            timer.end()
            logger.info(
                f"Фото успешно отправлено: {image.id} {'(использована предзагрузка)' if used_prefetch else ''}"
            )
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

    async def prefetch_next_image(self):
        """
        Предзагрузка следующего изображения в фоновом режиме.
        Выполняется асинхронно после отправки текущего фото.
        """
        async with self._prefetch_lock:
            try:
                logger.debug("🔄 Начало предзагрузки следующего изображения...")

                # Получение списка недавно отправленных ID
                recent_ids = self.database.get_recent_image_ids(
                    self.config.history.avoid_recent_days
                )

                # Получение случайного изображения с учетом предпочтений
                image = await self.image_selector.get_random_image(recent_ids)

                if not image:
                    logger.warning("⚠️ Не удалось предзагрузить изображение")
                    return

                # Скачивание изображения (предзагрузка всегда использует низкое качество для скорости)
                image_url = image.get_image_url(use_high_quality=False)
                image_data = await self.stash_client.download_image(image_url)

                if not image_data:
                    logger.warning(
                        f"⚠️ Не удалось скачать изображение {image.id} для предзагрузки"
                    )
                    return

                # Сохранение в кэш
                self._prefetched_image = {"image": image, "image_data": image_data}

                logger.info(
                    f"✅ Предзагружено изображение {image.id} ({len(image_data) / 1024:.1f} KB)"
                )

            except Exception as e:
                logger.error(f"❌ Ошибка при предзагрузке изображения: {e}")

    async def preload_image_to_cache(
        self, image: StashImage, use_high_quality: bool = True
    ):
        """
        Предзагрузка изображения в служебный канал для получения file_id.

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
            # Проверяем, не сохранен ли уже file_id
            existing_file_id = self.database.get_file_id(
                image.id, use_high_quality=use_high_quality
            )
            if existing_file_id:
                logger.debug(
                    f"file_id для изображения {image.id} уже сохранен, пропускаем предзагрузку"
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

            # Сохранение file_id в БД
            self.database.save_file_id(
                image.id, file_id, use_high_quality=use_high_quality
            )

            logger.info(
                f"✅ Предзагружено изображение {image.id} в служебный канал "
                f"({'high quality' if use_high_quality else 'thumbnail'}, "
                f"{len(image_data) / 1024:.1f} KB, file_id={file_id[:20]}...)"
            )

        except TelegramError as e:
            logger.error(
                f"Ошибка Telegram при предзагрузке изображения {image.id} в канал: {e}"
            )
        except Exception as e:
            logger.error(
                f"Неожиданная ошибка при предзагрузке изображения {image.id} в канал: {e}"
            )
