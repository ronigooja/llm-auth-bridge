"""Side-effect-free runtime configuration."""

from dataclasses import dataclass, field
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(
        default_factory=lambda: Path(os.getenv("LLM_AUTH_DB", "data/app.sqlite3"))
    )
    key_file: Path = field(
        default_factory=lambda: Path(
            os.getenv("LLM_AUTH_MASTER_KEY_FILE", ".secrets/master_key")
        )
    )
    secure_cookie: bool = field(
        default_factory=lambda: (
            os.getenv("LLM_AUTH_SECURE_COOKIE", "true").lower() == "true"
        )
    )
    session_seconds: int = 43200
    lease_seconds: int = 45
    task_seconds: int = 600
    human_seconds: int = 1800
    lock_file: Path | None = None
    takeover_url: str = field(
        default_factory=lambda: os.getenv(
            "LLM_AUTH_TAKEOVER_URL", "ws://worker:6080/websockify"
        )
    )
    static_dir: Path = field(
        default_factory=lambda: Path(os.getenv("LLM_AUTH_STATIC_DIR", "frontend/dist"))
    )

    @property
    def browser_lock(self):
        return self.lock_file or Path(
            os.getenv("LLM_AUTH_LOCK_FILE", str(self.db_path.parent / "browser.lock"))
        )


DB_PATH = Settings().db_path
MASTER_KEY_FILE = Settings().key_file
