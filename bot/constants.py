"""Константы проекта."""

# TTL кэшей (в секундах)
CACHE_TTL_FILTERING = 60  # TTL кэша фильтрации (списки перформеров и галерей)
CACHE_TTL_GALLERIES = 3600  # TTL кэша списка галерей (1 час)

# Веса галерей
GALLERY_WEIGHT_MULTIPLIER_POSITIVE = 1.2  # Множитель веса при положительном голосе
GALLERY_WEIGHT_MULTIPLIER_NEGATIVE = 0.8  # Множитель веса при отрицательном голосе
GALLERY_WEIGHT_MIN = 0.1  # Минимальный вес галереи
GALLERY_WEIGHT_MAX = 10.0  # Максимальный вес галереи
GALLERY_WEIGHT_DEFAULT = 1.0  # Вес галереи по умолчанию

# Пороги исключения галерей
EXCLUSION_THRESHOLD_PERCENTAGE = (
    33.3  # Процент минусов для исключения (для галерей с 3+ изображениями)
)
EXCLUSION_THRESHOLD_MIN_VOTES = 3  # Минимальное количество минусов для исключения

# Rate limits (в секундах)
RATE_LIMIT_UNAUTHORIZED_MESSAGE = 30  # Задержка между сообщениями об отсутствии доступа

# Коэффициенты для batch операций
BATCH_SIZE_MULTIPLIER = 0.8  # Множитель для расчета размера батча
