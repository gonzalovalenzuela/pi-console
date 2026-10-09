#!/usr/bin/env python3
"""NUT Monitor — Backend con auth, multi-servidor, historial SQLite."""
import json, os, re, socket, time, logging, threading, sys, sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from collections import deque
from contextlib import contextmanager

# Auth compartido
sys.path.insert(0, str(Path(__file__).parent.parent / "auth"))
import auth

HOST        = "127.0.0.1"
PORT        = 8081
POLL_SEC    = int(os.environ.get("NUT_POLL", 10))
STATIC_DIR  = Path(__file__).parent / "static"
DATA_FILE   = Path(__file__).parent / "servers.json"
DB_FILE     = Path(__file__).parent / "history.db"

# Cuántos puntos devolver en la API según rango
RANGE_LIMIT = {
    "1h":  720,    # 1h a 10s = 360 pts (margen x2 para no truncar los puntos recientes)
    "1d":  2880,   # 1d a 30s = 2880 pts
    "1w":  2016,   # 1w a 5min = 2016 pts
    "1mo": 2880,   # 1mes a 15min = 2880 pts
    "all": 4320,   # máx a mostrar en gráfico
}

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("nut")

# ─── SQLite ───────────────────────────────────────────────────────────────────
_db_lock = threading.Lock()

def db_connect():
    conn = sqlite3.connect(str(DB_FILE), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def db_init():
    with _db_lock:
        conn = db_connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                srv_id  TEXT NOT NULL,
                ups     TEXT NOT NULL,
                ts      INTEGER NOT NULL,
                charge  REAL DEFAULT 0,
                runtime INTEGER DEFAULT 0,
                load    REAL DEFAULT 0,
                vin     REAL DEFAULT 0,
                vout    REAL DEFAULT 0,
                watts   REAL DEFAULT 0,
                temp    REAL DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_srv_ups_ts ON history(srv_id, ups, ts)")
        conn.commit(); conn.close()
    log.info(f"DB: {DB_FILE}")

# Las filas se acumulan en memoria y se escriben juntas cada DB_FLUSH_SEC segundos
# (un commit por lote en vez de uno cada POLL_SEC por UPS: menos desgaste de la SD).
# Si el UPS no está en línea (ups.status distinto de OL: batería, carga baja, etc.)
# se escribe de inmediato, porque ahí es cuando más importa no perder datos.
DB_FLUSH_SEC = int(os.environ.get("NUT_DB_FLUSH", 60))
_INSERT_SQL = """
    INSERT INTO history (srv_id,ups,ts,charge,runtime,load,vin,vout,watts,temp)
    VALUES (?,?,?,?,?,?,?,?,?,?)
"""
_ins_buf = []
_ins_last = time.time()

def _flush_locked():
    global _ins_last
    if not _ins_buf: return
    conn = db_connect()
    try:
        conn.executemany(_INSERT_SQL, _ins_buf)
        conn.commit()
        _ins_buf.clear()
        _ins_last = time.time()
    finally:
        conn.close()

def db_flush(timeout=3):
    # timeout: desde el handler de SIGTERM (hilo principal) el lock podría estar tomado
    if not _db_lock.acquire(timeout=timeout): return
    try: _flush_locked()
    except Exception as e: log.error(f"db_flush: {e}")
    finally: _db_lock.release()

def db_insert(srv_id, ups, entry, urgent=False):
    with _db_lock:
        _ins_buf.append((srv_id, ups,
                         entry["ts"], entry["charge"], entry["runtime"], entry["load"],
                         entry["vin"], entry["vout"], entry["watts"], entry["temp"]))
        if len(_ins_buf) > 5000:          # si el disco falla, no crecer sin límite
            del _ins_buf[:len(_ins_buf)-5000]
        if urgent or time.time() - _ins_last >= DB_FLUSH_SEC:
            try: _flush_locked()
            except Exception as e: log.error(f"db flush: {e}")

def db_query(srv_id, ups, since_ts=0, limit=4320):
    """Historial de un UPS reducido a como máximo ~`limit` puntos.

    Agrupa por intervalos de tiempo iguales y promedia cada uno (el último punto
    conserva su timestamp real). Así la muestra es pareja, llega hasta el dato más
    reciente y no depende de los ids de fila, que se comparten entre todos los UPS.
    (Elegir filas con `id % paso` dejaba sin ningún punto a un UPS cuando había
    dos o más y el paso era par.)
    """
    with _db_lock:
        conn = db_connect()
        try:
            lo, hi = conn.execute(
                "SELECT MIN(ts), MAX(ts) FROM history WHERE srv_id=? AND ups=? AND ts>=?",
                (srv_id, ups, since_ts)).fetchone()
            if lo is None:
                return []
            bucket = max(1, -(-(hi - lo) // max(1, limit - 1)))   # techo de span/(limit-1)
            rows = conn.execute("""
                SELECT MAX(ts) AS ts, AVG(charge) AS charge, AVG(runtime) AS runtime,
                       AVG(load) AS load, AVG(vin) AS vin, AVG(vout) AS vout,
                       AVG(watts) AS watts, AVG(temp) AS temp
                FROM history
                WHERE srv_id=? AND ups=? AND ts>=?
                GROUP BY (ts - ?) / ?
                ORDER BY ts ASC
            """, (srv_id, ups, since_ts, lo, bucket)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

def db_prune():
    """Elimina registros de más de 1 año. Llamar periódicamente."""
    cutoff = int(time.time()) - 365 * 86400
    with _db_lock:
        conn = db_connect()
        deleted = conn.execute("DELETE FROM history WHERE ts < ?", (cutoff,)).rowcount
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit(); conn.close()
    if deleted: log.info(f"DB pruned: {deleted} registros >1 año eliminados")

# ─── Servidores ───────────────────────────────────────────────────────────────
def load_servers():
    try:
        if DATA_FILE.exists():
            d = json.loads(DATA_FILE.read_text())
            return d if isinstance(d, list) else []
    except: pass
    return [{"id": "local", "name": "Local", "host": "127.0.0.1", "port": 3493}]

def save_servers(s):
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2)); tmp.replace(DATA_FILE)

# ─── Watts ────────────────────────────────────────────────────────────────────
def _calc_watts(vars_):
    try:
        rp = float(vars_.get("ups.realpower") or 0)
        if rp > 0: return rp
    except: pass
    try:
        pva = float(vars_.get("ups.power") or 0)
        pf  = float(vars_.get("ups.powerfactor") or 0)
        if pva > 0 and pf > 0: return round(pva * pf, 1)
    except: pass
    try:
        vout = float(vars_.get("output.voltage") or 0)
        iout = float(vars_.get("output.current") or 0)
        if vout > 0 and iout > 0: return round(vout * iout, 1)
    except: pass
    try:
        pva  = float(vars_.get("ups.power") or 0)
        load = float(vars_.get("ups.load") or 0)
        if pva > 0 and load > 0: return round(pva * (load / 100) * 0.8, 1)
    except: pass
    try:
        nom  = float(vars_.get("ups.realpower.nominal") or
                     vars_.get("ups.power.nominal") or 0)
        load = float(vars_.get("ups.load") or 0)
        if nom > 0 and load > 0: return round(nom * (load / 100), 1)
    except: pass
    return 0.0

# ─── NUT Client ───────────────────────────────────────────────────────────────
class NUTClient:
    def __init__(self, host, port, timeout=5.0):
        self.host = host; self.port = int(port); self.timeout = timeout

    def _conn(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout); s.connect((self.host, self.port)); return s

    def _readline(self, sock):
        buf = b""
        while True:
            ch = sock.recv(1)
            if not ch or ch == b"\n": break
            buf += ch
        return buf.decode(errors="replace").strip()

    def _cmd(self, sock, cmd):
        sock.sendall((cmd + "\n").encode())
        lines = []; is_list = cmd.strip().upper().startswith("LIST")
        while True:
            line = self._readline(sock)
            if not line: break
            lines.append(line)
            if is_list:
                if line.startswith("END LIST") or line.startswith("ERR"): break
            else:
                if line.startswith("VAR ") or line.startswith("VER ") or \
                   line.startswith("ERR") or line.startswith("OK"): break
        return lines

    def list_ups(self):
        with self._conn() as s: lines = self._cmd(s, "LIST UPS")
        return [{"name": m.group(1), "desc": m.group(2)}
                for line in lines for m in [re.match(r'^UPS (\S+) "(.*)"$', line)] if m]

    def get_vars(self, ups):
        with self._conn() as s: lines = self._cmd(s, f"LIST VAR {ups}")
        return {m.group(1): m.group(2)
                for line in lines for m in [re.match(r'^VAR \S+ (\S+) "(.*)"$', line)] if m}

    def list_clients(self, ups):
        try:
            with self._conn() as s: lines = self._cmd(s, f"LIST CLIENT {ups}")
            return [m.group(1) for line in lines
                    for m in [re.match(r'^CLIENT \S+ (\S+)$', line)] if m]
        except Exception as e:
            log.debug(f"list_clients: {e}"); return []

    def get_version(self):
        try:
            with self._conn() as s: lines = self._cmd(s, "VER")
            return next((l.strip() for l in lines if l.strip()), "")
        except: return ""

# ─── Cache en memoria (solo estado actual) ────────────────────────────────────
class SCache:
    def __init__(self, sid):
        self.id = sid; self._lock = threading.RLock()
        self._ups = {}; self._clients = {}
        self._error = None; self._last_ok = None; self._ver = ""

    def update(self, name, vars_, clients=None, ver=""):
        with self._lock:
            self._ups[name]     = {**vars_, "_ts": time.time()}
            self._clients[name] = clients or []
            self._error = None; self._last_ok = time.time()
            if ver: self._ver = ver
        # Insertar en DB fuera del lock
        try:
            watts = _calc_watts(vars_)
            entry = {
                "ts":      int(time.time()),
                "charge":  float(vars_.get("battery.charge") or 0),
                "runtime": int(float(vars_.get("battery.runtime") or 0)),
                "load":    float(vars_.get("ups.load") or 0),
                "vin":     float(vars_.get("input.voltage") or 0),
                "vout":    float(vars_.get("output.voltage") or 0),
                "watts":   watts,
                "temp":    float(vars_.get("ups.temperature") or
                                 vars_.get("battery.temperature") or 0),
            }
            status = (vars_.get("ups.status") or "OL").strip()
            db_insert(self.id, name, entry, urgent=not status.startswith("OL"))
        except Exception as e:
            log.debug(f"db_insert error: {e}")

    def set_error(self, msg):
        with self._lock: self._error = msg

    def snap(self, range_="all"):
        """Devuelve estado actual + historial según rango."""
        with self._lock:
            ups_snap  = dict(self._ups)
            cli_snap  = dict(self._clients)
            error     = self._error
            last_ok   = self._last_ok
            ver       = self._ver

        # range=none: solo estado actual, sin tocar la base (refresco automático de la página)
        if range_ == "none":
            return {"id": self.id, "ups": ups_snap, "clients": cli_snap,
                    "history": {}, "error": error, "last_ok": last_ok,
                    "version": ver, "ts": time.time()}

        # Cargar historial de DB según rango
        since = 0
        now   = int(time.time())
        range_secs = {"1h":3600,"1d":86400,"1w":604800,"1mo":2592000}
        if range_ in range_secs: since = now - range_secs[range_]
        limit = RANGE_LIMIT.get(range_, 4320)

        history = {}
        for ups_name in ups_snap:
            history[ups_name] = db_query(self.id, ups_name, since_ts=since, limit=limit)

        return {"id": self.id, "ups": ups_snap, "clients": cli_snap,
                "history": history, "error": error, "last_ok": last_ok,
                "version": ver, "ts": time.time()}

_caches: dict = {}; _pollers: dict = {}; _gl = threading.Lock()

def ensure_poller(server):
    sid = server["id"]
    with _gl:
        if sid not in _caches: _caches[sid] = SCache(sid)
        if sid not in _pollers or not _pollers[sid].is_alive():
            t = threading.Thread(target=_poll, args=(server,), daemon=True)
            _pollers[sid] = t; t.start()
            log.info(f"Poller → {server['name']} ({server['host']}:{server['port']})")

def remove_poller(sid):
    with _gl: _caches.pop(sid, None); _pollers.pop(sid, None)

def _poll(server):
    sid = server["id"]; nut = NUTClient(server["host"], server["port"])
    cache = _caches.get(sid)
    if not cache: return
    poll_n = 0
    while True:
        if not any(s["id"] == sid for s in load_servers()): return
        try:
            ver   = nut.get_version()
            ups_l = nut.list_ups()
            if not ups_l: cache.set_error("No UPS found in upsd")
            for u in ups_l:
                vars_   = nut.get_vars(u["name"])
                clients = nut.list_clients(u["name"])
                vars_["_desc"]   = u["desc"]
                vars_["_serial"] = vars_.get("ups.serial") or vars_.get("device.serial") or ""
                cache.update(u["name"], vars_, clients, ver)
        except ConnectionRefusedError:
            cache.set_error(f"upsd no disponible en {server['host']}:{server['port']}")
        except socket.timeout:
            cache.set_error("Timeout connecting to upsd")
        except Exception as e:
            cache.set_error(str(e)); log.error(f"poll error: {e}")
        poll_n += 1
        # Limpiar DB cada 1440 polls (~4h con poll=10s)
        if poll_n % 1440 == 0:
            threading.Thread(target=db_prune, daemon=True).start()
        time.sleep(POLL_SEC)

def start_all():
    db_init()
    for s in load_servers(): ensure_poller(s)

# ─── HTTP Handler ─────────────────────────────────────────────────────────────
class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        if int(a[1]) >= 400: log.warning(f"{self.client_address[0]} {a[1]}")

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

    def _token(self):
        return auth.token_from_request(dict(self.headers),
                                       self.headers.get("Cookie", ""))

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

    def _range_param(self):
        qs = parse_qs(urlparse(self.path).query)
        return qs.get("range", ["all"])[0]

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        tok  = self._token()

        if path in ("/", "/index.html"):
            return self._file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        if path == "/api/login":
            return self._json(200, {"ok": True})

        if not auth.check_permission(tok, "nut", "readonly"):
            return self._json(401, {"error": "Unauthorized"})

        if path == "/api/config":
            self._json(200, {"poll_sec": POLL_SEC})
        elif path == "/api/servers":
            range_ = self._range_param()
            srvs   = load_servers()
            out    = [{**s, "status": _caches.get(s["id"], SCache(s["id"])).snap(range_)} for s in srvs]
            self._json(200, {"servers": out})
        elif path == "/api/ups":
            range_ = self._range_param()
            self._json(200, {sid: c.snap(range_) for sid, c in _caches.items()})
        elif path == "/api/history":
            # Historial de un UPS concreto para un rango (resolucion propia del rango)
            qs     = parse_qs(urlparse(self.path).query)
            sid    = qs.get("srv", ["local"])[0]
            ups    = qs.get("ups", ["ups"])[0]
            range_ = qs.get("range", ["all"])[0]
            range_secs = {"1h":3600,"1d":86400,"1w":604800,"1mo":2592000}
            since = int(time.time()) - range_secs[range_] if range_ in range_secs else 0
            rows  = db_query(sid, ups, since_ts=since, limit=RANGE_LIMIT.get(range_, 4320))
            self._json(200, {"history": rows})
        elif path == "/api/export/csv":
            # Export CSV del historial de un UPS específico
            qs    = parse_qs(urlparse(self.path).query)
            sid   = qs.get("srv", ["local"])[0]
            ups   = qs.get("ups", ["ups"])[0]
            range_ = qs.get("range", ["all"])[0]
            since = 0
            now   = int(time.time())
            range_secs = {"1h":3600,"1d":86400,"1w":604800,"1mo":2592000}
            if range_ in range_secs: since = now - range_secs[range_]
            rows = db_query(sid, ups, since_ts=since, limit=8640)
            import csv, io
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["timestamp","datetime","charge_pct","runtime_s","load_pct","vin_v","vout_v","watts","temp_c"])
            for r in rows:
                writer.writerow([
                    r["ts"],
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])),
                    r["charge"], r["runtime"], r["load"],
                    r["vin"], r["vout"], r["watts"], r["temp"]
                ])
            body = buf.getvalue().encode()
            fname = f"ups-history-{sid}-{ups}-{time.strftime('%Y%m%d')}.csv"
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)

        elif path == "/api/me":
            sess = auth.get_session(tok)
            self._json(200, {"username": sess["username"],
                              "permissions": sess["permissions"]} if sess else {})
        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        tok  = self._token()
        body = self._body()
        if body is None: return self._json(400, {"error": "Invalid request body"})

        if path == "/api/login":
            u = auth.authenticate(body.get("username",""), body.get("password",""))
            if not u: return self._json(401, {"error": "Invalid credentials"})
            token = auth.create_session(body["username"], u["permissions"])
            users = auth.load_users()
            must  = users.get(body["username"], {}).get("must_change_password", False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie",
                f"session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400")
            body_resp = json.dumps({"ok": True, "token": token,
                                    "permissions": u["permissions"],
                                    "must_change_password": must}).encode()
            self.send_header("Content-Length", str(len(body_resp)))
            self.end_headers(); self.wfile.write(body_resp); return

        if path == "/api/logout":
            auth.delete_session(tok)
            return self._json(200, {"ok": True})

        if not auth.check_permission(tok, "nut", "readonly"):
            return self._json(401, {"error": "Unauthorized"})

        if path == "/api/servers":
            if not auth.check_permission(tok, "nut", "admin"):
                return self._json(403, {"error": "Requiere permiso admin"})
            host = (body.get("host") or "").strip()
            name = (body.get("name") or "").strip()
            port = int(body.get("port") or 3493)
            if not host or not name: return self._json(400, {"error": "host y name requeridos"})
            srvs = load_servers()
            if any(s["host"]==host and s["port"]==port for s in srvs):
                return self._json(409, {"error": "Ya existe ese host:puerto"})
            import uuid
            server = {"id": str(uuid.uuid4()), "name": name, "host": host, "port": port}
            srvs.append(server); save_servers(srvs); ensure_poller(server)
            self._json(201, {"server": server})
        elif path == "/api/test":
            host = (body.get("host") or "").strip()
            port = int(body.get("port") or 3493)
            try:
                nut  = NUTClient(host, port, timeout=4)
                ups  = nut.list_ups(); ver = nut.get_version()
                self._json(200, {"ok": True, "ups_count": len(ups), "ups": ups, "version": ver})
            except Exception as e:
                self._json(200, {"ok": False, "error": str(e)})
        else:
            self._json(404, {"error": "Not found"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        tok  = self._token()
        if not auth.check_permission(tok, "nut", "admin"):
            return self._json(403, {"error": "Requiere permiso admin"})
        m = re.match(r'^/api/servers/([a-zA-Z0-9\-]+)$', path)
        if not m: return self._json(400, {"error": "Invalid ID"})
        sid = m.group(1)
        if sid == "local": return self._json(403, {"error": "No se puede eliminar el servidor local"})
        srvs = load_servers()
        new  = [s for s in srvs if s["id"] != sid]
        if len(new) == len(srvs): return self._json(404, {"error": "No encontrado"})
        save_servers(new); remove_poller(sid); self._json(200, {"ok": True})

if __name__ == "__main__":
    import signal, atexit
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    start_all()
    atexit.register(db_flush)
    # systemd detiene el servicio con SIGTERM: vaciar el buffer antes de salir
    signal.signal(signal.SIGTERM, lambda *_: (db_flush(), sys.exit(0)))
    log.info(f"NUT Monitor en http://{HOST}:{PORT} — poll cada {POLL_SEC}s")
    try:
        HTTPServer((HOST, PORT), H).serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
