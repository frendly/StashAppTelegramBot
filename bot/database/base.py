"""Базовый класс для работы с базой данных SQLite."""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseBase:
    """Базовый класс для работы с SQLite базой данных."""
    
    def __init__(self, db_path: str):
        """
        Инициализация подключения к базе данных.
        
        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path
        self._ensure_db_directory()
        self._init_database()
    
    def _ensure_db_directory(self):
        """Создание директории для базы данных, если она не существует."""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
    
    def _init_database(self):
        """Инициализация структуры базы данных."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица отправленных фото
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sent_photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_id TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id INTEGER,
                    title TEXT
                )
            """)
            
            # Создание индекса для быстрого поиска
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_image_id 
                ON sent_photos(image_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sent_at 
                ON sent_photos(sent_at)
            """)
            
            # Таблица голосований
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_id TEXT NOT NULL,
                    vote INTEGER NOT NULL,
                    gallery_id TEXT,
                    gallery_title TEXT,
                    performer_ids TEXT,
                    performer_names TEXT,
                    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(image_id)
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_votes_image_id 
                ON votes(image_id)
            """)
            
            # Таблица предпочтений по перформерам
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS performer_preferences (
                    performer_id TEXT PRIMARY KEY,
                    performer_name TEXT NOT NULL,
                    total_votes INTEGER DEFAULT 0,
                    positive_votes INTEGER DEFAULT 0,
                    negative_votes INTEGER DEFAULT 0,
                    score REAL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблица предпочтений по галереям
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gallery_preferences (
                    gallery_id TEXT PRIMARY KEY,
                    gallery_title TEXT NOT NULL,
                    total_votes INTEGER DEFAULT 0,
                    positive_votes INTEGER DEFAULT 0,
                    negative_votes INTEGER DEFAULT 0,
                    score REAL DEFAULT 0,
                    rating_set BOOLEAN DEFAULT FALSE,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    weight REAL DEFAULT 1.0,
                    excluded BOOLEAN DEFAULT FALSE,
                    excluded_at TIMESTAMP,
                    threshold_notification_shown BOOLEAN DEFAULT FALSE
                )
            """)
            
            # Миграция: добавление новых полей для существующих таблиц
            # SQLite не поддерживает IF NOT EXISTS для ALTER TABLE, поэтому проверяем через PRAGMA
            cursor.execute("PRAGMA table_info(gallery_preferences)")
            existing_columns = [row[1] for row in cursor.fetchall()]
            
            if 'weight' not in existing_columns:
                cursor.execute("ALTER TABLE gallery_preferences ADD COLUMN weight REAL DEFAULT 1.0")
                logger.info("Добавлено поле weight в gallery_preferences")
            
            if 'excluded' not in existing_columns:
                cursor.execute("ALTER TABLE gallery_preferences ADD COLUMN excluded BOOLEAN DEFAULT FALSE")
                logger.info("Добавлено поле excluded в gallery_preferences")
            
            if 'excluded_at' not in existing_columns:
                cursor.execute("ALTER TABLE gallery_preferences ADD COLUMN excluded_at TIMESTAMP")
                logger.info("Добавлено поле excluded_at в gallery_preferences")
            
            if 'threshold_notification_shown' not in existing_columns:
                cursor.execute("ALTER TABLE gallery_preferences ADD COLUMN threshold_notification_shown BOOLEAN DEFAULT FALSE")
                logger.info("Добавлено поле threshold_notification_shown в gallery_preferences")
            
            # Миграция существующих записей: установить weight = 1.0 для записей без веса
            cursor.execute("UPDATE gallery_preferences SET weight = 1.0 WHERE weight IS NULL")
            
            # Создание индекса на weight
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_gallery_weight 
                ON gallery_preferences(weight)
            """)
            
            conn.commit()
            logger.info(f"База данных инициализирована: {self.db_path}")
