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

            # Если дизлайк и есть информация о галерее, добавляем кнопку исключения
            if vote < 0 and image.gallery_id:
                voted_keyboard.append(
                    [
                        InlineKeyboardButton(
                            "🚫 Исключить галерею",
                            callback_data=f"exclude_gallery_{image.gallery_id}",
                        )
                    ]
                )

            # Обновляем кнопки в сообщении
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

    async def handle_exclude_gallery_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """
        Обработчик callback для исключения галереи из ротации.

        Args:
            update: Обновление от Telegram
            context: Контекст бота
        """
        query = update.callback_query
        user_id = update.effective_user.id

        # Проверка авторизации
        if not self._is_authorized(user_id):
            await query.answer("❌ У вас нет доступа к этому боту.", show_alert=True)
            return

        # Проверяем наличие voting_manager
        if not self.voting_manager:
            await query.answer("⚠️ Система голосования недоступна", show_alert=True)
            return

        # Подтверждаем получение callback
        await query.answer()

        try:
            # Парсим callback data
            callback_data = query.data
            if not callback_data.startswith("exclude_gallery_"):
                logger.error(f"Неверный формат callback_data: {callback_data}")
                return

            # Извлекаем gallery_id
            gallery_id = callback_data.replace("exclude_gallery_", "", 1)
            if not gallery_id:
                logger.error(
                    f"Не удалось извлечь gallery_id из callback_data: {callback_data}"
                )
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="❌ Ошибка: не удалось определить галерею.",
                )
                return

            # Получаем информацию о галерее перед исключением
            gallery_pref = self.database.get_gallery_preference(gallery_id)

            # Если галереи нет в БД, пытаемся получить из StashApp и создать запись
            if not gallery_pref:
                logger.info(
                    f"Галерея {gallery_id} не найдена в БД, пытаемся получить из StashApp"
                )
                try:
                    # Получаем список всех галерей из StashApp
                    all_galleries = await self.stash_client.get_all_galleries_cached()
                    gallery_info = next(
                        (
                            g
                            for g in all_galleries
                            if str(g.get("id")) == str(gallery_id)
                        ),
                        None,
                    )

                    if gallery_info:
                        gallery_title = gallery_info.get("title", "Неизвестная галерея")
                        # Создаем запись в БД
                        self.database.ensure_gallery_exists(gallery_id, gallery_title)
                        logger.info(
                            f"Создана запись для галереи {gallery_id} ({gallery_title}) в БД"
                        )
                        # Получаем обновленную информацию
                        gallery_pref = self.database.get_gallery_preference(gallery_id)
                    else:
                        logger.error(f"Галерея {gallery_id} не найдена в StashApp")
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text="❌ Галерея не найдена в StashApp.",
                        )
                        return
                except Exception as e:
                    logger.error(
                        f"Ошибка при получении галереи из StashApp: {e}", exc_info=True
                    )
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text="❌ Ошибка при получении информации о галерее.",
                    )
                    return

            if not gallery_pref:
                logger.error(f"Галерея {gallery_id} не найдена в базе данных")
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="❌ Галерея не найдена в базе данных.",
                )
                return

            gallery_title = gallery_pref.get("gallery_title", "Неизвестная галерея")

            # Получаем статистику галереи
            gallery_stats = self.database.get_gallery_statistics(gallery_id)
            if not gallery_stats:
                gallery_stats = {
                    "total_images": 0,
                    "positive_votes": 0,
                    "negative_votes": 0,
                    "negative_percentage": 0.0,
                }

            # Получаем вес галереи
            gallery_weight = self.database.get_gallery_weight(gallery_id)
            if gallery_weight is None:
                gallery_weight = 0.0

            # Исключаем галерею в БД
            success = self.database.exclude_gallery(gallery_id)
            if not success:
                logger.error(f"Не удалось исключить галерею {gallery_id}")
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"❌ Не удалось исключить галерею '{gallery_title}'.",
                )
                return

            # Добавляем тег exclude_gallery в StashApp
            try:
                stash_success = await self.stash_client.add_tag_to_gallery(
                    gallery_id, "exclude_gallery"
                )
                if stash_success:
                    logger.info(
                        f"Тег exclude_gallery добавлен к галерее {gallery_id} в StashApp"
                    )
                else:
                    logger.warning(
                        f"Галерея {gallery_id} исключена в БД, но не удалось добавить тег в StashApp"
                    )
            except Exception as e:
                logger.error(
                    f"Ошибка при добавлении тега к галерее в StashApp: {e}",
                    exc_info=True,
                )
                # Не прерываем выполнение, так как БД уже обновлена

            # Инвалидируем кэш весов
            self.voting_manager.invalidate_weights_cache()

            # Получаем изображение из кэша для обновления подписи
            image = self._last_sent_images.get(user_id)
            if image and image.gallery_id == gallery_id:
                # Определяем, было ли изображение предзагружено из служебного канала
                cached_file_id = self.database.get_file_id(
                    image.id, use_high_quality=True
                )
                is_preloaded_from_cache = cached_file_id is not None

                # Формируем обычную подпись (без уведомления о пороге)
                new_caption = self.caption_formatter.format_caption(
                    image, is_preloaded_from_cache
                )

                # Проверяем текущую клавиатуру, чтобы сохранить состояние кнопок голосования
                current_keyboard = []
                if (
                    query.message.reply_markup
                    and query.message.reply_markup.inline_keyboard
                ):
                    # Копируем только кнопки голосования (не кнопку исключения)
                    for row in query.message.reply_markup.inline_keyboard:
                        new_row = []
                        for btn in row:
                            # Сохраняем только кнопки голосования, создавая новые объекты
                            if btn.callback_data and (
                                btn.callback_data.startswith("vote_")
                                or btn.callback_data.startswith("voted_")
                            ):
                                new_row.append(
                                    InlineKeyboardButton(
                                        text=btn.text,
                                        callback_data=btn.callback_data,
                                    )
                                )
                        if new_row:
                            current_keyboard.append(new_row)

                # Если не нашли кнопки голосования, создаем стандартные
                if not current_keyboard:
                    current_keyboard = [
                        [
                            InlineKeyboardButton(
                                "👍",
                                callback_data=f"vote_up_{image.id}",
                            ),
                            InlineKeyboardButton(
                                "👎",
                                callback_data=f"vote_down_{image.id}",
                            ),
                        ]
                    ]

                # Пытаемся обновить подпись и клавиатуру
                try:
                    await query.edit_message_caption(
                        caption=new_caption,
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(current_keyboard),
                    )
                except Exception as e:
                    logger.warning(f"Не удалось обновить подпись сообщения: {e}")
                    # Если не удалось обновить подпись, просто обновляем клавиатуру
                    try:
                        await query.edit_message_reply_markup(
                            reply_markup=InlineKeyboardMarkup(current_keyboard)
                        )
                    except Exception as e2:
                        logger.warning(f"Не удалось обновить клавиатуру: {e2}")

            # Формируем сообщение подтверждения
            negative_votes = gallery_stats.get("negative_votes", 0)
            total_images = gallery_stats.get("total_images", 0)
            negative_percentage = gallery_stats.get("negative_percentage", 0.0)

            # Форматируем дату исключения
            from datetime import datetime

            excluded_date = datetime.now().strftime("%Y-%m-%d")

            confirmation_message = (
                f'✅ Галерея "{gallery_title}" исключена из ротации!\n\n'
                f"• Статистика сохранена: {negative_votes}/{total_images} "
                f"(-{negative_percentage:.1f}%)\n"
                f"• Вес: {gallery_weight:.3f}\n"
                f"• Исключена: {excluded_date}\n\n"
                f"Используйте /excluded для просмотра исключенных галерей."
            )

            # Отправляем подтверждающее сообщение
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=confirmation_message,
                parse_mode="HTML",
            )

            logger.info(
                f"Галерея '{gallery_title}' (ID: {gallery_id}) исключена пользователем {user_id}"
            )

        except Exception as e:
            logger.error(
                f"Ошибка при обработке callback исключения галереи: {e}", exc_info=True
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Произошла ошибка при исключении галереи.",
            )
