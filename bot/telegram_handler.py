"""Обработчики команд Telegram бота."""

import logging
import time
from typing import Optional, Dict
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    filters
)
from telegram.error import TelegramError

from bot.config import BotConfig
from bot.stash_client import StashClient, StashImage
from bot.database import Database

logger = logging.getLogger(__name__)


class TelegramHandler:
    """Класс для обработки команд Telegram бота."""
    
    def __init__(
        self,
        config: BotConfig,
        stash_client: StashClient,
        database: Database
    ):
        """
        Инициализация обработчика.
        
        Args:
            config: Конфигурация бота
            stash_client: Клиент StashApp
            database: База данных
        """
        self.config = config
        self.stash_client = stash_client
        self.database = database
        self.application: Optional[Application] = None
        self._last_command_time: Dict[int, float] = {}  # Rate limiting
    
    def _is_authorized(self, user_id: int) -> bool:
        """
        Проверка авторизации пользователя.
        
        Args:
            user_id: Telegram ID пользователя
            
        Returns:
            bool: True если пользователь авторизован
        """
        return user_id in self.config.telegram.allowed_user_ids
    
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
        try:
            # Получение списка недавно отправленных ID
            recent_ids = self.database.get_recent_image_ids(
                self.config.history.avoid_recent_days
            )
            
            logger.info(f"Запрос случайного фото (исключая {len(recent_ids)} недавних)")
            
            # Получение случайного изображения
            image = await self.stash_client.get_random_image_with_retry(
                exclude_ids=recent_ids,
                max_retries=5
            )
            
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
            
            # Отправка фото
            if context:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=image_data,
                    caption=caption,
                    parse_mode='HTML'
                )
            else:
                # Для планировщика используем application
                if self.application:
                    await self.application.bot.send_photo(
                        chat_id=chat_id,
                        photo=image_data,
                        caption=caption,
                        parse_mode='HTML'
                    )
            
            # Сохранение в базу данных
            self.database.add_sent_photo(
                image_id=image.id,
                user_id=user_id,
                title=image.title
            )
            
            logger.info(f"Фото успешно отправлено: {image.id}")
            return True
        
        except TelegramError as e:
            logger.error(f"Ошибка Telegram при отправке фото: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при отправке фото: {e}")
            return False
    
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
        
        if image.rating > 0:
            stars = "⭐" * (image.rating // 20)  # Конвертация rating100 в звезды (0-5)
            caption_parts.append(f"Рейтинг: {stars} ({image.rating}/100)")
        
        if image.tags:
            tags_str = ", ".join([f"#{tag.replace(' ', '_')}" for tag in image.tags[:5]])
            caption_parts.append(f"Теги: {tags_str}")
        
        return "\n".join(caption_parts) if caption_parts else "📸 Случайное фото"
    
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
            "/help - Показать эту справку\n\n"
            "📅 Автоматическая отправка: "
            f"{'включена ✅' if self.config.scheduler.enabled else 'выключена ❌'}"
        )
        
        await update.message.reply_text(welcome_message, parse_mode='HTML')
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
            "/help - Показать эту справку\n\n"
            "<b>О боте:</b>\n"
            "Бот отправляет случайные фотографии из вашей StashApp коллекции.\n"
            f"Фото не повторяются в течение {self.config.history.avoid_recent_days} дней.\n\n"
            f"<b>Расписание:</b> {self.config.scheduler.cron if self.config.scheduler.enabled else 'Не настроено'}"
        )
        
        await update.message.reply_text(help_message, parse_mode='HTML')
        logger.info(f"Команда /help от user_id={user_id}")
    
    async def random_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /random."""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        if not self._is_authorized(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этому боту.")
            return
        
        # Rate limiting - не чаще 1 раза в 10 секунд
        now = time.time()
        if user_id in self._last_command_time:
            time_passed = now - self._last_command_time[user_id]
            if time_passed < 10:
                wait_time = int(10 - time_passed)
                await update.message.reply_text(
                    f"⏳ Подождите {wait_time} секунд перед следующим запросом."
                )
                logger.warning(f"Rate limit для user_id={user_id}, осталось {wait_time}с")
                return
        
        self._last_command_time[user_id] = now
        
        logger.info(f"Команда /random от user_id={user_id}")
        
        # Отправка сообщения о загрузке
        loading_msg = await update.message.reply_text("🔄 Загружаю случайное фото...")
        
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
        
        stats_message = (
            "<b>📊 Статистика бота</b>\n\n"
            f"📸 Всего отправлено фото: <b>{total_sent}</b>\n"
            f"👤 Отправлено вам: <b>{user_sent}</b>\n"
        )
        
        if last_photo:
            image_id, sent_at, title = last_photo
            stats_message += f"\n🕐 Последнее фото: {title or 'Без названия'}\n"
            stats_message += f"📅 Дата: {sent_at[:19]}"
        
        await update.message.reply_text(stats_message, parse_mode='HTML')
    
    async def send_scheduled_photo(self, chat_id: int):
        """
        Отправка фото по расписанию.
        
        Args:
            chat_id: ID чата для отправки
        """
        logger.info(f"Отправка запланированного фото в chat_id={chat_id}")
        await self._send_random_photo(chat_id, context=None)
    
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
        
        logger.info("Обработчики команд настроены")
