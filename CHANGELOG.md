# Changelog

## 1.2.2g — 2026-10-23

- **Nueva licencia: PolyForm Noncommercial 1.0.0** (antes MIT). Uso gratis para uso personal, hobby, estudio, educación y organizaciones sin fines de lucro. El uso comercial y los derivados comerciales requieren permiso escrito del autor. Las versiones hasta la 1.2.2f siguen con su licencia MIT.
- El paquete incluye `/usr/share/doc/pi-console/copyright` y `LICENSE`.

## 1.2.2f — 2026-10-21

- **Pruebas automáticas en el repositorio** (`tests/`, solo biblioteca estándar). 29 pruebas: cortes y disponibilidad del UPS, lectores de sesiones (utmp y logind), detalle de la Pi (qué ve un administrador y qué un lector), contrato de las APIs (sin sesión → 401, lectura sola no escribe, bloqueo de peticiones entre sitios), versión única en `VERSION`, `debian/control` y CHANGELOG, copias compartidas idénticas, textos en español e inglés con las mismas claves, y sintaxis de JS y shell. Se corren con `python3 -m unittest discover -s tests -t . -v` y en GitHub Actions (`tests.yml`, Python 3.11 y 3.13).
- **Los módulos ya no hacen nada al importarse.** La carpeta de datos, los archivos antiguos y, en Net Monitor, el modo manual de una instalación nueva se preparan al arrancar el servicio, no al importar el archivo. Sin cambios para el usuario.
- **Overview, modo kiosko:** el enlace *Abrir* de la tarjeta Raspberry Pi ahora también se ve (estaba oculto).

## 1.2.2e — 2026-10-21

- **Detalle de la Pi: usuarios conectados.** Mostraba "Nadie conectado" aunque hubiera una sesión SSH, porque las versiones nuevas de Raspberry Pi OS (Debian 13) ya no llenan `/run/utmp`. Ahora también lee las sesiones de systemd-logind (lo mismo que muestra `w`).

## 1.2.2d — 2026-10-21

Auditoría de seguridad de lo agregado en 1.2.2a–c. Sin hallazgos críticos ni altos; tres endurecimientos:
- El detalle de la Pi (`/api/pidetail`) comparte el resultado 2 s entre sesiones y lo calcula un solo hilo a la vez, para que muchas peticiones no carguen la Raspberry Pi.
- Las direcciones MAC del detalle de la Pi solo las ven los administradores.
- Tabla de cortes del UPS: se conservan como máximo los 2000 cortes más recientes por UPS, para que un UPS defectuoso que alterne red/batería sin parar no haga crecer la base.

## 1.2.2c — 2026-10-21

- **UPS Monitor: tiempo en línea y disponibilidad.** Cada UPS muestra el tiempo en línea desde el último corte, la disponibilidad de 24 h, 7 d y 30 d, la cantidad de cortes de los últimos 30 días y el último corte (fecha, duración y carga mínima). Los cortes se guardan en `history.db` (tabla `outages`). Al actualizar se reconstruyen los cortes pasados desde el historial (tramos con voltaje de entrada bajo 20 V; solo si el UPS informa voltaje de entrada). La disponibilidad aparece cuando hay al menos 1 hora de datos.
- **Overview: línea de cortes en la tarjeta UPS** (tiempo en línea, último corte y disponibilidad de 30 días).
- **Overview: detalle de la Raspberry Pi.** El botón *Abrir* de la tarjeta Raspberry Pi muestra equipo, sistema, kernel, encendido y uptime, CPU total y por núcleo, frecuencia, carga, memoria y swap, discos, interfaces de red con IP y tráfico, temperatura y estado de energía (bajo voltaje y limitación). Los administradores también ven usuarios conectados, procesos con más CPU y memoria, y servicios con falla. Se actualiza cada 5 s.

## 1.2.2b — 2026-10-20

- **Overview: tarjetas ordenables.** Botón *Ordenar*: cada tarjeta muestra flechas ‹ › y una manija ⠿ para arrastrar (las flechas sirven en iPad y celular). *Restablecer orden* vuelve al de siempre (UPS, Proxmox, Red, Pi). El orden se guarda en cada navegador y también se usa en modo kiosko. La línea de tiempo siempre queda abajo.

## 1.2.2a — 2026-10-20

- **Formato de hora 24 h / 12 h.** Botón "24H/12H" junto al idioma (en el Resumen, antes del botón de idioma). Por defecto 24 h. Se guarda en el navegador y vale para todos los módulos. Afecta relojes, horas de gráficos, eventos, fechas con hora y registros.

## 1.2.2 — 2026-10-20

Reúne todos los cambios desde 1.2.1 (builds 1.2.1a a 1.2.1t).

**Seguridad**
- CSRF: las peticiones que modifican datos se rechazan si no vienen de la propia página.
- CSP estricta: sin scripts ni manejadores en línea (`script-src 'self'`). Navegadores: Chrome 75+, Firefox 105+, Safari 15.4+.
- XSS corregido en los 5 paneles. Incluye el que venía del servidor NUT (un equipo de la red podía ejecutar código en el navegador del administrador).
- WOL: el límite por IP ya no se evade con `X-Forwarded-For`. "Despertar todos" también tiene límite.
- Net Monitor: el escaneo de una IP solo acepta equipos de la red escaneada.
- Redirección abierta en el cambio de contraseña corregida.
- La contraseña inicial del admin ya no se escribe en el journal. Los hashes antiguos se migran a scrypt.
- Respaldo SFTP: el archivo de estado ahora está en `/var/log/pi-console/backup.status` (carpeta de root).
- Teleporter: se rechazan respaldos que descomprimen a más de 2 GiB. Dos subidas simultáneas ya no se pisan.
- Revisión final del código con bandit y shellcheck. Sin hallazgos críticos ni altos.

**Nuevo**
- Login: "Recordarme" (1 día, 1 semana, 1 mes o siempre). Sin marcar, 24 h.
- Admin: tarjeta "Sesiones activas" para ver y cerrar sesiones.
- Overview: selector de intervalo de actualización (10 s a 5 min, o manual).
- Net Monitor: botón de basurero para eliminar equipos. Categorías nuevas: Game Console, Servidor, Teléfono IP, UPS y Altavoz inteligente.
- Tarjeta de Net Monitor al pasar el mouse (o tocar en iPad) por una IP en UPS, Proxmox, WOL y Overview.
- Nuevo icono de la app y soporte para pantalla de inicio en iPad/iPhone (pantalla completa, icono incrustado).
- HTTPS autofirmado compatible con iOS. `pi-console-https enable` regenera el certificado antiguo una vez; hay que instalarlo de nuevo en cada dispositivo.

**Correcciones**
- Admin: el login con Enter abría dos sesiones.
- UPS Monitor: anillos y etiquetas de los gráficos ya no se cortan.
- Las duraciones de más de 24 h se ven en días (`1d 16h`).

**Al actualizar:** `pi-console-site.conf` cambió. Si lo editaste, dpkg preguntará; conserva el nuevo. Si ya tenías la app en la pantalla de inicio, quítala y agrégala otra vez.

## 1.2.1 — 2026-10-15

Versión estable de la serie 1.2 (reúne 1.2.0a–x). El funcionamiento es el de 1.2.0x, salvo lo indicado.

### Revisión previa al release
- Sin claves, tokens ni credenciales en el código, el historial de git ni el `.deb`.
- Sin datos personales ni de red: solo quedan el nombre del autor y direcciones de documentación (`192.0.2.0/24`).
- 38 pruebas de integración; instalación, actualización, desinstalación y purga del `.deb` probadas.

### Cambios
- **Paquete:** al purgar, los datos conservados pasan a `root:root` (700) y se devuelven al usuario del servicio al reinstalar. Antes quedaban a nombre de un uid huérfano.
- **Páginas:** la metaetiqueta `author` ya no incluye el correo.
- **Documentación:** capturas rehechas con datos ficticios y la versión actual; ruta local quitada de `docs/APT.md`.

## 1.2.0x — 2026-10-15

- **UPS Monitor:** los gráficos de voltaje, consumo y temperatura de cada UPS ocupan ahora todo el ancho del detalle (más amplios y sin el hueco que dejaba el de temperatura al quedar solo en una fila). En pantallas angostas ya iban a todo el ancho.

## 1.2.0w — 2026-10-15

- **Resumen:** las tarjetas se reparten de forma equilibrada. Si no caben todas en una fila (4 tarjetas con sitio para 3 columnas, típico en pantallas de ~1000–1300 px), pasan a 2×2 en vez de dejar la última sola en una segunda fila con un hueco a su derecha. En kiosko el ancho mínimo por tarjeta baja de 380 a 320 px: 4 tarjetas caben en una fila desde ~1400 px.

## 1.2.0v — 2026-10-15

- **Resumen, kiosko y pantallas anchas:** la línea de tiempo estaba dentro de la grilla de tarjetas y, al ocupar todas las columnas, reservaba una columna vacía a la derecha: con 4 tarjetas y un ancho de ~1100–1200 px quedaba cerca de un 20 % de la pantalla sin usar. Ahora la línea de tiempo va debajo de la grilla y las tarjetas reparten todo el ancho.

## 1.2.0u — 2026-10-15

### Seguridad (auditoría: 13 hallazgos)
- **Instalador y Teleporter como root:** ya no siguen enlaces simbólicos dentro de carpetas que controlan los servicios (antes un servicio comprometido podía hacer que un respaldo incluyera archivos de root o que una restauración los sobrescribiera). Las lecturas las hace el usuario del servicio y las escrituras usan `openat` con `O_NOFOLLOW`; la instantánea SQLite la toma el usuario del servicio; el registro de restauración está en `/var/log/pi-console/` (de root); `/opt/pi-console` y `/opt/pi-console-auth` son de root. Teleporter 2.2.0.
- **Servicios:** el código es de solo lectura para ellos y los datos pasan de `/opt/pi-console/<módulo>/` a `/var/lib/pi-console/<módulo>/` (el instalador los mueve solo). Unidades systemd endurecidas (`ProtectSystem`, `ProtectHome`, `PrivateTmp`, `NoNewPrivileges` donde no hay `ping` ni `sudo`, familias de sockets, `UMask=0077`…).
- **CSV de UPS Monitor:** el nombre del archivo exportado ya no puede inyectar cabeceras (CRLF).
- **HTTPS:** nuevo comando `pi-console-https` (`enable [--redirect] [--cert --key]`, `disable`, `status`) con certificado autofirmado o propio, HSTS y cookie `Secure` al redirigir.
- **Intentos de login:** contadores compartidos por todos los módulos (archivo con `flock`), límite por IP y por cuenta; cambiar la contraseña exige la actual y esos intentos también se limitan.
- **Respaldos:** no incluyen `sessions.json`; el respaldo SFTP se **cifra con gpg** (AES-256) antes de salir (`pi-console-sftp-backup decrypt` para abrirlo; la contraseña está en `/etc/pi-console/backup_passphrase`, guarda una copia fuera de la Pi).
- **Cuentas:** sin `admin`/`admin`: contraseña aleatoria en la instalación nueva (la muestra el instalador); mínimo 8 caracteres también al crear usuarios.
- **Permisos:** un usuario de solo lectura ya no puede iniciar un escaneo de Net Monitor; un admin parcial (p. ej. solo WOL) no puede degradar, borrar ni cambiar la contraseña del administrador principal.
- **Hosts y Pi-hole:** hosts y nombres de NUT, Proxmox y Pi-hole se validan; el certificado de Pi-hole se fija en la primera conexión (TOFU).
- **nginx:** `server_tokens off`, límites de peticiones y conexiones por IP (más estricto en el login), `Content-Length` negativo rechazado, cabeceras adicionales; `/api/health` público solo informa el estado y `/api/version` pide sesión. Se quita el endpoint `/wol/api/token` (sin uso).
- **Sesiones:** se guardan solo como hash SHA-256 y el login ya no devuelve el token en el JSON. **Hay que iniciar sesión otra vez tras actualizar.**
- **Admin Panel:** un usuario válido que no es admin recibe la misma respuesta que una contraseña incorrecta (sin oráculo de credenciales).
- **Límite conocido:** la CSP todavía permite `'unsafe-inline'` (resuelto en 1.2.1f).

## 1.2.0t — 2026-10-15

- **Resumen, kiosko:** el gráfico de temperatura de la UPS se muestra ahora en cualquier tamaño de pantalla, de forma compacta (en 1.2.0s seguía oculto entre 701 y 900 px de alto, que es el caso de varias tablets de 7").

## 1.2.0s — 2026-10-15

- **Resumen, kiosko de 7":** el gráfico de temperatura de la UPS no aparecía en pantallas de 700 px de alto o menos; ahora se muestra compacto, como los de la Pi y Proxmox. Entre 701 y 900 px sigue oculto para que quepa la pantalla.
- **Resumen, kiosko:** leyenda de la torta de Net Monitor en dos columnas con etiquetas cortas y título más compacto en el gráfico de temperatura de la Pi.
- **Sin referencias a redes privadas:** el servidor SFTP por defecto de `backup.conf` es ahora `storage.example.lan` (hay que indicar el real en `SFTP_HOST`); la red de respaldo de Net Monitor cuando no se detecta la IP es `192.0.2.0/24`.
- Documentación y capturas (claro y oscuro) actualizadas.

## 1.2.0r — 2026-10-14

- **Resumen, Net Monitor:** la leyenda de la torta mostraba solo los 6 tipos más numerosos, así que TV, teléfono, tablet, cámara, etc. podían quedar fuera aunque estuvieran en la torta. Ahora aparecen **todos** los tipos (hasta 12, con colores distintos); con más de 5 se ordenan en dos columnas. En el kiosko de pantalla chica la torta se achica y se usan nombres cortos (PC, Teléf., Cám., Impres.…) para que quepan todos sin cambiar el alto de las tarjetas.
- **Resumen, temperatura de la Pi:** el gráfico ya no reserva siempre 24 h de ancho: usa todo el ancho para los datos acumulados (2 min, 1 h, 24 h…) y el título indica el período que cubre («Temp 35 min»).

## 1.2.0q — 2026-10-14

- **UPS Monitor: gráfico de temperatura de la UPS.** En el detalle de cada UPS aparece, junto a los de voltaje y consumo, el gráfico de temperatura con los mismos rangos (1 h, 1 día, 1 mes, todo), cursor con valor y modo claro/oscuro. Solo se muestra si la UPS informa `ups.temperature` o `battery.temperature`; si no, no aparece. Usa el historial que ya se guardaba en `history.db`, así que muestra de inmediato lo registrado antes.
- En los rangos largos se promedian solo las lecturas con temperatura (antes un 0 por «sin dato» bajaba el promedio) y la línea se corta donde no hubo lectura.

## 1.2.0p — 2026-10-14

### Históricos en base de datos (SQLite)
- Los históricos de los gráficos del Resumen pasan de archivos JSON a una base **`/var/lib/pi-console/metrics.db`** (tablas `pi_samples` y `pve_samples`), compartida por el Resumen (temperatura y bajo voltaje de la Pi) y Proxmox Monitor (CPU y memoria de los nodos). Es el mismo motor que el historial de la UPS (`history.db`).
- **Cada muestra se guarda al instante** (modo WAL): un corte de luz ya no pierde los últimos minutos, y no se reescribe un archivo completo cada vez.
- **Retención configurable:** 7 días por defecto; `PICONSOLE_PI_KEEP_DAYS` (Pi) y `PVE_KEEP_DAYS` (Proxmox) la cambian, de 1 a 365. Los gráficos siguen mostrando 24 h (Pi) y 12 h (Proxmox).
- **Migración automática:** si existen `pi-history.json` o `proxmox-monitor/history.json` (versión 1.2.0o), se importan una vez a la base y se renombran a `.migrated`.
- **Teleporter** respalda `metrics.db` con la API de respaldo de SQLite (consistente aunque los servicios estén escribiendo) y la verifica. Restaura también respaldos de la 1.2.0o, que traían los JSON; los servicios los importan.
- En un equipo que no es Raspberry Pi no se crea hilo ni tabla de la Pi.

## 1.2.0o — 2026-10-14

### Históricos persistentes y en el respaldo
- **Proxmox: CPU y memoria (12 h).** Antes vivían solo en memoria y se perdían al reiniciar Proxmox Monitor o actualizar el paquete. Ahora se guardan en `proxmox-monitor/history.json` cada 5 min y al detener el servicio, y se recargan al arrancar (se descartan las muestras de más de 12 h y los clusters que ya no existen). También se conservan al desinstalar y reinstalar (`preinst`/`prerm`/`postinst`).
- **Pi: temperatura y bajo voltaje (24 h)** en `/var/lib/pi-console/pi-history.json` (ya persistente desde 1.2.0m).
- **UPS: temperatura (24 h)** ya estaba en `history.db`.
- **Teleporter** respalda y restaura `proxmox-monitor/history.json` y `pi-history.json` (el `history.db` de la UPS ya estaba). Los respaldos antiguos siguen siendo válidos (sin esos archivos se conservan los actuales).
- Un corte de luz brusco puede perder los últimos minutos del historial (se escribe cada 5 a 10 min para cuidar la SD).

## 1.2.0n — 2026-10-14

- **Kiosko de 7":** los gráficos de la Pi (temperatura y bajo voltaje) y de Proxmox (CPU y memoria) ya no se ocultan en pantallas bajas; se muestran compactos (28 px) y no cambian el alto de la página. El de temperatura de la UPS sigue oculto en kioskos de menos de 900 px de alto.

## 1.2.0m — 2026-10-14

### Nuevo: históricos en el Resumen
- **Raspberry Pi: temperatura y bajo voltaje (24 h).** El servicio Resumen anota cada minuto la temperatura y los bits de `get_throttled` y guarda las últimas 24 h en `/var/lib/pi-console/pi-history.json` (se escribe cada 10 muestras y al cerrar el servicio, y se retoma al reiniciar). El gráfico marca en **rojo** la subtensión (también la que ocurrió entre dos muestras y ya pasó) y en **ámbar** la limitación por energía o temperatura; muestra mín., máx. y cuántos episodios de subtensión hubo. **Solo existe en una Raspberry Pi**: en otros equipos no se crea hilo, archivo ni gráfico (`/api/pihistory` responde `pi:false`).
- **Proxmox: CPU y memoria (12 h)** por cluster, con el historial que ya guardaba Proxmox Monitor (promedio de los nodos en tramos de 5 min). El historial se pide una vez por minuto; el resto de las actualizaciones siguen siendo livianas.
- **UPS: temperatura (24 h)** bajo el gráfico de carga, solo si la UPS informa temperatura (NUT `ups.temperature` o `battery.temperature`).
- En modo kiosko de pantalla baja (7") los gráficos nuevos se ocultan como los demás; el de temperatura de la UPS también en kioskos de menos de 900 px de alto, para que todo siga cabiendo.

## 1.2.0l — 2026-10-14

### Nuevo: respaldo automático por SFTP
- **`pi-console-sftp-backup`** (`/usr/local/bin`) + cron diario a las 03:17 (`/etc/cron.d/pi-console-sftp-backup`): crea el respaldo con Teleporter, lo **verifica antes de subirlo** (`teleporter check`), lo envía por SFTP (por defecto a `storage.example.lan`) con nombre temporal `.part` que renombra al terminar, y compara el tamaño remoto con el local.
- **Retención:** 30 copias en el storage (`KEEP_REMOTE`) y 7 en la Pi (`KEEP_LOCAL`). Solo se borran archivos llamados `pi-console-auto-<equipo>-<fecha>_<hora>.tar.gz`; los demás archivos de la carpeta no se tocan.
- **Seguro:** solo llave SSH (sin contraseñas), la huella del servidor se fija en la primera conexión y un cambio hace fallar el respaldo, el archivo de configuración (`/etc/pi-console/backup.conf`) se *lee* y nunca se ejecuta (solo claves conocidas, valores validados), un solo respaldo a la vez.
- **Comandos:** `setup` (crea la llave y muestra la pública), `test` (conexión, carpeta, escritura), `run`, `status`. Resultado en `/var/lib/pi-console/backup.status` y en `journalctl -t pi-console-sftp-backup`.
- No confundir con el atajo antiguo `pi-console-backup`, que sigue igual y equivale a `teleporter backup`; el nuevo se llama `pi-console-sftp-backup`.
- Viene **desactivado** hasta completar `SFTP_USER`. El paquete recomienda `openssh-client` y `cron`; la llave y la huella se borran con `apt purge`.

## 1.2.0k — 2026-10-14

### Resumen
- **«Equipos nuevos» cortado en el kiosko de tablets chicas:** en tarjetas angostas la fila (etiqueta NEW + IP + nombre) se salía del borde de la tarjeta. Ahora el nombre puede achicarse y en el kiosko compacto va en una segunda línea, con puntos suspensivos si es muy largo, y la etiqueta es más pequeña. En otras pantallas el nombre largo se parte en vez de cortarse.

## 1.2.0j — 2026-10-14

### Resumen
- **Desplazamiento automático apagado por defecto:** ahora se activa con el botón «Auto-desplazar», que aparece junto a «Salir de kiosko» al mover el mouse o tocar la pantalla (solo si el contenido no cabe). Se apaga con el mismo botón, siempre vuelve apagado al entrar al kiosko y con `?autoscroll=1` arranca encendido. Reemplaza al parámetro `?autoscroll=0` de la 1.2.0h.
- **Toque accidental:** el primer toque solo muestra la barra de botones; ya no pulsa un botón que todavía estaba invisible (podía sacar del kiosko sin querer). La barra queda visible 4 s.

## 1.2.0i — 2026-10-14

### Resumen
- **Kiosko compacto para tablets de 7" y portátiles (≤ 1399 px de ancho):** tarjetas con menos margen y relleno, KPIs más chicos, hasta 4 tarjetas en una fila y las filas de las unidades que se envuelven en vez de salirse de la tarjeta. En pantallas bajas (≤ 700 px de alto, como 1024×600) se ocultan los gráficos de 24 h y se resumen la línea de tiempo (4 eventos), la leyenda de tipos y los equipos nuevos, de modo que todo cabe sin scroll. Más grande que 1399 px no cambia nada.

## 1.2.0h — 2026-10-14

### Resumen
- **Modo kiosko para pantallas chicas (tablet de 7"):** el tamaño de letra y de columnas se adapta al ancho de la pantalla (antes era fijo, pensado para 1920 px). `?zoom=0.5–2` ajusta el tamaño a gusto.
- **Desplazamiento automático** en kiosko cuando el contenido no cabe: sube y baja despacio con pausa arriba y abajo, se detiene 30 s al tocar la pantalla y se desactiva con `?autoscroll=0`.
- El botón «Salir de kiosko» aparece también al tocar la pantalla (tablets sin mouse).

## 1.2.0g — 2026-10-14

### Resumen
- **Compatible con iPad antiguos (p. ej. iPad Air 1, iOS 12):** el Safari de esa versión no soporta `gap` en flexbox (separaba mal cabecera, píldoras, filas y eventos) ni `:has()` (el modo kiosko no agrandaba la letra). La página detecta el soporte y usa márgenes de respaldo solo cuando hace falta, y el modo kiosko marca `<html>` con una clase en vez de `:has()`. En navegadores modernos el aspecto es el mismo (comparado píxel a píxel).

## 1.2.0f — 2026-10-14

### Resumen
- **Modo kiosko:** el botón «Salir de kiosko» (arriba a la derecha) se sobreponía al texto «Actualizado hace…»; ahora la barra superior le deja sitio.

## 1.2.0d — 2026-10-14

### Resumen
- **Mensajes de servidor UPS sin conexión legibles:** el aviso y la línea de tiempo mostraban el identificador interno del servidor (un UUID); ahora dicen el nombre y la dirección, p. ej. «Servidor UPS Sala técnica (ups.example.lan:3493) sin conexión: Timeout connecting to upsd». La tarjeta de UPS también usa el nombre del servidor.

## 1.2.0c — 2026-10-14

### Nuevo: Resumen (`/overview/`)
- **Página de resumen** con lo principal de UPS Monitor, Proxmox Monitor y Net Monitor en una sola pantalla: estado global con lista de lo que requiere atención, tarjetas por UPS (estado, batería, carga, autonomía, vatios, gráfico de 24 h), por cluster Proxmox (nodos, VMs/CTs, CPU/memoria, Ceph) y de la red (en línea/conocidos/apagados, último escaneo, tipos de equipo, equipos nuevos de 48 h). Cada persona ve solo los módulos a los que tiene acceso. Claro/oscuro, español/inglés y móvil.
- **Widget de la Raspberry Pi:** temperatura, CPU, memoria, disco, tiempo encendida y problemas de la fuente de poder.
- **Línea de tiempo de eventos:** UPS pasa a batería / batería baja / vuelve la red, servidor UPS sin conexión, nodo Proxmox caído o recuperado, cluster sin conexión, cambios de salud de Ceph, equipos nuevos / que volvieron / que dejaron de responder (el primer escaneo se resume en una línea; más de 5 cambios iguales se agrupan). Los registra cada módulo en `/var/lib/pi-console/events.json` (máx. 300 eventos o 30 días), así que se guardan aunque nadie tenga la página abierta. Reiniciar un servicio no genera eventos falsos.
- **Modo kiosko** (`?kiosk=1` o botón): pantalla completa, letra grande, sin botones ni cursor y con la pantalla siempre encendida.
- Servicio nuevo `pi-console-overview` (puerto 8085, solo loopback), ruta `/overview/` en nginx, acceso «Overview» en el menú de todos los módulos y tarjeta «Resumen» en la página de inicio. Se incluye en la salud del sistema, en `pi-console-resources`, en Teleporter (reinicio tras restaurar) y en la desinstalación.

## 1.2.0b — 2026-10-13

Compilación de documentación y pulido sobre la 1.2.0 (no cambia el comportamiento de los módulos).

### Documentación
- README reordenado (descripción, capturas, módulos, requisitos, instalación, actualizar, uso por módulo, operación, seguridad, estructura, licencia) y actualizado: primer ingreso con cambio de contraseña obligatorio, sección *Actualizar*, tabla de variables de entorno (`/etc/default/pi-console`), operación (`journalctl`, servicios, `remove`/`purge`), límite de intentos de login, requisitos (Raspberry Pi OS, DietPi o Debian 12+), estructura del repositorio y diagrama de arquitectura al día.
- Nuevo `README.en.md` (resumen en inglés) y archivo `LICENSE` (MIT).
- Capturas regeneradas para los 5 módulos en claro/oscuro y 4 resoluciones, más «Primer ingreso» y «Net Monitor vacío»; se quitaron las imágenes sueltas de la raíz.
- `docs/APT.md` indica que el repositorio APT está preparado pero sin publicar.

### Cambios menores
- **WOL Console:** la clave CSRF (`WOL_SECRET`) ahora es aleatoria y se guarda con permisos 600 en `wol-console/.csrf-secret`; ya no hay un valor por defecto conocido.
- **Página de inicio:** tarjetas en el orden del menú (UPS, Net, Proxmox, WOL) y nueva tarjeta de Admin Panel.
- Se eliminó `auth/static/login.html` (código muerto, sin referencias).

## 1.2.0 — 2026-10-13

Release final de la serie 1.2: reúne la base 1.2.0 (12-oct) y las compilaciones de prueba de instalación nueva 1.2.0a a 1.2.0e, que se reemplazan por esta versión. Resumen por compilación, de la más nueva a la más antigua:

### Compilación 1.2.0e (2026-10-13)

#### Net Monitor
- **El «Hacer escaneo inicial» se comporta igual que el botón «Escanear red»**: ambos llaman a la misma función, pero el botón inicial tardaba ~1,5 s en reaccionar (seguía clicable y mostrando «Sin hosts descubiertos» hasta la primera consulta de estado). Ahora, venga de donde venga el clic, al instante se muestran la barra de progreso, el botón superior ocupado y la lista vacía en «Escaneando…».

### Compilación 1.2.0d (2026-10-13)

#### Seguridad
- **Permisos entre módulos («solo das lo que tienes»).** En el Admin Panel, un administrador solo puede dar o quitar permisos en los módulos donde él mismo tiene ese nivel (un admin de WOL ya no puede dar ni quitar permisos en Net o Proxmox) y no puede borrar ni cambiar la contraseña de un usuario con más permisos que él. Los valores por defecto al crear un usuario se limitan a lo que el admin puede dar.
- **Respaldos (Teleporter) solo para admins de todos los módulos**: contienen hashes de contraseñas, tokens de Proxmox y la configuración completa. A los demás admins la tarjeta se les oculta y la API responde 403.
- **Proxmox: aviso permanente de certificado sin verificar** en cada cluster sin huella fijada (con el botón «Fijar certificado» para admins), y una advertencia en el log al arrancar el servicio.
- **Cookie de sesión `Secure` opcional**: con `PICONSOLE_SECURE_COOKIE=1` en `/etc/default/pi-console` (leído por las 5 unidades systemd) la cookie lleva `Secure`. Apagado por defecto: Pi Console se usa por HTTP en la LAN.
- README: nueva sección **Seguridad** (uso en LAN de confianza por HTTP, HTTPS opcional delante, permisos por módulo, certificados de Proxmox).

### Compilación 1.2.0c (2026-10-13)

#### Instalación nueva
- **Cambio de contraseña obligatorio en el primer ingreso.** La cuenta inicial `admin`/`admin` (y cualquier cuenta marcada «debe cambiar contraseña» desde el Admin Panel) pasa por una pantalla de cambio de contraseña antes de entrar a cualquier módulo; al guardarla vuelve al módulo desde el que ingresó y ya puede navegar a los demás. Se exige la contraseña actual, una nueva de al menos 6 caracteres y distinta de la actual.
- **Se aplica en el servidor, no solo en la página**: mientras la contraseña esté pendiente, la sesión no sirve en ningún módulo (todas las llamadas dan 401) salvo para cambiarla (`/admin/change-password`). Funciona con cualquier usuario, también sin permisos de administrador. Al cambiarla se cierran las demás sesiones de esa cuenta.
- **Net Monitor no escanea nada por defecto** en una instalación nueva: arranca en modo manual (intervalo 0) y, cuando no hay equipos, la página muestra la red detectada y el botón **«Hacer escaneo inicial»**. Se puede activar el escaneo automático en Ajustes. Las instalaciones existentes conservan su intervalo.
- En modo manual (intervalo 0) Net Monitor tampoco escanea al arrancar el servicio; antes lo hacía siempre una vez.
- **El escaneo va poblando la lista**: cada equipo encontrado se guarda enseguida (como máximo cada 2 s) y la página se refresca cada 3 s durante el escaneo, sin esperar a que termine toda la red. Mientras escanea con la lista vacía muestra «Escaneando…».

#### UPS Monitor
- **Primera UPS recién agregada**: la tabla muestra «Conectando con el servidor NUT…» (en vez de «No UPS found») y la página refresca cada 1,5 s hasta que llegan los datos, sin recargar a mano. Las dos primeras lecturas de cada UPS se guardan de inmediato, así los gráficos tienen puntos a los pocos segundos en vez de esperar hasta 60 s.
- El subtítulo «NUT · APC · Eaton» pasa a «NUT UPS».

### Compilación 1.2.0b (2026-10-13)

#### Instalación nueva
- **UPS Monitor ya no crea un servidor «Local» por defecto**: una instalación nueva empieza sin servidores (no hace falta tener una UPS); se agrega uno desde la página. Las instalaciones existentes conservan los suyos.
- **`snmp` pasa a ser dependencia** del paquete (antes solo sugerida), para que la fuente SNMP de Net Monitor funcione sin pasos extra.
- **Net Monitor**: la red a escanear por defecto es la /24 de la IP de la máquina (antes fijaba una red fija); se puede cambiar con `SCAN_NETWORK`. Los servidores Pi-hole ya no vienen precargados.
- Los ejemplos (placeholders) de IP en WOL, UPS, Net Monitor y Proxmox usan direcciones de documentación (`192.0.2.x`) en lugar de IP de una red real.
- Orden de navegación por defecto en todas las páginas: UPS Monitor, Net Monitor, Proxmox, WOL Console, Admin Panel (quien ya reordenó el menú conserva su orden).

### Compilación 1.2.0a (2026-10-13)

#### Correcciones
- **Instalación nueva: la página de inicio daba `500 Internal Server Error`.** nginx servía `/` desde `/opt/pi-console-home/`, pero el paquete instala la portada en `/opt/pi-console/home/`; la carpeta antigua solo existía en equipos con instalación manual previa. Ahora nginx usa `/opt/pi-console/home` (también en actualizaciones: la portada se actualiza con el paquete).
- Documentación: la instalación indica `apt-get install ./pi-console_X.deb` (resuelve dependencias) en lugar de `dpkg -i`.

### Base 1.2.0 (2026-10-12)

Primer release de la serie 1.2. Reúne todos los cambios de 1.1.8b a 1.1.9j (listados abajo) y agrega el código comentado.

#### Código comentado en español e inglés
- Todo el código fuente lleva comentarios en **español** y, a continuación, en **inglés** (marcados con `EN:`): los 5 servicios Python, el módulo de autenticación, `teleporter.sh`, los scripts de salud y recursos, los scripts del paquete (`postinst`, `preinst`, `prerm`, `postrm`), la configuración de nginx y las 7 páginas HTML. Cada archivo empieza con un mapa de su estructura y el flujo de datos; cada función explica qué hace y, cuando importa, por qué.
- Solo se agregaron comentarios; la lógica no cambió. Se verificó que el código sin comentarios quedara idéntico (Python por AST; shell, nginx y HTML por comparación de líneas, más `bash -n` y `node --check`).
- Los mensajes de log y de error de los servicios que quedaban en español ahora están en inglés («Admin permission required», «Duplicate MAC», «Scan finished…», etc.).

#### Interfaz
- En pantallas de hasta 960 px la barra lateral estaba oculta y no había forma de cambiar de módulo. Ahora hay un botón de menú (☰) en la barra superior que abre la navegación como panel lateral, con fondo atenuado; se cierra al tocar el fondo, un enlace o con Esc. Aplica a WOL Console, UPS Monitor, Net Monitor, Proxmox y Admin Panel.
- La barra superior pasa a varias filas en móvil para que todos sus controles (idioma, tema, usuario, escaneo) sean alcanzables.
- Todas las páginas (WOL, UPS, Net Monitor, Proxmox y Admin, incluida la pantalla de login) muestran *Pi Console vX.Y.Z* en el pie. La versión sale del archivo `/opt/pi-console/VERSION` que instala el paquete, vía `GET /api/version` de cada servicio (también aparece en `/api/health`).
- Diseño: en pantallas de laptop (≈1366 px o menos) Net Monitor y WOL Console se salían de la pantalla por la derecha porque la barra superior no cabía; ahora la barra se acomoda en varias filas y no hay desbordamiento horizontal entre 320 y 1366 px. En móvil, el Admin Panel ya no se ensancha más que la pantalla (las tablas se desplazan dentro de su tarjeta).
- Net Monitor: textos que quedaban en español con la interfaz en inglés («Todos», «seg», «cada 1h», «hace 8m», tooltips, detalle del host, progreso del escaneo) ahora siguen el idioma elegido.
- Móvil: en el Admin Panel las tablas se desplazan dentro de su tarjeta sin mover el título ni el botón *New user*, y la barra superior alinea sus márgenes con el contenido. En UPS Monitor la tabla de resumen cabe en pantallas de 360 px aunque el modelo/serie sea largo, y el panel de detalle del UPS queda siempre visible aunque la tabla se desplace.
- Móvil: en el Admin Panel la lista de usuarios y la de backups pasan a tarjetas (una por usuario/backup), sin columnas cortadas ni desplazamiento lateral.
- Tablets (≈800–1280 px, p. ej. iPad horizontal): en WOL Console el panel *Add device* pasa debajo de la tabla y el botón *Wake* ya no queda cortado; en Net Monitor el vendor/MAC se muestra solo en la fila expandida, los nombres largos se parten y la tabla cabe sin desplazarse aunque haya muchos puertos abiertos.

#### WOL Console
- Lee los hosts de Net Monitor (`net-monitor/hosts.json`, solo lectura): en *Add device* aparece **From Net Monitor** (solo admin con acceso a Net Monitor) para elegir un host detectado; rellena nombre, MAC, IP y categoría (computer→PC, storage→NAS, el resto→OTHER). Los ya agregados aparecen deshabilitados.
- Si Net Monitor conoce otra IP para la misma MAC (DHCP), la tabla muestra la IP de Net Monitor (la guardada queda tachada) y *Wake* la usa para comprobar si el equipo ya está encendido.
- Nuevo endpoint `GET /api/netmonitor/hosts` (requiere permiso `net` de lectura). Variables opcionales: `NET_HOSTS_FILE` (WOL) y `WOL_DEVICES_FILE` (Net Monitor).

#### UPS Monitor
- Los servidores NUT ahora se pueden **editar** (nombre, host y puerto) desde el botón de lápiz de la barra lateral, además de eliminarlos. Al cambiar host o puerto se reconecta de inmediato y se descartan los datos del destino anterior; el historial se conserva. Nuevo endpoint `PUT /api/servers/<id>` (solo admin).
- La cabecera de los dos gráficos (voltaje y consumo) ahora tiene el mismo diseño: título a la izquierda, rangos 1h/1d/1mo/All a la derecha y la leyenda entre ambos; en pantallas de hasta 700 px, título y rangos en la primera línea y la leyenda debajo, igual en los dos. Antes el gráfico de voltaje pasaba los rangos a una segunda línea y el de consumo no.
- Se pueden eliminar todos los servidores, incluido el *Local*. Sin servidores el panel muestra "No UPS found" y el resto de los módulos no se ve afectado; la lista vacía se conserva tras reiniciar y se puede volver a agregar un servidor cuando se quiera. Antes solo el servidor Local no se podía eliminar.

#### Net Monitor
- Nuevos tipos de dispositivo **printer** (impresora) y **tablet**. Impresoras: fabricantes (Brother, Canon, Epson, Lexmark, Xerox, Ricoh, Kyocera…), nombres de host (NPI…, LaserJet, MFC…), puertos 9100/515/631 y banners. Tablets: iPad, Galaxy Tab, Kindle, MiPad, etc.; un iPhone/Android sigue siendo *phone*. Disponibles en filtros y en la edición manual.
- Los hosts que están registrados en WOL Console (misma MAC) muestran la etiqueta **WOL**.
- La tabla de hosts ya no se desborda en pantallas angostas: hasta 700 px se ocultan las columnas Vendor/MAC, puertos, latencia y último visto, y hasta 480 px también OS. Todo eso sigue disponible al expandir la fila (toca el nombre del host).

#### Módulo de salud
- Cada servicio expone `GET /api/health` (sin login: solo niveles ok/warn/fail; con sesión, el detalle) y responde 503 si algo falla. Revisa archivos de datos legibles/escribibles, espacio en disco, y por módulo: WOL (red y lista de Net Monitor), UPS (base de datos, que el historial **realmente se esté guardando**, pollers vivos, upsd respondiendo), Net Monitor (escaneo trabado, temporizador de auto-escaneo armado) y Proxmox (pollers vivos, clusters respondiendo).
- El Admin Panel agrega la salud de todos los módulos en una tarjeta **Salud del sistema** (se refresca cada 30 s) y en `GET /admin/api/health`.
- Cada módulo de la tarjeta se expande al hacer clic y muestra todo lo que se revisa: cada chequeo con su descripción, su nivel (verde/naranja/rojo) y el detalle (espacio libre, filas pendientes, error exacto, tiempo activo). Se mantiene abierto al refrescar.
- Nuevo comando `pi-console-health` (código de salida 0 = ok, 1 = degradado, 2 = falla; `-j` muestra el JSON), útil para cron o monitoreo externo.
- **Fuente de la Raspberry Pi:** el Admin Panel y `pi-console-health` muestran el chequeo `power` con aviso cuando la Pi registra subtensión o limitación (por fuente o cable insuficiente), sea ahora o desde el arranque. Solo aparece en una Raspberry Pi: en una VM u otro equipo no se muestra. Los eventos «desde el arranque» solo se borran al reiniciar. El instalador agrega al usuario del servicio al grupo `video` en una Pi para poder leer `vcgencmd get_throttled`.

#### Revisión de código: bloqueos, concurrencia y robustez
- **Servidores HTTP multihilo con timeout** (WOL, UPS, Net Monitor, Proxmox, Admin): antes eran de un solo hilo, así que un cliente lento o colgado bloqueaba todo el módulo. Ahora cada conexión tiene su hilo y un timeout.
- **`users.json` y `sessions.json` compartidos por 5 procesos**: lectura-modificación-escritura bajo `flock`, escritura atómica (fsync + rename, archivo temporal propio) y copia `.bak` de la última versión válida. Archivos con permisos 0600. Un `users.json` dañado ya no reactiva `admin/admin`: se usa la copia `.bak` o, sin ella, no entra nadie hasta borrar el archivo.
- **Sesiones**: usuarios eliminados o con permisos reducidos pierden el acceso de inmediato (antes seguía vigente hasta 24 h); al cambiar contraseña o eliminar un usuario se cierran sus otras sesiones.
- **Datos de cada módulo** (`devices.json`, `wake_log.json`, `servers.json`, `hosts.json`, `config.json`, `clusters.json`): escritura atómica con copia `.bak`, y las altas/bajas/ediciones concurrentes ya no se pisan entre sí. `config.json` y `clusters.json` (tokens, SNMP, Pi-hole) pasan a 0600.
- **UPS Monitor**: un `ERR DATA-STALE` de upsd ya no inserta filas en cero en el historial; la base espera hasta 30 s por un bloqueo en vez de fallar; un error inesperado no mata el hilo de consulta (se reinicia solo); `/api/test` requiere admin.
- **Net Monitor**: dos escaneos simultáneos ya no pueden arrancar; el escaneo siempre libera su estado y reprograma un único temporizador (antes un reescaneo de una IP o un cambio de intervalo podían acumular temporizadores); cambiar el intervalo ya no borraba la configuración SNMP/OUI/Pi-hole; borrar un host durante un escaneo ya no reaparece; validación de IP/intervalo.
- **WOL Console**: envío del magic packet nativo (ya no depende del paquete `wakeonlan`, que no estaba declarado) y respeta el puerto del dispositivo; `/api/ping` valida el host (no acepta opciones de línea de comandos); contador de rate-limit con bloqueo y limpieza.
- **Proxmox**: `/api/test` requiere admin; el token API no se devuelve al crear un cluster; el hilo de consulta no muere por un error de lectura de configuración.

#### Correcciones
- **UPS Monitor dejaba de guardar el historial (gráficos de consumo sin datos nuevos)**: aproximadamente 4 horas después de iniciar el servicio, la limpieza periódica de la base (`db_prune`) fallaba con `database table is locked` y dejaba abierta su conexión; desde ese momento todos los guardados fallaban con `database is locked` hasta reiniciar el servicio. Ahora la limpieza cierra la transacción antes de compactar el WAL, siempre libera la conexión y un error ahí ya no afecta al resto.
- Los servicios aceptan ráfagas de conexiones simultáneas (cola de escucha de 5 a 128): antes, 30 peticiones a la vez podían terminar con la conexión reiniciada.

#### Documentación
- Capturas de pantalla de todos los módulos (claro/oscuro, 4 resoluciones) en `docs/screenshots/` y galería en el README.

#### Idioma
- Quedaban textos en español con la interfaz en inglés en WOL Console (filtro «Todos», tooltips, avisos y el «hace 8m»), UPS Monitor (tooltips y campo de servidor) y Proxmox Monitor («Conectando…», «Sin nodos»): ahora siguen el idioma elegido. Las fechas usan el formato del idioma.
- Mensajes de error del backend traducidos al inglés («User already exists», «Device not found», «Not found», «That host:port already exists», «Magic packet sent to …»).

#### Herramientas
- Nuevo comando `pi-console-resources`: memoria (RSS) y CPU de cada servicio, de nginx y RAM libre del sistema (`-w` para verlo en vivo). Sirve para decidir si hace falta mover Pi Console fuera de la Pi.

#### Seguridad
- Contraseñas: ahora se guardan con **scrypt** y una sal aleatoria por usuario (antes SHA-256 con una sal fija). Los usuarios existentes se migran solos en su próximo inicio de sesión; los respaldos antiguos siguen funcionando.
- Inicio de sesión: tras 5 intentos fallidos desde la misma IP se bloquea el acceso durante 5 minutos (respuesta 429). Cada fallo añade una pequeña espera, y un usuario inexistente tarda lo mismo que uno real. Los contadores son por servicio y se reinician al reiniciarlo.
- nginx: cabeceras `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` y una política `Content-Security-Policy` básica.
- **users.json ausente (SEC-01):** si el archivo de usuarios desaparece en una instalación ya usada, ya no se vuelve a crear el usuario `admin` / `admin`: se usa la copia `.bak` o, si no existe, nadie puede entrar hasta restaurarla. El usuario inicial solo se crea en una instalación nueva (marcador `.users-initialized` en `/var/lib/pi-console`).
- **WOL Console** escucha solo en `127.0.0.1`, como los demás módulos; se accede por nginx (puerto 80).
- **Permisos explícitos (PVE-01):** `net` y `pve` ya no se derivan del permiso WOL en cada petición. Al arrancar los servicios se migran una sola vez a valores explícitos (admin si era admin de WOL, solo lectura en otro caso) y un permiso ausente significa sin acceso. El Admin Panel muestra y edita ahora las columnas **Net Monitor** y **Proxmox**; los usuarios nuevos reciben *Sin acceso* a ambos por defecto.
- **Proxmox, certificado (PVE-02):** al agregar un cluster se muestra la huella SHA-256 del certificado y hay que confirmarla (botón *Probar* dos veces) antes de enviar el token; la conexión queda fijada a esa huella y falla si el certificado cambia. Los clusters existentes siguen funcionando, pero muestran el aviso «Certificado sin verificar» con un botón para fijarlo.
- **Restore de NUT y nginx solo por consola (SEC-03):** el panel ya no ofrece restaurar `/etc/nut` ni el sitio nginx (corrían como root vía sudo); `teleporter restore --nut` / `--nginx` sigue disponible en la consola. `teleporter.sh gui-restore` rechaza esas opciones.
- **Bloqueo entre procesos (CON-01):** si no se puede obtener el bloqueo de archivo, la operación falla con error en lugar de continuar sin él.

#### Instalación
- Los mensajes de instalación, actualización y desinstalación (`postinst`, `preinst`, `prerm`, `postrm`) ahora están en inglés.

## 1.1.8 — 2026-10-10

Reúne los cambios de 1.1.7 y sus revisiones (1.1.7a–1.1.7f).

### Net Monitor
- Tipos de dispositivo: computer, phone, tablet, printer, router, switch, ap, storage, tv, camera, appliance, other. Columna *Type*, filtros por tipo y edición manual (`auto` vuelve a la detección).
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
