# Changelog

## 1.1.7f — 2026-10-10

### Correcciones
- **Conflicto con el servicio `nut-monitor` de NUT**: el servicio systemd del UPS Monitor se llamaba `nut-monitor`, igual que el servicio `upsmon` del paquete `nut-client`. El archivo de Pi Console en `/etc/systemd/system` tapaba el de NUT, así que `systemctl restart nut-monitor` y `nut.target` arrancaban el dashboard en lugar de `upsmon` (que apaga la Pi cuando el UPS se queda sin batería), y administrar NUT con `systemctl` no funcionaba.
- El servicio del dashboard ahora se llama **`pi-console-ups`** (`journalctl -u pi-console-ups`). Al actualizar, el `postinst` detecta el servicio antiguo, lo elimina y, si hay un `MONITOR` en `/etc/nut/upsmon.conf`, vuelve a habilitar y arrancar el `nut-monitor` real de NUT. El teleporter y el `postrm` usan el nombre nuevo.

## 1.1.7e — 2026-10-10

### Correcciones
- **UPS Monitor: gráficos vacíos (sin datos de la última hora)**: el gráfico volvía a filtrar los puntos con el reloj del *navegador*, aunque el servidor ya los había filtrado con el reloj de la Pi. Si ambos relojes difieren en 1 hora o más (por ejemplo una Pi sin RTC/NTP al día), se descartaban todos los puntos. Ahora el recorte usa el punto más reciente del propio historial y no depende del reloj del navegador.

## 1.1.7d — 2026-10-09

### Correcciones
- **Inicio de sesión directo en un módulo** (WOL, UPS Monitor, Net Monitor, Proxmox): fallaba con `undefined is not an object (evaluating 'ME.username[0]')` y la página no entraba. La respuesta de `/api/login` no incluía el nombre de usuario; ahora lo incluye y la interfaz tolera que falte. Ocurría al entrar sin una sesión previa, por ejemplo tras restaurar un respaldo (las sesiones se reemplazan) o en una instalación nueva.

## 1.1.7c — 2026-10-09

### Teleporter integrado en el Admin Panel
- Nueva tarjeta **Backup & restore** en `/admin/`: crear respaldo (se descarga solo), subir un respaldo, verificarlo, restaurarlo, descargarlo o eliminarlo.
- **Migración a una instalación nueva**: instalar el `.deb`, entrar con el usuario por defecto, subir el respaldo y pulsar *Restore*. Una barra de progreso muestra el registro; al terminar hay que iniciar sesión con los usuarios del respaldo.
- La restauración se ejecuta como root a través de una regla `sudo` mínima (`/etc/sudoers.d/pi-console-teleporter`, solo `teleporter.sh gui-backup` y `gui-restore`) y en una unidad systemd separada (`pi-console-restore`), para sobrevivir al reinicio del propio panel. Se trabaja sobre una copia privada del archivo para evitar sustituciones entre la verificación y la extracción.
- Opciones al restaurar, ambas **desactivadas por defecto**: configuración de NUT (`/etc/nut`, se configura manualmente) y sitio nginx (se conserva el del paquete). En consola: `--nut` y `--nginx`. Los datos del UPS Monitor (servidores e historial) sí se restauran siempre.
- Los respaldos creados en el panel se guardan en `/var/lib/pi-console/teleporter/` (se conservan los 5 más recientes; las subidas se borran tras 24 h). Límite de subida: 200 MB.
- `teleporter.sh` 2.1: bloqueo para evitar dos operaciones simultáneas, marcador `RESULT:` en el registro y todas las variables de entorno de pruebas se ignoran cuando corre bajo `sudo`.
- Endpoints (solo admin): `GET /api/teleporter`, `POST /api/teleporter/{backup,upload,check,restore}`, `GET /api/teleporter/download/<archivo>`, `DELETE /api/teleporter/<archivo>`.
- nginx: `/admin/` acepta cuerpos de hasta 200 MB, sin buffer de subida y con timeouts de 300 s.

### Paquete
- Nueva dependencia: `sudo`.
- `postinst` crea el directorio de trabajo y la regla sudo (validada con `visudo -c`); `postrm` la elimina al desinstalar.

## 1.1.7a — 2026-10-09

### Net Monitor
- **Tipos de dispositivo**: computer, phone, router, switch, ap, storage, tv, camera, appliance, other. Columna *Type* con icono, filtros por tipo y edición manual (con opción `auto` para volver a la detección).
- **Detección más precisa**: Evaluación mediante puntajes (vendor, banner, hostname, puertos, gateway, TTL, bit de MAC aleatoria). Windows exige TTL 65-128 o evidencia fuerte; los NAS ya no se detectan como Windows; Android/iOS se clasifican como phone.
- **Fix**: el tipo/OS editado ya no se pierde al terminar un escaneo.
- **MAC visible** cuando no se detecta el vendor. Fuentes de MAC: Pi-hole → ARP local → SNMP.
- **Fuente SNMP** configurable junto al botón *Scan*: host, puerto, versión 1/2c/3, community, usuario v3, nivel, auth/privacy, timeout y botón *Test*. Lee `ipNetToMediaPhysAddress` (con respaldo a `ipNetToPhysicalPhysAddress`). Las credenciales nunca se devuelven por la API y `config.json` queda con permisos 600.
- **Base de vendors (OUI)**: archivo `manuf` de Wireshark (descarga semanal automática, bloques 24/28/36 bits) con respaldo a `ieee-data`. Actualización manual y estado en el panel.
- Fix: nombres de host de Pi-hole perdían caracteres finales al quitar `.local`.

### Proxmox Monitor
- **Refresco mucho más rápido** y con menos consumo: una sola llamada a `/cluster/resources` (con respaldo por nodo), conexión HTTPS persistente, sondeo adaptivo (5 s con la vista activa / 60 s en reposo), datos lentos (versión/Ceph) cada 60 s e historial cada 30 s. Las migraciones de VM/CT se reflejan en pocos segundos.
- **Orden estable de nodos**, ordenamiento manual (arrastrar o flechas) y **pin** por nodo; se guarda por cluster y sobrevive a refrescos y reinicios.
- **Seguridad**: `/api/clusters` ya no expone `token_value` a usuarios con rol viewer.
- Fix: error 502 por un `NameError` al iniciar (resuelto antes de publicar).

### UPS Monitor
- Layout compacto que **cabe en una sola pantalla** (probado en 1366x768, 1440x900 y 1920x1080).
- *Activity* bajó al fondo como panel delgado; los gráficos de voltaje y potencia se ajustan al alto libre de la ventana.

### Interfaz general
- Campos de entrada con fondo más oscuro y borde más marcado (tema claro y oscuro) para distinguir qué se puede completar.

### Teleporter (backup / verificación / restauración)
- Nuevo `/usr/local/bin/teleporter.sh` (con enlace `teleporter`): `teleporter backup`, `teleporter check <archivo>` y `sudo teleporter restore <archivo>`.
- Respalda usuarios y sesiones (`/var/lib/pi-console`), dispositivos WOL, servidores UPS + `history.db` (snapshot consistente con la API de SQLite), hosts/config de Net Monitor (SNMP), clusters Proxmox, configuración de NUT y el sitio nginx.
- `check` valida gzip, rutas seguras, checksums SHA-256, JSON, integridad SQLite y que `users.json` no esté vacío; no modifica nada.
- `restore` verifica antes de tocar nada, crea un snapshot de seguridad en `/var/backups/pi-console/`, detiene servicios, reemplaza archivos de forma atómica (permisos 600), recrea los enlaces de `/opt/pi-console-auth`, valida `nginx -t` (y revierte si falla) y siempre reinicia los servicios, incluso si algo falla.
- Acepta backups del teleporter 1.x. `pi-console-backup` y `pi-console-restore` ahora son atajos a `teleporter`.

### Paquete
- Nuevos `Suggests`: `ieee-data`, `snmp` (opcionales; `snmp` solo se necesita para la fuente SNMP).
- Los datos de usuario (`clusters.json`, `hosts.json`, `config.json`) se conservan al actualizar.

### Notas / conocido

- En pantallas de ~390 px de ancho el UPS Monitor aún desborda horizontalmente.
