"""Модели данных для StashApp."""

from typing import Dict, Any


class StashImage:
    """Класс представляющий изображение из StashApp."""
    
    def __init__(self, data: Dict[str, Any]):
        """
        Инициализация объекта изображения.
        
        Args:
            data: Данные изображения из GraphQL ответа
        """
        self.id = data['id']
        self.title = data.get('title', 'Без названия')
        self.rating = data.get('rating100', 0)
        
        # Сохраняем все варианты качества для возможности выбора
        paths = data.get('paths', {})
        self._thumbnail_url = paths.get('thumbnail', '')
        self._preview_url = paths.get('preview', '')
        self._image_url = paths.get('image', '')
        
        # По умолчанию используем thumbnail для максимально быстрой загрузки
        self.image_url = self._thumbnail_url or self._preview_url or self._image_url
        
        # Теги опциональны (могут не запрашиваться для ускорения)
        self.tags = [tag['name'] for tag in data.get('tags', [])]
        
        # Информация о галерее
        galleries = data.get('galleries', [])
        self.gallery_id = galleries[0]['id'] if galleries else None
        self.gallery_title = galleries[0]['title'] if galleries else None
        
        # Информация о перформерах
        self.performers = [
            {'id': p['id'], 'name': p['name']} 
            for p in data.get('performers', [])
        ]
    
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
    
    def __repr__(self):
        return f"StashImage(id={self.id}, title={self.title}, rating={self.rating}, gallery={self.gallery_title})"
