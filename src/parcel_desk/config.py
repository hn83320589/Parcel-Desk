from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """所有設定皆可用環境變數覆寫，前綴為 PARCEL_，例如 PARCEL_DATABASE_PATH。"""

    model_config = SettingsConfigDict(env_prefix="PARCEL_", env_file=".env", extra="ignore")

    database_path: Path = Path("data/parcel_desk.db")
    # `parcel-desk demo` 使用的示範資料庫，與正式資料庫分開，示範資料不會混入正式資料
    demo_database_path: Path = Path("data/demo.db")
    # 不提供預設值：未設定時由 resolve_jwt_secret 隨機產生並存到 jwt_secret_file
    jwt_secret: str | None = None
    jwt_expire_minutes: int = 12 * 60
    host: str = "0.0.0.0"
    port: int = 8000
    scheduler_enabled: bool = True
    reminder_interval_minutes: int = 10

    @property
    def jwt_secret_file(self) -> Path:
        # 每個資料庫各自一把密鑰：正式與示範資料庫放在同一目錄時，token 也不會互通
        return self.database_path.with_name(self.database_path.name + ".jwt_secret")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
