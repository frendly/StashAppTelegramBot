"""Форматирование подписей к изображениям."""

import logging
from typing import Optional, Dict, Any, Tuple

from bot.stash_client import StashImage
from bot.database import Database

logger = logging.getLogger(__name__)


class CaptionFormatter:
    """Класс для форматирования подписей к изображениям."""
    
    def __init__(self, database: Database):
        """
        Инициализация форматтера.
        
        Args:
            database: База данных для получения статистики
        """
        self.database = database
    
    def calculate_display_rating(self, positive_votes: int, negative_votes: int) -> Tuple[str, float]:
        """
        Расчет рейтинга для отображения в формате "⭐⭐⭐☆☆ (3.2/5.0)".
        
        Формула: (positive_votes * 5 + negative_votes * 1) / total_votes
        
        Args:
            positive_votes: Количество положительных голосов
            negative_votes: Количество отрицательных голосов
            
        Returns:
            tuple[str, float]: (stars_string, rating_value)
            - stars_string: Строка со звездами, например "⭐⭐⭐☆☆"
            - rating_value: Числовое значение рейтинга от 1.0 до 5.0
        """
        total_votes = positive_votes + negative_votes
        
        if total_votes == 0:
            # Если нет голосов, возвращаем нейтральный рейтинг
            return ("☆☆☆☆☆", 0.0)
        
        # Расчет рейтинга: (positive_votes * 5 + negative_votes * 1) / total_votes
        rating_value = (positive_votes * 5.0 + negative_votes * 1.0) / total_votes
        rating_value = max(1.0, min(5.0, rating_value))  # Ограничиваем диапазон 1.0-5.0
        
        # Конвертация в звезды (округление до ближайшего целого)
        stars_count = round(rating_value)
        stars_count = max(1, min(5, stars_count))  # Ограничиваем диапазон 1-5
        
        # Формирование строки со звездами
        stars_string = "⭐" * stars_count + "☆" * (5 - stars_count)
        
        return (stars_string, round(rating_value, 1))
    
    def format_progress_bar(self, negative_votes: int, total_images: int, negative_percentage: Optional[float] = None) -> str:
        """
        Форматирование прогресс-бара для отображения процента минусов.
        
        Args:
            negative_votes: Количество отрицательных голосов
            total_images: Общее количество изображений в галерее
            negative_percentage: Процент минусов (опционально, если не указан - вычисляется)
            
        Returns:
            str: Отформатированный прогресс-бар или пустая строка если total_images == 0
        """
        if total_images == 0:
            return ""
        
        # Защита от некорректных данных (negative_votes не может быть больше total_images)
        negative_votes = max(0, min(negative_votes, total_images))
        
        # Расчет процента минусов (используем переданный или вычисляем)
        if negative_percentage is None:
            negative_percentage = (negative_votes / total_images) * 100.0
        else:
            # Ограничиваем процент 0-100 для безопасности
            negative_percentage = max(0.0, min(100.0, negative_percentage))
        
        # Расчет заполненности прогресс-бара (10 символов, каждый = 10%)
        filled = int((negative_votes / total_images) * 10)
        filled = max(0, min(10, filled))  # Ограничение 0-10
        
        # Формирование прогресс-бара
        filled_chars = "█" * filled
        empty_chars = "░" * (10 - filled)
        progress_bar = f"[{filled_chars}{empty_chars}]"
        
        # Цветовая индикация
        color_emoji = "🔴" if negative_percentage >= 33.0 else "🟢"
        
        # Форматирование: [██████░░░░] 60% (12/20)
        return f"{color_emoji} {progress_bar} {negative_percentage:.0f}% ({negative_votes}/{total_images})"
    
    def format_caption(self, image: StashImage, is_preloaded_from_cache: bool = False) -> str:
        """
        Форматирование подписи к изображению согласно MVP.
        
        Формат обычного сообщения:
        👤 Перформер: Имя1, Имя2
        📊 Галерея: "Название_галереи"
        Вес: 2.4 | ⭐⭐⭐☆☆ (3.2/5.0)
        Прогресс: [██████░░░░] 60% (12/20)
        ⚡ Предзагружено (если предзагружено)
        
        Args:
            image: Объект изображения
            is_preloaded_from_cache: Флаг предзагрузки из служебного канала
            
        Returns:
            str: Отформатированная подпись
        """
        # Формируем информацию о перформере
        performer_names = [p['name'] for p in image.performers] if image.performers else []
        performer_text = ", ".join(performer_names) if performer_names else "не указан"
        
        # Если нет галереи, используем упрощенный формат
        if not image.gallery_id or not image.gallery_title:
            caption_parts = []
            caption_parts.append(f"👤 Перформер: {performer_text}")
            caption_parts.append(f"📊 Галерея: не указан")
            if image.title and image.title != 'Без названия':
                caption_parts.append(f"<b>{image.title}</b>")
            if is_preloaded_from_cache:
                caption_parts.append("⚡ Предзагружено")
            return "\n".join(caption_parts) if caption_parts else "📸 Случайное фото"
        
        try:
            # Получаем статистику галереи
            gallery_stats = self.database.get_gallery_statistics(image.gallery_id)
            
            # Если статистики нет, используем упрощенный формат
            if not gallery_stats or gallery_stats.get('total_images', 0) == 0:
                caption_parts = []
                caption_parts.append(f"👤 Перформер: {performer_text}")
                caption_parts.append(f"📊 Галерея: \"{image.gallery_title}\"")
                if image.title and image.title != 'Без названия':
                    caption_parts.append(f"<b>{image.title}</b>")
                if is_preloaded_from_cache:
                    caption_parts.append("⚡ Предзагружено")
                return "\n".join(caption_parts) if caption_parts else "📸 Случайное фото"
            
            # Формируем новый формат согласно MVP
            caption_parts = []
            
            # Перформер
            caption_parts.append(f"👤 Перформер: {performer_text}")
            
            # Галерея
            caption_parts.append(f"📊 Галерея: \"{image.gallery_title}\"")
            
            # Вес и рейтинг
            try:
                weight = self.database.get_gallery_weight(image.gallery_id)
                positive_votes = gallery_stats.get('positive_votes', 0)
                negative_votes = gallery_stats.get('negative_votes', 0)
                stars_string, rating_value = self.calculate_display_rating(positive_votes, negative_votes)
                
                # Показываем вес и рейтинг только если есть хотя бы один голос
                if positive_votes + negative_votes > 0:
                    caption_parts.append(f"Вес: {weight:.1f} | {stars_string} ({rating_value}/5.0)")
                else:
                    # Если нет голосов, показываем только вес
                    caption_parts.append(f"Вес: {weight:.1f}")
            except Exception as e:
                logger.warning(f"Ошибка при получении веса/рейтинга для галереи {image.gallery_id}: {e}")
                # Если не удалось получить вес/рейтинг, пропускаем эту строку
            
            # Прогресс-бар
            progress_bar = self.format_progress_bar(
                negative_votes=gallery_stats.get('negative_votes', 0),
                total_images=gallery_stats.get('total_images', 0),
                negative_percentage=gallery_stats.get('negative_percentage')
            )
            if progress_bar:
                caption_parts.append(f"Прогресс: {progress_bar}")
            
            # Пометка о предзагрузке
            if is_preloaded_from_cache:
                caption_parts.append("⚡ Предзагружено")
            
            return "\n".join(caption_parts) if caption_parts else "📸 Случайное фото"
            
        except Exception as e:
            logger.warning(f"Ошибка при форматировании подписи для галереи {image.gallery_id}: {e}")
            # Fallback на упрощенный формат
            caption_parts = []
            caption_parts.append(f"👤 Перформер: {performer_text}")
            if image.gallery_title:
                caption_parts.append(f"📊 Галерея: \"{image.gallery_title}\"")
            else:
                caption_parts.append(f"📊 Галерея: не указан")
            if image.title and image.title != 'Без названия':
                caption_parts.append(f"<b>{image.title}</b>")
            if is_preloaded_from_cache:
                caption_parts.append("⚡ Предзагружено")
            return "\n".join(caption_parts) if caption_parts else "📸 Случайное фото"
    
    def format_threshold_caption(self, image: StashImage, gallery_stats: Dict[str, Any], is_preloaded_from_cache: bool = False) -> str:
        """
        Форматирование подписи при достижении порога 33.3%.
        
        Формат согласно MVP:
        👤 Перформер: Имя1, Имя2
        Галерея: "Название_галереи"
        Прогресс: [██████░░░░] 60% (12/20)
        
        • Всего изображений: 20
        • Получили "+": 5
        • Получили "-": 12 (60%)
        • Без оценки: 3
        ⚡ Предзагружено (если предзагружено)
        
        Args:
            image: Объект изображения
            gallery_stats: Статистика галереи
            is_preloaded_from_cache: Флаг предзагрузки из служебного канала
            
        Returns:
            str: Отформатированная подпись
        """
        caption_parts = []
        
        # Формируем информацию о перформере
        performer_names = [p['name'] for p in image.performers] if image.performers else []
        performer_text = ", ".join(performer_names) if performer_names else "не указан"
        
        # Перформер
        caption_parts.append(f"👤 Перформер: {performer_text}")
        
        # Галерея
        if image.gallery_title:
            caption_parts.append(f"📊 Галерея: \"{image.gallery_title}\"")
        else:
            caption_parts.append(f"📊 Галерея: не указан")
        
        # Прогресс-бар
        total_images = gallery_stats.get('total_images', 0)
        negative_votes = gallery_stats.get('negative_votes', 0)
        negative_percentage = gallery_stats.get('negative_percentage', 0.0)
        
        if total_images > 0:
            progress_bar = self.format_progress_bar(
                negative_votes=negative_votes,
                total_images=total_images,
                negative_percentage=negative_percentage
            )
            if progress_bar:
                caption_parts.append(f"Прогресс: {progress_bar}")
        
        # Пустая строка перед детальной статистикой
        caption_parts.append("")
        
        # Детальная статистика
        positive_votes = gallery_stats.get('positive_votes', 0)
        unrated_count = max(0, total_images - positive_votes - negative_votes)
        
        # Защита от некорректных данных
        if total_images == 0:
            caption_parts.append("• Всего изображений: 0")
            return "\n".join(caption_parts)
        
        caption_parts.append(f"• Всего изображений: {total_images}")
        caption_parts.append(f"• Получили \"+\": {positive_votes}")
        caption_parts.append(f"• Получили \"-\": {negative_votes} ({negative_percentage:.0f}%)")
        caption_parts.append(f"• Без оценки: {unrated_count}")
        
        # Пометка о предзагрузке
        if is_preloaded_from_cache:
            caption_parts.append("⚡ Предзагружено")
        
        return "\n".join(caption_parts)
