#!/usr/bin/env python3
"""
Proxmox Monitor — Dashboard de nodos, VMs y CTs
API REST de Proxmox VE — sin dependencias externas
"""
import json, os, re, ssl, sys, time, logging, threading, http.client
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
from urllib.error import URLError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "auth"))
import auth

HOST       = "127.0.0.1"
PORT       = 8084
STATIC_DIR = Path(__file__).parent / "static"
DATA_FILE  = Path(__file__).parent / "clusters.json"
POLL_ACTIVE = float(os.environ.get("PVE_POLL_ACTIVE", 5))    # seconds, while someone is watching
POLL_IDLE   = float(os.environ.get("PVE_POLL_IDLE", 60))     # seconds, when nobody has the page open
VIEW_GRACE  = 30                                              # a viewer counts as active for this long
SLOW_EVERY  = 60                                              # version / ceph refresh period
HIST_EVERY  = 30                                              # node history sampling period
_last_view  = 0.0                                             # last time a browser asked for data

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("pve")

# ─── Proxmox API client ────────────────────────────────────────────────────────
class PVEHTTPError(RuntimeError):
    def __init__(self, status, reason=""):
        super().__init__(f"HTTP {status}: {reason}")
        self.status = status

class PVEClient:
    """PVE API client with a persistent HTTPS connection (avoids a TLS handshake on every poll)."""
    def __init__(self, host, port, user, token_name, token_value, verify_ssl=False):
        self.host, self.port = host, int(port)
        self.headers = {
            "Authorization": f"PVEAPIToken={user}!{token_name}={token_value}",
            "Accept":        "application/json",
        }
        self.ctx = ssl.create_default_context()
        if not verify_ssl:
            self.ctx.check_hostname = False
            self.ctx.verify_mode    = ssl.CERT_NONE
        self._conn = None
        self._lock = threading.Lock()

    def close(self):
        try:
            if self._conn: self._conn.close()
        except Exception:
            pass
        self._conn = None

    def get(self, path: str) -> dict:
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None:
                        self._conn = http.client.HTTPSConnection(self.host, self.port, timeout=8, context=self.ctx)
                    self._conn.request("GET", "/api2/json" + path, headers=self.headers)
                    r = self._conn.getresponse()
                    body = r.read()
                    if r.status >= 400:
                        raise PVEHTTPError(r.status, r.reason)
                    return json.loads(body.decode())
                except PVEHTTPError:
                    raise
                except (http.client.HTTPException, OSError, ValueError):
                    self.close()                      # stale keep-alive connection: reconnect once
                    if attempt == 2:
                        raise

    def resources(self) -> list:
        """One call for nodes, VMs, CTs and storages of the whole cluster."""
        return self.get("/cluster/resources").get("data", [])

    def nodes(self) -> list:
        return self.get("/nodes").get("data", [])

    def node_status(self, node: str) -> dict:
        return self.get(f"/nodes/{node}/status").get("data", {})

    def vms(self, node: str) -> list:
        return self.get(f"/nodes/{node}/qemu").get("data", [])

    def containers(self, node: str) -> list:
        return self.get(f"/nodes/{node}/lxc").get("data", [])

    def storage(self, node: str) -> list:
        return self.get(f"/nodes/{node}/storage").get("data", [])

    def cluster_status(self) -> list:
        try:
            return self.get("/cluster/status").get("data", [])
        except Exception:
            return []

    def version(self) -> str:
        try:
            return self.get("/version").get("data", {}).get("version", "")
        except Exception:
            return ""

# ─── Clusters config ──────────────────────────────────────────────────────────
def load_clusters() -> list:
    try:
        if DATA_FILE.exists():
            d = json.loads(DATA_FILE.read_text())
            return d if isinstance(d, list) else []
    except Exception: pass
    return []

def save_clusters(c: list):
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, indent=2))
    tmp.replace(DATA_FILE)

# ─── Cache ────────────────────────────────────────────────────────────────────
_cache:   dict = {}   # { cluster_id: snapshot }
_pollers: dict = {}
_glock = threading.Lock()

# ─── Ring buffer de historial CPU/RAM por nodo ────────────────────────────────
from collections import deque as _deque

_NODE_HISTORY: dict = {}   # { "cid:node": deque of {ts, cpu, mem_pct} }
_HIST_MAX = 1440           # ~12h a 30s
_hist_lock = threading.Lock()

def push_node_history(cid: str, node_name: str, cpu: float, mem: int, maxmem: int):
    key = f"{cid}:{node_name}"
    mem_pct = round(mem / maxmem * 100, 1) if maxmem > 0 else 0
    with _hist_lock:
        if key not in _NODE_HISTORY:
            _NODE_HISTORY[key] = _deque(maxlen=_HIST_MAX)
        if _NODE_HISTORY[key] and time.time() - _NODE_HISTORY[key][-1]["ts"] < HIST_EVERY - 1:
            return                         # fixed 30 s sampling even when polling faster
        _NODE_HISTORY[key].append({"ts": int(time.time()), "cpu": round(cpu*100, 1), "mem": mem_pct})

def get_node_history(cid: str, node_name: str) -> list:
    key = f"{cid}:{node_name}"
    with _hist_lock:
        return list(_NODE_HISTORY.get(key, []))


class ClusterCache:
    def __init__(self, cid):
        self.id    = cid
        self._lock = threading.RLock()
        self._data = {}
        self._err  = None
        self._ts   = None
        self.wake  = threading.Event()     # set to make the poller refresh right now

    def update(self, data: dict):
        with self._lock:
            self._data = data
            self._err  = None
            self._ts   = time.time()

    def set_error(self, e: str):
        with self._lock:
            self._err = e

    def snap(self) -> dict:
        with self._lock:
            return {"id": self.id, "data": dict(self._data),
                    "error": self._err, "ts": self._ts}

def _fetch_legacy(client, name):
    """Fallback when /cluster/resources is unavailable (standalone node, limited token): per-node calls."""
    nodes_data = []
    for node in client.nodes():
        n = node["node"]
        info = {k: node.get(k, 0) for k in ("uptime", "cpu", "maxcpu", "mem", "maxmem", "disk", "maxdisk")}
        info.update(name=n, status=node.get("status"), vms=[], cts=[], storage=[])
        if node.get("status") == "online":
            try:
                info["vms"], info["cts"], info["storage"] = client.vms(n), client.containers(n), client.storage(n)
            except Exception as e:
                log.warning(f"[{name}] {n} detail error: {e}")
        nodes_data.append(info)
    return nodes_data

def _build_from_resources(res: list) -> list:
    """Group /cluster/resources by node, mapped to the shape the UI already uses."""
    nodes, order = {}, []
    for r in res:
        t = r.get("type")
        if t == "node":
            n = r.get("node")
            nodes[n] = {"name": n, "status": r.get("status"), "uptime": r.get("uptime", 0),
                        "cpu": r.get("cpu", 0), "maxcpu": r.get("maxcpu", 0),
                        "mem": r.get("mem", 0), "maxmem": r.get("maxmem", 0),
                        "disk": r.get("disk", 0), "maxdisk": r.get("maxdisk", 0),
                        "vms": [], "cts": [], "storage": []}
            order.append(n)
    for r in res:
        t, n = r.get("type"), r.get("node")
        if n not in nodes: continue
        if t in ("qemu", "lxc"):
            item = {"vmid": r.get("vmid"), "name": r.get("name", ""), "status": r.get("status", ""),
                    "cpu": r.get("cpu", 0), "cpus": r.get("maxcpu", 0), "mem": r.get("mem", 0),
                    "maxmem": r.get("maxmem", 0), "disk": r.get("disk", 0), "maxdisk": r.get("maxdisk", 0),
                    "uptime": r.get("uptime", 0), "netin": r.get("netin", 0), "netout": r.get("netout", 0),
                    "tags": r.get("tags", ""), "lock": r.get("lock", ""), "template": r.get("template", 0)}
            nodes[n]["vms" if t == "qemu" else "cts"].append(item)
        elif t == "storage":
            tot, used = r.get("maxdisk", 0), r.get("disk", 0)
            nodes[n]["storage"].append({"storage": r.get("storage"), "type": r.get("plugintype", ""),
                                        "content": r.get("content", ""), "shared": r.get("shared", 0),
                                        "active": 1 if r.get("status") == "available" else 0,
                                        "total": tot, "used": used, "avail": max(tot - used, 0),
                                        "used_fraction": (used / tot) if tot else 0})
    for nd in nodes.values():
        if nd["status"] != "online":                # same as the per-node path: nothing listed for offline nodes
            nd["vms"], nd["cts"], nd["storage"] = [], [], []
    return [nodes[n] for n in order]

def _poll_cluster(cluster):
    cid = cluster["id"]
    cache = _cache.get(cid)
    if not cache: return

    client = PVEClient(
        host=cluster["host"], port=cluster.get("port", 8006),
        user=cluster["user"], token_name=cluster["token_name"],
        token_value=cluster["token_value"],
        verify_ssl=cluster.get("verify_ssl", False)
    )
    version, ceph, slow_ts = "", None, 0.0
    use_resources = True

    while True:
        if not any(c["id"] == cid for c in load_clusters()):
            client.close()
            return
        t0 = time.time()
        try:
            nodes_data = None
            if use_resources:
                try:
                    nodes_data = _build_from_resources(client.resources())
                    if not nodes_data: raise RuntimeError("empty /cluster/resources")
                except PVEHTTPError as e:
                    if e.status not in (403, 404, 501): raise      # transient server error: keep using /cluster/resources
                    log.warning(f"[{cluster['name']}] /cluster/resources unavailable ({e}); using per-node calls")
                    use_resources = False
            if nodes_data is None:
                nodes_data = _fetch_legacy(client, cluster["name"])

            # version and ceph change rarely: refresh them once a minute
            if t0 - slow_ts >= SLOW_EVERY:
                v = client.version()
                if v: version = v
                try:    ceph = client.get("/cluster/ceph/status").get("data")
                except Exception: ceph = None
                slow_ts = t0

            for nd in nodes_data:
                if nd.get("status") == "online":
                    push_node_history(cid, nd["name"], nd.get("cpu", 0), nd.get("mem", 0), nd.get("maxmem", 0))

            cache.update({"nodes": nodes_data, "version": version,
                          "name": cluster["name"], "ceph": ceph})
            log.debug(f"[{cluster['name']}] {len(nodes_data)} nodes in {time.time()-t0:.2f}s")

        except Exception as e:
            cache.set_error(str(e))
            client.close()
            log.error(f"[{cluster['name']}] poll error: {e}")

        # fast while a browser is watching, slow otherwise; a new viewer wakes the poller at once
        active = (time.time() - _last_view) < VIEW_GRACE
        cache.wake.wait(POLL_ACTIVE if active else POLL_IDLE)
        cache.wake.clear()

def ensure_poller(cluster):
    cid = cluster["id"]
    with _glock:
        if cid not in _cache:
            _cache[cid] = ClusterCache(cid)
        if cid not in _pollers or not _pollers[cid].is_alive():
            t = threading.Thread(target=_poll_cluster, args=(cluster,), daemon=True)
            _pollers[cid] = t; t.start()
            log.info(f"Poller → {cluster['name']} ({cluster['host']})")

def remove_poller(cid):
    with _glock:
        _cache.pop(cid, None)
        _pollers.pop(cid, None)

def start_all():
    for c in load_clusters():
        ensure_poller(c)

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

    def _tok(self):
        return auth.token_from_request(dict(self.headers), self.headers.get("Cookie", ""))

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

        if not auth.check_permission(tok, "pve", "readonly"):
            return self._json(401, {"error": "Unauthorized"})

        if path == "/api/clusters":
            global _last_view
            was_idle = (time.time() - _last_view) >= VIEW_GRACE
            _last_view = time.time()
            if was_idle:
                for cc in list(_cache.values()):
                    cc.wake.set()               # data may be up to a minute old: refresh now
            with_hist = parse_qs(urlparse(self.path).query).get("hist", ["1"])[0] != "0"
            clusters = load_clusters()
            out = []
            for c in clusters:
                snap = _cache.get(c["id"], ClusterCache(c["id"])).snap()
                # Inyectar historial por nodo
                nodes_with_hist = []
                for nd in snap.get("data", {}).get("nodes", []):
                    nd = dict(nd)
                    if with_hist:
                        nd["history"] = get_node_history(c["id"], nd["name"])
                    nodes_with_hist.append(nd)
                if "data" in snap:
                    snap = dict(snap)
                    snap["data"] = dict(snap["data"])
                    snap["data"]["nodes"] = nodes_with_hist
                # Agregar alertas de resource
                alerts = []
                for nd in nodes_with_hist:
                    if nd.get("status") == "online":
                        cpu_pct = nd.get("cpu", 0) * 100
                        maxmem  = nd.get("maxmem", 0)
                        mem_pct = (nd.get("mem", 0) / maxmem * 100) if maxmem > 0 else 0
                        if cpu_pct > 80:
                            alerts.append({"node": nd["name"], "type": "cpu", "value": round(cpu_pct, 1)})
                        if mem_pct > 90:
                            alerts.append({"node": nd["name"], "type": "mem", "value": round(mem_pct, 1)})
                out.append({**c, "snap": snap, "alerts": alerts})
            self._json(200, {"clusters": out})

        elif path == "/api/debug":
            out = []
            for cid, cc in _cache.items():
                snap = cc.snap()
                nodes = snap.get("data", {}).get("nodes", [])
                out.append({
                    "id": cid, "error": snap.get("error"),
                    "ts": snap.get("ts"),
                    "nodes": [{
                        "name": n["name"],
                        "status": n["status"],
                        "cpu": n.get("cpu"), "maxcpu": n.get("maxcpu"),
                        "mem": n.get("mem"), "maxmem": n.get("maxmem"),
                        "vms": len(n.get("vms") or []),
                        "cts": len(n.get("cts") or []),
                    } for n in nodes]
                })
            self._json(200, out)

        elif path == "/api/me":
            sess = auth.get_session(tok)
            if sess:
                # Auto-agregar permiso 'pve' si tiene sesión válida de otra app
                if "pve" not in sess.get("permissions", {}):
                    try:
                        users = auth.load_users()
                        uname = sess["username"]
                        if uname in users:
                            lvl = "admin" if users[uname]["permissions"].get("wol") == "admin" else "readonly"
                            users[uname]["permissions"]["pve"] = lvl
                            auth.save_users(users)
                            sess["permissions"]["pve"] = lvl
                    except Exception: pass
                self._json(200, {"username": sess["username"],
                                  "permissions": sess["permissions"]})
            else:
                self._json(200, {})
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

        if not auth.check_permission(tok, "pve", "readonly"):
            return self._json(401, {"error": "Unauthorized"})

        if path == "/api/clusters":
            if not auth.check_permission(tok, "pve", "admin"):
                return self._json(403, {"error": "Requiere admin"})
            host  = (body.get("host","")).strip()
            name  = (body.get("name","")).strip()
            user  = (body.get("user","")).strip()
            tname = (body.get("token_name","")).strip()
            tval  = (body.get("token_value","")).strip()
            port  = int(body.get("port", 8006))
            if not all([host,name,user,tname,tval]):
                return self._json(400, {"error": "Todos los campos son requeridos"})
            clusters = load_clusters()
            if any(c["host"]==host and c["port"]==port for c in clusters):
                return self._json(409, {"error": "Ya existe ese host:puerto"})
            import uuid
            cluster = {"id": str(uuid.uuid4()), "name": name, "host": host,
                       "port": port, "user": user, "token_name": tname,
                       "token_value": tval, "verify_ssl": False}
            clusters.append(cluster)
            save_clusters(clusters)
            ensure_poller(cluster)
            self._json(201, {"cluster": cluster})

        elif path == "/api/test":
            host  = (body.get("host","")).strip()
            port  = int(body.get("port", 8006))
            user  = (body.get("user","")).strip()
            tname = (body.get("token_name","")).strip()
            tval  = (body.get("token_value","")).strip()
            try:
                client = PVEClient(host, port, user, tname, tval)
                ver    = client.version()
                nodes  = client.nodes()
                self._json(200, {"ok": True, "version": ver,
                                 "nodes": len(nodes)})
            except Exception as e:
                self._json(200, {"ok": False, "error": str(e)})

        else:
            self._json(404, {"error": "Not found"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        tok  = self._tok()
        if not auth.check_permission(tok, "pve", "admin"):
            return self._json(403, {"error": "Requiere admin"})
        m = re.match(r'^/api/clusters/([a-zA-Z0-9\-]+)$', path)
        if not m: return self._json(400, {"error": "Invalid ID"})
        clusters = load_clusters()
        new = [c for c in clusters if c["id"] != m.group(1)]
        if len(new) == len(clusters): return self._json(404, {"error": "No encontrado"})
        save_clusters(new)
        remove_poller(m.group(1))
        self._json(200, {"ok": True})

if __name__ == "__main__":
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    # Agregar permiso 'pve' a usuarios existentes
    try:
        users = auth.load_users()
        changed = False
        for udata in users.values():
            if "pve" not in udata.get("permissions", {}):
                udata["permissions"]["pve"] = "admin" if udata["permissions"].get("wol") == "admin" else "readonly"
                changed = True
        if changed:
            auth.save_users(users); log.info("Permisos 'pve' actualizados")
    except Exception as e:
        log.warning(f"Permisos: {e}")

    log.info(f"Proxmox Monitor en http://{HOST}:{PORT} — poll cada {POLL_SEC}s")
    start_all()
    try:
        HTTPServer((HOST, PORT), H).serve_forever()
    except KeyboardInterrupt: sys.exit(0)
