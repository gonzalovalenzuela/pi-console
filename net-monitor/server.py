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
SCAN_PORTS    = os.environ.get("SCAN_PORTS",     "21,22,23,25,53,80,111,135,139,443,445,548,554,873,1883,2049,3260,3306,3389,5000,5001,5357,5432,5555,5900,6379,7547,8009,8080,8291,8443,9100,27017,62078")
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
    8080:"HTTP-Alt", 8443:"HTTPS-Alt", 27017:"MongoDB", 62078:"iTunes",
    111:"RPC", 135:"MSRPC", 548:"AFP", 873:"rsync", 2049:"NFS", 3260:"iSCSI",
    5000:"DSM/HTTP", 5001:"DSM/HTTPS", 5357:"WSDD", 5555:"ADB", 7547:"TR-069",
    8009:"Cast", 8291:"Winbox", 9100:"Print"
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

# ─── Device identification (OS + device type, no nmap) ───────────────────────
DEVICE_TYPES = ["computer", "router", "switch", "ap", "storage", "other"]

_OUI_PATHS = ["/usr/share/ieee-data/oui.txt", "/var/lib/ieee-data/oui.txt",
              "/usr/share/misc/oui.txt"]
_oui_db: dict | None = None
_oui_lock = threading.Lock()

def _load_oui() -> dict:
    """Lazy-load the IEEE OUI table (package ieee-data, optional)."""
    global _oui_db
    with _oui_lock:
        if _oui_db is not None:
            return _oui_db
        db = {}
        for p in _OUI_PATHS:
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if "(hex)" in line:
                            pre, _, name = line.partition("(hex)")
                            db[pre.strip().replace("-", "").upper()] = name.strip()
                if db: break
            except Exception:
                continue
        _oui_db = db
        return db

def oui_vendor(mac: str) -> str:
    m = re.sub(r"[^0-9A-Fa-f]", "", mac or "").upper()
    return _load_oui().get(m[:6], "") if len(m) >= 6 else ""

def mac_is_private(mac: str) -> bool:
    """Locally-administered bit set → randomized / private address (phones)."""
    m = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    try:    return bool(int(m[:2], 16) & 0x02)
    except Exception: return False

def arp_mac(ip: str) -> str:
    try:
        with open("/proc/net/arp") as f:
            for line in list(f)[1:]:
                c = line.split()
                if len(c) >= 4 and c[0] == ip and c[3] != "00:00:00:00:00:00":
                    return c[3].lower()
    except Exception:
        pass
    return ""

_gw_cache = {"ts": 0, "ip": ""}
def default_gateway() -> str:
    if time.time() - _gw_cache["ts"] < 300:
        return _gw_cache["ip"]
    gw = ""
    try:
        with open("/proc/net/route") as f:
            for line in list(f)[1:]:
                c = line.split()
                if len(c) > 2 and c[1] == "00000000":
                    gw = socket.inet_ntoa(struct.pack("<L", int(c[2], 16)))
                    break
    except Exception:
        pass
    _gw_cache.update(ts=time.time(), ip=gw)
    return gw

def _has(text: str, words) -> bool:
    return any(w in text for w in words)

V_STORAGE = ("synology", "qnap", "western digital", "buffalo", "asustor", "terramaster",
             "drobo", "seagate", "lacie", "ixsystems", "readynas", "thecus", "iomega", "ugreen")
V_ROUTER  = ("mikrotik", "routerboard", "sagemcom", "technicolor", "arris", "zyxel", "tenda",
             "fortinet", "juniper", "draytek", "peplink", "sierra wireless", "teltonika", "netcomm")
V_AP      = ("ruckus", "aruba", "engenius", "cambium", "meraki", "aerohive", "grandstream networks")
V_NETGEAR = ("ubiquiti", "tp-link", "tp link", "d-link", "netgear", "cisco", "linksys", "huawei technologies", "hewlett packard enterprise")
V_ANDROID = ("samsung", "xiaomi", "oppo", "oneplus", "vivo", "motorola", "realme", "honor",
             "tecno", "infinix", "hmd global", "nokia", "zte", "lenovo mobile", "google, inc", "google llc")
H_WIN     = re.compile(r"^(desktop|laptop|win|pc|workstation|surface)[-_]", re.I)
H_ANDROID = re.compile(r"android|galaxy|pixel|redmi|xiaomi|poco|oneplus|oppo|realme|huawei|honor|moto[-_ ]|^sm-|^sm[a-z]\d", re.I)
H_STORAGE = re.compile(r"nas|diskstation|synology|qnap|truenas|freenas|openmediavault|\bomv\b|unraid|storage|backup", re.I)
H_ROUTER  = re.compile(r"router|gateway|gw\d*\b|firewall|opnsense|pfsense|mikrotik|openwrt|fritz|^rt[-_]", re.I)
H_AP      = re.compile(r"(^|[-_.])(ap|uap|wap|wifi|wlan|unifi)([-_.\d]|$)|access.?point|eap\d", re.I)
H_SWITCH  = re.compile(r"switch|(^|[-_.])(sw|usw)([-_.\d]|$)|poe", re.I)

def identify(ip: str, open_ports: list, ttl: int, hostname: str, banner: str,
             vendor: str, mac: str) -> tuple[str, str]:
    """Return (os, device_type) from scored heuristics."""
    ports = set(open_ports)
    host  = (hostname or "").lower().split(".")[0]
    ban   = (banner or "").lower()
    ven   = (vendor or "").lower()
    gw    = (ip == default_gateway())
    web   = bool(ports & {80, 443, 8080, 8443})
    smb   = bool(ports & {445, 139})
    private_mac = mac_is_private(mac)

    # ── Device type scoring ──
    s = {t: 0 for t in DEVICE_TYPES}
    # storage
    if _has(ven, V_STORAGE):                          s["storage"] += 4
    if _has(ban, ("synology", "qnap", "dsm", "openmediavault", "truenas", "nas")): s["storage"] += 4
    if H_STORAGE.search(host):                        s["storage"] += 4
    if ports & {5000, 5001}:                          s["storage"] += 2
    if ports & {2049, 548, 3260, 873}:                s["storage"] += 3
    if smb and ttl and ttl <= 64 and 3389 not in ports and 135 not in ports:
        s["storage"] += 2
    # router
    if gw:                                            s["router"] += 6
    if _has(ven, V_ROUTER):                           s["router"] += 4
    if _has(ban, ("mikrotik", "routeros", "openwrt", "dd-wrt", "pfsense", "opnsense", "fortigate")): s["router"] += 4
    if H_ROUTER.search(host):                         s["router"] += 4
    if ports & {8291, 8728, 7547}:                    s["router"] += 4
    if 53 in ports and web and not smb:               s["router"] += 1
    # access point
    if _has(ven, V_AP):                               s["ap"] += 4
    if _has(ban, ("unifi", "ruckus", "aruba", "cambium", "ubnt")): s["ap"] += 3
    if H_AP.search(host):                             s["ap"] += 5
    # switch
    if H_SWITCH.search(host):                         s["switch"] += 5
    if _has(ban, ("procurve", "switch", "cisco", "netgear gs", "crs")): s["switch"] += 3
    # generic network-gear vendors: need web UI and no general-purpose ports
    if _has(ven, V_NETGEAR) and web and not (ports & {445, 3389, 5900}):
        for t in ("switch",): s[t] += 2
        s["router"] += 1
        s["ap"] += 1
        if "ubiquiti" in ven: s["ap"] += 3
    if ttl > 128 and len(ports) <= 4 and not gw:      s["switch"] += 2
    # computers
    if ports & {3389, 5900} or (22 in ports and not web): s["computer"] += 1
    if H_WIN.search(host) or "iphone" in host or "macbook" in host: s["computer"] += 3
    if "windows" in ban or "microsoft" in ban:        s["computer"] += 3

    best = max(DEVICE_TYPES[:-1], key=lambda t: s[t])
    dtype = best if s[best] >= 4 else ("computer" if s["computer"] >= 1 else "other")

    # ── OS ──
    win_strong = ("windows" in ban or "microsoft" in ban or "iis" in ban or H_WIN.search(host)
                  or "microsoft" in ven)
    if dtype in ("router", "switch", "ap"):
        os_name = "IoT"
    elif dtype == "storage":
        os_name = "Linux"
    elif 62078 in ports or "iphone" in host or "ipad" in host:
        os_name = "iOS"
    elif "apple" in ven or _has(host, ("macbook", "imac", "mac-mini", "macmini", "mac-pro")):
        os_name = "macOS" if not (62078 in ports) else "iOS"
    elif win_strong and (not ttl or ttl > 64 or "windows" in ban):
        os_name = "Windows"
    elif ttl > 64 and ttl <= 128 and (3389 in ports or (135 in ports and smb) or 5357 in ports):
        os_name = "Windows"
    elif ttl > 64 and ttl <= 128 and smb and 22 not in ports:
        os_name = "Windows"
    elif (H_ANDROID.search(host) or _has(ven, V_ANDROID) or 5555 in ports) and 22 not in ports and not smb:
        os_name = "Android"
    elif private_mac and not ports and ttl and ttl <= 64 and (not host or H_ANDROID.search(host)):
        os_name = "Android"
    elif (554 in ports or 1883 in ports or 9100 in ports or 8009 in ports) and 22 not in ports:
        os_name = "IoT"
    elif "freebsd" in ban or "openbsd" in ban:
        os_name = "BSD"
    elif 22 in ports or (ttl and ttl <= 64 and ports):
        os_name = "Linux"
    elif ttl > 128:
        os_name = "IoT"
    elif ttl > 64:
        os_name = "Windows" if ports else "Desconocido"
    else:
        os_name = "Desconocido"

    if dtype == "other" and os_name in ("Windows", "Linux", "macOS", "Android", "iOS"):
        dtype = "computer"
    return os_name, dtype

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

    # MAC from the ARP table (the ping just populated it) and vendor from OUI
    if not mac:
        mac = arp_mac(ip_str)
    if not vendor and mac:
        vendor = oui_vendor(mac)

    os_guess, dev_type = identify(ip_str, open_ports, ttl, hostname, banner, vendor, mac)

    ports_info = [{"port": p, "service": PORT_NAMES.get(p, "unknown")} for p in open_ports]

    ts_now = int(time.time())
    return {
        "ip":         ip_str,
        "hostname":   hostname,
        "vendor":     vendor,
        "mac":        mac,
        "os":         os_guess,
        "device_type": dev_type,
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
                        # Keep manually chosen device type
                        if existing.get("type_manual"):
                            result["device_type"] = existing.get("device_type", result["device_type"])
                            result["type_manual"] = True
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
                        log.debug(f"[{completed}/{len(ips)}] {ip_str} → {result['os']} | TTL={result['ttl']} | {len(result['ports'])} puertos")
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
                return self._json(409, {"error": "Scan already running"})
            single = (body.get("ip") or "").strip() or None
            threading.Thread(target=run_scan, kwargs={"single_ip": single}, daemon=True).start()
            self._json(200, {"ok": True, "message": single or NETWORK})

        elif path == "/api/pihole/config":
            if not auth.check_permission(tok, "net", "admin"):
                return self._json(403, {"error": "Admin permission required"})
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
                return self._json(403, {"error": "Admin permission required"})
            ip = (body.get("ip") or "").strip()
            if not ip: return self._json(400, {"error": "IP required"})
            hosts = load_hosts()
            if ip not in hosts: return self._json(404, {"error": "Host not found"})
            if "alias" in body:
                hosts[ip]["alias"] = str(body["alias"])[:40]
            if "os" in body:
                hosts[ip]["os"]        = str(body["os"])[:30]
                hosts[ip]["os_manual"] = True   # marcar como editado manualmente
            if "device_type" in body:
                dt = str(body["device_type"])
                if dt == "auto":
                    hosts[ip].pop("type_manual", None)   # back to auto-detection on next scan
                    dt = hosts[ip].get("device_type", "other")
                if dt not in DEVICE_TYPES:
                    return self._json(400, {"error": "Invalid device type"})
                hosts[ip]["device_type"] = dt
                if body["device_type"] != "auto":
                    hosts[ip]["type_manual"] = True
            if "group" in body:
                hosts[ip]["group"] = str(body["group"])[:20]
            save_hosts(hosts)
            self._json(200, {"ok": True})

        elif path == "/api/scan/interval":
            if not auth.check_permission(tok, "net", "admin"):
                return self._json(403, {"error": "Admin permission required"})
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
                return self._json(403, {"error": "Admin permission required"})
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
