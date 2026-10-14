from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """所有設定皆可用環境變數覆寫，前綴為 PARCEL_，例如 PARCEL_DATABASE_PATH。"""

    model_config = SettingsConfigDict(env_prefix="PARCEL_", env_file=".env", extra="ignore")

    database_path: Path = Path("data/parcel_desk.db")
    # 不提供預設值：未設定時由 resolve_jwt_secret 隨機產生並存到 jwt_secret_file
    jwt_secret: str | None = None
    jwt_expire_minutes: int = 12 * 60
    host: str = "0.0.0.0"
    port: int = 8000
    scheduler_enabled: bool = True
    reminder_interval_minutes: int = 10

    @property
    def jwt_secret_file(self) -> Path:
        return self.database_path.parent / ".jwt_secret"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
