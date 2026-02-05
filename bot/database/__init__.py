"""Модуль для работы с базой данных SQLite."""

from typing import Any

from .base import DatabaseBase
from .preferences import PreferencesRepository
from .sent_photos import SentPhotosRepository
from .statistics import StatisticsRepository
from .votes import VotesRepository
from .weights import WeightsRepository


class Database(DatabaseBase):
    """Класс-фасад для работы с SQLite базой данных и репозиториями."""

    def __init__(self, db_path: str):
        """
        Инициализация подключения к базе данных и репозиториев.

        Args:
            db_path: Путь к файлу базы данных
        """
        super().__init__(db_path)

        # Явная инициализация репозиториев с типами
        self.sent_photos_repo: SentPhotosRepository = SentPhotosRepository(self.db_path)
        self.votes_repo: VotesRepository = VotesRepository(self.db_path)
        self.preferences_repo: PreferencesRepository = PreferencesRepository(
            self.db_path
        )
        self.weights_repo: WeightsRepository = WeightsRepository(self.db_path)
        self.statistics_repo: StatisticsRepository = StatisticsRepository(self.db_path)

    # --- Методы-обёртки для sent_photos_repo ---

    def add_sent_photo(
        self,
        image_id: str,
        user_id: int | None = None,
        title: str | None = None,
        file_id: str | None = None,
        file_id_high_quality: str | None = None,
    ) -> None:
        """См. документацию `SentPhotosRepository.add_sent_photo`."""
        self.sent_photos_repo.add_sent_photo(
            image_id=image_id,
            user_id=user_id,
            title=title,
            file_id=file_id,
            file_id_high_quality=file_id_high_quality,
        )

    def get_recent_image_ids(self, days: int) -> list[str]:
        """См. документацию `SentPhotosRepository.get_recent_image_ids`."""
        return self.sent_photos_repo.get_recent_image_ids(days)

    def is_recently_sent(self, image_id: str, days: int) -> bool:
        """См. документацию `SentPhotosRepository.is_recently_sent`."""
        return self.sent_photos_repo.is_recently_sent(image_id, days)

    def get_total_sent_count(self) -> int:
        """См. документацию `SentPhotosRepository.get_total_sent_count`."""
        return self.sent_photos_repo.get_total_sent_count()

    def get_user_sent_count(self, user_id: int) -> int:
        """См. документацию `SentPhotosRepository.get_user_sent_count`."""
        return self.sent_photos_repo.get_user_sent_count(user_id)

    def cleanup_old_records(self, days: int) -> None:
        """См. документацию `SentPhotosRepository.cleanup_old_records`."""
        self.sent_photos_repo.cleanup_old_records(days)

    def get_last_sent_photo(self) -> tuple | None:
        """См. документацию `SentPhotosRepository.get_last_sent_photo`."""
        return self.sent_photos_repo.get_last_sent_photo()

    def get_last_sent_photo_for_user(self, user_id: int) -> tuple | None:
        """См. документацию `SentPhotosRepository.get_last_sent_photo_for_user`."""
        return self.sent_photos_repo.get_last_sent_photo_for_user(user_id)

    def get_file_id(self, image_id: str, use_high_quality: bool = False) -> str | None:
        """См. документацию `SentPhotosRepository.get_file_id`."""
        return self.sent_photos_repo.get_file_id(
            image_id=image_id,
            use_high_quality=use_high_quality,
        )

    def save_file_id(
        self,
        image_id: str,
        file_id: str,
        use_high_quality: bool = False,
    ) -> None:
        """См. документацию `SentPhotosRepository.save_file_id`."""
        self.sent_photos_repo.save_file_id(
            image_id=image_id,
            file_id=file_id,
            use_high_quality=use_high_quality,
        )

    def get_random_cached_image_id(
        self, exclude_ids: list[str] | None = None
    ) -> str | None:
        """См. документацию `SentPhotosRepository.get_random_cached_image_id`."""
        return self.sent_photos_repo.get_random_cached_image_id(exclude_ids)

    # --- Методы-обёртки для votes_repo ---

    def add_vote(
        self,
        image_id: str,
        vote: int,
        gallery_id: str | None = None,
        gallery_title: str | None = None,
        performer_ids: list[str] | None = None,
        performer_names: list[str] | None = None,
    ) -> None:
        """См. документацию `VotesRepository.add_vote`."""
        self.votes_repo.add_vote(
            image_id=image_id,
            vote=vote,
            gallery_id=gallery_id,
            gallery_title=gallery_title,
            performer_ids=performer_ids,
            performer_names=performer_names,
        )

    def get_vote(self, image_id: str) -> dict[str, Any] | None:
        """См. документацию `VotesRepository.get_vote`."""
        return self.votes_repo.get_vote(image_id)

    def get_image_vote_status(self, image_id: str) -> int | None:
        """См. документацию `VotesRepository.get_image_vote_status`."""
        return self.votes_repo.get_image_vote_status(image_id)

    def get_total_votes_count(self) -> dict[str, int]:
        """См. документацию `VotesRepository.get_total_votes_count`."""
        return self.votes_repo.get_total_votes_count()

    # --- Методы-обёртки для preferences_repo ---

    def update_performer_preference(
        self, performer_id: str, performer_name: str, vote: int
    ) -> None:
        """См. документацию `PreferencesRepository.update_performer_preference`."""
        self.preferences_repo.update_performer_preference(
            performer_id=performer_id,
            performer_name=performer_name,
            vote=vote,
        )

    def get_performer_preferences(self) -> list[dict[str, Any]]:
        """См. документацию `PreferencesRepository.get_performer_preferences`."""
        return self.preferences_repo.get_performer_preferences()

    def get_blacklisted_performers(self) -> list[str]:
        """См. документацию `PreferencesRepository.get_blacklisted_performers`."""
        return self.preferences_repo.get_blacklisted_performers()

    def get_whitelisted_performers(self) -> list[str]:
        """См. документацию `PreferencesRepository.get_whitelisted_performers`."""
        return self.preferences_repo.get_whitelisted_performers()

    def update_gallery_preference(
        self, gallery_id: str, gallery_title: str, vote: int
    ) -> bool:
        """См. документацию `PreferencesRepository.update_gallery_preference`."""
        return self.preferences_repo.update_gallery_preference(
            gallery_id=gallery_id,
            gallery_title=gallery_title,
            vote=vote,
        )

    def mark_gallery_rating_set(self, gallery_id: str) -> None:
        """См. документацию `PreferencesRepository.mark_gallery_rating_set`."""
        self.preferences_repo.mark_gallery_rating_set(gallery_id)

    def get_gallery_preferences(self) -> list[dict[str, Any]]:
        """См. документацию `PreferencesRepository.get_gallery_preferences`."""
        return self.preferences_repo.get_gallery_preferences()

    def get_gallery_preference(self, gallery_id: str) -> dict[str, Any] | None:
        """См. документацию `PreferencesRepository.get_gallery_preference`."""
        return self.preferences_repo.get_gallery_preference(gallery_id)

    def get_blacklisted_galleries(self) -> list[str]:
        """См. документацию `PreferencesRepository.get_blacklisted_galleries`."""
        return self.preferences_repo.get_blacklisted_galleries()

    def get_whitelisted_galleries(self) -> list[str]:
        """См. документацию `PreferencesRepository.get_whitelisted_galleries`."""
        return self.preferences_repo.get_whitelisted_galleries()

    def is_threshold_notification_shown(self, gallery_id: str) -> bool:
        """См. документацию `PreferencesRepository.is_threshold_notification_shown`."""
        return self.preferences_repo.is_threshold_notification_shown(gallery_id)

    def mark_threshold_notification_shown(self, gallery_id: str) -> None:
        """См. документацию `PreferencesRepository.mark_threshold_notification_shown`."""
        self.preferences_repo.mark_threshold_notification_shown(gallery_id)

    def ensure_gallery_exists(self, gallery_id: str, gallery_title: str) -> bool:
        """См. документацию `PreferencesRepository.ensure_gallery_exists`."""
        return self.preferences_repo.ensure_gallery_exists(
            gallery_id=gallery_id,
            gallery_title=gallery_title,
        )

    def exclude_gallery(self, gallery_id: str) -> bool:
        """См. документацию `PreferencesRepository.exclude_gallery`."""
        return self.preferences_repo.exclude_gallery(gallery_id)

    # --- Методы-обёртки для weights_repo ---

    def get_gallery_weight(self, gallery_id: str) -> float:
        """См. документацию `WeightsRepository.get_gallery_weight`."""
        return self.weights_repo.get_gallery_weight(gallery_id)

    def update_gallery_weight(self, gallery_id: str, vote: int) -> float:
        """См. документацию `WeightsRepository.update_gallery_weight`."""
        return self.weights_repo.update_gallery_weight(gallery_id, vote)

    def get_all_gallery_weights(self) -> list[dict[str, Any]]:
        """См. документацию `WeightsRepository.get_all_gallery_weights`."""
        return self.weights_repo.get_all_gallery_weights()

    def get_active_gallery_weights(self) -> dict[str, float]:
        """См. документацию `WeightsRepository.get_active_gallery_weights`."""
        return self.weights_repo.get_active_gallery_weights()

    def get_gallery_stats_with_viewed_counts(self) -> dict[str, dict[str, Any]]:
        """См. документацию `WeightsRepository.get_gallery_stats_with_viewed_counts`."""
        return self.weights_repo.get_gallery_stats_with_viewed_counts()

    def update_gallery_last_selected(self, gallery_id: str) -> None:
        """См. документацию `WeightsRepository.update_gallery_last_selected`."""
        self.weights_repo.update_gallery_last_selected(gallery_id)

    # --- Методы-обёртки для statistics_repo ---

    def update_gallery_image_count(self, gallery_id: str, total_images: int) -> bool:
        """См. документацию `StatisticsRepository.update_gallery_image_count`."""
        return self.statistics_repo.update_gallery_image_count(
            gallery_id=gallery_id,
            total_images=total_images,
        )

    def get_gallery_statistics(self, gallery_id: str) -> dict[str, Any] | None:
        """См. документацию `StatisticsRepository.get_gallery_statistics`."""
        return self.statistics_repo.get_gallery_statistics(gallery_id)

    def calculate_negative_percentage(self, gallery_id: str) -> float:
        """См. документацию `StatisticsRepository.calculate_negative_percentage`."""
        return self.statistics_repo.calculate_negative_percentage(gallery_id)

    def get_galleries_needing_update(
        self, days_threshold: int = 7
    ) -> list[dict[str, Any]]:
        """См. документацию `StatisticsRepository.get_galleries_needing_update`."""
        return self.statistics_repo.get_galleries_needing_update(days_threshold)

    def get_gallery_image_count(self, gallery_id: str) -> int | None:
        """См. документацию `StatisticsRepository.get_gallery_image_count`."""
        return self.statistics_repo.get_gallery_image_count(gallery_id)

    def should_update_image_count(
        self, gallery_id: str, days_threshold: int = 7
    ) -> bool:
        """См. документацию `StatisticsRepository.should_update_image_count`."""
        return self.statistics_repo.should_update_image_count(
            gallery_id,
            days_threshold=days_threshold,
        )


# Экспорт для обратной совместимости
__all__ = ["Database"]
