from __future__ import annotations

import base64
import hashlib
import html
import os
import secrets
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    session_secret: str
    data_dir: Path
    state_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        required = ("ADMIN_USERNAME", "ADMIN_PASSWORD", "SESSION_SECRET")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError(
                "Faltan variables requeridas: " + ", ".join(missing) + ". Revise .env.example."
            )

        secret = os.environ["SESSION_SECRET"]
        if len(secret) < 32:
            raise RuntimeError("SESSION_SECRET debe tener al menos 32 caracteres aleatorios.")

        return cls(
            username=os.environ["ADMIN_USERNAME"].strip(),
            password=os.environ["ADMIN_PASSWORD"],
            session_secret=secret,
            data_dir=Path(os.environ.get("DATA_DIR", "/data")),
            state_dir=Path(os.environ.get("STATE_DIR", "/var/lib/selfdrive")),
        )


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Return a portable salted scrypt hash; plaintext passwords never reach SQLite."""
    actual_salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=actual_salt, n=2**14, r=8, p=1)
    return "scrypt$16384$8$1${}${}".format(
        base64.b64encode(actual_salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_b64, digest_b64 = encoded.split("$")
        if algorithm != "scrypt":
            return False
        expected = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
        )
        return secrets.compare_digest(expected, base64.b64decode(digest_b64))
    except (TypeError, ValueError):
        return False


def database_connection(settings: Settings) -> sqlite3.Connection:
    connection = sqlite3.connect(settings.state_dir / "selfdrive.sqlite3")
    connection.row_factory = sqlite3.Row
    return connection


def setup_storage(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    with database_connection(settings) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                storage_name TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                created_at TEXT NOT NULL
            );
            """
        )
        existing = db.execute("SELECT id FROM users WHERE username = ?", (settings.username,)).fetchone()
        if existing is None:
            db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (settings.username, hash_password(settings.password)),
            )


def is_authenticated(request: Request) -> bool:
    return request.session.get("username") is not None


def require_login(request: Request) -> RedirectResponse | None:
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    return None


def format_size(size: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def page(title: str, body: str) -> HTMLResponse:
    document = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} · Mi Drive</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; color: #172033; background: #f4f7fb; }}
    body {{ margin: 0; }} main {{ width: min(920px, calc(100% - 2rem)); margin: 3rem auto; }}
    .card {{ background: white; border-radius: 12px; box-shadow: 0 2px 12px #17203318; padding: clamp(1.25rem, 4vw, 2rem); }}
    header {{ display: flex; gap: 1rem; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }}
    h1 {{ margin: 0; font-size: clamp(1.5rem, 4vw, 2rem); }}
    form {{ display: flex; gap: .75rem; flex-wrap: wrap; align-items: center; }}
    input {{ font: inherit; padding: .65rem; border: 1px solid #b8c3d8; border-radius: 7px; }}
    button, .button {{ background: #1769e0; border: 0; border-radius: 7px; color: white; cursor: pointer; font: inherit; padding: .65rem 1rem; text-decoration: none; }}
    button.secondary {{ background: #e7edf8; color: #172033; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 1.5rem; }} th, td {{ border-bottom: 1px solid #e5eaf2; padding: .8rem .4rem; text-align: left; }}
    td:last-child, th:last-child {{ text-align: right; }} .muted {{ color: #5f6d84; }} .error {{ background: #fff0f0; color: #9b1c1c; border-radius: 7px; padding: .75rem; }}
    @media (max-width: 540px) {{ table th:nth-child(3), table td:nth-child(3) {{ display: none; }} }}
  </style>
</head><body><main>{body}</main></body></html>"""
    return HTMLResponse(document)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    if not config.username:
        raise RuntimeError("ADMIN_USERNAME no puede estar vacío.")
    setup_storage(config)

    application = FastAPI(title="Mi Drive", docs_url=None, redoc_url=None)
    application.add_middleware(
        SessionMiddleware,
        secret_key=config.session_secret,
        same_site="lax",
        https_only=False,  # HTTP is intentional for the LAN-only MVP; enable HTTPS before remote access.
    )

    @application.get("/login", response_class=HTMLResponse, response_model=None)
    def login_form(request: Request, error: str | None = None) -> HTMLResponse | RedirectResponse:
        if is_authenticated(request):
            return RedirectResponse("/", status_code=303)
        message = '<p class="error">Usuario o contraseña incorrectos.</p>' if error else ""
        return page(
            "Ingresar",
            f"""<section class="card"><h1>Mi Drive</h1>{message}
            <p class="muted">Acceso privado de la red local.</p>
            <form method="post" action="/login">
              <input required autofocus name="username" autocomplete="username" placeholder="Usuario">
              <input required name="password" type="password" autocomplete="current-password" placeholder="Contraseña">
              <button type="submit">Ingresar</button>
            </form></section>""",
        )

    @application.post("/login")
    def login(request: Request, username: Annotated[str, Form()], password: Annotated[str, Form()]) -> RedirectResponse:
        with database_connection(config) as db:
            user = db.execute(
                "SELECT username, password_hash FROM users WHERE username = ?", (username.strip(),)
            ).fetchone()
        if user is None or not verify_password(password, user["password_hash"]):
            return RedirectResponse("/login?error=1", status_code=303)
        request.session.clear()
        request.session["username"] = user["username"]
        return RedirectResponse("/", status_code=303)

    @application.post("/logout")
    def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @application.get("/", response_class=HTMLResponse, response_model=None)
    def index(request: Request) -> HTMLResponse | RedirectResponse:
        redirect = require_login(request)
        if redirect:
            return redirect
        with database_connection(config) as db:
            files = db.execute(
                "SELECT id, original_name, size_bytes, created_at FROM files ORDER BY created_at DESC"
            ).fetchall()
        rows = "".join(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td><a class=\"button\" href=\"/files/{}/download\">Descargar</a></td></tr>".format(
                html.escape(item["original_name"]),
                html.escape(format_size(item["size_bytes"])),
                html.escape(item["created_at"]),
                html.escape(item["id"]),
            )
            for item in files
        ) or '<tr><td colspan="4" class="muted">Todavía no hay archivos.</td></tr>'
        return page(
            "Archivos",
            f"""<section class="card"><header><div><h1>Mis archivos</h1><p class="muted">Solo disponible en tu red local.</p></div>
            <form method="post" action="/logout"><button class="secondary">Salir</button></form></header>
            <form method="post" action="/files" enctype="multipart/form-data">
              <input required type="file" name="upload"><button type="submit">Subir archivo</button>
            </form>
            <table><thead><tr><th>Nombre</th><th>Tamaño</th><th>Subido</th><th></th></tr></thead><tbody>{rows}</tbody></table></section>""",
        )

    @application.post("/files")
    def upload_file(request: Request, upload: Annotated[UploadFile, File()]) -> RedirectResponse:
        redirect = require_login(request)
        if redirect:
            return redirect
        original_name = Path(upload.filename or "").name.strip()
        if not original_name or original_name in {".", ".."}:
            raise HTTPException(status_code=400, detail="Seleccione un archivo válido.")

        file_id = uuid.uuid4().hex
        storage_name = f"{file_id}.bin"
        final_path = config.data_dir / storage_name
        temporary_path = config.data_dir / f".{file_id}.uploading"
        size = 0
        try:
            with temporary_path.open("xb") as destination:
                while chunk := upload.file.read(1024 * 1024):
                    destination.write(chunk)
                    size += len(chunk)
            os.replace(temporary_path, final_path)
            created_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
            with database_connection(config) as db:
                db.execute(
                    "INSERT INTO files (id, original_name, storage_name, size_bytes, created_at) VALUES (?, ?, ?, ?, ?)",
                    (file_id, original_name, storage_name, size, created_at),
                )
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=507 if exc.errno == 28 else 500,
                detail="No se pudo guardar el archivo. Verifique el espacio y permisos del disco.",
            ) from exc
        finally:
            upload.file.close()
        return RedirectResponse("/", status_code=303)

    @application.get("/files/{file_id}/download", response_model=None)
    def download_file(file_id: str, request: Request) -> FileResponse | RedirectResponse:
        redirect = require_login(request)
        if redirect:
            return redirect
        with database_connection(config) as db:
            item = db.execute(
                "SELECT original_name, storage_name FROM files WHERE id = ?", (file_id,)
            ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="Archivo no encontrado.")
        path = config.data_dir / item["storage_name"]
        if not path.is_file():
            raise HTTPException(status_code=404, detail="El archivo ya no está en el disco.")
        return FileResponse(path, media_type="application/octet-stream", filename=item["original_name"])

    return application
