"""Пароли, сессии, права доступа, защита входа от перебора."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from functools import wraps
from typing import Callable

from flask import abort, flash, g, redirect, request, session, url_for

from . import db

ROLE_TITLES = {
    "student": "Студент",
    "teacher": "Преподаватель",
    "methodist": "Методист",
    "admin": "Администратор",
}

_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < 6:
        return "Пароль должен быть не короче 6 символов."
    return None


# --- защита от перебора пароля (в памяти процесса) --------------------------
_FAILS: dict[str, list[float]] = {}
MAX_FAILS = 5
WINDOW_SEC = 300


def login_blocked(login: str) -> bool:
    stamps = [t for t in _FAILS.get(login, []) if time.time() - t < WINDOW_SEC]
    _FAILS[login] = stamps
    return len(stamps) >= MAX_FAILS


def register_fail(login: str) -> None:
    _FAILS.setdefault(login, []).append(time.time())


def clear_fails(login: str) -> None:
    _FAILS.pop(login, None)


# --- текущий пользователь и права -------------------------------------------
def load_user() -> None:
    g.user = None
    uid = session.get("uid")
    if uid:
        row = db.one(g.db, "SELECT * FROM users WHERE id=? AND is_active=1", (uid,))
        if row is None:
            session.clear()
        g.user = row


def role_home(role: str) -> str:
    return url_for({
        "student": "student.home",
        "teacher": "teacher.home",
        "methodist": "methodist.home",
        "admin": "admin.home",
    }[role])


def login_required(*roles: str) -> Callable:
    """Доступ только для указанных ролей (без аргументов — любому вошедшему)."""

    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*a, **kw):
            if g.user is None:
                return redirect(url_for("auth.login", next=request.path))
            if g.user["must_change"] and request.endpoint not in ("auth.password", "auth.logout"):
                flash("Для продолжения смените временный пароль.", "warn")
                return redirect(url_for("auth.password"))
            if roles and g.user["role"] not in roles:
                abort(403)
            return fn(*a, **kw)

        return wrapper

    return deco
