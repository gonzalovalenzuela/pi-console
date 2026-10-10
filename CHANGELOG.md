# Changelog

## Sin publicar

### UPS Monitor
- Los servidores NUT ahora se pueden **editar** (nombre, host y puerto) desde el botón de lápiz de la barra lateral, además de eliminarlos. Al cambiar host o puerto se reconecta de inmediato y se descartan los datos del destino anterior; el historial se conserva. Nuevo endpoint `PUT /api/servers/<id>` (solo admin).

## 1.1.8 — 2026-10-10

Reúne los cambios de 1.1.7 y sus revisiones (1.1.7a–1.1.7f).

### Net Monitor
- Tipos de dispositivo: computer, phone, router, switch, ap, storage, tv, camera, appliance, other. Columna *Type*, filtros por tipo y edición manual (`auto` vuelve a la detección).
- Detección por puntajes (vendor, banner, hostname, puertos, gateway, TTL, MAC aleatoria). Los NAS ya no se detectan como Windows; Android/iOS se clasifican como phone.
- El tipo/OS editado ya no se pierde al terminar un escaneo.
- Se muestra la MAC cuando no se detecta el vendor. Fuentes de MAC: Pi-hole, ARP local, SNMP.
- Fuente SNMP configurable (host, puerto, v1/2c/3, community, usuario v3, auth/privacy, timeout, botón *Test*). Lee `ipNetToMediaPhysAddress` con respaldo a `ipNetToPhysicalPhysAddress`. Las credenciales no se devuelven por la API y `config.json` queda con permisos 600.
- Base de vendors (OUI): `manuf` de Wireshark con descarga semanal, respaldo a `ieee-data`, actualización manual y estado en el panel.
- Los nombres de host de Pi-hole perdían caracteres finales al quitar `.local`.

### Proxmox Monitor
- Refresco más rápido: una sola llamada a `/cluster/resources` (con respaldo por nodo), conexión HTTPS persistente, sondeo de 5 s con la vista activa y 60 s en reposo, datos lentos cada 60 s, historial cada 30 s.
- Orden estable de nodos, orden manual (arrastrar o flechas) y pin por nodo, guardados por cluster.
- `/api/clusters` ya no expone `token_value` a usuarios viewer.

### UPS Monitor
- Layout compacto que cabe en una pantalla (probado en 1366x768, 1440x900 y 1920x1080). *Activity* pasa al fondo; los gráficos se ajustan al alto libre.
- Gráficos vacíos en la última hora: el cliente volvía a filtrar con el reloj del navegador y descartaba todo si difería del reloj de la Pi. Ahora el recorte usa el punto más reciente del historial.
- El servicio systemd se llama ahora `pi-console-ups` (antes `nut-monitor`). El nombre antiguo tapaba el servicio `upsmon` de `nut-client`: `systemctl restart nut-monitor` y `nut.target` arrancaban el dashboard en lugar de `upsmon`. Al actualizar, el `postinst` elimina la unidad antigua y, si hay `MONITOR` en `/etc/nut/upsmon.conf`, habilita y arranca el `nut-monitor` real. Logs: `journalctl -u pi-console-ups`.

### Inicio de sesión
- Login directo en un módulo (WOL, UPS, Net, Proxmox) fallaba con `ME.username[0]`: `/api/login` no devolvía el usuario. Ahora lo devuelve y la interfaz tolera que falte.

### Interfaz
- Campos de entrada con fondo más oscuro y borde más marcado en tema claro y oscuro.

### Teleporter (respaldo y restauración)
- `/usr/local/bin/teleporter.sh` (enlace `teleporter`): `teleporter backup`, `teleporter check <archivo>`, `sudo teleporter restore <archivo> [-y] [--nut] [--nginx]`. `pi-console-backup` y `pi-console-restore` son atajos.
- Respalda usuarios y sesiones, dispositivos WOL, servidores UPS e `history.db` (snapshot SQLite consistente), hosts/config de Net Monitor, clusters Proxmox, y opcionalmente configuración de NUT y sitio nginx.
- `check` valida gzip, rutas seguras, SHA-256, JSON, integridad SQLite y que `users.json` no esté vacío; no modifica nada.
- `restore` verifica antes de tocar, crea un snapshot en `/var/backups/pi-console/`, detiene servicios, reemplaza archivos de forma atómica (0600), valida `nginx -t` (revierte si falla), usa bloqueo contra ejecuciones simultáneas y siempre reinicia los servicios. Acepta respaldos del teleporter 1.x.
- Configuración de NUT y sitio nginx se restauran solo con `--nut` / `--nginx` (desactivado por defecto; NUT se configura manualmente).
- Variables de entorno de pruebas se ignoran bajo `sudo`.

### Admin Panel
- Tarjeta *Backup & restore* en `/admin/`: crear (descarga automática), subir, verificar, restaurar, descargar y eliminar respaldos. Permite migrar a una instalación nueva: instalar el `.deb`, subir el respaldo y pulsar *Restore*; luego iniciar sesión con los usuarios del respaldo.
- La restauración corre como root mediante `/etc/sudoers.d/pi-console-teleporter` (solo `teleporter.sh gui-backup` y `gui-restore`), en la unidad `pi-console-restore`, con registro en `/var/lib/pi-console/teleporter/restore.log`.
- Respaldos en `/var/lib/pi-console/teleporter/` (se conservan 5; subidas se borran tras 24 h). Límite de subida: 200 MB.
- Endpoints (solo admin): `GET /api/teleporter`, `POST /api/teleporter/{backup,upload,check,restore}`, `GET /api/teleporter/download/<archivo>`, `DELETE /api/teleporter/<archivo>`.
- nginx `/admin/`: cuerpos de hasta 200 MB, sin buffer de subida, timeouts de 300 s.

### Paquete
- Nueva dependencia: `sudo`. Nuevos `Suggests`: `ieee-data`, `snmp`.
- `postinst` crea el directorio del teleporter y la regla sudo (validada con `visudo -c`); `postrm` la elimina.
- Los datos de usuario (`clusters.json`, `hosts.json`, `config.json`) se conservan al actualizar.

### Conocido
- En pantallas de ~390 px el UPS Monitor desborda horizontalmente.
- El banner del `postinst` siempre muestra el usuario inicial `admin / admin`, también al actualizar.
