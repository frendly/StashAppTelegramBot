# Инструкция по развертыванию StashApp Telegram Bot

## Подготовка

### 1. Получение Telegram Bot Token

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`
3. Придумайте имя для бота (например: "My StashApp Bot")
4. Придумайте username (должен заканчиваться на 'bot', например: `mystash_photos_bot`)
5. Сохраните полученный токен (формат: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)
6. Настройте бота:
   ```
   /setdescription - установить описание
   /setcommands - установить список команд:
   random - Получить случайное фото
   stats - Показать статистику
   preferences - Показать предпочтения
   help - Справка
   ```

### 2. Получение Telegram ID

1. Откройте [@userinfobot](https://t.me/userinfobot)
2. Отправьте любое сообщение
3. Сохраните полученный ID (например: `123456789`)

### 3. Проверка доступа к StashApp

Убедитесь, что StashApp:
- Запущен и доступен
- GraphQL API включен (по умолчанию: `http://localhost:9999/graphql`)
- Если используется API Key, получите его в настройках StashApp

## Развертывание на TrueNAS Scale

### Способ 1: Custom App (рекомендуется)

#### Шаг 1: Подготовка файлов

```bash
# На вашем компьютере создайте директорию
mkdir ~/stash-telegram-bot
cd ~/stash-telegram-bot

# Скопируйте все файлы проекта
# Или клонируйте репозиторий
```

#### Шаг 2: Сборка Docker образа

```bash
# Соберите образ локально
docker build -t stash-telegram-bot:latest .

# Сохраните образ в tar файл
docker save stash-telegram-bot:latest -o stash-telegram-bot.tar

# Скопируйте на TrueNAS
scp stash-telegram-bot.tar root@truenas-ip:/mnt/pool/apps/
```

#### Шаг 3: Загрузка образа на TrueNAS

```bash
# Подключитесь к TrueNAS по SSH
ssh root@truenas-ip

# Загрузите образ
docker load -i /mnt/pool/apps/stash-telegram-bot.tar
```

#### Шаг 4: Создание конфигурации

```bash
# Создайте директорию для конфигурации
mkdir -p /mnt/pool/apps/stash-telegram-bot/config
mkdir -p /mnt/pool/apps/stash-telegram-bot/data

# Создайте config.yml
nano /mnt/pool/apps/stash-telegram-bot/config/config.yml
```

Вставьте конфигурацию:

```yaml
telegram:
  bot_token: "ВАШ_ТОКЕН"
  allowed_user_ids:
    - 123456789  # Ваш Telegram ID

stash:
  api_url: "http://IP_АДРЕС_STASH:9999/graphql"
  api_key: ""

scheduler:
  enabled: true
  cron: "0 10 * * *"
  timezone: "Europe/Moscow"

history:
  avoid_recent_days: 30

database:
  path: "/data/sent_photos.db"
```

#### Шаг 5: Установка через TrueNAS UI

1. Откройте **Apps** в TrueNAS Scale
2. Нажмите **Discover Apps** → **Custom App**
3. Заполните:
   - **Application Name**: `stash-telegram-bot`
   - **Image Repository**: `stash-telegram-bot`
   - **Image Tag**: `latest`
   - **Image Pull Policy**: `Never` (образ уже загружен локально)

4. **Container Environment Variables**:
   ```
   TELEGRAM_BOT_TOKEN = ваш_токен
   TZ = Europe/Moscow
   ```

5. **Storage** - добавьте Host Path Volumes:
   - **Host Path**: `/mnt/pool/apps/stash-telegram-bot/config`
     **Mount Path**: `/config`
     **Read Only**: ✅

   - **Host Path**: `/mnt/pool/apps/stash-telegram-bot/data`
     **Mount Path**: `/data`
     **Read Only**: ❌

6. **Networking**:
   - Если StashApp в отдельной сети, добавьте в ту же сеть

7. **Resource Limits** (опционально):
   - CPU: 1 core
   - Memory: 512MB

8. Нажмите **Save** и **Deploy**

### Способ 2: Docker Compose через SSH

```bash
# Подключитесь к TrueNAS
ssh root@truenas-ip

# Создайте директорию
mkdir -p /mnt/pool/apps/stash-telegram-bot
cd /mnt/pool/apps/stash-telegram-bot

# Скопируйте файлы проекта (используйте scp/git)
# Создайте config.yml

# Запустите
docker-compose up -d

# Проверьте статус
docker-compose logs -f
```

## Развертывание на обычном сервере

### Ubuntu/Debian

```bash
# Установите Docker
sudo apt update
sudo apt install docker.io docker-compose

# Клонируйте проект
git clone <repository-url> /opt/stash-telegram-bot
cd /opt/stash-telegram-bot

# Создайте конфигурацию
cp config.example.yml config.yml
nano config.yml  # Отредактируйте

# Создайте директории
mkdir -p data logs

# Запустите
docker-compose up -d

# Просмотр логов
docker-compose logs -f
```

### Автозапуск при перезагрузке

Docker Compose с `restart: unless-stopped` автоматически перезапустит контейнер.

Или создайте systemd сервис:

```bash
sudo nano /etc/systemd/system/stash-telegram-bot.service
```

```ini
[Unit]
Description=StashApp Telegram Bot
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/stash-telegram-bot
ExecStart=/usr/bin/docker-compose up -d
ExecStop=/usr/bin/docker-compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable stash-telegram-bot.service
sudo systemctl start stash-telegram-bot.service
```

## Локальная разработка

```bash
# Клонируйте проект
git clone <repository-url>
cd stash-telegram-bot

# Создайте виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Установите зависимости
pip install -r requirements.txt

# Создайте конфигурацию
cp config.example.yml config.yml
# Отредактируйте config.yml

# Запустите
python -m bot.main
```

## Проверка работы

### 1. Проверка логов

```bash
# Docker Compose
docker-compose logs -f stash-telegram-bot

# Docker
docker logs -f stash-telegram-bot

# Локально
tail -f bot.log
```

### 2. Проверка в Telegram

1. Найдите вашего бота в Telegram
2. Отправьте `/start`
3. Попробуйте `/random`
4. Проверьте `/stats`

### 3. Проверка базы данных

```bash
# Войдите в контейнер
docker exec -it stash-telegram-bot sh

# Проверьте БД
sqlite3 /data/sent_photos.db "SELECT COUNT(*) FROM sent_photos;"
```

## Обновление

### Docker

```bash
# Остановите контейнер
docker-compose down

# Пересоберите образ
docker-compose build

# Запустите заново
docker-compose up -d
```

### Без остановки (новая версия)

```bash
# Соберите новый образ с другим тегом
docker build -t stash-telegram-bot:v1.1 .

# Обновите docker-compose.yml
# Запустите
docker-compose up -d
```

## Резервное копирование

### База данных

```bash
# Создайте резервную копию
docker exec stash-telegram-bot sqlite3 /data/sent_photos.db ".backup /data/backup.db"

# Скопируйте на хост
docker cp stash-telegram-bot:/data/backup.db ./backup-$(date +%Y%m%d).db
```

### Конфигурация

```bash
# Создайте резервные копии
cp config.yml config.yml.backup
cp data/sent_photos.db data/sent_photos.db.backup
```

## Миграция

### С одного сервера на другой

```bash
# На старом сервере
docker-compose down
tar -czf stash-bot-backup.tar.gz config.yml data/

# Перенесите архив на новый сервер
scp stash-bot-backup.tar.gz new-server:/opt/stash-telegram-bot/

# На новом сервере
cd /opt/stash-telegram-bot
tar -xzf stash-bot-backup.tar.gz
docker-compose up -d
```

## Устранение неполадок

### Бот не запускается

```bash
# Проверьте логи
docker-compose logs stash-telegram-bot

# Проверьте конфигурацию
docker exec stash-telegram-bot cat /config/config.yml

# Проверьте переменные окружения
docker exec stash-telegram-bot env | grep TELEGRAM
```

### Не подключается к StashApp

```bash
# Проверьте доступность StashApp из контейнера
docker exec stash-telegram-bot ping stash-host

# Проверьте GraphQL endpoint
docker exec stash-telegram-bot curl http://stash:9999/graphql
```

### Планировщик не работает

1. Проверьте `scheduler.enabled: true` в конфигурации
2. Проверьте правильность cron выражения
3. Проверьте временную зону
4. Проверьте логи на момент запланированной отправки

## Мониторинг

### Простой healthcheck

```bash
# Проверка работы контейнера
docker ps | grep stash-telegram-bot

# Проверка наличия БД (значит бот работал)
docker exec stash-telegram-bot ls -lh /data/sent_photos.db
```

### Уведомления о сбоях (опционально)

Добавьте в cron на хосте:

```bash
# Проверка каждые 5 минут
*/5 * * * * docker ps | grep -q stash-telegram-bot || echo "Bot is down!" | mail -s "Alert" your@email.com
```

---

**Удачного развертывания! 🚀**
