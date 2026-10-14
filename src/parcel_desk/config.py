from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """所有設定皆可用環境變數覆寫，前綴為 PARCEL_，例如 PARCEL_DATABASE_PATH。"""

    model_config = SettingsConfigDict(env_prefix="PARCEL_", env_file=".env", extra="ignore")

    database_path: Path = Path("data/parcel_desk.db")
    jwt_secret: str = "dev-secret-change-me-in-production"
    jwt_expire_minutes: int = 12 * 60
    host: str = "0.0.0.0"
    port: int = 8000
    scheduler_enabled: bool = True
    reminder_interval_minutes: int = 10

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
