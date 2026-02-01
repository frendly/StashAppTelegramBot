"""Сервис для работы с галереями StashApp."""

import logging
import time
from typing import Any

from .client import StashGraphQLClient

logger = logging.getLogger(__name__)


class GalleryService:
    """Сервис для работы с галереями из StashApp."""

    def __init__(self, client: StashGraphQLClient, cache_ttl: int = 3600):
        """
        Инициализация сервиса.

        Args:
            client: Базовый GraphQL клиент
            cache_ttl: Время жизни кэша в секундах (по умолчанию 1 час)
        """
        self.client = client
        self.cache_ttl = cache_ttl

        # Кэш для списка всех галерей
        self._all_galleries_cache: list[dict[str, Any]] | None = None
        self._galleries_cache_time: float = 0

    async def get_all_galleries(self) -> list[dict[str, Any]]:
        """
        Получение списка всех галерей из StashApp.

        Returns:
            List[Dict]: Список галерей с id, title, image_count
        """
        query = """
        query GetAllGalleries {
          findGalleries(
            filter: {
              per_page: 10000
              sort: "title"
            }
          ) {
            count
            galleries {
              id
              title
              image_count
            }
          }
        }
        """

        try:
            data = await self.client.execute_query(query)
            galleries = data.get("findGalleries", {}).get("galleries", [])
            count = data.get("findGalleries", {}).get("count", 0)
            logger.info(
                f"Получено {len(galleries)} галерей из StashApp (всего: {count})"
            )
            return galleries
        except Exception as e:
            logger.error(f"Ошибка при получении списка галерей: {e}")
            return []

    async def get_all_galleries_cached(self) -> list[dict[str, Any]]:
        """
        Получение списка всех галерей с кэшированием.

        Returns:
            List[Dict]: Список галерей
        """
        current_time = time.perf_counter()

        # Проверяем кэш
        if (
            self._all_galleries_cache
            and (current_time - self._galleries_cache_time) < self.cache_ttl
        ):
            logger.debug(
                f"Используется кэшированный список галерей ({len(self._all_galleries_cache)} галерей)"
            )
            return self._all_galleries_cache

        # Обновляем кэш
        galleries = await self.get_all_galleries()
        self._all_galleries_cache = galleries
        self._galleries_cache_time = current_time

        return galleries

    async def get_gallery_image_count(self, gallery_id: str) -> int | None:
        """
        Получение количества изображений в галерее.

        Args:
            gallery_id: ID галереи

        Returns:
            Optional[int]: Количество изображений или None при ошибке
        """
        query = """
        query GetGalleryImageCount($id: ID!) {
          findGallery(id: $id) {
            image_count
          }
        }
        """

        variables = {"id": gallery_id}

        try:
            data = await self.client.execute_query(query, variables)
            gallery = data.get("findGallery")

            if gallery and "image_count" in gallery:
                count = gallery["image_count"]
                logger.debug(f"Количество изображений в галерее {gallery_id}: {count}")
                return count

            logger.warning(
                f"Галерея {gallery_id} не найдена или не содержит image_count"
            )
            return None
        except Exception as e:
            logger.error(
                f"Ошибка при получении количества изображений для галереи {gallery_id}: {e}"
            )
            return None
