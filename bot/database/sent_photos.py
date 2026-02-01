"""Модуль для работы с таблицей sent_photos."""

import logging
import sqlite3
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SentPhotosRepository:
    """Класс для работы с таблицей sent_photos."""

    def __init__(self, db_path: str):
        """
        Инициализация репозитория.

        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path

    def add_sent_photo(
        self,
        image_id: str,
        user_id: int | None = None,
        title: str | None = None,
        file_id: str | None = None,
        file_id_high_quality: str | None = None,
    ):
        """
        Добавление записи об отправленном фото.

        Args:
            image_id: ID изображения из StashApp
            user_id: Telegram ID пользователя (опционально)
            title: Название изображения (опционально)
            file_id: Telegram file_id для thumbnail (опционально)
            file_id_high_quality: Telegram file_id для high quality (опционально)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sent_photos (image_id, user_id, title, file_id, file_id_high_quality)
                VALUES (?, ?, ?, ?, ?)
            """,
                (image_id, user_id, title, file_id, file_id_high_quality),
            )
            conn.commit()
            logger.debug(
                f"Добавлена запись о фото: image_id={image_id}, file_id={file_id}, file_id_high_quality={file_id_high_quality}"
            )

    def get_recent_image_ids(self, days: int) -> list[str]:
        """
        Получение списка ID изображений, отправленных за последние N дней.

        Args:
            days: Количество дней

        Returns:
            List[str]: Список ID изображений
        """
        start_time = time.perf_counter()
        cutoff_date = datetime.now() - timedelta(days=days)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT image_id
                FROM sent_photos
                WHERE sent_at >= ?
            """,
                (cutoff_date,),
            )

            results = cursor.fetchall()
            image_ids = [row[0] for row in results]

            duration = time.perf_counter() - start_time
            logger.debug(
                f"⏱️  DB get_recent_image_ids: {duration:.3f}s ({len(image_ids)} items, {days} days)"
            )
            return image_ids

    def is_recently_sent(self, image_id: str, days: int) -> bool:
        """
        Проверка, было ли изображение отправлено недавно.

        Args:
            image_id: ID изображения
            days: Количество дней для проверки

        Returns:
            bool: True если изображение было отправлено за последние N дней
        """
        recent_ids = self.get_recent_image_ids(days)
        return image_id in recent_ids

    def get_total_sent_count(self) -> int:
        """
        Получение общего количества отправленных фото.

        Returns:
            int: Количество отправленных фото
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sent_photos")
            count = cursor.fetchone()[0]
            return count

    def get_user_sent_count(self, user_id: int) -> int:
        """
        Получение количества фото, отправленных конкретному пользователю.

        Args:
            user_id: Telegram ID пользователя

        Returns:
            int: Количество отправленных фото
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM sent_photos
                WHERE user_id = ?
            """,
                (user_id,),
            )
            count = cursor.fetchone()[0]
            return count

    def cleanup_old_records(self, days: int):
        """
        Удаление записей старше указанного количества дней.

        Args:
            days: Количество дней (записи старше будут удалены)
        """
        cutoff_date = datetime.now() - timedelta(days=days)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM sent_photos
                WHERE sent_at < ?
            """,
                (cutoff_date,),
            )
            deleted_count = cursor.rowcount
            conn.commit()
            logger.info(f"Удалено {deleted_count} старых записей (старше {days} дней)")

    def get_last_sent_photo(self) -> tuple | None:
        """
        Получение информации о последнем отправленном фото.

        Returns:
            Optional[tuple]: (image_id, sent_at, title) или None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT image_id, sent_at, title
                FROM sent_photos
                ORDER BY sent_at DESC
                LIMIT 1
            """
            )
            result = cursor.fetchone()
            return result if result else None

    def get_last_sent_photo_for_user(self, user_id: int) -> tuple | None:
        """
        Получение информации о последнем отправленном фото для конкретного пользователя.

        Args:
            user_id: Telegram ID пользователя

        Returns:
            Optional[tuple]: (image_id, sent_at, title) или None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT image_id, sent_at, title
                FROM sent_photos
                WHERE user_id = ?
                ORDER BY sent_at DESC
                LIMIT 1
            """,
                (user_id,),
            )
            result = cursor.fetchone()
            return result if result else None

    def get_file_id(self, image_id: str, use_high_quality: bool = False) -> str | None:
        """
        Получение file_id для изображения.

        Args:
            image_id: ID изображения из StashApp
            use_high_quality: Если True, возвращает file_id для высокого качества

        Returns:
            Optional[str]: file_id или None если не найден
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Валидация имени колонки для безопасности
            if use_high_quality:
                query = """
                    SELECT file_id_high_quality
                    FROM sent_photos
                    WHERE image_id = ? AND file_id_high_quality IS NOT NULL
                    ORDER BY sent_at IS NULL, sent_at DESC, id DESC
                    LIMIT 1
                """
            else:
                query = """
                    SELECT file_id
                    FROM sent_photos
                    WHERE image_id = ? AND file_id IS NOT NULL
                    ORDER BY sent_at IS NULL, sent_at DESC, id DESC
                    LIMIT 1
                """

            cursor.execute(query, (image_id,))
            result = cursor.fetchone()
            return result[0] if result else None

    def save_file_id(self, image_id: str, file_id: str, use_high_quality: bool = False):
        """
        Сохранение file_id для изображения.

        Обновляет последнюю запись для данного image_id, если file_id еще не сохранен.
        Если записи нет, создает новую запись.

        Args:
            image_id: ID изображения из StashApp
            file_id: Telegram file_id
            use_high_quality: Если True, сохраняет file_id для высокого качества
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Валидация имени колонки для безопасности
            if use_high_quality:
                column = "file_id_high_quality"
            else:
                column = "file_id"

            # SQLite не поддерживает UPDATE с ORDER BY и LIMIT
            # Используем подзапрос для получения ID последней записи
            if use_high_quality:
                update_query = """
                    UPDATE sent_photos
                    SET file_id_high_quality = ?
                    WHERE id = (
                        SELECT id FROM sent_photos
                        WHERE image_id = ? AND file_id_high_quality IS NULL
                        ORDER BY sent_at DESC
                        LIMIT 1
                    )
                """
            else:
                update_query = """
                    UPDATE sent_photos
                    SET file_id = ?
                    WHERE id = (
                        SELECT id FROM sent_photos
                        WHERE image_id = ? AND file_id IS NULL
                        ORDER BY sent_at DESC
                        LIMIT 1
                    )
                """

            cursor.execute(update_query, (file_id, image_id))

            # Если не было обновлено (нет записей или все уже имеют file_id), создаем новую запись
            if cursor.rowcount == 0:
                if use_high_quality:
                    insert_query = "INSERT INTO sent_photos (image_id, file_id_high_quality) VALUES (?, ?)"
                else:
                    insert_query = (
                        "INSERT INTO sent_photos (image_id, file_id) VALUES (?, ?)"
                    )
                cursor.execute(insert_query, (image_id, file_id))

            conn.commit()
            logger.debug(f"Сохранен {column} для image_id={image_id}: {file_id}")

    def get_random_cached_image_id(
        self, exclude_ids: list[str] | None = None
    ) -> str | None:
        """
        Получение случайного ID изображения с кешем (file_id_high_quality).

        Использует SQL для случайного выбора, что эффективнее чем загрузка всех ID.

        Args:
            exclude_ids: Список ID изображений для исключения

        Returns:
            Optional[str]: Случайный ID изображения с кешем или None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            if exclude_ids and len(exclude_ids) > 0:
                # Исключаем указанные ID
                placeholders = ",".join(["?"] * len(exclude_ids))
                query = f"""
                    SELECT DISTINCT image_id
                    FROM sent_photos
                    WHERE file_id_high_quality IS NOT NULL
                    AND image_id NOT IN ({placeholders})
                    ORDER BY RANDOM()
                    LIMIT 1
                """
                cursor.execute(query, exclude_ids)
            else:
                query = """
                    SELECT DISTINCT image_id
                    FROM sent_photos
                    WHERE file_id_high_quality IS NOT NULL
                    ORDER BY RANDOM()
                    LIMIT 1
                """
                cursor.execute(query)

            result = cursor.fetchone()
            image_id = result[0] if result else None

            if image_id:
                logger.debug(f"Найдено изображение в кеше: {image_id}")
            else:
                logger.debug("Кеш пуст или все изображения исключены")

            return image_id
