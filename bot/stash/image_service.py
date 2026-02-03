"""Сервис для работы с изображениями StashApp."""

import logging
import random
import time
from typing import Any

from .client import StashGraphQLClient
from .models import StashImage

logger = logging.getLogger(__name__)


class ImageService:
    """Сервис для работы с изображениями из StashApp."""

    def __init__(
        self, client: StashGraphQLClient, category_metrics=None, gallery_service=None
    ):
        """
        Инициализация сервиса.

        Args:
            client: Базовый GraphQL клиент
            category_metrics: Опциональный объект CategoryMetrics для отслеживания метрик
            gallery_service: Опциональный GalleryService для получения ID тега (для синхронизации кэша)
        """
        self.client = client
        self.category_metrics = category_metrics
        self._gallery_service = gallery_service
        # Кэш для ID тега exclude_gallery (используется только если gallery_service не передан)
        self._exclude_tag_id: str | None = None

    async def get_random_image(
        self, exclude_ids: list[str] | None = None
    ) -> StashImage | None:
        """
        Получение случайного изображения.

        Args:
            exclude_ids: Список ID изображений для исключения

        Returns:
            Optional[StashImage]: Случайное изображение или None
        """
        start_time = time.perf_counter()

        # Получаем ID тега exclude_gallery для фильтрации
        exclude_tag_id = await self._get_exclude_tag_id()

        # Формируем фильтр изображений
        image_filter: dict[str, Any] = {}

        # Добавляем фильтр по тегу галереи, если тег найден
        if exclude_tag_id:
            image_filter["galleries_filter"] = {
                "tags": {
                    "value": [exclude_tag_id],
                    "modifier": "EXCLUDES",
                }
            }

        # Запрос с thumbnail для оптимизации скорости загрузки
        # Уменьшено до 20 изображений и убраны теги для ускорения
        # Всегда используем image_filter (пустой словарь, если фильтр не нужен)
        query = """
        query FindRandomImage($image_filter: ImageFilterType!) {
          findImages(
            image_filter: $image_filter
            filter: { per_page: 20, sort: "random" }
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

        try:
            query_start = time.perf_counter()
            variables = {"image_filter": image_filter}
            data = await self.client.execute_query(query, variables)
            query_duration = time.perf_counter() - query_start

            images = data.get("findImages", {}).get("images", [])

            if not images:
                logger.warning("Случайное изображение не найдено")
                return None

            # Локальная фильтрация: исключаем изображения из exclude_ids
            filter_start = time.perf_counter()
            if exclude_ids:
                exclude_set = set(exclude_ids)
                filtered_images = [
                    img for img in images if img["id"] not in exclude_set
                ]
                filter_duration = time.perf_counter() - filter_start
                logger.debug(
                    f"Получено {len(images)} изображений, после фильтрации: {len(filtered_images)} ({filter_duration:.3f}s)"
                )

                if not filtered_images:
                    logger.warning("После фильтрации не осталось изображений")
                    return None

                images = filtered_images

            # Возвращаем первое подходящее изображение
            image_data = images[0]
            image = StashImage(image_data)

            total_duration = time.perf_counter() - start_time
            logger.info(
                f"⏱️  get_random_image: {total_duration:.3f}s (query: {query_duration:.3f}s)"
            )
            return image

        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(f"⏱️  get_random_image failed after {duration:.3f}s: {e}")
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

    async def get_random_image_with_retry(
        self, exclude_ids: list[str] | None = None, max_retries: int = 3
    ) -> StashImage | None:
        """
        Получение случайного изображения с повторными попытками.

        Args:
            exclude_ids: Список ID изображений для исключения
            max_retries: Максимальное количество попыток

        Returns:
            Optional[StashImage]: Случайное изображение или None
        """
        for attempt in range(max_retries):
            try:
                image = await self.get_random_image(exclude_ids)
                if image:
                    return image
                logger.warning(
                    f"Попытка {attempt + 1}/{max_retries}: изображение не найдено"
                )
            except Exception as e:
                logger.error(f"Попытка {attempt + 1}/{max_retries} не удалась: {e}")

        logger.error(f"Не удалось получить изображение после {max_retries} попыток")
        return None

    async def get_images_from_gallery_by_rating(
        self, gallery_id: str, rating_filter: str, exclude_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """
        Получение изображений из галереи с фильтром по рейтингу.

        Args:
            gallery_id: ID галереи
            rating_filter: Фильтр рейтинга - "unrated", "positive", "negative"
            exclude_ids: Список ID изображений для исключения

        Returns:
            List[Dict[str, Any]]: Список изображений или пустой список
        """
        start_time = time.perf_counter()

        # Формируем параметры фильтра по рейтингу
        if rating_filter == "unrated":
            # Неоцененные: используем модификатор IS_NULL
            rating_value = 0  # Значение не важно для IS_NULL, но требуется схемой
            rating_modifier = "IS_NULL"
        elif rating_filter == "positive":
            # С "+": rating100 >= 80 (используем GREATER_THAN как указано в документации)
            rating_value = 80
            rating_modifier = "GREATER_THAN"
        elif rating_filter == "negative":
            # С "-": rating100 <= 20 (используем LESS_THAN как указано в документации)
            rating_value = 20
            rating_modifier = "LESS_THAN"
        else:
            logger.error(f"Неизвестный фильтр рейтинга: {rating_filter}")
            return []

        # Единый GraphQL запрос для всех случаев
        query = """
        query GetImagesFromGalleryByRating($gallery_id: ID!, $rating_value: Int!, $rating_modifier: CriterionModifier!) {
          findImages(
            image_filter: {
              galleries: {
                value: [$gallery_id]
                modifier: INCLUDES
              }
              rating100: {
                value: $rating_value
                modifier: $rating_modifier
              }
            }
            filter: {
              per_page: 20
              sort: "random"
            }
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
            "gallery_id": gallery_id,
            "rating_value": rating_value,
            "rating_modifier": rating_modifier,
        }

        try:
            query_start = time.perf_counter()
            data = await self.client.execute_query(query, variables)
            query_duration = time.perf_counter() - query_start

            images = data.get("findImages", {}).get("images", [])

            # Локальная фильтрация: исключаем изображения из exclude_ids
            if exclude_ids:
                exclude_set = set(exclude_ids)
                images = [img for img in images if img["id"] not in exclude_set]

            total_duration = time.perf_counter() - start_time
            logger.debug(
                f"⏱️  get_images_from_gallery_by_rating: {total_duration:.3f}s (query: {query_duration:.3f}s, gallery: {gallery_id}, filter: {rating_filter}, found: {len(images)})"
            )
            return images

        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(
                f"⏱️  get_images_from_gallery_by_rating failed after {duration:.3f}s (gallery: {gallery_id}, filter: {rating_filter}): {e}"
            )
            return []

    async def get_random_image_from_gallery(
        self, gallery_id: str, exclude_ids: list[str] | None = None
    ) -> StashImage | None:
        """
        Получение случайного изображения из конкретной галереи.

        Args:
            gallery_id: ID галереи
            exclude_ids: Список ID изображений для исключения

        Returns:
            Optional[StashImage]: Случайное изображение или None
        """
        start_time = time.perf_counter()

        query = """
        query GetRandomImageFromGallery($gallery_id: ID!) {
          findImages(
            image_filter: {
              galleries: {
                value: [$gallery_id]
                modifier: INCLUDES
              }
            }
            filter: {
              per_page: 20
              sort: "random"
            }
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

        variables = {"gallery_id": gallery_id}

        try:
            query_start = time.perf_counter()
            data = await self.client.execute_query(query, variables)
            query_duration = time.perf_counter() - query_start

            images = data.get("findImages", {}).get("images", [])

            if not images:
                logger.warning(
                    f"Случайное изображение не найдено в галерее {gallery_id}"
                )
                return None

            # Локальная фильтрация: исключаем изображения из exclude_ids
            filter_start = time.perf_counter()
            if exclude_ids:
                exclude_set = set(exclude_ids)
                filtered_images = [
                    img for img in images if img["id"] not in exclude_set
                ]
                filter_duration = time.perf_counter() - filter_start
                logger.debug(
                    f"Получено {len(images)} изображений из галереи {gallery_id}, после фильтрации: {len(filtered_images)} ({filter_duration:.3f}s)"
                )

                if not filtered_images:
                    logger.warning(
                        f"После фильтрации не осталось изображений в галерее {gallery_id}"
                    )
                    return None

                images = filtered_images

            # Возвращаем первое подходящее изображение
            image_data = images[0]
            image = StashImage(image_data)

            total_duration = time.perf_counter() - start_time
            logger.info(
                f"⏱️  get_random_image_from_gallery: {total_duration:.3f}s (query: {query_duration:.3f}s, gallery: {gallery_id})"
            )
            return image

        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(
                f"⏱️  get_random_image_from_gallery failed after {duration:.3f}s (gallery: {gallery_id}): {e}"
            )
            return None

    async def get_random_image_from_gallery_weighted(
        self, gallery_id: str, exclude_ids: list[str] | None = None
    ) -> StashImage | None:
        """
        Получение случайного изображения из галереи с учетом приоритетов по рейтингу.

        Приоритеты:
        - 70% неоцененные изображения (rating100 IS NULL)
        - 20% изображения с "+" (rating100 >= 80)
        - 10% изображения с "-" (rating100 <= 20)

        Если все категории пусты, используется fallback на получение любого изображения
        из галереи без фильтра по рейтингу (для изображений с рейтингом 21-79).

        Args:
            gallery_id: ID галереи
            exclude_ids: Список ID изображений для исключения

        Returns:
            Optional[StashImage]: Случайное изображение или None
        """
        start_time = time.perf_counter()

        # Генерируем случайное число от 0 до 99 для выбора категории
        random_value = random.randint(0, 99)

        # Определяем категорию по приоритетам
        if random_value < 70:
            # 0-69: неоцененные (70%)
            selected_category = "unrated"
            logger.debug(f"Выбрана категория: неоцененные (random={random_value})")
        elif random_value < 90:
            # 70-89: с "+" (20%)
            selected_category = "positive"
            logger.debug(f"Выбрана категория: с '+' (random={random_value})")
        else:
            # 90-99: с "-" (10%)
            selected_category = "negative"
            logger.debug(f"Выбрана категория: с '-' (random={random_value})")

        # Приоритет fallback: неоцененные > с + > с -
        fallback_order = ["unrated", "positive", "negative"]

        # Пробуем получить изображение из выбранной категории и fallback категорий
        used_fallback = False
        actual_category = selected_category

        for idx, category in enumerate(
            [selected_category] + [c for c in fallback_order if c != selected_category]
        ):
            try:
                images = await self.get_images_from_gallery_by_rating(
                    gallery_id=gallery_id,
                    rating_filter=category,
                    exclude_ids=exclude_ids,
                )

                if images:
                    # Если это не первая попытка (не выбранная категория), значит использовался fallback
                    if idx > 0:
                        used_fallback = True
                        logger.info(
                            f"🔄 Fallback: категория '{selected_category}' пуста, использована '{category}' для галереи {gallery_id}"
                        )

                    actual_category = category

                    # Выбираем случайное изображение из списка
                    image_data = random.choice(images)
                    image = StashImage(image_data)

                    # Обновляем метрики, если они доступны
                    if self.category_metrics:
                        self.category_metrics.update_category_metrics(
                            gallery_id,
                            selected_category,
                            actual_category,
                            used_fallback,
                        )

                    total_duration = time.perf_counter() - start_time
                    logger.info(
                        f"⏱️  get_random_image_from_gallery_weighted: {total_duration:.3f}s (gallery: {gallery_id}, selected: {selected_category}, actual: {actual_category}, fallback: {used_fallback})"
                    )
                    return image
                else:
                    logger.debug(
                        f"Категория {category} пуста для галереи {gallery_id}, пробуем следующую"
                    )

            except Exception as e:
                logger.warning(
                    f"Ошибка при получении изображений из категории {category} для галереи {gallery_id}: {e}"
                )
                continue

        # Если все категории пустые, пробуем получить любое изображение из галереи без фильтра по рейтингу
        # Это нужно для случаев, когда в галерее есть изображения с рейтингом 21-79, которые не попадают
        # ни в одну из трех категорий (unrated, positive >= 80, negative <= 20)
        logger.info(
            f"Все категории пусты для галереи {gallery_id}, пробуем получить любое изображение без фильтра по рейтингу"
        )
        try:
            image = await self.get_random_image_from_gallery(
                gallery_id=gallery_id, exclude_ids=exclude_ids
            )

            if image:
                used_fallback = True
                actual_category = "any"  # Специальная категория для изображений без фильтра по рейтингу

                # Обновляем метрики, если они доступны
                if self.category_metrics:
                    self.category_metrics.update_category_metrics(
                        gallery_id, selected_category, actual_category, used_fallback
                    )

                total_duration = time.perf_counter() - start_time
                logger.info(
                    f"⏱️  get_random_image_from_gallery_weighted: {total_duration:.3f}s (gallery: {gallery_id}, selected: {selected_category}, actual: {actual_category}, fallback: {used_fallback}, no-rating-filter)"
                )
                return image
        except Exception as e:
            logger.warning(
                f"Ошибка при получении изображения без фильтра по рейтингу для галереи {gallery_id}: {e}"
            )

        # Если и это не помогло, возвращаем None
        total_duration = time.perf_counter() - start_time
        logger.warning(
            f"⏱️  get_random_image_from_gallery_weighted: не найдено изображений в галерее {gallery_id} после {total_duration:.3f}s (все категории пусты и fallback не помог)"
        )

        # Обновляем метрики (даже если ничего не найдено)
        if self.category_metrics:
            self.category_metrics.update_category_metrics(
                gallery_id, selected_category, "none", used_fallback=False
            )

        return None

    async def get_random_image_weighted(
        self,
        exclude_ids: list[str] | None = None,
        blacklisted_performers: list[str] | None = None,
        blacklisted_galleries: list[str] | None = None,
        whitelisted_performers: list[str] | None = None,
        whitelisted_galleries: list[str] | None = None,
        max_retries: int = 3,
    ) -> StashImage | None:
        """
        Получение случайного изображения с учетом предпочтений.

        Args:
            exclude_ids: Список ID изображений для исключения
            blacklisted_performers: Список ID перформеров для исключения
            blacklisted_galleries: Список ID галерей для исключения
            whitelisted_performers: Список ID предпочитаемых перформеров
            whitelisted_galleries: Список ID предпочитаемых галерей
            max_retries: Максимальное количество попыток

        Returns:
            Optional[StashImage]: Случайное изображение или None
        """
        start_time = time.perf_counter()

        blacklisted_performers = blacklisted_performers or []
        blacklisted_galleries = blacklisted_galleries or []
        whitelisted_performers = whitelisted_performers or []
        whitelisted_galleries = whitelisted_galleries or []
        exclude_ids = exclude_ids or []

        attempts_made = 0
        for attempt in range(max_retries):
            attempts_made += 1
            try:
                image = await self.get_random_image(exclude_ids)
                if not image:
                    logger.warning(
                        f"Попытка {attempt + 1}/{max_retries}: изображение не найдено"
                    )
                    continue

                # Проверяем blacklist для галерей
                if image.gallery_id and image.gallery_id in blacklisted_galleries:
                    logger.debug(
                        f"Изображение {image.id} исключено: галерея в blacklist"
                    )
                    exclude_ids.append(image.id)
                    continue

                # Проверяем blacklist для перформеров
                performer_ids = [p["id"] for p in image.performers]
                if any(pid in blacklisted_performers for pid in performer_ids):
                    logger.debug(
                        f"Изображение {image.id} исключено: перформер в blacklist"
                    )
                    exclude_ids.append(image.id)
                    continue

                # Приоритизируем whitelist
                is_whitelisted = False
                if image.gallery_id and image.gallery_id in whitelisted_galleries:
                    is_whitelisted = True
                    logger.debug(f"Изображение {image.id} из предпочитаемой галереи")

                if any(pid in whitelisted_performers for pid in performer_ids):
                    is_whitelisted = True
                    logger.debug(f"Изображение {image.id} с предпочитаемым перформером")

                # Если есть whitelist и изображение не в нем, пропускаем с вероятностью 50%
                if (
                    whitelisted_performers or whitelisted_galleries
                ) and not is_whitelisted:
                    if random.random() < 0.5:
                        logger.debug(
                            f"Изображение {image.id} пропущено: не в whitelist"
                        )
                        exclude_ids.append(image.id)
                        continue

                duration = time.perf_counter() - start_time
                logger.info(
                    f"⏱️  get_random_image_weighted: {duration:.3f}s ({attempts_made} attempts)"
                )
                return image

            except Exception as e:
                logger.error(f"Попытка {attempt + 1}/{max_retries} не удалась: {e}")

        duration = time.perf_counter() - start_time
        logger.error(
            f"⏱️  get_random_image_weighted failed after {duration:.3f}s ({attempts_made} attempts)"
        )
        return None

    async def get_image_by_id(self, image_id: str) -> StashImage | None:
        """
        Получение изображения по ID из StashApp.

        Args:
            image_id: ID изображения

        Returns:
            Optional[StashImage]: Изображение или None при ошибке
        """
        start_time = time.perf_counter()

        query = """
        query GetImageById($id: ID!) {
          findImage(id: $id) {
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
            }
            performers {
              id
              name
            }
            details
          }
        }
        """

        variables = {"id": image_id}

        try:
            query_start = time.perf_counter()
            data = await self.client.execute_query(query, variables)
            query_duration = time.perf_counter() - query_start

            image_data = data.get("findImage")

            if not image_data:
                logger.warning(f"Изображение {image_id} не найдено в StashApp")
                return None

            image = StashImage(image_data)

            total_duration = time.perf_counter() - start_time
            logger.info(
                f"⏱️  get_image_by_id: {total_duration:.3f}s (query: {query_duration:.3f}s, image: {image_id})"
            )
            return image

        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(
                f"⏱️  get_image_by_id failed after {duration:.3f}s (image: {image_id}): {e}"
            )
            return None
