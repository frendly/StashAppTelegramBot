"""Модуль для обработки голосований за изображения."""

import logging
import time
from typing import List, Dict, Any, Optional, Tuple

from bot.database import Database
from bot.stash_client import StashClient, StashImage

logger = logging.getLogger(__name__)


class VotingManager:
    """Класс для управления системой голосования."""
    
    def __init__(self, database: Database, stash_client: StashClient, cache_ttl: int = 60):
        """
        Инициализация менеджера голосования.
        
        Args:
            database: База данных
            stash_client: Клиент StashApp
            cache_ttl: Время жизни кэша в секундах (по умолчанию 60)
        """
        self.database = database
        self.stash_client = stash_client
        self.cache_ttl = cache_ttl
        
        # Кэш для списков фильтрации
        self._filtering_cache: Optional[Dict[str, List[str]]] = None
        self._filtering_cache_time: float = 0
        
        # Кэш для весов галерей
        self._weights_cache: Optional[Dict[str, float]] = None
        self._weights_cache_time: float = 0
    
    async def process_vote(
        self,
        image: StashImage,
        vote: int
    ) -> Dict[str, Any]:
        """
        Обработка голоса за изображение.
        
        Args:
            image: Объект изображения
            vote: 1 для лайка, -1 для дизлайка
            
        Returns:
            Dict: Результат обработки с информацией об обновлениях
        """
        result = {
            'image_rating_updated': False,
            'gallery_rating_updated': False,
            'performers_updated': [],
            'gallery_updated': None,
            'error': None
        }
        
        try:
            # 1. Обновляем рейтинг изображения в Stash
            rating = 5 if vote > 0 else 1
            image_updated = await self.stash_client.update_image_rating(image.id, rating)
            result['image_rating_updated'] = image_updated
            
            if not image_updated:
                logger.warning(f"Не удалось обновить рейтинг изображения {image.id}")
            
            # 2. Сохраняем голос в базу данных
            performer_ids = [p['id'] for p in image.performers]
            performer_names = [p['name'] for p in image.performers]
            
            self.database.add_vote(
                image_id=image.id,
                vote=vote,
                gallery_id=image.gallery_id,
                gallery_title=image.gallery_title,
                performer_ids=performer_ids,
                performer_names=performer_names
            )
            
            # 3. Обновляем предпочтения по перформерам
            for performer in image.performers:
                self.database.update_performer_preference(
                    performer_id=performer['id'],
                    performer_name=performer['name'],
                    vote=vote
                )
                result['performers_updated'].append(performer['name'])
                logger.debug(f"Обновлены предпочтения перформера: {performer['name']}")
            
            # 4. Обновляем предпочтения по галерее (если есть)
            if image.gallery_id and image.gallery_title:
                should_update_gallery = self.database.update_gallery_preference(
                    gallery_id=image.gallery_id,
                    gallery_title=image.gallery_title,
                    vote=vote
                )
                
                result['gallery_updated'] = image.gallery_title
                
                # 4.1. Обновляем вес галереи с учетом коэффициента k=0.2
                try:
                    new_weight = self.database.update_gallery_weight(image.gallery_id, vote)
                    logger.debug(f"Вес галереи '{image.gallery_title}' обновлен: {new_weight:.3f}")
                    # Инвалидируем кэш весов после обновления
                    self.invalidate_weights_cache()
                except Exception as e:
                    logger.warning(f"Ошибка при обновлении веса галереи {image.gallery_id}: {e}")
                
                # 4.2. Обновляем статистику галереи (количество изображений)
                try:
                    if self.database.should_update_image_count(image.gallery_id, days_threshold=7):
                        logger.debug(f"Обновление количества изображений для галереи {image.gallery_id}")
                        image_count = await self.stash_client.get_gallery_image_count(image.gallery_id)
                        
                        if image_count is not None:
                            self.database.update_gallery_image_count(image.gallery_id, image_count)
                            logger.debug(f"Количество изображений для галереи '{image.gallery_title}' обновлено: {image_count}")
                        else:
                            logger.warning(f"Не удалось получить количество изображений для галереи {image.gallery_id}")
                except Exception as e:
                    logger.warning(f"Ошибка при обновлении статистики галереи {image.gallery_id}: {e}")
                
                # 5. Если достигнут порог в 5 голосов, устанавливаем рейтинг галереи
                if should_update_gallery:
                    gallery_pref = self.database.get_gallery_preference(image.gallery_id)
                    if gallery_pref:
                        # Рассчитываем средний рейтинг на основе голосов
                        avg_rating = self._calculate_gallery_rating(
                            gallery_pref['positive_votes'],
                            gallery_pref['negative_votes']
                        )
                        
                        gallery_rating_updated = await self.stash_client.update_gallery_rating(
                            image.gallery_id,
                            avg_rating
                        )
                        
                        if gallery_rating_updated:
                            self.database.mark_gallery_rating_set(image.gallery_id)
                            result['gallery_rating_updated'] = True
                            logger.info(
                                f"Рейтинг галереи '{image.gallery_title}' установлен на {avg_rating}/5"
                            )
            
            logger.info(f"Голос обработан: image={image.id}, vote={vote}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при обработке голоса: {e}", exc_info=True)
            result['error'] = str(e)
            return result
    
    def _calculate_gallery_rating(self, positive_votes: int, negative_votes: int) -> int:
        """
        Рассчет среднего рейтинга галереи на основе голосов.
        
        Args:
            positive_votes: Количество лайков
            negative_votes: Количество дизлайков
            
        Returns:
            int: Рейтинг от 1 до 5
        """
        total_votes = positive_votes + negative_votes
        if total_votes == 0:
            return 3  # Нейтральный рейтинг
        
        # Простая формула: процент положительных голосов преобразуем в рейтинг 1-5
        positive_ratio = positive_votes / total_votes
        
        # Преобразуем ratio (0-1) в рейтинг (1-5)
        # 0.0-0.2 -> 1, 0.2-0.4 -> 2, 0.4-0.6 -> 3, 0.6-0.8 -> 4, 0.8-1.0 -> 5
        # Используем int(ratio * 4) + 1, чтобы избежать выхода за пределы при ratio=1.0
        rating = int(positive_ratio * 4) + 1
        return max(1, min(5, rating))  # Ограничиваем диапазон 1-5
    
    def get_preferences_summary(self) -> Dict[str, Any]:
        """
        Получение сводки по предпочтениям.
        
        Returns:
            Dict: Сводная информация о предпочтениях
        """
        performer_prefs = self.database.get_performer_preferences()
        gallery_prefs = self.database.get_gallery_preferences()
        
        # Топ-5 любимых перформеров (с положительным score)
        top_performers = [p for p in performer_prefs if p['score'] > 0][:5]
        
        # Топ-5 нелюбимых перформеров (с отрицательным score, сортируем по возрастанию)
        negative_performers = [p for p in performer_prefs if p['score'] < 0]
        worst_performers = sorted(negative_performers, key=lambda x: x['score'])[:5]
        
        # Топ-5 любимых галерей (с положительным score)
        top_galleries = [g for g in gallery_prefs if g['score'] > 0][:5]
        
        # Топ-5 нелюбимых галерей (с отрицательным score, сортируем по возрастанию)
        negative_galleries = [g for g in gallery_prefs if g['score'] < 0]
        worst_galleries = sorted(negative_galleries, key=lambda x: x['score'])[:5]
        
        return {
            'top_performers': top_performers,
            'worst_performers': worst_performers,
            'top_galleries': top_galleries,
            'worst_galleries': worst_galleries,
            'total_performers': len(performer_prefs),
            'total_galleries': len(gallery_prefs)
        }
    
    def get_filtering_lists(self) -> Dict[str, List[str]]:
        """
        Получение списков для фильтрации изображений (с кэшированием).
        
        Returns:
            Dict: Словарь с blacklist и whitelist для перформеров и галерей
        """
        current_time = time.time()
        
        # Проверяем, актуален ли кэш
        if self._filtering_cache is not None and (current_time - self._filtering_cache_time) < self.cache_ttl:
            logger.debug(f"⏱️  Using cached filtering lists (age: {current_time - self._filtering_cache_time:.1f}s)")
            return self._filtering_cache
        
        # Обновляем кэш
        logger.debug("⏱️  Refreshing filtering lists cache")
        self._filtering_cache = {
            'blacklisted_performers': self.database.get_blacklisted_performers(),
            'blacklisted_galleries': self.database.get_blacklisted_galleries(),
            'whitelisted_performers': self.database.get_whitelisted_performers(),
            'whitelisted_galleries': self.database.get_whitelisted_galleries()
        }
        self._filtering_cache_time = current_time
        
        return self._filtering_cache
    
    def invalidate_filtering_cache(self):
        """Инвалидация кэша фильтрации (вызывается после голосования)."""
        logger.debug("⏱️  Invalidating filtering lists cache")
        self._filtering_cache = None
        self._filtering_cache_time = 0
    
    def get_cached_gallery_weights(self) -> Dict[str, float]:
        """
        Получение весов активных галерей с кэшированием.
        
        Returns:
            Dict[str, float]: Словарь {gallery_id: weight} для всех неисключенных галерей
        """
        current_time = time.time()
        
        # Проверяем, актуален ли кэш
        if self._weights_cache is not None and (current_time - self._weights_cache_time) < self.cache_ttl:
            logger.debug(f"⏱️  Using cached gallery weights (age: {current_time - self._weights_cache_time:.1f}s)")
            return self._weights_cache
        
        # Обновляем кэш
        logger.debug("⏱️  Refreshing gallery weights cache")
        self._weights_cache = self.database.get_active_gallery_weights()
        self._weights_cache_time = current_time
        
        return self._weights_cache
    
    def invalidate_weights_cache(self):
        """Инвалидация кэша весов галерей (вызывается после обновления веса)."""
        logger.debug("⏱️  Invalidating gallery weights cache")
        self._weights_cache = None
        self._weights_cache_time = 0
    
    def check_exclusion_threshold(self, gallery_id: str) -> Tuple[bool, float]:
        """
        Проверка достижения порога исключения для галереи.
        
        Пороги:
        - Галерея с 1 изображением: 1 минус → порог достигнут
        - Галерея с 2 изображениями: 1 минус → порог достигнут
        - Галерея с 3+ изображениями: ≥33.3% минусов → порог достигнут
        
        Args:
            gallery_id: ID галереи
            
        Returns:
            Tuple[bool, float]: (threshold_reached, negative_percentage)
            - threshold_reached: True если порог достигнут
            - negative_percentage: Процент минусов (0.0-100.0)
        """
        try:
            gallery_stats = self.database.get_gallery_statistics(gallery_id)
            
            if not gallery_stats:
                return (False, 0.0)
            
            total_images = gallery_stats.get('total_images', 0)
            negative_votes = gallery_stats.get('negative_votes', 0)
            negative_percentage = gallery_stats.get('negative_percentage', 0.0)
            
            # Если total_images == 0, порог не достигнут
            if total_images == 0:
                return (False, 0.0)
            
            # Проверка порогов согласно MVP
            if total_images == 1:
                # 1 изображение: 1 минус → порог достигнут
                threshold_reached = negative_votes >= 1
            elif total_images == 2:
                # 2 изображения: 1 минус → порог достигнут
                threshold_reached = negative_votes >= 1
            else:
                # 3+ изображения: ≥33.3% минусов → порог достигнут
                # Используем прямое сравнение для избежания проблем с точностью float
                # negative_percentage уже округлен до 2 знаков в get_gallery_statistics
                threshold_reached = negative_percentage >= 33.3
            
            return (threshold_reached, negative_percentage)
            
        except Exception as e:
            logger.error(f"Ошибка при проверке порога исключения для галереи {gallery_id}: {e}", exc_info=True)
            return (False, 0.0)