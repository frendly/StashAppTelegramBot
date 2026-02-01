"""Обработка голосования."""

import logging
import time
from typing import TYPE_CHECKING, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import BotConfig
from bot.database import Database
from bot.handlers.caption_formatter import CaptionFormatter
from bot.stash_client import StashClient, StashImage

if TYPE_CHECKING:
    from bot.handlers.photo_sender import PhotoSender
    from bot.voting import VotingManager

logger = logging.getLogger(__name__)


class VoteHandler:
    """Класс для обработки голосования."""

    def __init__(
        self,
        config: BotConfig,
        stash_client: StashClient,
        database: Database,
        caption_formatter: CaptionFormatter,
        voting_manager: Optional["VotingManager"] = None,
        application=None,
        photo_sender: Optional["PhotoSender"] = None,
        last_sent_images: dict[int, StashImage] | None = None,
        last_sent_image_id: dict[int, str] | None = None,
        last_command_time: dict[int, float] | None = None,
    ):
        """
        Инициализация обработчика голосования.

        Args:
            config: Конфигурация бота
            stash_client: Клиент StashApp
            database: База данных
            caption_formatter: Форматтер подписей
            voting_manager: Менеджер голосования (опционально)
            application: Telegram Application (опционально)
            photo_sender: Отправитель фото (опционально, для отправки нового фото после голосования)
            last_sent_images: Кэш последних отправленных изображений
            last_sent_image_id: Кэш ID последнего отправленного изображения
            last_command_time: Кэш времени последней команды (для rate limiting)
        """
        self.config = config
        self.stash_client = stash_client
        self.database = database
        self.caption_formatter = caption_formatter
        self.voting_manager = voting_manager
        self.application = application
        self.photo_sender = photo_sender
        self._last_sent_images = last_sent_images or {}
        self._last_sent_image_id = last_sent_image_id or {}
        self._last_command_time = last_command_time or {}

    def _is_authorized(self, user_id: int) -> bool:
        """
        Проверка авторизации пользователя.

        Args:
            user_id: Telegram ID пользователя

        Returns:
            bool: True если пользователь авторизован
        """
        return user_id in self.config.telegram.allowed_user_ids

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

    async def handle_vote_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        Обработчик callback для голосования.

        Args:
            update: Обновление от Telegram
            context: Контекст бота
        """
        query = update.callback_query
        user_id = update.effective_user.id

        # Проверка авторизации
        if not self._is_authorized(user_id):
            await query.answer("❌ У вас нет доступа к этому боту.")
            return

        # Проверяем наличие voting_manager
        if not self.voting_manager:
            await query.answer("⚠️ Система голосования недоступна")
            return

        # Подтверждаем получение callback
        await query.answer()

        try:
            # Парсим callback data
            callback_data = query.data
            if not callback_data.startswith("vote_"):
                return

            parts = callback_data.split("_")
            if len(parts) != 3:
                logger.error(f"Неверный формат callback_data: {callback_data}")
                return

            vote_type = parts[1]  # "up" или "down"
            image_id = parts[2]

            vote = 1 if vote_type == "up" else -1

            # Получаем изображение из кэша
            image = self._last_sent_images.get(user_id)

            if not image or image.id != image_id:
                # Если изображения нет в кэше, пытаемся получить из StashApp API
                logger.warning(
                    f"Изображение {image_id} не найдено в кэше для user {user_id}, пытаемся получить из API"
                )
                image = await self.stash_client.get_image_by_id(image_id)

                if not image:
                    # Если и из API не удалось получить, возвращаем ошибку
                    logger.error(
                        f"Не удалось получить изображение {image_id} из API для user {user_id}"
                    )
                    await query.edit_message_reply_markup(reply_markup=None)
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text="⚠️ Не удалось обработать голос. Попробуйте запросить новое фото.",
                    )
                    return

                logger.info(
                    f"Изображение {image_id} получено из API для user {user_id}"
                )

            # Обрабатываем голос
            logger.info(
                f"Обработка голоса: user={user_id}, image={image_id}, vote={vote}"
            )
            result = await self.voting_manager.process_vote(image, vote)

            # Формируем сообщение об обновлениях
            vote_emoji = "👍" if vote > 0 else "👎"
            response_parts = [f"{vote_emoji} <b>Ваш голос учтен!</b>"]

            if result["image_rating_updated"]:
                rating = 5 if vote > 0 else 1
                response_parts.append(f"✅ Рейтинг фото обновлен: {rating}/5")

            if result["performers_updated"]:
                performers_str = ", ".join(result["performers_updated"][:3])
                response_parts.append(f"👤 Перформеры обновлены: {performers_str}")

            if result["gallery_updated"]:
                response_parts.append(
                    f"📁 Галерея обновлена: {result['gallery_updated']}"
                )

            if result["gallery_rating_updated"]:
                response_parts.append("⭐ Рейтинг галереи установлен в Stash!")

            if result["error"]:
                response_parts.append(f"⚠️ Ошибка: {result['error']}")

            # Проверяем достижение порога после голосования
            should_show_threshold = False
            if image.gallery_id:
                should_show_threshold = self._should_show_threshold_notification(
                    image.gallery_id
                )

            # Обновляем кнопки (отмечаем сделанный выбор)
            voted_keyboard = [
                [
                    InlineKeyboardButton(
                        f"{'✓ ' if vote > 0 else ''}👍",
                        callback_data=f"voted_{image_id}",
                    ),
                    InlineKeyboardButton(
                        f"{'✓ ' if vote < 0 else ''}👎",
                        callback_data=f"voted_{image_id}",
                    ),
                ]
            ]

            # Если порог достигнут, добавляем кнопку исключения и обновляем подпись
            if should_show_threshold and image.gallery_id and image.gallery_title:
                # Получаем обновленную статистику
                gallery_stats = self.database.get_gallery_statistics(image.gallery_id)
                if gallery_stats:
                    # Проверяем, было ли изображение предзагружено из служебного канала
                    cached_file_id = self.database.get_file_id(
                        image.id, use_high_quality=True
                    )
                    is_preloaded_from_cache = cached_file_id is not None
                    # Формируем новую подпись с порогом
                    new_caption = self.caption_formatter.format_threshold_caption(
                        image, gallery_stats, is_preloaded_from_cache
                    )

                    # Добавляем кнопку исключения
                    exclude_button_text = f'🚫 Исключить "{image.gallery_title}"'
                    if len(exclude_button_text) > 64:
                        exclude_button_text = (
                            f'🚫 Исключить "{image.gallery_title[:50]}..."'
                        )
                    voted_keyboard.append(
                        [
                            InlineKeyboardButton(
                                exclude_button_text,
                                callback_data=f"exclude_gallery_{image.gallery_id}",
                            )
                        ]
                    )

                    # Обновляем подпись и кнопки в сообщении
                    try:
                        await query.edit_message_caption(
                            caption=new_caption,
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(voted_keyboard),
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось обновить подпись сообщения: {e}")
                        # Если не удалось обновить подпись, просто обновляем кнопки
                        await query.edit_message_reply_markup(
                            reply_markup=InlineKeyboardMarkup(voted_keyboard)
                        )

                    # Отмечаем уведомление как показанное
                    self.database.mark_threshold_notification_shown(image.gallery_id)
                else:
                    # Если статистики нет, просто обновляем кнопки
                    await query.edit_message_reply_markup(
                        reply_markup=InlineKeyboardMarkup(voted_keyboard)
                    )
            else:
                # Порог не достигнут, просто обновляем кнопки
                await query.edit_message_reply_markup(
                    reply_markup=InlineKeyboardMarkup(voted_keyboard)
                )

            # Отправляем сообщение с результатом голосования
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="\n".join(response_parts),
                parse_mode="HTML",
            )

            # Инвалидация кэша фильтрации после голосования
            self.voting_manager.invalidate_filtering_cache()

            # Определяем, нужно ли отправлять новое изображение
            should_send_new_image = False

            # Проверяем, является ли изображение последним (сначала кэш, потом БД)
            last_image_id = self._last_sent_image_id.get(user_id)

            if last_image_id and image_id == last_image_id:
                # Изображение совпадает с последним в кэше - отправляем новое
                should_send_new_image = True
                logger.info(
                    f"Изображение {image_id} является последним (из кэша), отправляем новое изображение"
                )
            else:
                # Кэш пуст или не совпадает - проверяем БД для надежности
                # (кэш может быть устаревшим, поэтому всегда проверяем БД)
                last_photo = self.database.get_last_sent_photo_for_user(user_id)
                if last_photo:
                    last_photo_image_id = last_photo[0]
                    # Обновляем кэш для будущих проверок
                    self._last_sent_image_id[user_id] = last_photo_image_id

                    if image_id == last_photo_image_id:
                        # Изображение совпадает с последним в БД - отправляем новое
                        should_send_new_image = True
                        logger.info(
                            f"Изображение {image_id} является последним (из БД), отправляем новое изображение"
                        )
                    else:
                        # Изображение не совпадает с последним в БД - не отправляем
                        should_send_new_image = False
                        logger.info(
                            f"Изображение {image_id} не является последним (последнее: {last_photo_image_id}), не отправляем новое изображение"
                        )
                else:
                    # В БД нет записей для пользователя - это может быть первое изображение
                    # Если изображение получено из API (fallback), значит его точно нет в БД - отправляем новое
                    # Если из кэша, но нет в БД - странная ситуация, но тоже отправляем новое для безопасности
                    should_send_new_image = True
                    logger.info(
                        f"В БД нет записей для user {user_id}, отправляем новое изображение"
                    )

            # Отправляем новое изображение только если нужно
            if should_send_new_image:
                # Rate limiting - не чаще 1 раза в 2 секунды
                chat_id = query.message.chat_id
                now = time.time()
                if user_id in self._last_command_time:
                    time_passed = now - self._last_command_time[user_id]
                    if time_passed < 2:
                        wait_time = int(2 - time_passed)
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"⏳ Подождите {wait_time} секунд перед следующим запросом.",
                        )
                        logger.warning(
                            f"Rate limit для user_id={user_id}, осталось {wait_time}с"
                        )
                        return

                self._last_command_time[user_id] = now

                # Отправка сообщения о загрузке
                loading_msg = await context.bot.send_message(
                    chat_id=chat_id, text="🔄 Загружаю следующее фото..."
                )

                # Отправка следующего случайного фото через photo_sender
                if self.photo_sender:
                    success = await self.photo_sender.send_random_photo(
                        chat_id, user_id, context
                    )

                    # Удаление сообщения о загрузке
                    try:
                        await loading_msg.delete()
                    except Exception as e:
                        logger.warning(f"Не удалось удалить loading сообщение: {e}")

                    if not success:
                        logger.error(
                            f"Не удалось отправить фото после голосования user_id={user_id}"
                        )
                else:
                    logger.warning(
                        "photo_sender не инициализирован, не могу отправить новое фото"
                    )
                    await loading_msg.delete()

        except Exception as e:
            logger.error(
                f"Ошибка при обработке callback голосования: {e}", exc_info=True
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Произошла ошибка при обработке голоса.",
            )
            return False

    async def handle_voted_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        Обработчик callback для уже проголосованных кнопок.
        Просто подтверждаем получение, чтобы callback не висел.

        Args:
            update: Обновление от Telegram
            context: Контекст бота
        """
        query = update.callback_query
        await query.answer("Вы уже проголосовали за это фото", show_alert=False)
