"""Главный модуль бота - точка входа."""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application

from bot.config import BotConfig, load_config
from bot.database import Database
from bot.scheduler import Scheduler
from bot.stash_client import StashClient
from bot.telegram_handler import TelegramHandler
from bot.voting import VotingManager

# Настройка логирования
log_path = os.getenv("LOG_PATH", "bot.log")
os.makedirs(
    os.path.dirname(log_path) if os.path.dirname(log_path) else ".", exist_ok=True
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.info,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)


class Bot:
    """Главный класс бота."""

    def __init__(self, config_path: str = "config.yml"):
        """
        Инициализация бота.

        Args:
            config_path: Путь к конфигурационному файлу
        """
        self.config: BotConfig = None
        self.database: Database = None
        self.stash_client: StashClient = None
        self.voting_manager: VotingManager = None
        self.telegram_handler: TelegramHandler = None
        self.scheduler: Scheduler = None
        self.application: Application = None
        self.config_path = config_path
        self._shutdown_event = asyncio.Event()
        self._web_app_runner: web.AppRunner | None = None

    async def initialize(self):
        """Инициализация компонентов бота."""
        try:
            logger.info("=" * 50)
            logger.info("Запуск StashApp Telegram Bot")
            logger.info("=" * 50)

            # Загрузка конфигурации
            logger.info(f"Загрузка конфигурации из {self.config_path}")
            self.config = load_config(self.config_path)
            logger.info(
                f"Конфигурация загружена. Разрешенные пользователи: {self.config.telegram.allowed_user_ids}"
            )

            # Инициализация базы данных
            logger.info(f"Инициализация базы данных: {self.config.database.path}")
            self.database = Database(self.config.database.path)

            # Инициализация StashApp клиента
            logger.info(f"Инициализация StashApp клиента: {self.config.stash.api_url}")
            self.stash_client = StashClient(
                api_url=self.config.stash.api_url,
                api_key=self.config.stash.api_key,
                username=self.config.stash.username,
                password=self.config.stash.password,
            )

            # Вход в async context для HTTP сессии
            await self.stash_client.__aenter__()

            # Проверка подключения к StashApp
            logger.info("Проверка подключения к StashApp...")
            connection_ok = await self.stash_client.test_connection()
            if not connection_ok:
                logger.warning(
                    "Не удалось подключиться к StashApp. Проверьте настройки."
                )
            else:
                logger.info("✅ Подключение к StashApp успешно")

            # Начальное наполнение кеша при старте (если кеш пуст)
            if self.config.cache:
                await self._initialize_cache()

            # Инициализация менеджера голосования
            logger.info("Инициализация менеджера голосования...")
            self.voting_manager = VotingManager(
                database=self.database, stash_client=self.stash_client
            )

            # Инициализация Telegram обработчиков
            logger.info("Инициализация Telegram обработчиков...")
            self.telegram_handler = TelegramHandler(
                config=self.config,
                stash_client=self.stash_client,
                database=self.database,
                voting_manager=self.voting_manager,
            )

            # Создание Telegram Application
            logger.info("Создание Telegram Application...")
            self.application = (
                Application.builder().token(self.config.telegram.bot_token).build()
            )

            # Настройка обработчиков команд
            self.telegram_handler.setup_handlers(self.application)

            # Настройка меню команд
            await self.telegram_handler.setup_bot_menu()

            # Инициализация планировщика
            logger.info("Инициализация планировщика...")
            self.scheduler = Scheduler(
                config=self.config,
                telegram_handler=self.telegram_handler,
                database=self.database,
                stash_client=self.stash_client,
            )
            self.scheduler.setup()

            logger.info("✅ Все компоненты инициализированы успешно")

        except FileNotFoundError as e:
            logger.error(f"❌ Файл не найден: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"❌ Ошибка при инициализации: {e}", exc_info=True)
            sys.exit(1)

    async def start(self):
        """Запуск бота."""
        try:
            # Запуск планировщика
            if self.config.scheduler.enabled:
                self.scheduler.start()
                status = self.scheduler.get_status()
                logger.info(f"Планировщик: {status}")

            # Запуск Telegram бота: polling или webhook
            if self.config.telegram.webhook and self.config.telegram.webhook.enabled:
                await self._start_webhook_mode()
            else:
                await self._start_polling_mode()

        except Exception as e:
            logger.error(f"❌ Ошибка при запуске бота: {e}", exc_info=True)
            raise

    async def stop(self):
        """Остановка бота."""
        logger.info("Остановка бота...")

        try:
            # Отправка уведомления администраторам
            if self.application:
                for user_id in self.config.telegram.allowed_user_ids:
                    try:
                        await self.application.bot.send_message(
                            chat_id=user_id,
                            text="⚠️ <b>Бот останавливается...</b>",
                            parse_mode="HTML",
                        )
                    except asyncio.CancelledError:
                        # Игнорируем отмену при остановке - это нормально
                        pass
                    except Exception:
                        pass

            # Остановка планировщика
            if self.scheduler:
                self.scheduler.stop()

            # Остановка Telegram бота
            if self.application:
                try:
                    # Если работали в режиме webhook — сначала удаляем webhook и останавливаем HTTP-сервер
                    if (
                        self.config
                        and self.config.telegram.webhook
                        and self.config.telegram.webhook.enabled
                    ):
                        await self._stop_webhook_mode()
                    else:
                        # Режим polling
                        await self.application.updater.stop()

                    await self.application.stop()
                    await self.application.shutdown()
                except asyncio.CancelledError:
                    # Игнорируем отмену при остановке - это нормально
                    logger.debug("Telegram бот остановлен (задача отменена)")

            # Закрытие StashApp клиента
            if self.stash_client:
                try:
                    await self.stash_client.__aexit__(None, None, None)
                except asyncio.CancelledError:
                    # Игнорируем отмену при остановке - это нормально
                    logger.debug("StashApp клиент закрыт (задача отменена)")

            logger.info("✅ Бот остановлен")

        except Exception as e:
            logger.error(f"Ошибка при остановке бота: {e}", exc_info=True)

    async def _initialize_cache(self):
        """
        Начальное наполнение кеша при старте бота.

        Если размер кеша меньше минимального, загружает изображения до нужного уровня.
        """
        if not self.config.cache or not self.config.telegram.cache_channel_id:
            return

        try:
            logger.info("Проверка начального размера кеша...")
            cache_size = await self.stash_client.get_cache_size()
            min_cache_size = self.config.cache.min_cache_size

            if cache_size < min_cache_size:
                needed = min_cache_size - cache_size
                logger.info(
                    f"Размер кеша: {cache_size}/{min_cache_size}. "
                    f"Начальное наполнение: нужно {needed} изображений"
                )

                # Загружаем пакетами по 10 для скорости
                batch_size = 10
                loaded = 0

                while loaded < needed:
                    batch_needed = min(batch_size, needed - loaded)

                    # 80% новых, 20% известных
                    new_count = int(batch_needed * 0.8)
                    known_count = batch_needed - new_count

                    # Получаем изображения
                    recent_ids = self.database.get_recent_image_ids(
                        self.config.history.avoid_recent_days
                    )

                    new_images = await self.stash_client.get_images_without_file_id(
                        count=new_count, exclude_ids=recent_ids
                    )
                    known_images = await self.stash_client.get_images_with_file_id(
                        count=known_count, exclude_ids=recent_ids
                    )

                    images_to_preload = new_images + known_images

                    # Предзагружаем
                    for image in images_to_preload:
                        try:
                            await self.telegram_handler.preload_image_to_cache(
                                image, use_high_quality=True
                            )
                            loaded += 1
                        except Exception as e:
                            logger.warning(
                                f"Ошибка при начальной предзагрузке изображения {image.id}: {e}"
                            )

                    logger.info(
                        f"Начальное наполнение: загружено {loaded}/{needed} изображений"
                    )

                    # Проверяем текущий размер кеша
                    cache_size = await self.stash_client.get_cache_size()
                    if cache_size >= min_cache_size:
                        break

                logger.info(
                    f"✅ Начальное наполнение кеша завершено. Размер кеша: {cache_size}"
                )
            else:
                logger.info(
                    f"✅ Кеш уже наполнен. Размер: {cache_size}/{min_cache_size}"
                )

        except Exception as e:
            logger.error(
                f"Критическая ошибка при начальном наполнении кеша: {e}", exc_info=True
            )

    async def _start_polling_mode(self):
        """Запуск бота в режиме polling."""
        logger.info("Запуск Telegram бота в режиме polling...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
        )

        logger.info("=" * 50)
        logger.info("✅ Бот запущен в режиме polling и готов к работе!")
        logger.info("=" * 50)

        # Отправка уведомления администраторам
        for user_id in self.config.telegram.allowed_user_ids:
            try:
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text="✅ <b>Бот запущен и готов к работе!</b>\n\nИспользуйте /help для просмотра команд.",
                    parse_mode="HTML",
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"Не удалось отправить уведомление пользователю {user_id}: {e}"
                )

        # Ожидание сигнала завершения
        await self._shutdown_event.wait()

    async def _start_webhook_mode(self):
        """Запуск бота в режиме webhook."""
        webhook_config = self.config.telegram.webhook
        assert webhook_config is not None  # для type checker

        logger.info("Запуск Telegram бота в режиме webhook...")
        logger.info(
            "Webhook URL: %s, listen: %s:%s",
            webhook_config.url,
            webhook_config.listen_address,
            webhook_config.port,
        )

        await self.application.initialize()
        await self.application.start()

        # Настройка aiohttp-приложения для приема webhook-запросов
        aiohttp_app = web.Application()

        async def handle_update(request: web.Request) -> web.Response:
            # Проверка секретного токена, если он настроен
            if webhook_config.secret_token:
                received_token = request.headers.get(
                    "X-Telegram-Bot-Api-Secret-Token", ""
                )
                if received_token != webhook_config.secret_token:
                    logger.warning("Получен webhook с неверным secret_token")
                    return web.Response(status=403, text="Forbidden")

            try:
                data = await request.json()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Не удалось прочитать JSON из webhook-запроса: {e}")
                return web.Response(status=400, text="Bad Request")

            try:
                update = Update.de_json(data=data, bot=self.application.bot)
                await self.application.process_update(update)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Ошибка обработки webhook-обновления: {e}", exc_info=True)
                return web.Response(status=500, text="Internal Server Error")

            return web.Response(text="OK")

        # Путь берём из URL (например, /webhook)
        parsed = urlparse(webhook_config.url or "")
        path = parsed.path or "/"
        webhook_path = path if path.startswith("/") else f"/{path}"

        aiohttp_app.router.add_post(webhook_path, handle_update)

        self._web_app_runner = web.AppRunner(aiohttp_app)
        try:
            await self._web_app_runner.setup()
            site = web.TCPSite(
                self._web_app_runner,
                webhook_config.listen_address,
                webhook_config.port,
            )
            await site.start()
            logger.info(
                "HTTP сервер webhook запущен на %s:%s%s",
                webhook_config.listen_address,
                webhook_config.port,
                webhook_path,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(
                f"Не удалось запустить HTTP сервер webhook: {e}", exc_info=True
            )
            raise

        # Регистрируем webhook в Telegram
        try:
            await self.application.bot.set_webhook(
                url=webhook_config.url,
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True,
                secret_token=webhook_config.secret_token,
            )
            logger.info("Webhook успешно зарегистрирован в Telegram API")
        except Exception as e:  # noqa: BLE001
            logger.error(
                f"Не удалось зарегистрировать webhook в Telegram: {e}", exc_info=True
            )
            raise

        logger.info("=" * 50)
        logger.info("✅ Бот запущен в режиме webhook и готов к работе!")
        logger.info("=" * 50)

        # Отправка уведомления администраторам
        for user_id in self.config.telegram.allowed_user_ids:
            try:
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "✅ <b>Бот запущен в режиме webhook и готов к работе!</b>\n\n"
                        "Используйте /help для просмотра команд."
                    ),
                    parse_mode="HTML",
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"Не удалось отправить уведомление пользователю {user_id}: {e}"
                )

        # Ожидание сигнала завершения
        await self._shutdown_event.wait()

    async def _stop_webhook_mode(self):
        """Остановка webhook-режима: удаление webhook и остановка HTTP-сервера."""
        logger.info("Остановка webhook-режима...")

        # Удаляем webhook из Telegram API
        try:
            await self.application.bot.delete_webhook(drop_pending_updates=False)
            logger.info("Webhook удалён из Telegram API")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Не удалось удалить webhook из Telegram: {e}")

        # Останавливаем HTTP-сервер
        if self._web_app_runner:
            try:
                await self._web_app_runner.cleanup()
                logger.info("HTTP сервер webhook остановлен")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Ошибка при остановке HTTP сервера webhook: {e}")

    def signal_handler(self, signum, frame):
        """
        Обработчик сигналов для graceful shutdown.

        Args:
            signum: Номер сигнала
            frame: Фрейм
        """
        logger.info(f"Получен сигнал {signum}. Начинаем graceful shutdown...")
        self._shutdown_event.set()


async def main():
    """Главная функция."""
    # Загрузка переменных окружения
    load_dotenv()

    # Определение пути к конфигурации
    config_path = Path("config.yml")
    if not config_path.exists():
        config_path = Path("/config/config.yml")  # Для Docker контейнера

    if not config_path.exists():
        logger.error("❌ Конфигурационный файл не найден. Создайте config.yml")
        sys.exit(1)

    # Создание и запуск бота
    bot = Bot(str(config_path))

    # Настройка обработчиков сигналов
    signal.signal(signal.SIGINT, bot.signal_handler)
    signal.signal(signal.SIGTERM, bot.signal_handler)

    try:
        await bot.initialize()
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Получен KeyboardInterrupt")
    finally:
        await bot.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Программа прервана пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
