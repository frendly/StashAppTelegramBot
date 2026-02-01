"""Сервис для работы с telegram_file_id в StashApp."""

import logging

from .client import StashGraphQLClient
from .models import StashImage

logger = logging.getLogger(__name__)


class FileIdService:
    """Сервис для сохранения и получения telegram_file_id из StashApp."""

    def __init__(self, client: StashGraphQLClient):
        """
        Инициализация сервиса.

        Args:
            client: Базовый GraphQL клиент
        """
        self.client = client

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
                return image.get("details")
            return None
        except Exception as e:
            logger.error(
                f"Ошибка при получении telegram_file_id для изображения {image_id}: {e}"
            )
            return None

    async def get_cache_size(self) -> int:
        """
        Получение размера кеша (количество изображений с telegram_file_id).

        Returns:
            int: Количество изображений в кеше
        """
        query = """
        query GetCacheSize {
          findImages(
            image_filter: {
              details: {
                value: ""
                modifier: NOT_NULL
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

        query = """
        query FindImagesWithoutFileId($per_page: Int!) {
          findImages(
            image_filter: {
              details: {
                value: ""
                modifier: IS_NULL
              }
            }
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

        variables = {"per_page": min(count * 2, 100)}  # Берем больше для фильтрации

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
            List[StashImage]: Список изображений
        """
        exclude_ids = exclude_ids or []

        query = """
        query FindImagesWithFileId($per_page: Int!) {
          findImages(
            image_filter: {
              details: {
                value: ""
                modifier: NOT_NULL
              }
            }
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

        variables = {"per_page": min(count * 2, 100)}  # Берем больше для фильтрации

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

        query = """
        query FindRandomCachedImage($per_page: Int!) {
          findImages(
            image_filter: {
              details: {
                value: ""
                modifier: NOT_NULL
              }
            }
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

        variables = {"per_page": 20}

        try:
            data = await self.client.execute_query(query, variables)
            images_data = data.get("findImages", {}).get("images", [])

            if not images_data:
                return None

            # Фильтруем по exclude_ids
            if exclude_ids:
                exclude_set = set(exclude_ids)
                images_data = [
                    img for img in images_data if img["id"] not in exclude_set
                ]

            if not images_data:
                return None

            # Возвращаем первое подходящее изображение
            return StashImage(images_data[0])
        except Exception as e:
            logger.error(f"Ошибка при получении случайного изображения из кеша: {e}")
            return None
