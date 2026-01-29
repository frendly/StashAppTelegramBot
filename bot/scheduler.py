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
    
    def __init__(self, config: BotConfig, telegram_handler: TelegramHandler):
        """
        Инициализация планировщика.
        
        Args:
            config: Конфигурация бота
            telegram_handler: Обработчик Telegram команд
        """
        self.config = config
        self.telegram_handler = telegram_handler
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
            await self.telegram_handler.send_scheduled_photo(chat_id=user_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке запланированного фото: {e}")
    
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
