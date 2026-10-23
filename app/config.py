from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    session_secret: str
    data_dir: Path
    state_dir: Path
    library_dir: Path = Path("/library")
    sources_file: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        required = ("ADMIN_USERNAME", "ADMIN_PASSWORD", "SESSION_SECRET")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError("Faltan variables requeridas: " + ", ".join(missing) + ". Revise .env.example.")
        secret = os.environ["SESSION_SECRET"]
        if len(secret) < 32:
            raise RuntimeError("SESSION_SECRET debe tener al menos 32 caracteres aleatorios.")
        return cls(
            username=os.environ["ADMIN_USERNAME"].strip(),
            password=os.environ["ADMIN_PASSWORD"],
            session_secret=secret,
            data_dir=Path(os.environ.get("DATA_DIR", "/data")),
            state_dir=Path(os.environ.get("STATE_DIR", "/var/lib/selfdrive")),
            library_dir=Path(os.environ.get("LIBRARY_DIR", "/library")),
            sources_file=Path(os.environ["SOURCES_FILE"]) if os.environ.get("SOURCES_FILE") else None,
        )
