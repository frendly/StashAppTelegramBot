"""Модуль для проверки здоровья бота и его компонентов."""

import logging
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from telegram import Bot

if TYPE_CHECKING:
    from bot.stash_client import StashClient

logger = logging.getLogger(__name__)


async def check_stashapp_health(stash_client: "StashClient") -> dict[str, Any]:
    """
    Проверка подключения к StashApp API.

    Args:
        stash_client: Клиент StashApp

    Returns:
        Словарь с результатом проверки:
        - status: "healthy" или "unhealthy"
        - message: Сообщение о статусе
    """
    try:
        is_connected = await stash_client.test_connection()
        if is_connected:
            return {
                "status": "healthy",
                "message": "Подключение к StashApp успешно",
            }
        return {
            "status": "unhealthy",
            "message": "Не удалось подключиться к StashApp",
        }
    except Exception as e:
        logger.error(f"Ошибка при проверке StashApp: {e}", exc_info=True)
        return {
            "status": "unhealthy",
            "message": f"Ошибка при проверке StashApp: {str(e)}",
        }


def check_database_health(db_path: str) -> dict[str, Any]:
    """
    Проверка подключения к базе данных.

    Args:
        db_path: Путь к файлу базы данных

    Returns:
        Словарь с результатом проверки:
        - status: "healthy" или "unhealthy"
        - message: Сообщение о статусе
    """
    try:
        # Выполняем простой запрос для проверки подключения
        with sqlite3.connect(db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return {
            "status": "healthy",
            "message": "Подключение к базе данных успешно",
        }
    except sqlite3.Error as e:
        logger.error(f"Ошибка при проверке базы данных: {e}", exc_info=True)
        return {
            "status": "unhealthy",
            "message": f"Ошибка подключения к базе данных: {str(e)}",
        }
    except Exception as e:
        logger.error(f"Неожиданная ошибка при проверке БД: {e}", exc_info=True)
        return {
            "status": "unhealthy",
            "message": f"Ошибка при проверке базы данных: {str(e)}",
        }


async def check_telegram_health(bot: Bot) -> dict[str, Any]:
    """
    Проверка подключения к Telegram API.

    Args:
        bot: Экземпляр Telegram бота

    Returns:
        Словарь с результатом проверки:
        - status: "healthy" или "unhealthy"
        - message: Сообщение о статусе
    """
    try:
        bot_info = await bot.get_me()
        if bot_info and bot_info.username:
            return {
                "status": "healthy",
                "message": f"Подключение к Telegram API успешно (бот: @{bot_info.username})",
            }
        return {
            "status": "healthy",
            "message": "Подключение к Telegram API успешно",
        }
    except Exception as e:
        logger.error(f"Ошибка при проверке Telegram API: {e}", exc_info=True)
        return {
            "status": "unhealthy",
            "message": f"Ошибка при проверке Telegram API: {str(e)}",
        }


async def check_all_health(
    stash_client: "StashClient", db_path: str, bot: Bot | None = None
) -> dict[str, Any]:
    """
    Проверка здоровья всех компонентов бота.

    Args:
        stash_client: Клиент StashApp
        db_path: Путь к файлу базы данных
        bot: Экземпляр Telegram бота (опционально)

    Returns:
        Словарь с результатами проверки всех компонентов:
        - overall_status: "healthy", "unhealthy", "degraded" или "error"
        - stashapp: Результат проверки StashApp
        - database: Результат проверки базы данных
        - telegram: Результат проверки Telegram API (если bot передан)
        - timestamp: Временная метка проверки
    """
    results: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }

    # Проверка StashApp
    results["stashapp"] = await check_stashapp_health(stash_client)

    # Проверка базы данных
    results["database"] = check_database_health(db_path)

    # Проверка Telegram API (если бот доступен)
    if bot:
        results["telegram"] = await check_telegram_health(bot)
    else:
        results["telegram"] = {
            "status": "unknown",
            "message": "Бот не инициализирован",
        }

    # Определение общего статуса
    all_checks = [
        results["stashapp"]["status"],
        results["database"]["status"],
        results["telegram"]["status"],
    ]
    if "unhealthy" in all_checks:
        results["overall_status"] = "unhealthy"
    elif "unknown" in all_checks:
        results["overall_status"] = "degraded"
    else:
        results["overall_status"] = "healthy"

    return results
