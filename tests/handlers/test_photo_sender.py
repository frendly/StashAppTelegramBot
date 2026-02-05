"""Тесты для модуля photo_sender."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Message, PhotoSize

from bot.handlers.photo_sender import PhotoSender


class DummyStashImage:
    """Заглушка StashImage для тестов."""

    def __init__(self, image_id: str, gallery_id: str | None = None):
        self.id = image_id
        self.gallery_id = gallery_id
        self.title = f"Image {image_id}"
        self.telegram_file_id = f"file_id_{image_id}"

    def get_gallery_title(self) -> str | None:
        """Возвращает название галереи."""
        return f"Gallery {self.gallery_id}" if self.gallery_id else None


@pytest.fixture
def mock_config():
    """Создание мока конфигурации."""
    config = MagicMock()
    config.history.avoid_recent_days = 7
    config.cache = MagicMock()
    config.cache.min_cache_size = 10
    return config


@pytest.fixture
def mock_stash_client():
    """Создание мока StashClient."""
    client = AsyncMock()
    client.save_telegram_file_id = AsyncMock(return_value=True)
    client.get_cache_size = AsyncMock(return_value=5)
    return client


@pytest.fixture
def mock_database():
    """Создание мока Database."""
    db = MagicMock()
    db.get_recent_image_ids = MagicMock(return_value=[])
    db.get_gallery_statistics = MagicMock(return_value=None)
    db.mark_threshold_notification_shown = MagicMock()
    db.get_file_id = MagicMock(return_value=None)
    db.add_sent_photo = MagicMock()
    return db


@pytest.fixture
def mock_image_selector():
    """Создание мока ImageSelector."""
    selector = AsyncMock()
    return selector


@pytest.fixture
def mock_caption_formatter():
    """Создание мока CaptionFormatter."""
    formatter = MagicMock()
    formatter.format_caption = MagicMock(return_value="Test caption")
    formatter.format_threshold_caption = MagicMock(return_value="Threshold caption")
    return formatter


@pytest.fixture
def mock_voting_manager():
    """Создание мока VotingManager."""
    manager = MagicMock()
    manager.check_exclusion_threshold = MagicMock(return_value=(False, 0.0))
    return manager


@pytest.fixture
def photo_sender(
    mock_config,
    mock_stash_client,
    mock_database,
    mock_image_selector,
    mock_caption_formatter,
    mock_voting_manager,
):
    """Создание экземпляра PhotoSender для тестов."""
    return PhotoSender(
        config=mock_config,
        stash_client=mock_stash_client,
        database=mock_database,
        image_selector=mock_image_selector,
        caption_formatter=mock_caption_formatter,
        voting_manager=mock_voting_manager,
        last_sent_images={},
        last_sent_image_id={},
    )


@pytest.fixture
def mock_context():
    """Создание мока Context для тестов."""
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_photo = AsyncMock()
    return context


@pytest.mark.asyncio
class TestPhotoSenderGetImageFromCache:
    """Тесты для метода _get_image_from_cache."""

    async def test_get_image_success(self, photo_sender, mock_context):
        """Успешное получение изображения из кэша."""
        image = DummyStashImage("img123")
        photo_sender.image_selector.get_random_image_from_cache = AsyncMock(
            return_value=image
        )

        result = await photo_sender._get_image_from_cache(12345, mock_context)

        assert result == image

    async def test_return_none_when_cache_empty(self, photo_sender, mock_context):
        """Возврат None, если кэш пуст."""
        photo_sender.image_selector.get_random_image_from_cache = AsyncMock(
            return_value=None
        )

        result = await photo_sender._get_image_from_cache(12345, mock_context)

        assert result is None
        mock_context.bot.send_message.assert_called_once()

    async def test_return_none_when_no_file_id(self, photo_sender, mock_context):
        """Возврат None, если у изображения нет file_id."""
        image = DummyStashImage("img123")
        image.telegram_file_id = None
        photo_sender.image_selector.get_random_image_from_cache = AsyncMock(
            return_value=image
        )

        result = await photo_sender._get_image_from_cache(12345, mock_context)

        assert result is None
        mock_context.bot.send_message.assert_called_once()


class TestPhotoSenderFormatCaptionWithThreshold:
    """Тесты для метода _format_caption_with_threshold."""

    def test_format_normal_caption_when_no_threshold(self, photo_sender):
        """Форматирование обычной подписи, если порог не достигнут."""
        image = DummyStashImage("img123", "gallery1")
        photo_sender.voting_manager.check_exclusion_threshold = MagicMock(
            return_value=(False, 0.0)
        )
        photo_sender.database.is_threshold_notification_shown = MagicMock(
            return_value=False
        )

        result = photo_sender._format_caption_with_threshold(image, True)

        assert result == "Test caption"
        photo_sender.caption_formatter.format_caption.assert_called_once()

    def test_format_threshold_caption_when_threshold_reached(self, photo_sender):
        """Форматирование подписи с порогом, если порог достигнут."""
        image = DummyStashImage("img123", "gallery1")
        photo_sender.voting_manager.check_exclusion_threshold = MagicMock(
            return_value=(True, 50.0)
        )
        photo_sender.database.is_threshold_notification_shown = MagicMock(
            return_value=False
        )
        photo_sender.database.get_gallery_statistics = MagicMock(
            return_value={"total_images": 10, "negative_votes": 5}
        )

        result = photo_sender._format_caption_with_threshold(image, True)

        assert result == "Threshold caption"
        photo_sender.caption_formatter.format_threshold_caption.assert_called_once()
        photo_sender.database.mark_threshold_notification_shown.assert_called_once_with(
            "gallery1"
        )


class TestPhotoSenderCreateVotingKeyboard:
    """Тесты для метода _create_voting_keyboard."""

    def test_create_keyboard_without_exclude_button(self, photo_sender):
        """Создание клавиатуры без кнопки исключения."""
        image = DummyStashImage("img123", "gallery1")
        keyboard = photo_sender._create_voting_keyboard(image, False)

        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 2

    def test_create_keyboard_with_exclude_button(self, photo_sender):
        """Создание клавиатуры с кнопкой исключения."""
        image = DummyStashImage("img123", "gallery1")
        keyboard = photo_sender._create_voting_keyboard(image, True)

        assert len(keyboard.inline_keyboard) == 2
        assert "Исключить" in keyboard.inline_keyboard[1][0].text

    def test_truncate_long_gallery_title(self, photo_sender):
        """Обрезка длинного названия галереи в кнопке."""
        image = DummyStashImage("img123", "gallery1")
        image.get_gallery_title = MagicMock(
            return_value="A" * 100
        )  # Очень длинное название
        keyboard = photo_sender._create_voting_keyboard(image, True)

        button_text = keyboard.inline_keyboard[1][0].text
        assert len(button_text) <= 64  # Лимит Telegram


@pytest.mark.asyncio
class TestPhotoSenderSendPhotoToTelegram:
    """Тесты для метода _send_photo_to_telegram."""

    async def test_send_with_context(self, photo_sender, mock_context):
        """Отправка фото через context."""
        sent_message = MagicMock(spec=Message)
        mock_context.bot.send_photo = AsyncMock(return_value=sent_message)

        success, message = await photo_sender._send_photo_to_telegram(
            12345, "file_id_123", "Test caption", MagicMock(), mock_context
        )

        assert success is True
        assert message == sent_message
        mock_context.bot.send_photo.assert_called_once()

    async def test_send_with_application(self, photo_sender):
        """Отправка фото через application."""
        sent_message = MagicMock(spec=Message)
        photo_sender.application = MagicMock()
        photo_sender.application.bot.send_photo = AsyncMock(return_value=sent_message)

        success, message = await photo_sender._send_photo_to_telegram(
            12345, "file_id_123", "Test caption", MagicMock(), None
        )

        assert success is True
        assert message == sent_message

    async def test_return_false_when_no_context_or_application(self, photo_sender):
        """Возврат False, если нет ни context, ни application."""
        photo_sender.application = None

        success, message = await photo_sender._send_photo_to_telegram(
            12345, "file_id_123", "Test caption", MagicMock(), None
        )

        assert success is False
        assert message is None


@pytest.mark.asyncio
class TestPhotoSenderUpdateFileIdIfChanged:
    """Тесты для метода _update_file_id_if_changed."""

    async def test_update_when_file_id_changed(self, photo_sender):
        """Обновление file_id, если он изменился."""
        image = DummyStashImage("img123")
        sent_message = MagicMock(spec=Message)
        photo1 = MagicMock(spec=PhotoSize)
        photo1.file_id = "small_file_id"
        photo2 = MagicMock(spec=PhotoSize)
        photo2.file_id = "new_file_id"
        sent_message.photo = [
            photo1,
            photo2,
        ]  # Telegram возвращает список размеров, берем последний

        await photo_sender._update_file_id_if_changed(
            image, sent_message, "old_file_id"
        )

        photo_sender.stash_client.save_telegram_file_id.assert_called_once_with(
            "img123", "new_file_id"
        )

    async def test_no_update_when_file_id_same(self, photo_sender):
        """Не обновлять file_id, если он не изменился."""
        image = DummyStashImage("img123")
        sent_message = MagicMock(spec=Message)
        photo1 = MagicMock(spec=PhotoSize)
        photo1.file_id = "small_file_id"
        photo2 = MagicMock(spec=PhotoSize)
        photo2.file_id = "same_file_id"
        sent_message.photo = [photo1, photo2]

        await photo_sender._update_file_id_if_changed(
            image, sent_message, "same_file_id"
        )

        photo_sender.stash_client.save_telegram_file_id.assert_not_called()

    async def test_no_update_when_no_message(self, photo_sender):
        """Не обновлять file_id, если нет сообщения."""
        image = DummyStashImage("img123")

        await photo_sender._update_file_id_if_changed(image, None, "file_id")

        photo_sender.stash_client.save_telegram_file_id.assert_not_called()
