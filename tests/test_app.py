from pathlib import Path

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
    assert client.get("/facultad-descarga/%2E%2E/secret", follow_redirects=False).status_code == 404


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
    assert "Biblioteca no disponible" in client.get("/").text
    assert client.get("/facultad/", follow_redirects=False).status_code == 503
