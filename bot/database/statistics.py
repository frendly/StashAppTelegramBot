"""Модуль для работы со статистикой галерей."""

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class StatisticsRepository:
    """Класс для работы со статистикой галерей."""
    
    def __init__(self, db_path: str):
        """
        Инициализация репозитория.
        
        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path
    
    def update_gallery_image_count(self, gallery_id: str, total_images: int) -> bool:
        """
        Обновление количества изображений в галерее.
        
        Args:
            gallery_id: ID галереи
            total_images: Общее количество изображений
            
        Returns:
            bool: True если обновление успешно
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE gallery_preferences
                    SET total_images = ?, images_count_updated_at = CURRENT_TIMESTAMP
                    WHERE gallery_id = ?
                """, (total_images, gallery_id))
                
                if cursor.rowcount == 0:
                    logger.warning(f"Галерея {gallery_id} не найдена для обновления количества изображений")
                    return False
                
                conn.commit()
                logger.debug(f"Обновлено количество изображений для галереи {gallery_id}: {total_images}")
                return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении количества изображений для галереи {gallery_id}: {e}")
            return False
    
    def get_gallery_statistics(self, gallery_id: str) -> Optional[Dict[str, Any]]:
        """
        Получение полной статистики галереи.
        
        Args:
            gallery_id: ID галереи
            
        Returns:
            Optional[Dict]: Статистика галереи или None если не найдена
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT total_images, positive_votes, negative_votes, images_count_updated_at
                FROM gallery_preferences
                WHERE gallery_id = ?
            """, (gallery_id,))
            
            result = cursor.fetchone()
            if not result:
                return None
            
            total_images = result[0] if result[0] is not None else 0
            positive_votes = result[1] if result[1] is not None else 0
            negative_votes = result[2] if result[2] is not None else 0
            images_count_updated_at = result[3]
            
            # Расчет процента минусов (оптимизировано - используем уже полученные данные)
            if total_images == 0:
                negative_percentage = 0.0
            else:
                negative_percentage = round((negative_votes / total_images) * 100.0, 2)
            
            return {
                'gallery_id': gallery_id,
                'total_images': total_images,
                'positive_votes': positive_votes,
                'negative_votes': negative_votes,
                'negative_percentage': negative_percentage,
                'images_count_updated_at': images_count_updated_at
            }
    
    def calculate_negative_percentage(self, gallery_id: str) -> float:
        """
        Расчет процента минусов для галереи.
        
        Формула: (negative_votes / total_images) × 100%
        
        Args:
            gallery_id: ID галереи
            
        Returns:
            float: Процент минусов (0.0-100.0) или 0.0 если данных нет
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT total_images, negative_votes
                FROM gallery_preferences
                WHERE gallery_id = ?
            """, (gallery_id,))
            
            result = cursor.fetchone()
            if not result:
                return 0.0
            
            total_images = result[0] if result[0] is not None else 0
            negative_votes = result[1] if result[1] is not None else 0
            
            if total_images == 0:
                return 0.0
            
            percentage = (negative_votes / total_images) * 100.0
            return round(percentage, 2)
    
    def get_galleries_needing_update(self, days_threshold: int = 7) -> List[Dict[str, Any]]:
        """
        Получение списка галерей, которым нужно обновить количество изображений.
        
        Критерии:
        - total_images == 0 (первое голосование)
        - images_count_updated_at старше days_threshold дней
        
        Args:
            days_threshold: Порог в днях для обновления (по умолчанию 7)
            
        Returns:
            List[Dict]: Список галерей с gallery_id и gallery_title
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Вычисляем дату порога
            # SQLite поддерживает datetime объекты напрямую
            threshold_date = datetime.now() - timedelta(days=days_threshold)
            
            cursor.execute("""
                SELECT gallery_id, gallery_title
                FROM gallery_preferences
                WHERE total_images = 0 
                   OR images_count_updated_at IS NULL
                   OR datetime(images_count_updated_at) < datetime(?)
            """, (threshold_date.strftime('%Y-%m-%d %H:%M:%S'),))
            
            results = cursor.fetchall()
            return [
                {
                    'gallery_id': row[0],
                    'gallery_title': row[1]
                }
                for row in results
            ]
    
    def get_gallery_image_count(self, gallery_id: str) -> Optional[int]:
        """
        Получение количества изображений для галереи из БД.
        
        Args:
            gallery_id: ID галереи
            
        Returns:
            Optional[int]: Количество изображений или None если галерея не найдена
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT total_images
                FROM gallery_preferences
                WHERE gallery_id = ?
            """, (gallery_id,))
            
            result = cursor.fetchone()
            if not result or result[0] is None:
                return None
            
            return result[0]
    
    def should_update_image_count(self, gallery_id: str, days_threshold: int = 7) -> bool:
        """
        Проверка, нужно ли обновить количество изображений для галереи.
        
        Args:
            gallery_id: ID галереи
            days_threshold: Порог в днях для обновления (по умолчанию 7)
            
        Returns:
            bool: True если нужно обновить
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT total_images, images_count_updated_at
                FROM gallery_preferences
                WHERE gallery_id = ?
            """, (gallery_id,))
            
            result = cursor.fetchone()
            if not result:
                return False
            
            total_images = result[0] if result[0] is not None else 0
            images_count_updated_at = result[1]
            
            # Если количество изображений равно 0, нужно обновить
            if total_images == 0:
                return True
            
            # Если дата обновления не установлена, нужно обновить
            if images_count_updated_at is None:
                return True
            
            # Проверяем, не старше ли дата обновления порога
            # SQLite TIMESTAMP хранится в формате 'YYYY-MM-DD HH:MM:SS',
            # строковое сравнение работает корректно для этого формата (лексикографически)
            threshold_date = datetime.now() - timedelta(days=days_threshold)
            threshold_str = threshold_date.strftime('%Y-%m-%d %H:%M:%S')
            
            try:
                # Простое строковое сравнение работает для формата SQLite TIMESTAMP
                if images_count_updated_at < threshold_str:
                    return True
            except (TypeError, ValueError) as e:
                # Если не удалось сравнить дату, считаем что нужно обновить
                logger.warning(f"Ошибка при сравнении даты для галереи {gallery_id}: {e}")
                return True
            
            return False