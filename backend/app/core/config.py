import os
from dotenv import load_dotenv

load_dotenv()


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev_secret")
    JWT_ALGO: str = os.getenv("JWT_ALGO", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = _get_env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 30)
    REFRESH_TOKEN_EXPIRE_DAYS: int = _get_env_int("REFRESH_TOKEN_EXPIRE_DAYS", 7)
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")

settings = Settings()