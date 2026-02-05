import sqlite3
from datetime import datetime, timedelta

from bot.database import Database


def test_add_and_get_last_sent_photo(database: Database) -> None:
    """Проверка добавления и получения последнего отправленного фото."""
    database.add_sent_photo(image_id="img1", user_id=123, title="Test 1")
    database.add_sent_photo(image_id="img2", user_id=456, title="Test 2")

    last = database.get_last_sent_photo()
    assert last is not None

    image_id, sent_at, title = last
    assert image_id == "img2"
    assert title == "Test 2"
    assert sent_at is not None


def test_get_last_sent_photo_for_user(database: Database) -> None:
    """Проверка получения последнего фото для конкретного пользователя."""
    database.add_sent_photo(image_id="img1", user_id=1, title="User1")
    database.add_sent_photo(image_id="img2", user_id=2, title="User2")

    last_user1 = database.get_last_sent_photo_for_user(user_id=1)
    assert last_user1 is not None
    image_id, sent_at, title = last_user1
    assert image_id == "img1"
    assert title == "User1"
    assert sent_at is not None

    last_user2 = database.get_last_sent_photo_for_user(user_id=2)
    assert last_user2 is not None
    image_id2, _, title2 = last_user2
    assert image_id2 == "img2"
    assert title2 == "User2"


def test_get_recent_image_ids_filters_only_user_photos(
    database: Database, db_path: str
) -> None:
    """В выборку попадают только фото с user_id (без предзагрузки)."""
    database.add_sent_photo(image_id="user_img", user_id=123, title="User")
    database.add_sent_photo(image_id="cache_img", user_id=None, title="Cache")

    recent_ids = database.get_recent_image_ids(days=365)
    assert "user_img" in recent_ids
    assert "cache_img" not in recent_ids

    old_date = datetime.now() - timedelta(days=400)
    old_date_str = old_date.strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE sent_photos SET sent_at = ? WHERE image_id = ?",
            (old_date_str, "user_img"),
        )
        conn.commit()

    recent_ids_after = database.get_recent_image_ids(days=365)
    assert "user_img" not in recent_ids_after


def test_is_recently_sent_uses_recent_ids(database: Database) -> None:
    """Проверка обертки is_recently_sent."""
    database.add_sent_photo(image_id="img_recent", user_id=1, title="Recent")

    assert database.is_recently_sent("img_recent", days=30) is True
    assert database.is_recently_sent("img_other", days=30) is False


def test_file_id_save_and_get_existing_record(database: Database) -> None:
    """Сохранение file_id в существующей записи и последующее чтение."""
    database.add_sent_photo(image_id="img1", user_id=1, title="Test")

    database.save_file_id(image_id="img1", file_id="thumb_id")
    got = database.get_file_id(image_id="img1", use_high_quality=False)

    assert got == "thumb_id"


def test_file_id_save_and_get_creates_new_record_if_missing(database: Database) -> None:
    """Сохранение file_id создает запись, если ее еще нет."""
    database.save_file_id(image_id="img2", file_id="thumb_id_2")

    got = database.get_file_id(image_id="img2", use_high_quality=False)
    assert got == "thumb_id_2"


def test_high_quality_file_id_independent(database: Database) -> None:
    """Проверка раздельного хранения обычного и high-quality file_id."""
    database.add_sent_photo(image_id="img3", user_id=1, title="Test3")

    database.save_file_id(image_id="img3", file_id="thumb", use_high_quality=False)
    database.save_file_id(image_id="img3", file_id="hq", use_high_quality=True)

    thumb = database.get_file_id(image_id="img3", use_high_quality=False)
    hq = database.get_file_id(image_id="img3", use_high_quality=True)

    assert thumb == "thumb"
    assert hq == "hq"
