from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SRE_", env_file=".env", extra="ignore")

    env_name: str = "local-docker"
    api_port: int = 8080
    database_url: str = "postgresql+asyncpg://sre:sre@localhost:5433/sre"

    config_dir: Path = Path("../config")
    models_profile: str = "local"  # local | airgap | fake
    fake_script_dir: Path | None = None  # overrides models.fake.yaml script_dir

    holmes_url: str = "http://holmes:5050"

    grafana_url: str | None = None
    grafana_sa_token: str | None = None
    grafana_prom_ds_uid: str | None = None
    grafana_loki_ds_uid: str | None = None
    grafana_webhook_secret: str | None = None
    grafana_poll_interval_s: int = 30
    grafana_poll_enabled: bool = False

    telegram_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_allowed_user_ids: list[int] = []

    github_token: str | None = None
    github_webhook_secret: str | None = None
    gitlab_token: str | None = None
    gitlab_webhook_secret: str | None = None
    gitlab_base_url: str = "https://gitlab.com"
    scm_poll_enabled: bool = False
    scm_poll_interval_s: int = 60
    scm_draft_mr: bool = False

    chat_thread_daily_usd_cap: float = 1.00

    @property
    def models_config_path(self) -> Path:
        name = "models.fake.yaml" if self.models_profile == "fake" else "models.yaml"
        return self.config_dir / name


@lru_cache
def get_settings() -> Settings:
    return Settings()
