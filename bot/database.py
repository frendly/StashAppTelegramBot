"""Работа с базой данных SQLite для хранения истории отправленных фото."""

import sqlite3
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

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
            
            # Таблица отправленных фото
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
            
            # Таблица голосований
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_id TEXT NOT NULL,
                    vote INTEGER NOT NULL,
                    gallery_id TEXT,
                    gallery_title TEXT,
                    performer_ids TEXT,
                    performer_names TEXT,
                    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(image_id)
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_votes_image_id 
                ON votes(image_id)
            """)
            
            # Таблица предпочтений по перформерам
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS performer_preferences (
                    performer_id TEXT PRIMARY KEY,
                    performer_name TEXT NOT NULL,
                    total_votes INTEGER DEFAULT 0,
                    positive_votes INTEGER DEFAULT 0,
                    negative_votes INTEGER DEFAULT 0,
                    score REAL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица предпочтений по галереям
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gallery_preferences (
                    gallery_id TEXT PRIMARY KEY,
                    gallery_title TEXT NOT NULL,
                    total_votes INTEGER DEFAULT 0,
                    positive_votes INTEGER DEFAULT 0,
                    negative_votes INTEGER DEFAULT 0,
                    score REAL DEFAULT 0,
                    rating_set BOOLEAN DEFAULT FALSE,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
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
    
    # Voting methods
    
    def add_vote(
        self, 
        image_id: str, 
        vote: int, 
        gallery_id: Optional[str] = None,
        gallery_title: Optional[str] = None,
        performer_ids: Optional[List[str]] = None,
        performer_names: Optional[List[str]] = None
    ):
        """
        Добавление или обновление голоса за изображение.
        
        Args:
            image_id: ID изображения
            vote: 1 для лайка, -1 для дизлайка
            gallery_id: ID галереи (опционально)
            gallery_title: Название галереи (опционально)
            performer_ids: Список ID перформеров (опционально)
            performer_names: Список имен перформеров (опционально)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Сериализация списков в JSON
            performer_ids_json = json.dumps(performer_ids) if performer_ids else None
            performer_names_json = json.dumps(performer_names) if performer_names else None
            
            cursor.execute("""
                INSERT OR REPLACE INTO votes 
                (image_id, vote, gallery_id, gallery_title, performer_ids, performer_names)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (image_id, vote, gallery_id, gallery_title, performer_ids_json, performer_names_json))
            
            conn.commit()
            logger.debug(f"Добавлен голос: image_id={image_id}, vote={vote}")
    
    def get_vote(self, image_id: str) -> Optional[Dict[str, Any]]:
        """
        Получение голоса за изображение.
        
        Args:
            image_id: ID изображения
            
        Returns:
            Optional[Dict]: Информация о голосе или None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT image_id, vote, gallery_id, gallery_title, 
                       performer_ids, performer_names, voted_at
                FROM votes 
                WHERE image_id = ?
            """, (image_id,))
            
            result = cursor.fetchone()
            if not result:
                return None
            
            performer_ids = json.loads(result[4]) if result[4] else []
            performer_names = json.loads(result[5]) if result[5] else []
            
            return {
                'image_id': result[0],
                'vote': result[1],
                'gallery_id': result[2],
                'gallery_title': result[3],
                'performer_ids': performer_ids,
                'performer_names': performer_names,
                'voted_at': result[6]
            }
    
    def update_performer_preference(
        self, 
        performer_id: str, 
        performer_name: str, 
        vote: int
    ):
        """
        Обновление предпочтений по перформеру.
        
        Args:
            performer_id: ID перформера
            performer_name: Имя перформера
            vote: 1 для лайка, -1 для дизлайка
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Получаем текущие данные
            cursor.execute("""
                SELECT total_votes, positive_votes, negative_votes
                FROM performer_preferences
                WHERE performer_id = ?
            """, (performer_id,))
            
            result = cursor.fetchone()
            
            if result:
                total_votes = result[0] + 1
                positive_votes = result[1] + (1 if vote > 0 else 0)
                negative_votes = result[2] + (1 if vote < 0 else 0)
            else:
                total_votes = 1
                positive_votes = 1 if vote > 0 else 0
                negative_votes = 1 if vote < 0 else 0
            
            # Рассчитываем score
            score = (positive_votes - negative_votes) / total_votes if total_votes > 0 else 0
            
            cursor.execute("""
                INSERT OR REPLACE INTO performer_preferences
                (performer_id, performer_name, total_votes, positive_votes, negative_votes, score, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (performer_id, performer_name, total_votes, positive_votes, negative_votes, score))
            
            conn.commit()
            logger.debug(f"Обновлены предпочтения перформера: {performer_name} (score={score:.2f})")
    
    def update_gallery_preference(
        self, 
        gallery_id: str, 
        gallery_title: str, 
        vote: int
    ) -> bool:
        """
        Обновление предпочтений по галерее.
        
        Args:
            gallery_id: ID галереи
            gallery_title: Название галереи
            vote: 1 для лайка, -1 для дизлайка
            
        Returns:
            bool: True если достигнут порог в 5 голосов и рейтинг еще не установлен
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Получаем текущие данные
            cursor.execute("""
                SELECT total_votes, positive_votes, negative_votes, rating_set
                FROM gallery_preferences
                WHERE gallery_id = ?
            """, (gallery_id,))
            
            result = cursor.fetchone()
            
            if result:
                total_votes = result[0] + 1
                positive_votes = result[1] + (1 if vote > 0 else 0)
                negative_votes = result[2] + (1 if vote < 0 else 0)
                rating_set = result[3]
            else:
                total_votes = 1
                positive_votes = 1 if vote > 0 else 0
                negative_votes = 1 if vote < 0 else 0
                rating_set = False
            
            # Рассчитываем score
            score = (positive_votes - negative_votes) / total_votes if total_votes > 0 else 0
            
            cursor.execute("""
                INSERT OR REPLACE INTO gallery_preferences
                (gallery_id, gallery_title, total_votes, positive_votes, negative_votes, score, rating_set, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (gallery_id, gallery_title, total_votes, positive_votes, negative_votes, score, rating_set))
            
            conn.commit()
            logger.debug(f"Обновлены предпочтения галереи: {gallery_title} (score={score:.2f}, votes={total_votes})")
            
            # Возвращаем True если достигнут порог и рейтинг еще не установлен
            return total_votes >= 5 and not rating_set
    
    def mark_gallery_rating_set(self, gallery_id: str):
        """
        Отметить, что рейтинг галереи был установлен в Stash.
        
        Args:
            gallery_id: ID галереи
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE gallery_preferences
                SET rating_set = TRUE, updated_at = CURRENT_TIMESTAMP
                WHERE gallery_id = ?
            """, (gallery_id,))
            conn.commit()
            logger.debug(f"Рейтинг галереи {gallery_id} отмечен как установленный")
    
    def get_performer_preferences(self) -> List[Dict[str, Any]]:
        """
        Получение всех предпочтений по перформерам.
        
        Returns:
            List[Dict]: Список предпочтений
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT performer_id, performer_name, total_votes, 
                       positive_votes, negative_votes, score
                FROM performer_preferences
                ORDER BY score DESC
            """)
            
            results = cursor.fetchall()
            return [
                {
                    'performer_id': row[0],
                    'performer_name': row[1],
                    'total_votes': row[2],
                    'positive_votes': row[3],
                    'negative_votes': row[4],
                    'score': row[5]
                }
                for row in results
            ]
    
    def get_gallery_preferences(self) -> List[Dict[str, Any]]:
        """
        Получение всех предпочтений по галереям.
        
        Returns:
            List[Dict]: Список предпочтений
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT gallery_id, gallery_title, total_votes, 
                       positive_votes, negative_votes, score
                FROM gallery_preferences
                ORDER BY score DESC
            """)
            
            results = cursor.fetchall()
            return [
                {
                    'gallery_id': row[0],
                    'gallery_title': row[1],
                    'total_votes': row[2],
                    'positive_votes': row[3],
                    'negative_votes': row[4],
                    'score': row[5]
                }
                for row in results
            ]
    
    def get_blacklisted_performers(self) -> List[str]:
        """
        Получение списка перформеров с отрицательным score (blacklist).
        
        Returns:
            List[str]: Список ID перформеров
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT performer_id
                FROM performer_preferences
                WHERE score < 0
            """)
            
            results = cursor.fetchall()
            return [row[0] for row in results]
    
    def get_blacklisted_galleries(self) -> List[str]:
        """
        Получение списка галерей с отрицательным score (blacklist).
        
        Returns:
            List[str]: Список ID галерей
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT gallery_id
                FROM gallery_preferences
                WHERE score < 0
            """)
            
            results = cursor.fetchall()
            return [row[0] for row in results]
    
    def get_whitelisted_performers(self) -> List[str]:
        """
        Получение списка перформеров с положительным score (whitelist).
        
        Returns:
            List[str]: Список ID перформеров
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT performer_id
                FROM performer_preferences
                WHERE score > 0
                ORDER BY score DESC
            """)
            
            results = cursor.fetchall()
            return [row[0] for row in results]
    
    def get_whitelisted_galleries(self) -> List[str]:
        """
        Получение списка галерей с положительным score (whitelist).
        
        Returns:
            List[str]: Список ID галерей
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT gallery_id
                FROM gallery_preferences
                WHERE score > 0
                ORDER BY score DESC
            """)
            
            results = cursor.fetchall()
            return [row[0] for row in results]
    
    def get_gallery_preference(self, gallery_id: str) -> Optional[Dict[str, Any]]:
        """
        Получение предпочтения для конкретной галереи.
        
        Args:
            gallery_id: ID галереи
            
        Returns:
            Optional[Dict]: Информация о предпочтении или None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT gallery_id, gallery_title, total_votes, 
                       positive_votes, negative_votes, score
                FROM gallery_preferences
                WHERE gallery_id = ?
            """, (gallery_id,))
            
            result = cursor.fetchone()
            if not result:
                return None
            
            return {
                'gallery_id': result[0],
                'gallery_title': result[1],
                'total_votes': result[2],
                'positive_votes': result[3],
                'negative_votes': result[4],
                'score': result[5]
            }
    
    def get_total_votes_count(self) -> Dict[str, int]:
        """
        Получение общего количества голосов.
        
        Returns:
            Dict: Словарь с количеством всех голосов, положительных и отрицательных
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN vote > 0 THEN 1 ELSE 0 END) as positive,
                       SUM(CASE WHEN vote < 0 THEN 1 ELSE 0 END) as negative
                FROM votes
            """)
            
            result = cursor.fetchone()
            return {
                'total': result[0] if result[0] else 0,
                'positive': result[1] if result[1] else 0,
                'negative': result[2] if result[2] else 0
            }