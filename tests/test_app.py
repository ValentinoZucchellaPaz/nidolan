from pathlib import Path
import json
import sqlite3

from fastapi.testclient import TestClient

from app.main import Settings, create_app, reset_admin_password


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(
        Settings(
            username="admin",
            password="correct horse battery staple",
            session_secret="a" * 32,
            data_dir=tmp_path / "data",
            state_dir=tmp_path / "state",
        )
    )
    return TestClient(app)


def login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "correct horse battery staple"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_files_require_a_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/files/not-real/download", follow_redirects=False).headers["location"] == "/login"


def test_login_rejects_bad_password_and_allows_valid_one(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    failed = client.post("/login", data={"username": "admin", "password": "bad"}, follow_redirects=False)
    assert failed.headers["location"] == "/login?error=1"
    login(client)
    assert client.get("/").status_code == 200
    client.post("/logout")
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"


def test_reset_password_uses_the_current_environment_password(tmp_path: Path) -> None:
    make_client(tmp_path)
    replacement = Settings(
        username="nuevo-admin",
        password="new correct horse battery staple",
        session_secret="b" * 32,
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
    )
    reset_admin_password(replacement)
    changed = TestClient(create_app(replacement))
    rejected = changed.post(
        "/login", data={"username": "admin", "password": "correct horse battery staple"}, follow_redirects=False
    )
    assert rejected.headers["location"] == "/login?error=1"
    accepted = changed.post(
        "/login", data={"username": "nuevo-admin", "password": replacement.password}, follow_redirects=False
    )
    assert accepted.status_code == 303


def test_upload_lists_and_downloads_a_utf8_filename(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)
    contents = b"contenido binario\x00\xff"
    uploaded = client.post(
        "/files",
        files={"upload": ("informe final ñ.txt", contents, "text/plain")},
        follow_redirects=False,
    )
    assert uploaded.status_code == 303
    home = client.get("/")
    assert "informe final ñ.txt" in home.text
    assert list((tmp_path / "data").glob("*.bin"))
    download_url = home.text.split('/files/')[1].split('/download')[0]
    downloaded = client.get(f"/files/{download_url}/download")
    assert downloaded.content == contents


def test_linked_library_browses_without_copying_and_blocks_escaping_its_root(tmp_path: Path) -> None:
    library = tmp_path / "facultad"
    subject = library / "Redes"
    subject.mkdir(parents=True)
    notes = subject / "apuntes.txt"
    notes.write_text("apuntes de red", encoding="utf-8")
    settings = Settings(
        username="admin",
        password="correct horse battery staple",
        session_secret="c" * 32,
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
        library_dir=library,
    )
    client = TestClient(create_app(settings))
    login(client)
    root = client.get("/facultad/")
    assert "Redes" in root.text
    nested = client.get("/facultad/Redes")
    assert "apuntes.txt" in nested.text
    downloaded = client.get("/facultad-descarga/Redes/apuntes.txt")
    assert downloaded.content == b"apuntes de red"
    assert list((tmp_path / "data").glob("*.bin")) == []
    assert client.get("/source-download/facultad/%2E%2E/secret", follow_redirects=False).status_code == 404


def test_missing_linked_library_does_not_break_the_personal_drive(tmp_path: Path) -> None:
    settings = Settings(
        username="admin",
        password="correct horse battery staple",
        session_secret="d" * 32,
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
        library_dir=tmp_path / "disco-desconectado",
    )
    client = TestClient(create_app(settings))
    login(client)
    assert "No disponible" in client.get("/").text
    assert "Esta ubicación no está disponible" in client.get("/sources/facultad/").text


def test_folders_rename_move_and_prevent_cycles(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)
    assert client.post("/folders", data={"name": "Facu", "parent": ""}, follow_redirects=False).status_code == 303
    assert client.post("/folders", data={"name": "Pelis", "parent": ""}, follow_redirects=False).status_code == 303
    with sqlite3.connect(tmp_path / "state" / "selfdrive.sqlite3") as db:
        facu, pelis = db.execute("SELECT id FROM nodes WHERE kind='folder' ORDER BY name").fetchall()
    facu_id, pelis_id = facu[0], pelis[0]
    assert client.post("/files", data={"parent": facu_id}, files={"upload": ("clase.pdf", b"PDF", "application/pdf")}).status_code == 200
    assert "clase.pdf" in client.get(f"/drive/{facu_id}").text
    with sqlite3.connect(tmp_path / "state" / "selfdrive.sqlite3") as db:
        file_id = db.execute("SELECT id FROM nodes WHERE name='clase.pdf'").fetchone()[0]
    assert client.post(f"/nodes/{file_id}/rename", data={"name": "clase final.pdf"}, follow_redirects=False).status_code == 303
    assert client.post(f"/nodes/{file_id}/move", data={"destination": pelis_id}, follow_redirects=False).status_code == 303
    assert "clase final.pdf" in client.get(f"/drive/{pelis_id}").text
    assert client.post(f"/nodes/{facu_id}/move", data={"destination": facu_id}).status_code == 400


def test_legacy_files_migrate_once_without_losing_blob_or_login(tmp_path: Path) -> None:
    from app.db import hash_password
    state, data = tmp_path / "state", tmp_path / "data"
    state.mkdir(); data.mkdir()
    (data / "legacy.bin").write_bytes(b"old")
    with sqlite3.connect(state / "selfdrive.sqlite3") as db:
        db.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL);"
                         "CREATE TABLE files(id TEXT PRIMARY KEY, original_name TEXT NOT NULL, storage_name TEXT UNIQUE NOT NULL, size_bytes INTEGER NOT NULL, created_at TEXT NOT NULL);")
        db.execute("INSERT INTO users(username,password_hash) VALUES (?,?)", ("admin", hash_password("correct horse battery staple")))
        db.execute("INSERT INTO files VALUES (?,?,?,?,?)", ("legacy", "viejo.pdf", "legacy.bin", 3, "2024-01-01 00:00 UTC"))
    client = make_client(tmp_path)
    login(client)
    assert client.get("/files/legacy/download").content == b"old"
    assert "viejo.pdf" in client.get("/drive").text
    make_client(tmp_path)
    with sqlite3.connect(state / "selfdrive.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM nodes WHERE id='legacy'").fetchone()[0] == 1
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_multiple_sources_and_symlink_escape(tmp_path: Path) -> None:
    faculty = tmp_path / "faculty"; movies = tmp_path / "movies"
    faculty.mkdir(); movies.mkdir()
    (movies / "film.mkv").write_bytes(b"movie")
    (movies / "escape").symlink_to(tmp_path / "outside.txt")
    (tmp_path / "outside.txt").write_text("private")
    config = tmp_path / "sources.json"
    config.write_text(json.dumps([{"id": "facultad", "name": "Facultad", "path": str(faculty)},
                                  {"id": "peliculas", "name": "Películas", "path": str(movies)}]))
    client = TestClient(create_app(Settings("admin", "correct horse battery staple", "z" * 32,
                                           tmp_path / "data", tmp_path / "state", faculty, config)))
    login(client)
    assert "Películas" in client.get("/").text
    assert "film.mkv" in client.get("/sources/peliculas/").text
    assert client.get("/source-download/peliculas/film.mkv").content == b"movie"
    assert client.get("/source-download/peliculas/escape").status_code == 404
    assert not list((tmp_path / "data").glob("*.bin"))
