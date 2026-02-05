from bot.constants import (
    GALLERY_WEIGHT_DEFAULT,
    GALLERY_WEIGHT_MAX,
    GALLERY_WEIGHT_MIN,
)
from bot.database import Database


def test_get_gallery_weight_default_for_unknown(database: Database) -> None:
    """Неизвестная галерея возвращает вес по умолчанию."""
    weight = database.get_gallery_weight("unknown")
    assert weight == GALLERY_WEIGHT_DEFAULT


def test_update_gallery_weight_increases_and_decreases(database: Database) -> None:
    """Обновление веса галереи при положительном и отрицательном голосе."""
    database.ensure_gallery_exists("g1", "Gallery 1")

    w1 = database.get_gallery_weight("g1")
    w2 = database.update_gallery_weight("g1", vote=1)
    w3 = database.update_gallery_weight("g1", vote=-1)

    assert w1 == GALLERY_WEIGHT_DEFAULT
    assert GALLERY_WEIGHT_MIN <= w2 <= GALLERY_WEIGHT_MAX
    assert GALLERY_WEIGHT_MIN <= w3 <= GALLERY_WEIGHT_MAX


def test_update_gallery_weight_clamped_to_limits(database: Database) -> None:
    """Вес не выходит за пределы GALLERY_WEIGHT_MIN и GALLERY_WEIGHT_MAX."""
    database.ensure_gallery_exists("g2", "Gallery 2")

    for _ in range(20):
        database.update_gallery_weight("g2", vote=1)
    w_max = database.get_gallery_weight("g2")
    assert w_max <= GALLERY_WEIGHT_MAX + 1e-6

    for _ in range(40):
        database.update_gallery_weight("g2", vote=-1)
    w_min = database.get_gallery_weight("g2")
    assert w_min >= GALLERY_WEIGHT_MIN - 1e-6


def test_get_active_gallery_weights_excludes_excluded(database: Database) -> None:
    """Исключенные галереи не попадают в активные веса."""
    database.ensure_gallery_exists("g3", "Gallery 3")
    database.ensure_gallery_exists("g4", "Gallery 4")

    database.exclude_gallery("g4")

    active = database.get_active_gallery_weights()
    assert "g3" in active
    assert "g4" not in active
