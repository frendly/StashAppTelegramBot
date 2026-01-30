"""Утилиты для профилирования и измерения производительности."""

import time
import logging
import functools
from typing import Callable, Any
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


def timing_decorator(operation_name: str):
    """
    Декоратор для измерения времени выполнения асинхронных функций.
    
    Args:
        operation_name: Название операции для логирования
        
    Returns:
        Декорированная функция
        
    Example:
        @timing_decorator("Database query")
        async def get_data():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration = time.perf_counter() - start
                logger.info(f"⏱️  {operation_name}: {duration:.3f}s")
                return result
            except Exception as e:
                duration = time.perf_counter() - start
                logger.error(f"⏱️  {operation_name}: {duration:.3f}s (FAILED: {e})")
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration = time.perf_counter() - start
                logger.info(f"⏱️  {operation_name}: {duration:.3f}s")
                return result
            except Exception as e:
                duration = time.perf_counter() - start
                logger.error(f"⏱️  {operation_name}: {duration:.3f}s (FAILED: {e})")
                raise
        
        # Проверяем, является ли функция корутиной
        if functools.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


@asynccontextmanager
async def timing_context(operation_name: str):
    """
    Асинхронный контекстный менеджер для измерения времени выполнения блока кода.
    
    Args:
        operation_name: Название операции для логирования
        
    Example:
        async with timing_context("Processing data"):
            await process_something()
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        logger.info(f"⏱️  {operation_name}: {duration:.3f}s")


class PerformanceTimer:
    """
    Класс для детального профилирования с несколькими этапами.
    
    Example:
        timer = PerformanceTimer("Send photo operation")
        timer.start()
        
        timer.checkpoint("Database query")
        await db.get_data()
        
        timer.checkpoint("API call")
        await api.fetch()
        
        timer.end()  # Выведет все этапы и общее время
    """
    
    def __init__(self, operation_name: str):
        """
        Инициализация таймера.
        
        Args:
            operation_name: Название операции
        """
        self.operation_name = operation_name
        self.start_time: float = 0
        self.last_checkpoint: float = 0
        self.checkpoints: list[tuple[str, float]] = []
        self.total_duration: float = 0
    
    def start(self):
        """Начать измерение."""
        self.start_time = time.perf_counter()
        self.last_checkpoint = self.start_time
        self.checkpoints = []
        logger.debug(f"🚀 Starting: {self.operation_name}")
    
    def checkpoint(self, checkpoint_name: str):
        """
        Отметить контрольную точку.
        
        Args:
            checkpoint_name: Название этапа
        """
        now = time.perf_counter()
        duration = now - self.last_checkpoint
        self.checkpoints.append((checkpoint_name, duration))
        logger.debug(f"  ⏱️  {checkpoint_name}: {duration:.3f}s")
        self.last_checkpoint = now
    
    def end(self):
        """Завершить измерение и вывести итоговую информацию."""
        self.total_duration = time.perf_counter() - self.start_time
        
        logger.info(f"=" * 60)
        logger.info(f"⏱️  Performance Report: {self.operation_name}")
        logger.info(f"-" * 60)
        
        for checkpoint_name, duration in self.checkpoints:
            percentage = (duration / self.total_duration * 100) if self.total_duration > 0 else 0
            logger.info(f"  {checkpoint_name:.<40} {duration:>6.3f}s ({percentage:>5.1f}%)")
        
        logger.info(f"-" * 60)
        logger.info(f"  {'TOTAL':.<40} {self.total_duration:>6.3f}s (100.0%)")
        logger.info(f"=" * 60)
    
    def get_report(self) -> dict[str, Any]:
        """
        Получить отчет в виде словаря.
        
        Returns:
            Dict с информацией о производительности
        """
        return {
            'operation': self.operation_name,
            'total_duration': self.total_duration,
            'checkpoints': [
                {
                    'name': name,
                    'duration': duration,
                    'percentage': (duration / self.total_duration * 100) if self.total_duration > 0 else 0
                }
                for name, duration in self.checkpoints
            ]
        }
