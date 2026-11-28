"""Passwords (scrypt) and signed session cookies (HMAC-SHA256). No third-party auth library needed."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

COOKIE = "cf_session"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(s), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:  # noqa: BLE001
        return False


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user_id: int, sid: str, secret: str, hours: int) -> str:
    """Signed cookie value. ``sid`` names a row in ``user_sessions`` so a session can be revoked server-side."""
    body = _b64(json.dumps({"u": user_id, "s": sid, "exp": int(time.time()) + hours * 3600}).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str, secret: str) -> tuple[int, str] | None:
    """(user id, session id) of a valid, unexpired token; None otherwise (also for old tokens without a session)."""
    try:
        body, sig = token.split(".")
        good = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(_unb64(body))
        if data["exp"] <= time.time() or not data.get("s"):
            return None
        return int(data["u"]), str(data["s"])
    except Exception:  # noqa: BLE001
        return None


_DUMMY = hash_password("timing-equaliser")


def verify_dummy(password: str) -> None:
    """Spend the same time as a real check, so unknown usernames cannot be told apart by timing."""
    verify_password(password, _DUMMY)
