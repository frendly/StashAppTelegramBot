from bot.database import Database


def test_update_performer_preference(database: Database) -> None:
    """Обновление предпочтений перформера и пересчет score."""
    database.update_performer_preference("p1", "Name", 1)
    database.update_performer_preference("p1", "Name", -1)
    database.update_performer_preference("p1", "Name", 1)

    prefs = database.get_performer_preferences()
    assert len(prefs) == 1

    performer = prefs[0]
    assert performer["performer_id"] == "p1"
    assert performer["total_votes"] == 3
    assert performer["positive_votes"] == 2
    assert performer["negative_votes"] == 1
    assert performer["score"] == (2 - 1) / 3


def test_update_gallery_preference_threshold_flag(database: Database) -> None:
    """Флаг достижения порога 5 голосов для галереи."""
    flags: list[bool] = []
    for _ in range(4):
        flags.append(database.update_gallery_preference("g1", "Gallery 1", vote=1))
    flags.append(database.update_gallery_preference("g1", "Gallery 1", vote=1))

    assert flags[:-1] == [False, False, False, False]
    assert flags[-1] is True


def test_ensure_gallery_exists_and_exclude(database: Database) -> None:
    """Создание галереи по умолчанию и последующее исключение."""
    created_first = database.ensure_gallery_exists("g2", "Gallery 2")
    created_second = database.ensure_gallery_exists("g2", "Gallery 2 (new name)")

    assert created_first is True
    assert created_second is False

    result = database.exclude_gallery("g2")
    assert result is True

    preference = database.get_gallery_preference("g2")
    assert preference is not None
