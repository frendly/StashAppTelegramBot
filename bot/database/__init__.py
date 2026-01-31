"""Модуль для работы с базой данных SQLite."""

from .base import DatabaseBase
from .sent_photos import SentPhotosRepository
from .votes import VotesRepository
from .preferences import PreferencesRepository
from .weights import WeightsRepository
from .statistics import StatisticsRepository


class Database(DatabaseBase):
    """Класс для работы с SQLite базой данных."""
    
    def __init__(self, db_path: str):
        """
        Инициализация подключения к базе данных.
        
        Args:
            db_path: Путь к файлу базы данных
        """
        super().__init__(db_path)
        
        # Инициализация репозиториев
        self.sent_photos_repo = SentPhotosRepository(self.db_path)
        self.votes_repo = VotesRepository(self.db_path)
        self.preferences_repo = PreferencesRepository(self.db_path)
        self.weights_repo = WeightsRepository(self.db_path)
        self.statistics_repo = StatisticsRepository(self.db_path)
        
        # Делегирование методов для обратной совместимости
        # Sent photos methods
        self.add_sent_photo = self.sent_photos_repo.add_sent_photo
        self.get_recent_image_ids = self.sent_photos_repo.get_recent_image_ids
        self.is_recently_sent = self.sent_photos_repo.is_recently_sent
        self.get_total_sent_count = self.sent_photos_repo.get_total_sent_count
        self.get_user_sent_count = self.sent_photos_repo.get_user_sent_count
        self.cleanup_old_records = self.sent_photos_repo.cleanup_old_records
        self.get_last_sent_photo = self.sent_photos_repo.get_last_sent_photo
        self.get_last_sent_photo_for_user = self.sent_photos_repo.get_last_sent_photo_for_user
        
        # Votes methods
        self.add_vote = self.votes_repo.add_vote
        self.get_vote = self.votes_repo.get_vote
        self.get_image_vote_status = self.votes_repo.get_image_vote_status
        self.get_total_votes_count = self.votes_repo.get_total_votes_count
        
        # Preferences methods
        self.update_performer_preference = self.preferences_repo.update_performer_preference
        self.get_performer_preferences = self.preferences_repo.get_performer_preferences
        self.get_blacklisted_performers = self.preferences_repo.get_blacklisted_performers
        self.get_whitelisted_performers = self.preferences_repo.get_whitelisted_performers
        self.update_gallery_preference = self.preferences_repo.update_gallery_preference
        self.mark_gallery_rating_set = self.preferences_repo.mark_gallery_rating_set
        self.get_gallery_preferences = self.preferences_repo.get_gallery_preferences
        self.get_gallery_preference = self.preferences_repo.get_gallery_preference
        self.get_blacklisted_galleries = self.preferences_repo.get_blacklisted_galleries
        self.get_whitelisted_galleries = self.preferences_repo.get_whitelisted_galleries
        self.is_threshold_notification_shown = self.preferences_repo.is_threshold_notification_shown
        self.mark_threshold_notification_shown = self.preferences_repo.mark_threshold_notification_shown
        self.ensure_gallery_exists = self.preferences_repo.ensure_gallery_exists
        
        # Weights methods
        self.calculate_initial_weight = self.weights_repo.calculate_initial_weight
        self.get_gallery_weight = self.weights_repo.get_gallery_weight
        self.update_gallery_weight = self.weights_repo.update_gallery_weight
        self.get_all_gallery_weights = self.weights_repo.get_all_gallery_weights
        self.get_active_gallery_weights = self.weights_repo.get_active_gallery_weights
        self.get_gallery_stats_with_viewed_counts = self.weights_repo.get_gallery_stats_with_viewed_counts
        self.update_gallery_last_selected = self.weights_repo.update_gallery_last_selected
        
        # Statistics methods
        self.update_gallery_image_count = self.statistics_repo.update_gallery_image_count
        self.get_gallery_statistics = self.statistics_repo.get_gallery_statistics
        self.calculate_negative_percentage = self.statistics_repo.calculate_negative_percentage
        self.get_galleries_needing_update = self.statistics_repo.get_galleries_needing_update
        self.should_update_image_count = self.statistics_repo.should_update_image_count


# Экспорт для обратной совместимости
__all__ = ['Database']
