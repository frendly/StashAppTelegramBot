import sqlite3

from bot.database import Database


def test_update_gallery_image_count_and_get_statistics(database: Database) -> None:
    """Обновление количества изображений и получение статистики."""
    database.ensure_gallery_exists("g1", "Gallery 1")

    for _ in range(3):
        database.update_gallery_preference("g1", "Gallery 1", vote=-1)

    database.update_gallery_image_count("g1", total_images=10)

    stats = database.get_gallery_statistics("g1")
    assert stats is not None
    assert stats["total_images"] == 10
    assert stats["negative_votes"] == 3
    assert stats["negative_percentage"] == 30.0


def test_calculate_negative_percentage(database: Database) -> None:
    """Расчет процента минусов по данным в БД."""
    database.ensure_gallery_exists("g2", "Gallery 2")
    for _ in range(2):
        database.update_gallery_preference("g2", "Gallery 2", vote=-1)
    database.update_gallery_image_count("g2", total_images=8)

    percent = database.calculate_negative_percentage("g2")
    assert percent == 25.0

    assert database.calculate_negative_percentage("unknown") == 0.0


def test_should_update_image_count(database: Database, db_path: str) -> None:
    """Проверка критериев необходимости обновления количества изображений."""
    database.ensure_gallery_exists("g3", "Gallery 3")

    assert database.should_update_image_count("g3") is True

    database.update_gallery_image_count("g3", total_images=5)
    assert database.should_update_image_count("g3") is False

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE gallery_preferences
            SET images_count_updated_at = '2000-01-01 00:00:00'
            WHERE gallery_id = ?
            """,
            ("g3",),
        )
        conn.commit()

    assert database.should_update_image_count("g3") is True
