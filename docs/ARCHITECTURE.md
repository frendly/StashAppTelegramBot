# Архитектура StashApp Telegram Bot

## Обзор системы

StashApp Telegram Bot - это асинхронное приложение, которое интегрирует StashApp с Telegram, позволяя получать случайные фотографии из коллекции по команде или автоматически по расписанию.

## Компоненты системы

```
┌─────────────────────────────────────────────────────────┐
│                    Telegram Bot                          │
│                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Commands   │  │  Scheduler   │  │   Database   │  │
│  │  /start      │  │              │  │              │  │
│  │  /random     │──┤  APScheduler │──┤   SQLite     │  │
│  │  /stats      │  │  Cron Jobs   │  │   History    │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│         │                  │                             │
│         └──────────────────┼─────────────────────────────┤
│                            ▼                             │
│                 ┌──────────────────┐                     │
│                 │  StashApp Client │                     │
│                 │   GraphQL API    │                     │
│                 └──────────────────┘                     │
└─────────────────────────┼───────────────────────────────┘
                          │
                          ▼
                  ┌──────────────┐
                  │   StashApp   │
                  │  GraphQL API │
                  └──────────────┘
```

## Модули

### 1. `main.py` - Точка входа

**Ответственность:**
- Инициализация всех компонентов
- Управление жизненным циклом приложения
- Graceful shutdown
- Настройка логирования

**Основные классы:**
- `Bot` - главный класс приложения

**Потоки выполнения:**
```
Запуск → Инициализация конфигурации → Инициализация БД →
→ Инициализация StashApp клиента → Создание Telegram Application →
→ Запуск планировщика → Polling → Ожидание завершения
```

### 2. `config.py` - Управление конфигурацией

**Ответственность:**
- Загрузка YAML конфигурации
- Валидация параметров
- Поддержка переменных окружения

**Dataclasses:**
- `TelegramConfig` - настройки Telegram
- `StashConfig` - настройки StashApp
- `SchedulerConfig` - настройки планировщика
- `HistoryConfig` - настройки истории
- `DatabaseConfig` - настройки БД
- `BotConfig` - общая конфигурация

### 3. `database.py` - Работа с базой данных

**Ответственность:**
- Хранение истории отправленных фото
- Предотвращение повторов
- Статистика

**Схема БД:**
```sql
CREATE TABLE sent_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER,
    title TEXT
);

CREATE INDEX idx_image_id ON sent_photos(image_id);
CREATE INDEX idx_sent_at ON sent_photos(sent_at);
```

**Основные методы:**
- `add_sent_photo()` - добавление записи
- `get_recent_image_ids()` - получение недавних ID
- `is_recently_sent()` - проверка повтора
- `get_total_sent_count()` - общая статистика
- `cleanup_old_records()` - очистка старых записей

### 4. `stash_client.py` - Клиент StashApp

**Ответственность:**
- Взаимодействие с StashApp GraphQL API
- Получение случайных изображений
- Скачивание изображений
- Обработка ошибок API

**Основные классы:**
- `StashImage` - модель изображения
- `StashClient` - HTTP клиент с GraphQL

**GraphQL запросы:**
```graphql
query FindRandomImage($excludeIds: [ID!]) {
  findImages(
    image_filter: { id: { modifier: NOT_EQUALS, value: $excludeIds } }
    filter: { per_page: 1, sort: "random" }
  ) {
    images {
      id, title, rating100, paths { image }, tags { name }
    }
  }
}
```

**Особенности:**
- Async context manager для управления сессией
- Retry логика для надежности
- Поддержка API ключей

### 5. `telegram_handler.py` - Обработчики команд

**Ответственность:**
- Обработка команд пользователей
- Авторизация по whitelist
- Форматирование сообщений
- Отправка фото

**Команды:**
- `/start` - приветствие и инструкции
- `/help` - справка по командам
- `/random` - отправка случайного фото
- `/stats` - статистика отправленных фото

**Поток обработки `/random`:**
```
Команда → Проверка авторизации → Получение недавних ID →
→ Запрос к StashApp → Скачивание изображения →
→ Форматирование подписи → Отправка в Telegram →
→ Сохранение в БД
```

### 6. `scheduler.py` - Планировщик

**Ответственность:**
- Автоматическая отправка по расписанию
- Управление cron задачами
- Поддержка временных зон

**Используемые библиотеки:**
- `APScheduler` - планировщик задач
- `CronTrigger` - cron выражения
- `pytz` - временные зоны

**Процесс:**
```
Инициализация → Парсинг cron → Создание триггера →
→ Добавление задач для каждого пользователя →
→ Запуск планировщика → Выполнение по расписанию
```

## Потоки данных

### Отправка случайного фото

```
┌──────────────┐
│   User       │
│ /random      │
└──────┬───────┘
       │
       ▼
┌──────────────────┐
│ telegram_handler │
│ - Авторизация    │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│   Database       │
│ - Recent IDs     │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ stash_client     │
│ - Random query   │
│ - Download       │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ StashApp API     │
│ - Image data     │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ telegram_handler │
│ - Format caption │
│ - Send photo     │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│   Database       │
│ - Save record    │
└──────────────────┘
```

### Автоматическая отправка по расписанию

```
┌──────────────────┐
│   Scheduler      │
│ - Cron trigger   │
└──────┬───────────┘
       │ (по расписанию)
       ▼
┌──────────────────┐
│ telegram_handler │
│ send_scheduled   │
└──────┬───────────┘
       │
       ▼
   (тот же поток что и /random)
```

## Асинхронная архитектура

### AsyncIO Event Loop

```python
asyncio.run(main())
  ├── Bot.initialize()
  │   ├── load_config()
  │   ├── Database.__init__()
  │   ├── StashClient.__aenter__()
  │   └── Application.builder().build()
  │
  ├── Bot.start()
  │   ├── Scheduler.start()
  │   ├── Application.start()
  │   └── Updater.start_polling()
  │
  └── Bot.stop()
      ├── Scheduler.stop()
      ├── Application.shutdown()
      └── StashClient.__aexit__()
```

### Конкурентность

- **Telegram polling** - отдельный async task
- **APScheduler** - интегрирован с asyncio
- **HTTP запросы** - aiohttp для неблокирующих операций
- **Database** - синхронный (sqlite3), но операции быстрые

## Обработка ошибок

### Уровни обработки:

1. **Telegram API errors** - обрабатываются в `telegram_handler.py`
2. **StashApp API errors** - обрабатываются в `stash_client.py`
3. **Database errors** - обрабатываются в `database.py`
4. **Application errors** - обрабатываются в `main.py`

### Стратегии:

- **Retry** - для HTTP запросов к StashApp
- **Graceful degradation** - бот продолжает работу при ошибках API
- **Logging** - все ошибки логируются с подробностями
- **User notification** - пользователь получает понятное сообщение

## Безопасность

### Механизмы защиты:

1. **Авторизация:**
   - Whitelist по Telegram ID
   - Проверка в каждом handler

2. **Изоляция:**
   - Docker контейнер
   - Непривилегированный пользователь (botuser)
   - Ограничение ресурсов

3. **Конфиденциальность:**
   - Токены в переменных окружения
   - config.yml не в git (.gitignore)
   - Read-only mount для конфигурации

## Масштабируемость

### Текущие ограничения:

- **SQLite** - одно приложение, но достаточно для задачи
- **Polling** - не масштабируется на множество инстансов
- **In-memory state** - нет распределенного состояния

### Потенциальные улучшения:

- **Webhook** вместо polling
- **PostgreSQL** вместо SQLite для многопользовательской работы
- **Redis** для кэширования и распределенного состояния
- **Kubernetes** для оркестрации

## Мониторинг и логирование

### Логи:

```python
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        StreamHandler(stdout),      # Console
        FileHandler('bot.log')      # File
    ]
)
```

### Метрики:

- Количество отправленных фото (БД)
- Время отклика StashApp API (логи)
- Ошибки и исключения (логи)

### Healthcheck:

- Docker healthcheck проверяет наличие БД
- Можно добавить HTTP endpoint для мониторинга

## Развертывание

### Контейнеризация:

```dockerfile
FROM python:3.11-slim
# Минимальный образ
# Непривилегированный пользователь
# Volumes для данных
```

### Конфигурация:

- **12-Factor App** принципы
- Конфигурация через файлы и env переменные
- Персистентные данные в volumes

### CI/CD потенциал:

```
Build → Test → Push to Registry → Deploy → Health Check
```

## Зависимости

### Python пакеты:

- `python-telegram-bot==20.7` - Telegram API
- `aiohttp==3.9.1` - Async HTTP client
- `APScheduler==3.10.4` - Планировщик
- `PyYAML==6.0.1` - YAML конфигурация
- `python-dotenv==1.0.0` - .env поддержка

### Системные:

- Python 3.11+
- SQLite3
- Docker (опционально)

## Тестирование

### Потенциальные тесты:

```python
# Unit tests
test_config_loading()
test_database_operations()
test_stash_client_queries()

# Integration tests
test_random_photo_flow()
test_scheduler_trigger()
test_authorization()

# E2E tests
test_telegram_commands()
test_scheduled_sending()
```

## Производительность

### Оптимизации:

- **Асинхронность** - неблокирующие I/O операции
- **Индексы БД** - быстрый поиск по image_id и sent_at
- **Connection pooling** - aiohttp сессии
- **Lazy loading** - загрузка изображений по требованию

### Метрики:

- Время отклика на команду: ~2-5 сек (зависит от StashApp)
- Потребление памяти: ~50-100 MB
- CPU: минимальное (ожидание событий)

---

**Архитектура спроектирована для:**
- ✅ Надежности
- ✅ Простоты развертывания
- ✅ Легкости поддержки
- ✅ Расширяемости
