"""Алгоритмы выбора галерей."""

import logging
import random
import time
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Константы для алгоритма взвешенного выбора
COVERAGE_PENALTY_MULTIPLIER = 0.5  # Множитель штрафа за просмотренность (50% при 100% покрытии)
FRESHNESS_BONUS_PER_DAY = 0.5  # Бонус за каждый день без выбора (50%)
MAX_FRESHNESS_BONUS = 2.0  # Максимальный бонус за свежесть (200%)
MAX_DAYS_FOR_FRESHNESS = 4  # Количество дней для достижения максимального бонуса


def select_gallery_by_weight(
    weights_dict: Dict[str, float],
    all_galleries: Optional[List[Dict[str, Any]]] = None,
    gallery_stats: Optional[Dict[str, Dict[str, Any]]] = None,
    excluded_galleries: Optional[set] = None
) -> Optional[str]:
    """
    Взвешенный случайный выбор галереи с учетом всех галерей из StashApp,
    просмотренности и свежести.
    
    Алгоритм:
    1. Если передан список всех галерей, использует его (включая галереи без записей в БД)
    2. Для каждой галереи вычисляет модифицированный вес с учетом:
       - Базового веса из БД (или 1.0 по умолчанию)
       - Штрафа за просмотренность (чем больше просмотрено, тем меньше вес)
       - Бонуса за свежесть (чем дольше не выбиралась, тем больше вес)
    3. Выполняет взвешенный случайный выбор
    
    Args:
        weights_dict: Словарь {gallery_id: weight} с весами из БД
        all_galleries: Список всех галерей из StashApp [{id, title, image_count}]
        gallery_stats: Статистика по галереям {gallery_id: {viewed: int, total: int, last_selected: float}}
        excluded_galleries: Множество ID исключенных галерей (опционально)
        
    Returns:
        Optional[str]: ID выбранной галереи или None если словарь пуст
    """
    # Если список всех галерей не передан, используем старую логику (только галереи из БД)
    if not all_galleries:
        if not weights_dict:
            return None
        
        total_weight = sum(weights_dict.values())
        if total_weight <= 0:
            logger.warning("Сумма весов галерей <= 0, невозможно выбрать галерею")
            return None
        
        random_value = random.uniform(0, total_weight)
        accumulated_weight = 0.0
        for gallery_id, weight in weights_dict.items():
            accumulated_weight += weight
            if random_value <= accumulated_weight:
                logger.debug(f"Выбрана галерея {gallery_id} с весом {weight:.3f} (random={random_value:.3f}, total={total_weight:.3f})")
                return gallery_id
        
        last_gallery_id = list(weights_dict.keys())[-1]
        logger.warning(f"Floating point edge case: возвращаем последнюю галерею {last_gallery_id}")
        return last_gallery_id
    
    # Новая логика: работаем со всеми галереями из StashApp
    gallery_stats = gallery_stats or {}
    excluded_galleries = excluded_galleries or set()
    current_time = time.time()
    modified_weights = {}
    
    # Проходим по всем галереям из StashApp
    for gallery in all_galleries:
        gallery_id = gallery['id']
        
        # Пропускаем исключенные галереи
        if gallery_id in excluded_galleries:
            logger.debug(f"Пропускаем исключенную галерею {gallery_id}")
            continue
        
        total_images = gallery.get('image_count', 0)
        
        # Получаем вес из БД или используем 1.0 по умолчанию
        base_weight = weights_dict.get(gallery_id, 1.0)
        
        # Если вес равен 0 или отрицательный, пропускаем (возможно, галерея исключена)
        if base_weight <= 0:
            logger.debug(f"Пропускаем галерею {gallery_id} с неположительным весом {base_weight}")
            continue
        
        # Получаем статистику
        stats = gallery_stats.get(gallery_id, {})
        viewed = stats.get('viewed', 0)
        last_selected = stats.get('last_selected', 0)
        
        # 1. Штраф за просмотренность (чем больше просмотрено, тем меньше вес)
        if total_images > 0:
            coverage_ratio = viewed / total_images  # 0.0 - 1.0
            # Если просмотрено 50%, вес уменьшается на 25%
            # Если просмотрено 100%, вес уменьшается на 50%
            coverage_penalty = 1.0 - (coverage_ratio * COVERAGE_PENALTY_MULTIPLIER)
        else:
            coverage_ratio = 0.0  # Для логирования
            coverage_penalty = 1.0
        
        # 2. Бонус за свежесть (время с последнего выбора)
        if last_selected == 0:
            days_since = MAX_DAYS_FOR_FRESHNESS + 1  # Никогда не выбиралась - максимальный бонус
        else:
            days_since = (current_time - last_selected) / 86400
        
        # Бонус: +50% за каждый день без выбора (макс +200% за 4+ дня)
        freshness_bonus = min(days_since * FRESHNESS_BONUS_PER_DAY, MAX_FRESHNESS_BONUS)
        freshness_multiplier = 1.0 + freshness_bonus
        
        # Финальный вес
        modified_weight = base_weight * coverage_penalty * freshness_multiplier
        
        # Проверяем, что вес не стал отрицательным или нулевым
        if modified_weight <= 0:
            logger.debug(f"Пропускаем галерею {gallery_id} с нулевым/отрицательным модифицированным весом")
            continue
        
        modified_weights[gallery_id] = modified_weight
        
        logger.debug(
            f"Галерея {gallery.get('title', gallery_id)}: base={base_weight:.2f}, "
            f"viewed={viewed}/{total_images}, coverage={coverage_ratio*100:.1f}%, "
            f"days_since={days_since:.1f}, final={modified_weight:.2f}"
        )
    
    # Стандартный алгоритм взвешенного выбора
    total_weight = sum(modified_weights.values())
    if total_weight <= 0:
        logger.warning("Сумма модифицированных весов <= 0")
        return None
    
    random_value = random.uniform(0, total_weight)
    accumulated_weight = 0.0
    
    for gallery_id, weight in modified_weights.items():
        accumulated_weight += weight
        if random_value <= accumulated_weight:
            # Находим название галереи для лога
            gallery_title = next(
                (g.get('title', gallery_id) for g in all_galleries if g['id'] == gallery_id),
                gallery_id
            )
            logger.info(
                f"Выбрана галерея {gallery_title} ({gallery_id}) "
                f"с модифицированным весом {weight:.3f} "
                f"(random={random_value:.3f}, total={total_weight:.3f})"
            )
            return gallery_id
    
    # Fallback
    last_gallery_id = list(modified_weights.keys())[-1]
    logger.warning(f"Floating point edge case: возвращаем последнюю галерею {last_gallery_id}")
    return last_gallery_id
