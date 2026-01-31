"""Планировщик для автоматической отправки фото по расписанию."""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone as pytz_timezone

from bot.config import BotConfig
from bot.telegram_handler import TelegramHandler

logger = logging.getLogger(__name__)


class Scheduler:
    """Класс для управления планировщиком автоматической отправки."""
    
    def __init__(
        self, 
        config: BotConfig, 
        telegram_handler: TelegramHandler,
        database=None,
        stash_client=None
    ):
        """
        Инициализация планировщика.
        
        Args:
            config: Конфигурация бота
            telegram_handler: Обработчик Telegram команд
            database: База данных (опционально, для фоновых задач)
            stash_client: Клиент StashApp (опционально, для фоновых задач)
        """
        self.config = config
        self.telegram_handler = telegram_handler
        self.database = database
        self.stash_client = stash_client
        self.scheduler = AsyncIOScheduler()
    
    def setup(self):
        """Настройка планировщика согласно конфигурации."""
        if not self.config.scheduler.enabled:
            logger.info("Планировщик отключен в конфигурации")
            return
        
        try:
            # Парсинг cron выражения
            cron_parts = self.config.scheduler.cron.split()
            
            if len(cron_parts) != 5:
                logger.error(f"Неверный формат cron выражения: {self.config.scheduler.cron}")
                return
            
            minute, hour, day, month, day_of_week = cron_parts
            
            # Настройка временной зоны
            tz = pytz_timezone(self.config.scheduler.timezone)
            
            # Создание триггера
            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone=tz
            )
            
            # Добавление задачи для каждого разрешенного пользователя
            for user_id in self.config.telegram.allowed_user_ids:
                self.scheduler.add_job(
                    self._send_to_user,
                    trigger=trigger,
                    args=[user_id],
                    id=f"send_photo_{user_id}",
                    name=f"Отправка фото пользователю {user_id}",
                    replace_existing=True
                )
                logger.info(
                    f"Задача добавлена: отправка фото пользователю {user_id} "
                    f"по расписанию {self.config.scheduler.cron}"
                )
            
            # Добавление задачи обновления статистики галерей (раз в день в 3:00)
            if self.database and self.stash_client:
                stats_trigger = CronTrigger(
                    minute=0,
                    hour=3,
                    day='*',
                    month='*',
                    day_of_week='*',
                    timezone=tz
                )
                self.scheduler.add_job(
                    self._update_gallery_statistics,
                    trigger=stats_trigger,
                    id="update_gallery_statistics",
                    name="Обновление статистики галерей",
                    replace_existing=True
                )
                logger.info("Задача добавлена: обновление статистики галерей (ежедневно в 3:00)")
            
            # Добавление задачи предзагрузки изображений в служебный канал (каждую минуту)
            if self.config.telegram.cache_channel_id and self.telegram_handler and self.database and self.stash_client:
                preload_trigger = CronTrigger(
                    minute='*',
                    hour='*',
                    day='*',
                    month='*',
                    day_of_week='*',
                    timezone=tz
                )
                self.scheduler.add_job(
                    self._preload_images_to_cache,
                    trigger=preload_trigger,
                    id="preload_images_to_cache",
                    name="Предзагрузка изображений в служебный канал",
                    replace_existing=True
                )
                logger.info(f"Задача добавлена: предзагрузка изображений в служебный канал (каждую минуту)")
            elif self.config.telegram.cache_channel_id:
                logger.warning("Предзагрузка изображений отключена: не инициализированы telegram_handler, database или stash_client")
            
            logger.info(
                f"Планировщик настроен: cron='{self.config.scheduler.cron}', "
                f"timezone='{self.config.scheduler.timezone}'"
            )
        
        except Exception as e:
            logger.error(f"Ошибка при настройке планировщика: {e}")
    
    async def _send_to_user(self, user_id: int):
        """
        Отправка фото пользователю.
        
        Args:
            user_id: Telegram ID пользователя
        """
        try:
            logger.info(f"Выполнение запланированной отправки для user_id={user_id}")
            await self.telegram_handler.send_scheduled_photo(chat_id=user_id, user_id=user_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке запланированного фото: {e}")
    
    async def _update_gallery_statistics(self):
        """
        Фоновая задача обновления статистики галерей.
        
        Обновляет количество изображений для всех галерей, которым нужно обновление.
        """
        if not self.database or not self.stash_client:
            logger.warning("Не удалось обновить статистику: database или stash_client не инициализированы")
            return
        
        try:
            logger.info("Начало обновления статистики галерей...")
            galleries = self.database.get_galleries_needing_update(days_threshold=7)
            
            if not galleries:
                logger.info("Нет галерей, требующих обновления статистики")
                return
            
            logger.info(f"Найдено галерей для обновления: {len(galleries)}")
            
            updated_count = 0
            error_count = 0
            
            for gallery in galleries:
                gallery_id = gallery['gallery_id']
                gallery_title = gallery['gallery_title']
                
                try:
                    image_count = await self.stash_client.get_gallery_image_count(gallery_id)
                    
                    if image_count is not None:
                        success = self.database.update_gallery_image_count(gallery_id, image_count)
                        if success:
                            updated_count += 1
                            logger.debug(f"Обновлена статистика галереи '{gallery_title}': {image_count} изображений")
                        else:
                            error_count += 1
                            logger.warning(f"Не удалось обновить статистику галереи '{gallery_title}'")
                    else:
                        error_count += 1
                        logger.warning(f"Не удалось получить количество изображений для галереи '{gallery_title}'")
                
                except Exception as e:
                    error_count += 1
                    logger.error(f"Ошибка при обновлении статистики галереи '{gallery_title}': {e}")
            
            logger.info(
                f"Обновление статистики завершено: обновлено {updated_count}, "
                f"ошибок {error_count} из {len(galleries)} галерей"
            )
        
        except Exception as e:
            logger.error(f"Критическая ошибка при обновлении статистики галерей: {e}", exc_info=True)
    
    async def _preload_images_to_cache(self):
        """
        Фоновая задача предзагрузки изображений в служебный канал.
        
        Предзагружает 2 изображения high quality в служебный канал для получения file_id_high_quality.
        Это ускоряет отправку изображений пользователям.
        """
        if not self.database or not self.stash_client or not self.telegram_handler:
            logger.warning("Не удалось предзагрузить изображения: database, stash_client или telegram_handler не инициализированы")
            return
        
        if not self.config.telegram.cache_channel_id:
            logger.debug("Предзагрузка отключена: cache_channel_id не указан")
            return
        
        try:
            logger.debug("Начало предзагрузки изображений в служебный канал...")
            
            # Получение списка недавно отправленных ID
            recent_ids = self.database.get_recent_image_ids(
                self.config.history.avoid_recent_days
            )
            
            # Получение 2 случайных изображений с учетом предпочтений
            images_to_preload = []
            for _ in range(2):
                try:
                    # Используем метод из telegram_handler для получения случайного изображения
                    # Это обеспечивает единую логику выбора с учетом весов галерей и фильтров
                    exclude_ids = recent_ids + [img.id for img in images_to_preload]
                    image = await self.telegram_handler._get_random_image(exclude_ids)
                    if image:
                        images_to_preload.append(image)
                except Exception as e:
                    logger.warning(f"Ошибка при получении изображения для предзагрузки: {e}")
                    continue
            
            if not images_to_preload:
                logger.warning("Не удалось получить изображения для предзагрузки")
                return
            
            logger.info(f"Получено {len(images_to_preload)} изображений для предзагрузки")
            
            # Предзагрузка каждого изображения
            success_count = 0
            error_count = 0
            
            for image in images_to_preload:
                try:
                    # Используем метод telegram_handler для предзагрузки
                    await self.telegram_handler._preload_image_to_cache(image, use_high_quality=True)
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    logger.warning(f"Ошибка при предзагрузке изображения {image.id}: {e}")
            
            logger.info(
                f"Предзагрузка завершена: успешно {success_count}, ошибок {error_count} "
                f"из {len(images_to_preload)} изображений"
            )
        
        except Exception as e:
            logger.error(f"Критическая ошибка при предзагрузке изображений: {e}", exc_info=True)
    
    def start(self):
        """Запуск планировщика."""
        if not self.config.scheduler.enabled:
            logger.info("Планировщик не запущен (отключен в конфигурации)")
            return
        
        try:
            self.scheduler.start()
            logger.info("Планировщик запущен")
            
            # Вывод информации о запланированных задачах
            jobs = self.scheduler.get_jobs()
            logger.info(f"Активных задач: {len(jobs)}")
            for job in jobs:
                logger.info(f"  - {job.name}: следующий запуск {job.next_run_time}")
        
        except Exception as e:
            logger.error(f"Ошибка при запуске планировщика: {e}")
    
    def stop(self):
        """Остановка планировщика."""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
                logger.info("Планировщик остановлен")
        except Exception as e:
            logger.error(f"Ошибка при остановке планировщика: {e}")
    
    def get_status(self) -> dict:
        """
        Получение статуса планировщика.
        
        Returns:
            dict: Статус планировщика
        """
        return {
            "enabled": self.config.scheduler.enabled,
            "running": self.scheduler.running if self.config.scheduler.enabled else False,
            "cron": self.config.scheduler.cron,
            "timezone": self.config.scheduler.timezone,
            "jobs_count": len(self.scheduler.get_jobs()) if self.config.scheduler.enabled else 0
        }
