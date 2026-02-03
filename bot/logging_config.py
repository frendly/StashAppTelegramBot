"""Конфигурация логирования с поддержкой JSON, ротации и контекстных переменных."""

import logging
import os
import sys
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Any

from pythonjsonlogger import jsonlogger

# Контекстные переменные для трейсинга
request_id: ContextVar[str] = ContextVar("request_id", default="")
user_id: ContextVar[int | None] = ContextVar("user_id", default=None)
image_id: ContextVar[str | None] = ContextVar("image_id", default=None)
gallery_id: ContextVar[str | None] = ContextVar("gallery_id", default=None)


class ContextualJsonFormatter(jsonlogger.JsonFormatter):
    """JSON форматтер с автоматическим добавлением контекстных переменных."""

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        """
        Добавление полей в JSON лог, включая контекстные переменные.

        Args:
            log_record: Словарь для записи лога
            record: Запись лога
            message_dict: Словарь с сообщением
        """
        super().add_fields(log_record, record, message_dict)

        # Добавляем контекстные переменные
        current_request_id = request_id.get()
        if current_request_id:
            log_record["request_id"] = current_request_id

        current_user_id = user_id.get()
        if current_user_id is not None:
            log_record["user_id"] = current_user_id

        current_image_id = image_id.get()
        if current_image_id:
            log_record["image_id"] = current_image_id

        current_gallery_id = gallery_id.get()
        if current_gallery_id:
            log_record["gallery_id"] = current_gallery_id


def set_request_context(
    request_id_value: str | None = None,
    user_id_value: int | None = None,
    image_id_value: str | None = None,
    gallery_id_value: str | None = None,
) -> str:
    """
    Установка контекста для текущей операции.

    Args:
        request_id_value: ID запроса/операции (если None, генерируется автоматически)
        user_id_value: ID пользователя Telegram
        image_id_value: ID изображения
        gallery_id_value: ID галереи

    Returns:
        str: ID запроса (сгенерированный или переданный)
    """
    if request_id_value is None:
        request_id_value = f"req_{uuid.uuid4().hex[:12]}"
    request_id.set(request_id_value)

    if user_id_value is not None:
        user_id.set(user_id_value)

    if image_id_value is not None:
        image_id.set(image_id_value)

    if gallery_id_value is not None:
        gallery_id.set(gallery_id_value)

    return request_id_value


def clear_request_context():
    """Очистка контекста текущей операции."""
    request_id.set("")
    user_id.set(None)
    image_id.set(None)
    gallery_id.set(None)


def get_request_context() -> dict[str, Any]:
    """
    Получение текущего контекста операции.

    Returns:
        dict: Словарь с текущими значениями контекстных переменных
    """
    return {
        "request_id": request_id.get(),
        "user_id": user_id.get(),
        "image_id": image_id.get(),
        "gallery_id": gallery_id.get(),
    }


@contextmanager
def request_context(
    request_id_value: str | None = None,
    user_id_value: int | None = None,
    image_id_value: str | None = None,
    gallery_id_value: str | None = None,
):
    """
    Context manager для автоматической установки и очистки контекста.

    Args:
        request_id_value: ID запроса/операции (если None, генерируется автоматически)
        user_id_value: ID пользователя Telegram
        image_id_value: ID изображения
        gallery_id_value: ID галереи

    Yields:
        str: ID запроса (сгенерированный или переданный)

    Example:
        with request_context(user_id=123, image_id="img_456"):
            logger.info("Отправка фото")  # Автоматически добавит user_id и image_id
        # Контекст автоматически очищен
    """
    req_id = set_request_context(
        request_id_value=request_id_value,
        user_id_value=user_id_value,
        image_id_value=image_id_value,
        gallery_id_value=gallery_id_value,
    )
    try:
        yield req_id
    finally:
        clear_request_context()


def setup_logging(
    log_path: str = "bot.log",
    log_level: str = "INFO",
    json_format: bool = True,
    console_format: str = "text",
    rotation: dict[str, Any] | None = None,
) -> None:
    """
    Настройка логирования с поддержкой JSON, ротации и контекста.

    Args:
        log_path: Путь к файлу логов
        log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Использовать JSON формат для файлового вывода
        console_format: Формат для консоли ("json" или "text")
        rotation: Настройки ротации логов:
            - type: "size" или "time"
            - max_bytes: максимальный размер файла (для type="size")
            - backup_count: количество резервных файлов
            - when: "midnight", "H", "D", "W0" и т.д. (для type="time")
            - interval: интервал ротации (для type="time")
    """
    # Создаем директорию для логов, если нужно
    log_dir = os.path.dirname(log_path) if os.path.dirname(log_path) else "."
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            # Если не удалось создать директорию, логируем ошибку через logging
            # Используем базовый logger, так как настройка еще не завершена
            temp_logger = logging.getLogger(__name__)
            temp_logger.warning(
                f"Не удалось создать директорию для логов {log_dir}: {e}. "
                "Логирование будет работать, но файл может не создаться."
            )

    # Преобразуем строковый уровень в числовой
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Настройка файлового обработчика
    if rotation and rotation.get("type") == "time":
        # Ротация по времени
        when = rotation.get("when", "midnight")
        interval = rotation.get("interval", 1)
        backup_count = rotation.get("backup_count", 30)

        # Валидация параметров
        if not isinstance(interval, int) or interval < 1:
            raise ValueError(
                f"rotation.interval должен быть положительным целым числом, получено: {interval}"
            )
        if not isinstance(backup_count, int) or backup_count < 1:
            raise ValueError(
                f"rotation.backup_count должен быть положительным целым числом, получено: {backup_count}"
            )

        file_handler = TimedRotatingFileHandler(
            log_path,
            when=when,
            interval=interval,
            backupCount=backup_count,
            encoding="utf-8",
        )
    elif rotation and rotation.get("type") == "size":
        # Ротация по размеру
        max_bytes = rotation.get("max_bytes", 10 * 1024 * 1024)  # 10MB по умолчанию
        backup_count = rotation.get("backup_count", 5)

        # Валидация параметров
        if not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError(
                f"rotation.max_bytes должен быть положительным целым числом, получено: {max_bytes}"
            )
        if not isinstance(backup_count, int) or backup_count < 1:
            raise ValueError(
                f"rotation.backup_count должен быть положительным целым числом, получено: {backup_count}"
            )

        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
    elif rotation and rotation.get("type") not in ("time", "size"):
        raise ValueError(
            f"rotation.type должен быть 'time' или 'size', получено: {rotation.get('type')}"
        )
    else:
        # Без ротации
        file_handler = logging.FileHandler(log_path, encoding="utf-8")

    # Форматтер для файла
    if json_format:
        file_formatter = ContextualJsonFormatter(
            "%(timestamp)s %(level)s %(name)s %(message)s",
            timestamp=True,
        )
    else:
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(numeric_level)

    # Настройка консольного обработчика
    console_handler = logging.StreamHandler(sys.stdout)

    if console_format == "json":
        console_formatter = ContextualJsonFormatter(
            "%(timestamp)s %(level)s %(name)s %(message)s",
            timestamp=True,
        )
    else:
        # Человекочитаемый формат для консоли
        console_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(numeric_level)

    # Настройка корневого логгера
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.handlers.clear()  # Очищаем существующие обработчики
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
