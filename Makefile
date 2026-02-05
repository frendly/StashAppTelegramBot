.PHONY: help build up down logs restart clean shell backup stats
.PHONY: ghcr-login ghcr-build ghcr-push ghcr-pull ghcr-up
.PHONY: install-dev lint format check complexity test test-file check-venv

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
	@echo "  make install-dev - Установить dev-зависимости (ruff, radon)"
	@echo "  make lint        - Проверить код линтером"
	@echo "  make format      - Автоформатирование кода"
	@echo "  make check       - Проверить форматирование (без изменений)"
	@echo "  make complexity  - Анализ сложности кода (radon)"
	@echo "  make test        - Запустить unit-тесты (pytest)"
	@echo "  make test-file FILE=<path> - Запустить тесты из конкретного файла"
	@if [ "$(HAS_UV)" = "yes" ]; then \
		echo ""; \
		echo "ℹ️  Используется uv для управления окружением"; \
	else \
		echo ""; \
		echo "💡 Используется .venv (fallback)"; \
		echo "   Рекомендуется установить uv: curl -LsSf https://astral.sh/uv/install.sh | sh"; \
	fi
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
# Приоритет: uv > .venv (fallback)
# uv автоматически управляет виртуальным окружением и не требует активации
HAS_UV := $(shell command -v uv >/dev/null 2>&1 && echo "yes" || echo "no")
VENV_PYTHON := $(shell if [ "$(HAS_UV)" = "yes" ]; then echo "uv run python"; else if [ -d .venv ] && .venv/bin/python -c "import sys" >/dev/null 2>&1; then echo ".venv/bin/python"; else echo ""; fi; fi)
VENV_PIP := $(shell if [ "$(HAS_UV)" = "yes" ]; then echo "uv pip install"; else if [ -d .venv ] && .venv/bin/pip --version >/dev/null 2>&1; then echo ".venv/bin/pip install"; else echo ""; fi; fi)

# Проверка доступности окружения
check-venv:
	@if [ "$(HAS_UV)" != "yes" ] && [ -z "$(VENV_PYTHON)" ]; then \
		echo "❌ Ошибка: uv не установлен и .venv не найден"; \
		echo ""; \
		echo "Установите uv (рекомендуется):"; \
		echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		echo ""; \
		echo "Или создайте окружение вручную:"; \
		echo "  python3 -m venv .venv"; \
		echo "  .venv/bin/pip install -r requirements.txt"; \
		echo "  .venv/bin/pip install -r requirements-dev.txt"; \
		exit 1; \
	fi

install-dev: check-venv
	@echo "Установка dev-зависимостей..."
	@if [ "$(HAS_UV)" = "yes" ]; then \
		echo "Используется: uv"; \
		uv pip install -r requirements.txt; \
		uv pip install -r requirements-dev.txt; \
	else \
		echo "Используется: .venv/bin/pip"; \
		.venv/bin/pip install -r requirements.txt; \
		.venv/bin/pip install -r requirements-dev.txt; \
	fi
	@echo "✅ Dev-зависимости установлены"

lint: check-venv
	@echo "Проверка кода линтером..."
	@if [ "$(HAS_UV)" = "yes" ]; then \
		uv run python -m ruff check bot/; \
	else \
		.venv/bin/python -m ruff check bot/; \
	fi
	@echo "✅ Проверка завершена"

format: check-venv
	@echo "Форматирование кода..."
	@if [ "$(HAS_UV)" = "yes" ]; then \
		uv run python -m ruff format bot/; \
	else \
		.venv/bin/python -m ruff format bot/; \
	fi
	@echo "✅ Код отформатирован"

check: check-venv
	@echo "Проверка форматирования (без изменений)..."
	@if [ "$(HAS_UV)" = "yes" ]; then \
		uv run python -m ruff check bot/; \
		uv run python -m ruff format --check bot/; \
	else \
		.venv/bin/python -m ruff check bot/; \
		.venv/bin/python -m ruff format --check bot/; \
	fi
	@echo "✅ Проверка завершена"

complexity: check-venv
	@echo "Анализ сложности кода..."
	@if [ "$(HAS_UV)" = "yes" ]; then \
		uv run python -m radon cc bot/ --min B -a; \
	else \
		.venv/bin/python -m radon cc bot/ --min B -a; \
	fi
	@echo "✅ Анализ завершен"

test: check-venv
	@echo "Запуск unit-тестов..."
	@if [ "$(HAS_UV)" = "yes" ]; then \
		echo "Используется: uv run python -m pytest"; \
		uv run python -m pytest; \
	else \
		echo "Используется: .venv/bin/python -m pytest"; \
		.venv/bin/python -m pytest; \
	fi

test-file: check-venv
	@if [ -z "$(FILE)" ]; then \
		echo "❌ Ошибка: укажите файл через FILE=<path>"; \
		echo "Пример: make test-file FILE=tests/handlers/test_vote_handler.py"; \
		exit 1; \
	fi
	@echo "Запуск тестов из файла: $(FILE)"
	@if [ "$(HAS_UV)" = "yes" ]; then \
		echo "Используется: uv run python -m pytest"; \
		uv run python -m pytest $(FILE) -v --tb=short; \
	else \
		echo "Используется: .venv/bin/python -m pytest"; \
		.venv/bin/python -m pytest $(FILE) -v --tb=short; \
	fi
