"""Обработка голосования."""

import logging
from typing import TYPE_CHECKING, Any, Optional

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
        check_authorization=None,
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
            check_authorization: Функция проверки авторизации (опционально)
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
        self.check_authorization = check_authorization

    def _is_authorized(self, user_id: int) -> bool:
        """
        Проверка авторизации пользователя.

        Args:
            user_id: Telegram ID пользователя

        Returns:
            bool: True если пользователь авторизован
        """
        return user_id in self.config.telegram.allowed_user_ids

    def _parse_vote_callback_data(self, callback_data: str) -> tuple[str, str] | None:
        """
        Парсинг callback data для голосования.

        Args:
            callback_data: Данные callback

        Returns:
            Tuple[vote_type, image_id] или None при ошибке
        """
        if not callback_data.startswith("vote_"):
            return None

        parts = callback_data.split("_")
        if len(parts) != 3:
            logger.error(f"Неверный формат callback_data: {callback_data}")
            return None

        vote_type = parts[1]  # "up" или "down"
        image_id = parts[2]
        return (vote_type, image_id)

    async def _get_image_for_vote(
        self, user_id: int, image_id: str
    ) -> StashImage | None:
        """
        Получение изображения для голосования (из кэша или API).

        Args:
            user_id: ID пользователя
            image_id: ID изображения

        Returns:
            StashImage или None при ошибке
        """
        # Получаем изображение из кэша
        image = self._last_sent_images.get(user_id)

        if image and image.id == image_id:
            return image

        # Если изображения нет в кэше, пытаемся получить из StashApp API
        logger.warning(
            f"Изображение {image_id} не найдено в кэше для user {user_id}, пытаемся получить из API"
        )
        image = await self.stash_client.get_image_by_id(image_id)

        if not image:
            logger.error(
                f"Не удалось получить изображение {image_id} из API для user {user_id}"
            )
            return None

        logger.info(f"Изображение {image_id} получено из API для user {user_id}")
        return image

    def _build_vote_response_message(self, result: dict[str, Any], vote: int) -> str:
        """
        Формирование сообщения с результатами голосования.

        Args:
            result: Результат обработки голоса
            vote: Значение голоса (1 или -1)

        Returns:
            Текст сообщения
        """
        vote_emoji = "👍" if vote > 0 else "👎"
        response_parts = [f"{vote_emoji} <b>Ваш голос учтен!</b>"]

        if result["image_rating_updated"]:
            rating = 5 if vote > 0 else 1
            response_parts.append(f"✅ Рейтинг фото обновлен: {rating}/5")

        if result["performers_updated"]:
            performers_str = ", ".join(result["performers_updated"][:3])
            response_parts.append(f"👤 Перформеры обновлены: {performers_str}")

        if result["gallery_updated"]:
            response_parts.append(f"📁 Галерея обновлена: {result['gallery_updated']}")

        if result["gallery_rating_updated"]:
            response_parts.append("⭐ Рейтинг галереи установлен в Stash!")

        if result["error"]:
            response_parts.append(f"⚠️ Ошибка: {result['error']}")

        return "\n".join(response_parts)

    def _create_voted_keyboard(
        self, image_id: str, vote: int, image: StashImage
    ) -> InlineKeyboardMarkup:
        """
        Создание клавиатуры с отмеченным голосом.

        Args:
            image_id: ID изображения
            vote: Значение голоса (1 или -1)
            image: Объект изображения

        Returns:
            InlineKeyboardMarkup с кнопками голосования
        """
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

        return InlineKeyboardMarkup(voted_keyboard)

    def _should_send_new_image(self, user_id: int, image_id: str) -> bool:
        """
        Проверка, нужно ли отправлять новое изображение после голосования.

        Args:
            user_id: ID пользователя
            image_id: ID изображения, за которое проголосовали

        Returns:
            True если нужно отправить новое изображение
        """
        # Проверяем, является ли изображение последним (сначала кэш, потом БД)
        last_image_id = self._last_sent_image_id.get(user_id)

        if last_image_id and image_id == last_image_id:
            logger.info(
                f"Изображение {image_id} является последним (из кэша), отправляем новое изображение"
            )
            return True

        # Кэш пуст или не совпадает - проверяем БД для надежности
        last_photo = self.database.get_last_sent_photo_for_user(user_id)
        if last_photo:
            last_photo_image_id = last_photo[0]
            # Обновляем кэш для будущих проверок
            self._last_sent_image_id[user_id] = last_photo_image_id

            if image_id == last_photo_image_id:
                logger.info(
                    f"Изображение {image_id} является последним (из БД), отправляем новое изображение"
                )
                return True
            else:
                logger.info(
                    f"Изображение {image_id} не является последним (последнее: {last_photo_image_id}), не отправляем новое изображение"
                )
                return False

        # В БД нет записей для пользователя - отправляем новое
        logger.info(
            f"В БД нет записей для user {user_id}, отправляем новое изображение"
        )
        return True

    async def _send_next_image_after_vote(
        self, chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Отправка следующего изображения после голосования.

        Args:
            chat_id: ID чата
            user_id: ID пользователя
            context: Контекст бота
        """
        # Отправка сообщения о загрузке
        loading_msg = await context.bot.send_message(
            chat_id=chat_id, text="🔄 Загружаю следующее фото..."
        )

        # Отправка следующего случайного фото через photo_sender
        if not self.photo_sender:
            logger.warning(
                "photo_sender не инициализирован, не могу отправить новое фото"
            )
            await loading_msg.delete()
            return

        success = await self.photo_sender.send_random_photo(chat_id, user_id, context)

        # Удаление сообщения о загрузке
        try:
            await loading_msg.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить loading сообщение: {e}")

        if not success:
            logger.error(
                f"Не удалось отправить фото после голосования user_id={user_id}"
            )

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

        # Проверка авторизации
        if not await self.check_authorization(update, context):
            return

        user_id = update.effective_user.id

        # Проверяем наличие voting_manager
        if not self.voting_manager:
            await query.answer("⚠️ Система голосования недоступна")
            return

        # Подтверждаем получение callback
        await query.answer()

        try:
            # Парсим callback data
            parsed = self._parse_vote_callback_data(query.data)
            if not parsed:
                return

            vote_type, image_id = parsed
            vote = 1 if vote_type == "up" else -1

            # Получаем изображение
            image = await self._get_image_for_vote(user_id, image_id)
            if not image:
                await query.edit_message_reply_markup(reply_markup=None)
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="⚠️ Не удалось обработать голос. Попробуйте запросить новое фото.",
                )
                return

            # Обрабатываем голос
            logger.info(
                f"Обработка голоса: user={user_id}, image={image_id}, vote={vote}"
            )
            result = await self.voting_manager.process_vote(image, vote)

            # Формируем и отправляем сообщение с результатами
            response_message = self._build_vote_response_message(result, vote)
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=response_message,
                parse_mode="HTML",
            )

            # Обновляем кнопки
            voted_keyboard = self._create_voted_keyboard(image_id, vote, image)
            await query.edit_message_reply_markup(reply_markup=voted_keyboard)

            # Инвалидация кэша фильтрации после голосования
            self.voting_manager.invalidate_filtering_cache()

            # Отправляем новое изображение, если нужно
            if self._should_send_new_image(user_id, image_id):
                await self._send_next_image_after_vote(
                    query.message.chat_id, user_id, context
                )

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

    def _parse_exclude_gallery_callback_data(self, callback_data: str) -> str | None:
        """
        Парсинг callback data для исключения галереи.

        Args:
            callback_data: Данные callback

        Returns:
            gallery_id или None при ошибке
        """
        if not callback_data.startswith("exclude_gallery_"):
            logger.error(f"Неверный формат callback_data: {callback_data}")
            return None

        gallery_id = callback_data.replace("exclude_gallery_", "", 1)
        if not gallery_id:
            logger.error(
                f"Не удалось извлечь gallery_id из callback_data: {callback_data}"
            )
            return None

        return gallery_id

    async def _ensure_gallery_in_db(
        self, gallery_id: str, chat_id: int
    ) -> tuple[str, dict[str, Any]] | None:
        """
        Обеспечение наличия галереи в БД (создание при необходимости).

        Args:
            gallery_id: ID галереи
            chat_id: ID чата для отправки сообщений об ошибках

        Returns:
            Tuple[gallery_id, gallery_pref] или None при ошибке
        """
        gallery_pref = self.database.get_gallery_preference(gallery_id)
        if gallery_pref:
            return (gallery_id, gallery_pref)

        # Если галереи нет в БД, пытаемся получить из StashApp и создать запись
        logger.info(
            f"Галерея {gallery_id} не найдена в БД, пытаемся получить из StashApp"
        )
        try:
            all_galleries = await self.stash_client.get_all_galleries_cached()
            gallery_info = next(
                (g for g in all_galleries if str(g.get("id")) == str(gallery_id)),
                None,
            )

            if not gallery_info:
                logger.error(f"Галерея {gallery_id} не найдена в StashApp")
                return None

            # Используем ID из StashApp для консистентности
            stash_gallery_id = str(gallery_info.get("id"))
            gallery_title = gallery_info.get("title") or "Неизвестная галерея"

            # Создаем запись в БД
            created = self.database.ensure_gallery_exists(
                stash_gallery_id, gallery_title
            )

            # Получаем информацию о галерее после создания
            gallery_pref = self.database.get_gallery_preference(stash_gallery_id)

            if not gallery_pref:
                logger.error(
                    f"Галерея {stash_gallery_id} не найдена в БД после создания записи"
                )
                return None

            if created:
                logger.info(
                    f"Создана запись для галереи {stash_gallery_id} ({gallery_title}) в БД"
                )
            else:
                logger.info(
                    f"Галерея {stash_gallery_id} ({gallery_title}) уже существует в БД"
                )

            return (stash_gallery_id, gallery_pref)

        except Exception as e:
            logger.error(
                f"Ошибка при получении галереи из StashApp: {e}", exc_info=True
            )
            return None

    async def _exclude_gallery_in_stash(self, gallery_id: str) -> bool:
        """
        Исключение галереи в StashApp (добавление тега).

        Args:
            gallery_id: ID галереи

        Returns:
            True если успешно
        """
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
            return stash_success
        except Exception as e:
            logger.error(
                f"Ошибка при добавлении тега к галерее в StashApp: {e}",
                exc_info=True,
            )
            return False

    def _extract_voting_keyboard(
        self, reply_markup: InlineKeyboardMarkup | None, image_id: str
    ) -> list[list[InlineKeyboardButton]]:
        """
        Извлечение кнопок голосования из существующей клавиатуры.

        Args:
            reply_markup: Существующая клавиатура
            image_id: ID изображения для создания новых кнопок при необходимости

        Returns:
            Список строк с кнопками голосования
        """
        current_keyboard = []
        if reply_markup and reply_markup.inline_keyboard:
            # Копируем только кнопки голосования (не кнопку исключения)
            for row in reply_markup.inline_keyboard:
                new_row = []
                for btn in row:
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
                        callback_data=f"vote_up_{image_id}",
                    ),
                    InlineKeyboardButton(
                        "👎",
                        callback_data=f"vote_down_{image_id}",
                    ),
                ]
            ]

        return current_keyboard

    async def _update_message_after_exclusion(
        self,
        query,
        user_id: int,
        gallery_id: str,
    ) -> None:
        """
        Обновление сообщения после исключения галереи (подпись и клавиатура).

        Args:
            query: Callback query
            user_id: ID пользователя
            gallery_id: ID галереи
        """
        image = self._last_sent_images.get(user_id)
        if not image or image.gallery_id != gallery_id:
            return

        # Определяем, было ли изображение предзагружено из служебного канала
        cached_file_id = self.database.get_file_id(image.id, use_high_quality=True)
        is_preloaded_from_cache = cached_file_id is not None

        # Формируем обычную подпись (без уведомления о пороге)
        new_caption = self.caption_formatter.format_caption(
            image, is_preloaded_from_cache
        )

        # Извлекаем кнопки голосования
        current_keyboard = self._extract_voting_keyboard(
            query.message.reply_markup, image.id
        )

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

    def _build_exclusion_confirmation_message(
        self,
        gallery_title: str,
        gallery_stats: dict[str, Any],
        gallery_weight: float,
    ) -> str:
        """
        Формирование сообщения подтверждения исключения галереи.

        Args:
            gallery_title: Название галереи
            gallery_stats: Статистика галереи
            gallery_weight: Вес галереи

        Returns:
            Текст сообщения подтверждения
        """
        from datetime import datetime

        negative_votes = gallery_stats.get("negative_votes", 0)
        total_images = gallery_stats.get("total_images", 0)
        negative_percentage = gallery_stats.get("negative_percentage", 0.0)
        excluded_date = datetime.now().strftime("%Y-%m-%d")

        return (
            f'✅ Галерея "{gallery_title}" исключена из ротации!\n\n'
            f"• Статистика сохранена: {negative_votes}/{total_images} "
            f"(-{negative_percentage:.1f}%)\n"
            f"• Вес: {gallery_weight:.3f}\n"
            f"• Исключена: {excluded_date}\n\n"
            f"Используйте /excluded для просмотра исключенных галерей."
        )

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

        # Проверка авторизации
        if not await self.check_authorization(update, context):
            return

        user_id = update.effective_user.id

        # Проверяем наличие voting_manager
        if not self.voting_manager:
            await query.answer("⚠️ Система голосования недоступна", show_alert=True)
            return

        # Подтверждаем получение callback
        await query.answer()

        try:
            # Парсим callback data
            gallery_id = self._parse_exclude_gallery_callback_data(query.data)
            if not gallery_id:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="❌ Ошибка: не удалось определить галерею.",
                )
                return

            # Обеспечиваем наличие галереи в БД
            gallery_result = await self._ensure_gallery_in_db(
                gallery_id, query.message.chat_id
            )
            if not gallery_result:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="❌ Ошибка при получении информации о галерее.",
                )
                return

            gallery_id, gallery_pref = gallery_result
            gallery_title = gallery_pref.get("gallery_title", "Неизвестная галерея")

            # Получаем статистику и вес галереи
            gallery_stats = self.database.get_gallery_statistics(gallery_id)
            if not gallery_stats:
                gallery_stats = {
                    "total_images": 0,
                    "positive_votes": 0,
                    "negative_votes": 0,
                    "negative_percentage": 0.0,
                }

            gallery_weight = self.database.get_gallery_weight(gallery_id) or 0.0

            # Исключаем галерею в БД
            success = self.database.exclude_gallery(gallery_id)
            if not success:
                logger.error(f"Не удалось исключить галерею {gallery_id}")
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"❌ Не удалось исключить галерею '{gallery_title}'.",
                )
                return

            # Добавляем тег в StashApp (не критично, если не удалось)
            await self._exclude_gallery_in_stash(gallery_id)

            # Инвалидируем кэш весов
            self.voting_manager.invalidate_weights_cache()

            # Обновляем сообщение (подпись и клавиатуру)
            await self._update_message_after_exclusion(query, user_id, gallery_id)

            # Отправляем подтверждающее сообщение
            confirmation_message = self._build_exclusion_confirmation_message(
                gallery_title, gallery_stats, gallery_weight
            )
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
