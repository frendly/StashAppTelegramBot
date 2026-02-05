from typing import Any

import pytest

from bot.voting import VotingManager


class DummyDatabase:
    """Простая заглушка базы данных для тестов VotingManager."""

    def __init__(self) -> None:
        self.performer_prefs: list[dict[str, Any]] = []
        self.gallery_prefs: list[dict[str, Any]] = []
        self.blacklisted_performers: list[str] = []
        self.whitelisted_performers: list[str] = []
        self.blacklisted_galleries: list[str] = []
        self.whitelisted_galleries: list[str] = []
        self.gallery_stats: dict[str, dict[str, Any]] = {}

    # Методы для сводки предпочтений
    def get_performer_preferences(self) -> list[dict[str, Any]]:
        """Возвращает предпочтения по перформерам."""
        return self.performer_prefs

    def get_gallery_preferences(self) -> list[dict[str, Any]]:
        """Возвращает предпочтения по галереям."""
        return self.gallery_prefs

    # Методы для списков фильтрации
    def get_blacklisted_performers(self) -> list[str]:
        """Возвращает blacklist перформеров."""
        return self.blacklisted_performers

    def get_whitelisted_performers(self) -> list[str]:
        """Возвращает whitelist перформеров."""
        return self.whitelisted_performers

    def get_blacklisted_galleries(self) -> list[str]:
        """Возвращает blacklist галерей."""
        return self.blacklisted_galleries

    def get_whitelisted_galleries(self) -> list[str]:
        """Возвращает whitelist галерей."""
        return self.whitelisted_galleries

    # Методы для порога исключения
    def get_gallery_statistics(self, gallery_id: str) -> dict[str, Any] | None:
        """Возвращает статистику галереи для проверки порога исключения."""
        return self.gallery_stats.get(gallery_id)


class DummyStashClient:
    """Заглушка StashClient для инициализации VotingManager в тестах."""

    async def update_image_rating(self, *_: Any, **__: Any) -> bool:
        """Заглушка обновления рейтинга изображения."""
        return True


@pytest.fixture
def voting_manager() -> VotingManager:
    """Создание экземпляра VotingManager с заглушками."""
    db = DummyDatabase()
    stash = DummyStashClient()
    # Маленький TTL для ускорения тестов кэша
    return VotingManager(database=db, stash_client=stash, cache_ttl=10)


def test_get_preferences_summary_splits_top_and_worst(
    voting_manager: VotingManager,
) -> None:
    """Сводка предпочтений корректно делит любимых и нелюбимых."""
    db: DummyDatabase = voting_manager.database  # type: ignore[assignment]

    db.performer_prefs = [
        {"performer_id": "p1", "score": 1.0},
        {"performer_id": "p2", "score": -0.5},
        {"performer_id": "p3", "score": 0.5},
        {"performer_id": "p4", "score": -1.0},
    ]
    db.gallery_prefs = [
        {"gallery_id": "g1", "score": 0.8},
        {"gallery_id": "g2", "score": -0.3},
        {"gallery_id": "g3", "score": 0.2},
        {"gallery_id": "g4", "score": -0.9},
    ]

    summary = voting_manager.get_preferences_summary()

    assert summary["total_performers"] == 4
    assert summary["total_galleries"] == 4

    top_perf_ids = [p["performer_id"] for p in summary["top_performers"]]
    worst_perf_ids = [p["performer_id"] for p in summary["worst_performers"]]

    assert set(top_perf_ids) == {"p1", "p3"}
    assert set(worst_perf_ids) == {"p2", "p4"}

    top_gal_ids = [g["gallery_id"] for g in summary["top_galleries"]]
    worst_gal_ids = [g["gallery_id"] for g in summary["worst_galleries"]]

    assert set(top_gal_ids) == {"g1", "g3"}
    assert set(worst_gal_ids) == {"g2", "g4"}


def test_get_filtering_lists_uses_cache(voting_manager: VotingManager) -> None:
    """Списки фильтрации кэшируются и повторный вызов не дергает базу."""
    db: DummyDatabase = voting_manager.database  # type: ignore[assignment]

    db.blacklisted_performers = ["p1"]
    db.blacklisted_galleries = ["g1"]
    db.whitelisted_performers = ["p2"]
    db.whitelisted_galleries = ["g2"]

    first = voting_manager.get_filtering_lists()
    assert first["blacklisted_performers"] == ["p1"]

    db.blacklisted_performers = ["p1", "p3"]

    second = voting_manager.get_filtering_lists()
    assert second == first


def test_get_cached_gallery_weights_uses_cache(voting_manager: VotingManager) -> None:
    """Кэш весов галерей переиспользуется до истечения TTL."""

    class WeightsDatabase(DummyDatabase):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def get_active_gallery_weights(self) -> dict[str, float]:
            """Возврат весов галерей с подсчетом вызовов."""
            self.calls += 1
            return {"g1": 1.0, "g2": 2.0}

    voting_manager.database = WeightsDatabase()  # type: ignore[assignment]

    first = voting_manager.get_cached_gallery_weights()
    second = voting_manager.get_cached_gallery_weights()

    assert first == {"g1": 1.0, "g2": 2.0}
    assert second == first
    assert voting_manager.database.calls == 1  # type: ignore[union-attr]


def test_check_exclusion_threshold_logic(voting_manager: VotingManager) -> None:
    """Порог исключения учитывает как абсолютное число дизлайков, так и процент."""
    db: DummyDatabase = voting_manager.database  # type: ignore[assignment]

    db.gallery_stats["small_1"] = {
        "total_images": 1,
        "negative_votes": 1,
        "negative_percentage": 100.0,
    }
    reached, percent = voting_manager.check_exclusion_threshold("small_1")
    assert reached is True
    assert percent == 100.0

    db.gallery_stats["mid"] = {
        "total_images": 10,
        "negative_votes": 1,
        "negative_percentage": 10.0,
    }
    reached_mid, percent_mid = voting_manager.check_exclusion_threshold("mid")
    assert reached_mid is False
    assert percent_mid == 10.0

    db.gallery_stats["many_downvotes"] = {
        "total_images": 100,
        "negative_votes": 5,
        "negative_percentage": 5.0,
    }
    reached_many, _ = voting_manager.check_exclusion_threshold("many_downvotes")
    assert reached_many is True

    db.gallery_stats["by_percent"] = {
        "total_images": 6,
        "negative_votes": 2,
        "negative_percentage": 33.33,
    }
    reached_percent, _ = voting_manager.check_exclusion_threshold("by_percent")
    assert reached_percent is True


def test_check_exclusion_threshold_handles_missing_stats(
    voting_manager: VotingManager,
) -> None:
    """При отсутствии статистики или ошибке метод безопасно возвращает False."""
    reached, percent = voting_manager.check_exclusion_threshold("unknown")
    assert reached is False
    assert percent == 0.0
