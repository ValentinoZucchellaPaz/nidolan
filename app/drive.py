from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from app.auth import User, current_user
from app.db import database_connection
from app.drive_store import all_folders, breadcrumbs, children, create_folder, folder, move, node, rename, save_upload
from app.sources import configured_sources, source_status
from app.views import describe_entry, render

router = APIRouter(tags=["drive"], dependencies=[Depends(current_user)])


def parent_id(value: str) -> str | None:
    return value or None


def location(folder_id: str | None) -> str:
    return f"/drive/{folder_id}" if folder_id else "/drive"


@router.get("/")
def home(request: Request, user: User):
    settings = request.app.state.settings
    with database_connection(settings) as db:
        recent = db.execute("SELECT * FROM nodes WHERE kind = 'file' ORDER BY created_at DESC LIMIT 8").fetchall()
    sources = configured_sources(settings)
    return render(request, "home.html", title="Inicio", active="home", sources=sources, recent=recent,
                  source_status=source_status, describe_entry=describe_entry)


@router.get("/drive")
@router.get("/drive/{folder_id}")
def browse_drive(request: Request, user: User, folder_id: str = "", sort: str = "name"):
    settings = request.app.state.settings
    current = parent_id(folder_id)
    with database_connection(settings) as db:
        folder(db, current)
        trail = breadcrumbs(db, current)
        rows = children(db, current, sort)
        folders = all_folders(db)
        destinations = [{"id": item["id"], "label": " / ".join(part["name"] for part in breadcrumbs(db, item["id"]))} for item in folders]
    crumbs = [{"name": "Mi Drive", "url": "/drive"}] + [{"name": item["name"], "url": location(item["id"])} for item in trail]
    entries = [describe_entry(item["name"], item["kind"] == "folder", item["size_bytes"],
                              location(item["id"]) if item["kind"] == "folder" else f"/files/{item['id']}/download",
                              item["updated_at"], item["id"]) for item in rows]
    return render(request, "browser.html", title=crumbs[-1]["name"], sources=configured_sources(settings),
                  active="drive", entries=entries, crumbs=crumbs, parent_url=crumbs[-2]["url"] if len(crumbs) > 1 else "/",
                  current_url=location(current), offline=False, managed=True, sort=sort, folders=destinations,
                  folder_id=current or "")


@router.post("/folders")
def add_folder(request: Request, user: User, name: Annotated[str, Form()], parent: Annotated[str, Form()] = ""):
    create_folder(request.app.state.settings, parent_id(parent), name)
    return RedirectResponse(location(parent_id(parent)), status_code=303)


@router.post("/nodes/{node_id}/rename")
def rename_node(node_id: str, request: Request, user: User, name: Annotated[str, Form()]):
    previous = rename(request.app.state.settings, node_id, name)
    return RedirectResponse(location(previous), status_code=303)


@router.post("/nodes/{node_id}/move")
def move_node(node_id: str, request: Request, user: User, destination: Annotated[str, Form()] = ""):
    previous = move(request.app.state.settings, node_id, parent_id(destination))
    return RedirectResponse(location(previous), status_code=303)


@router.post("/files")
def upload_file(request: Request, user: User, upload: Annotated[UploadFile, File()], parent: Annotated[str, Form()] = ""):
    save_upload(request.app.state.settings, parent_id(parent), upload)
    return RedirectResponse(location(parent_id(parent)), status_code=303)


@router.get("/files/{file_id}/download")
def download_file(file_id: str, request: Request, user: User):
    settings = request.app.state.settings
    with database_connection(settings) as db:
        item = node(db, file_id)
    if item["kind"] != "file":
        raise HTTPException(404, "Archivo no encontrado.")
    path = settings.data_dir / item["storage_name"]
    if not path.is_file():
        raise HTTPException(404, "El archivo ya no está en el disco.")
    return FileResponse(path, media_type="application/octet-stream", filename=item["name"])
