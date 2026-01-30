"""Клиент для работы с StashApp GraphQL API."""

import aiohttp
import logging
import time
from typing import List, Optional, Dict, Any

from bot.performance import timing_decorator

logger = logging.getLogger(__name__)


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
        
        # Используем thumbnail для максимально быстрой загрузки, fallback на preview и оригинал
        paths = data.get('paths', {})
        self.image_url = paths.get('thumbnail') or paths.get('preview') or paths.get('image', '')
        
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
            Exception: При ошибке запроса
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
                response.raise_for_status()
                data = await response.json()
                
                duration = time.perf_counter() - start_time
                logger.debug(f"⏱️  GraphQL query executed: {duration:.3f}s")
                
                if 'errors' in data:
                    error_msg = data['errors'][0].get('message', 'Unknown error')
                    logger.error(f"GraphQL ошибка: {error_msg}")
                    raise Exception(f"GraphQL error: {error_msg}")
                
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