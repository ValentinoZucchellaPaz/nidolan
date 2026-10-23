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
from urllib.parse import quote

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
    library_dir: Path = Path("/library")

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
            library_dir=Path(os.environ.get("LIBRARY_DIR", "/library")),
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


def reset_admin_password(settings: Settings) -> None:
    """Replace the only local account without touching stored files or metadata."""
    setup_storage(settings)
    with database_connection(settings) as db:
        db.execute("DELETE FROM users")
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (settings.username, hash_password(settings.password)),
        )


def library_root(settings: Settings) -> tuple[Path | None, str | None]:
    try:
        root = settings.library_dir.resolve()
    except OSError:
        return None, "No se pudo acceder a la carpeta vinculada."
    if not root.is_dir():
        return None, "La carpeta vinculada no está disponible."
    return root, None


def resolve_library_path(settings: Settings, relative_path: str) -> Path:
    root, error = library_root(settings)
    if error or root is None:
        raise HTTPException(status_code=503, detail=error or "Biblioteca no disponible.")
    try:
        candidate = (root / relative_path).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Ruta de biblioteca no encontrada.") from None
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="Ese elemento ya no existe en la biblioteca.")
    return candidate


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


def file_kind(name: str) -> str:
    extension = Path(name).suffix.lower()
    if extension in {".mp4", ".mkv", ".mov", ".avi", ".webm"}:
        return "VID"
    if extension in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}:
        return "IMG"
    if extension in {".zip", ".rar", ".7z", ".tar", ".gz"}:
        return "ZIP"
    if extension in {".pdf", ".txt", ".md", ".doc", ".docx"}:
        return "DOC"
    return "FILE"


def page(title: str, body: str, scripts: str = "") -> HTMLResponse:
    document = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} · Mi Drive</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; color: #edf4ff; background: #0b1224; }}
    * {{ box-sizing: border-box; }} body {{ min-height: 100vh; margin: 0; background: #0b1224; }}
    body::before {{ content: ""; position: fixed; inset: 0; pointer-events: none; opacity: .22; background-image: linear-gradient(#8fbaff12 1px, transparent 1px), linear-gradient(90deg, #8fbaff12 1px, transparent 1px); background-size: 32px 32px; mask-image: linear-gradient(to bottom, black, transparent 75%); }}
    main {{ position: relative; width: min(1100px, calc(100% - 2rem)); margin: clamp(1rem, 4vw, 3.5rem) auto; }} h1, h2, p {{ margin-top: 0; }} h1 {{ font-size: clamp(2rem, 5vw, 3.5rem); letter-spacing: -.055em; line-height: .96; }} h2 {{ font-size: 1rem; margin-bottom: .5rem; }}
    button, .button {{ appearance: none; border: 0; border-radius: .7rem; color: #091224; cursor: pointer; font: inherit; font-weight: 720; padding: .72rem 1rem; text-decoration: none; transition: transform .16s ease, background .16s ease; }} button:hover, .button:hover {{ transform: translateY(-1px); }} button:focus-visible, .button:focus-visible, input:focus-visible {{ outline: 3px solid #8fd5ff; outline-offset: 3px; }} .button, .primary {{ background: #a7e6ff; }} .quiet {{ background: #1d2c4d; color: #d9e6fb; }}
    .shell {{ background: #101a30e8; border: 1px solid #3b5280; box-shadow: 0 2rem 5rem #02071480; }} .topbar {{ align-items: center; border-radius: 1rem 1rem 0 0; display: flex; justify-content: space-between; padding: 1rem 1.25rem; }} .brand {{ align-items: center; display: flex; font-weight: 760; gap: .75rem; letter-spacing: -.025em; }} .brand-mark {{ align-items: center; background: #b9f3d4; border-radius: .55rem; color: #0e2330; display: grid; font-size: 1.2rem; height: 2rem; place-items: center; width: 2rem; }} .account {{ align-items: center; color: #b8c8e4; display: flex; gap: .65rem; }} .avatar {{ align-items: center; background: #355393; border: 1px solid #789be0; border-radius: 50%; color: white; display: grid; font-size: .8rem; font-weight: 800; height: 2rem; place-items: center; width: 2rem; }}
    .dashboard {{ border-radius: 0 0 1rem 1rem; padding: clamp(1.25rem, 4vw, 3rem); }} .hero {{ align-items: end; display: flex; gap: 1.5rem; justify-content: space-between; margin: 1.5rem 0 2.5rem; }} .hero p {{ color: #b8c8e4; font-size: 1.05rem; margin-bottom: 0; max-width: 34rem; }} .online {{ align-items: center; background: #153b3b; border: 1px solid #32756d; border-radius: 999px; color: #b9f3d4; display: inline-flex; font-size: .84rem; font-weight: 700; gap: .5rem; padding: .5rem .75rem; white-space: nowrap; }} .pulse {{ background: #9df7c9; border-radius: 50%; box-shadow: 0 0 0 .35rem #9df7c925; height: .5rem; width: .5rem; }}
    .metrics {{ display: grid; gap: .75rem; grid-template-columns: repeat(3, 1fr); margin-bottom: 1.5rem; }} .metric {{ background: #14213c; border: 1px solid #2d416a; border-radius: .8rem; padding: 1rem; }} .metric span {{ color: #9bb0d4; display: block; font-size: .82rem; margin-bottom: .3rem; }} .metric strong {{ font-size: 1.25rem; letter-spacing: -.03em; }}
    .library-gate {{ align-items: center; background: #132b31; border: 1px solid #32636b; border-radius: .8rem; display: flex; gap: 1rem; justify-content: space-between; margin-bottom: 1.5rem; padding: 1rem; }} .library-gate p {{ color: #b8d7dc; margin: .25rem 0 0; }} .library-gate .button {{ background: #b9f3d4; flex: none; }} .library-warning {{ background: #382b40; border-color: #785478; }} .library-warning p {{ color: #eed5f1; }}
    .upload-dock {{ align-items: center; background: linear-gradient(120deg, #1c335c, #142343); border: 1px dashed #8fbaff; border-radius: .9rem; display: grid; gap: 1rem; grid-template-columns: 1fr auto; margin: 1.5rem 0 2.5rem; padding: 1rem; transition: background .16s ease, border-color .16s ease; }} .upload-dock.dragging {{ background: #264a7c; border-color: #b9f3d4; }} .upload-copy {{ min-width: 0; }} .upload-copy p {{ color: #b8c8e4; margin: .25rem 0 0; }} .upload-dock form {{ align-items: center; display: flex; flex-wrap: wrap; gap: .75rem; justify-content: flex-end; }} .file-input {{ height: 1px; overflow: hidden; position: absolute; width: 1px; }} .choose-file {{ background: #263d68; border: 1px solid #5578ae; color: #e6efff; }} .selected-file {{ color: #b9f3d4; font-size: .88rem; max-width: 15rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }} .progress {{ background: #0b1428; border-radius: 999px; display: none; height: .45rem; overflow: hidden; width: 100%; }} .progress span {{ background: #b9f3d4; display: block; height: 100%; width: 0; }}
    .section-head {{ align-items: center; display: flex; gap: 1rem; justify-content: space-between; }} .section-head h2 {{ margin: 0; }} .search {{ background: #0d172d; border: 1px solid #31466f; border-radius: .65rem; color: #edf4ff; font: inherit; padding: .65rem .8rem; width: min(18rem, 55vw); }} .file-list {{ border-top: 1px solid #2d416a; margin-top: 1rem; }} .file-row {{ align-items: center; border-bottom: 1px solid #263959; display: grid; gap: .75rem; grid-template-columns: 3.2rem minmax(0, 1fr) 7rem 10rem auto; padding: .9rem .25rem; }} .file-type {{ background: #1e3156; border-radius: .55rem; color: #a7e6ff; font-size: .67rem; font-weight: 850; letter-spacing: .04em; padding: .55rem .25rem; text-align: center; }} .file-name {{ color: #f3f7ff; font-weight: 680; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }} .file-meta {{ color: #9bb0d4; font-size: .86rem; }} .download {{ background: transparent; border: 1px solid #46608f; color: #dce9ff; font-size: .88rem; padding: .5rem .7rem; }} .empty {{ border: 1px dashed #3e5683; border-radius: .8rem; color: #aebfdb; margin-top: 1rem; padding: 3rem 1rem; text-align: center; }} .empty b {{ color: #edf4ff; display: block; font-size: 1.1rem; margin-bottom: .4rem; }}
    .login {{ margin: clamp(2rem, 10vh, 8rem) auto; max-width: 29rem; }} .login .shell {{ border-radius: 1rem; padding: clamp(1.5rem, 6vw, 3rem); }} .login h1 {{ margin: 1.5rem 0 .75rem; }} .login p {{ color: #b8c8e4; }} .field {{ display: grid; gap: .45rem; margin: 1.1rem 0; }} .field label {{ color: #c9d7ef; font-size: .9rem; font-weight: 650; }} .field input {{ background: #0b1428; border: 1px solid #3e5683; border-radius: .65rem; color: #f5f8ff; font: inherit; padding: .85rem; }} .login button {{ margin-top: .75rem; width: 100%; }} .error {{ background: #48263c; border: 1px solid #965171; border-radius: .65rem; color: #ffdbe8; padding: .8rem; }}
    [hidden] {{ display: none !important; }} @media (max-width: 720px) {{ .hero {{ align-items: start; flex-direction: column; }} .metrics {{ grid-template-columns: 1fr; }} .upload-dock {{ grid-template-columns: 1fr; }} .upload-dock form {{ justify-content: start; }} .file-row {{ grid-template-columns: 3.2rem minmax(0, 1fr) auto; }} .file-meta.date {{ display: none; }} .account .account-name {{ display: none; }} }} @media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ scroll-behavior: auto !important; transition-duration: 0.01ms !important; }} }}
  </style>
</head><body><main>{body}</main>{scripts}</body></html>"""
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
            f"""<section class="login"><div class="shell"><div class="brand"><span class="brand-mark">↗</span> Mi Drive</div>
            <h1>Tu servidor,<br>en casa.</h1><p>Entrá a tus archivos desde cualquier dispositivo de tu red local.</p>{message}
            <form method="post" action="/login">
              <div class="field"><label for="username">Usuario</label><input id="username" required autofocus name="username" autocomplete="username" placeholder="Tu usuario"></div>
              <div class="field"><label for="password">Contraseña</label><input id="password" required name="password" type="password" autocomplete="current-password" placeholder="Tu contraseña"></div>
              <button class="primary" type="submit">Abrir Mi Drive</button>
            </form></div></section>""",
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
        total_size = sum(item["size_bytes"] for item in files)
        _, library_error = library_root(config)
        library_card = (
            f"""<section class="library-gate"><div><h2>Facultad</h2><p>Carpeta vinculada: se lee desde tu PC, sin copiar archivos.</p></div><a class="button" href="/facultad">Abrir biblioteca</a></section>"""
            if library_error is None
            else f"""<section class="library-gate library-warning"><div><h2>Biblioteca no disponible</h2><p>{html.escape(library_error)} Mi Drive sigue funcionando normalmente.</p></div></section>"""
        )
        rows = "".join(
            "<article class=\"file-row\" data-file-name=\"{}\"><span class=\"file-type\">{}</span><div><div class=\"file-name\" title=\"{}\">{}</div><div class=\"file-meta mobile-date\">{}</div></div><span class=\"file-meta\">{}</span><span class=\"file-meta date\">{}</span><a class=\"button download\" href=\"/files/{}/download\">Descargar</a></article>".format(
                html.escape(item["original_name"].lower(), quote=True),
                file_kind(item["original_name"]),
                html.escape(item["original_name"], quote=True),
                html.escape(item["original_name"]),
                html.escape(item["created_at"]),
                html.escape(format_size(item["size_bytes"])),
                html.escape(item["created_at"]),
                html.escape(item["id"]),
            )
            for item in files
        ) or '<div class="empty"><b>El estante está vacío.</b>Soltá un archivo arriba para guardarlo en tu servidor.</div>'
        scripts = """<script>
          (() => {
            const form = document.querySelector('#upload-form');
            const input = document.querySelector('#file-input');
            const dock = document.querySelector('.upload-dock');
            const name = document.querySelector('#selected-file');
            const progress = document.querySelector('#upload-progress');
            const bar = progress?.querySelector('span');
            const search = document.querySelector('#file-search');
            const choose = file => { if (!file) return; name.textContent = file.name; name.hidden = false; };
            input?.addEventListener('change', () => choose(input.files[0]));
            ['dragenter', 'dragover'].forEach(event => dock?.addEventListener(event, item => { item.preventDefault(); dock.classList.add('dragging'); }));
            ['dragleave', 'drop'].forEach(event => dock?.addEventListener(event, item => { item.preventDefault(); dock.classList.remove('dragging'); }));
            dock?.addEventListener('drop', event => { if (event.dataTransfer.files.length) { input.files = event.dataTransfer.files; choose(input.files[0]); } });
            form?.addEventListener('submit', event => {
              if (!input.files.length || !window.XMLHttpRequest) return;
              event.preventDefault(); progress.style.display = 'block';
              const button = form.querySelector('button'); button.disabled = true; button.textContent = 'Subiendo…';
              const request = new XMLHttpRequest(); request.open('POST', '/files'); request.upload.onprogress = item => { if (item.lengthComputable) bar.style.width = `${Math.round(item.loaded / item.total * 100)}%`; };
              request.onload = () => { if (request.status >= 200 && request.status < 400) location.reload(); else { button.disabled = false; button.textContent = 'Reintentar'; } };
              request.onerror = () => { button.disabled = false; button.textContent = 'Reintentar'; }; request.send(new FormData(form));
            });
            search?.addEventListener('input', () => document.querySelectorAll('.file-row').forEach(row => { row.hidden = !row.dataset.fileName.includes(search.value.toLowerCase()); }));
          })();
        </script>"""
        return page(
            "Archivos",
            f"""<section class="shell topbar"><div class="brand"><span class="brand-mark">↗</span> Mi Drive</div><div class="account"><span class="account-name">{html.escape(request.session['username'])}</span><span class="avatar">{html.escape(request.session['username'][0].upper())}</span><form method="post" action="/logout"><button class="quiet" type="submit">Salir</button></form></div></section>
            <section class="shell dashboard"><div class="hero"><div><h1>Todo lo tuyo,<br>en tu red.</h1><p>Un estante privado para archivos, películas y proyectos. Sin salir de casa.</p></div><span class="online"><i class="pulse"></i>Servidor activo</span></div>
            <div class="metrics"><div class="metric"><span>Archivos guardados</span><strong>{len(files)}</strong></div><div class="metric"><span>Espacio ocupado</span><strong>{format_size(total_size)}</strong></div><div class="metric"><span>Acceso</span><strong>Solo LAN</strong></div></div>
            {library_card}
            <section class="upload-dock"><div class="upload-copy"><h2>Sumá algo al estante</h2><p>Arrastrá un archivo aquí o elegilo desde tu dispositivo.</p><span id="selected-file" class="selected-file" hidden></span></div><form id="upload-form" method="post" action="/files" enctype="multipart/form-data"><input id="file-input" class="file-input" required type="file" name="upload"><label class="button choose-file" for="file-input">Elegir archivo</label><button class="primary" type="submit">Subir</button></form><div id="upload-progress" class="progress" aria-label="Progreso de subida"><span></span></div></section>
            <div class="section-head"><h2>Biblioteca</h2><input id="file-search" class="search" type="search" placeholder="Buscar un archivo" aria-label="Buscar un archivo"></div><div class="file-list">{rows}</div></section>""",
            scripts,
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

    @application.get("/facultad")
    def faculty_root(request: Request) -> RedirectResponse:
        redirect = require_login(request)
        if redirect:
            return redirect
        return RedirectResponse("/facultad/", status_code=303)

    @application.get("/facultad/{relative_path:path}", response_class=HTMLResponse, response_model=None)
    def faculty_browser(relative_path: str, request: Request) -> HTMLResponse | RedirectResponse:
        redirect = require_login(request)
        if redirect:
            return redirect
        current = resolve_library_path(config, relative_path)
        if not current.is_dir():
            raise HTTPException(status_code=404, detail="Abra carpetas o descargue archivos desde la biblioteca.")
        try:
            entries = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        except OSError as exc:
            raise HTTPException(status_code=503, detail="No se pudo leer esta carpeta de la biblioteca.") from exc

        current_relative = current.relative_to(config.library_dir.resolve())
        back_link = ""
        if current_relative != Path("."):
            parent = current_relative.parent
            back_link = f'<a class="button quiet" href="/facultad/{quote(parent.as_posix(), safe="/")}">Volver</a>'
        rows = []
        for entry in entries:
            relative = current_relative / entry.name
            relative_url = quote(relative.as_posix(), safe="/")
            if entry.is_dir():
                action = f'<a class="button download" href="/facultad/{relative_url}">Abrir</a>'
                kind, details = "DIR", "Carpeta"
            else:
                try:
                    details = format_size(entry.stat().st_size)
                except OSError:
                    details = "No disponible"
                kind = file_kind(entry.name)
                action = f'<a class="button download" href="/facultad-descarga/{relative_url}">Descargar</a>'
            rows.append(
                "<article class=\"file-row\"><span class=\"file-type\">{}</span><div class=\"file-name\" title=\"{}\">{}</div><span class=\"file-meta\">{}</span><span class=\"file-meta date\">Solo lectura</span>{}</article>".format(
                    kind,
                    html.escape(entry.name, quote=True),
                    html.escape(entry.name),
                    html.escape(details),
                    action,
                )
            )
        display_path = "Facultad" if current_relative == Path(".") else f"Facultad / {current_relative.as_posix()}"
        contents = "".join(rows) or '<div class="empty"><b>Esta carpeta está vacía.</b>No hay elementos para mostrar.</div>'
        return page(
            "Facultad",
            f"""<section class="shell topbar"><div class="brand"><span class="brand-mark">↗</span> Mi Drive</div><div class="account"><a class="button quiet" href="/">Mis archivos</a><form method="post" action="/logout"><button class="quiet" type="submit">Salir</button></form></div></section>
            <section class="shell dashboard"><div class="hero"><div><h1>{html.escape(display_path)}</h1><p>Carpeta vinculada desde tu PC. Los archivos se leen en su ubicación original.</p></div><span class="online"><i class="pulse"></i>Solo lectura</span></div><div class="section-head"><h2>Contenido</h2>{back_link}</div><div class="file-list">{contents}</div></section>""",
        )

    @application.get("/facultad-descarga/{relative_path:path}", response_model=None)
    def faculty_download(relative_path: str, request: Request) -> FileResponse | RedirectResponse:
        redirect = require_login(request)
        if redirect:
            return redirect
        path = resolve_library_path(config, relative_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Ese archivo ya no está disponible.")
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    return application
