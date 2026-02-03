"""Планировщик для автоматической отправки фото по расписанию."""

import asyncio
import logging
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone as pytz_timezone
from telegram.error import RetryAfter, TelegramError

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
        stash_client=None,
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
                logger.error(
                    f"Неверный формат cron выражения: {self.config.scheduler.cron}"
                )
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
                timezone=tz,
            )

            # Добавление задачи для каждого разрешенного пользователя
            for user_id in self.config.telegram.allowed_user_ids:
                self.scheduler.add_job(
                    self._send_to_user,
                    trigger=trigger,
                    args=[user_id],
                    id=f"send_photo_{user_id}",
                    name=f"Отправка фото пользователю {user_id}",
                    replace_existing=True,
                )
                logger.info(
                    f"Задача добавлена: отправка фото пользователю {user_id} "
                    f"по расписанию {self.config.scheduler.cron}"
                )

            # Добавление задачи обновления статистики галерей (раз в день в 3:00)
            if self.database and self.stash_client:
                stats_trigger = CronTrigger(
                    minute=0, hour=3, day="*", month="*", day_of_week="*", timezone=tz
                )
                self.scheduler.add_job(
                    self._update_gallery_statistics,
                    trigger=stats_trigger,
                    id="update_gallery_statistics",
                    name="Обновление статистики галерей",
                    replace_existing=True,
                )
                logger.info(
                    "Задача добавлена: обновление статистики галерей (ежедневно в 3:00)"
                )

            # Добавление задачи предзагрузки изображений в служебный канал (ночью каждые 5 минут)
            if (
                self.config.telegram.cache_channel_id
                and self.telegram_handler
                and self.database
                and self.stash_client
            ):
                preload_trigger = CronTrigger(
                    minute="*/5",
                    hour="2-5",
                    day="*",
                    month="*",
                    day_of_week="*",
                    timezone=tz,
                )
                self.scheduler.add_job(
                    self._preload_images_to_cache,
                    trigger=preload_trigger,
                    id="preload_images_to_cache",
                    name="Предзагрузка изображений в служебный канал",
                    replace_existing=True,
                )
                logger.info(
                    "Задача добавлена: предзагрузка изображений в служебный канал "
                    "(ночью с 2:00 до 6:00, каждые 5 минут)"
                )
            elif self.config.telegram.cache_channel_id:
                logger.warning(
                    "Предзагрузка изображений отключена: не инициализированы telegram_handler, database или stash_client"
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
            await self.telegram_handler.send_scheduled_photo(
                chat_id=user_id, user_id=user_id
            )
        except asyncio.CancelledError:
            # Пробрасываем CancelledError дальше - это нормальная часть механизма отмены задач
            logger.debug(f"Запланированная отправка для user_id={user_id} отменена")
            raise
        except Exception as e:
            logger.error(f"Ошибка при отправке запланированного фото: {e}")

    async def _update_gallery_statistics(self):
        """
        Фоновая задача обновления статистики галерей.

        Обновляет количество изображений для всех галерей, которым нужно обновление.
        """
        if not self.database or not self.stash_client:
            logger.warning(
                "Не удалось обновить статистику: database или stash_client не инициализированы"
            )
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
                gallery_id = gallery["gallery_id"]
                gallery_title = gallery["gallery_title"]

                try:
                    image_count = await self.stash_client.get_gallery_image_count(
                        gallery_id
                    )

                    if image_count is not None:
                        success = self.database.update_gallery_image_count(
                            gallery_id, image_count
                        )
                        if success:
                            updated_count += 1
                            logger.debug(
                                f"Обновлена статистика галереи '{gallery_title}': {image_count} изображений"
                            )
                        else:
                            error_count += 1
                            logger.warning(
                                f"Не удалось обновить статистику галереи '{gallery_title}'"
                            )
                    else:
                        error_count += 1
                        logger.warning(
                            f"Не удалось получить количество изображений для галереи '{gallery_title}'"
                        )

                except Exception as e:
                    error_count += 1
                    logger.error(
                        f"Ошибка при обновлении статистики галереи '{gallery_title}': {e}"
                    )

            logger.info(
                f"Обновление статистики завершено: обновлено {updated_count}, "
                f"ошибок {error_count} из {len(galleries)} галерей"
            )

        except Exception as e:
            logger.error(
                f"Критическая ошибка при обновлении статистики галерей: {e}",
                exc_info=True,
            )

    async def _preload_images_to_cache(self):
        """
        Фоновая задача предзагрузки изображений в служебный канал.

        Стратегия 80/20:
        - 80% новых изображений (без telegram_file_id) - равномерно по галереям
        - 20% известных изображений (с telegram_file_id) - по весам популярности

        Безопасная загрузка с соблюдением rate limits Telegram API:
        - Максимум 20 сообщений/сек (консервативно)
        - Автоматическая обработка RetryAfter
        - Экспоненциальный backoff при ошибках
        - Защита от бана (проверка на блокировку)
        """
        if not self.database or not self.stash_client or not self.telegram_handler:
            logger.warning(
                "Не удалось предзагрузить изображения: database, stash_client или telegram_handler не инициализированы"
            )
            return

        if not self.config.telegram.cache_channel_id:
            logger.debug("Предзагрузка отключена: cache_channel_id не указан")
            return

        try:
            logger.info("Начало предзагрузки изображений в служебный канал...")

            # Проверка размера кеша
            cache_size = await self.stash_client.get_cache_size()
            min_cache_size = (
                self.config.cache.min_cache_size if self.config.cache else 200
            )

            # Определяем размер пакета для предзагрузки
            if cache_size < min_cache_size:
                # Критический уровень - загружаем больше
                needed = min_cache_size - cache_size
                batch_size = min(needed, 1000)  # Максимум 1000 за раз
                logger.info(
                    f"Размер кеша: {cache_size}/{min_cache_size}. "
                    f"Загружаем {batch_size} изображений для пополнения"
                )
            else:
                # Нормальный уровень - ночью загружаем большие объемы
                batch_size = 1000

            # Получение списка недавно отправленных ID
            recent_ids = self.database.get_recent_image_ids(
                self.config.history.avoid_recent_days
            )

            # 80% новых (без telegram_file_id)
            new_count = int(batch_size * 0.8)
            new_images = await self.stash_client.get_images_without_file_id(
                count=new_count, exclude_ids=recent_ids
            )

            # 20% известных (с telegram_file_id) - обновляем для надежности
            known_count = batch_size - new_count
            known_images = await self.stash_client.get_images_with_file_id(
                count=known_count, exclude_ids=recent_ids
            )

            images_to_preload = new_images + known_images

            if not images_to_preload:
                logger.warning("Не удалось получить изображения для предзагрузки")
                return

            logger.info(
                f"Получено {len(images_to_preload)} изображений для предзагрузки "
                f"(новых: {len(new_images)}, известных: {len(known_images)})"
            )

            # Предзагрузка с соблюдением rate limits
            success_count = 0
            error_count = 0
            rate_limit_errors = 0
            consecutive_errors = 0
            max_consecutive_errors = 10  # Остановка при 10 ошибках подряд

            # Базовая задержка: 0.05 сек = 20 сообщений/сек (безопасно)
            base_delay = 0.05
            current_delay = base_delay

            start_time = time.time()
            processed_count = 0  # Счетчик реально обработанных изображений

            for idx, image in enumerate(images_to_preload, 1):
                processed_count = idx  # Обновляем счетчик обработанных
                try:
                    await self.telegram_handler.preload_image_to_cache(
                        image, use_high_quality=True
                    )
                    success_count += 1
                    consecutive_errors = 0  # Сбрасываем счетчик ошибок
                    current_delay = base_delay  # Возвращаем базовую задержку

                    # Прогресс каждые 100 изображений
                    if idx % 100 == 0:
                        elapsed = time.time() - start_time
                        rate = idx / elapsed if elapsed > 0 else 0
                        remaining = len(images_to_preload) - idx
                        if rate > 0:
                            eta_seconds = remaining / rate
                            eta_str = f"{eta_seconds:.0f} сек"
                        else:
                            eta_str = "N/A"
                        logger.info(
                            f"Прогресс: {idx}/{len(images_to_preload)} "
                            f"({success_count} успешно, {error_count} ошибок). "
                            f"Скорость: {rate:.1f} img/sec, ETA: {eta_str}"
                        )

                    # Задержка между запросами
                    await asyncio.sleep(current_delay)

                except RetryAfter as e:
                    # Telegram просит подождать - это нормально, не ошибка
                    rate_limit_errors += 1
                    wait_time = e.retry_after
                    logger.warning(
                        f"Rate limit достигнут (изображение {idx}/{len(images_to_preload)}). "
                        f"Ожидание {wait_time} секунд..."
                    )
                    await asyncio.sleep(wait_time)

                    # Увеличиваем задержку после rate limit
                    current_delay = min(current_delay * 1.5, 1.0)  # Макс 1 сек

                    # Повторяем попытку
                    try:
                        await self.telegram_handler.preload_image_to_cache(
                            image, use_high_quality=True
                        )
                        success_count += 1
                        consecutive_errors = 0  # Сбрасываем счетчик ошибок
                        current_delay = base_delay  # Возвращаем базовую задержку
                    except Exception as retry_e:
                        error_count += 1
                        consecutive_errors += 1
                        logger.warning(
                            f"Ошибка при повторной попытке изображения {image.id}: {retry_e}"
                        )

                    # Задержка перед следующим изображением после обработки RetryAfter
                    await asyncio.sleep(current_delay)

                except TelegramError as e:
                    error_count += 1
                    consecutive_errors += 1
                    error_msg = str(e)

                    # Проверяем на критические ошибки
                    if "blocked" in error_msg.lower() or "banned" in error_msg.lower():
                        logger.error(
                            "КРИТИЧНО: Бот заблокирован! Останавливаем предзагрузку."
                        )
                        break

                    logger.warning(
                        f"Ошибка Telegram при предзагрузке изображения {image.id}: {e}"
                    )

                    # Экспоненциальный backoff при ошибках
                    current_delay = min(current_delay * 2, 2.0)  # Макс 2 сек
                    await asyncio.sleep(current_delay)

                    # Если слишком много ошибок подряд - останавливаемся
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error(
                            f"Слишком много ошибок подряд ({consecutive_errors}). "
                            f"Останавливаем предзагрузку для безопасности."
                        )
                        break

                except Exception as e:
                    error_count += 1
                    consecutive_errors += 1
                    logger.warning(
                        f"Ошибка при предзагрузке изображения {image.id}: {e}"
                    )
                    await asyncio.sleep(current_delay)

            elapsed_total = time.time() - start_time
            # processed_count уже содержит реально обработанное количество
            avg_rate = processed_count / elapsed_total if elapsed_total > 0 else 0

            logger.info(
                f"Предзагрузка завершена: успешно {success_count}, ошибок {error_count}, "
                f"rate limit пауз {rate_limit_errors} из {processed_count} обработанных "
                f"(всего запрошено {len(images_to_preload)}). "
                f"Время: {elapsed_total:.1f} сек ({elapsed_total / 60:.1f} мин), "
                f"средняя скорость: {avg_rate:.1f} img/sec"
            )

        except Exception as e:
            logger.error(
                f"Критическая ошибка при предзагрузке изображений: {e}", exc_info=True
            )

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
            "running": self.scheduler.running
            if self.config.scheduler.enabled
            else False,
            "cron": self.config.scheduler.cron,
            "timezone": self.config.scheduler.timezone,
            "jobs_count": len(self.scheduler.get_jobs())
            if self.config.scheduler.enabled
            else 0,
        }
