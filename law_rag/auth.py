# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import hmac
import random
import re
import secrets
import sqlite3
import threading
import time
import uuid

from law_rag.store import conn

_lock = threading.Lock()
_captchas: dict[str, tuple[str, float]] = {}
CAPTCHA_TTL = 120
CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
USER_RE = re.compile(r"^[\w\u4e00-\u9fff-]{3,20}$")


def init_users() -> None:
    from law_rag.store import init_db

    init_db()


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"{salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    check = _hash_password(password, salt)
    return hmac.compare_digest(check, stored)


def validate_username(username: str) -> str:
    name = (username or "").strip()
    if not USER_RE.fullmatch(name):
        raise ValueError("用户名需为 3–20 个字，可用汉字、字母、数字和下划线")
    return name


def validate_password(password: str) -> str:
    if not password or len(password) < 6 or len(password) > 64:
        raise ValueError("密码至少 6 位，最多 64 位")
    return password


def create_user(username: str, password: str, is_admin: bool = False) -> None:
    with conn() as con:
        try:
            con.execute(
                "INSERT INTO users (username, password_hash, created_at, is_admin) VALUES (?, ?, ?, ?)",
                (username, _hash_password(password), time.time(), 1 if is_admin else 0),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("该用户名已被注册") from exc


def authenticate(username: str, password: str) -> bool:
    with conn() as con:
        row = con.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
    return bool(row) and _verify_password(password, row["password_hash"])


def get_user(username: str) -> dict | None:
    with conn() as con:
        row = con.execute(
            "SELECT username, is_admin, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def user_exists(username: str) -> bool:
    with conn() as con:
        row = con.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    return row is not None


def _purge_captcha() -> None:
    now = time.time()
    dead = [k for k, (_, exp) in _captchas.items() if exp < now]
    for k in dead:
        _captchas.pop(k, None)


def make_captcha() -> tuple[str, str]:
    code = "".join(random.choice(CHARS) for _ in range(4))
    cid = uuid.uuid4().hex
    with _lock:
        _purge_captcha()
        _captchas[cid] = (code, time.time() + CAPTCHA_TTL)
    parts = []
    for i, ch in enumerate(code):
        x = 18 + i * 28
        y = random.randint(28, 42)
        rot = random.randint(-18, 18)
        fill = random.choice(["#1b3d48", "#b23a2f", "#7a4a1d", "#245260"])
        parts.append(
            f'<text x="{x}" y="{y}" fill="{fill}" transform="rotate({rot} {x} {y})" '
            f'font-size="28" font-family="Georgia, serif" font-weight="700">{ch}</text>'
        )
    noise = []
    for _ in range(5):
        x1, y1 = random.randint(0, 130), random.randint(0, 50)
        x2, y2 = random.randint(0, 130), random.randint(0, 50)
        noise.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="#d8cbb3" stroke-width="1"/>'
        )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="140" height="52" '
        'role="img" aria-label="验证码">'
        '<rect width="140" height="52" fill="#fffaf1"/>'
        + "".join(noise)
        + "".join(parts)
        + "</svg>"
    )
    return cid, svg


def verify_captcha(captcha_id: str, code: str) -> bool:
    if not captcha_id or not code:
        return False
    with _lock:
        item = _captchas.pop(captcha_id, None)
    if not item:
        return False
    real, exp = item
    if time.time() > exp:
        return False
    guess = code.strip().lower()
    real_code = real.lower()
    if len(guess) != len(real_code):
        return False
    return hmac.compare_digest(real_code, guess)
