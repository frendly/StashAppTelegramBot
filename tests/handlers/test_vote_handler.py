"""Тесты для модуля vote_handler."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import CallbackQuery, Message, Update, User

from bot.handlers.vote_handler import VoteHandler


class DummyStashImage:
    """Заглушка StashImage для тестов."""

    def __init__(self, image_id: str, gallery_id: str | None = None):
        self.id = image_id
        self.gallery_id = gallery_id
        self.title = f"Image {image_id}"

    def get_gallery_title(self) -> str | None:
        """Возвращает название галереи."""
        return f"Gallery {self.gallery_id}" if self.gallery_id else None


@pytest.fixture
def mock_config():
    """Создание мока конфигурации."""
    config = MagicMock()
    config.telegram.allowed_user_ids = [12345]
    return config


@pytest.fixture
def mock_stash_client():
    """Создание мока StashClient."""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_database():
    """Создание мока Database."""
    db = MagicMock()
    return db


@pytest.fixture
def mock_caption_formatter():
    """Создание мока CaptionFormatter."""
    formatter = MagicMock()
    return formatter


@pytest.fixture
def mock_voting_manager():
    """Создание мока VotingManager."""
    manager = AsyncMock()
    manager.process_vote = AsyncMock(
        return_value={
            "image_rating_updated": True,
            "gallery_rating_updated": False,
            "performers_updated": ["Performer1"],
            "gallery_updated": "Test Gallery",
            "error": None,
        }
    )
    manager.invalidate_filtering_cache = MagicMock()
    manager.invalidate_weights_cache = MagicMock()
    return manager


@pytest.fixture
def vote_handler(
    mock_config,
    mock_stash_client,
    mock_database,
    mock_caption_formatter,
    mock_voting_manager,
):
    """Создание экземпляра VoteHandler для тестов."""
    handler = VoteHandler(
        config=mock_config,
        stash_client=mock_stash_client,
        database=mock_database,
        caption_formatter=mock_caption_formatter,
        voting_manager=mock_voting_manager,
        last_sent_images={},
        last_sent_image_id={},
    )
    # Устанавливаем check_authorization как мок
    handler.check_authorization = AsyncMock(return_value=True)
    return handler


@pytest.fixture
def mock_update():
    """Создание мока Update для тестов."""
    update = MagicMock(spec=Update)
    update.effective_user = User(id=12345, is_bot=False, first_name="Test")
    update.callback_query = MagicMock(spec=CallbackQuery)
    update.callback_query.data = "vote_up_image123"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    update.callback_query.message = MagicMock(spec=Message)
    update.callback_query.message.chat_id = 12345
    return update


@pytest.fixture
def mock_context():
    """Создание мока Context для тестов."""
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    return context


class TestVoteHandlerParseCallbackData:
    """Тесты для метода _parse_vote_callback_data."""

    def test_parse_valid_vote_up(self, vote_handler):
        """Парсинг корректного callback для лайка."""
        result = vote_handler._parse_vote_callback_data("vote_up_image123")
        assert result == ("up", "image123")

    def test_parse_valid_vote_down(self, vote_handler):
        """Парсинг корректного callback для дизлайка."""
        result = vote_handler._parse_vote_callback_data("vote_down_image456")
        assert result == ("down", "image456")

    def test_parse_invalid_prefix(self, vote_handler):
        """Парсинг callback с неверным префиксом."""
        result = vote_handler._parse_vote_callback_data("invalid_data")
        assert result is None

    def test_parse_invalid_format(self, vote_handler):
        """Парсинг callback с неверным форматом."""
        result = vote_handler._parse_vote_callback_data("vote_image123")
        assert result is None

    def test_parse_too_many_parts(self, vote_handler):
        """Парсинг callback с слишком большим количеством частей."""
        result = vote_handler._parse_vote_callback_data("vote_up_image123_extra")
        assert result is None


class TestVoteHandlerBuildResponseMessage:
    """Тесты для метода _build_vote_response_message."""

    def test_build_message_with_all_updates(self, vote_handler):
        """Формирование сообщения со всеми обновлениями."""
        result = {
            "image_rating_updated": True,
            "gallery_rating_updated": True,
            "performers_updated": ["Perf1", "Perf2", "Perf3", "Perf4"],
            "gallery_updated": "Test Gallery",
            "error": None,
        }
        message = vote_handler._build_vote_response_message(result, 1)
        assert "👍" in message
        assert "Рейтинг фото обновлен: 5/5" in message
        assert "Перформеры обновлены: Perf1, Perf2, Perf3" in message
        assert "Галерея обновлена: Test Gallery" in message
        assert "Рейтинг галереи установлен" in message

    def test_build_message_with_error(self, vote_handler):
        """Формирование сообщения с ошибкой."""
        result = {
            "image_rating_updated": False,
            "gallery_rating_updated": False,
            "performers_updated": [],
            "gallery_updated": None,
            "error": "Test error",
        }
        message = vote_handler._build_vote_response_message(result, -1)
        assert "👎" in message
        assert "Ошибка: Test error" in message

    def test_build_message_minimal(self, vote_handler):
        """Формирование минимального сообщения."""
        result = {
            "image_rating_updated": False,
            "gallery_rating_updated": False,
            "performers_updated": [],
            "gallery_updated": None,
            "error": None,
        }
        message = vote_handler._build_vote_response_message(result, 1)
        assert "👍" in message
        assert "Ваш голос учтен!" in message


class TestVoteHandlerCreateVotedKeyboard:
    """Тесты для метода _create_voted_keyboard."""

    def test_create_keyboard_for_like(self, vote_handler):
        """Создание клавиатуры для лайка."""
        image = DummyStashImage("img123", "gallery1")
        keyboard = vote_handler._create_voted_keyboard("img123", 1, image)
        assert len(keyboard.inline_keyboard) == 1
        assert "✓ 👍" in keyboard.inline_keyboard[0][0].text

    def test_create_keyboard_for_dislike_with_gallery(self, vote_handler):
        """Создание клавиатуры для дизлайка с галереей."""
        image = DummyStashImage("img123", "gallery1")
        keyboard = vote_handler._create_voted_keyboard("img123", -1, image)
        assert len(keyboard.inline_keyboard) == 2
        assert "✓ 👎" in keyboard.inline_keyboard[0][1].text
        assert "Исключить" in keyboard.inline_keyboard[1][0].text

    def test_create_keyboard_for_dislike_without_gallery(self, vote_handler):
        """Создание клавиатуры для дизлайка без галереи."""
        image = DummyStashImage("img123", None)
        keyboard = vote_handler._create_voted_keyboard("img123", -1, image)
        assert len(keyboard.inline_keyboard) == 1
        assert "✓ 👎" in keyboard.inline_keyboard[0][1].text


class TestVoteHandlerShouldSendNewImage:
    """Тесты для метода _should_send_new_image."""

    def test_should_send_when_last_in_cache(self, vote_handler):
        """Отправка нового изображения, если текущее последнее в кэше."""
        vote_handler._last_sent_image_id[12345] = "img123"
        result = vote_handler._should_send_new_image(12345, "img123")
        assert result is True

    def test_should_not_send_when_not_last_in_cache(self, vote_handler):
        """Не отправлять новое изображение, если текущее не последнее в кэше."""
        vote_handler._last_sent_image_id[12345] = "img456"
        result = vote_handler._should_send_new_image(12345, "img123")
        assert result is False

    def test_should_send_when_last_in_db(self, vote_handler, mock_database):
        """Отправка нового изображения, если текущее последнее в БД."""
        vote_handler._last_sent_image_id = {}
        vote_handler.database.get_last_sent_photo_for_user = MagicMock(
            return_value=("img123", None, None)
        )
        result = vote_handler._should_send_new_image(12345, "img123")
        assert result is True

    def test_should_send_when_no_records(self, vote_handler, mock_database):
        """Отправка нового изображения, если нет записей в БД."""
        vote_handler._last_sent_image_id = {}
        vote_handler.database.get_last_sent_photo_for_user = MagicMock(
            return_value=None
        )
        result = vote_handler._should_send_new_image(12345, "img123")
        assert result is True


@pytest.mark.asyncio
class TestVoteHandlerGetImageForVote:
    """Тесты для метода _get_image_for_vote."""

    async def test_get_image_from_cache(self, vote_handler):
        """Получение изображения из кэша."""
        image = DummyStashImage("img123")
        vote_handler._last_sent_images[12345] = image
        result = await vote_handler._get_image_for_vote(12345, "img123")
        assert result == image
        vote_handler.stash_client.get_image_by_id.assert_not_called()

    async def test_get_image_from_api_when_not_in_cache(self, vote_handler):
        """Получение изображения из API, если его нет в кэше."""
        vote_handler._last_sent_images = {}
        image = DummyStashImage("img123")
        vote_handler.stash_client.get_image_by_id = AsyncMock(return_value=image)
        result = await vote_handler._get_image_for_vote(12345, "img123")
        assert result == image
        vote_handler.stash_client.get_image_by_id.assert_called_once_with("img123")

    async def test_return_none_when_image_not_found(self, vote_handler):
        """Возврат None, если изображение не найдено."""
        vote_handler._last_sent_images = {}
        vote_handler.stash_client.get_image_by_id = AsyncMock(return_value=None)
        result = await vote_handler._get_image_for_vote(12345, "img123")
        assert result is None
