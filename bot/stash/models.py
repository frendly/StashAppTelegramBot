"""Модели данных для StashApp."""

import os
from typing import Any


class StashImage:
    """Класс представляющий изображение из StashApp."""

    def __init__(self, data: dict[str, Any]):
        """
        Инициализация объекта изображения.

        Args:
            data: Данные изображения из GraphQL ответа
        """
        self.id = data["id"]
        self.title = data.get("title", "Без названия")
        self.rating = data.get("rating100", 0)

        # Сохраняем все варианты качества для возможности выбора
        paths = data.get("paths", {})
        self._thumbnail_url = paths.get("thumbnail", "")
        self._preview_url = paths.get("preview", "")
        self._image_url = paths.get("image", "")

        # По умолчанию используем thumbnail для максимально быстрой загрузки
        self.image_url = self._thumbnail_url or self._preview_url or self._image_url

        # Теги опциональны (могут не запрашиваться для ускорения)
        self.tags = [tag["name"] for tag in data.get("tags", [])]

        # Информация о галерее
        galleries = data.get("galleries", [])
        if galleries:
            gallery = galleries[0]
            self.gallery_id = gallery["id"]
            self.gallery_title = gallery.get("title")

            # Сохраняем folder для возможного использования в форматтере
            self.gallery_folder = gallery.get("folder")

            # Сохраняем files для fallback на путь файла
            self.gallery_files = gallery.get("files", [])

            # Если title пустой или None, извлекаем название из пути к папке или файлу
            if not self.gallery_title or (
                isinstance(self.gallery_title, str) and not self.gallery_title.strip()
            ):
                if self.gallery_folder:
                    folder_path = self.gallery_folder.get("path", "")
                    if folder_path:
                        # Извлекаем последнюю часть пути (название папки)
                        # Например: /data/images/hetrainsherass -> hetrainsherass
                        folder_name = os.path.basename(folder_path.rstrip("/"))
                        if folder_name:
                            self.gallery_title = folder_name
                # Если folder тоже нет, пытаемся извлечь из files[0].path
                elif self.gallery_files:
                    first_file = self.gallery_files[0]
                    file_path = first_file.get("path", "")
                    if file_path:
                        # Извлекаем имя файла без расширения
                        # Например: /path/to/file.zip -> file
                        file_name = os.path.basename(file_path)
                        if file_name:
                            # Убираем расширение
                            name_without_ext = os.path.splitext(file_name)[0]
                            if name_without_ext:
                                self.gallery_title = name_without_ext
        else:
            self.gallery_id = None
            self.gallery_title = None
            self.gallery_folder = None
            self.gallery_files = []

        # Информация о перформерах
        self.performers = [
            {"id": p["id"], "name": p["name"]} for p in data.get("performers", [])
        ]

        # Telegram file_id (хранится в поле details в StashApp)
        # details содержит telegram_file_id как простую строку
        self.telegram_file_id = data.get("details")

    def get_image_url(self, use_high_quality: bool = False) -> str:
        """
        Получение URL изображения с указанным качеством.

        Args:
            use_high_quality: Если True, использует preview (или image если preview нет)
                            Если False, использует thumbnail (быстро, низкое качество)

        Returns:
            str: URL изображения
        """
        if use_high_quality:
            # Для высокого качества используем preview, fallback на image
            return self._preview_url or self._image_url or self._thumbnail_url
        else:
            # Для быстрой загрузки используем thumbnail, fallback на preview и image
            return self._thumbnail_url or self._preview_url or self._image_url

    def get_gallery_title(self) -> str | None:
        """
        Получение названия галереи с fallback на имя файла.

        Returns:
            str | None: Название галереи или None, если не найдено
        """
        # Если есть gallery_title (не None и не пустая строка), используем его
        if self.gallery_title and self.gallery_title.strip():
            return self.gallery_title

        # Если нет gallery_title, пытаемся извлечь из files[0].path
        if self.gallery_files:
            file_path = self.gallery_files[0].get("path", "")
            if file_path:
                file_name = os.path.basename(file_path)
                if file_name:
                    return file_name

        # Последний fallback - используем gallery_id
        if self.gallery_id:
            return f"Галерея {self.gallery_id}"

        return None

    def __repr__(self):
        return f"StashImage(id={self.id}, title={self.title}, rating={self.rating}, gallery={self.gallery_title})"
