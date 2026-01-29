# 📦 Использование GitHub Container Registry

## Преимущества GHCR

✅ **Бесплатно** для публичных репозиториев
✅ **Интегрировано** с GitHub
✅ **Автоматическая сборка** через GitHub Actions
✅ **Версионирование** образов
✅ **Не нужно** собирать локально

---

## 🚀 Быстрый старт

### Вариант 1: Использование готового образа (если опубликован)

```bash
# В docker-compose.yml замените build на image:
services:
  stash-telegram-bot:
    image: ghcr.io/username/stash-telegram-bot:latest
    # остальная конфигурация...
```

### Вариант 2: Публикация своего образа

---

## 📋 Пошаговая инструкция

### 1. Создание GitHub репозитория

```bash
# Инициализация git (если еще не сделано)
git init
git add .
git commit -m "Initial commit: StashApp Telegram Bot"

# Создайте репозиторий на GitHub, затем:
git remote add origin https://github.com/username/stash-telegram-bot.git
git branch -M main
git push -u origin main
```

### 2. Создание Personal Access Token (PAT)

1. Откройте: https://github.com/settings/tokens
2. Нажмите **"Generate new token"** → **"Generate new token (classic)"**
3. Выберите scopes:
   - ✅ `write:packages`
   - ✅ `read:packages`
   - ✅ `delete:packages` (опционально)
4. Сохраните токен!

### 3. Локальная публикация образа

```bash
# Авторизация в GHCR
echo "YOUR_GITHUB_TOKEN" | docker login ghcr.io -u USERNAME --password-stdin

# Сборка образа с правильным тегом
docker build -t ghcr.io/username/stash-telegram-bot:latest .

# Опционально: добавьте версию
docker tag ghcr.io/username/stash-telegram-bot:latest ghcr.io/username/stash-telegram-bot:v1.0.0

# Публикация
docker push ghcr.io/username/stash-telegram-bot:latest
docker push ghcr.io/username/stash-telegram-bot:v1.0.0
```

### 4. Автоматическая сборка через GitHub Actions

Создайте `.github/workflows/docker-publish.yml`:

```yaml
name: Docker Build and Push

on:
  push:
    branches: [ main ]
    tags: [ 'v*.*.*' ]
  pull_request:
    branches: [ main ]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata (tags, labels)
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=ref,event=branch
            type=ref,event=pr
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=sha

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: ${{ github.event_name != 'pull_request' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

### 5. Использование образа на сервере

Обновите `docker-compose.yml`:

```yaml
version: '3.8'

services:
  stash-telegram-bot:
    image: ghcr.io/username/stash-telegram-bot:latest
    # Удалите строку: build: .
    container_name: stash-telegram-bot
    restart: unless-stopped
    
    volumes:
      - ./config.yml:/config/config.yml:ro
      - ./data:/data
      - ./logs:/app/logs
    
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - STASH_API_KEY=${STASH_API_KEY:-}
      - TZ=${TIMEZONE:-Europe/Moscow}
    
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 512M
        reservations:
          cpus: '0.5'
          memory: 256M
    
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

Запуск:

```bash
# Авторизация (если образ private)
echo "YOUR_GITHUB_TOKEN" | docker login ghcr.io -u username --password-stdin

# Запуск
docker-compose pull  # Скачать последнюю версию
docker-compose up -d
```

---

## 🔒 Публичный vs Приватный образ

### Публичный образ (рекомендуется для open source)

```bash
# Сделать образ публичным:
# 1. Откройте: https://github.com/username?tab=packages
# 2. Найдите ваш пакет
# 3. Package settings → Change visibility → Public
```

**Преимущества:**
- ✅ Не нужна авторизация для pull
- ✅ Доступен всем пользователям
- ✅ Бесплатный безлимитный трафик

### Приватный образ

**Использование:**
```bash
# На сервере создайте ~/.docker/config.json
docker login ghcr.io -u username
# Введите PAT как пароль
```

**Или через docker-compose:**
```yaml
# НЕ РЕКОМЕНДУЕТСЯ - токен в открытом виде!
services:
  stash-telegram-bot:
    image: ghcr.io/username/stash-telegram-bot:latest
    # Используйте docker login вместо этого
```

---

## 📌 Версионирование

### Семантическое версионирование

```bash
# Создайте git tag
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0

# GitHub Actions автоматически соберет и опубликует:
# - ghcr.io/username/stash-telegram-bot:v1.0.0
# - ghcr.io/username/stash-telegram-bot:1.0
# - ghcr.io/username/stash-telegram-bot:latest
```

### Использование конкретной версии

```yaml
services:
  stash-telegram-bot:
    # Стабильная версия (рекомендуется для продакшена)
    image: ghcr.io/username/stash-telegram-bot:v1.0.0
    
    # Или последний minor версии
    # image: ghcr.io/username/stash-telegram-bot:1.0
    
    # Или всегда последняя (для разработки)
    # image: ghcr.io/username/stash-telegram-bot:latest
```

---

## 🔄 Автоматическое обновление

### Вариант 1: Watchtower (автообновление контейнеров)

```yaml
# docker-compose.yml
services:
  stash-telegram-bot:
    image: ghcr.io/username/stash-telegram-bot:latest
    # ... остальная конфигурация

  watchtower:
    image: containrrr/watchtower
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - WATCHTOWER_POLL_INTERVAL=3600  # Проверка каждый час
      - WATCHTOWER_CLEANUP=true
    restart: unless-stopped
```

### Вариант 2: Ручное обновление

```bash
# Обновление до последней версии
docker-compose pull
docker-compose up -d

# Проверка версии
docker inspect ghcr.io/username/stash-telegram-bot:latest | grep Created
```

---

## 📊 Мониторинг и метрики

### Просмотр доступных версий

```bash
# Через GitHub CLI
gh api /user/packages/container/stash-telegram-bot/versions

# Или на веб-странице:
# https://github.com/username?tab=packages
```

### Статистика скачиваний

Доступна на странице пакета в GitHub.

---

## 🛠️ Отладка

### Проверка авторизации

```bash
docker login ghcr.io -u username
# Должно показать: Login Succeeded
```

### Проверка доступности образа

```bash
docker pull ghcr.io/username/stash-telegram-bot:latest
```

### Просмотр слоев образа

```bash
docker history ghcr.io/username/stash-telegram-bot:latest
```

---

## 📝 Обновленный Makefile

Добавьте команды для работы с GHCR:

```makefile
# Makefile
REGISTRY = ghcr.io
USERNAME = username
IMAGE_NAME = stash-telegram-bot
TAG = latest

.PHONY: docker-login docker-build docker-push docker-pull

docker-login:
	@echo "Logging in to GitHub Container Registry..."
	@echo "$(GITHUB_TOKEN)" | docker login $(REGISTRY) -u $(USERNAME) --password-stdin

docker-build:
	docker build -t $(REGISTRY)/$(USERNAME)/$(IMAGE_NAME):$(TAG) .

docker-push: docker-build
	docker push $(REGISTRY)/$(USERNAME)/$(IMAGE_NAME):$(TAG)

docker-pull:
	docker pull $(REGISTRY)/$(USERNAME)/$(IMAGE_NAME):$(TAG)

# Использование:
# make docker-build TAG=v1.0.0
# make docker-push TAG=v1.0.0
```

---

## 🎯 Рекомендуемый workflow

### Для разработки:

```bash
# Локальная сборка
docker-compose build
docker-compose up -d
```

### Для продакшена:

```bash
# Используйте образ из GHCR
docker-compose pull
docker-compose up -d
```

### Для релиза:

```bash
# Создайте версию
git tag -a v1.0.0 -m "Release 1.0.0"
git push origin v1.0.0

# GitHub Actions автоматически:
# 1. Соберет образ
# 2. Опубликует в GHCR
# 3. Создаст GitHub Release
```

---

## 💡 Best Practices

1. **Используйте семантическое версионирование** (v1.0.0, v1.1.0, v2.0.0)
2. **Тегируйте стабильные релизы** - не полагайтесь только на latest
3. **Документируйте изменения** в CHANGELOG.md
4. **Проверяйте образы** перед продакшен деплоем
5. **Используйте digest** для максимальной стабильности:
   ```yaml
   image: ghcr.io/username/stash-telegram-bot@sha256:abc123...
   ```

---

## 📚 Дополнительные ресурсы

- [GitHub Container Registry Docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [GitHub Actions Docker](https://docs.github.com/en/actions/publishing-packages/publishing-docker-images)
- [Docker Hub vs GHCR](https://github.blog/2021-06-21-github-packages-container-registry-generally-available/)

---

## ✅ Итого

GitHub Container Registry - отличный выбор для:
- ✅ Open source проектов
- ✅ Приватных проектов (до 500 MB бесплатно)
- ✅ Автоматизации CI/CD
- ✅ Версионирования образов
- ✅ Интеграции с GitHub

**Рекомендуется использовать GHCR вместо локальной сборки для продакшена!** 🚀
