"""Модуль для обработки голосований за изображения."""

import logging
import time
from typing import List, Dict, Any, Optional

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