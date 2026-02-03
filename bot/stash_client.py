"""Клиент для работы с StashApp GraphQL API (фасад)."""

from bot.stash.client import StashGraphQLClient
from bot.stash.file_id_service import FileIdService
from bot.stash.gallery_service import GalleryService
from bot.stash.image_service import ImageService
from bot.stash.metrics import CategoryMetrics
from bot.stash.models import StashImage
from bot.stash.rating_service import RatingService
from bot.stash.selection import select_gallery_by_weight

# Экспорт для обратной совместимости
__all__ = ["StashClient", "StashImage", "select_gallery_by_weight"]


class StashClient:
    """Фасад для взаимодействия с StashApp GraphQL API."""

    def __init__(
        self,
        api_url: str,
        api_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        """
        Инициализация клиента.

        Args:
            api_url: URL GraphQL API StashApp
            api_key: API ключ для авторизации (опционально)
            username: Имя пользователя для Basic Auth (опционально)
            password: Пароль для Basic Auth (опционально)
        """
        # Создаем базовый клиент
        self._client = StashGraphQLClient(api_url, api_key, username, password)

        # Создаем метрики
        self._category_metrics = CategoryMetrics()

        # Создаем сервисы (важен порядок: gallery_service нужен для image_service и file_id_service)
        self._gallery_service = GalleryService(self._client)

        self._image_service = ImageService(
            self._client, self._category_metrics, self._gallery_service
        )

        self._rating_service = RatingService(self._client)
        self._file_id_service = FileIdService(self._client, self._gallery_service)

        # Сохраняем для обратной совместимости
        self.api_url = api_url
        self.api_key = api_key
        self.username = username
        self.password = password
        self.session = None  # Будет установлен через __aenter__
        self.auth = self._client.auth

    async def __aenter__(self):
        """Создание HTTP сессии."""
        await self._client.__aenter__()
        self.session = self._client.session
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрытие HTTP сессии."""
        await self._client.__aexit__(exc_type, exc_val, exc_tb)
        self.session = None

    # Делегирование методов базового клиента
    async def download_image(self, image_url: str) -> bytes | None:
        """Скачивание изображения по URL."""
        return await self._client.download_image(image_url)

    async def test_connection(self) -> bool:
        """Проверка подключения к StashApp API."""
        return await self._client.test_connection()

    # Делегирование методов ImageService
    async def get_random_image(
        self, exclude_ids: list[str] | None = None
    ) -> StashImage | None:
        """Получение случайного изображения."""
        return await self._image_service.get_random_image(exclude_ids)

    async def get_random_image_with_retry(
        self, exclude_ids: list[str] | None = None, max_retries: int = 3
    ) -> StashImage | None:
        """Получение случайного изображения с повторными попытками."""
        return await self._image_service.get_random_image_with_retry(
            exclude_ids, max_retries
        )

    async def get_images_from_gallery_by_rating(
        self, gallery_id: str, rating_filter: str, exclude_ids: list[str] | None = None
    ) -> list[dict]:
        """Получение изображений из галереи с фильтром по рейтингу."""
        return await self._image_service.get_images_from_gallery_by_rating(
            gallery_id, rating_filter, exclude_ids
        )

    async def get_random_image_from_gallery(
        self, gallery_id: str, exclude_ids: list[str] | None = None
    ) -> StashImage | None:
        """Получение случайного изображения из конкретной галереи."""
        return await self._image_service.get_random_image_from_gallery(
            gallery_id, exclude_ids
        )

    async def get_random_image_from_gallery_weighted(
        self, gallery_id: str, exclude_ids: list[str] | None = None
    ) -> StashImage | None:
        """Получение случайного изображения из галереи с учетом приоритетов по рейтингу."""
        return await self._image_service.get_random_image_from_gallery_weighted(
            gallery_id, exclude_ids
        )

    async def get_random_image_weighted(
        self,
        exclude_ids: list[str] | None = None,
        blacklisted_performers: list[str] | None = None,
        blacklisted_galleries: list[str] | None = None,
        whitelisted_performers: list[str] | None = None,
        whitelisted_galleries: list[str] | None = None,
        max_retries: int = 3,
    ) -> StashImage | None:
        """Получение случайного изображения с учетом предпочтений."""
        return await self._image_service.get_random_image_weighted(
            exclude_ids,
            blacklisted_performers,
            blacklisted_galleries,
            whitelisted_performers,
            whitelisted_galleries,
            max_retries,
        )

    async def get_image_by_id(self, image_id: str) -> StashImage | None:
        """Получение изображения по ID из StashApp."""
        return await self._image_service.get_image_by_id(image_id)

    # Делегирование методов GalleryService
    async def get_all_galleries(self) -> list[dict]:
        """Получение списка всех галерей из StashApp."""
        return await self._gallery_service.get_all_galleries()

    async def get_all_galleries_cached(self) -> list[dict]:
        """Получение списка всех галерей с кэшированием."""
        return await self._gallery_service.get_all_galleries_cached()

    async def get_gallery_image_count(self, gallery_id: str) -> int | None:
        """Получение количества изображений в галерее."""
        return await self._gallery_service.get_gallery_image_count(gallery_id)

    async def add_tag_to_gallery(self, gallery_id: str, tag_name: str) -> bool:
        """Добавление тега к галерее."""
        return await self._gallery_service.add_tag_to_gallery(gallery_id, tag_name)

    async def get_exclude_tag_id(self) -> str | None:
        """Получение ID тега exclude_gallery (с кэшированием)."""
        return await self._gallery_service.get_exclude_tag_id()

    # Делегирование методов RatingService
    async def update_image_rating(self, image_id: str, rating: int) -> bool:
        """Обновление рейтинга изображения."""
        return await self._rating_service.update_image_rating(image_id, rating)

    async def update_gallery_rating(self, gallery_id: str, rating: int) -> bool:
        """Обновление рейтинга галереи."""
        return await self._rating_service.update_gallery_rating(gallery_id, rating)

    # Делегирование методов FileIdService
    async def save_telegram_file_id(self, image_id: str, file_id: str) -> bool:
        """Сохранение telegram_file_id для изображения."""
        return await self._file_id_service.save_telegram_file_id(image_id, file_id)

    async def get_telegram_file_id(self, image_id: str) -> str | None:
        """Получение telegram_file_id для изображения."""
        return await self._file_id_service.get_telegram_file_id(image_id)

    async def get_cache_size(self) -> int:
        """Получение размера кеша (количество изображений с telegram_file_id)."""
        return await self._file_id_service.get_cache_size()

    async def get_images_without_file_id(
        self, count: int, exclude_ids: list[str] | None = None
    ) -> list[StashImage]:
        """Получение изображений без telegram_file_id (новые для кеша)."""
        return await self._file_id_service.get_images_without_file_id(
            count, exclude_ids
        )

    async def get_images_with_file_id(
        self, count: int, exclude_ids: list[str] | None = None
    ) -> list[StashImage]:
        """Получение изображений с telegram_file_id (известные для обновления)."""
        return await self._file_id_service.get_images_with_file_id(count, exclude_ids)

    async def get_random_image_from_cache(
        self, exclude_ids: list[str] | None = None
    ) -> StashImage | None:
        """Получение случайного изображения из кеша (с telegram_file_id)."""
        return await self._file_id_service.get_random_image_from_cache(exclude_ids)

    # Делегирование методов CategoryMetrics
    def get_category_metrics(self, gallery_id: str | None = None) -> dict:
        """Получение метрик распределения категорий."""
        return self._category_metrics.get_category_metrics(gallery_id)

    def log_category_metrics(self, gallery_id: str | None = None):
        """Логирование метрик распределения категорий."""
        self._category_metrics.log_category_metrics(gallery_id)

    def reset_category_metrics(self, gallery_id: str | None = None):
        """Сброс метрик распределения категорий."""
        self._category_metrics.reset_category_metrics(gallery_id)

    # Приватные методы для обратной совместимости (если используются где-то)
    def _get_headers(self):
        """Получение заголовков для запроса (приватный метод для обратной совместимости)."""
        return self._client._get_headers()

    async def _execute_query(self, query: str, variables: dict | None = None) -> dict:
        """Выполнение GraphQL запроса (приватный метод для обратной совместимости)."""
        return await self._client.execute_query(query, variables)

    def _update_category_metrics(
        self,
        gallery_id: str,
        selected_category: str,
        actual_category: str,
        used_fallback: bool = False,
    ):
        """Обновление метрик распределения категорий (приватный метод для обратной совместимости)."""
        self._category_metrics.update_category_metrics(
            gallery_id, selected_category, actual_category, used_fallback
        )
