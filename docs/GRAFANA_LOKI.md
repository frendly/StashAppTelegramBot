# Интеграция с Grafana Loki

Данная документация описывает процесс интеграции бота с Grafana Loki для централизованного сбора и анализа логов.

## Архитектура

```
┌─────────────────┐
│  Telegram Bot   │
│  (JSON логи)    │
└────────┬────────┘
         │
         ├───> bot.log (файл)
         │
         └───> stdout (Docker logs)
                  │
                  ▼
         ┌─────────────────┐
         │    Promtail     │
         │  (сбор логов)   │
         └────────┬────────┘
                  │
                  ▼
         ┌─────────────────┐
         │  Grafana Loki   │
         │  (хранение)      │
         └────────┬────────┘
                  │
                  ▼
         ┌─────────────────┐
         │    Grafana      │
         │  (визуализация) │
         └─────────────────┘
```

## Шаг 1: Установка Grafana Loki

### Вариант A: Docker Compose (рекомендуется)

Создайте файл `docker-compose.loki.yml`:

```yaml
version: '3.8'

services:
  loki:
    image: grafana/loki:latest
    container_name: loki
    ports:
      - "3100:3100"
    volumes:
      - ./loki-config:/etc/loki
      - loki-data:/loki
    command: -config.file=/etc/loki/loki-config.yaml
    restart: unless-stopped

  promtail:
    image: grafana/promtail:latest
    container_name: promtail
    volumes:
      - ./logs:/var/log/bot:ro
      - ./promtail-config:/etc/promtail
    command: -config.file=/etc/promtail/promtail-config.yaml
    restart: unless-stopped
    depends_on:
      - loki

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana-data:/var/lib/grafana
    restart: unless-stopped
    depends_on:
      - loki

volumes:
  loki-data:
  grafana-data:
```

### Вариант B: Отдельная установка

Следуйте официальной документации:
- [Loki Installation](https://grafana.com/docs/loki/latest/installation/)
- [Promtail Installation](https://grafana.com/docs/loki/latest/clients/promtail/)

## Шаг 2: Конфигурация Loki

Создайте директорию `loki-config` и файл `loki-config.yaml`:

```yaml
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    instance_addr: 127.0.0.1
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2020-10-24
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

ruler:
  alertmanager_url: http://localhost:9093

# Лимиты для предотвращения переполнения
limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  ingestion_rate_mb: 16
  ingestion_burst_size_mb: 32
```

## Шаг 3: Конфигурация Promtail

Создайте директорию `promtail-config` и файл `promtail-config.yaml`:

```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  # Конфигурация для чтения логов из файла
  - job_name: stash-telegram-bot-file
    static_configs:
      - targets:
          - localhost
        labels:
          job: stash-telegram-bot
          source: file
          __path__: /var/log/bot/bot.log*
    pipeline_stages:
      # Парсинг JSON логов
      - json:
          expressions:
            timestamp: timestamp
            level: level
            logger: logger
            message: message
            module: module
            function: function
            line: line
            request_id: request_id
            user_id: user_id
            image_id: image_id
            gallery_id: gallery_id
      # Добавление меток для фильтрации
      # Примечание: Promtail автоматически преобразует значения в строки для меток
      - labels:
          level:
          logger:
          user_id:  # int из JSON будет преобразован в строку автоматически
          image_id:
          gallery_id:
      # Преобразование timestamp в наносекунды
      - timestamp:
          source: timestamp
          format: RFC3339Nano

  # Конфигурация для чтения логов из Docker (stdout)
  - job_name: stash-telegram-bot-docker
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 5s
    relabel_configs:
      # Фильтруем только контейнер бота
      - source_labels: [__meta_docker_container_name]
        regex: stash-telegram-bot
        action: keep
      # Добавляем метки
      - source_labels: [__meta_docker_container_name]
        target_label: container
      - replacement: stash-telegram-bot
        target_label: job
      - replacement: docker
        target_label: source
    pipeline_stages:
      # Парсинг JSON логов из stdout
      - json:
          expressions:
            timestamp: timestamp
            level: level
            logger: logger
            message: message
            request_id: request_id
            user_id: user_id
            image_id: image_id
            gallery_id: gallery_id
      - labels:
          level:
          logger:
      - timestamp:
          source: timestamp
          format: RFC3339Nano
```

## Шаг 4: Обновление docker-compose.yml бота

Убедитесь, что логи бота доступны для Promtail:

```yaml
services:
  stash-telegram-bot:
    # ... существующая конфигурация ...
    volumes:
      - ./config.yml:/config/config.yml:ro
      - ./data:/data
      - ./logs:/app/logs  # Важно: логи должны быть доступны
    environment:
      - LOG_PATH=/app/logs/bot.log
    networks:
      - monitoring  # Добавьте сеть для связи с Loki

networks:
  monitoring:
    external: true
```

## Шаг 5: Запуск стека мониторинга

```bash
# Создайте необходимые директории
mkdir -p loki-config promtail-config logs

# Скопируйте конфигурационные файлы (см. шаги 2 и 3)

# Запустите стек
docker-compose -f docker-compose.loki.yml up -d

# Проверьте статус
docker-compose -f docker-compose.loki.yml ps
```

## Шаг 6: Настройка Grafana

### 6.1. Добавление источника данных Loki

1. Откройте Grafana: http://localhost:3000
2. Логин: `admin`, Пароль: `admin`
3. Перейдите в **Configuration** → **Data Sources**
4. Нажмите **Add data source**
5. Выберите **Loki**
6. URL: `http://loki:3100`
7. Нажмите **Save & Test**

### 6.2. Создание первого запроса

Перейдите в **Explore** и попробуйте запросы:

```logql
# Все логи бота
{job="stash-telegram-bot"}

# Только ошибки
{job="stash-telegram-bot"} |= "ERROR"

# Логи конкретного пользователя
{job="stash-telegram-bot", user_id="123456789"}

# Логи конкретного изображения
{job="stash-telegram-bot", image_id="img_123"}

# Логи по уровню
{job="stash-telegram-bot", level="INFO"}

# Поиск по тексту
{job="stash-telegram-bot"} |~ "отправка фото"

# Логи с контекстом request_id
{job="stash-telegram-bot"} | json | request_id != ""
```

## Шаг 7: Примеры полезных запросов LogQL

### Поиск ошибок за последний час

```logql
{job="stash-telegram-bot", level="ERROR"} [1h]
```

### Подсчет логов по уровням

```logql
sum by (level) (count_over_time({job="stash-telegram-bot"}[5m]))
```

### Топ пользователей по активности

```logql
topk(10, sum by (user_id) (count_over_time({job="stash-telegram-bot", user_id!=""}[1h])))
```

### Логи с конкретным request_id (трейсинг)

```logql
{job="stash-telegram-bot"} | json | request_id="req_abc123"
```

### Логи отправки фото

```logql
{job="stash-telegram-bot"} |~ "Фото успешно отправлено" | json
```

### Ошибки при отправке фото

```logql
{job="stash-telegram-bot"} |~ "Ошибка.*отправк" | json
```

## Шаг 8: Создание дашборда

### 8.1. Создание панели "Общая статистика"

1. Создайте новый дашборд
2. Добавьте панель **Stat**
3. Запрос:
   ```logql
   sum(count_over_time({job="stash-telegram-bot"}[5m]))
   ```
4. Название: "Всего логов за 5 минут"

### 8.2. Панель "Распределение по уровням"

1. Добавьте панель **Pie chart**
2. Запрос:
   ```logql
   sum by (level) (count_over_time({job="stash-telegram-bot"}[1h]))
   ```

### 8.3. Панель "Логи в реальном времени"

1. Добавьте панель **Logs**
2. Запрос:
   ```logql
   {job="stash-telegram-bot"} | json
   ```
3. Включите опцию "Live"

### 8.4. Панель "Активность пользователей"

1. Добавьте панель **Table**
2. Запрос:
   ```logql
   topk(10, sum by (user_id) (count_over_time({job="stash-telegram-bot", user_id!=""}[1h])))
   ```

### 8.5. Панель "Последние ошибки"

1. Добавьте панель **Logs**
2. Запрос:
   ```logql
   {job="stash-telegram-bot", level="ERROR"} | json
   ```
3. Сортировка: по времени (новые сверху)

## Шаг 9: Настройка алертов (опционально)

### Создание правила алерта в Loki

Создайте файл `loki-config/rules/alerts.yaml`:

```yaml
groups:
  - name: bot_alerts
    interval: 30s
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate({job="stash-telegram-bot", level="ERROR"}[5m])) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень ошибок в боте"
          description: "Более 0.1 ошибок в секунду за последние 5 минут"
```

Обновите `loki-config.yaml`:

```yaml
ruler:
  alertmanager_url: http://alertmanager:9093
  storage:
    type: local
    local:
      directory: /loki/rules
  rule_path: /loki/rules
```

## Шаг 10: Troubleshooting

### Проблема: Promtail не читает логи

**Решение:**
1. Проверьте права доступа к файлам логов
2. Убедитесь, что путь в `__path__` правильный
3. Проверьте логи Promtail: `docker logs promtail`

### Проблема: Логи не появляются в Grafana

**Решение:**
1. Проверьте подключение Promtail к Loki:
   ```bash
   curl http://localhost:3100/ready
   ```
2. Проверьте метки в запросе Grafana
3. Убедитесь, что формат JSON корректен

### Проблема: Высокое потребление диска

**Решение:**
1. Настройте retention в Loki:
   ```yaml
   limits_config:
     retention_period: 720h  # 30 дней
   ```
2. Используйте компрессию:
   ```yaml
   compactor:
     working_directory: /loki/compactor
     shared_store: filesystem
   ```

### Проблема: Медленные запросы

**Решение:**
1. Используйте индексы для часто используемых полей
2. Ограничьте временной диапазон запросов
3. Используйте агрегации вместо детальных логов

## Дополнительные ресурсы

- [Документация Grafana Loki](https://grafana.com/docs/loki/latest/)
- [LogQL Query Language](https://grafana.com/docs/loki/latest/logql/)
- [Promtail Configuration](https://grafana.com/docs/loki/latest/clients/promtail/configuration/)
- [Grafana Dashboards](https://grafana.com/grafana/dashboards/)

## Примеры готовых дашбордов

Импортируйте готовые дашборды из Grafana:
- [Loki Dashboard](https://grafana.com/grafana/dashboards/13639)
- [Application Logs](https://grafana.com/grafana/dashboards/15141)

## Рекомендации по производительности

1. **Ротация логов**: Настройте ротацию в конфигурации бота для предотвращения больших файлов
2. **Retention**: Настройте период хранения логов в Loki (рекомендуется 30-90 дней)
3. **Индексация**: Используйте метки для часто фильтруемых полей (level, user_id)
4. **Сжатие**: Включите сжатие в Loki для экономии места
5. **Мониторинг**: Следите за использованием диска и памяти Loki

## Безопасность

1. **Аутентификация**: Включите аутентификацию в Grafana для production
2. **HTTPS**: Используйте HTTPS для доступа к Grafana
3. **Ограничение доступа**: Настройте firewall для портов Loki и Grafana
4. **Резервное копирование**: Регулярно делайте бэкапы данных Loki
