#!/usr/bin/env python3
"""WOL Console — Backend con auth compartido."""
import json, os, socket, re, sys, time, logging, hashlib, hmac, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "auth"))
import auth

PORT       = 8080
HOST       = "0.0.0.0"
DATA_FILE  = Path(__file__).parent / "devices.json"
LOG_FILE   = Path(__file__).parent / "wake_log.json"
STATIC_DIR = Path(__file__).parent / "static"
WOL_SECRET = os.environ.get("WOL_SECRET", "cambiar-esta-clave")
RATE_LIMIT  = 10

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("wol")

# ─── Rate limiting ────────────────────────────────────────────────────────────
_rate: dict = {}
def check_rate(ip):
    now = time.time()
    hits = [t for t in _rate.get(ip, []) if now-t < 60]
    if len(hits) >= RATE_LIMIT: return False
    hits.append(now); _rate[ip] = hits; return True

# ─── CSRF token ───────────────────────────────────────────────────────────────
def gen_token():
    ts = str(int(time.time()//300))
    return hmac.new(WOL_SECRET.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]

def valid_token(t):
    for d in (0,-1):
        ts = str(int(time.time()//300)+d)
        exp = hmac.new(WOL_SECRET.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(exp, t or ""): return True
    return False

# ─── MAC validation ───────────────────────────────────────────────────────────
_MAC = re.compile(r'^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$')
def norm_mac(raw):
    raw = raw.strip()
    return raw.upper().replace("-",":") if _MAC.match(raw) else None

# ─── Broadcast IP ─────────────────────────────────────────────────────────────
def _local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    except: return "127.0.0.1"

def _broadcast():
    return _local_ip().rsplit(".",1)[0] + ".255"

# ─── Ping (para verificar si ya está online) ──────────────────────────────────
def ping_host(ip: str, timeout: float = 1.0) -> bool:
    """Retorna True si el host responde a ping."""
    if not ip: return False
    try:
        import subprocess
        r = subprocess.run(["ping", "-c1", f"-W{int(timeout)}", ip],
                           capture_output=True, timeout=timeout+1)
        return r.returncode == 0
    except Exception:
        return False

# ─── WOL ──────────────────────────────────────────────────────────────────────
def send_wol(mac, port):
    import subprocess, shutil
    broadcast = _broadcast()
    clean = re.sub(r'[^0-9A-Fa-f:]', '', mac)
    if not shutil.which("wakeonlan"):
        raise RuntimeError("wakeonlan no encontrado. Instala: sudo apt install wakeonlan")
    cmd = ["wakeonlan", "-i", broadcast, clean]
    log.info(f"Ejecutando: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "wakeonlan failed")
    log.info(f"Magic packet → MAC={clean} broadcast={broadcast}:{port}")

# ─── Wake log ─────────────────────────────────────────────────────────────────
_log_lock = threading.Lock()

def load_wake_log() -> list:
    try:
        if LOG_FILE.exists():
            d = json.loads(LOG_FILE.read_text())
            return d if isinstance(d, list) else []
    except: pass
    return []

def append_wake_log(entry: dict):
    with _log_lock:
        entries = load_wake_log()
        entries.append(entry)
        entries = entries[-500:]   # máx 500 entradas
        tmp = LOG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=2))
        tmp.replace(LOG_FILE)

# ─── Devices ──────────────────────────────────────────────────────────────────
_dev_lock = threading.Lock()

def load_devices():
    try:
        if DATA_FILE.exists():
            d = json.loads(DATA_FILE.read_text())
            return d if isinstance(d, list) else []
    except: pass
    return []

def save_devices(devs):
    with _dev_lock:
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(devs, indent=2)); tmp.replace(DATA_FILE)

def validate_device(d):
    if not isinstance(d.get("name"), str) or not d["name"].strip():
        return False, "Invalid name"
    if not isinstance(d.get("mac"), str) or not norm_mac(d["mac"]):
        return False, "Invalid MAC address"
    p = d.get("port", 9)
    if not isinstance(p, int) or not (1 <= p <= 65535):
        return False, "Invalid port"
    if d.get("tag","PC") not in ("PC","SERVER","NAS","VM","OTHER"):
        return False, "Invalid category"
    return True, ""

# ─── HTTP Handler ─────────────────────────────────────────────────────────────
class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        if int(a[1]) >= 400: log.warning(f"{self.client_address[0]} {a[1]}")

    def _ip(self):
        fwd = self.headers.get("X-Forwarded-For")
        return fwd.split(",")[0].strip() if fwd else self.client_address[0]

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > 8192: return None
            return json.loads(self.rfile.read(n))
        except: return None

    def _tok(self):
        return auth.token_from_request(dict(self.headers),
                                       self.headers.get("Cookie",""))

    def _file(self, path, mime):
        try:
            c = Path(path).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(c)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.end_headers(); self.wfile.write(c)
        except FileNotFoundError: self._json(404, {"error": "Not found"})

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        tok  = self._tok()

        if path in ("/", "/index.html"):
            return self._file(STATIC_DIR / "index.html", "text/html; charset=utf-8")

        if path == "/api/token":
            return self._json(200, {"token": gen_token()})

        if not auth.check_permission(tok, "wol", "readonly"):
            return self._json(401, {"error": "Unauthorized"})

        if path == "/api/devices":
            devs = load_devices()
            wake_log = load_wake_log()
            # Anotar last_wake por device id
            last_wake = {}
            for entry in wake_log:
                did = entry.get("device_id")
                if did and (did not in last_wake or entry["ts"] > last_wake[did]["ts"]):
                    last_wake[did] = entry
            for d in devs:
                lw = last_wake.get(d["id"])
                d["last_wake"] = lw["ts"] if lw else None
                d["last_wake_user"] = lw["user"] if lw else None
            self._json(200, {"devices": devs})

        elif path == "/api/wake_log":
            entries = load_wake_log()
            self._json(200, {"log": list(reversed(entries[-100:]))})

        elif path == "/api/config":
            self._json(200, {"server_host": _local_ip(), "port": PORT})

        elif path == "/api/me":
            sess = auth.get_session(tok)
            self._json(200, {"username": sess["username"],
                              "permissions": sess["permissions"]} if sess else {})
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        tok  = self._tok()
        body = self._body()
        if body is None: return self._json(400, {"error": "Invalid request body"})

        if path == "/api/login":
            u = auth.authenticate(body.get("username",""), body.get("password",""))
            if not u: return self._json(401, {"error": "Invalid credentials"})
            token = auth.create_session(body["username"], u["permissions"])
            users = auth.load_users()
            must  = users.get(body["username"],{}).get("must_change_password", False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie",
                f"session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400")
            br = json.dumps({"ok": True, "token": token,
                             "permissions": u["permissions"],
                             "must_change_password": must}).encode()
            self.send_header("Content-Length", str(len(br)))
            self.end_headers(); self.wfile.write(br); return

        if path == "/api/logout":
            auth.delete_session(tok); return self._json(200, {"ok": True})

        if not auth.check_permission(tok, "wol", "readonly"):
            return self._json(401, {"error": "Unauthorized"})

        if path == "/api/devices":
            if not auth.check_permission(tok, "wol", "admin"):
                return self._json(403, {"error": "Requiere permiso admin"})
            ok2, msg = validate_device(body)
            if not ok2: return self._json(400, {"error": msg})
            mac  = norm_mac(body["mac"])
            devs = load_devices()
            if any(d["mac"] == mac for d in devs):
                return self._json(409, {"error": "MAC duplicada"})
            import uuid
            dev = {"id": str(uuid.uuid4()), "name": body["name"].strip()[:40],
                   "mac": mac, "ip": (body.get("ip") or "").strip() or None,
                   "port": int(body.get("port",9)),
                   "tag": body.get("tag","PC"), "added": int(time.time())}
            devs.append(dev); save_devices(devs)
            self._json(201, {"device": dev})

        elif path == "/api/ping":
            # Verificar si un equipo ya está online antes de despertar
            if not auth.check_permission(tok, "wol", "readonly"):
                return self._json(403, {"error": "Unauthorized"})
            ip = (body.get("ip") or "").strip()
            if not ip:
                return self._json(400, {"error": "IP requerida"})
            online = ping_host(ip)
            self._json(200, {"online": online, "ip": ip})

        elif path == "/api/wake":
            if not auth.check_permission(tok, "wol", "execute"):
                return self._json(403, {"error": "Requiere permiso execute"})
            if not check_rate(self._ip()):
                return self._json(429, {"error": "Rate limit"})
            devs = load_devices()
            dev  = next((d for d in devs if d["id"] == body.get("id")), None)
            if not dev: return self._json(404, {"error": "Dispositivo no encontrado"})

            # Verificar si ya está online
            already_online = ping_host(dev.get("ip","")) if dev.get("ip") else False
            if already_online and not body.get("force"):
                return self._json(200, {"ok": False, "already_online": True,
                                        "message": f"{dev['name']} is already on"})
            try:
                send_wol(dev["mac"], dev.get("port",9))
                sess = auth.get_session(tok)
                username = sess["username"] if sess else "?"
                # Registrar en log
                append_wake_log({
                    "ts": int(time.time()),
                    "device_id": dev["id"],
                    "device_name": dev["name"],
                    "mac": dev["mac"],
                    "user": username,
                    "already_online": already_online,
                })
                self._json(200, {"ok": True,
                                 "message": f"Paquete enviado a {dev['name']}",
                                 "already_online": already_online})
            except Exception as e:
                log.error(f"WOL error: {e}"); self._json(500, {"error": str(e)})

        elif path == "/api/wake_all":
            if not auth.check_permission(tok, "wol", "execute"):
                return self._json(403, {"error": "Requiere permiso execute"})
            devs = load_devices()
            sess = auth.get_session(tok)
            username = sess["username"] if sess else "?"
            sent = 0
            errors = []
            for dev in devs:
                try:
                    send_wol(dev["mac"], dev.get("port", 9))
                    append_wake_log({
                        "ts": int(time.time()),
                        "device_id": dev["id"],
                        "device_name": dev["name"],
                        "mac": dev["mac"],
                        "user": username,
                        "already_online": False,
                        "bulk": True,
                    })
                    sent += 1
                except Exception as e:
                    errors.append({"name": dev["name"], "error": str(e)})
            self._json(200, {"ok": True, "sent": sent, "errors": errors})

        else:
            self._json(404, {"error": "Not found"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        tok  = self._tok()
        if not auth.check_permission(tok, "wol", "admin"):
            return self._json(403, {"error": "Requiere permiso admin"})
        m = re.match(r'^/api/devices/([0-9a-f\-]{36})$', path)
        if not m: return self._json(400, {"error": "Invalid ID"})
        devs = load_devices()
        new  = [d for d in devs if d["id"] != m.group(1)]
        if len(new) == len(devs): return self._json(404, {"error": "No encontrado"})
        save_devices(new); self._json(200, {"ok": True})

if __name__ == "__main__":
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"WOL Console en http://{HOST}:{PORT}")
    try:
        HTTPServer((HOST, PORT), H).serve_forever()
    except KeyboardInterrupt: sys.exit(0)
    except PermissionError:
        log.error(f"Sin permisos para puerto {PORT}"); sys.exit(1)
