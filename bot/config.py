"""Конфигурация бота."""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class TelegramConfig:
    """Конфигурация Telegram бота."""

    bot_token: str
    allowed_user_ids: list[int]
    cache_channel_id: int | None = None


@dataclass
class StashConfig:
    """Конфигурация StashApp API."""

    api_url: str
    api_key: str | None = None
    username: str | None = None
    password: str | None = None


@dataclass
class SchedulerConfig:
    """Конфигурация планировщика."""

    enabled: bool
    cron: str
    timezone: str


@dataclass
class HistoryConfig:
    """Конфигурация истории отправленных фото."""

    avoid_recent_days: int


@dataclass
class DatabaseConfig:
    """Конфигурация базы данных."""

    path: str


@dataclass
class BotConfig:
    """Общая конфигурация бота."""

    telegram: TelegramConfig
    stash: StashConfig
    scheduler: SchedulerConfig
    history: HistoryConfig
    database: DatabaseConfig


def load_config(config_path: str = "config.yml") -> BotConfig:
    """
    Загрузка конфигурации из YAML файла с поддержкой переменных окружения.

    Args:
        config_path: Путь к конфигурационному файлу

    Returns:
        BotConfig: Объект конфигурации
    """
    config_file = Path(config_path)

    if not config_file.exists():
        raise FileNotFoundError(f"Конфигурационный файл не найден: {config_path}")

    with open(config_file, encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    # Поддержка переменных окружения
    telegram_token = (
        os.getenv("TELEGRAM_BOT_TOKEN") or config_data["telegram"]["bot_token"]
    )
    stash_api_key = os.getenv("STASH_API_KEY") or config_data["stash"].get(
        "api_key", ""
    )
    stash_username = os.getenv("STASH_USERNAME") or config_data["stash"].get(
        "username", ""
    )
    stash_password = os.getenv("STASH_PASSWORD") or config_data["stash"].get(
        "password", ""
    )

    telegram_config = TelegramConfig(
        bot_token=telegram_token,
        allowed_user_ids=config_data["telegram"]["allowed_user_ids"],
        cache_channel_id=config_data["telegram"].get("cache_channel_id"),
    )

    stash_config = StashConfig(
        api_url=config_data["stash"]["api_url"],
        api_key=stash_api_key if stash_api_key else None,
        username=stash_username if stash_username else None,
        password=stash_password if stash_password else None,
    )

    scheduler_config = SchedulerConfig(
        enabled=config_data["scheduler"]["enabled"],
        cron=config_data["scheduler"]["cron"],
        timezone=config_data["scheduler"]["timezone"],
    )

    history_config = HistoryConfig(
        avoid_recent_days=config_data["history"]["avoid_recent_days"]
    )

    database_config = DatabaseConfig(path=config_data["database"]["path"])

    # Валидация конфигурации
    if (
        not telegram_config.bot_token
        or telegram_config.bot_token == "YOUR_BOT_TOKEN_HERE"
    ):
        raise ValueError(
            "❌ Telegram bot token не настроен. Укажите токен в config.yml"
        )

    if not telegram_config.allowed_user_ids:
        raise ValueError(
            "❌ Список allowed_user_ids пуст. Добавьте хотя бы один Telegram ID"
        )

    if history_config.avoid_recent_days < 1:
        raise ValueError("❌ avoid_recent_days должен быть >= 1")

    return BotConfig(
        telegram=telegram_config,
        stash=stash_config,
        scheduler=scheduler_config,
        history=history_config,
        database=database_config,
    )
