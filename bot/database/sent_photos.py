"""Модуль для работы с таблицей sent_photos."""

import sqlite3
import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)


class SentPhotosRepository:
    """Класс для работы с таблицей sent_photos."""
    
    def __init__(self, db_path: str):
        """
        Инициализация репозитория.
        
        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path
    
    def add_sent_photo(self, image_id: str, user_id: Optional[int] = None, title: Optional[str] = None):
        """
        Добавление записи об отправленном фото.
        
        Args:
            image_id: ID изображения из StashApp
            user_id: Telegram ID пользователя (опционально)
            title: Название изображения (опционально)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sent_photos (image_id, user_id, title)
                VALUES (?, ?, ?)
            """, (image_id, user_id, title))
            conn.commit()
            logger.debug(f"Добавлена запись о фото: image_id={image_id}")
    
    def get_recent_image_ids(self, days: int) -> List[str]:
        """
        Получение списка ID изображений, отправленных за последние N дней.
        
        Args:
            days: Количество дней
            
        Returns:
            List[str]: Список ID изображений
        """
        start_time = time.perf_counter()
        cutoff_date = datetime.now() - timedelta(days=days)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT image_id 
                FROM sent_photos 
                WHERE sent_at >= ?
            """, (cutoff_date,))
            
            results = cursor.fetchall()
            image_ids = [row[0] for row in results]
            
            duration = time.perf_counter() - start_time
            logger.debug(f"⏱️  DB get_recent_image_ids: {duration:.3f}s ({len(image_ids)} items, {days} days)")
            return image_ids
    
    def is_recently_sent(self, image_id: str, days: int) -> bool:
        """
        Проверка, было ли изображение отправлено недавно.
        
        Args:
            image_id: ID изображения
            days: Количество дней для проверки
            
        Returns:
            bool: True если изображение было отправлено за последние N дней
        """
        recent_ids = self.get_recent_image_ids(days)
        return image_id in recent_ids
    
    def get_total_sent_count(self) -> int:
        """
        Получение общего количества отправленных фото.
        
        Returns:
            int: Количество отправленных фото
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sent_photos")
            count = cursor.fetchone()[0]
            return count
    
    def get_user_sent_count(self, user_id: int) -> int:
        """
        Получение количества фото, отправленных конкретному пользователю.
        
        Args:
            user_id: Telegram ID пользователя
            
        Returns:
            int: Количество отправленных фото
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM sent_photos 
                WHERE user_id = ?
            """, (user_id,))
            count = cursor.fetchone()[0]
            return count
    
    def cleanup_old_records(self, days: int):
        """
        Удаление записей старше указанного количества дней.
        
        Args:
            days: Количество дней (записи старше будут удалены)
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM sent_photos 
                WHERE sent_at < ?
            """, (cutoff_date,))
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Удалено {deleted_count} старых записей (старше {days} дней)")
    
    def get_last_sent_photo(self) -> Optional[tuple]:
        """
        Получение информации о последнем отправленном фото.
        
        Returns:
            Optional[tuple]: (image_id, sent_at, title) или None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT image_id, sent_at, title 
                FROM sent_photos 
                ORDER BY sent_at DESC 
                LIMIT 1
            """)
            result = cursor.fetchone()
            return result if result else None
    
    def get_last_sent_photo_for_user(self, user_id: int) -> Optional[tuple]:
        """
        Получение информации о последнем отправленном фото для конкретного пользователя.
        
        Args:
            user_id: Telegram ID пользователя
            
        Returns:
            Optional[tuple]: (image_id, sent_at, title) или None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT image_id, sent_at, title 
                FROM sent_photos 
                WHERE user_id = ?
                ORDER BY sent_at DESC 
                LIMIT 1
            """, (user_id,))
            result = cursor.fetchone()
            return result if result else None