"""Обработчики команд Telegram бота (фасад)."""

import logging
import time
from typing import TYPE_CHECKING, Optional

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

from bot.config import BotConfig
from bot.constants import RATE_LIMIT_UNAUTHORIZED_MESSAGE
from bot.database import Database
from bot.handlers.caption_formatter import CaptionFormatter
from bot.handlers.command_handler import CommandHandler as CmdHandler
from bot.handlers.image_selector import ImageSelector
from bot.handlers.photo_sender import PhotoSender
from bot.handlers.vote_handler import VoteHandler
from bot.stash_client import StashClient, StashImage

if TYPE_CHECKING:
    from bot.voting import VotingManager

logger = logging.getLogger(__name__)


class TelegramHandler:
    """Фасад для обработки команд Telegram бота."""

    def __init__(
        self,
        config: BotConfig,
        stash_client: StashClient,
        database: Database,
        voting_manager: Optional["VotingManager"] = None,
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
        self.application: Application | None = None

        # Кэши для последних отправленных изображений
        self._last_sent_images: dict[int, StashImage] = {}
        self._last_sent_image_id: dict[int, str] = {}
        self._last_unauthorized_message_time: dict[int, float] = {}

        # Создаем обработчики
        self.caption_formatter = CaptionFormatter(database)
        self.image_selector = ImageSelector(stash_client, database, voting_manager)
        self.photo_sender = PhotoSender(
            config=config,
            stash_client=stash_client,
            database=database,
            image_selector=self.image_selector,
            caption_formatter=self.caption_formatter,
            voting_manager=voting_manager,
            application=None,  # Будет установлен в setup_handlers
            last_sent_images=self._last_sent_images,
            last_sent_image_id=self._last_sent_image_id,
        )
        self.command_handler = CmdHandler(config, database, voting_manager)
        self.vote_handler = VoteHandler(
            config=config,
            stash_client=stash_client,
            database=database,
            caption_formatter=self.caption_formatter,
            voting_manager=voting_manager,
            application=None,  # Будет установлен в setup_handlers
            photo_sender=self.photo_sender,
            last_sent_images=self._last_sent_images,
            last_sent_image_id=self._last_sent_image_id,
        )

        # Настраиваем check_authorization в обработчиках
        self._setup_authorization_handlers()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start."""
        await self.command_handler.start_command(update, context)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help."""
        await self.command_handler.help_command(update, context)

    async def check_authorization(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """
        Единая проверка авторизации с rate limiting для сообщений об отсутствии доступа.

        Args:
            update: Обновление от Telegram
            context: Контекст бота

        Returns:
            bool: True если пользователь авторизован, False если нет
        """
        user_id = update.effective_user.id

        # Проверка авторизации
        if self.command_handler._is_authorized(user_id):
            return True

        # Если не авторизован, проверяем rate limiting
        now = time.time()
        if user_id in self._last_unauthorized_message_time:
            time_passed = now - self._last_unauthorized_message_time[user_id]
            if time_passed < RATE_LIMIT_UNAUTHORIZED_MESSAGE:
                # Пропускаем отправку сообщения, чтобы не спамить
                return False

        # Обновляем время последней отправки
        self._last_unauthorized_message_time[user_id] = now

        # Отправляем сообщение через правильный API
        message = "❌ У вас нет доступа к этому боту."
        if update.callback_query:
            # Для callback query используем query.answer
            await update.callback_query.answer(message, show_alert=False)
        elif update.message:
            # Для обычных сообщений используем reply_text
            await update.message.reply_text(message)
        else:
            # Если нет ни message, ни callback_query, просто логируем
            logger.warning(
                f"Неавторизованная попытка доступа: user_id={user_id} (неизвестный тип update)"
            )
            return False

        logger.warning(f"Неавторизованная попытка доступа: user_id={user_id}")
        return False

    def _setup_authorization_handlers(self):
        """
        Настройка check_authorization в обработчиках после создания метода.
        Вызывается после создания всех обработчиков.
        """
        # Передаем bound method check_authorization в обработчики
        self.command_handler.check_authorization = self.check_authorization
        self.vote_handler.check_authorization = self.check_authorization

    async def random_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /random."""
        if not await self.check_authorization(update, context):
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        logger.info(f"Команда /random от user_id={user_id}")

        # Отправка сообщения о загрузке
        loading_msg = await update.message.reply_text(
            "🔄 Загружаю случайное фото...",
            reply_markup=self.command_handler._get_persistent_keyboard(),
        )

        # Отправка случайного фото
        # Кэш обновляется автоматически в photo_sender после сохранения в БД
        success = await self.photo_sender.send_random_photo(chat_id, user_id, context)

        # Удаление сообщения о загрузке
        await loading_msg.delete()

        if not success:
            logger.error(f"Не удалось отправить фото user_id={user_id}")

    async def handle_text_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Обработчик текстовых сообщений (кнопка Random)."""
        if not await self.check_authorization(update, context):
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        text = update.message.text

        # Обработка кнопки Random
        if text == "💕 Random":
            logger.info(f"Кнопка Random от user_id={user_id}")

            # Отправка сообщения о загрузке
            loading_msg = await update.message.reply_text(
                "🔄 Загружаю случайное фото...",
                reply_markup=self.command_handler._get_persistent_keyboard(),
            )

            # Отправка случайного фото
            # Кэш обновляется автоматически в photo_sender после сохранения в БД
            success = await self.photo_sender.send_random_photo(
                chat_id, user_id, context
            )

            # Удаление сообщения о загрузке
            await loading_msg.delete()

            if not success:
                logger.error(f"Не удалось отправить фото user_id={user_id}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stats."""
        await self.command_handler.stats_command(update, context)

    async def preferences_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Обработчик команды /preferences."""
        await self.command_handler.preferences_command(update, context)

    async def send_scheduled_photo(self, chat_id: int, user_id: int):
        """
        Отправка фото по расписанию.

        Args:
            chat_id: ID чата для отправки
            user_id: ID пользователя (для работы кнопок голосования)
        """
        logger.info(
            f"Отправка запланированного фото в chat_id={chat_id}, user_id={user_id}"
        )
        # Отправка фото по расписанию
        # Кэш обновляется автоматически в photo_sender после сохранения в БД
        success = await self.photo_sender.send_random_photo(
            chat_id, user_id=user_id, context=None, use_high_quality=True
        )
        if not success:
            logger.error(
                f"Не удалось отправить запланированное фото в chat_id={chat_id}, user_id={user_id}"
            )

    async def handle_vote_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Обработчик callback для голосования."""
        await self.vote_handler.handle_vote_callback(update, context)

    async def handle_voted_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Обработчик callback для уже проголосованных кнопок."""
        await self.vote_handler.handle_voted_callback(update, context)

    async def handle_exclude_gallery_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Обработчик callback для исключения галереи."""
        await self.vote_handler.handle_exclude_gallery_callback(update, context)

    def setup_handlers(self, application: Application):
        """
        Настройка обработчиков команд.

        Args:
            application: Объект Application бота
        """
        self.application = application

        # Обновляем application в обработчиках
        self.photo_sender.application = application
        self.vote_handler.application = application

        # Добавление обработчиков команд
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("random", self.random_command))
        application.add_handler(CommandHandler("stats", self.stats_command))
        application.add_handler(CommandHandler("preferences", self.preferences_command))

        # Добавление обработчика текстовых сообщений (кнопка Random)
        from telegram.ext import MessageHandler

        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message)
        )

        # Добавление обработчиков callback для голосования
        application.add_handler(
            CallbackQueryHandler(self.handle_vote_callback, pattern=r"^vote_")
        )
        application.add_handler(
            CallbackQueryHandler(self.handle_voted_callback, pattern=r"^voted_")
        )
        application.add_handler(
            CallbackQueryHandler(
                self.handle_exclude_gallery_callback, pattern=r"^exclude_gallery_"
            )
        )

        logger.info("Обработчики команд настроены")

    async def setup_bot_menu(self):
        """Настройка меню команд бота."""
        from telegram import BotCommand

        commands = [
            BotCommand("random", "Случайное фото"),
            BotCommand("stats", "Статистика"),
            BotCommand("preferences", "Предпочтения"),
            BotCommand("help", "Справка"),
        ]

        await self.application.bot.set_my_commands(commands)
        logger.info("Меню команд установлено")

    # Публичные методы для использования из scheduler.py
    async def get_random_image(
        self, exclude_ids: list[str], update_last_selected: bool = True
    ) -> StashImage | None:
        """
        Получение случайного изображения (публичный метод для scheduler).

        Args:
            exclude_ids: Список ID изображений для исключения
            update_last_selected: Если True, обновляет время последнего выбора галереи

        Returns:
            Optional[StashImage]: Случайное изображение или None
        """
        return await self.image_selector.get_random_image(
            exclude_ids, update_last_selected
        )

    async def preload_image_to_cache(
        self, image: StashImage, use_high_quality: bool = True
    ):
        """
        Предзагрузка изображения в служебный канал (публичный метод для scheduler).

        Args:
            image: Объект изображения StashImage
            use_high_quality: Если True, использует high quality версию
        """
        await self.photo_sender.preload_image_to_cache(image, use_high_quality)
