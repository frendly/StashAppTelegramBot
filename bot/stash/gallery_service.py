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

        # Кэш для ID тега exclude_gallery
        self._exclude_tag_id: str | None = None

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

    async def find_or_create_tag(self, tag_name: str) -> str | None:
        """
        Найти или создать тег по имени.

        Args:
            tag_name: Название тега

        Returns:
            Optional[str]: ID тега или None при ошибке
        """
        # Проверяем кэш для exclude_gallery
        if tag_name == "exclude_gallery" and self._exclude_tag_id:
            return self._exclude_tag_id

        # Сначала ищем существующий тег
        query = """
        query FindTag($name: String!) {
          findTags(
            tag_filter: {
              name: {
                value: $name
                modifier: EQUALS
              }
            }
            filter: { per_page: 1 }
          ) {
            tags {
              id
              name
            }
          }
        }
        """

        variables = {"name": tag_name}

        try:
            data = await self.client.execute_query(query, variables)
            tags = data.get("findTags", {}).get("tags", [])

            if tags:
                tag_id = tags[0]["id"]
                # Сохраняем в кэш для exclude_gallery
                if tag_name == "exclude_gallery":
                    self._exclude_tag_id = tag_id
                logger.debug(f"Найден тег '{tag_name}' с ID {tag_id}")
                return tag_id

            # Если тег не найден, создаем его
            mutation = """
            mutation TagCreate($name: String!) {
              tagCreate(input: { name: $name }) {
                id
                name
              }
            }
            """

            data = await self.client.execute_query(mutation, variables)
            tag = data.get("tagCreate")

            if tag:
                tag_id = tag["id"]
                # Сохраняем в кэш для exclude_gallery
                if tag_name == "exclude_gallery":
                    self._exclude_tag_id = tag_id
                logger.info(f"Создан новый тег '{tag_name}' с ID {tag_id}")
                return tag_id

            logger.error(f"Не удалось создать тег '{tag_name}'")
            return None

        except Exception as e:
            logger.error(f"Ошибка при поиске/создании тега '{tag_name}': {e}")
            return None

    async def get_gallery_tags(self, gallery_id: str) -> list[str]:
        """
        Получить список ID тегов галереи.

        Args:
            gallery_id: ID галереи

        Returns:
            List[str]: Список ID тегов
        """
        query = """
        query GetGalleryTags($id: ID!) {
          findGallery(id: $id) {
            id
            tags {
              id
              name
            }
          }
        }
        """

        variables = {"id": gallery_id}

        try:
            data = await self.client.execute_query(query, variables)
            gallery = data.get("findGallery")

            if gallery:
                tags = gallery.get("tags", [])
                tag_ids = [tag["id"] for tag in tags]
                logger.debug(f"Получено {len(tag_ids)} тегов для галереи {gallery_id}")
                return tag_ids

            logger.warning(f"Галерея {gallery_id} не найдена")
            return []

        except Exception as e:
            logger.error(f"Ошибка при получении тегов галереи {gallery_id}: {e}")
            return []

    async def add_tag_to_gallery(self, gallery_id: str, tag_name: str) -> bool:
        """
        Добавить тег к галерее, сохраняя существующие теги.

        Args:
            gallery_id: ID галереи
            tag_name: Название тега для добавления

        Returns:
            bool: True если операция успешна
        """
        # Получаем или создаем тег
        tag_id = await self.find_or_create_tag(tag_name)
        if not tag_id:
            logger.error(f"Не удалось найти или создать тег '{tag_name}'")
            return False

        # Получаем текущие теги галереи
        current_tag_ids = await self.get_gallery_tags(gallery_id)

        # Проверяем, не добавлен ли уже тег
        if tag_id in current_tag_ids:
            logger.debug(f"Тег '{tag_name}' уже добавлен к галерее {gallery_id}")
            return True

        # Добавляем новый тег к существующим
        new_tag_ids = current_tag_ids + [tag_id]

        mutation = """
        mutation GalleryUpdate($id: ID!, $tag_ids: [ID!]!) {
          galleryUpdate(input: { id: $id, tag_ids: $tag_ids }) {
            id
            tags {
              id
              name
            }
          }
        }
        """

        variables = {"id": gallery_id, "tag_ids": new_tag_ids}

        try:
            data = await self.client.execute_query(mutation, variables)
            if data.get("galleryUpdate"):
                logger.info(
                    f"Тег '{tag_name}' добавлен к галерее {gallery_id}. "
                    f"Всего тегов: {len(new_tag_ids)}"
                )
                return True

            logger.error(f"Не удалось добавить тег '{tag_name}' к галерее {gallery_id}")
            return False

        except Exception as e:
            logger.error(
                f"Ошибка при добавлении тега '{tag_name}' к галерее {gallery_id}: {e}"
            )
            return False

    async def get_exclude_tag_id(self) -> str | None:
        """
        Получить ID тега exclude_gallery (с кэшированием и автоматическим созданием).

        Returns:
            Optional[str]: ID тега или None при ошибке
        """
        # Проверяем кэш
        if self._exclude_tag_id:
            return self._exclude_tag_id

        # Получаем или создаем тег
        tag_id = await self.find_or_create_tag("exclude_gallery")
        return tag_id

    def get_cached_exclude_tag_id(self) -> str | None:
        """
        Получить ID тега exclude_gallery из кэша (без запроса к API).

        Returns:
            Optional[str]: ID тега или None если еще не закэширован
        """
        return self._exclude_tag_id
