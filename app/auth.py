from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import database_connection, verify_password
from app.views import render

router = APIRouter(tags=["auth"])


def current_user(request: Request) -> str:
    username = request.session.get("username")
    if not username:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return username


User = Annotated[str, Depends(current_user)]


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str | None = None):
    if request.session.get("username"):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", error=bool(error))


@router.post("/login")
def login(request: Request, username: Annotated[str, Form()], password: Annotated[str, Form()]):
    with database_connection(request.app.state.settings) as db:
        user = db.execute("SELECT username, password_hash FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if user is None or not verify_password(password, user["password_hash"]):
        return RedirectResponse("/login?error=1", status_code=303)
    request.session.clear()
    request.session["username"] = user["username"]
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
