import random
from typing import Any

from bot.stash.selection import select_gallery_by_weight


def test_select_gallery_by_weight_simple_only_weights() -> None:
    """Простой взвешенный выбор без статистики и списка всех галерей."""
    weights = {"g1": 0.0, "g2": 1.0, "g3": 0.0}

    selected = select_gallery_by_weight(weights_dict=weights)

    assert selected == "g2"


def test_select_gallery_by_weight_returns_none_for_empty() -> None:
    """Пустой словарь весов возвращает None."""
    assert select_gallery_by_weight(weights_dict={}) is None


def test_select_gallery_by_weight_with_all_galleries_and_stats() -> None:
    """Алгоритм учитывает просмотренность и свежесть."""
    weights = {"g1": 1.0, "g2": 1.0}
    all_galleries: list[dict[str, Any]] = [
        {"id": "g1", "title": "Old & Seen", "image_count": 10},
        {"id": "g2", "title": "Fresh", "image_count": 10},
    ]
    gallery_stats = {
        "g1": {"viewed": 10, "total": 10, "last_selected": 0},
        "g2": {"viewed": 0, "total": 10, "last_selected": 0},
    }

    selected = select_gallery_by_weight(
        weights_dict=weights,
        all_galleries=all_galleries,
        gallery_stats=gallery_stats,
    )

    assert selected in {"g1", "g2"}


def test_select_gallery_by_weight_respects_excluded_galleries() -> None:
    """Исключенные галереи не могут быть выбраны."""
    weights = {"g1": 1.0, "g2": 1.0}
    all_galleries = [
        {"id": "g1", "title": "Included", "image_count": 5},
        {"id": "g2", "title": "Excluded", "image_count": 5},
    ]

    selected = select_gallery_by_weight(
        weights_dict=weights,
        all_galleries=all_galleries,
        gallery_stats={},
        excluded_galleries={"g2"},
    )

    assert selected == "g1"


def test_select_gallery_by_weight_prefers_fresh_less_viewed() -> None:
    """Свежая и мало просмотренная галерея выбирается заметно чаще."""
    weights = {"old": 1.0, "fresh": 1.0}
    all_galleries: list[dict[str, Any]] = [
        {"id": "old", "title": "Old", "image_count": 10},
        {"id": "fresh", "title": "Fresh", "image_count": 10},
    ]

    now = 1_000_000.0
    old_last_selected = now - 60 * 60
    fresh_last_selected = 0.0

    gallery_stats = {
        "old": {
            "viewed": 10,
            "total": 10,
            "last_selected": old_last_selected,
        },
        "fresh": {
            "viewed": 0,
            "total": 10,
            "last_selected": fresh_last_selected,
        },
    }

    random.seed(0)

    old_count = 0
    fresh_count = 0
    runs = 200

    for _ in range(runs):
        selected = select_gallery_by_weight(
            weights_dict=weights,
            all_galleries=all_galleries,
            gallery_stats=gallery_stats,
        )
        if selected == "old":
            old_count += 1
        elif selected == "fresh":
            fresh_count += 1

    assert fresh_count > old_count
    assert fresh_count > runs * 0.6
