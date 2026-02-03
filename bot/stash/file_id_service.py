"""Сервис для работы с telegram_file_id в StashApp."""

import logging
from typing import Any

from .client import StashGraphQLClient
from .models import StashImage

logger = logging.getLogger(__name__)


class FileIdService:
    """Сервис для сохранения и получения telegram_file_id из StashApp."""

    def __init__(self, client: StashGraphQLClient, gallery_service=None):
        """
        Инициализация сервиса.

        Args:
            client: Базовый GraphQL клиент
            gallery_service: Опциональный GalleryService для получения ID тега (для синхронизации кэша)
        """
        self.client = client
        self._gallery_service = gallery_service
        # Кэш для ID тега exclude_gallery (используется только если gallery_service не передан)
        self._exclude_tag_id: str | None = None

    async def save_telegram_file_id(self, image_id: str, file_id: str) -> bool:
        """
        Сохранение telegram_file_id для изображения.

        Args:
            image_id: ID изображения
            file_id: Telegram file_id

        Returns:
            bool: True если сохранение успешно
        """
        mutation = """
        mutation ImageUpdate($id: ID!, $details: String) {
          imageUpdate(input: { id: $id, details: $details }) {
            id
            details
          }
        }
        """

        variables = {"id": image_id, "details": file_id}

        try:
            data = await self.client.execute_query(mutation, variables)
            if data.get("imageUpdate"):
                logger.debug(
                    f"telegram_file_id для изображения {image_id} сохранен: {file_id[:20]}..."
                )
                return True
            return False
        except Exception as e:
            logger.error(
                f"Ошибка при сохранении telegram_file_id для изображения {image_id}: {e}"
            )
            return False

    async def get_telegram_file_id(self, image_id: str) -> str | None:
        """
        Получение telegram_file_id для изображения.

        Args:
            image_id: ID изображения

        Returns:
            Optional[str]: telegram_file_id или None если не найден
        """
        query = """
        query GetImageFileId($id: ID!) {
          findImage(id: $id) {
            id
            details
          }
        }
        """

        variables = {"id": image_id}

        try:
            data = await self.client.execute_query(query, variables)
            image = data.get("findImage")
            if image:
                # details содержит telegram_file_id (просто строка)
                details = (
                    image.get("details", "").strip() if image.get("details") else ""
                )
                return details if details else None
            return None
        except Exception as e:
            logger.error(
                f"Ошибка при получении telegram_file_id для изображения {image_id}: {e}"
            )
            return None

    async def _get_exclude_tag_id(self) -> str | None:
        """
        Получить ID тега exclude_gallery (с кэшированием).

        Returns:
            Optional[str]: ID тега или None при ошибке
        """
        # Если передан gallery_service, используем его (единый кэш)
        if self._gallery_service:
            tag_id = await self._gallery_service.get_exclude_tag_id()
            if tag_id:
                return tag_id
            logger.warning(
                "Не удалось получить ID тега exclude_gallery через GalleryService"
            )
            return None

        # Fallback: используем локальный кэш и запросы
        if self._exclude_tag_id:
            return self._exclude_tag_id

        # Ищем тег
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

        variables = {"name": "exclude_gallery"}

        try:
            data = await self.client.execute_query(query, variables)
            tags = data.get("findTags", {}).get("tags", [])

            if tags:
                tag_id = tags[0]["id"]
                self._exclude_tag_id = tag_id
                logger.debug(f"Найден тег exclude_gallery с ID {tag_id}")
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
                self._exclude_tag_id = tag_id
                logger.info(f"Создан тег exclude_gallery с ID {tag_id}")
                return tag_id

            logger.warning(
                "Не удалось найти или создать тег exclude_gallery. "
                "Фильтрация по исключенным галереям не будет применяться."
            )
            return None

        except Exception as e:
            logger.error(
                f"Ошибка при получении ID тега exclude_gallery: {e}. "
                "Фильтрация по исключенным галереям не будет применяться."
            )
            return None

    async def get_cache_size(self) -> int:
        """
        Получение размера кеша (количество изображений с telegram_file_id).

        Returns:
            int: Количество изображений в кеше (только с непустым details)
        """
        query = """
        query GetCacheSize {
          findImages(
            image_filter: {
              details: {
                value: "."
                modifier: MATCHES_REGEX
              }
            }
            filter: { per_page: 1 }
          ) {
            count
          }
        }
        """

        try:
            data = await self.client.execute_query(query)
            count = data.get("findImages", {}).get("count", 0)
            return count
        except Exception as e:
            logger.error(f"Ошибка при получении размера кеша: {e}")
            return 0

    async def get_images_without_file_id(
        self, count: int, exclude_ids: list[str] | None = None
    ) -> list[StashImage]:
        """
        Получение изображений без telegram_file_id (новые для кеша).

        Args:
            count: Количество изображений
            exclude_ids: Список ID изображений для исключения

        Returns:
            List[StashImage]: Список изображений
        """
        exclude_ids = exclude_ids or []

        # Получаем ID тега exclude_gallery для фильтрации
        exclude_tag_id = await self._get_exclude_tag_id()

        # Формируем фильтр изображений
        image_filter: dict[str, Any] = {
            "details": {
                "value": "",
                "modifier": "IS_NULL",
            }
        }

        # Добавляем фильтр по тегу галереи, если тег найден
        if exclude_tag_id:
            image_filter["galleries_filter"] = {
                "tags": {
                    "value": [exclude_tag_id],
                    "modifier": "EXCLUDES",
                }
            }

        query = """
        query FindImagesWithoutFileId($per_page: Int!, $image_filter: ImageFilterType!) {
          findImages(
            image_filter: $image_filter
            filter: { per_page: $per_page, sort: "random" }
          ) {
            images {
              id
              title
              rating100
              paths {
                thumbnail
                preview
                image
              }
              galleries {
                id
                title
                folder {
                  path
                }
                files {
                  path
                }
              }
              performers {
                id
                name
              }
              details
            }
          }
        }
        """

        variables = {
            "per_page": min(count * 2, 100),  # Берем больше для фильтрации
            "image_filter": image_filter,
        }

        try:
            data = await self.client.execute_query(query, variables)
            images_data = data.get("findImages", {}).get("images", [])

            # Фильтруем по exclude_ids
            if exclude_ids:
                exclude_set = set(exclude_ids)
                images_data = [
                    img for img in images_data if img["id"] not in exclude_set
                ]

            # Возвращаем нужное количество
            result = []
            for img_data in images_data[:count]:
                result.append(StashImage(img_data))

            return result
        except Exception as e:
            logger.error(f"Ошибка при получении изображений без file_id: {e}")
            return []

    async def get_images_with_file_id(
        self, count: int, exclude_ids: list[str] | None = None
    ) -> list[StashImage]:
        """
        Получение изображений с telegram_file_id (известные для обновления).

        Args:
            count: Количество изображений
            exclude_ids: Список ID изображений для исключения

        Returns:
            List[StashImage]: Список изображений (только с непустым details)
        """
        exclude_ids = exclude_ids or []

        # Получаем ID тега exclude_gallery для фильтрации
        exclude_tag_id = await self._get_exclude_tag_id()

        # Формируем фильтр изображений
        image_filter: dict[str, Any] = {
            "details": {
                "value": ".",
                "modifier": "MATCHES_REGEX",
            }
        }

        # Добавляем фильтр по тегу галереи, если тег найден
        if exclude_tag_id:
            image_filter["galleries_filter"] = {
                "tags": {
                    "value": [exclude_tag_id],
                    "modifier": "EXCLUDES",
                }
            }

        query = """
        query FindImagesWithFileId($per_page: Int!, $image_filter: ImageFilterType!) {
          findImages(
            image_filter: $image_filter
            filter: { per_page: $per_page, sort: "random" }
          ) {
            images {
              id
              title
              rating100
              paths {
                thumbnail
                preview
                image
              }
              galleries {
                id
                title
                folder {
                  path
                }
                files {
                  path
                }
              }
              performers {
                id
                name
              }
              details
            }
          }
        }
        """

        variables = {
            "per_page": min(count * 2, 100),  # Берем больше для фильтрации
            "image_filter": image_filter,
        }

        try:
            data = await self.client.execute_query(query, variables)
            images_data = data.get("findImages", {}).get("images", [])

            # Фильтруем по exclude_ids
            if exclude_ids:
                exclude_set = set(exclude_ids)
                images_data = [
                    img for img in images_data if img["id"] not in exclude_set
                ]

            # MATCHES_REGEX уже отфильтровал пустые строки на сервере
            result = []
            for img_data in images_data[:count]:
                result.append(StashImage(img_data))

            return result
        except Exception as e:
            logger.error(f"Ошибка при получении изображений с file_id: {e}")
            return []

    async def get_random_image_from_cache(
        self, exclude_ids: list[str] | None = None
    ) -> StashImage | None:
        """
        Получение случайного изображения из кеша (с telegram_file_id).

        Args:
            exclude_ids: Список ID изображений для исключения

        Returns:
            Optional[StashImage]: Случайное изображение или None
        """
        exclude_ids = exclude_ids or []

        # Получаем ID тега exclude_gallery для фильтрации
        exclude_tag_id = await self._get_exclude_tag_id()

        # Формируем фильтр изображений
        image_filter: dict[str, Any] = {
            "details": {
                "value": ".",
                "modifier": "MATCHES_REGEX",
            }
        }

        # Добавляем фильтр по тегу галереи, если тег найден
        if exclude_tag_id:
            image_filter["galleries_filter"] = {
                "tags": {
                    "value": [exclude_tag_id],
                    "modifier": "EXCLUDES",
                }
            }

        query = """
        query FindRandomCachedImage($per_page: Int!, $image_filter: ImageFilterType!) {
          findImages(
            image_filter: $image_filter
            filter: { per_page: $per_page, sort: "random" }
          ) {
            images {
              id
              title
              rating100
              paths {
                thumbnail
                preview
                image
              }
              galleries {
                id
                title
                folder {
                  path
                }
                files {
                  path
                }
              }
              performers {
                id
                name
              }
              details
            }
          }
        }
        """

        variables = {
            "per_page": 20,
            "image_filter": image_filter,
        }

        try:
            data = await self.client.execute_query(query, variables)
            images_data = data.get("findImages", {}).get("images", [])

            if not images_data:
                logger.warning(
                    "get_random_image_from_cache: запрос вернул 0 изображений"
                )
                return None

            # Фильтруем по exclude_ids
            if exclude_ids:
                exclude_set = set(exclude_ids)
                images_data = [
                    img for img in images_data if img["id"] not in exclude_set
                ]

            if not images_data:
                logger.warning(
                    f"get_random_image_from_cache: все изображения в exclude_ids "
                    f"(exclude_ids count: {len(exclude_ids)})"
                )
                return None

            # MATCHES_REGEX уже отфильтровал пустые строки на сервере,
            # поэтому просто возвращаем первое подходящее изображение
            return StashImage(images_data[0])
        except Exception as e:
            logger.error(f"Ошибка при получении случайного изображения из кеша: {e}")
            return None
