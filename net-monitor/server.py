#!/usr/bin/env python3
"""
Net Monitor — Escaneo de red sin nmap
Detección: TTL + puertos Python puro + HTTP banner + mDNS
"""
import json, os, re, socket, struct, subprocess, sys, time, logging, threading, ipaddress, ssl
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent / "auth"))
import auth

HOST          = "127.0.0.1"
PORT          = 8083
STATIC_DIR    = Path(__file__).parent / "static"
DATA_FILE     = Path(__file__).parent / "hosts.json"
CONF_FILE     = Path(__file__).parent / "config.json"

def load_config() -> dict:
    try:
        if CONF_FILE.exists():
            return json.loads(CONF_FILE.read_text())
    except Exception: pass
    return {}

def save_config(cfg: dict):
    tmp = CONF_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(CONF_FILE)
NETWORK       = os.environ.get("SCAN_NETWORK",   "192.168.0.0/24")
SCAN_PORTS    = os.environ.get("SCAN_PORTS",     "21,22,23,25,53,80,139,443,445,554,1883,3306,3389,5432,5900,6379,8080,8443,27017,62078")
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", 3600))
PORT_TIMEOUT  = float(os.environ.get("PORT_TIMEOUT", 0.5))
MAX_WORKERS   = int(os.environ.get("MAX_WORKERS", 30))

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("net")

# Pi-hole v6 API
PIHOLE_HOSTS  = os.environ.get("PIHOLE_HOSTS",  "192.168.0.2,192.168.0.5")
PIHOLE_PASS   = os.environ.get("PIHOLE_PASS",   "")
_pihole_cache: dict = {}   # { ip: {hostname, vendor, mac} }
_pihole_lock  = threading.Lock()
_pihole_ts    = 0          # timestamp of last successful fetch

PORT_NAMES = {
    21:"FTP", 22:"SSH", 23:"Telnet", 25:"SMTP", 53:"DNS",
    80:"HTTP", 139:"NetBIOS", 443:"HTTPS", 445:"SMB",
    554:"RTSP", 1883:"MQTT", 3306:"MySQL", 3389:"RDP",
    5432:"PostgreSQL", 5900:"VNC", 6379:"Redis",
    8080:"HTTP-Alt", 8443:"HTTPS-Alt", 27017:"MongoDB", 62078:"iTunes"
}

OS_GROUPS = ["Windows", "Linux", "macOS", "iOS", "IoT", "Android", "BSD", "Desconocido"]

# ─── TTL → OS hint ────────────────────────────────────────────────────────────
def ttl_os_hint(ttl: int) -> str:
    if ttl <= 0:   return ""
    if ttl <= 64:  return "linux_or_apple"   # Linux / macOS / iOS / Android
    if ttl <= 128: return "windows"           # Windows
    return "network_device"                   # routers, IoT

# ─── Ping con TTL ─────────────────────────────────────────────────────────────
def ping_ttl(ip: str) -> tuple[bool, int, float]:
    """Retorna (alive, ttl, latency_ms). TTL=0, latency=0 si no responde."""
    try:
        r = subprocess.run(
            ["ping", "-c1", "-W1", str(ip)],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode != 0:
            return False, 0, 0.0
        # Extraer TTL
        m_ttl = re.search(r"ttl=(\d+)", r.stdout, re.IGNORECASE)
        ttl = int(m_ttl.group(1)) if m_ttl else 0
        # Extraer tiempo en ms
        m_t = re.search(r"time[=<]([\d.]+)\s*ms", r.stdout, re.IGNORECASE)
        latency = float(m_t.group(1)) if m_t else 0.0
        return True, ttl, round(latency, 2)
    except Exception:
        return False, 0, 0.0

# ─── Port scan (Python puro) ──────────────────────────────────────────────────
def check_port(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=PORT_TIMEOUT):
            return True
    except Exception:
        return False

def scan_ports(ip: str, ports: list[int]) -> list[int]:
    """Escanea lista de puertos en paralelo, retorna los abiertos."""
    open_ports = []
    with ThreadPoolExecutor(max_workers=min(len(ports), 20)) as ex:
        futures = {ex.submit(check_port, ip, p): p for p in ports}
        for f in as_completed(futures):
            if f.result():
                open_ports.append(futures[f])
    return sorted(open_ports)

# ─── HTTP banner ──────────────────────────────────────────────────────────────
def http_banner(ip: str, port: int = 80) -> str:
    try:
        with socket.create_connection((ip, port), timeout=2) as s:
            s.sendall(b"HEAD / HTTP/1.0\r\nHost: " + ip.encode() + b"\r\n\r\n")
            banner = s.recv(1024).decode(errors="replace")
        server = re.search(r"Server:\s*(.+)", banner, re.IGNORECASE)
        return server.group(1).strip()[:80] if server else ""
    except Exception:
        return ""

# ─── Pi-hole v6 API ───────────────────────────────────────────────────────────
def _pihole_request(host: str, path: str, method: str = "GET",
                    data: bytes = None, sid: str = None) -> dict:
    url = f"https://{host}{path}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    headers = {"Content-Type": "application/json"}
    if sid:
        headers["X-FTL-SID"] = sid
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, context=ctx, timeout=5) as r:
        return json.loads(r.read().decode())

def _pihole_login(host: str, password: str) -> str | None:
    try:
        d = _pihole_request(host, "/api/auth", "POST",
                            json.dumps({"password": password}).encode())
        sid = d.get("session", {}).get("sid")
        if sid:
            log.info(f"Pi-hole login OK: {host}")
        return sid
    except Exception as e:
        log.warning(f"Pi-hole login error {host}: {e}")
        return None

def _pihole_logout(host: str, sid: str):
    try:
        _pihole_request(host, "/api/auth", "DELETE", sid=sid)
    except Exception:
        pass

def refresh_pihole_cache():
    """Obtiene hostname+vendor+MAC de Pi-hole y llena _pihole_cache."""
    global _pihole_ts
    password = PIHOLE_PASS
    if not password:
        return

    hosts_list = [h.strip() for h in PIHOLE_HOSTS.split(",") if h.strip()]
    new_cache: dict = {}

    for host in hosts_list:
        sid = _pihole_login(host, password)
        if not sid:
            continue
        try:
            data = _pihole_request(host, "/api/network/devices", sid=sid)
            devices = data.get("devices", [])
            for dev in devices:
                mac    = dev.get("hwaddr", "")
                vendor = dev.get("macVendor", "")
                for ip_entry in dev.get("ips", []):
                    ip   = ip_entry.get("ip", "")
                    name = ip_entry.get("name", "").rstrip(".local").rstrip(".")
                    if ip:
                        new_cache[ip] = {
                            "hostname": name,
                            "vendor":   vendor,
                            "mac":      mac,
                        }
            log.info(f"Pi-hole cache: {len(new_cache)} entradas desde {host}")
            break  # Usar solo el primero que responda
        except Exception as e:
            log.warning(f"Pi-hole network/devices error {host}: {e}")
        finally:
            _pihole_logout(host, sid)

    with _pihole_lock:
        _pihole_cache.clear()
        _pihole_cache.update(new_cache)
        _pihole_ts = time.time()

def pihole_lookup(ip: str) -> dict:
    """Retorna {hostname, vendor, mac} desde cache de Pi-hole."""
    # Refrescar cache si tiene más de 30 minutos
    if time.time() - _pihole_ts > 1800 and PIHOLE_PASS:
        threading.Thread(target=refresh_pihole_cache, daemon=True).start()
    with _pihole_lock:
        return _pihole_cache.get(ip, {})

# ─── DNS inverso ──────────────────────────────────────────────────────────────
def resolve_dns(ip: str) -> str:
    try:
        return socket.gethostbyaddr(str(ip))[0]
    except Exception:
        return ""

# ─── mDNS hint (sin librería externa) ────────────────────────────────────────
def mdns_hint(hostname: str) -> str:
    """Si el hostname termina en .local y tiene sufijo típico de Apple."""
    if not hostname:
        return ""
    h = hostname.lower()
    if any(s in h for s in ["iphone", "ipad", "macbook", "imac", "apple"]):
        return "apple"
    return ""

# ─── OS detection (sin nmap) ─────────────────────────────────────────────────
def detect_os(open_ports: list[int], ttl: int, hostname: str, banner: str) -> str:
    ports = set(open_ports)
    ttl_hint = ttl_os_hint(ttl)
    banner_l = banner.lower()
    host_l   = hostname.lower()

    # Banner HTTP delata OS/firmware
    if "windows" in banner_l:                       return "Windows"
    if "mikrotik" in banner_l:                      return "IoT"
    if "synology" in banner_l or "dsm" in banner_l: return "Linux"
    if "nginx" in banner_l or "apache" in banner_l:
        if ttl_hint == "windows":                   return "Windows"
        return "Linux"
    if "ilo" in banner_l or "idrac" in banner_l:    return "Linux"

    # mDNS hostname hints
    if mdns_hint(hostname) == "apple":
        if 62078 in ports: return "iOS"
        return "macOS"

    # Puerto 62078 = iPhone/iPad (iTunes sync)
    if 62078 in ports:                              return "iOS"

    # Windows: SMB o RDP
    if 445 in ports or 3389 in ports:              return "Windows"
    if 139 in ports and 22 not in ports:            return "Windows"

    # macOS: VNC + SSH sin SMB, o bonjour
    if 5900 in ports and 22 in ports and 445 not in ports:
        if ttl_hint != "windows":                   return "macOS"

    # IoT: RTSP, MQTT, sin SSH
    if (554 in ports or 1883 in ports) and 22 not in ports:
        return "IoT"

    # Router/switch: TTL alto, pocos puertos
    if ttl > 200 and len(ports) <= 3:              return "IoT"

    # Linux: SSH sin SMB
    if 22 in ports and 445 not in ports:
        if ttl_hint == "linux_or_apple":            return "Linux"
        if ttl_hint == "windows":                   return "Windows"
        return "Linux"

    # Solo HTTP/HTTPS sin SSH
    if (80 in ports or 443 in ports or 8080 in ports) and 22 not in ports:
        if ttl_hint == "windows":                   return "Windows"
        if ttl > 200:                               return "IoT"
        return "Linux"

    # TTL como último recurso
    if ttl_hint == "windows":                       return "Windows"
    if ttl_hint == "linux_or_apple" and ports:      return "Linux"

    return "Desconocido"

# ─── Scan host completo ───────────────────────────────────────────────────────
def scan_host(ip: str) -> dict | None:
    ip_str = str(ip)
    alive, ttl, latency = ping_ttl(ip_str)
    if not alive:
        return None

    # Pi-hole lookup primero (más confiable que DNS inverso)
    ph        = pihole_lookup(ip_str)
    hostname  = ph.get("hostname") or resolve_dns(ip_str)
    vendor    = ph.get("vendor", "")
    mac       = ph.get("mac", "")

    port_list  = [int(p) for p in SCAN_PORTS.split(",") if p.strip()]
    open_ports = scan_ports(ip_str, port_list)

    # HTTP banner en puertos web abiertos
    banner = ""
    for p in [80, 8080, 443, 8443]:
        if p in open_ports:
            banner = http_banner(ip_str, p)
            if banner: break

    # Mejorar detección de OS con vendor de MAC (Apple, Intel, etc.)
    if not hostname and vendor:
        vendor_l = vendor.lower()
        if "apple" in vendor_l:
            hostname = ""  # Apple sin nombre = probablemente iOS/macOS

    os_guess = detect_os(open_ports, ttl, hostname, banner)

    # Refinar OS con vendor de MAC
    if os_guess == "Desconocido" and vendor:
        vendor_l = vendor.lower()
        if "apple" in vendor_l:
            os_guess = "iOS" if 62078 in open_ports else "macOS"
        elif "microsoft" in vendor_l:
            os_guess = "Windows"

    ports_info = [{"port": p, "service": PORT_NAMES.get(p, "unknown")} for p in open_ports]

    ts_now = int(time.time())
    return {
        "ip":         ip_str,
        "hostname":   hostname,
        "vendor":     vendor,
        "mac":        mac,
        "os":         os_guess,
        "os_raw":     f"TTL={ttl}" + (f" | {banner[:40]}" if banner else ""),
        "ttl":        ttl,
        "latency":    latency,
        "banner":     banner,
        "ports":      ports_info,
        "online":     True,
        "last_seen":  int(time.time()),
        "first_seen": int(time.time()),
    }

# ─── Persistencia ─────────────────────────────────────────────────────────────
def load_hosts() -> dict:
    try:
        if DATA_FILE.exists():
            return json.loads(DATA_FILE.read_text())
    except Exception: pass
    return {}

def save_hosts(hosts: dict):
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(hosts, indent=2))
    tmp.replace(DATA_FILE)

# ─── Scanner ──────────────────────────────────────────────────────────────────
_scan_lock        = threading.Lock()
_scan_status      = {"running": False, "progress": 0, "total": 0,
                     "started": None, "finished": None, "error": None}
_scan_timer       = None
_saved            = load_config()
_current_interval = _saved.get("scan_interval", SCAN_INTERVAL)
# Cargar credenciales Pi-hole guardadas
if not PIHOLE_PASS and _saved.get("pihole_pass"):
    PIHOLE_PASS = _saved["pihole_pass"]
if _saved.get("pihole_hosts"):
    PIHOLE_HOSTS = _saved["pihole_hosts"]

def run_scan(network: str = None, single_ip: str = None):
    global _scan_timer
    with _scan_lock:
        if _scan_status["running"]:
            return

    hosts = load_hosts()

    if single_ip:
        ips = [ipaddress.ip_address(single_ip)]
    else:
        try:
            ips = list(ipaddress.ip_network(network or NETWORK, strict=False).hosts())
        except Exception as e:
            log.error(f"Red inválida: {e}"); return

    _scan_status.update({"running": True, "progress": 0,
                         "total": len(ips), "started": int(time.time()),
                         "finished": None, "error": None})
    log.info(f"Iniciando escaneo: {len(ips)} hosts en {network or NETWORK}")

    def scan_one(ip):
        return str(ip), scan_host(str(ip))

    try:
        completed = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(scan_one, ip): ip for ip in ips}
            for future in as_completed(futures):
                completed += 1
                _scan_status["progress"] = completed
                try:
                    ip_str, result = future.result()
                    if result:
                        existing = hosts.get(ip_str, {})
                        is_new = ip_str not in hosts
                        result["first_seen"] = existing.get("first_seen", result["first_seen"])
                        result["alias"]      = existing.get("alias", "")
                        # Marcar como "nuevo" si nunca se vio antes o apareció en últimas 48h
                        new_threshold = int(time.time()) - 48 * 3600
                        result["new_device"] = is_new or (result["first_seen"] > new_threshold and is_new)
                        # Respetar latencia anterior si ahora no hay datos
                        if result.get("latency", 0) == 0 and existing.get("latency", 0) > 0:
                            result["latency"] = existing["latency"]
                        # Respetar OS editado manualmente
                        if existing.get("os_manual"):
                            result["os"]        = existing["os"]
                            result["os_manual"] = True
                        # Historial de disponibilidad: registrar evento si cambió estado
                        history = existing.get("uptime_history", [])
                        was_online = existing.get("online", False)
                        if not was_online and result["online"]:
                            history.append({"ts": int(time.time()), "event": "up"})
                        history = history[-200:]  # max 200 eventos
                        result["uptime_history"] = history
                        hosts[ip_str] = result
                        log.info(f"[{completed}/{len(ips)}] {ip_str} → {result['os']} | TTL={result['ttl']} | {len(result['ports'])} puertos")
                    else:
                        if ip_str in hosts:
                            if hosts[ip_str].get("online"):  # was online, now offline
                                history = hosts[ip_str].get("uptime_history", [])
                                history.append({"ts": int(time.time()), "event": "down"})
                                hosts[ip_str]["uptime_history"] = history[-200:]
                            hosts[ip_str]["online"] = False
                            hosts[ip_str]["last_seen_offline"] = int(time.time())
                except Exception as e:
                    log.error(f"Error escaneando: {e}")

                if completed % 20 == 0:
                    save_hosts(hosts)

        save_hosts(hosts)
        online = sum(1 for h in hosts.values() if h.get("online"))
        _scan_status.update({"running": False, "finished": int(time.time())})
        log.info(f"Escaneo completado: {online} hosts online de {len(ips)} escaneados")

    except Exception as e:
        _scan_status.update({"running": False, "error": str(e), "finished": int(time.time())})
        log.error(f"Error en escaneo: {e}")

    # Próximo escaneo automático
    if _current_interval > 0:
        _scan_timer = threading.Timer(
            _current_interval,
            lambda: threading.Thread(target=run_scan, daemon=True).start()
        )
        _scan_timer.daemon = True
        _scan_timer.start()
        log.info(f"Próximo escaneo en {_current_interval//60} minutos")
    else:
        log.info("Auto-scan desactivado (modo manual)")

def start_auto_scan():
    # Cargar cache de Pi-hole antes del primer escaneo
    if PIHOLE_PASS:
        threading.Thread(target=refresh_pihole_cache, daemon=True).start()
    threading.Thread(target=run_scan, daemon=True).start()

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

        if not auth.check_permission(tok, "net", "readonly"):
            return self._json(401, {"error": "Unauthorized"})

        if path == "/api/hosts":
            hosts = load_hosts()
            self._json(200, {
                "hosts":   list(hosts.values()),
                "scan":    _scan_status,
                "network": NETWORK,
            })
        elif path == "/api/scan/status":
            self._json(200, _scan_status)

        elif path == "/api/config":
            cfg = load_config()
            self._json(200, {
                "scan_interval":   _current_interval,
                "network":         NETWORK,
                "pihole_hosts":    PIHOLE_HOSTS,
                "pihole_enabled":  bool(PIHOLE_PASS or cfg.get("pihole_pass")),
                "pihole_cache_ts": _pihole_ts,
                "pihole_entries":  len(_pihole_cache),
            })

        elif path == "/api/config":
            self._json(200, {
                "network":       NETWORK,
                "scan_interval": _current_interval,
                "scan_ports":    SCAN_PORTS,
                "max_workers":   MAX_WORKERS,
            })
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
            u = auth.authenticate(body.get("username", ""), body.get("password", ""))
            if not u: return self._json(401, {"error": "Invalid credentials"})
            token = auth.create_session(body["username"], u["permissions"])
            users = auth.load_users()
            must  = users.get(body["username"], {}).get("must_change_password", False)
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

        if not auth.check_permission(tok, "net", "readonly"):
            return self._json(401, {"error": "Unauthorized"})

        if path == "/api/scan/start":
            if _scan_status["running"]:
                return self._json(409, {"error": "Escaneo en progreso"})
            single = (body.get("ip") or "").strip() or None
            threading.Thread(target=run_scan, kwargs={"single_ip": single}, daemon=True).start()
            self._json(200, {"ok": True, "message": single or NETWORK})

        elif path == "/api/pihole/config":
            if not auth.check_permission(tok, "net", "admin"):
                return self._json(403, {"error": "Requiere permiso admin"})
            global PIHOLE_PASS, PIHOLE_HOSTS
            cfg = load_config()
            if "password" in body:
                PIHOLE_PASS = body["password"]
                cfg["pihole_pass"] = body["password"]
            if "hosts" in body:
                PIHOLE_HOSTS = body["hosts"]
                cfg["pihole_hosts"] = body["hosts"]
            save_config(cfg)
            # Refrescar cache inmediatamente
            if PIHOLE_PASS:
                threading.Thread(target=refresh_pihole_cache, daemon=True).start()
            self._json(200, {"ok": True})

        elif path == "/api/hosts/update":
            if not auth.check_permission(tok, "net", "admin"):
                return self._json(403, {"error": "Requiere permiso admin"})
            ip = (body.get("ip") or "").strip()
            if not ip: return self._json(400, {"error": "IP requerida"})
            hosts = load_hosts()
            if ip not in hosts: return self._json(404, {"error": "Host no encontrado"})
            if "alias" in body:
                hosts[ip]["alias"] = str(body["alias"])[:40]
            if "os" in body:
                hosts[ip]["os"]        = str(body["os"])[:30]
                hosts[ip]["os_manual"] = True   # marcar como editado manualmente
            if "group" in body:
                hosts[ip]["group"] = str(body["group"])[:20]
            save_hosts(hosts)
            self._json(200, {"ok": True})

        elif path == "/api/scan/interval":
            if not auth.check_permission(tok, "net", "admin"):
                return self._json(403, {"error": "Requiere permiso admin"})
            global _current_interval, _scan_timer
            interval = int(body.get("interval", 3600))
            if interval < 0 or (interval > 0 and interval < 60):
                return self._json(400, {"error": "Minimum 60 seconds or 0 for manual"})
            # Cancelar timer anterior
            if _scan_timer:
                _scan_timer.cancel()
                _scan_timer = None
            _current_interval = interval
            save_config({"scan_interval": interval})
            # Programar nuevo timer si no es manual
            if interval > 0:
                _scan_timer = threading.Timer(
                    interval,
                    lambda: threading.Thread(target=run_scan, daemon=True).start()
                )
                _scan_timer.daemon = True
                _scan_timer.start()
                log.info(f"Intervalo de escaneo cambiado a {interval//60} minutos")
            else:
                log.info("Auto-scan desactivado")
            self._json(200, {"ok": True, "interval": interval})

        elif path == "/api/hosts/delete":
            if not auth.check_permission(tok, "net", "admin"):
                return self._json(403, {"error": "Requiere permiso admin"})
            ip = (body.get("ip") or "").strip()
            hosts = load_hosts()
            if ip in hosts: del hosts[ip]; save_hosts(hosts)
            self._json(200, {"ok": True})

        else:
            self._json(404, {"error": "Not found"})

if __name__ == "__main__":
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    # Agregar permiso 'net' a usuarios existentes
    try:
        users = auth.load_users()
        changed = False
        for udata in users.values():
            if "net" not in udata.get("permissions", {}):
                udata["permissions"]["net"] = "admin" if udata["permissions"].get("wol") == "admin" else "readonly"
                changed = True
        if changed:
            auth.save_users(users); log.info("Permisos 'net' actualizados")
    except Exception as e:
        log.warning(f"No se pudo actualizar permisos: {e}")

    log.info(f"Net Monitor en http://{HOST}:{PORT}")
    log.info(f"Red: {NETWORK} | Workers: {MAX_WORKERS} | Auto-scan: {SCAN_INTERVAL//60}min")
    log.info(f"Detección: TTL + puertos Python + HTTP banner (sin nmap)")
    start_auto_scan()
    try:
        HTTPServer((HOST, PORT), H).serve_forever()
    except KeyboardInterrupt: sys.exit(0)
