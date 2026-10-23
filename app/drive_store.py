from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import Settings
from app.db import database_connection, now


def valid_name(name: str) -> str:
    value = name.strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value or len(value) > 255:
        raise HTTPException(400, "Nombre inválido.")
    return value


def folder(db: sqlite3.Connection, folder_id: str | None):
    if not folder_id:
        return None
    row = db.execute("SELECT * FROM nodes WHERE id = ? AND kind = 'folder'", (folder_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Carpeta no encontrada.")
    return row


def node(db: sqlite3.Connection, node_id: str):
    row = db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Elemento no encontrado.")
    return row


def conflict(db: sqlite3.Connection, parent_id: str | None, name: str, exclude: str | None = None) -> None:
    row = db.execute(
        "SELECT id FROM nodes WHERE parent_id IS ? AND name = ? COLLATE NOCASE AND id != ?",
        (parent_id, name, exclude or ""),
    ).fetchone()
    if row:
        raise HTTPException(409, "Ya existe un elemento con ese nombre en la carpeta.")


def children(db: sqlite3.Connection, parent_id: str | None, sort: str):
    order = "updated_at DESC, name COLLATE NOCASE" if sort == "date" else "kind DESC, name COLLATE NOCASE"
    return db.execute(f"SELECT * FROM nodes WHERE parent_id IS ? ORDER BY {order}", (parent_id,)).fetchall()


def breadcrumbs(db: sqlite3.Connection, folder_id: str | None):
    result = []
    seen = set()
    while folder_id:
        if folder_id in seen:
            raise HTTPException(500, "Jerarquía de carpetas inválida.")
        seen.add(folder_id)
        item = folder(db, folder_id)
        result.append(item)
        folder_id = item["parent_id"]
    return list(reversed(result))


def all_folders(db: sqlite3.Connection):
    return db.execute("SELECT id, parent_id, name FROM nodes WHERE kind = 'folder' ORDER BY name COLLATE NOCASE").fetchall()


def create_folder(settings: Settings, parent_id: str | None, name: str):
    name = valid_name(name)
    with database_connection(settings) as db:
        db.execute("BEGIN IMMEDIATE")
        folder(db, parent_id)
        conflict(db, parent_id, name)
        db.execute(
            "INSERT INTO nodes (id,parent_id,name,kind,created_at,updated_at) VALUES (?,?,?,'folder',?,?)",
            (uuid.uuid4().hex, parent_id, name, now(), now()),
        )


def rename(settings: Settings, node_id: str, name: str):
    name = valid_name(name)
    with database_connection(settings) as db:
        db.execute("BEGIN IMMEDIATE")
        item = node(db, node_id)
        conflict(db, item["parent_id"], name, node_id)
        db.execute("UPDATE nodes SET name = ?, updated_at = ? WHERE id = ?", (name, now(), node_id))
        return item["parent_id"]


def move(settings: Settings, node_id: str, destination: str | None):
    with database_connection(settings) as db:
        db.execute("BEGIN IMMEDIATE")
        item = node(db, node_id)
        folder(db, destination)
        if destination == node_id:
            raise HTTPException(400, "No se puede mover una carpeta dentro de sí misma.")
        ancestor = destination
        while ancestor:
            if ancestor == node_id:
                raise HTTPException(400, "No se puede mover una carpeta dentro de una subcarpeta suya.")
            ancestor = folder(db, ancestor)["parent_id"]
        conflict(db, destination, item["name"], node_id)
        db.execute("UPDATE nodes SET parent_id = ?, updated_at = ? WHERE id = ?", (destination, now(), node_id))
        return item["parent_id"]


def save_upload(settings: Settings, parent_id: str | None, upload: UploadFile):
    name = valid_name(Path(upload.filename or "").name)
    file_id = uuid.uuid4().hex
    storage_name = f"{file_id}.bin"
    temporary = settings.data_dir / f".{file_id}.uploading"
    final = settings.data_dir / storage_name
    size = 0
    try:
        with temporary.open("xb") as destination:
            while chunk := upload.file.read(1024 * 1024):
                destination.write(chunk)
                size += len(chunk)
        with database_connection(settings) as db:
            db.execute("BEGIN IMMEDIATE")
            folder(db, parent_id)
            conflict(db, parent_id, name)
            os.replace(temporary, final)
            db.execute(
                "INSERT INTO nodes (id,parent_id,name,kind,storage_name,size_bytes,created_at,updated_at) VALUES (?,?,?,'file',?,?,?,?)",
                (file_id, parent_id, name, storage_name, size, now(), now()),
            )
    except OSError as exc:
        raise HTTPException(507 if exc.errno == 28 else 500, "No se pudo guardar el archivo. Revisá el espacio y los permisos del disco.") from exc
    finally:
        upload.file.close()
        temporary.unlink(missing_ok=True)
        with database_connection(settings) as db:
            exists = db.execute("SELECT id FROM nodes WHERE id = ?", (file_id,)).fetchone()
        if not exists:
            final.unlink(missing_ok=True)
    return parent_id
