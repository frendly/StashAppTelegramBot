"""Клиент для работы с StashApp GraphQL API."""

import aiohttp
import logging
import random
import time
from typing import List, Optional, Dict, Any

from bot.performance import timing_decorator

logger = logging.getLogger(__name__)


def select_gallery_by_weight(weights_dict: Dict[str, float]) -> Optional[str]:
    """
    Взвешенный случайный выбор галереи на основе весов.
    
    Алгоритм:
    1. Вычисляет сумму всех весов
    2. Генерирует случайное число от 0 до суммы
    3. Проходит по галереям, накапливая веса, пока не превысит случайное число
    
    Args:
        weights_dict: Словарь {gallery_id: weight} с весами галерей
        
    Returns:
        Optional[str]: ID выбранной галереи или None если словарь пуст
    """
    if not weights_dict:
        return None
    
    # Вычисляем сумму всех весов
    total_weight = sum(weights_dict.values())
    
    if total_weight <= 0:
        logger.warning("Сумма весов галерей <= 0, невозможно выбрать галерею")
        return None
    
    # Генерируем случайное число от 0 до суммы весов
    random_value = random.uniform(0, total_weight)
    
    # Проходим по галереям, накапливая веса
    accumulated_weight = 0.0
    for gallery_id, weight in weights_dict.items():
        accumulated_weight += weight
        if random_value <= accumulated_weight:
            logger.debug(f"Выбрана галерея {gallery_id} с весом {weight:.3f} (random={random_value:.3f}, total={total_weight:.3f})")
            return gallery_id
    
    # На всякий случай (не должно произойти из-за floating point ошибок)
    # Возвращаем последнюю галерею
    last_gallery_id = list(weights_dict.keys())[-1]
    logger.warning(f"Floating point edge case: возвращаем последнюю галерею {last_gallery_id}")
    return last_gallery_id


class StashImage:
    """Класс представляющий изображение из StashApp."""
    
    def __init__(self, data: Dict[str, Any]):
        """
        Инициализация объекта изображения.
        
        Args:
            data: Данные изображения из GraphQL ответа
        """
        self.id = data['id']
        self.title = data.get('title', 'Без названия')
        self.rating = data.get('rating100', 0)
        
        # Сохраняем все варианты качества для возможности выбора
        paths = data.get('paths', {})
        self._thumbnail_url = paths.get('thumbnail', '')
        self._preview_url = paths.get('preview', '')
        self._image_url = paths.get('image', '')
        
        # По умолчанию используем thumbnail для максимально быстрой загрузки
        self.image_url = self._thumbnail_url or self._preview_url or self._image_url
        
        # Теги опциональны (могут не запрашиваться для ускорения)
        self.tags = [tag['name'] for tag in data.get('tags', [])]
        
        # Информация о галерее
        galleries = data.get('galleries', [])
        self.gallery_id = galleries[0]['id'] if galleries else None
        self.gallery_title = galleries[0]['title'] if galleries else None
        
        # Информация о перформерах
        self.performers = [
            {'id': p['id'], 'name': p['name']} 
            for p in data.get('performers', [])
        ]
    
    def get_image_url(self, use_high_quality: bool = False) -> str:
        """
        Получение URL изображения с указанным качеством.
        
        Args:
            use_high_quality: Если True, использует preview (или image если preview нет)
                            Если False, использует thumbnail (быстро, низкое качество)
        
        Returns:
            str: URL изображения
        """
        if use_high_quality:
            # Для высокого качества используем preview, fallback на image
            return self._preview_url or self._image_url or self._thumbnail_url
        else:
            # Для быстрой загрузки используем thumbnail, fallback на preview и image
            return self._thumbnail_url or self._preview_url or self._image_url
    
    def __repr__(self):
        return f"StashImage(id={self.id}, title={self.title}, rating={self.rating}, gallery={self.gallery_title})"


class StashClient:
    """Клиент для взаимодействия с StashApp GraphQL API."""
    
    def __init__(self, api_url: str, api_key: Optional[str] = None,
                 username: Optional[str] = None, password: Optional[str] = None):
        """
        Инициализация клиента.
        
        Args:
            api_url: URL GraphQL API StashApp
            api_key: API ключ для авторизации (опционально)
            username: Имя пользователя для Basic Auth (опционально)
            password: Пароль для Basic Auth (опционально)
        """
        self.api_url = api_url
        self.api_key = api_key
        self.username = username
        self.password = password
        self.session: Optional[aiohttp.ClientSession] = None
        self.auth: Optional[aiohttp.BasicAuth] = None
        
        # Метрики для отслеживания распределения категорий
        # Структура: {gallery_id: {"selected": {"unrated": 0, "positive": 0, "negative": 0},
        #                          "actual": {"unrated": 0, "positive": 0, "negative": 0, "none": 0},
        #                          "fallback": 0}}
        self._category_metrics: Dict[str, Dict[str, Any]] = {}
        
        # Создаем BasicAuth если есть логин/пароль
        if self.username and self.password:
            self.auth = aiohttp.BasicAuth(self.username, self.password)
            logger.info("Basic Authentication включен")
    
    async def __aenter__(self):
        """Создание HTTP сессии."""
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрытие HTTP сессии."""
        if self.session:
            await self.session.close()
    
    def _get_headers(self) -> Dict[str, str]:
        """
        Получение заголовков для запроса.
        
        Returns:
            Dict[str, str]: Заголовки запроса
        """
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["ApiKey"] = self.api_key
        return headers
    
    async def _execute_query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Выполнение GraphQL запроса.
        
        Args:
            query: GraphQL запрос
            variables: Переменные для запроса
            
        Returns:
            Dict[str, Any]: Результат запроса
            
        Raises:
            RuntimeError: Если HTTP сессия не инициализирована
            aiohttp.ClientResponseError: При HTTP ошибках (4xx, 5xx)
            Exception: При GraphQL ошибках в ответе
        """
        if not self.session:
            raise RuntimeError("HTTP сессия не инициализирована. Используйте async with.")
        
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        
        start_time = time.perf_counter()
        try:
            async with self.session.post(
                self.api_url,
                json=payload,
                headers=self._get_headers(),
                auth=self.auth
            ) as response:
                duration = time.perf_counter() - start_time
                
                # Пытаемся прочитать ответ как JSON
                try:
                    data = await response.json()
                except Exception:
                    # Если ответ не JSON, читаем как текст для логирования
                    try:
                        text_response = await response.text()
                        logger.error(f"⏱️  GraphQL query failed after {duration:.3f}s: HTTP {response.status}, non-JSON response: {text_response[:500]}")
                    except Exception:
                        logger.error(f"⏱️  GraphQL query failed after {duration:.3f}s: HTTP {response.status}, failed to read response body")
                    # Выбрасываем HTTP ошибку (выбросит aiohttp.ClientResponseError при статусе >= 400)
                    response.raise_for_status()
                    # Если статус < 400, но ответ не JSON - это тоже ошибка для GraphQL API
                    raise Exception(f"GraphQL API вернул не-JSON ответ при статусе {response.status}")
                
                # Проверяем HTTP ошибки и GraphQL ошибки
                error_details = data.get('errors', [])
                
                if response.status >= 400:
                    # HTTP ошибка (4xx, 5xx)
                    if error_details:
                        error_msg = error_details[0].get('message', 'Unknown error')
                        logger.error(f"⏱️  GraphQL query failed after {duration:.3f}s: HTTP {response.status}, GraphQL error: {error_msg}")
                        logger.debug(f"Full error response: {data}")
                    else:
                        logger.error(f"⏱️  GraphQL query failed after {duration:.3f}s: HTTP {response.status}, response: {data}")
                    # Выбрасываем HTTP ошибку
                    response.raise_for_status()
                elif error_details:
                    # GraphQL ошибка при успешном HTTP ответе (200 OK)
                    error_msg = error_details[0].get('message', 'Unknown error')
                    logger.error(f"⏱️  GraphQL query failed after {duration:.3f}s: GraphQL error: {error_msg}")
                    logger.debug(f"Full error response: {data}")
                    raise Exception(f"GraphQL error: {error_msg}")
                
                logger.debug(f"⏱️  GraphQL query executed: {duration:.3f}s")
                
                return data.get('data', {})
        
        except aiohttp.ClientError as e:
            duration = time.perf_counter() - start_time
            logger.error(f"⏱️  GraphQL query failed after {duration:.3f}s: {e}")
            raise Exception(f"Не удалось подключиться к StashApp: {e}")
    
    async def get_random_image(self, exclude_ids: Optional[List[str]] = None) -> Optional[StashImage]:
        """
        Получение случайного изображения.
        
        Args:
            exclude_ids: Список ID изображений для исключения
            
        Returns:
            Optional[StashImage]: Случайное изображение или None
        """
        start_time = time.perf_counter()
        
        # Запрос с thumbnail для оптимизации скорости загрузки
        # Уменьшено до 20 изображений и убраны теги для ускорения
        query = """
        query FindRandomImage {
          findImages(
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
              }
              performers {
                id
                name
              }
            }
          }
        }
        """
        
        try:
            query_start = time.perf_counter()
            data = await self._execute_query(query)
            query_duration = time.perf_counter() - query_start
            
            images = data.get('findImages', {}).get('images', [])
            
            if not images:
                logger.warning("Случайное изображение не найдено")
                return None
            
            # Локальная фильтрация: исключаем изображения из exclude_ids
            filter_start = time.perf_counter()
            if exclude_ids:
                exclude_set = set(exclude_ids)
                filtered_images = [img for img in images if img['id'] not in exclude_set]
                filter_duration = time.perf_counter() - filter_start
                logger.debug(f"Получено {len(images)} изображений, после фильтрации: {len(filtered_images)} ({filter_duration:.3f}s)")
                
                if not filtered_images:
                    logger.warning("После фильтрации не осталось изображений")
                    return None
                
                images = filtered_images
            
            # Возвращаем первое подходящее изображение
            image_data = images[0]
            image = StashImage(image_data)
            
            total_duration = time.perf_counter() - start_time
            logger.info(f"⏱️  get_random_image: {total_duration:.3f}s (query: {query_duration:.3f}s)")
            return image
        
        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(f"⏱️  get_random_image failed after {duration:.3f}s: {e}")
            return None
    
    async def get_random_image_with_retry(
        self, 
        exclude_ids: Optional[List[str]] = None,
        max_retries: int = 3
    ) -> Optional[StashImage]:
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
                logger.warning(f"Попытка {attempt + 1}/{max_retries}: изображение не найдено")
            except Exception as e:
                logger.error(f"Попытка {attempt + 1}/{max_retries} не удалась: {e}")
        
        logger.error(f"Не удалось получить изображение после {max_retries} попыток")
        return None
    
    async def get_images_from_gallery_by_rating(
        self,
        gallery_id: str,
        rating_filter: str,
        exclude_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
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
              }
              performers {
                id
                name
              }
            }
          }
        }
        """
        
        variables = {
            "gallery_id": gallery_id,
            "rating_value": rating_value,
            "rating_modifier": rating_modifier
        }
        
        try:
            query_start = time.perf_counter()
            data = await self._execute_query(query, variables)
            query_duration = time.perf_counter() - query_start
            
            images = data.get('findImages', {}).get('images', [])
            
            # Локальная фильтрация: исключаем изображения из exclude_ids
            if exclude_ids:
                exclude_set = set(exclude_ids)
                images = [img for img in images if img['id'] not in exclude_set]
            
            total_duration = time.perf_counter() - start_time
            logger.debug(f"⏱️  get_images_from_gallery_by_rating: {total_duration:.3f}s (query: {query_duration:.3f}s, gallery: {gallery_id}, filter: {rating_filter}, found: {len(images)})")
            return images
        
        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(f"⏱️  get_images_from_gallery_by_rating failed after {duration:.3f}s (gallery: {gallery_id}, filter: {rating_filter}): {e}")
            return []
    
    async def get_random_image_from_gallery(
        self,
        gallery_id: str,
        exclude_ids: Optional[List[str]] = None
    ) -> Optional[StashImage]:
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
              }
              performers {
                id
                name
              }
            }
          }
        }
        """
        
        variables = {
            "gallery_id": gallery_id
        }
        
        try:
            query_start = time.perf_counter()
            data = await self._execute_query(query, variables)
            query_duration = time.perf_counter() - query_start
            
            images = data.get('findImages', {}).get('images', [])
            
            if not images:
                logger.warning(f"Случайное изображение не найдено в галерее {gallery_id}")
                return None
            
            # Локальная фильтрация: исключаем изображения из exclude_ids
            filter_start = time.perf_counter()
            if exclude_ids:
                exclude_set = set(exclude_ids)
                filtered_images = [img for img in images if img['id'] not in exclude_set]
                filter_duration = time.perf_counter() - filter_start
                logger.debug(f"Получено {len(images)} изображений из галереи {gallery_id}, после фильтрации: {len(filtered_images)} ({filter_duration:.3f}s)")
                
                if not filtered_images:
                    logger.warning(f"После фильтрации не осталось изображений в галерее {gallery_id}")
                    return None
                
                images = filtered_images
            
            # Возвращаем первое подходящее изображение
            image_data = images[0]
            image = StashImage(image_data)
            
            total_duration = time.perf_counter() - start_time
            logger.info(f"⏱️  get_random_image_from_gallery: {total_duration:.3f}s (query: {query_duration:.3f}s, gallery: {gallery_id})")
            return image
        
        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(f"⏱️  get_random_image_from_gallery failed after {duration:.3f}s (gallery: {gallery_id}): {e}")
            return None
    
    def _update_category_metrics(self, gallery_id: str, selected_category: str, actual_category: str, used_fallback: bool = False):
        """
        Обновление метрик распределения категорий.
        
        Args:
            gallery_id: ID галереи
            selected_category: Выбранная категория (по приоритетам)
            actual_category: Фактически использованная категория
            used_fallback: Использовался ли fallback
        """
        if gallery_id not in self._category_metrics:
            self._category_metrics[gallery_id] = {
                "selected": {"unrated": 0, "positive": 0, "negative": 0},
                "actual": {"unrated": 0, "positive": 0, "negative": 0, "none": 0},
                "fallback": 0
            }
        
        metrics = self._category_metrics[gallery_id]
        
        # Обновляем счетчик выбранной категории
        if selected_category in metrics["selected"]:
            metrics["selected"][selected_category] += 1
        
        # Обновляем счетчик фактически использованной категории
        if actual_category in metrics["actual"]:
            metrics["actual"][actual_category] += 1
        
        # Обновляем счетчик fallback
        if used_fallback:
            metrics["fallback"] += 1
    
    def get_category_metrics(self, gallery_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Получение метрик распределения категорий.
        
        Args:
            gallery_id: ID галереи (опционально, если None - возвращает все метрики)
            
        Returns:
            Dict: Метрики распределения категорий
        """
        if gallery_id:
            return self._category_metrics.get(gallery_id, {
                "selected": {"unrated": 0, "positive": 0, "negative": 0},
                "actual": {"unrated": 0, "positive": 0, "negative": 0, "none": 0},
                "fallback": 0
            })
        return self._category_metrics.copy()
    
    def log_category_metrics(self, gallery_id: Optional[str] = None):
        """
        Логирование метрик распределения категорий.
        
        Args:
            gallery_id: ID галереи (опционально, если None - логирует все метрики)
        """
        if gallery_id:
            metrics = self._category_metrics.get(gallery_id)
            if not metrics:
                logger.info(f"📊 Метрики для галереи {gallery_id}: нет данных")
                return
            
            selected = metrics["selected"]
            actual = metrics["actual"]
            fallback = metrics["fallback"]
            
            total_selected = sum(selected.values())
            total_actual = sum(actual.values())
            
            if total_selected > 0:
                selected_pct = {k: (v / total_selected * 100) for k, v in selected.items()}
                actual_pct = {k: (v / total_actual * 100) if total_actual > 0 else 0 for k, v in actual.items()}
                fallback_pct = (fallback / total_selected * 100) if total_selected > 0 else 0
                
                # Формируем строку для фактических категорий (исключаем "none" из процентов, но показываем отдельно)
                actual_total_with_images = total_actual - actual.get("none", 0)
                actual_pct_with_images = {k: (v / actual_total_with_images * 100) if actual_total_with_images > 0 else 0 
                                         for k, v in actual.items() if k != "none"}
                
                logger.info(
                    f"📊 Метрики для галереи {gallery_id}:\n"
                    f"  Выбрано: unrated={selected['unrated']} ({selected_pct['unrated']:.1f}%), "
                    f"positive={selected['positive']} ({selected_pct['positive']:.1f}%), "
                    f"negative={selected['negative']} ({selected_pct['negative']:.1f}%)\n"
                    f"  Фактически: unrated={actual['unrated']} ({actual_pct_with_images.get('unrated', 0):.1f}%), "
                    f"positive={actual['positive']} ({actual_pct_with_images.get('positive', 0):.1f}%), "
                    f"negative={actual['negative']} ({actual_pct_with_images.get('negative', 0):.1f}%), "
                    f"none={actual.get('none', 0)}\n"
                    f"  Fallback: {fallback} ({fallback_pct:.1f}%)"
                )
            else:
                logger.info(f"📊 Метрики для галереи {gallery_id}: нет данных")
        else:
            # Логируем все метрики
            if not self._category_metrics:
                logger.info("📊 Метрики распределения категорий: нет данных")
                return
            
            logger.info("📊 Метрики распределения категорий по всем галереям:")
            for gid, metrics in self._category_metrics.items():
                selected = metrics["selected"]
                actual = metrics["actual"]
                fallback = metrics["fallback"]
                
                total_selected = sum(selected.values())
                total_actual = sum(actual.values())
                
                if total_selected > 0:
                    selected_pct = {k: (v / total_selected * 100) for k, v in selected.items()}
                    actual_total_with_images = total_actual - actual.get("none", 0)
                    actual_pct_with_images = {k: (v / actual_total_with_images * 100) if actual_total_with_images > 0 else 0 
                                             for k, v in actual.items() if k != "none"}
                    fallback_pct = (fallback / total_selected * 100) if total_selected > 0 else 0
                    
                    logger.info(
                        f"  Галерея {gid}: выбрано={total_selected} (unrated={selected_pct['unrated']:.1f}%, "
                        f"positive={selected_pct['positive']:.1f}%, negative={selected_pct['negative']:.1f}%), "
                        f"фактически={actual_total_with_images} (unrated={actual_pct_with_images.get('unrated', 0):.1f}%, "
                        f"positive={actual_pct_with_images.get('positive', 0):.1f}%, negative={actual_pct_with_images.get('negative', 0):.1f}%, "
                        f"none={actual.get('none', 0)}), fallback={fallback_pct:.1f}%"
                    )
    
    def reset_category_metrics(self, gallery_id: Optional[str] = None):
        """
        Сброс метрик распределения категорий.
        
        Args:
            gallery_id: ID галереи (опционально, если None - сбрасывает все метрики)
        """
        if gallery_id:
            if gallery_id in self._category_metrics:
                del self._category_metrics[gallery_id]
                logger.debug(f"Метрики для галереи {gallery_id} сброшены")
        else:
            self._category_metrics.clear()
            logger.debug("Все метрики распределения категорий сброшены")
    
    async def get_random_image_from_gallery_weighted(
        self,
        gallery_id: str,
        exclude_ids: Optional[List[str]] = None
    ) -> Optional[StashImage]:
        """
        Получение случайного изображения из галереи с учетом приоритетов по рейтингу.
        
        Приоритеты:
        - 70% неоцененные изображения (rating100 IS NULL)
        - 20% изображения с "+" (rating100 >= 80)
        - 10% изображения с "-" (rating100 <= 20)
        
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
        
        for idx, category in enumerate([selected_category] + [c for c in fallback_order if c != selected_category]):
            try:
                images = await self.get_images_from_gallery_by_rating(
                    gallery_id=gallery_id,
                    rating_filter=category,
                    exclude_ids=exclude_ids
                )
                
                if images:
                    # Если это не первая попытка (не выбранная категория), значит использовался fallback
                    if idx > 0:
                        used_fallback = True
                        logger.info(f"🔄 Fallback: категория '{selected_category}' пуста, использована '{category}' для галереи {gallery_id}")
                    
                    actual_category = category
                    
                    # Выбираем случайное изображение из списка
                    image_data = random.choice(images)
                    image = StashImage(image_data)
                    
                    # Обновляем метрики
                    self._update_category_metrics(gallery_id, selected_category, actual_category, used_fallback)
                    
                    total_duration = time.perf_counter() - start_time
                    logger.info(f"⏱️  get_random_image_from_gallery_weighted: {total_duration:.3f}s (gallery: {gallery_id}, selected: {selected_category}, actual: {actual_category}, fallback: {used_fallback})")
                    return image
                else:
                    logger.debug(f"Категория {category} пуста для галереи {gallery_id}, пробуем следующую")
            
            except Exception as e:
                logger.warning(f"Ошибка при получении изображений из категории {category} для галереи {gallery_id}: {e}")
                continue
        
        # Если все категории пустые, возвращаем None
        total_duration = time.perf_counter() - start_time
        logger.warning(f"⏱️  get_random_image_from_gallery_weighted: не найдено изображений в галерее {gallery_id} после {total_duration:.3f}s (все категории пусты)")
        
        # Обновляем метрики (даже если ничего не найдено)
        self._update_category_metrics(gallery_id, selected_category, "none", used_fallback=False)
        
        return None
    
    async def download_image(self, image_url: str) -> Optional[bytes]:
        """
        Скачивание изображения по URL.
        
        Args:
            image_url: URL изображения
            
        Returns:
            Optional[bytes]: Данные изображения или None
        """
        if not self.session:
            raise RuntimeError("HTTP сессия не инициализирована")
        
        start_time = time.perf_counter()
        try:
            # Добавляем API Key в URL как query параметр, если он есть
            download_url = image_url
            if self.api_key:
                separator = '&' if '?' in image_url else '?'
                download_url = f"{image_url}{separator}apikey={self.api_key}"
            
            async with self.session.get(download_url, auth=self.auth) as response:
                response.raise_for_status()
                image_data = await response.read()
                duration = time.perf_counter() - start_time
                size_kb = len(image_data) / 1024
                logger.info(f"⏱️  Image download: {duration:.3f}s ({size_kb:.1f} KB, {size_kb/duration:.1f} KB/s)")
                return image_data
        
        except aiohttp.ClientError as e:
            duration = time.perf_counter() - start_time
            logger.error(f"⏱️  Image download failed after {duration:.3f}s: {e}")
            return None
    
    async def test_connection(self) -> bool:
        """
        Проверка подключения к StashApp API.
        
        Returns:
            bool: True если подключение успешно
        """
        query = """
        query {
          findImages(filter: { per_page: 1 }) {
            count
          }
        }
        """
        
        try:
            data = await self._execute_query(query)
            count = data.get('findImages', {}).get('count', 0)
            logger.info(f"Подключение к StashApp успешно. Всего изображений: {count}")
            return True
        except Exception as e:
            logger.error(f"Не удалось подключиться к StashApp: {e}")
            return False
    
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
        
        variables = {
            "id": image_id,
            "rating": rating100
        }
        
        try:
            data = await self._execute_query(mutation, variables)
            if data.get('imageUpdate'):
                logger.info(f"Рейтинг изображения {image_id} обновлен на {rating}/5 ({rating100}/100)")
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
        
        variables = {
            "id": gallery_id,
            "rating": rating100
        }
        
        try:
            data = await self._execute_query(mutation, variables)
            if data.get('galleryUpdate'):
                logger.info(f"Рейтинг галереи {gallery_id} обновлен на {rating}/5 ({rating100}/100)")
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка при обновлении рейтинга галереи {gallery_id}: {e}")
            return False
    
    async def get_gallery_image_count(self, gallery_id: str) -> Optional[int]:
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
        
        variables = {
            "id": gallery_id
        }
        
        try:
            data = await self._execute_query(query, variables)
            gallery = data.get('findGallery')
            
            if gallery and 'image_count' in gallery:
                count = gallery['image_count']
                logger.debug(f"Количество изображений в галерее {gallery_id}: {count}")
                return count
            
            logger.warning(f"Галерея {gallery_id} не найдена или не содержит image_count")
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении количества изображений для галереи {gallery_id}: {e}")
            return None
    
    async def get_random_image_weighted(
        self,
        exclude_ids: Optional[List[str]] = None,
        blacklisted_performers: Optional[List[str]] = None,
        blacklisted_galleries: Optional[List[str]] = None,
        whitelisted_performers: Optional[List[str]] = None,
        whitelisted_galleries: Optional[List[str]] = None,
        max_retries: int = 3
    ) -> Optional[StashImage]:
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
                    logger.warning(f"Попытка {attempt + 1}/{max_retries}: изображение не найдено")
                    continue
                
                # Проверяем blacklist для галерей
                if image.gallery_id and image.gallery_id in blacklisted_galleries:
                    logger.debug(f"Изображение {image.id} исключено: галерея в blacklist")
                    exclude_ids.append(image.id)
                    continue
                
                # Проверяем blacklist для перформеров
                performer_ids = [p['id'] for p in image.performers]
                if any(pid in blacklisted_performers for pid in performer_ids):
                    logger.debug(f"Изображение {image.id} исключено: перформер в blacklist")
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
                if (whitelisted_performers or whitelisted_galleries) and not is_whitelisted:
                    import random
                    if random.random() < 0.5:
                        logger.debug(f"Изображение {image.id} пропущено: не в whitelist")
                        exclude_ids.append(image.id)
                        continue
                
                duration = time.perf_counter() - start_time
                logger.info(f"⏱️  get_random_image_weighted: {duration:.3f}s ({attempts_made} attempts)")
                return image
                
            except Exception as e:
                logger.error(f"Попытка {attempt + 1}/{max_retries} не удалась: {e}")
        
        duration = time.perf_counter() - start_time
        logger.error(f"⏱️  get_random_image_weighted failed after {duration:.3f}s ({attempts_made} attempts)")
        return None