from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).parent
STATIC_DIR = BASE / "static"
templates = Jinja2Templates(directory=BASE / "templates")


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def icon_for(name: str, is_folder: bool) -> str:
    if is_folder:
        return "folder"
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}:
        return "image"
    if suffix in {".mp4", ".mkv", ".mov", ".avi", ".webm"}:
        return "video"
    return "file"


def describe_entry(name: str, is_folder: bool, size: int, url: str, modified: float | str, node_id: str | None = None):
    date = datetime.fromtimestamp(modified).strftime("%d/%m/%Y") if isinstance(modified, float) else modified[:10]
    return {"name": name, "kind": "folder" if is_folder else "file", "icon": icon_for(name, is_folder),
            "size": "—" if is_folder else format_size(size), "date": date, "url": url, "id": node_id}


def render(request: Request, template: str, **context) -> HTMLResponse:
    from app.sources import source_status
    context.setdefault("source_status", source_status)
    return templates.TemplateResponse(request, template, {"request": request, **context})
