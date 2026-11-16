import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"

class Settings(BaseSettings):
    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str
    # Google rejects an OAuth redirect URI that is a private IP unless
    # device_id/device_name are present in the authorization request.
    GOOGLE_DEVICE_ID: str = ""
    GOOGLE_DEVICE_NAME: str = "KiraAIAssistant"

    TOKEN_ENCRYPTION_KEY: str
    SESSION_COOKIE_NAME: str
    SESSION_COOKIE_SECURE: bool = False

    SECRET_KEY: str

    # контейнер, логи которого показывает дашборд, если в запросе не передан
    LOGS_CONTAINER: str = ""

    # Токен, которым Telegram-агент авторизует отправку логов в дашборд.
    # Пустая строка полностью отключает приём логов агента.
    AGENT_LOG_TOKEN: str = ""
    # Имя виртуального источника логов агента в списке дашборда.
    AGENT_LOG_SERVICE: str = "telegram-agent"

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()

def get_db_url():
    return (f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}@"
            f"{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")