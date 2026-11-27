"""Web settings from the environment (12-factor). Secrets live only in the server environment."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass
class WebConfig:
    data_dir: Path = field(default_factory=lambda: Path(_env("CERTIFLOW_DATA_DIR", "data")))
    database_url: str = field(default_factory=lambda: _env("CERTIFLOW_DATABASE_URL", "") or "")
    library: Path = field(default_factory=lambda: Path(_env("CERTIFLOW_LIBRARY", "assets/shoreline/library.json")))
    secret_key: str = field(default_factory=lambda: _env("CERTIFLOW_SECRET_KEY") or "")
    queue: str = field(default_factory=lambda: _env("CERTIFLOW_QUEUE", "thread"))          # thread | celery
    redis_url: str = field(default_factory=lambda: _env("CERTIFLOW_REDIS_URL", "redis://localhost:6379/0"))
    llm: str = field(default_factory=lambda: _env("CERTIFLOW_LLM", "anthropic"))            # anthropic | mock
    checkpoint_dsn: str = field(default_factory=lambda: _env("CERTIFLOW_CHECKPOINT_DSN", "") or "")
    secure_cookies: bool = field(default_factory=lambda: _env("CERTIFLOW_SECURE_COOKIES", "0") == "1")
    session_hours: int = field(default_factory=lambda: int(_env("CERTIFLOW_SESSION_HOURS", "12")))
    max_upload_mb: int = field(default_factory=lambda: int(_env("CERTIFLOW_MAX_UPLOAD_MB", "80")))
    static_dir: Path = field(default_factory=lambda: Path(_env("CERTIFLOW_STATIC_DIR", "web/dist")))

    def __post_init__(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_url = f"sqlite:///{(self.data_dir / 'certiflow.db').resolve()}"
        if not self.secret_key:
            # dev fallback: a per-install key kept in the data dir (production sets CERTIFLOW_SECRET_KEY)
            kf = self.data_dir / ".secret_key"
            if not kf.exists():
                kf.write_text(secrets.token_hex(32))
                kf.chmod(0o600)
            self.secret_key = kf.read_text().strip()

    @property
    def jobs_dir(self) -> Path:
        p = self.data_dir / "jobs"
        p.mkdir(parents=True, exist_ok=True)
        return p


_config: WebConfig | None = None


def get_config() -> WebConfig:
    global _config
    if _config is None:
        _config = WebConfig()
    return _config


def set_config(cfg: WebConfig) -> None:
    global _config
    _config = cfg
