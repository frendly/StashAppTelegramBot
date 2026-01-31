"""Модуль для работы с весами галерей."""

import sqlite3
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class WeightsRepository:
    """Класс для работы с весами галерей."""
    
    def __init__(self, db_path: str):
        """
        Инициализация репозитория.
        
        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path
    
    @staticmethod
    def calculate_initial_weight(positive_votes: int, negative_votes: int) -> float:
        """
        Расчет начального веса из истории голосований.
        
        Args:
            positive_votes: Количество положительных голосов
            negative_votes: Количество отрицательных голосов
            
        Returns:
            float: Начальный вес с учетом ограничений 0.1 ≤ вес ≤ 10.0
        """
        # Формула: W = 1.0 * 1.2^(плюсы) * 0.8^(минусы)
        weight = 1.0 * (1.2 ** positive_votes) * (0.8 ** negative_votes)
        
        # Применяем ограничения
        weight = max(0.1, min(10.0, weight))
        
        return weight
    
    def get_gallery_weight(self, gallery_id: str) -> float:
        """
        Получение текущего веса галереи.
        
        Args:
            gallery_id: ID галереи
            
        Returns:
            float: Вес галереи или 1.0 если галерея не найдена
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT weight
                FROM gallery_preferences
                WHERE gallery_id = ?
            """, (gallery_id,))
            
            result = cursor.fetchone()
            if result and result[0] is not None:
                return float(result[0])
            return 1.0
    
    def update_gallery_weight(self, gallery_id: str, vote: int) -> float:
        """
        Обновление веса галереи с учетом коэффициента k=0.2.
        
        Args:
            gallery_id: ID галереи
            vote: 1 для лайка, -1 для дизлайка
            
        Returns:
            float: Новый вес галереи
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Получаем текущий вес
            cursor.execute("""
                SELECT weight
                FROM gallery_preferences
                WHERE gallery_id = ?
            """, (gallery_id,))
            
            result = cursor.fetchone()
            
            if not result:
                # Галерея не найдена, возвращаем вес по умолчанию
                logger.warning(f"Галерея {gallery_id} не найдена для обновления веса")
                return 1.0
            
            current_weight = float(result[0]) if result[0] is not None else 1.0
            
            # Обновляем вес с учетом коэффициента k=0.2
            if vote > 0:
                # При "+": вес = вес × 1.2
                new_weight = current_weight * 1.2
            elif vote < 0:
                # При "-": вес = вес × 0.8
                new_weight = current_weight * 0.8
            else:
                # Нейтральный голос (не должен происходить, но на всякий случай)
                new_weight = current_weight
            
            # Применяем ограничения: 0.1 ≤ вес ≤ 10.0
            new_weight = max(0.1, min(10.0, new_weight))
            
            # Обновляем вес в БД
            cursor.execute("""
                UPDATE gallery_preferences
                SET weight = ?, updated_at = CURRENT_TIMESTAMP
                WHERE gallery_id = ?
            """, (new_weight, gallery_id))
            
            conn.commit()
            logger.debug(f"Обновлен вес галереи {gallery_id}: {current_weight:.3f} -> {new_weight:.3f} (vote={vote})")
            
            return new_weight
    
    def _get_active_gallery_weights_data(self) -> List[tuple]:
        """
        Внутренний метод для получения данных активных (неисключенных) галерей.
        
        Returns:
            List[tuple]: Список кортежей (gallery_id, weight)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT gallery_id, weight
                FROM gallery_preferences
                WHERE excluded = FALSE OR excluded IS NULL
            """)
            return cursor.fetchall()
    
    def get_all_gallery_weights(self) -> List[Dict[str, Any]]:
        """
        Получение всех весов галерей (для взвешенного выбора).
        
        Returns:
            List[Dict]: Список словарей с gallery_id и weight, исключая исключенные галереи
        """
        results = self._get_active_gallery_weights_data()
        return [
            {
                'gallery_id': row[0],
                'weight': float(row[1]) if row[1] is not None else 1.0
            }
            for row in results
        ]
    
    def get_active_gallery_weights(self) -> Dict[str, float]:
        """
        Получение словаря весов активных (неисключенных) галерей.
        
        Returns:
            Dict[str, float]: Словарь {gallery_id: weight} для всех неисключенных галерей
        """
        results = self._get_active_gallery_weights_data()
        return {
            row[0]: float(row[1]) if row[1] is not None else 1.0
            for row in results
        }
    
    def get_gallery_stats_with_viewed_counts(self) -> Dict[str, Dict[str, Any]]:
        """
        Получение статистики по галереям для модификации весов.
        
        Returns:
            Dict: {gallery_id: {weight: float, viewed: int, total: int, last_selected: float}}
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Получаем веса, количество изображений, время последнего выбора и статус исключения
            cursor.execute("""
                SELECT 
                    gp.gallery_id,
                    gp.weight,
                    gp.total_images,
                    gp.last_selected_at,
                    COUNT(DISTINCT v.image_id) as viewed_count,
                    gp.excluded
                FROM gallery_preferences gp
                LEFT JOIN votes v ON v.gallery_id = gp.gallery_id
                GROUP BY gp.gallery_id
            """)
            
            results = {}
            current_time = time.time()
            
            for row in cursor.fetchall():
                gallery_id = row[0]
                weight = float(row[1]) if row[1] else 1.0
                total_images = int(row[2]) if row[2] else 0
                last_selected_at = row[3]
                viewed_count = int(row[4]) if row[4] else 0
                excluded = bool(row[5]) if row[5] is not None else False
                
                # Пропускаем исключенные галереи
                if excluded:
                    continue
                
                # Преобразуем timestamp в секунды
                if last_selected_at:
                    try:
                        # Пробуем разные форматы даты
                        if 'T' in str(last_selected_at):
                            dt = datetime.fromisoformat(str(last_selected_at).replace('Z', '+00:00'))
                        else:
                            dt = datetime.strptime(str(last_selected_at), '%Y-%m-%d %H:%M:%S')
                        last_selected = dt.timestamp()
                    except Exception as e:
                        logger.debug(f"Ошибка парсинга даты {last_selected_at}: {e}")
                        last_selected = 0
                else:
                    last_selected = 0
                
                results[gallery_id] = {
                    'weight': weight,
                    'viewed': viewed_count,
                    'total': total_images if total_images > 0 else 1,
                    'last_selected': last_selected
                }
            
            return results
    
    def update_gallery_last_selected(self, gallery_id: str):
        """
        Обновление времени последнего выбора галереи.
        
        Args:
            gallery_id: ID галереи
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE gallery_preferences
                SET last_selected_at = CURRENT_TIMESTAMP
                WHERE gallery_id = ?
            """, (gallery_id,))
            
            # Если галереи нет в БД, создаем запись (на случай, если она еще не была выбрана)
            if cursor.rowcount == 0:
                # Пытаемся создать запись с базовыми значениями
                # Но нам нужно название галереи, поэтому просто логируем
                logger.debug(f"Галерея {gallery_id} не найдена в БД для обновления last_selected_at")
            else:
                conn.commit()
                logger.debug(f"Обновлено время последнего выбора для галереи {gallery_id}")