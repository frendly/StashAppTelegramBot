"""Обработка команд Telegram бота."""

import logging

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import BotConfig
from bot.database import Database

logger = logging.getLogger(__name__)


class CommandHandler:
    """Класс для обработки команд Telegram бота."""

    def __init__(self, config: BotConfig, database: Database, voting_manager=None):
        """
        Инициализация обработчика команд.

        Args:
            config: Конфигурация бота
            database: База данных
            voting_manager: Менеджер голосования (опционально)
        """
        self.config = config
        self.database = database
        self.voting_manager = voting_manager

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
            keyboard, resize_keyboard=True, one_time_keyboard=False
        )

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
            parse_mode="HTML",
            reply_markup=self._get_persistent_keyboard(),
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
            parse_mode="HTML",
            reply_markup=self._get_persistent_keyboard(),
        )
        logger.info(f"Команда /help от user_id={user_id}")

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
        if votes_stats["total"] > 0:
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
            parse_mode="HTML",
            reply_markup=self._get_persistent_keyboard(),
        )

    async def preferences_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
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
        if summary["top_performers"]:
            prefs_message += "<b>👍 Любимые перформеры:</b>\n"
            for i, p in enumerate(summary["top_performers"], 1):
                name = p["performer_name"]
                display_name = f"{name[:25]}..." if len(name) > 25 else name
                prefs_message += (
                    f"{i}. {display_name} "
                    f"(👍 {p['positive_votes']} / 👎 {p['negative_votes']}, "
                    f"score: {p['score']:.2f})\n"
                )
            prefs_message += "\n"

        # Нелюбимые перформеры
        if summary["worst_performers"]:
            prefs_message += "<b>👎 Нелюбимые перформеры:</b>\n"
            for i, p in enumerate(summary["worst_performers"], 1):
                name = p["performer_name"]
                display_name = f"{name[:25]}..." if len(name) > 25 else name
                prefs_message += (
                    f"{i}. {display_name} "
                    f"(👍 {p['positive_votes']} / 👎 {p['negative_votes']}, "
                    f"score: {p['score']:.2f})\n"
                )
            prefs_message += "\n"

        # Топ галерей
        if summary["top_galleries"]:
            prefs_message += "<b>👍 Любимые галереи:</b>\n"
            for i, g in enumerate(summary["top_galleries"], 1):
                title = g["gallery_title"]
                display_title = f"{title[:30]}..." if len(title) > 30 else title
                prefs_message += (
                    f"{i}. {display_title} "
                    f"(👍 {g['positive_votes']} / 👎 {g['negative_votes']}, "
                    f"score: {g['score']:.2f})\n"
                )
            prefs_message += "\n"

        # Нелюбимые галереи
        if summary["worst_galleries"]:
            prefs_message += "<b>👎 Нелюбимые галереи:</b>\n"
            for i, g in enumerate(summary["worst_galleries"], 1):
                title = g["gallery_title"]
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

        if (
            not summary["top_performers"]
            and not summary["worst_performers"]
            and not summary["top_galleries"]
            and not summary["worst_galleries"]
        ):
            prefs_message += (
                "\n\n💡 <i>Пока нет данных. Начните голосовать за фото!</i>"
            )

        await update.message.reply_text(
            prefs_message,
            parse_mode="HTML",
            reply_markup=self._get_persistent_keyboard(),
        )

    async def handle_text_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Обработчик текстовых сообщений (кнопка Random)."""
        user_id = update.effective_user.id
        text = update.message.text

        if not self._is_authorized(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этому боту.")
            return

        # Обработка кнопки Random
        if text == "💕 Random":
            # Возвращаем True, чтобы показать, что сообщение обработано
            # Фактическая отправка фото будет выполнена в telegram_handler
            return True

        return False
