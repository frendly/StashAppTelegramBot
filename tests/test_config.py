from pathlib import Path

import pytest

from bot.config import BotConfig, load_config


def write_config(tmp_path: Path, content: str) -> str:
    """Запись временного config.yml и возврат пути."""
    config_file = tmp_path / "config.yml"
    config_file.write_text(content, encoding="utf-8")
    return str(config_file)


def test_load_config_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Базовая загрузка конфигурации из YAML."""
    config_yaml = """
telegram:
  bot_token: "TOKEN"
  allowed_user_ids: [123]
stash:
  api_url: "http://localhost:9999/graphql"
scheduler:
  enabled: true
  cron: "0 10 * * *"
  timezone: "Europe/Moscow"
history:
  avoid_recent_days: 30
database:
  path: "/data/sent_photos.db"
cache:
  min_cache_size: 100
"""
    path = write_config(tmp_path, config_yaml)

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("STASH_API_KEY", raising=False)
    monkeypatch.delenv("STASH_USERNAME", raising=False)
    monkeypatch.delenv("STASH_PASSWORD", raising=False)

    config = load_config(path)
    assert isinstance(config, BotConfig)
    assert config.telegram.bot_token == "TOKEN"
    assert config.telegram.allowed_user_ids == [123]
    assert config.stash.api_url == "http://localhost:9999/graphql"
    assert config.cache is not None
    assert config.cache.min_cache_size == 100


def test_load_config_uses_env_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Переменные окружения перекрывают значения из файла."""
    config_yaml = """
telegram:
  bot_token: "FROM_FILE"
  allowed_user_ids: [1]
stash:
  api_url: "http://stash/graphql"
  api_key: "from_file_key"
  username: "user_file"
  password: "pass_file"
scheduler:
  enabled: true
  cron: "* * * * *"
  timezone: "UTC"
history:
  avoid_recent_days: 10
database:
  path: "/db.sqlite"
"""
    path = write_config(tmp_path, config_yaml)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "FROM_ENV")
    monkeypatch.setenv("STASH_API_KEY", "env_key")
    monkeypatch.setenv("STASH_USERNAME", "env_user")
    monkeypatch.setenv("STASH_PASSWORD", "env_pass")

    config = load_config(path)

    assert config.telegram.bot_token == "FROM_ENV"
    assert config.stash.api_key == "env_key"
    assert config.stash.username == "env_user"
    assert config.stash.password == "env_pass"


def test_load_config_validation_errors(tmp_path: Path) -> None:
    """Некорректная конфигурация вызывает ожидаемые ошибки валидации."""
    bad_yaml = """
telegram:
  bot_token: ""
  allowed_user_ids: []
stash:
  api_url: "http://stash/graphql"
scheduler:
  enabled: true
  cron: "* * * * *"
  timezone: "UTC"
history:
  avoid_recent_days: 0
database:
  path: "/db.sqlite"
cache:
  min_cache_size: 0
"""
    path = write_config(tmp_path, bad_yaml)

    with pytest.raises(ValueError):
        load_config(path)


def test_load_config_webhook_requires_url(tmp_path: Path) -> None:
    """Если webhook включен, но url не указан, поднимается ошибка."""
    config_yaml = """
telegram:
  bot_token: "TOKEN"
  allowed_user_ids: [1]
  webhook:
    enabled: true
    url: ""
stash:
  api_url: "http://stash/graphql"
scheduler:
  enabled: true
  cron: "* * * * *"
  timezone: "UTC"
history:
  avoid_recent_days: 10
database:
  path: "/db.sqlite"
"""
    path = write_config(tmp_path, config_yaml)

    with pytest.raises(ValueError):
        load_config(path)
