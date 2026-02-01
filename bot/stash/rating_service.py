"""Сервис для обновления рейтингов в StashApp."""

import logging

from .client import StashGraphQLClient

logger = logging.getLogger(__name__)


class RatingService:
    """Сервис для обновления рейтингов изображений и галерей в StashApp."""

    def __init__(self, client: StashGraphQLClient):
        """
        Инициализация сервиса.

        Args:
            client: Базовый GraphQL клиент
        """
        self.client = client

    async def update_image_rating(self, image_id: str, rating: int) -> bool:
        """
        Обновление рейтинга изображения.

        Args:
            image_id: ID изображения
            rating: Рейтинг (1-5, будет преобразован в rating100)

        Returns:
            bool: True если обновление успешно
        """
        # Преобразуем rating (1-5) в rating100 (0-100)
        rating100 = rating * 20

        mutation = """
        mutation ImageUpdate($id: ID!, $rating: Int!) {
          imageUpdate(input: { id: $id, rating100: $rating }) {
            id
            rating100
          }
        }
        """

        variables = {"id": image_id, "rating": rating100}

        try:
            data = await self.client.execute_query(mutation, variables)
            if data.get("imageUpdate"):
                logger.info(
                    f"Рейтинг изображения {image_id} обновлен на {rating}/5 ({rating100}/100)"
                )
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка при обновлении рейтинга изображения {image_id}: {e}")
            return False

    async def update_gallery_rating(self, gallery_id: str, rating: int) -> bool:
        """
        Обновление рейтинга галереи.

        Args:
            gallery_id: ID галереи
            rating: Рейтинг (1-5, будет преобразован в rating100)

        Returns:
            bool: True если обновление успешно
        """
        # Преобразуем rating (1-5) в rating100 (0-100)
        rating100 = rating * 20

        mutation = """
        mutation GalleryUpdate($id: ID!, $rating: Int!) {
          galleryUpdate(input: { id: $id, rating100: $rating }) {
            id
            rating100
          }
        }
        """

        variables = {"id": gallery_id, "rating": rating100}

        try:
            data = await self.client.execute_query(mutation, variables)
            if data.get("galleryUpdate"):
                logger.info(
                    f"Рейтинг галереи {gallery_id} обновлен на {rating}/5 ({rating100}/100)"
                )
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка при обновлении рейтинга галереи {gallery_id}: {e}")
            return False
