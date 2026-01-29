# StashApp Telegram Bot Dockerfile
FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Создание рабочей директории
WORKDIR /app

# Копирование файлов зависимостей
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода приложения
COPY bot/ ./bot/

# Создание директории для данных
RUN mkdir -p /data /config

# Создание пользователя для запуска приложения (безопасность)
RUN useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app /data /config

# Переключение на непривилегированного пользователя
USER botuser

# Переменные окружения по умолчанию
ENV PYTHONUNBUFFERED=1
ENV CONFIG_PATH=/config/config.yml

# Healthcheck (опционально)
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os; exit(0 if os.path.exists('/data/sent_photos.db') else 1)"

# Запуск бота
CMD ["python", "-m", "bot.main"]
