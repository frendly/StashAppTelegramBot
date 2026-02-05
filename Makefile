.PHONY: help build up down logs restart clean shell backup stats
.PHONY: ghcr-login ghcr-build ghcr-push ghcr-pull ghcr-up
.PHONY: install-dev lint format check

# Конфигурация для GitHub Container Registry
REGISTRY = ghcr.io
USERNAME ?= $(shell git config user.name | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
REPO_NAME = $(shell basename $(CURDIR))
IMAGE_NAME = $(REGISTRY)/$(USERNAME)/$(REPO_NAME)
TAG ?= latest

help:
	@echo "StashApp Telegram Bot - Команды управления"
	@echo ""
	@echo "Локальная разработка:"
	@echo "  make build       - Собрать Docker образ локально"
	@echo "  make up          - Запустить бот (локальная сборка)"
	@echo "  make down        - Остановить бот"
	@echo "  make logs        - Просмотр логов"
	@echo "  make restart     - Перезапустить бот"
	@echo "  make clean       - Очистка (остановка + удаление volumes)"
	@echo "  make shell       - Зайти в контейнер"
	@echo "  make backup      - Создать резервную копию БД"
	@echo "  make stats       - Показать статистику из БД"
	@echo ""
	@echo "Разработка и качество кода:"
	@echo "  make install-dev - Установить dev-зависимости (ruff)"
	@echo "  make lint        - Проверить код линтером"
	@echo "  make format      - Автоформатирование кода"
	@echo "  make check       - Проверить форматирование (без изменений)"
	@echo "  make test        - Запустить unit-тесты (pytest)"
	@echo ""
	@echo "GitHub Container Registry:"
	@echo "  make ghcr-login      - Авторизация в GHCR"
	@echo "  make ghcr-build      - Собрать образ для GHCR"
	@echo "  make ghcr-push       - Опубликовать образ в GHCR"
	@echo "  make ghcr-pull       - Скачать образ из GHCR"
	@echo "  make ghcr-up         - Запустить бот из GHCR"
	@echo ""
	@echo "Текущие настройки GHCR:"
	@echo "  Registry:  $(REGISTRY)"
	@echo "  Username:  $(USERNAME)"
	@echo "  Image:     $(IMAGE_NAME):$(TAG)"

build:
	docker-compose build

up:
	docker-compose up -d
	@echo "Бот запущен! Проверьте логи: make logs"

down:
	docker-compose down

logs:
	docker-compose logs -f stash-telegram-bot

restart:
	docker-compose restart stash-telegram-bot

clean:
	docker-compose down -v
	@echo "Контейнеры и volumes удалены"

shell:
	docker exec -it stash-telegram-bot sh

backup:
	@echo "Создание резервной копии БД..."
	@mkdir -p backups
	docker cp stash-telegram-bot:/data/sent_photos.db backups/backup-$$(date +%Y%m%d-%H%M%S).db
	@echo "Резервная копия создана в директории backups/"

stats:
	@echo "Статистика из базы данных:"
	@docker exec stash-telegram-bot sqlite3 /data/sent_photos.db "SELECT COUNT(*) as 'Total Photos Sent' FROM sent_photos;"
	@docker exec stash-telegram-bot sqlite3 /data/sent_photos.db "SELECT COUNT(DISTINCT image_id) as 'Unique Photos' FROM sent_photos;"
	@docker exec stash-telegram-bot sqlite3 /data/sent_photos.db "SELECT 'Last sent: ' || MAX(sent_at) FROM sent_photos;"

# GitHub Container Registry команды
ghcr-login:
	@echo "Авторизация в GitHub Container Registry..."
	@echo "Введите ваш GitHub Personal Access Token (PAT):"
	@docker login $(REGISTRY) -u $(USERNAME)

ghcr-build:
	@echo "Сборка образа для GHCR: $(IMAGE_NAME):$(TAG)"
	docker build -t $(IMAGE_NAME):$(TAG) .
	@echo "✅ Образ собран: $(IMAGE_NAME):$(TAG)"

ghcr-push: ghcr-build
	@echo "Публикация образа в GHCR: $(IMAGE_NAME):$(TAG)"
	docker push $(IMAGE_NAME):$(TAG)
	@echo "✅ Образ опубликован: $(IMAGE_NAME):$(TAG)"
	@echo "Доступен по адресу: https://github.com/$(USERNAME)?tab=packages"

ghcr-pull:
	@echo "Скачивание образа из GHCR: $(IMAGE_NAME):$(TAG)"
	docker pull $(IMAGE_NAME):$(TAG)
	@echo "✅ Образ скачан"

ghcr-up:
	@echo "Запуск бота из GHCR..."
	@if [ ! -f docker-compose.ghcr.yml ]; then \
		echo "❌ Файл docker-compose.ghcr.yml не найден!"; \
		exit 1; \
	fi
	@sed "s|ghcr.io/username/stash-telegram-bot|$(IMAGE_NAME)|g" docker-compose.ghcr.yml > docker-compose.ghcr.tmp.yml
	docker-compose -f docker-compose.ghcr.tmp.yml pull
	docker-compose -f docker-compose.ghcr.tmp.yml up -d
	@rm -f docker-compose.ghcr.tmp.yml
	@echo "✅ Бот запущен из образа GHCR"

# Команды для разработки и качества кода
install-dev:
	@echo "Установка dev-зависимостей..."
	pip install -r requirements-dev.txt
	@echo "✅ Dev-зависимости установлены"

lint:
	@echo "Проверка кода линтером..."
	ruff check bot/
	@echo "✅ Проверка завершена"

format:
	@echo "Форматирование кода..."
	ruff format bot/
	@echo "✅ Код отформатирован"

check:
	@echo "Проверка форматирования (без изменений)..."
	ruff check bot/
	ruff format --check bot/
	@echo "✅ Проверка завершена"

test:
	@echo "Запуск unit-тестов..."
	pytest
