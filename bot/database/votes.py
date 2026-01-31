"""Модуль для работы с таблицей votes."""

import sqlite3
import logging
import json
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


class VotesRepository:
    """Класс для работы с таблицей votes."""
    
    def __init__(self, db_path: str):
        """
        Инициализация репозитория.
        
        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path
    
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
    
    def get_image_vote_status(self, image_id: str) -> Optional[int]:
        """
        Получение статуса голосования за изображение.
        
        Args:
            image_id: ID изображения
            
        Returns:
            Optional[int]: None (неоцененное), 1 (плюс), -1 (минус)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT vote
                FROM votes 
                WHERE image_id = ?
            """, (image_id,))
            
            result = cursor.fetchone()
            if not result:
                return None
            
            vote = result[0]
            # Возвращаем 1 для положительного голоса, -1 для отрицательного
            if vote > 0:
                return 1
            elif vote < 0:
                return -1
            else:
                return None
    
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
