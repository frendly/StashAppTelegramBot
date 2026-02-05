#!/usr/bin/env python3
"""Скрипт для healthcheck Docker контейнера."""

import json
import os
import sys
import urllib.request
from urllib.error import URLError

# Пробуем оба возможных порта: 8080 (polling) и 8443 (webhook)
ports = [os.getenv("HEALTH_CHECK_PORT", "8080"), "8443"]
# Убираем дубликаты
ports = list(dict.fromkeys(ports))

for port in ports:
    try:
        url = f"http://localhost:{port}/health"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
            status = data.get("overall_status", "unknown")
            if status in ("healthy", "degraded"):
                sys.exit(0)
    except (URLError, ValueError, KeyError, OSError):
        # Пробуем следующий порт
        continue

# Если ни один порт не ответил или все unhealthy
sys.exit(1)
