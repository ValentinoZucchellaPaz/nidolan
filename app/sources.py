from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from app.auth import User, current_user
from app.config import Settings
from app.views import describe_entry, render

router = APIRouter(tags=["sources"], dependencies=[Depends(current_user)])


def configured_sources(settings: Settings) -> list[dict]:
    if settings.sources_file is None:
        return [{"id": "facultad", "name": "Facultad", "path": str(settings.library_dir)}]
    try:
        data = json.loads(settings.sources_file.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("La configuración debe ser una lista.")
        seen = set()
        for source in data:
            if not isinstance(source, dict) or not isinstance(source.get("id"), str) or not re.fullmatch(r"[a-z0-9-]+", source["id"]):
                raise ValueError("Identificador de ubicación inválido.")
            if source["id"] in seen or not isinstance(source.get("name"), str) or not source["name"].strip():
                raise ValueError("Nombre o identificador de ubicación duplicado/inválido.")
            if not isinstance(source.get("path"), str) or not Path(source["path"]).is_absolute():
                raise ValueError("Cada ubicación necesita una ruta absoluta dentro del contenedor.")
            seen.add(source["id"])
        return data
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        raise RuntimeError(f"Configuración de ubicaciones inválida: {exc}") from exc


def source_by_id(settings: Settings, source_id: str) -> dict:
    for source in configured_sources(settings):
        if source["id"] == source_id:
            return source
    raise HTTPException(404, "Ubicación no encontrada.")


def source_status(source: dict) -> bool:
    try:
        return Path(source["path"]).is_dir()
    except OSError:
        return False


def resolved_source_path(source: dict, relative: str) -> Path:
    root = Path(source["path"]).resolve()
    if not root.is_dir():
        raise HTTPException(503, "Esta ubicación no está disponible. Revisá su montaje en Docker.")
    try:
        target = (root / relative).resolve(strict=True)
        target.relative_to(root)
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(404, "Elemento no encontrado en esta ubicación.") from None
    return target


@router.get("/sources/{source_id}")
def source_root(source_id: str, user: User):
    return RedirectResponse(f"/sources/{source_id}/", status_code=303)


@router.get("/sources/{source_id}/{relative:path}")
def browse_source(source_id: str, relative: str, request: Request, user: User, sort: str = "name"):
    source = source_by_id(request.app.state.settings, source_id)
    all_sources = configured_sources(request.app.state.settings)
    if not source_status(source):
        if relative:
            raise HTTPException(503, "Esta ubicación no está disponible.")
        return render(request, "browser.html", title=source["name"], sources=all_sources, active=source_id,
                      entries=[], crumbs=[], parent_url="/", current_url=f"/sources/{source_id}/",
                      offline=True, managed=False, sort=sort, folders=[])
    current = resolved_source_path(source, relative)
    if not current.is_dir():
        raise HTTPException(404, "Abrí la carpeta o descargá el archivo.")
    try:
        root = Path(source["path"]).resolve()
        items = []
        for item in current.iterdir():
            try:
                item.resolve(strict=True).relative_to(root)
                item.stat()
            except (OSError, ValueError, RuntimeError):
                continue
            items.append(item)
        if sort == "date":
            items.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        else:
            items.sort(key=lambda x: (not x.is_dir(), x.name.casefold()))
        entries = []
        for item in items:
            try:
                resolved = item.resolve(strict=True)
                resolved.relative_to(root)
                info = item.stat()
            except (OSError, ValueError, RuntimeError):
                continue
            path = (Path(relative) / item.name).as_posix() if relative else item.name
            url = f"/sources/{source_id}/{quote(path, safe='/')}"
            entries.append(describe_entry(item.name, item.is_dir(), 0 if item.is_dir() else info.st_size,
                                          url if item.is_dir() else f"/source-download/{source_id}/{quote(path, safe='/')}",
                                          info.st_mtime))
    except OSError as exc:
        raise HTTPException(503, "No se pudo leer esta carpeta.") from exc
    parts = Path(relative).parts if relative else ()
    crumbs = [{"name": source["name"], "url": f"/sources/{source_id}/"}]
    for index, part in enumerate(parts):
        crumbs.append({"name": part, "url": f"/sources/{source_id}/{quote('/'.join(parts[:index + 1]), safe='/')}"})
    parent_url = crumbs[-2]["url"] if len(crumbs) > 1 else "/"
    current_url = crumbs[-1]["url"]
    return render(request, "browser.html", title=crumbs[-1]["name"], sources=all_sources,
                  active=source_id, entries=entries, crumbs=crumbs, parent_url=parent_url,
                  current_url=current_url, offline=False, managed=False, sort=sort, folders=[])


@router.get("/source-download/{source_id}/{relative:path}")
def download_source(source_id: str, relative: str, request: Request, user: User):
    source = source_by_id(request.app.state.settings, source_id)
    path = resolved_source_path(source, relative)
    if not path.is_file():
        raise HTTPException(404, "Archivo no encontrado.")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@router.get("/facultad")
@router.get("/facultad/{relative:path}")
def old_faculty(relative: str = "", user: User = None):
    return RedirectResponse(f"/sources/facultad/{quote(relative, safe='/')}", status_code=303)


@router.get("/facultad-descarga/{relative:path}")
def old_faculty_download(relative: str, user: User):
    return RedirectResponse(f"/source-download/facultad/{quote(relative, safe='/')}", status_code=303)
