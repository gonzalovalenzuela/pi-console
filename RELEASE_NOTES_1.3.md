# Pi Console 1.3

## Español
Reúne los cambios desde 1.2.2 (builds 1.2.2a a 1.2.2g).

**Licencia:** desde esta versión Pi Console usa **PolyForm Noncommercial 1.0.0** (antes MIT). Es gratis para uso personal, hobby, estudio, educación y organizaciones sin fines de lucro. El uso comercial y los derivados comerciales requieren permiso escrito del autor. Las versiones anteriores siguen con su licencia MIT.

**Nuevo**
- Overview: tarjetas ordenables. Botón *Ordenar* con flechas ‹ › y manija ⠿ para arrastrar. *Restablecer orden* vuelve al de siempre. El orden se guarda en cada navegador y también vale en modo kiosko.
- Formato de hora 24 h / 12 h en todos los módulos. Por defecto 24 h.
- UPS Monitor: tiempo en línea desde el último corte, disponibilidad de 24 h, 7 d y 30 d, cortes de los últimos 30 días y último corte (fecha, duración y carga mínima). Los cortes pasados se reconstruyen del historial si el UPS informa voltaje de entrada. El Overview muestra una línea con lo mismo.
- Overview: botón *Abrir* en la tarjeta Raspberry Pi con el detalle del equipo: CPU por núcleo, memoria, discos, red, temperatura y energía. Los administradores también ven usuarios conectados, procesos y servicios con falla. Se actualiza cada 5 s y funciona en modo kiosko.

**Seguridad**
- Auditoría de lo nuevo: sin hallazgos críticos ni altos.
- El detalle de la Pi no carga la Raspberry Pi aunque lo pidan muchas sesiones. Las direcciones MAC solo las ven los administradores.
- Cortes del UPS: máximo 2000 por UPS.

**Correcciones**
- Detalle de la Pi: los usuarios conectados no aparecían en Raspberry Pi OS nuevo (Debian 13).

**Interno:** 31 pruebas automáticas en el repositorio y en GitHub Actions. Los módulos ya no crean archivos al importarse.

**Al actualizar:** no hay cambios de configuración. La base del UPS agrega una tabla de cortes sola, la primera vez que arranca.

**Instalar o actualizar**
```bash
wget https://github.com/gonzalovalenzuela/pi-console/releases/download/1.3/pi-console_1.3_all.deb
sha256sum pi-console_1.3_all.deb    # 32f9176c5b7820e8be04989cc2b99d656a83eb020923cf64c2605962f9fd0a61
sudo apt-get install -y ./pi-console_1.3_all.deb
```

## English
Includes every change since 1.2.2 (builds 1.2.2a to 1.2.2g).

**License:** from this version Pi Console uses the **PolyForm Noncommercial License 1.0.0** (it was MIT). It is free for personal use, hobby projects, study, education and non-profit organizations. Commercial use and commercial derivative works require the author's written permission. Earlier versions keep their MIT license.

**New**
- Overview: reorderable cards. *Reorder* button with ‹ › arrows and a ⠿ handle to drag. *Reset order* goes back to the usual one. The order is saved per browser and also applies in kiosk mode.
- 24 h / 12 h time format in every module. 24 h by default.
- UPS Monitor: time online since the last outage, 24 h, 7 d and 30 d availability, outages in the last 30 days and the last outage (date, duration and lowest charge). Past outages are rebuilt from the history if the UPS reports input voltage. The Overview shows a line with the same data.
- Overview: *Open* button on the Raspberry Pi card with the device details: per-core CPU, memory, disks, network, temperature and power. Administrators also see logged-in users, processes and failed services. It refreshes every 5 s and works in kiosk mode.

**Security**
- Review of the new code: no critical or high findings.
- The Pi details do not load the Raspberry Pi even if many sessions request them. MAC addresses are only shown to administrators.
- UPS outages: at most 2000 per UPS.

**Fixes**
- Pi details: logged-in users did not show on newer Raspberry Pi OS (Debian 13).

**Internal:** 31 automated tests in the repository and in GitHub Actions. Modules no longer create files when imported.

**When upgrading:** no configuration changes. The UPS database adds an outages table by itself the first time it starts.

**Install or upgrade**
```bash
wget https://github.com/gonzalovalenzuela/pi-console/releases/download/1.3/pi-console_1.3_all.deb
sha256sum pi-console_1.3_all.deb    # 32f9176c5b7820e8be04989cc2b99d656a83eb020923cf64c2605962f9fd0a61
sudo apt-get install -y ./pi-console_1.3_all.deb
```
