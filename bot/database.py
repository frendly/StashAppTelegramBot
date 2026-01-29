"""Работа с базой данных SQLite для хранения истории отправленных фото."""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class Database:
    """Класс для работы с SQLite базой данных."""
    
    def __init__(self, db_path: str):
        """
        Инициализация подключения к базе данных.
        
        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path
        self._ensure_db_directory()
        self._init_database()
    
    def _ensure_db_directory(self):
        """Создание директории для базы данных, если она не существует."""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
    
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sent_photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_id TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id INTEGER,
                    title TEXT
                )
            """)
            
            # Создание индекса для быстрого поиска
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_image_id 
                ON sent_photos(image_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sent_at 
                ON sent_photos(sent_at)
            """)
            
            conn.commit()
            logger.info(f"База данных инициализирована: {self.db_path}")
    
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
            logger.debug(f"Найдено {len(image_ids)} изображений за последние {days} дней")
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
