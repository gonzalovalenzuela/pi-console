#!/usr/bin/env python3
"""Panel de administración de usuarios — corre en puerto 8082."""
import json, sys, time, logging, re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import auth

HOST = "127.0.0.1"
PORT = 8082
STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("admin")

VALID_PERMS = ("readonly", "execute", "admin", "none")

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
        except FileNotFoundError:
            self._json(404, {"error": "Not found"})

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        tok  = self._tok()

        if path in ("/", "/index.html"):
            return self._file(STATIC_DIR / "index.html", "text/html; charset=utf-8")

        if not auth.check_permission(tok, "wol", "admin") and \
           not auth.check_permission(tok, "nut", "admin"):
            return self._json(401, {"error": "No autorizado"})

        if path == "/api/users":
            users = auth.load_users()
            out   = [{"username": u, "permissions": d["permissions"],
                      "must_change_password": d.get("must_change_password", False),
                      "created": d.get("created")}
                     for u, d in users.items()]
            self._json(200, {"users": out})
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
        if body is None: return self._json(400, {"error": "Cuerpo inválido"})

        # Login público
        if path == "/api/login":
            u = auth.authenticate(body.get("username",""), body.get("password",""))
            if not u: return self._json(401, {"error": "Credenciales incorrectas"})
            # Solo admins pueden acceder al panel
            if auth.LEVELS.get(u["permissions"].get("wol",""),0) < 3 and \
               auth.LEVELS.get(u["permissions"].get("nut",""),0) < 3:
                return self._json(403, {"error": "Solo administradores pueden acceder al panel"})
            token = auth.create_session(body["username"], u["permissions"])
            users = auth.load_users()
            must  = users.get(body["username"],{}).get("must_change_password", False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie",
                f"session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400")
            br = json.dumps({"ok": True, "token": token, "permissions": u["permissions"],
                             "must_change_password": must}).encode()
            self.send_header("Content-Length", str(len(br)))
            self.end_headers(); self.wfile.write(br); return

        if path == "/api/logout":
            auth.delete_session(tok); return self._json(200, {"ok": True})

        if not auth.check_permission(tok, "wol", "admin") and \
           not auth.check_permission(tok, "nut", "admin"):
            return self._json(401, {"error": "No autorizado"})

        sess = auth.get_session(tok)
        me   = sess["username"] if sess else ""

        if path == "/api/users":
            # Crear usuario
            uname = (body.get("username") or "").strip()
            pwd   = (body.get("password") or "").strip()
            wol_p = body.get("wol_permission","readonly")
            nut_p = body.get("nut_permission","readonly")
            if not uname or not pwd:
                return self._json(400, {"error": "username y password requeridos"})
            if not re.match(r'^[a-zA-Z0-9_\-]{2,32}$', uname):
                return self._json(400, {"error": "Username inválido (2-32 chars alfanuméricos)"})
            if wol_p not in VALID_PERMS or nut_p not in VALID_PERMS:
                return self._json(400, {"error": "Permiso inválido"})
            users = auth.load_users()
            if uname in users:
                return self._json(409, {"error": "Usuario ya existe"})
            users[uname] = {
                "password_hash": auth._hash(pwd),
                "permissions": {"wol": wol_p, "nut": nut_p},
                "created": int(time.time()),
                "must_change_password": body.get("must_change_password", False),
            }
            auth.save_users(users)
            log.info(f"Usuario creado: {uname} por {me}")
            self._json(201, {"ok": True})

        elif path == "/api/change_password":
            # Cambiar propia contraseña o la de cualquiera (admin)
            target = (body.get("username") or me).strip()
            new_pw = (body.get("new_password") or "").strip()
            if not new_pw or len(new_pw) < 6:
                return self._json(400, {"error": "La contraseña debe tener al menos 6 caracteres"})
            # No-admin solo puede cambiar la suya
            if target != me and not auth.check_permission(tok, "wol", "admin"):
                return self._json(403, {"error": "Solo puedes cambiar tu propia contraseña"})
            users = auth.load_users()
            if target not in users:
                return self._json(404, {"error": "Usuario no encontrado"})
            users[target]["password_hash"] = auth._hash(new_pw)
            users[target]["must_change_password"] = False
            auth.save_users(users)
            log.info(f"Contraseña cambiada: {target} por {me}")
            self._json(200, {"ok": True})

        else:
            self._json(404, {"error": "Not found"})

    def do_PUT(self):
        path = urlparse(self.path).path.rstrip("/")
        tok  = self._tok()
        body = self._body()
        if body is None: return self._json(400, {"error": "Cuerpo inválido"})

        if not auth.check_permission(tok, "wol", "admin") and \
           not auth.check_permission(tok, "nut", "admin"):
            return self._json(401, {"error": "No autorizado"})

        sess = auth.get_session(tok)
        me   = sess["username"] if sess else ""

        m = re.match(r'^/api/users/([a-zA-Z0-9_\-]+)$', path)
        if m:
            uname = m.group(1)
            wol_p = body.get("wol_permission")
            nut_p = body.get("nut_permission")
            if wol_p and wol_p not in VALID_PERMS:
                return self._json(400, {"error": "Permiso WOL inválido"})
            if nut_p and nut_p not in VALID_PERMS:
                return self._json(400, {"error": "Permiso NUT inválido"})
            # Proteger al propio admin de quitarse permisos
            if uname == me and (wol_p == "none" or nut_p == "none"):
                return self._json(400, {"error": "No puedes quitarte tus propios permisos de admin"})
            users = auth.load_users()
            if uname not in users:
                return self._json(404, {"error": "Usuario no encontrado"})
            if wol_p: users[uname]["permissions"]["wol"] = wol_p
            if nut_p: users[uname]["permissions"]["nut"] = nut_p
            auth.save_users(users)
            log.info(f"Permisos actualizados: {uname} por {me}")
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "Not found"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        tok  = self._tok()
        if not auth.check_permission(tok, "wol", "admin") and \
           not auth.check_permission(tok, "nut", "admin"):
            return self._json(401, {"error": "No autorizado"})
        sess = auth.get_session(tok)
        me   = sess["username"] if sess else ""
        m = re.match(r'^/api/users/([a-zA-Z0-9_\-]+)$', path)
        if not m: return self._json(400, {"error": "Usuario inválido"})
        uname = m.group(1)
        if uname == me: return self._json(400, {"error": "No puedes eliminarte a ti mismo"})
        users = auth.load_users()
        if uname not in users: return self._json(404, {"error": "No encontrado"})
        del users[uname]; auth.save_users(users)
        log.info(f"Usuario eliminado: {uname} por {me}")
        self._json(200, {"ok": True})

if __name__ == "__main__":
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"Admin Panel en http://{HOST}:{PORT}")
    try:
        HTTPServer((HOST, PORT), H).serve_forever()
    except KeyboardInterrupt: sys.exit(0)
