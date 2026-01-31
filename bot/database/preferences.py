"""Модуль для работы с таблицами performer_preferences и gallery_preferences."""

import sqlite3
import logging
import time
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


class PreferencesRepository:
    """Класс для работы с таблицами performer_preferences и gallery_preferences."""
    
    def __init__(self, db_path: str):
        """
        Инициализация репозитория.
        
        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path
    
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
    
    def get_blacklisted_performers(self) -> List[str]:
        """
        Получение списка перформеров с отрицательным score (blacklist).
        
        Returns:
            List[str]: Список ID перформеров
        """
        start_time = time.perf_counter()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT performer_id
                FROM performer_preferences
                WHERE score < 0
            """)
            
            results = cursor.fetchall()
            ids = [row[0] for row in results]
            
            duration = time.perf_counter() - start_time
            logger.debug(f"⏱️  DB get_blacklisted_performers: {duration:.3f}s ({len(ids)} items)")
            return ids
    
    def get_whitelisted_performers(self) -> List[str]:
        """
        Получение списка перформеров с положительным score (whitelist).
        
        Returns:
            List[str]: Список ID перформеров
        """
        start_time = time.perf_counter()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT performer_id
                FROM performer_preferences
                WHERE score > 0
                ORDER BY score DESC
            """)
            
            results = cursor.fetchall()
            ids = [row[0] for row in results]
            
            duration = time.perf_counter() - start_time
            logger.debug(f"⏱️  DB get_whitelisted_performers: {duration:.3f}s ({len(ids)} items)")
            return ids
    
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
    
    def get_blacklisted_galleries(self) -> List[str]:
        """
        Получение списка галерей с отрицательным score (blacklist).
        
        Returns:
            List[str]: Список ID галерей
        """
        start_time = time.perf_counter()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT gallery_id
                FROM gallery_preferences
                WHERE score < 0
            """)
            
            results = cursor.fetchall()
            ids = [row[0] for row in results]
            
            duration = time.perf_counter() - start_time
            logger.debug(f"⏱️  DB get_blacklisted_galleries: {duration:.3f}s ({len(ids)} items)")
            return ids
    
    def get_whitelisted_galleries(self) -> List[str]:
        """
        Получение списка галерей с положительным score (whitelist).
        
        Returns:
            List[str]: Список ID галерей
        """
        start_time = time.perf_counter()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT gallery_id
                FROM gallery_preferences
                WHERE score > 0
                ORDER BY score DESC
            """)
            
            results = cursor.fetchall()
            ids = [row[0] for row in results]
            
            duration = time.perf_counter() - start_time
            logger.debug(f"⏱️  DB get_whitelisted_galleries: {duration:.3f}s ({len(ids)} items)")
            return ids
    
    def is_threshold_notification_shown(self, gallery_id: str) -> bool:
        """
        Проверка, показывалось ли уведомление о достижении порога для галереи.
        
        Args:
            gallery_id: ID галереи
            
        Returns:
            bool: True если уведомление уже показывалось
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT threshold_notification_shown
                FROM gallery_preferences
                WHERE gallery_id = ?
            """, (gallery_id,))
            
            result = cursor.fetchone()
            if not result:
                return False
            
            return bool(result[0]) if result[0] is not None else False
    
    def mark_threshold_notification_shown(self, gallery_id: str):
        """
        Отметить, что уведомление о достижении порога было показано для галереи.
        
        Args:
            gallery_id: ID галереи
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE gallery_preferences
                SET threshold_notification_shown = TRUE
                WHERE gallery_id = ?
            """, (gallery_id,))
            
            conn.commit()
            logger.debug(f"Уведомление о пороге для галереи {gallery_id} отмечено как показанное")