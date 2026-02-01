"""Метрики распределения категорий изображений."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CategoryMetrics:
    """Класс для отслеживания метрик распределения категорий изображений."""

    def __init__(self):
        """Инициализация метрик."""
        # Метрики для отслеживания распределения категорий
        # Структура: {gallery_id: {"selected": {"unrated": 0, "positive": 0, "negative": 0},
        #                          "actual": {"unrated": 0, "positive": 0, "negative": 0, "none": 0},
        #                          "fallback": 0}}
        self._category_metrics: dict[str, dict[str, Any]] = {}

    def update_category_metrics(
        self,
        gallery_id: str,
        selected_category: str,
        actual_category: str,
        used_fallback: bool = False,
    ):
        """
        Обновление метрик распределения категорий.

        Args:
            gallery_id: ID галереи
            selected_category: Выбранная категория (по приоритетам)
            actual_category: Фактически использованная категория
            used_fallback: Использовался ли fallback
        """
        if gallery_id not in self._category_metrics:
            self._category_metrics[gallery_id] = {
                "selected": {"unrated": 0, "positive": 0, "negative": 0},
                "actual": {
                    "unrated": 0,
                    "positive": 0,
                    "negative": 0,
                    "any": 0,
                    "none": 0,
                },
                "fallback": 0,
            }

        metrics = self._category_metrics[gallery_id]

        # Обновляем счетчик выбранной категории
        if selected_category in metrics["selected"]:
            metrics["selected"][selected_category] += 1

        # Обновляем счетчик фактически использованной категории
        # Если категория "any" еще не существует, добавляем её
        if actual_category not in metrics["actual"]:
            metrics["actual"][actual_category] = 0
        metrics["actual"][actual_category] += 1

        # Обновляем счетчик fallback
        if used_fallback:
            metrics["fallback"] += 1

    def get_category_metrics(self, gallery_id: str | None = None) -> dict[str, Any]:
        """
        Получение метрик распределения категорий.

        Args:
            gallery_id: ID галереи (опционально, если None - возвращает все метрики)

        Returns:
            Dict: Метрики распределения категорий
        """
        if gallery_id:
            return self._category_metrics.get(
                gallery_id,
                {
                    "selected": {"unrated": 0, "positive": 0, "negative": 0},
                    "actual": {
                        "unrated": 0,
                        "positive": 0,
                        "negative": 0,
                        "any": 0,
                        "none": 0,
                    },
                    "fallback": 0,
                },
            )
        return self._category_metrics.copy()

    def _calculate_actual_percentages(self, actual: dict[str, int]) -> dict[str, float]:
        """
        Вычисление процентов для фактических категорий (исключая 'none').

        Args:
            actual: Словарь с количеством изображений по категориям

        Returns:
            Dict[str, float]: Словарь с процентами для каждой категории (кроме 'none')
        """
        actual_total_with_images = sum(v for k, v in actual.items() if k != "none")
        if actual_total_with_images == 0:
            return {k: 0.0 for k in actual.keys() if k != "none"}
        return {
            k: (v / actual_total_with_images * 100)
            for k, v in actual.items()
            if k != "none"
        }

    def log_category_metrics(self, gallery_id: str | None = None):
        """
        Логирование метрик распределения категорий.

        Args:
            gallery_id: ID галереи (опционально, если None - логирует все метрики)
        """
        if gallery_id:
            metrics = self._category_metrics.get(gallery_id)
            if not metrics:
                logger.info(f"📊 Метрики для галереи {gallery_id}: нет данных")
                return

            selected = metrics["selected"]
            actual = metrics["actual"]
            fallback = metrics["fallback"]

            total_selected = sum(selected.values())

            if total_selected > 0:
                selected_pct = {
                    k: (v / total_selected * 100) for k, v in selected.items()
                }
                fallback_pct = (
                    (fallback / total_selected * 100) if total_selected > 0 else 0
                )

                # Вычисляем проценты для фактических категорий (исключая "none")
                actual_pct_with_images = self._calculate_actual_percentages(actual)

                # Формируем строку для фактических категорий
                actual_parts = []
                for cat in ["unrated", "positive", "negative", "any"]:
                    if cat in actual:
                        count = actual[cat]
                        pct = actual_pct_with_images.get(cat, 0)
                        actual_parts.append(f"{cat}={count} ({pct:.1f}%)")

                logger.info(
                    f"📊 Метрики для галереи {gallery_id}:\n"
                    f"  Выбрано: unrated={selected['unrated']} ({selected_pct['unrated']:.1f}%), "
                    f"positive={selected['positive']} ({selected_pct['positive']:.1f}%), "
                    f"negative={selected['negative']} ({selected_pct['negative']:.1f}%)\n"
                    f"  Фактически: {', '.join(actual_parts)}, none={actual.get('none', 0)}\n"
                    f"  Fallback: {fallback} ({fallback_pct:.1f}%)"
                )
            else:
                logger.info(f"📊 Метрики для галереи {gallery_id}: нет данных")
        else:
            # Логируем все метрики
            if not self._category_metrics:
                logger.info("📊 Метрики распределения категорий: нет данных")
                return

            logger.info("📊 Метрики распределения категорий по всем галереям:")
            for gid, metrics in self._category_metrics.items():
                selected = metrics["selected"]
                actual = metrics["actual"]
                fallback = metrics["fallback"]

                total_selected = sum(selected.values())

                if total_selected > 0:
                    selected_pct = {
                        k: (v / total_selected * 100) for k, v in selected.items()
                    }
                    fallback_pct = (
                        (fallback / total_selected * 100) if total_selected > 0 else 0
                    )

                    # Вычисляем проценты для фактических категорий (исключая "none")
                    actual_pct_with_images = self._calculate_actual_percentages(actual)
                    actual_total_with_images = sum(
                        v for k, v in actual.items() if k != "none"
                    )

                    # Формируем строку для фактических категорий
                    actual_parts = []
                    for cat in ["unrated", "positive", "negative", "any"]:
                        if cat in actual:
                            count = actual[cat]
                            pct = actual_pct_with_images.get(cat, 0)
                            actual_parts.append(f"{cat}={count} ({pct:.1f}%)")

                    logger.info(
                        f"  Галерея {gid}: выбрано={total_selected} (unrated={selected_pct['unrated']:.1f}%, "
                        f"positive={selected_pct['positive']:.1f}%, negative={selected_pct['negative']:.1f}%), "
                        f"фактически={actual_total_with_images} ({', '.join(actual_parts)}, "
                        f"none={actual.get('none', 0)}), fallback={fallback_pct:.1f}%"
                    )

    def reset_category_metrics(self, gallery_id: str | None = None):
        """
        Сброс метрик распределения категорий.

        Args:
            gallery_id: ID галереи (опционально, если None - сбрасывает все метрики)
        """
        if gallery_id:
            if gallery_id in self._category_metrics:
                del self._category_metrics[gallery_id]
                logger.debug(f"Метрики для галереи {gallery_id} сброшены")
        else:
            self._category_metrics.clear()
            logger.debug("Все метрики распределения категорий сброшены")
