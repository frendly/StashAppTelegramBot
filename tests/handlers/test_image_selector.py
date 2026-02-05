"""Тесты для модуля image_selector."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.image_selector import ImageSelector


class DummyStashImage:
    """Заглушка StashImage для тестов."""

    def __init__(self, image_id: str, gallery_id: str | None = None):
        self.id = image_id
        self.gallery_id = gallery_id
        self.title = f"Image {image_id}"

    def get_gallery_title(self) -> str | None:
        """Возвращает название галереи."""
        return f"Gallery {self.gallery_id}" if self.gallery_id else None


@pytest.fixture
def mock_stash_client():
    """Создание мока StashClient."""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_database():
    """Создание мока Database."""
    db = MagicMock()
    return db


@pytest.fixture
def mock_voting_manager():
    """Создание мока VotingManager."""
    manager = MagicMock()
    manager.get_cached_gallery_weights = MagicMock(return_value={"g1": 1.0, "g2": 2.0})
    manager.get_filtering_lists = MagicMock(
        return_value={
            "blacklisted_performers": [],
            "blacklisted_galleries": [],
            "whitelisted_performers": [],
            "whitelisted_galleries": [],
        }
    )
    return manager


@pytest.fixture
def image_selector(mock_stash_client, mock_database, mock_voting_manager):
    """Создание экземпляра ImageSelector для тестов."""
    return ImageSelector(
        stash_client=mock_stash_client,
        database=mock_database,
        voting_manager=mock_voting_manager,
    )


@pytest.fixture
def image_selector_no_voting(mock_stash_client, mock_database):
    """Создание экземпляра ImageSelector без voting_manager."""
    return ImageSelector(
        stash_client=mock_stash_client,
        database=mock_database,
        voting_manager=None,
    )


@pytest.mark.asyncio
class TestImageSelectorGetRandomImage:
    """Тесты для метода get_random_image."""

    async def test_fallback_to_basic_when_no_voting_manager(
        self, image_selector_no_voting
    ):
        """Использование базового метода, если нет voting_manager."""
        image = DummyStashImage("img123")
        image_selector_no_voting.stash_client.get_random_image_with_retry = AsyncMock(
            return_value=image
        )
        result = await image_selector_no_voting.get_random_image(["img456"])
        assert result == image
        image_selector_no_voting.stash_client.get_random_image_with_retry.assert_called_once_with(
            exclude_ids=["img456"], max_retries=5
        )

    async def test_select_gallery_weighted_success(self, image_selector):
        """Успешный взвешенный выбор галереи."""
        image = DummyStashImage("img123")
        image_selector.stash_client.get_all_galleries_cached = AsyncMock(
            return_value=[{"id": "g1", "title": "Gallery 1", "image_count": 10}]
        )
        image_selector.stash_client.get_random_image_from_gallery_weighted = AsyncMock(
            return_value=image
        )
        image_selector.database.get_gallery_stats_with_viewed_counts = MagicMock(
            return_value={}
        )
        image_selector.database.update_gallery_last_selected = MagicMock()
        # Убеждаемся, что select_gallery_by_weight вернет галерею
        # (моки уже настроены для этого через voting_manager.get_cached_gallery_weights)

        result = await image_selector.get_random_image(["img456"])

        assert result == image
        image_selector.stash_client.get_random_image_from_gallery_weighted.assert_called_once()

    async def test_fallback_to_filtered_when_weighted_fails(self, image_selector):
        """Fallback на фильтрованный выбор при ошибке взвешенного."""
        image = DummyStashImage("img123")
        image_selector.stash_client.get_all_galleries_cached = AsyncMock(
            return_value=None
        )
        image_selector.stash_client.get_random_image_weighted = AsyncMock(
            return_value=image
        )

        result = await image_selector.get_random_image(["img456"])

        assert result == image
        image_selector.stash_client.get_random_image_weighted.assert_called_once()

    async def test_fallback_to_basic_when_all_fail(self, image_selector):
        """Fallback на базовый метод, если все остальные методы не сработали."""
        image = DummyStashImage("img123")
        image_selector.stash_client.get_all_galleries_cached = AsyncMock(
            return_value=None
        )
        image_selector.stash_client.get_random_image_weighted = AsyncMock(
            return_value=None
        )
        image_selector.stash_client.get_random_image_with_retry = AsyncMock(
            return_value=image
        )

        result = await image_selector.get_random_image(["img456"])

        assert result == image
        image_selector.stash_client.get_random_image_with_retry.assert_called_once()


@pytest.mark.asyncio
class TestImageSelectorGetRandomImageFromCache:
    """Тесты для метода get_random_image_from_cache."""

    async def test_get_image_from_cache_success(self, image_selector):
        """Успешное получение изображения из кэша."""
        image = DummyStashImage("img123")
        image_selector.stash_client.get_random_image_from_cache = AsyncMock(
            return_value=image
        )

        result = await image_selector.get_random_image_from_cache(["img456"])

        assert result == image
        image_selector.stash_client.get_random_image_from_cache.assert_called_once_with(
            ["img456"]
        )

    async def test_return_none_when_cache_empty(self, image_selector):
        """Возврат None, если кэш пуст."""
        image_selector.stash_client.get_random_image_from_cache = AsyncMock(
            return_value=None
        )

        result = await image_selector.get_random_image_from_cache(["img456"])

        assert result is None

    async def test_handle_exception(self, image_selector):
        """Обработка исключения при получении из кэша."""
        image_selector.stash_client.get_random_image_from_cache = AsyncMock(
            side_effect=Exception("Test error")
        )

        result = await image_selector.get_random_image_from_cache(["img456"])

        assert result is None
