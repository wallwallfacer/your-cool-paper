"""Configuration loaded from environment / .env files."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    return Path(os.environ.get("PAPERS_COOL_DATA_DIR", str(Path.home() / ".papers-cool")))


_loaded = False


def _load_env() -> None:
    global _loaded
    if _loaded:
        return
    candidates = [
        _default_data_dir() / ".env",
        Path.cwd() / ".env",
    ]
    for p in candidates:
        if p.exists():
            load_dotenv(p, override=False)
    _loaded = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    openai_api_key: str = "sk-missing"
    openai_base_url: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_timeout: float = 120.0

    default_ai_lang: str = "zh"

    arxiv_categories: str = "cs.IR,cs.LG,cs.CL,cs.AI"

    host: str = "127.0.0.1"
    port: int = 8000

    disable_scheduler: bool = False

    # When BOTH are set, every route except /login + /api/auth requires the cookie.
    # Leave either blank for local-only "no password" mode.
    site_password: str = ""
    auth_secret: str = ""

    @property
    def data_dir(self) -> Path:
        return _default_data_dir()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db.sqlite"

    @property
    def pdf_cache_dir(self) -> Path:
        return self.data_dir / "pdf_cache"

    @property
    def categories(self) -> list[str]:
        return [c.strip() for c in self.arxiv_categories.split(",") if c.strip()]


def get_settings() -> Settings:
    _load_env()
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.pdf_cache_dir.mkdir(parents=True, exist_ok=True)
    return settings
