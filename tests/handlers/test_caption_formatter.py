from typing import Any

from bot.database import Database
from bot.handlers.caption_formatter import CaptionFormatter


class DummyImage:
    """Простая заглушка для StashImage в тестах."""

    def __init__(
        self,
        gallery_id: str | None = None,
        gallery_title: str | None = None,
        performers: list[dict[str, Any]] | None = None,
        title: str | None = None,
    ) -> None:
        self.gallery_id = gallery_id
        self._gallery_title = gallery_title
        self.performers = performers or []
        self.title = title

    def get_gallery_title(self) -> str | None:
        """Возврат названия галереи (имитация StashImage)."""
        return self._gallery_title


def test_calculate_display_rating_no_votes(database: Database) -> None:
    """При отсутствии голосов рейтинг и звезды нейтральные."""
    formatter = CaptionFormatter(database)

    stars, rating = formatter.calculate_display_rating(0, 0)

    assert stars == "☆☆☆☆☆"
    assert rating == 0.0


def test_calculate_display_rating_positive_and_negative(database: Database) -> None:
    """Проверка расчета рейтинга при смешанных голосах."""
    formatter = CaptionFormatter(database)

    stars, rating = formatter.calculate_display_rating(
        positive_votes=3,
        negative_votes=1,
    )

    assert stars in {"⭐⭐⭐⭐☆", "⭐⭐⭐⭐⭐"}
    assert 3.5 <= rating <= 5.0


def test_format_progress_bar_zero_total(database: Database) -> None:
    """При отсутствии изображений прогресс-бар не выводится."""
    formatter = CaptionFormatter(database)

    text = formatter.format_progress_bar(negative_votes=0, total_images=0)
    assert text == ""


def test_format_progress_bar_basic(database: Database) -> None:
    """Базовый случай прогресс-бара с корректным процентом и счетчиком."""
    formatter = CaptionFormatter(database)

    text = formatter.format_progress_bar(negative_votes=3, total_images=10)
    assert "30%" in text
    assert "(3/10)" in text
    assert "[" in text and "]" in text


def test_format_progress_bar_clamps_negative_votes(database: Database) -> None:
    """Количество минусов не может быть больше общего количества изображений."""
    formatter = CaptionFormatter(database)

    text = formatter.format_progress_bar(negative_votes=15, total_images=10)
    assert "100%" in text
    assert "(10/10)" in text


def test_format_caption_without_gallery_uses_simple_format(database: Database) -> None:
    """Без gallery_id используется упрощенный формат подписи."""
    formatter = CaptionFormatter(database)

    image = DummyImage(
        gallery_id=None,
        gallery_title=None,
        performers=[],
        title="Some title",
    )

    caption = formatter.format_caption(image, is_preloaded_from_cache=True)

    assert "👤 Перформер: не указан" in caption
    assert "📊 Галерея: не указан" in caption
    assert "Some title" in caption
    assert "⚡ Предзагружено" in caption


def test_format_caption_with_gallery_no_stats_uses_simplified(
    database: Database,
) -> None:
    """При отсутствии статистики по галерее используется упрощенный формат."""
    formatter = CaptionFormatter(database)

    database.ensure_gallery_exists("g1", "Gallery 1")

    image = DummyImage(
        gallery_id="g1",
        gallery_title="Gallery 1",
        performers=[{"name": "Performer"}],
        title="Image title",
    )

    caption = formatter.format_caption(image, is_preloaded_from_cache=False)

    assert '📊 Галерея: "Gallery 1"' in caption
    assert "Вес:" not in caption
    assert "Прогресс:" not in caption


def test_format_caption_with_stats_and_weight(database: Database) -> None:
    """При наличии статистики и весов показываются вес, рейтинг и прогресс-бар."""
    formatter = CaptionFormatter(database)

    database.ensure_gallery_exists("g2", "Gallery 2")

    for _ in range(3):
        database.update_gallery_preference("g2", "Gallery 2", vote=1)
    database.update_gallery_preference("g2", "Gallery 2", vote=-1)

    database.update_gallery_image_count("g2", total_images=10)

    image = DummyImage(
        gallery_id="g2",
        gallery_title="Gallery 2",
        performers=[{"name": "P1"}, {"name": "P2"}],
        title=None,
    )

    caption = formatter.format_caption(image, is_preloaded_from_cache=True)

    assert "Вес:" in caption
    assert "⭐" in caption
    assert "Прогресс:" in caption
    assert "⚡ Предзагружено" in caption


def test_format_threshold_caption_full_stats(database: Database) -> None:
    """Форматирование подписи при достижении порога исключения."""
    formatter = CaptionFormatter(database)

    image = DummyImage(
        gallery_id="g3",
        gallery_title="Gallery 3",
        performers=[{"name": "P1"}],
    )

    gallery_stats = {
        "gallery_id": "g3",
        "total_images": 20,
        "positive_votes": 5,
        "negative_votes": 12,
        "negative_percentage": 60.0,
        "images_count_updated_at": None,
    }

    caption = formatter.format_threshold_caption(
        image=image,
        gallery_stats=gallery_stats,
        is_preloaded_from_cache=True,
    )

    assert "👤 Перформер: P1" in caption
    assert '📊 Галерея: "Gallery 3"' in caption
    assert "Прогресс:" in caption
    assert "• Всего изображений: 20" in caption
    assert '• Получили "+": 5' in caption
    assert '• Получили "-": 12 (60%)' in caption
    assert "• Без оценки: 3" in caption
    assert "⚡ Предзагружено" in caption


def test_format_threshold_caption_zero_total(database: Database) -> None:
    """При total_images = 0 возвращается только базовая информация и количество изображений."""
    formatter = CaptionFormatter(database)

    image = DummyImage(
        gallery_id="g4",
        gallery_title="Gallery 4",
        performers=[],
    )

    gallery_stats = {
        "gallery_id": "g4",
        "total_images": 0,
        "positive_votes": 0,
        "negative_votes": 0,
        "negative_percentage": 0.0,
        "images_count_updated_at": None,
    }

    caption = formatter.format_threshold_caption(
        image=image,
        gallery_stats=gallery_stats,
        is_preloaded_from_cache=False,
    )

    assert "• Всего изображений: 0" in caption
