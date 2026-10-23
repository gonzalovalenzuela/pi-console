# Pi Console

**Homelab dashboard** for Raspberry Pi: UPS, network, Proxmox, Wake-on-LAN and administration in one place. No external dependencies: standard-library Python + nginx.

[Español → README.md](README.md)

<img src="docs/screenshots/1920x1080/light/overview.png" alt="Overview" width="900">

**Contents:** [Modules](#modules) · [Screenshots](#screenshots) · [Requirements](#requirements) · [Install](#install) · [Update](#update) · [First login](#first-login) · [Features](#features-by-module) · [HTTPS](#https) · [Backups](#backups) · [Health and operations](#health-and-operations) · [Settings](#settings) · [Security](#security) · [Layout](#layout) · [License](#license)

---

## Modules

| Module | Path | Port | What it does |
|---|---|---|---|
| **Overview** | `/overview/` | 8085 | Status of everything on one screen, event timeline and kiosk mode |
| **UPS Monitor** | `/nut/` | 8081 | Reads UPS units through NUT: battery, load, runtime, power, voltages, temperature, history and CSV |
| **Net Monitor** | `/net/` | 8083 | Scans the network: hosts, type, OS, ports, MAC and vendor |
| **Proxmox Monitor** | `/pve/` | 8084 | Proxmox VE clusters: nodes, VMs, CTs and Ceph |
| **WOL Console** | `/wol/` | 8080 | Powers on machines with Wake-on-LAN |
| **Admin Panel** | `/admin/` | 8082 | Users, permissions, sessions, backups and system health |

Each user can reorder the menu. The home page (`/`) has one card per module.

## Screenshots

<img src="docs/screenshots/1920x1080/light/ups.png" width="290"> <img src="docs/screenshots/1920x1080/light/net.png" width="290"> <img src="docs/screenshots/1920x1080/dark/proxmox.png" width="290">

All screens (light and dark, 4 sizes) are in [`docs/screenshots/`](docs/screenshots/). The data is demo data.

---

## Requirements

- Raspberry Pi (tested on 3A+) or a VM/x86 machine, with Raspberry Pi OS, DietPi, Debian 12+ or Ubuntu.
- Python 3.9+, nginx, `sudo`, `snmp` and NUT (`nut`, `nut-client`). `apt` installs them with the `.deb`.
- Optional: `ieee-data` (local MAC vendor database).

## Install

```bash
wget https://github.com/gonzalovalenzuela/pi-console/releases/download/1.3/pi-console_1.3_all.deb
sudo apt-get update
sudo apt-get install -y ./pi-console_1.3_all.deb
```

Use `apt-get install ./file.deb`, not `dpkg -i`, so `apt` installs the dependencies. Then open `http://<pi-ip>/`.

The installer creates the `pi-console` system user, the systemd services, the nginx config and the `admin` user with a **random password**, shown when it finishes. If you lost it: `sudo cat /var/lib/pi-console/initial-admin-password`.

**From source** (development): copy the modules to `/opt/pi-console`, install the config from `etc/nginx/` and create the services using `debian/postinst` as a guide.

## Update

```bash
wget https://github.com/gonzalovalenzuela/pi-console/releases/download/1.3/pi-console_1.3_all.deb
sudo apt-get install -y ./pi-console_1.3_all.deb
pi-console-health
```

- Works from any 1.1.x or 1.2.x. Data in `/var/lib/pi-console` is kept and also copied to `/var/backups/pi-console`.
- Installing a **lower** version number than the current one needs `--allow-downgrades`.
- After updating, reload the page (Ctrl+Shift+R). On iPad, close and reopen the page.
- Changes for each version are in [CHANGELOG.md](CHANGELOG.md).

## First login

1. Sign in as `admin` with the password the installer showed.
2. You must choose a new password (minimum 8 characters) before using any module.
3. Create your users in the Admin Panel. For any user you can tick "must change password" when creating them or resetting their password.

---

## Features by module

### Overview
- **Global status** (All good / Attention / Failure) and a list of what needs attention, linked to the module.
- **UPS:** state, battery, load, runtime, power and 24 h charts.
- **Proxmox:** nodes online, running VMs and CTs, CPU and memory (12 h chart), Ceph health.
- **Network:** hosts online, known and offline, last scan, device types and new hosts from the last 48 h.
- **Raspberry Pi:** temperature, CPU, memory, disk, uptime and power supply status. On a Raspberry Pi only, it adds a 24 h temperature chart with under-voltage and throttling marks (kept 7 days in `metrics.db`).
- **Event timeline:** important changes with their time (UPS on battery, node down, Ceph change, new or vanished hosts). The modules record them even when nobody has the page open: last 300 events or 30 days.
- Everyone sees only the modules they can access.
- **Refresh:** interval selector (10 s, 30 s, 1, 2, 5 min or manual with ↻), per browser. A hidden tab makes no requests.

**Kiosk mode** (*Kiosk* button or `/overview/?kiosk=1`): full screen, large text, no buttons or cursor, screen kept awake. A touch or the mouse shows the exit button. URL options: `?zoom=0.8` (0.5 to 2) and `?autoscroll=1` (scrolls up and down by itself if the content does not fit). A read-only user is recommended.

**iPad as a display:** open `http://PI-IP/overview/?kiosk=1` in Safari → Share → *Add to Home Screen*, with *Open as Web App* on. To stop it from locking: *Guided Access* or *Auto-Lock: Never*.

### UPS Monitor
- Starts with no servers. An admin adds one (name, `upsd` host and port, default 3493) and can test the connection before saving.
- Polls `upsd` every 10 s and keeps history in SQLite (WAL, 1 year).
- Voltage, power and temperature charts (if the UPS reports it). CSV export.
- Shows the clients connected to each UPS.

### Net Monitor
- **Network:** detected automatically (the Pi's /24) or set with `SCAN_NETWORK`.
- **Scanning:** a new install scans nothing until you ask (*Run initial scan* button). Automatic scanning is enabled in *Settings* (minimum 60 s).
- **Detection:** ping (TTL), ports and HTTP banner. It does not use `nmap`.
- **MAC and vendor**, in this order: Pi-hole, local ARP, SNMP (ARP table of a router or switch). Vendors come from the Wireshark `manuf` list (weekly download) or `ieee-data`.
- **Device types:** computer, phone, tablet, router, switch, access point, storage, TV, camera, printer, game console, server, IP phone, UPS, smart speaker and other. OS, type and group can be edited by hand.
- **Trash button** to remove a host from the list (admins only). If it is still connected, the next scan discovers it again.
- Hovering (or tapping on iPad) an IP in UPS, Proxmox, WOL or Overview shows a card with the host's data.
- SNMP credentials and the Pi-hole password are stored with 600 permissions and the API never returns them.

### Proxmox Monitor
- Polls each cluster every 5 s with the page open and every 60 s when idle.
- Node order and pinned nodes are saved per cluster (admin only).
- When adding a cluster you must confirm its certificate SHA-256 fingerprint, which is then pinned. If the certificate changes, the token is not sent.

### WOL Console
- Sends magic packets (at most 10 per minute per IP).
- Picks hosts found by Net Monitor (name, MAC, IP and category) and uses the latest IP if DHCP changed it.
- Net Monitor tags hosts registered here with *WOL*.

### Admin Panel
- Users and per-module permissions (none, read-only, execute, admin).
- **Active sessions:** signed-in devices (user, browser, IP, last activity); close one or all the others.
- **System health** card and **Backups** (Teleporter).

### All modules
- **Language:** English (default) or Spanish; shared across modules.
- **24H/12H time** (since 1.2.2a): button next to the language buttons. Default 24 h; stored in the browser.
- **Remember me** at login: 1 day, 1 week, 1 month or forever. Unticked, the session lasts 24 h.

---

## HTTPS

By default it is served over HTTP on port 80, meant for a trusted local network. To encrypt:

```bash
sudo pi-console-https enable --redirect                                  # self-signed certificate
sudo pi-console-https enable --redirect --cert fullchain.pem --key privkey.pem   # your own certificate (for example Let's Encrypt)
sudo pi-console-https status
sudo pi-console-https disable
```

`--redirect` sends port 80 to HTTPS, marks the cookie `Secure` and sends HSTS. With the self-signed certificate the browser warns once. On iPad/iPhone you must install it and trust it (Settings → General → About → Certificate Trust Settings). With your own certificate, use the name in the certificate, not the IP.

---

## Backups

### Teleporter (manual)
```bash
sudo teleporter backup ~/pi-console-$(date +%Y%m%d).tar.gz   # create
teleporter check ~/pi-console-20261009.tar.gz                # verify, changes nothing
sudo teleporter restore ~/pi-console-20261009.tar.gz         # restore (-y to skip the question)
```

- **Includes:** users, WOL, UPS (servers and history), Net Monitor (hosts and SNMP), Proxmox, Overview histories, and the NUT and nginx config. **Does not include** sessions, HTTPS certificates or the SFTP backup key.
- **Restoring NUT and nginx** is only done from the console with `--nut` and `--nginx`; the panel does not allow it.
- **Before restoring**, a copy of the current state is saved in `/var/backups/pi-console/`.
- **Limits:** an archive that expands to more than 2 GiB is rejected; uploads from the panel are capped at 200 MB.
- **From the panel** (`/admin/` → *Backup & restore*): create and download, upload, verify and restore. Only admins of every module can use it.
- **Moving to another Pi:** install the `.deb`, sign in as `admin`, upload the backup and press *Restore*.
- The file holds password hashes and tokens (600 permissions): keep it somewhere private.

### Automatic SFTP backup
A daily cron job (03:17) makes a backup, verifies it and uploads it over SFTP. It ships installed and **disabled** until `SFTP_USER` is set. It only uses an SSH key.

```bash
sudo pi-console-sftp-backup setup       # creates the SSH key and shows the public one
sudo nano /etc/pi-console/backup.conf   # set SFTP_USER (and SFTP_HOST, SFTP_DIR)
sudo pi-console-sftp-backup test        # checks connection, folder and write access
sudo pi-console-sftp-backup run         # back up now
sudo pi-console-sftp-backup status      # result of the last run
```

- **Encryption:** the file is uploaded encrypted with gpg (AES-256). The passphrase is created automatically in `/etc/pi-console/backup_passphrase`: **keep a copy off the Pi** (`sudo cat /etc/pi-console/backup_passphrase`); without it no backup can be opened.
- **Restore:** download the `.tar.gz.gpg`, run `sudo pi-console-sftp-backup decrypt file.tar.gz.gpg`, then `sudo teleporter restore file.tar.gz`.
- **Safe:** uploaded as `.part` and renamed; the remote size is compared; the server's host key is pinned on first connection.
- **Retention:** 30 copies on the storage (`KEEP_REMOTE`) and 7 on the Pi (`KEEP_LOCAL`). Only files named `pi-console-auto-<host>-<date>_<time>.tar.gz` are deleted.
- Result in `/var/log/pi-console/backup.status`; errors with `journalctl -t pi-console-sftp-backup`. Change the schedule in `/etc/cron.d/pi-console-sftp-backup`.
- Use a dedicated SFTP user with access to that folder only.

---

## Health and operations

```bash
pi-console-health         # summary: exit 0 = ok, 1 = degraded, 2 = failed (-j for JSON)
pi-console-resources      # memory and CPU per service (-w refreshes every 2 s)
systemctl status wol-console pi-console-ups admin-panel net-monitor proxmox-monitor pi-console-overview
journalctl -u net-monitor -f        # logs of one service
sudo systemctl restart net-monitor  # restart one
```

Each module answers `GET /api/health` (200 = ok or degraded, 503 = failed). Without a session it only shows levels. It detects a stopped service, a corrupt data file, a nearly full disk, a locked history database, a stuck scan and `upsd` or Proxmox not answering. On a Raspberry Pi it also warns about under-voltage or throttling; that warning comes from the firmware and only clears on reboot.

| Service | Module |
|---|---|
| `wol-console` | WOL Console |
| `pi-console-ups` | UPS Monitor (formerly `nut-monitor`, which clashed with NUT's `upsmon`) |
| `admin-panel` | Admin Panel |
| `net-monitor` | Net Monitor |
| `proxmox-monitor` | Proxmox Monitor |
| `pi-console-overview` | Overview |

**Uninstall:** `sudo apt remove pi-console` stops the services and saves a copy of the data in `/var/backups/pi-console`. `sudo apt purge pi-console` also removes the code, services, nginx site and the `pi-console` user. In both cases `/var/lib/pi-console` and `/var/backups/pi-console` are **not deleted**; remove them by hand for a clean machine.

---

## Settings

The defaults suit most setups. To change them, write `NAME=value` in `/etc/default/pi-console` and restart the services:

```bash
echo 'NUT_POLL=5' | sudo tee -a /etc/default/pi-console
sudo systemctl restart wol-console pi-console-ups admin-panel net-monitor proxmox-monitor pi-console-overview
```

| Variable | Module | Default | Purpose |
|---|---|---|---|
| `SCAN_NETWORK` | Net | Pi's /24 | Network to scan (e.g. `192.0.2.0/24`) |
| `SCAN_INTERVAL` | Net | manual | Seconds between automatic scans (0 = manual) |
| `SCAN_PORTS` | Net | common ports | Ports probed |
| `PORT_TIMEOUT` | Net | `0.5` | Seconds to wait per port |
| `MAX_WORKERS` | Net | `30` | Hosts scanned at once |
| `PIHOLE_HOSTS`, `PIHOLE_PASS` | Net | empty | Pi-hole (also set from the page) |
| `NUT_POLL` | UPS | `10` | Seconds between `upsd` polls |
| `NUT_DB_FLUSH` | UPS | `60` | Seconds between history writes |
| `PVE_POLL_ACTIVE`, `PVE_POLL_IDLE` | Proxmox | `5`, `60` | Seconds between polls with the page open / idle |
| `PVE_KEEP_DAYS` | Proxmox | `7` | Days of CPU and memory history |
| `PICONSOLE_PI_KEEP_DAYS` | Overview | `7` | Days of Pi history |
| `WOL_BROADCAST` | WOL | automatic | Comma-separated broadcast addresses |
| `PICONSOLE_SECURE_COOKIE` | all | off | `1` marks the cookie `Secure` (only behind HTTPS) |

---

## Security

Designed for a **trusted local network**. Do not expose port 80 to the internet.

- **Access:** the Python services listen on `127.0.0.1` only; only nginx is visible on the network. To encrypt, see [HTTPS](#https).
- **Passwords:** minimum 8 characters, stored with scrypt. The initial account uses a random password that must be changed.
- **Login attempts:** 5 failures from one IP within 10 minutes lock that IP for 5 minutes; each account also has its own limit. The counter is shared by all modules. nginx rate-limits requests and connections per IP.
- **Sessions:** `HttpOnly` and `SameSite=Strict` cookie; only the SHA-256 hash of the token is stored on disk. They can be viewed and closed in the Admin Panel.
- **CSRF:** every request that changes data is rejected (403) unless it comes from the app's own page.
- **Strict CSP:** no inline scripts or handlers (`script-src 'self'`). Browsers: Chrome 75+, Firefox 105+, Safari 15.4+.
- **Per-module permissions:** an admin can only grant or remove permissions on modules where they hold that level, and cannot delete or change the password of a user with more permissions.
- **Least privilege:** the code in `/opt/pi-console` is root-owned and read-only for the services; their data lives in `/var/lib/pi-console/`. The systemd units are hardened. Scripts that run as root (installer, Teleporter, SFTP backup) never follow symlinks inside the services' folders.
- **Validated input:** NUT, Proxmox and Pi-hole hosts and names; the Pi-hole certificate is pinned on first connection; each Proxmox cluster's fingerprint is pinned. An old cluster without a fingerprint shows a permanent warning (use *Pin certificate*).
- **Backup from the panel:** runs as root through a `sudo` rule limited to `teleporter.sh gui-backup` and `gui-restore`. Restoring the NUT config can bring in commands that `upsd` runs as root: restore trusted backups only.

---

## Layout

```
pi-console/
├── auth/              # shared authentication, Admin Panel and panel backups
├── wol-console/       # each module: server.py + static/
├── nut-monitor/       # (UPS Monitor)
├── net-monitor/
├── proxmox-monitor/
├── overview/          # Overview
├── home/              # home page and icons
├── etc/               # nginx, backup.conf, cron
├── scripts/           # teleporter.sh, pi-console-sftp-backup, -https, -health, -resources, apt-repo.py
├── debian/            # .deb packaging
├── assets/icons/      # source icons and the script that regenerates the PNGs
├── tests/             # automated tests (unittest)
├── docs/              # APT.md and screenshots
├── CHANGELOG.md, RELEASE_NOTES_*.md, VERSION, LICENSE
└── README.md, README.en.md
```

On the Pi:

| Path | Content |
|---|---|
| `/opt/pi-console/` | Code (replaced on every update) |
| `/var/lib/pi-console/` | Data: `users.json`, `<module>/`, `metrics.db`, `events.json` |
| `/etc/pi-console/` | `backup.conf`, backup key and passphrase, `tls/` |
| `/var/backups/pi-console/` | Copies made before updating, uninstalling or restoring |
| `/var/log/pi-console/` | SFTP backup status and restore log |
| `/usr/local/bin/` | `teleporter`, `pi-console-sftp-backup`, `pi-console-https`, `pi-console-health`, `pi-console-resources` |

Each module is an independent Python HTTP server. All of them use `auth/auth.py` for users and sessions.

Tests (standard library only, never touches `/var/lib`): `python3 -m unittest discover -s tests -t . -v`

Code comments are in Spanish and English (English ones start with `EN:`). A generator for an APT repository is in `scripts/apt-repo.py` (not published yet, see [docs/APT.md](docs/APT.md)).

---

## License

[PolyForm Noncommercial 1.0.0](LICENSE), from version 1.3.

- **Free** for personal use, hobby projects, study, education and non-profit organizations.
- **Commercial use (for example, inside a company) and commercial derivative works require the author's written permission.** To ask for it, open an issue on GitHub.
- Versions before 1.3 were released under the MIT license; those copies keep that license.

Created with the help of AI.
