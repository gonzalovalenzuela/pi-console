# Changelog

## 1.1.7 — 2026-10-09

### Net Monitor
- **Tipos de dispositivo**: computer, phone, router, switch, ap, storage, tv, camera, appliance, other. Columna *Type* con icono, filtros por tipo y edición manual (con opción `auto` para volver a la detección).
- **Detección más precisa**: heurística por puntaje (vendor, banner, hostname, puertos, gateway, TTL, bit de MAC aleatoria). Windows exige TTL 65-128 o evidencia fuerte; los NAS ya no se detectan como Windows; Android/iOS se clasifican como phone.
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
- Layout compacto que **cabe en una sola pantalla** (probado en 1366x768, 1440x900 y 1920x1080), sin scroll innecesario.
- *Activity* bajó al fondo como panel delgado; los gráficos de voltaje y potencia se ajustan al alto libre de la ventana.

### Interfaz general
- Campos de entrada con fondo más oscuro y borde más marcado (tema claro y oscuro) para distinguir qué se puede completar.

### Paquete
- Nuevos `Suggests`: `ieee-data`, `snmp` (opcionales; `snmp` solo se necesita para la fuente SNMP).
- Los datos de usuario (`clusters.json`, `hosts.json`, `config.json`) se conservan al actualizar.

### Notas / conocido
- La descarga automática de `manuf` no pudo probarse desde el entorno de desarrollo (sin acceso a wireshark.org); el formato se validó con una muestra real.
- En pantallas de ~390 px de ancho el UPS Monitor aún desborda horizontalmente (ya ocurría antes).
