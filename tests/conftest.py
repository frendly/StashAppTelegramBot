import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from bot.database import Database

# Добавляем корень проекта в sys.path, чтобы импортировать пакет bot
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@pytest.fixture
def db_path(tmp_path) -> str:
    """Путь к временной SQLite-базе для тестов."""
    return str(tmp_path / "test.db")


@pytest.fixture
def database(db_path: str) -> "Database":
    """Инициализация экземпляра Database с временной БД."""
    from bot.database import Database

    return Database(db_path)
