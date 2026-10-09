#!/usr/bin/env python3
"""
Pi Console — Auth Module
Gestión de usuarios, sesiones y permisos compartido por WOL y NUT
"""
import json, os, hashlib, hmac, secrets, time, logging
from pathlib import Path

log = logging.getLogger("auth")

USERS_FILE    = Path(os.environ.get("PICONSOLE_USERS",    "/var/lib/pi-console/users.json"))
SESSION_TTL = 24 * 3600   # 24 horas
SESSIONS_FILE = Path(os.environ.get("PICONSOLE_SESSIONS", "/var/lib/pi-console/sessions.json"))
_slock = None
def _get_lock():
    global _slock
    if _slock is None:
        import threading
        _slock = threading.Lock()
    return _slock

def _salt() -> str:
    return os.environ.get("PICONSOLE_SALT", "pi-console-salt-change-me")

def _hash(password: str) -> str:
    return hashlib.sha256(f"{_salt()}:{password}".encode()).hexdigest()

# ─── Persistencia ─────────────────────────────────────────────────────────────
def load_users() -> dict:
    try:
        if USERS_FILE.exists():
            return json.loads(USERS_FILE.read_text())
    except Exception as e:
        log.warning(f"users.json: {e}")
    return {
        "admin": {
            "password_hash": _hash("admin"),
            "permissions": {"wol": "admin", "nut": "admin", "net": "admin", "pve": "admin"},
            "created": int(time.time()),
            "must_change_password": True,
        }
    }

def save_users(users: dict):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = USERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(users, indent=2))
    tmp.replace(USERS_FILE)

# ─── Sesiones compartidas (persistidas a disco) ────────────────────────────────
def _load_sessions() -> dict:
    try:
        if SESSIONS_FILE.exists():
            return json.loads(SESSIONS_FILE.read_text())
    except Exception:
        pass
    return {}

def _save_sessions(sessions: dict):
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SESSIONS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(sessions))
    tmp.replace(SESSIONS_FILE)

def create_session(username: str, permissions: dict) -> str:
    token = secrets.token_hex(32)
    with _get_lock():
        sessions = _load_sessions()
        sessions[token] = {
            "username":    username,
            "permissions": permissions,
            "expires":     time.time() + SESSION_TTL,
        }
        _purge(sessions)
        _save_sessions(sessions)
    return token

def get_session(token: str) -> dict | None:
    if not token: return None
    with _get_lock():
        sessions = _load_sessions()
        s = sessions.get(token)
        if not s: return None
        if time.time() > s["expires"]:
            sessions.pop(token, None); _save_sessions(sessions); return None
        # Renovar TTL en cada uso (sliding window de 24h)
        s["expires"] = time.time() + SESSION_TTL
        sessions[token] = s
        _save_sessions(sessions)
        return s

def delete_session(token: str):
    with _get_lock():
        sessions = _load_sessions()
        sessions.pop(token, None)
        _save_sessions(sessions)

def _purge(sessions: dict):
    now = time.time()
    for t in [k for k,v in sessions.items() if now > v["expires"]]:
        del sessions[t]

# ─── Helpers ──────────────────────────────────────────────────────────────────
LEVELS = {"readonly": 1, "execute": 2, "admin": 3}

def authenticate(username: str, password: str) -> dict | None:
    users = load_users()
    user  = users.get(username)
    if not user: return None
    if not hmac.compare_digest(user["password_hash"], _hash(password)): return None
    return user

def check_permission(token: str, resource: str, required: str) -> bool:
    s = get_session(token)
    if not s: return False
    return LEVELS.get(s["permissions"].get(resource, ""), 0) >= LEVELS.get(required, 999)

def token_from_request(headers, cookie_str="") -> str | None:
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "): return auth[7:].strip()
    for p in cookie_str.split(";"):
        p = p.strip()
        if p.startswith("session="): return p[8:].strip()
    return None
