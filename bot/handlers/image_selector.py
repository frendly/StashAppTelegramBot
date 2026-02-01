"""Выбор случайного изображения."""

import logging
from typing import List, Optional

from bot.stash_client import StashClient, StashImage, select_gallery_by_weight
from bot.database import Database

logger = logging.getLogger(__name__)


class ImageSelector:
    """Класс для выбора случайного изображения с учетом весов и фильтров."""
    
    def __init__(self, stash_client: StashClient, database: Database, voting_manager=None):
        """
        Инициализация селектора.
        
        Args:
            stash_client: Клиент StashApp
            database: База данных
            voting_manager: Менеджер голосования (опционально)
        """
        self.stash_client = stash_client
        self.database = database
        self.voting_manager = voting_manager
    
    async def get_random_image(self, exclude_ids: List[str], update_last_selected: bool = True) -> Optional[StashImage]:
        """
        Получение случайного изображения с учетом фильтров и предпочтений.
        
        Использует взвешенный случайный выбор галереи на основе весов.
        При отсутствии весов или ошибках использует fallback на старый метод.
        
        Args:
            exclude_ids: Список ID изображений для исключения
            update_last_selected: Если True, обновляет время последнего выбора галереи.
                                Если False, пропускает обновление (для служебных операций)
            
        Returns:
            Optional[StashImage]: Случайное изображение или None
        """
        # Если нет voting_manager, используем старый метод
        if not self.voting_manager:
            return await self.stash_client.get_random_image_with_retry(
                exclude_ids=exclude_ids,
                max_retries=5
            )
        
        # Пытаемся использовать взвешенный выбор галереи с учетом всех галерей из StashApp
        try:
            # Получаем все галереи из StashApp (с кэшированием)
            all_galleries = await self.stash_client.get_all_galleries_cached()
            
            if not all_galleries:
                logger.warning("Не удалось получить список галерей из StashApp, используем старый метод")
            else:
                # Получаем веса активных галерей из БД (используем кэшированную версию)
                weights_dict = self.voting_manager.get_cached_gallery_weights()
                
                # Получаем статистику по галереям (сколько изображений просмотрено, время последнего выбора)
                gallery_stats = self.database.get_gallery_stats_with_viewed_counts()
                
                # Получаем список исключенных галерей
                filtering_lists = self.voting_manager.get_filtering_lists()
                excluded_galleries = set(filtering_lists.get('blacklisted_galleries', []))
                
                # Выбираем галерею с учетом всех факторов (все галереи, просмотренность, свежесть)
                selected_gallery_id = select_gallery_by_weight(
                    weights_dict=weights_dict,
                    all_galleries=all_galleries,
                    gallery_stats=gallery_stats,
                    excluded_galleries=excluded_galleries
                )
                
                if selected_gallery_id:
                    # Обновляем время последнего выбора галереи только если это не служебная операция
                    if update_last_selected:
                        try:
                            self.database.update_gallery_last_selected(selected_gallery_id)
                        except Exception as e:
                            logger.debug(f"Не удалось обновить last_selected_at для галереи {selected_gallery_id}: {e}")
                    
                    # Получаем случайное изображение из выбранной галереи с учетом приоритетов по рейтингу
                    image = await self.stash_client.get_random_image_from_gallery_weighted(
                        gallery_id=selected_gallery_id,
                        exclude_ids=exclude_ids
                    )
                    
                    if image:
                        logger.debug(f"Изображение получено из галереи {selected_gallery_id} (взвешенный выбор с учетом всех галерей, просмотренности и свежести)")
                        return image
                    else:
                        logger.warning(f"🔄 Fallback level 1: Не удалось получить изображение из галереи {selected_gallery_id} (все категории пусты), используем старый метод с фильтрацией")
                else:
                    logger.warning("🔄 Fallback level 1: Не удалось выбрать галерею взвешенным выбором, используем старый метод с фильтрацией")
        except Exception as e:
            logger.warning(f"🔄 Fallback level 1: Ошибка при взвешенном выборе галереи: {e}, используем старый метод с фильтрацией", exc_info=True)
        
        # Fallback level 1: используем старый метод с фильтрацией
        try:
            filtering_lists = self.voting_manager.get_filtering_lists()
            image = await self.stash_client.get_random_image_weighted(
                exclude_ids=exclude_ids,
                blacklisted_performers=filtering_lists['blacklisted_performers'],
                blacklisted_galleries=filtering_lists['blacklisted_galleries'],
                whitelisted_performers=filtering_lists['whitelisted_performers'],
                whitelisted_galleries=filtering_lists['whitelisted_galleries'],
                max_retries=5
            )
            if image:
                logger.info("✅ Fallback level 1 успешен: изображение получено через старый метод с фильтрацией")
                return image
            else:
                logger.warning("🔄 Fallback level 2: Старый метод с фильтрацией не вернул изображение, используем базовый метод")
        except Exception as e:
            logger.warning(f"🔄 Fallback level 2: Ошибка при fallback методе с фильтрацией: {e}, используем базовый метод", exc_info=True)
        
        # Fallback level 2: базовый метод без фильтрации
        logger.info("🔄 Fallback level 2: Используем базовый метод без фильтрации")
        return await self.stash_client.get_random_image_with_retry(
            exclude_ids=exclude_ids,
            max_retries=5
        )
