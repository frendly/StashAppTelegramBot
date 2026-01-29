"""Клиент для работы с StashApp GraphQL API."""

import aiohttp
import logging
from typing import List, Optional, Dict, Any

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
        self.image_url = data.get('paths', {}).get('image', '')
        self.tags = [tag['name'] for tag in data.get('tags', [])]
    
    def __repr__(self):
        return f"StashImage(id={self.id}, title={self.title}, rating={self.rating})"


class StashClient:
    """Клиент для взаимодействия с StashApp GraphQL API."""
    
    def __init__(self, api_url: str, api_key: Optional[str] = None):
        """
        Инициализация клиента.
        
        Args:
            api_url: URL GraphQL API StashApp
            api_key: API ключ для авторизации (опционально)
        """
        self.api_url = api_url
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
    
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
        
        try:
            async with self.session.post(
                self.api_url,
                json=payload,
                headers=self._get_headers()
            ) as response:
                response.raise_for_status()
                data = await response.json()
                
                if 'errors' in data:
                    error_msg = data['errors'][0].get('message', 'Unknown error')
                    logger.error(f"GraphQL ошибка: {error_msg}")
                    raise Exception(f"GraphQL error: {error_msg}")
                
                return data.get('data', {})
        
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения с StashApp: {e}")
            raise Exception(f"Не удалось подключиться к StashApp: {e}")
    
    async def get_random_image(self, exclude_ids: Optional[List[str]] = None) -> Optional[StashImage]:
        """
        Получение случайного изображения.
        
        Args:
            exclude_ids: Список ID изображений для исключения
            
        Returns:
            Optional[StashImage]: Случайное изображение или None
        """
        query = """
        query FindRandomImage($excludeIds: [ID!]) {
          findImages(
            image_filter: {
              id: { modifier: NOT_EQUALS, value: $excludeIds }
            }
            filter: { per_page: 1, sort: "random" }
          ) {
            images {
              id
              title
              rating100
              paths {
                image
              }
              tags {
                name
              }
            }
          }
        }
        """
        
        variables = {}
        if exclude_ids:
            # GraphQL NOT_EQUALS с массивом для исключения нескольких ID
            # Альтернативный подход - получить несколько случайных и фильтровать
            logger.debug(f"Исключаем {len(exclude_ids)} изображений")
            variables = {"excludeIds": exclude_ids}
        
        try:
            data = await self._execute_query(query, variables)
            images = data.get('findImages', {}).get('images', [])
            
            if not images:
                logger.warning("Случайное изображение не найдено")
                return None
            
            image_data = images[0]
            image = StashImage(image_data)
            logger.info(f"Получено случайное изображение: {image}")
            return image
        
        except Exception as e:
            logger.error(f"Ошибка при получении случайного изображения: {e}")
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
        
        try:
            async with self.session.get(image_url, headers=self._get_headers()) as response:
                response.raise_for_status()
                image_data = await response.read()
                logger.debug(f"Изображение скачано: {len(image_data)} байт")
                return image_data
        
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка при скачивании изображения: {e}")
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
