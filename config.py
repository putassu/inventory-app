import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Определяем корень проекта
BASE_DIR = Path(__file__).parent.resolve()

# Загружаем .env
load_dotenv(BASE_DIR / ".env")

class Config:
    # Директории
    BASE_DIR = BASE_DIR
    TESTS_DIR = BASE_DIR / "tests"
    CASES_DIR = TESTS_DIR / "cases"
    PROMPTS_DIR = BASE_DIR / "prompts"
    
    # Модели
    GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini/gemini-3.5-flash")
    CLOUD_GEMMA_MODEL_NAME = os.getenv("CLOUD_GEMMA_MODEL_NAME", "gemma-4-31b")
    LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL_NAME", "local-gemma-4")
    SMALL_LOCAL_MODEL_NAME = os.getenv("SMALL_LOCAL_MODEL_NAME", "local-gemma-4-e4b")
    EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "local-bge-m3")
    
    # For backward compatibility
    CLOUD_MODEL_NAME = GEMINI_MODEL_NAME
    
    # LiteLLM
    LITELLM_API_BASE = os.getenv("LITELLM_API_BASE", "http://172.17.0.1:4000")
    LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
    API_URL = f"{LITELLM_API_BASE}/v1/chat/completions" 
    
    # S3 / MinIO
    MINIO_ROOT_USER = os.getenv("MINIO_ROOT_USER", "admin")
    MINIO_ROOT_PASSWORD = os.getenv("MINIO_ROOT_PASSWORD", "")
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "inventory-media")

    @property
    def S3_ENDPOINT_URL(self) -> str:
        url = os.getenv("S3_ENDPOINT_URL", "http://minio:9000")
        is_docker = os.path.exists("/.dockerenv") or os.getenv("RUNNING_IN_DOCKER") == "true"
        if not is_docker:
            url = url.replace("://minio:9000", "://127.0.0.1:9010")
            url = url.replace("://minio:", "://127.0.0.1:")
        return url

    # Qdrant
    @property
    def QDRANT_URL(self) -> str:
        url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        is_docker = os.path.exists("/.dockerenv") or os.getenv("RUNNING_IN_DOCKER") == "true"
        if not is_docker:
            url = url.replace("://qdrant:", "://127.0.0.1:")
        return url

    # Redis
    @property
    def REDIS_URL(self) -> str:
        url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        is_docker = os.path.exists("/.dockerenv") or os.getenv("RUNNING_IN_DOCKER") == "true"
        if not is_docker:
            url = url.replace("://redis:", "://127.0.0.1:")
            url = url.replace("://redis/", "://127.0.0.1/")
        return url

    
    # Логгирование
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    
    # Настройки обработки изображений
    # Адаптивный даунскейл: {кол-во фото: размер стороны в px}
    ADAPTIVE_IMAGE_SIZES = {
        1: 1024, # 1 фото = высокое качество
        2: 768,  # 2 фото = среднее сжатие
        3: 512   # 3 фото = сильное сжатие (чтобы влезть в контекст)
    }
    JPEG_QUALITY = 85
    
    # Настройки превью (Thumbnails) для Android
    THUMBNAIL_SIZE = 256
    THUMBNAIL_QUALITY = 60

    # Настройки безопасности (JWT)
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your_very_long_and_secure_random_string_here")
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "43200")) # 30 дней
    
    # Лимиты и Garbage Collector
    MAX_TASKS_PER_USER = int(os.getenv("MAX_TASKS_PER_USER", "5"))
    GARBAGE_TTL_SECONDS = int(os.getenv("GARBAGE_TTL_SECONDS", "2592000")) # 30 дней в секундах
    MIN_CONFIDENCE_SCORE = float(os.getenv("MIN_CONFIDENCE_SCORE", "0.8"))
    LANGGRAPH_NODE_RETRIES = int(os.getenv("LANGGRAPH_NODE_RETRIES", "2"))


def setup_logger():
    logger = logging.getLogger("inventory_app")
    
    if not logger.handlers:
        numeric_level = getattr(logging, Config.LOG_LEVEL, logging.INFO)
        logger.setLevel(numeric_level)
        
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s', 
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger

settings = Config()
logger = setup_logger()