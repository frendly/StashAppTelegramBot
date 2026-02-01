"""Базовый GraphQL клиент для StashApp."""

import asyncio
import aiohttp
import logging
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class StashGraphQLClient:
    """Базовый клиент для выполнения GraphQL запросов к StashApp API."""
    
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
    
    async def execute_query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
            data = await self.execute_query(query)
            count = data.get('findImages', {}).get('count', 0)
            logger.info(f"Подключение к StashApp успешно. Всего изображений: {count}")
            return True
        except Exception as e:
            logger.error(f"Не удалось подключиться к StashApp: {e}")
            return False
