"""Обработчики команд Telegram бота."""

import asyncio
import logging
import time
from typing import Optional, Dict, Any, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.error import TelegramError

from bot.config import BotConfig
from bot.stash_client import StashClient, StashImage, select_gallery_by_weight
from bot.database import Database
from bot.performance import PerformanceTimer

logger = logging.getLogger(__name__)


class TelegramHandler:
    """Класс для обработки команд Telegram бота."""
    
    def __init__(
        self,
        config: BotConfig,
        stash_client: StashClient,
        database: Database,
        voting_manager = None  # Type hint avoided to prevent circular import
    ):
        """
        Инициализация обработчика.
        
        Args:
            config: Конфигурация бота
            stash_client: Клиент StashApp
            database: База данных
            voting_manager: Менеджер голосования (опционально)
        """
        self.config = config
        self.stash_client = stash_client
        self.database = database
        self.voting_manager = voting_manager
        self.application: Optional[Application] = None
        self._last_command_time: Dict[int, float] = {}  # Rate limiting
        self._last_sent_images: Dict[int, StashImage] = {}  # Кэш последних отправленных изображений
        self._prefetched_image: Optional[Dict[str, Any]] = None  # Предзагруженное изображение {image, image_data}
        self._prefetch_lock: asyncio.Lock = asyncio.Lock()  # Lock для синхронизации предзагрузки
    
    def _is_authorized(self, user_id: int) -> bool:
        """
        Проверка авторизации пользователя.
        
        Args:
            user_id: Telegram ID пользователя
            
        Returns:
            bool: True если пользователь авторизован
        """
        return user_id in self.config.telegram.allowed_user_ids
    
    def _get_persistent_keyboard(self) -> ReplyKeyboardMarkup:
        """
        Создание постоянной клавиатуры с кнопкой Random.
        
        Returns:
            ReplyKeyboardMarkup: Клавиатура с кнопкой Random
        """
        keyboard = [[KeyboardButton("💕 Random")]]
        return ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            one_time_keyboard=False
        )
    
    async def _send_random_photo(
        self,
        chat_id: int,
        user_id: Optional[int] = None,
        context: Optional[ContextTypes.DEFAULT_TYPE] = None
    ) -> bool:
        """
        Отправка случайного фото.
        
        Args:
            chat_id: ID чата для отправки
            user_id: ID пользователя (для статистики)
            context: Контекст бота (опционально)
            
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
            
            if self._prefetched_image:
                # Проверяем, что предзагруженное изображение еще актуально
                recent_ids = self.database.get_recent_image_ids(
                    self.config.history.avoid_recent_days
                )
                prefetched_image = self._prefetched_image['image']
                
                if prefetched_image.id not in recent_ids:
                    logger.info("⚡ Используется предзагруженное изображение")
                    image = prefetched_image
                    image_data = self._prefetched_image['image_data']
                    self._prefetched_image = None  # Очистка кэша
                    used_prefetch = True
                    timer.checkpoint("Use prefetched image")
                else:
                    logger.info("⚠️ Предзагруженное изображение устарело, загружаем новое")
                    self._prefetched_image = None  # Очистка устаревшего кэша
                    timer.checkpoint("Clear stale cache")
            
            # Если нет предзагруженного изображения, загружаем обычным способом
            if not image or not image_data:
                # Получение списка недавно отправленных ID
                recent_ids = self.database.get_recent_image_ids(
                    self.config.history.avoid_recent_days
                )
                timer.checkpoint("Get recent IDs from DB")
                
                logger.info(f"Запрос случайного фото (исключая {len(recent_ids)} недавних)")
                
                # Получение списка фильтров для метрик
                if self.voting_manager:
                    timer.checkpoint("Get filtering lists from DB")
                
                # Получение случайного изображения с учетом предпочтений
                image = await self._get_random_image(recent_ids)
                timer.checkpoint("Get random image")
                
                if not image:
                    logger.error("Не удалось получить случайное изображение")
                    if context:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text="❌ Не удалось получить изображение из StashApp. Попробуйте позже."
                        )
                    return False
                
                # Скачивание изображения
                image_data = await self.stash_client.download_image(image.image_url)
                timer.checkpoint("Download image")
                
                if not image_data:
                    logger.error(f"Не удалось скачать изображение {image.id}")
                    if context:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text="❌ Не удалось скачать изображение. Попробуйте позже."
                        )
                    return False
            
            # Формирование подписи
            caption = self._format_caption(image)
            
            # Создание кнопок для голосования
            keyboard = [
                [
                    InlineKeyboardButton("👍", callback_data=f"vote_up_{image.id}"),
                    InlineKeyboardButton("👎", callback_data=f"vote_down_{image.id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Отправка фото
            send_start = time.perf_counter()
            if context:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=image_data,
                    caption=caption,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            else:
                # Для планировщика используем application
                if self.application:
                    await self.application.bot.send_photo(
                        chat_id=chat_id,
                        photo=image_data,
                        caption=caption,
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
            timer.checkpoint("Send to Telegram")
            
            # Сохранение изображения в кэш для обработки голосования
            if user_id:
                self._last_sent_images[user_id] = image
            
            # Сохранение в базу данных
            self.database.add_sent_photo(
                image_id=image.id,
                user_id=user_id,
                title=image.title
            )
            timer.checkpoint("Save to database")
            
            # Запуск фоновой предзагрузки следующего изображения
            # Только если была команда от пользователя (не планировщик)
            if user_id:
                asyncio.create_task(self._prefetch_next_image())
                logger.debug("🔄 Запущена фоновая предзагрузка следующего изображения")
            
            timer.end()
            logger.info(f"Фото успешно отправлено: {image.id} {'(использована предзагрузка)' if used_prefetch else ''}")
            return True
        
        except TelegramError as e:
            logger.error(f"Ошибка Telegram при отправке фото: {e}")
            timer.end()
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при отправке фото: {e}")
            timer.end()
            return False
    
    async def _get_random_image(self, exclude_ids: List[str]) -> Optional[StashImage]:
        """
        Получение случайного изображения с учетом фильтров и предпочтений.
        
        Использует взвешенный случайный выбор галереи на основе весов.
        При отсутствии весов или ошибках использует fallback на старый метод.
        
        Args:
            exclude_ids: Список ID изображений для исключения
            
        Returns:
            Optional[StashImage]: Случайное изображение или None
        """
        # Если нет voting_manager, используем старый метод
        if not self.voting_manager:
            return await self.stash_client.get_random_image_with_retry(
                exclude_ids=exclude_ids,
                max_retries=5
            )
        
        # Пытаемся использовать взвешенный выбор галереи
        try:
            # Получаем веса активных галерей (используем кэшированную версию)
            weights_dict = self.voting_manager.get_cached_gallery_weights()
            
            # Проверяем, есть ли веса и они не пустые
            if weights_dict:
                # Выбираем галерею взвешенным случайным выбором
                selected_gallery_id = select_gallery_by_weight(weights_dict)
                
                if selected_gallery_id:
                    # Получаем случайное изображение из выбранной галереи с учетом приоритетов по рейтингу
                    image = await self.stash_client.get_random_image_from_gallery_weighted(
                        gallery_id=selected_gallery_id,
                        exclude_ids=exclude_ids
                    )
                    
                    if image:
                        logger.debug(f"Изображение получено из галереи {selected_gallery_id} (взвешенный выбор с приоритетами по рейтингу)")
                        return image
                    else:
                        logger.warning(f"🔄 Fallback level 1: Не удалось получить изображение из галереи {selected_gallery_id} (все категории пусты), используем старый метод с фильтрацией")
                else:
                    logger.warning("🔄 Fallback level 1: Не удалось выбрать галерею взвешенным выбором, используем старый метод с фильтрацией")
            else:
                logger.warning("🔄 Fallback level 1: Веса галерей отсутствуют или пусты, используем старый метод с фильтрацией")
        except Exception as e:
            logger.warning(f"🔄 Fallback level 1: Ошибка при взвешенном выборе галереи: {e}, используем старый метод с фильтрацией", exc_info=True)
        
        # Fallback level 1: используем старый метод с фильтрацией
        try:
            filtering_lists = self.voting_manager.get_filtering_lists()
            image = await self.stash_client.get_random_image_weighted(
                exclude_ids=exclude_ids,
                blacklisted_performers=filtering_lists['blacklisted_performers'],
                blacklisted_galleries=filtering_lists['blacklisted_galleries'],
                whitelisted_performers=filtering_lists['whitelisted_performers'],
                whitelisted_galleries=filtering_lists['whitelisted_galleries'],
                max_retries=5
            )
            if image:
                logger.info("✅ Fallback level 1 успешен: изображение получено через старый метод с фильтрацией")
                return image
            else:
                logger.warning("🔄 Fallback level 2: Старый метод с фильтрацией не вернул изображение, используем базовый метод")
        except Exception as e:
            logger.warning(f"🔄 Fallback level 2: Ошибка при fallback методе с фильтрацией: {e}, используем базовый метод", exc_info=True)
        
        # Fallback level 2: базовый метод без фильтрации
        logger.info("🔄 Fallback level 2: Используем базовый метод без фильтрации")
        return await self.stash_client.get_random_image_with_retry(
            exclude_ids=exclude_ids,
            max_retries=5
        )
    
    def _format_progress_bar(self, negative_votes: int, total_images: int, negative_percentage: Optional[float] = None) -> str:
        """
        Форматирование прогресс-бара для отображения процента минусов.
        
        Args:
            negative_votes: Количество отрицательных голосов
            total_images: Общее количество изображений в галерее
            negative_percentage: Процент минусов (опционально, если не указан - вычисляется)
            
        Returns:
            str: Отформатированный прогресс-бар или пустая строка если total_images == 0
        """
        if total_images == 0:
            return ""
        
        # Защита от некорректных данных (negative_votes не может быть больше total_images)
        negative_votes = max(0, min(negative_votes, total_images))
        
        # Расчет процента минусов (используем переданный или вычисляем)
        if negative_percentage is None:
            negative_percentage = (negative_votes / total_images) * 100.0
        else:
            # Ограничиваем процент 0-100 для безопасности
            negative_percentage = max(0.0, min(100.0, negative_percentage))
        
        # Расчет заполненности прогресс-бара (10 символов, каждый = 10%)
        filled = int((negative_votes / total_images) * 10)
        filled = max(0, min(10, filled))  # Ограничение 0-10
        
        # Формирование прогресс-бара
        filled_chars = "█" * filled
        empty_chars = "░" * (10 - filled)
        progress_bar = f"[{filled_chars}{empty_chars}]"
        
        # Цветовая индикация
        color_emoji = "🔴" if negative_percentage >= 33.0 else "🟢"
        
        # Форматирование: [██████░░░░] 60% (12/20)
        return f"{color_emoji} {progress_bar} {negative_percentage:.0f}% ({negative_votes}/{total_images})"
    
    def _format_caption(self, image: StashImage) -> str:
        """
        Форматирование подписи к изображению.
        
        Args:
            image: Объект изображения
            
        Returns:
            str: Отформатированная подпись
        """
        caption_parts = []
        
        if image.title and image.title != 'Без названия':
            caption_parts.append(f"<b>{image.title}</b>")
        
        if image.rating is not None and image.rating > 0:
            stars = "⭐" * (image.rating // 20)  # Конвертация rating100 в звезды (0-5)
            caption_parts.append(f"Рейтинг: {stars} ({image.rating}/100)")
        
        if image.tags:
            tags_str = ", ".join([f"#{tag.replace(' ', '_')}" for tag in image.tags[:5]])
            caption_parts.append(f"Теги: {tags_str}")
        
        # Добавление прогресс-бара, если есть статистика галереи
        if image.gallery_id:
            try:
                gallery_stats = self.database.get_gallery_statistics(image.gallery_id)
                if gallery_stats and gallery_stats.get('total_images', 0) > 0:
                    progress_bar = self._format_progress_bar(
                        negative_votes=gallery_stats.get('negative_votes', 0),
                        total_images=gallery_stats.get('total_images', 0),
                        negative_percentage=gallery_stats.get('negative_percentage')  # Используем готовое значение из БД
                    )
                    if progress_bar:  # Проверка все еще нужна на случай edge cases
                        caption_parts.append(f"Прогресс: {progress_bar}")
            except Exception as e:
                logger.warning(f"Ошибка при получении статистики галереи {image.gallery_id}: {e}")
        
        return "\n".join(caption_parts) if caption_parts else "📸 Случайное фото"
    
    async def _prefetch_next_image(self):
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
                image = await self._get_random_image(recent_ids)
                
                if not image:
                    logger.warning("⚠️ Не удалось предзагрузить изображение")
                    return
                
                # Скачивание изображения
                image_data = await self.stash_client.download_image(image.image_url)
                
                if not image_data:
                    logger.warning(f"⚠️ Не удалось скачать изображение {image.id} для предзагрузки")
                    return
                
                # Сохранение в кэш
                self._prefetched_image = {
                    'image': image,
                    'image_data': image_data
                }
                
                logger.info(f"✅ Предзагружено изображение {image.id} ({len(image_data) / 1024:.1f} KB)")
                
            except Exception as e:
                logger.error(f"❌ Ошибка при предзагрузке изображения: {e}")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start."""
        user_id = update.effective_user.id
        
        if not self._is_authorized(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этому боту.")
            logger.warning(f"Неавторизованная попытка доступа: user_id={user_id}")
            return
        
        welcome_message = (
            "👋 <b>Привет! Я бот для StashApp.</b>\n\n"
            "Доступные команды:\n"
            "/random - Получить случайное фото\n"
            "/stats - Показать статистику\n"
            "/preferences - Показать предпочтения\n"
            "/help - Показать эту справку\n\n"
            "📅 Автоматическая отправка: "
            f"{'включена ✅' if self.config.scheduler.enabled else 'выключена ❌'}"
        )
        
        await update.message.reply_text(
            welcome_message, 
            parse_mode='HTML',
            reply_markup=self._get_persistent_keyboard()
        )
        logger.info(f"Команда /start от user_id={user_id}")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help."""
        user_id = update.effective_user.id
        
        if not self._is_authorized(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этому боту.")
            return
        
        help_message = (
            "<b>📖 Справка по боту StashApp</b>\n\n"
            "<b>Команды:</b>\n"
            "/random - Получить случайное фото из коллекции\n"
            "/stats - Показать статистику отправленных фото\n"
            "/preferences - Показать ваши предпочтения\n"
            "/help - Показать эту справку\n\n"
            "<b>О боте:</b>\n"
            "Бот отправляет случайные фотографии из вашей StashApp коллекции.\n"
            f"Фото не повторяются в течение {self.config.history.avoid_recent_days} дней.\n\n"
            "<b>Голосование:</b>\n"
            "Под каждым фото есть кнопки 👍 и 👎.\n"
            "• 👍 - ставит рейтинг 5/5 фото и запоминает перформеров/галерею\n"
            "• 👎 - ставит рейтинг 1/5 и фильтрует похожий контент\n"
            "После 5+ голосов галерея получает средний рейтинг автоматически.\n\n"
            f"<b>Расписание:</b> {self.config.scheduler.cron if self.config.scheduler.enabled else 'Не настроено'}"
        )
        
        await update.message.reply_text(
            help_message, 
            parse_mode='HTML',
            reply_markup=self._get_persistent_keyboard()
        )
        logger.info(f"Команда /help от user_id={user_id}")
    
    async def random_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /random."""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        if not self._is_authorized(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этому боту.")
            return
        
        # Rate limiting - не чаще 1 раза в 2 секунды
        now = time.time()
        if user_id in self._last_command_time:
            time_passed = now - self._last_command_time[user_id]
            if time_passed < 2:
                wait_time = int(2 - time_passed)
                await update.message.reply_text(
                    f"⏳ Подождите {wait_time} секунд перед следующим запросом.",
                    reply_markup=self._get_persistent_keyboard()
                )
                logger.warning(f"Rate limit для user_id={user_id}, осталось {wait_time}с")
                return
        
        self._last_command_time[user_id] = now
        
        logger.info(f"Команда /random от user_id={user_id}")
        
        # Отправка сообщения о загрузке
        loading_msg = await update.message.reply_text(
            "🔄 Загружаю случайное фото...",
            reply_markup=self._get_persistent_keyboard()
        )
        
        # Отправка случайного фото
        success = await self._send_random_photo(chat_id, user_id, context)
        
        # Удаление сообщения о загрузке
        await loading_msg.delete()
        
        if not success:
            logger.error(f"Не удалось отправить фото user_id={user_id}")
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений (кнопка Random)."""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        text = update.message.text
        
        if not self._is_authorized(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этому боту.")
            return
        
        # Обработка кнопки Random
        if text == "💕 Random":
            # Rate limiting - не чаще 1 раза в 2 секунды
            now = time.time()
            if user_id in self._last_command_time:
                time_passed = now - self._last_command_time[user_id]
                if time_passed < 2:
                    wait_time = int(2 - time_passed)
                    await update.message.reply_text(
                        f"⏳ Подождите {wait_time} секунд перед следующим запросом.",
                        reply_markup=self._get_persistent_keyboard()
                    )
                    logger.warning(f"Rate limit для user_id={user_id}, осталось {wait_time}с")
                    return
            
            self._last_command_time[user_id] = now
            
            logger.info(f"Кнопка Random от user_id={user_id}")
            
            # Отправка сообщения о загрузке
            loading_msg = await update.message.reply_text(
                "🔄 Загружаю случайное фото...",
                reply_markup=self._get_persistent_keyboard()
            )
            
            # Отправка случайного фото
            success = await self._send_random_photo(chat_id, user_id, context)
            
            # Удаление сообщения о загрузке
            await loading_msg.delete()
            
            if not success:
                logger.error(f"Не удалось отправить фото user_id={user_id}")
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stats."""
        user_id = update.effective_user.id
        
        if not self._is_authorized(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этому боту.")
            return
        
        logger.info(f"Команда /stats от user_id={user_id}")
        
        # Получение статистики
        total_sent = self.database.get_total_sent_count()
        user_sent = self.database.get_user_sent_count(user_id)
        last_photo = self.database.get_last_sent_photo()
        votes_stats = self.database.get_total_votes_count()
        
        stats_message = (
            "<b>📊 Статистика бота</b>\n\n"
            f"📸 Всего отправлено фото: <b>{total_sent}</b>\n"
            f"👤 Отправлено вам: <b>{user_sent}</b>\n"
        )
        
        # Добавление статистики по голосам
        if votes_stats['total'] > 0:
            stats_message += (
                f"\n<b>🗳 Голосование:</b>\n"
                f"Всего голосов: <b>{votes_stats['total']}</b>\n"
                f"👍 Положительных: <b>{votes_stats['positive']}</b>\n"
                f"👎 Отрицательных: <b>{votes_stats['negative']}</b>\n"
            )
        
        if last_photo:
            image_id, sent_at, title = last_photo
            stats_message += f"\n🕐 Последнее фото: {title or 'Без названия'}\n"
            stats_message += f"📅 Дата: {sent_at[:19]}"
        
        await update.message.reply_text(
            stats_message, 
            parse_mode='HTML',
            reply_markup=self._get_persistent_keyboard()
        )
    
    async def preferences_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /preferences."""
        user_id = update.effective_user.id
        
        if not self._is_authorized(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этому боту.")
            return
        
        if not self.voting_manager:
            await update.message.reply_text("⚠️ Система голосования недоступна.")
            return
        
        logger.info(f"Команда /preferences от user_id={user_id}")
        
        # Получение сводки предпочтений
        summary = self.voting_manager.get_preferences_summary()
        
        prefs_message = "<b>📊 Ваши предпочтения</b>\n\n"
        
        # Топ перформеров
        if summary['top_performers']:
            prefs_message += "<b>👍 Любимые перформеры:</b>\n"
            for i, p in enumerate(summary['top_performers'], 1):
                name = p['performer_name']
                display_name = f"{name[:25]}..." if len(name) > 25 else name
                prefs_message += (
                    f"{i}. {display_name} "
                    f"(👍 {p['positive_votes']} / 👎 {p['negative_votes']}, "
                    f"score: {p['score']:.2f})\n"
                )
            prefs_message += "\n"
        
        # Нелюбимые перформеры
        if summary['worst_performers']:
            prefs_message += "<b>👎 Нелюбимые перформеры:</b>\n"
            for i, p in enumerate(summary['worst_performers'], 1):
                name = p['performer_name']
                display_name = f"{name[:25]}..." if len(name) > 25 else name
                prefs_message += (
                    f"{i}. {display_name} "
                    f"(👍 {p['positive_votes']} / 👎 {p['negative_votes']}, "
                    f"score: {p['score']:.2f})\n"
                )
            prefs_message += "\n"
        
        # Топ галерей
        if summary['top_galleries']:
            prefs_message += "<b>👍 Любимые галереи:</b>\n"
            for i, g in enumerate(summary['top_galleries'], 1):
                title = g['gallery_title']
                display_title = f"{title[:30]}..." if len(title) > 30 else title
                prefs_message += (
                    f"{i}. {display_title} "
                    f"(👍 {g['positive_votes']} / 👎 {g['negative_votes']}, "
                    f"score: {g['score']:.2f})\n"
                )
            prefs_message += "\n"
        
        # Нелюбимые галереи
        if summary['worst_galleries']:
            prefs_message += "<b>👎 Нелюбимые галереи:</b>\n"
            for i, g in enumerate(summary['worst_galleries'], 1):
                title = g['gallery_title']
                display_title = f"{title[:30]}..." if len(title) > 30 else title
                prefs_message += (
                    f"{i}. {display_title} "
                    f"(👍 {g['positive_votes']} / 👎 {g['negative_votes']}, "
                    f"score: {g['score']:.2f})\n"
                )
            prefs_message += "\n"
        
        # Общая статистика
        prefs_message += (
            f"<b>Всего:</b> {summary['total_performers']} перформеров, "
            f"{summary['total_galleries']} галерей"
        )
        
        if not summary['top_performers'] and not summary['worst_performers'] and \
           not summary['top_galleries'] and not summary['worst_galleries']:
            prefs_message += "\n\n💡 <i>Пока нет данных. Начните голосовать за фото!</i>"
        
        await update.message.reply_text(
            prefs_message, 
            parse_mode='HTML',
            reply_markup=self._get_persistent_keyboard()
        )
    
    async def send_scheduled_photo(self, chat_id: int):
        """
        Отправка фото по расписанию.
        
        Args:
            chat_id: ID чата для отправки
        """
        logger.info(f"Отправка запланированного фото в chat_id={chat_id}")
        await self._send_random_photo(chat_id, context=None)
    
    async def handle_vote_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                # Если изображения нет в кэше, пытаемся получить информацию из базы
                logger.warning(f"Изображение {image_id} не найдено в кэше для user {user_id}")
                await query.edit_message_reply_markup(reply_markup=None)
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="⚠️ Не удалось обработать голос. Попробуйте запросить новое фото."
                )
                return
            
            # Обрабатываем голос
            logger.info(f"Обработка голоса: user={user_id}, image={image_id}, vote={vote}")
            result = await self.voting_manager.process_vote(image, vote)
            
            # Формируем сообщение об обновлениях
            vote_emoji = "👍" if vote > 0 else "👎"
            response_parts = [f"{vote_emoji} <b>Ваш голос учтен!</b>"]
            
            if result['image_rating_updated']:
                rating = 5 if vote > 0 else 1
                response_parts.append(f"✅ Рейтинг фото обновлен: {rating}/5")
            
            if result['performers_updated']:
                performers_str = ", ".join(result['performers_updated'][:3])
                response_parts.append(f"👤 Перформеры обновлены: {performers_str}")
            
            if result['gallery_updated']:
                response_parts.append(f"📁 Галерея обновлена: {result['gallery_updated']}")
            
            if result['gallery_rating_updated']:
                response_parts.append(f"⭐ Рейтинг галереи установлен в Stash!")
            
            if result['error']:
                response_parts.append(f"⚠️ Ошибка: {result['error']}")
            
            # Обновляем кнопки (отмечаем сделанный выбор)
            voted_keyboard = [
                [
                    InlineKeyboardButton(
                        f"{'✓ ' if vote > 0 else ''}👍", 
                        callback_data=f"voted_{image_id}"
                    ),
                    InlineKeyboardButton(
                        f"{'✓ ' if vote < 0 else ''}👎", 
                        callback_data=f"voted_{image_id}"
                    )
                ]
            ]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(voted_keyboard))
            
            # Отправляем сообщение с результатом голосования
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="\n".join(response_parts),
                parse_mode='HTML'
            )
            
            # Инвалидация кэша фильтрации после голосования
            self.voting_manager.invalidate_filtering_cache()
            
            # Rate limiting - не чаще 1 раза в 2 секунды
            chat_id = query.message.chat_id
            now = time.time()
            if user_id in self._last_command_time:
                time_passed = now - self._last_command_time[user_id]
                if time_passed < 2:
                    wait_time = int(2 - time_passed)
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⏳ Подождите {wait_time} секунд перед следующим запросом."
                    )
                    logger.warning(f"Rate limit для user_id={user_id}, осталось {wait_time}с")
                    return
            
            self._last_command_time[user_id] = now
            
            # Отправка сообщения о загрузке
            loading_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="🔄 Загружаю следующее фото..."
            )
            
            # Отправка следующего случайного фото
            success = await self._send_random_photo(chat_id, user_id, context)
            
            # Удаление сообщения о загрузке
            try:
                await loading_msg.delete()
            except Exception as e:
                logger.warning(f"Не удалось удалить loading сообщение: {e}")
            
            if not success:
                logger.error(f"Не удалось отправить фото после голосования user_id={user_id}")
            
        except Exception as e:
            logger.error(f"Ошибка при обработке callback голосования: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Произошла ошибка при обработке голоса."
            )
    
    async def handle_voted_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Обработчик callback для уже проголосованных кнопок.
        Просто подтверждаем получение, чтобы callback не висел.
        
        Args:
            update: Обновление от Telegram
            context: Контекст бота
        """
        query = update.callback_query
        await query.answer("Вы уже проголосовали за это фото", show_alert=False)
    
    def setup_handlers(self, application: Application):
        """
        Настройка обработчиков команд.
        
        Args:
            application: Объект Application бота
        """
        self.application = application
        
        # Добавление обработчиков команд
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("random", self.random_command))
        application.add_handler(CommandHandler("stats", self.stats_command))
        application.add_handler(CommandHandler("preferences", self.preferences_command))
        
        # Добавление обработчика текстовых сообщений (кнопка Random)
        from telegram.ext import MessageHandler
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))
        
        # Добавление обработчиков callback для голосования
        application.add_handler(CallbackQueryHandler(self.handle_vote_callback, pattern=r'^vote_'))
        application.add_handler(CallbackQueryHandler(self.handle_voted_callback, pattern=r'^voted_'))
        
        logger.info("Обработчики команд настроены")
    
    async def setup_bot_menu(self):
        """Настройка меню команд бота."""
        from telegram import BotCommand
        
        commands = [
            BotCommand("random", "Случайное фото"),
            BotCommand("stats", "Статистика"),
            BotCommand("preferences", "Предпочтения"),
            BotCommand("help", "Справка")
        ]
        
        await self.application.bot.set_my_commands(commands)
        logger.info("Меню команд установлено")