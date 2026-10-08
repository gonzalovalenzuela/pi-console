# Pi Console

**Homelab dashboard** para Raspberry Pi — panel centralizado con autenticación SSO y cinco módulos de gestión.

Autor: Gonzalo Valenzuela &lt;gonzalo@rave.cl&gt;  
Versión: 1.0.4

---

## Módulos

| Módulo | Puerto | Ruta | Descripción |
|--------|--------|------|-------------|
| **WOL Console** | 8080 | `/wol/` | Wake-on-LAN — enciende equipos remotamente |
| **UPS Monitor** | 8081 | `/nut/` | Monitor de UPS vía NUT — batería, carga, autonomía |
| **Admin Panel** | 8082 | `/admin/` | Gestión de usuarios y permisos SSO |
| **Net Monitor** | 8083 | `/net/` | Escáner de red — hosts, OS y puertos abiertos |
| **Proxmox Monitor** | 8084 | `/pve/` | Dashboard de clusters Proxmox VE — nodos, VMs, CTs |

La página de inicio (`/`) sirve desde `/opt/pi-console-home/` vía nginx.

---

## Arquitectura

```
Raspberry Pi
│
├── nginx (puerto 80)  ←── reverse proxy con rutas por módulo
│   └── pi-console.conf
│
├── /opt/pi-console/
│   ├── home/          ←── página de inicio estática
│   ├── auth/          ←── autenticación SSO compartida
│   ├── wol-console/   ←── servidor Python + frontend
│   ├── nut-monitor/   ←── servidor Python + frontend
│   ├── net-monitor/   ←── servidor Python + frontend
│   └── proxmox-monitor/ ←── servidor Python + frontend
│
└── systemd services
    ├── wol-console.service
    ├── nut-monitor.service
    ├── admin-panel.service
    ├── net-monitor.service
    └── proxmox-monitor.service
```

Cada módulo es un servidor HTTP Python 3 independiente. La autenticación se comparte a través de `/opt/pi-console-auth/` (symlinks a `auth/`).

---

## Requisitos

- Raspberry Pi (probado en 3A+) con Raspberry Pi OS / Debian Bookworm
- Python 3.9+
- nginx
- NUT (`nut`, `nut-client`) — para el módulo UPS Monitor
- `nmap` — para el módulo Net Monitor

---

## Instalación

### Opción A — paquete `.deb` (recomendado)

```bash
# Descargar el .deb desde Releases
wget https://github.com/<tu-usuario>/pi-console/releases/latest/download/pi-console_1.0.4_all.deb

# Instalar
sudo dpkg -i pi-console_1.0.4_all.deb
sudo apt-get install -f   # si faltan dependencias
```

El instalador:
- Crea el usuario del sistema `pi-console`
- Instala los servicios systemd y los habilita
- Configura nginx
- Crea el usuario inicial `admin` / `admin` (cambiar en primer login)

### Opción B — desde fuente (desarrollo)

```bash
git clone https://github.com/<tu-usuario>/pi-console.git
cd pi-console

# Copiar archivos
sudo mkdir -p /opt/pi-console
sudo cp -r wol-console nut-monitor net-monitor proxmox-monitor auth /opt/pi-console/
sudo cp -r home /opt/pi-console-home

# Nginx
sudo cp etc/nginx/sites-available/pi-console.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/pi-console.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Instalar servicios manualmente (ver debian/postinst como referencia)
```

---

## Empaquetar .deb

```bash
# El código fuente mapea a la estructura del paquete así:
# <repo>/                →  /opt/pi-console/
# <repo>/etc/            →  /etc/
# <repo>/debian/         →  DEBIAN/ (scripts del paquete)

# Reconstruir el árbol del paquete:
mkdir -p build/pi-console_1.0.4/opt/pi-console
cp -r wol-console nut-monitor net-monitor proxmox-monitor auth home \
      build/pi-console_1.0.4/opt/pi-console/
cp -r etc build/pi-console_1.0.4/
mkdir build/pi-console_1.0.4/DEBIAN
cp debian/* build/pi-console_1.0.4/DEBIAN/
chmod +x build/pi-console_1.0.4/DEBIAN/{postinst,preinst,prerm,postrm}

# Construir
dpkg-deb --build build/pi-console_1.0.4 pi-console_1.0.4_all.deb
```

---

## Internacionalización

La interfaz soporta **inglés** (por defecto) y **español**. El idioma se persiste en `localStorage` con la clave `pi-lang` y se comparte entre todos los módulos.

---

## Estructura del repositorio

```
pi-console/
├── auth/                    # Módulo de autenticación SSO
│   ├── auth.py              # Librería de autenticación compartida
│   ├── admin_panel.py       # Servidor del panel de administración
│   └── static/
│       ├── index.html       # Admin panel UI
│       └── login.html       # Página de login
├── wol-console/
│   ├── server.py
│   └── static/index.html
├── nut-monitor/
│   ├── server.py
│   └── static/index.html
├── net-monitor/
│   ├── server.py
│   └── static/index.html
├── proxmox-monitor/
│   ├── server.py
│   └── static/index.html
├── home/
│   └── index.html           # Página de inicio del dashboard
├── etc/
│   └── nginx/
│       └── sites-available/
│           └── pi-console.conf
├── debian/                  # Scripts de empaquetado .deb
│   ├── control
│   ├── postinst
│   ├── preinst
│   ├── prerm
│   └── postrm
└── README.md
```

---

## Licencia

MIT — uso libre para homelab personal y proyectos propios.
