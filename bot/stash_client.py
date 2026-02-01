"""Клиент для работы с StashApp GraphQL API."""

import asyncio
import aiohttp
import logging
import random
import time
from typing import List, Optional, Dict, Any

from bot.performance import timing_decorator

logger = logging.getLogger(__name__)


def select_gallery_by_weight(
    weights_dict: Dict[str, float],
    all_galleries: Optional[List[Dict[str, Any]]] = None,
    gallery_stats: Optional[Dict[str, Dict[str, Any]]] = None,
    excluded_galleries: Optional[set] = None
) -> Optional[str]:
    """
    Взвешенный случайный выбор галереи с учетом всех галерей из StashApp,
    просмотренности и свежести.
    
    Алгоритм:
    1. Если передан список всех галерей, использует его (включая галереи без записей в БД)
    2. Для каждой галереи вычисляет модифицированный вес с учетом:
       - Базового веса из БД (или 1.0 по умолчанию)
       - Штрафа за просмотренность (чем больше просмотрено, тем меньше вес)
       - Бонуса за свежесть (чем дольше не выбиралась, тем больше вес)
    3. Выполняет взвешенный случайный выбор
    
    Args:
        weights_dict: Словарь {gallery_id: weight} с весами из БД
        all_galleries: Список всех галерей из StashApp [{id, title, image_count}]
        gallery_stats: Статистика по галереям {gallery_id: {viewed: int, total: int, last_selected: float}}
        excluded_galleries: Множество ID исключенных галерей (опционально)
        
    Returns:
        Optional[str]: ID выбранной галереи или None если словарь пуст
    """
    # Если список всех галерей не передан, используем старую логику (только галереи из БД)
    if not all_galleries:
        if not weights_dict:
            return None
        
        total_weight = sum(weights_dict.values())
        if total_weight <= 0:
            logger.warning("Сумма весов галерей <= 0, невозможно выбрать галерею")
            return None
        
        random_value = random.uniform(0, total_weight)
        accumulated_weight = 0.0
        for gallery_id, weight in weights_dict.items():
            accumulated_weight += weight
            if random_value <= accumulated_weight:
                logger.debug(f"Выбрана галерея {gallery_id} с весом {weight:.3f} (random={random_value:.3f}, total={total_weight:.3f})")
                return gallery_id
        
        last_gallery_id = list(weights_dict.keys())[-1]
        logger.warning(f"Floating point edge case: возвращаем последнюю галерею {last_gallery_id}")
        return last_gallery_id
    
    # Новая логика: работаем со всеми галереями из StashApp
    gallery_stats = gallery_stats or {}
    excluded_galleries = excluded_galleries or set()
    current_time = time.time()
    modified_weights = {}
    
    # Проходим по всем галереям из StashApp
    for gallery in all_galleries:
        gallery_id = gallery['id']
        
        # Пропускаем исключенные галереи
        if gallery_id in excluded_galleries:
            logger.debug(f"Пропускаем исключенную галерею {gallery_id}")
            continue
        
        total_images = gallery.get('image_count', 0)
        
        # Получаем вес из БД или используем 1.0 по умолчанию
        base_weight = weights_dict.get(gallery_id, 1.0)
        
        # Если вес равен 0 или отрицательный, пропускаем (возможно, галерея исключена)
        if base_weight <= 0:
            logger.debug(f"Пропускаем галерею {gallery_id} с неположительным весом {base_weight}")
            continue
        
        # Получаем статистику
        stats = gallery_stats.get(gallery_id, {})
        viewed = stats.get('viewed', 0)
        last_selected = stats.get('last_selected', 0)
        
        # 1. Штраф за просмотренность (чем больше просмотрено, тем меньше вес)
        if total_images > 0:
            coverage_ratio = viewed / total_images  # 0.0 - 1.0
            # Если просмотрено 50%, вес уменьшается на 25%
            # Если просмотрено 100%, вес уменьшается на 50%
            coverage_penalty = 1.0 - (coverage_ratio * 0.5)
        else:
            coverage_ratio = 0.0  # Для логирования
            coverage_penalty = 1.0
        
        # 2. Бонус за свежесть (время с последнего выбора)
        if last_selected == 0:
            days_since = 999  # Никогда не выбиралась - максимальный бонус
        else:
            days_since = (current_time - last_selected) / 86400
        
        # Бонус: +50% за каждый день без выбора (макс +200% за 4+ дня)
        freshness_bonus = min(days_since * 0.5, 2.0)
        freshness_multiplier = 1.0 + freshness_bonus
        
        # Финальный вес
        modified_weight = base_weight * coverage_penalty * freshness_multiplier
        
        # Проверяем, что вес не стал отрицательным или нулевым
        if modified_weight <= 0:
            logger.debug(f"Пропускаем галерею {gallery_id} с нулевым/отрицательным модифицированным весом")
            continue
        
        modified_weights[gallery_id] = modified_weight
        
        logger.debug(
            f"Галерея {gallery.get('title', gallery_id)}: base={base_weight:.2f}, "
            f"viewed={viewed}/{total_images}, coverage={coverage_ratio*100:.1f}%, "
            f"days_since={days_since:.1f}, final={modified_weight:.2f}"
        )
    
    # Стандартный алгоритм взвешенного выбора
    total_weight = sum(modified_weights.values())
    if total_weight <= 0:
        logger.warning("Сумма модифицированных весов <= 0")
        return None
    
    random_value = random.uniform(0, total_weight)
    accumulated_weight = 0.0
    
    for gallery_id, weight in modified_weights.items():
        accumulated_weight += weight
        if random_value <= accumulated_weight:
            # Находим название галереи для лога
            gallery_title = next(
                (g.get('title', gallery_id) for g in all_galleries if g['id'] == gallery_id),
                gallery_id
            )
            logger.info(
                f"Выбрана галерея {gallery_title} ({gallery_id}) "
                f"с модифицированным весом {weight:.3f} "
                f"(random={random_value:.3f}, total={total_weight:.3f})"
            )
            return gallery_id
    
    # Fallback
    last_gallery_id = list(modified_weights.keys())[-1]
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
        
        # Кэш для списка всех галерей
        self._all_galleries_cache: Optional[List[Dict[str, Any]]] = None
        self._galleries_cache_time: float = 0
        self._galleries_cache_ttl: int = 3600  # 1 час
        
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
                except asyncio.CancelledError:
                    # Пробрасываем CancelledError дальше
                    raise
                except Exception:
                    # Если ответ не JSON, читаем как текст для логирования
                    try:
                        text_response = await response.text()
                        logger.error(f"⏱️  GraphQL query failed after {duration:.3f}s: HTTP {response.status}, non-JSON response: {text_response[:500]}")
                    except asyncio.CancelledError:
                        # Пробрасываем CancelledError дальше
                        raise
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
        
        except asyncio.CancelledError:
            # Пробрасываем CancelledError дальше - это нормальная часть механизма отмены задач
            duration = time.perf_counter() - start_time
            logger.debug(f"GraphQL query cancelled after {duration:.3f}s")
            raise
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
                "actual": {"unrated": 0, "positive": 0, "negative": 0, "any": 0, "none": 0},
                "fallback": 0
            }
        
        metrics = self._category_metrics[gallery_id]
        
        # Обновляем счетчик выбранной категории
        if selected_category in metrics["selected"]:
            metrics["selected"][selected_category] += 1
        
        # Обновляем счетчик фактически использованной категории
        # Если категория "any" еще не существует, добавляем её
        if actual_category not in metrics["actual"]:
            metrics["actual"][actual_category] = 0
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
                "actual": {"unrated": 0, "positive": 0, "negative": 0, "any": 0, "none": 0},
                "fallback": 0
            })
        return self._category_metrics.copy()
    
    def _calculate_actual_percentages(self, actual: Dict[str, int]) -> Dict[str, float]:
        """
        Вычисление процентов для фактических категорий (исключая 'none').
        
        Args:
            actual: Словарь с количеством изображений по категориям
            
        Returns:
            Dict[str, float]: Словарь с процентами для каждой категории (кроме 'none')
        """
        actual_total_with_images = sum(v for k, v in actual.items() if k != "none")
        if actual_total_with_images == 0:
            return {k: 0.0 for k in actual.keys() if k != "none"}
        return {k: (v / actual_total_with_images * 100) for k, v in actual.items() if k != "none"}
    
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
                fallback_pct = (fallback / total_selected * 100) if total_selected > 0 else 0
                
                # Вычисляем проценты для фактических категорий (исключая "none")
                actual_pct_with_images = self._calculate_actual_percentages(actual)
                
                # Формируем строку для фактических категорий
                actual_parts = []
                for cat in ["unrated", "positive", "negative", "any"]:
                    if cat in actual:
                        count = actual[cat]
                        pct = actual_pct_with_images.get(cat, 0)
                        actual_parts.append(f"{cat}={count} ({pct:.1f}%)")
                
                logger.info(
                    f"📊 Метрики для галереи {gallery_id}:\n"
                    f"  Выбрано: unrated={selected['unrated']} ({selected_pct['unrated']:.1f}%), "
                    f"positive={selected['positive']} ({selected_pct['positive']:.1f}%), "
                    f"negative={selected['negative']} ({selected_pct['negative']:.1f}%)\n"
                    f"  Фактически: {', '.join(actual_parts)}, none={actual.get('none', 0)}\n"
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
                    fallback_pct = (fallback / total_selected * 100) if total_selected > 0 else 0
                    
                    # Вычисляем проценты для фактических категорий (исключая "none")
                    actual_pct_with_images = self._calculate_actual_percentages(actual)
                    actual_total_with_images = sum(v for k, v in actual.items() if k != "none")
                    
                    # Формируем строку для фактических категорий
                    actual_parts = []
                    for cat in ["unrated", "positive", "negative", "any"]:
                        if cat in actual:
                            count = actual[cat]
                            pct = actual_pct_with_images.get(cat, 0)
                            actual_parts.append(f"{cat}={count} ({pct:.1f}%)")
                    
                    logger.info(
                        f"  Галерея {gid}: выбрано={total_selected} (unrated={selected_pct['unrated']:.1f}%, "
                        f"positive={selected_pct['positive']:.1f}%, negative={selected_pct['negative']:.1f}%), "
                        f"фактически={actual_total_with_images} ({', '.join(actual_parts)}, "
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
        
        # Если все категории пустые, пробуем получить любое изображение из галереи без фильтра по рейтингу
        # Это нужно для случаев, когда в галерее есть изображения с рейтингом 21-79, которые не попадают
        # ни в одну из трех категорий (unrated, positive >= 80, negative <= 20)
        logger.info(f"Все категории пусты для галереи {gallery_id}, пробуем получить любое изображение без фильтра по рейтингу")
        try:
            image = await self.get_random_image_from_gallery(
                gallery_id=gallery_id,
                exclude_ids=exclude_ids
            )
            
            if image:
                used_fallback = True
                actual_category = "any"  # Специальная категория для изображений без фильтра по рейтингу
                
                # Обновляем метрики
                self._update_category_metrics(gallery_id, selected_category, actual_category, used_fallback)
                
                total_duration = time.perf_counter() - start_time
                logger.info(f"⏱️  get_random_image_from_gallery_weighted: {total_duration:.3f}s (gallery: {gallery_id}, selected: {selected_category}, actual: {actual_category}, fallback: {used_fallback}, no-rating-filter)")
                return image
        except Exception as e:
            logger.warning(f"Ошибка при получении изображения без фильтра по рейтингу для галереи {gallery_id}: {e}")
        
        # Если и это не помогло, возвращаем None
        total_duration = time.perf_counter() - start_time
        logger.warning(f"⏱️  get_random_image_from_gallery_weighted: не найдено изображений в галерее {gallery_id} после {total_duration:.3f}s (все категории пусты и fallback не помог)")
        
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
        
        except asyncio.CancelledError:
            # Пробрасываем CancelledError дальше - это нормальная часть механизма отмены задач
            duration = time.perf_counter() - start_time
            logger.debug(f"Image download cancelled after {duration:.3f}s")
            raise
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
    
    async def get_all_galleries(self) -> List[Dict[str, Any]]:
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
            data = await self._execute_query(query)
            galleries = data.get('findGalleries', {}).get('galleries', [])
            count = data.get('findGalleries', {}).get('count', 0)
            logger.info(f"Получено {len(galleries)} галерей из StashApp (всего: {count})")
            return galleries
        except Exception as e:
            logger.error(f"Ошибка при получении списка галерей: {e}")
            return []
    
    async def get_all_galleries_cached(self) -> List[Dict[str, Any]]:
        """
        Получение списка всех галерей с кэшированием.
        
        Returns:
            List[Dict]: Список галерей
        """
        current_time = time.perf_counter()
        
        # Проверяем кэш
        if (self._all_galleries_cache and 
            (current_time - self._galleries_cache_time) < self._galleries_cache_ttl):
            logger.debug(f"Используется кэшированный список галерей ({len(self._all_galleries_cache)} галерей)")
            return self._all_galleries_cache
        
        # Обновляем кэш
        galleries = await self.get_all_galleries()
        self._all_galleries_cache = galleries
        self._galleries_cache_time = current_time
        
        return galleries
    
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
    
    async def get_image_by_id(self, image_id: str) -> Optional[StashImage]:
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
            }
            performers {
              id
              name
            }
          }
        }
        """
        
        variables = {
            "id": image_id
        }
        
        try:
            query_start = time.perf_counter()
            data = await self._execute_query(query, variables)
            query_duration = time.perf_counter() - query_start
            
            image_data = data.get('findImage')
            
            if not image_data:
                logger.warning(f"Изображение {image_id} не найдено в StashApp")
                return None
            
            image = StashImage(image_data)
            
            total_duration = time.perf_counter() - start_time
            logger.info(f"⏱️  get_image_by_id: {total_duration:.3f}s (query: {query_duration:.3f}s, image: {image_id})")
            return image
        
        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(f"⏱️  get_image_by_id failed after {duration:.3f}s (image: {image_id}): {e}")
            return None