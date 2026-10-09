#!/bin/bash
# teleporter.sh — backup, verify and restore Pi Console (data + NUT + nginx)
#
#   teleporter backup  [file.tar.gz]        create a backup (needs root)
#   teleporter check   <file.tar.gz>        verify a backup (no changes made)
#   teleporter restore <file.tar.gz> [-y]   restore it on this Pi (needs root)
#
# Installed as /usr/local/bin/teleporter.sh, with a `teleporter` symlink.
#
# Design notes (lessons learned):
#  * users.json / sessions.json live in /var/lib/pi-console and /opt/pi-console-auth
#    holds SYMLINKS to them — restore writes the real file and re-creates the links.
#  * history.db is copied with the SQLite backup API (consistent while running);
#    stale -wal/-shm files are removed on restore.
#  * `check` runs before every restore; nothing is touched if the archive is bad.
#  * A safety snapshot of the current state is taken before restoring.
#  * Services are always restarted, even if the restore fails half way.
#  * Archive members are whitelisted: absolute paths, "..", links are rejected.
#  * Files with secrets (tokens, SNMP/NUT passwords) are stored/restored 0600.
set -uo pipefail

TELEPORTER_VERSION="2.1.0"

# Paths (overridable through the environment, used by the tests).
# Under sudo (the admin panel) every override is dropped: only the defaults apply.
if [ -n "${SUDO_USER:-}" ]; then
  unset PICONSOLE_HOME PICONSOLE_DATA PICONSOLE_AUTH_LINK PICONSOLE_NUT_DIR PICONSOLE_NGINX_CONF \
        PICONSOLE_NGINX_ENABLED PICONSOLE_SAFETY_DIR PICONSOLE_LOCK TELEPORTER_SKIP_SYSTEM
fi
PI_HOME="${PICONSOLE_HOME:-/opt/pi-console}"
DATA_DIR="${PICONSOLE_DATA:-/var/lib/pi-console}"
AUTH_DIR="${PICONSOLE_AUTH_LINK:-/opt/pi-console-auth}"
NUT_DIR="${PICONSOLE_NUT_DIR:-/etc/nut}"
NGINX_CONF="${PICONSOLE_NGINX_CONF:-/etc/nginx/sites-available/pi-console.conf}"
NGINX_ENABLED="${PICONSOLE_NGINX_ENABLED:-/etc/nginx/sites-enabled/pi-console.conf}"
SAFETY_DIR="${PICONSOLE_SAFETY_DIR:-/var/backups/pi-console}"
SPOOL_DIR="$DATA_DIR/teleporter"      # backups/uploads handled by the admin panel
LOCK_FILE="${PICONSOLE_LOCK:-/run/lock/pi-console-teleporter.lock}"
SERVICE_USER="pi-console"
SERVICES="wol-console nut-monitor admin-panel net-monitor proxmox-monitor"
SKIP_SYSTEM="${TELEPORTER_SKIP_SYSTEM:-0}"   # 1 = no systemctl/nginx/chown (tests)

# member-in-archive | real path on disk
DATA_FILES=(
  "data/users.json|$DATA_DIR/users.json"
  "data/sessions.json|$DATA_DIR/sessions.json"
  "data/wol-console/devices.json|$PI_HOME/wol-console/devices.json"
  "data/wol-console/wake_log.json|$PI_HOME/wol-console/wake_log.json"
  "data/nut-monitor/servers.json|$PI_HOME/nut-monitor/servers.json"
  "data/nut-monitor/history.db|$PI_HOME/nut-monitor/history.db"
  "data/net-monitor/hosts.json|$PI_HOME/net-monitor/hosts.json"
  "data/net-monitor/config.json|$PI_HOME/net-monitor/config.json"
  "data/proxmox-monitor/clusters.json|$PI_HOME/proxmox-monitor/clusters.json"
)
CONF_FILES=(
  "conf/nginx/pi-console.conf|$NGINX_CONF"
  "conf/nut/nut.conf|$NUT_DIR/nut.conf"
  "conf/nut/ups.conf|$NUT_DIR/ups.conf"
  "conf/nut/upsd.conf|$NUT_DIR/upsd.conf"
  "conf/nut/upsd.users|$NUT_DIR/upsd.users"
  "conf/nut/upsmon.conf|$NUT_DIR/upsmon.conf"
)

# ── output helpers ────────────────────────────────────────────────────────────
if [ -t 1 ]; then G=$'\033[0;32m'; Y=$'\033[1;33m'; R=$'\033[0;31m'; B=$'\033[0;34m'; N=$'\033[0m'
else G=""; Y=""; R=""; B=""; N=""; fi
ok()   { echo "  ${G}✓${N} $*"; }
warn() { echo "  ${Y}!${N} $*"; WARNINGS=$((WARNINGS+1)); }
err()  { echo "  ${R}✗${N} $*" >&2; ERRORS=$((ERRORS+1)); }
hdr()  { echo; echo "${B}▶ $*${N}"; }
die()  { echo "${R}Error:${N} $*" >&2; exit 1; }
WARNINGS=0; ERRORS=0

TMP=""
cleanup() { [ -n "$TMP" ] && rm -rf "$TMP"; }
trap cleanup EXIT

need_root() {
  [ "$SKIP_SYSTEM" = "1" ] && return 0
  [ "$(id -u)" -eq 0 ] || die "this command needs root: sudo teleporter $*"
}
need_tools() {
  for t in tar gzip python3 sha256sum; do
    command -v "$t" >/dev/null 2>&1 || die "missing required tool: $t"
  done
}
svc_user_exists() { id -u "$SERVICE_USER" >/dev/null 2>&1; }
is_secret() {
  case "$1" in
    *users.json|*sessions.json|*config.json|*clusters.json|*servers.json|*upsd.users|*upsmon.conf) return 0;;
  esac
  return 1
}

# ── validators ────────────────────────────────────────────────────────────────
validate_json() {  # file -> prints nothing, rc 0/1
  python3 -I - "$1" <<'PY' 2>/dev/null
import json, sys
with open(sys.argv[1], encoding="utf-8") as f: json.load(f)
PY
}
validate_sqlite() {  # file -> prints row count on success
  python3 -I - "$1" <<'PY' 2>/dev/null
import sqlite3, sys
c = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
r = c.execute("PRAGMA integrity_check").fetchone()
if not r or r[0] != "ok": sys.exit(1)
try: n = c.execute("SELECT COUNT(*) FROM history").fetchone()[0]
except Exception: n = "?"
print(n)
PY
}
users_have_admin() {
  python3 -I - "$1" <<'PY' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if isinstance(d, dict) and d else 1)
PY
}

# ── archive safety ────────────────────────────────────────────────────────────
# Rejects absolute paths, "..", links/devices and unknown members.
archive_is_safe() {  # archive
  local archive="$1" listing m
  gzip -t "$archive" 2>/dev/null || { err "not a valid gzip file"; return 1; }
  listing=$(tar -tzvf "$archive" 2>/dev/null) || { err "tar cannot read the archive"; return 1; }
  while IFS= read -r line; do
    case "${line:0:1}" in
      -|d) ;;
      *) err "archive contains a link or special file: $line"; return 1;;
    esac
  done <<<"$listing"
  while IFS= read -r m; do
    m="${m#./}"; m="${m%/}"
    if [ -z "$m" ] || [ "$m" = "." ]; then continue; fi
    case "$m" in
      /*|*..*) err "unsafe path in archive: $m"; return 1;;
    esac
    case "$m" in
      backup.json|SHA256SUMS|data|data/*|conf|conf/*) ;;
      *) err "unexpected member in archive: $m"; return 1;;
    esac
  done < <(tar -tzf "$archive")
  return 0
}

extract_archive() {  # archive dest
  tar -xzf "$1" -C "$2" --no-same-owner --no-same-permissions 2>/dev/null \
    || { err "could not extract the archive"; return 1; }
  # Legacy layout (teleporter 1.x): data/auth/{users,sessions}.json
  local f
  for f in users sessions; do
    if [ -f "$2/data/auth/$f.json" ] && [ ! -f "$2/data/$f.json" ]; then
      mv "$2/data/auth/$f.json" "$2/data/$f.json"
    fi
  done
  return 0
}

# ── BACKUP ────────────────────────────────────────────────────────────────────
cmd_backup() {
  need_root backup "$@"; need_tools; take_lock
  local dest="${1:-}"
  if [ -z "$dest" ]; then
    mkdir -p "$SAFETY_DIR" 2>/dev/null || true
    dest="$SAFETY_DIR/pi-console-$(hostname -s)-$(date +%Y%m%d_%H%M%S).tar.gz"
  fi
  case "$dest" in *.tar.gz|*.tgz) ;; *) dest="$dest.tar.gz";; esac
  [ -e "$dest" ] && die "destination already exists: $dest"
  [ -d "$(dirname "$dest")" ] || die "destination directory does not exist: $(dirname "$dest")"

  TMP=$(mktemp -d) || die "cannot create a temporary directory"
  trap cleanup EXIT
  umask 077
  mkdir -p "$TMP/data" "$TMP/conf"

  echo "${B}Pi Console Teleporter — backup${N}"
  echo "  Host: $(hostname)   Date: $(date -Iseconds)"

  hdr "Module data"
  local entry rel src n_data=0
  for entry in "${DATA_FILES[@]}"; do
    rel="${entry%%|*}"; src="${entry#*|}"
    if [ ! -f "$src" ]; then warn "$rel — not present, skipped"; continue; fi
    mkdir -p "$TMP/$(dirname "$rel")"
    if [[ "$rel" == *.db ]]; then
      if python3 -I - "$src" "$TMP/$rel" <<'PY'
import sqlite3, sys
s = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
d = sqlite3.connect(sys.argv[2])
s.backup(d); d.close(); s.close()
PY
      then ok "$rel ($(du -h "$TMP/$rel" | cut -f1)) — consistent SQLite snapshot"
      else err "$rel — SQLite backup failed"; continue; fi
    else
      cp -- "$src" "$TMP/$rel" || { err "$rel — copy failed"; continue; }
      if [[ "$rel" == *.json ]] && ! validate_json "$TMP/$rel"; then
        warn "$rel — source is not valid JSON (copied as is)"
      else ok "$rel ($(du -h "$TMP/$rel" | cut -f1))"; fi
    fi
    n_data=$((n_data+1))
  done

  hdr "System configuration"
  for entry in "${CONF_FILES[@]}"; do
    rel="${entry%%|*}"; src="${entry#*|}"
    if [ -r "$src" ] && [ -f "$src" ]; then
      mkdir -p "$TMP/$(dirname "$rel")"
      cp -- "$src" "$TMP/$rel" && ok "$src"
    else warn "$src — not present or unreadable, skipped"; fi
  done

  [ "$n_data" -gt 0 ] || die "no Pi Console data found — is the package installed?"

  hdr "Packing"
  local pkg_ver
  pkg_ver=$(dpkg-query -W -f='${Version}' pi-console 2>/dev/null || echo unknown)
  python3 -I - "$TMP" "$TELEPORTER_VERSION" "$pkg_ver" "$SERVICES" <<'PY'
import json, os, socket, subprocess, sys, time
tmp, tver, pver, services = sys.argv[1:5]
def state(s):
    try: return subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True).stdout.strip() or "unknown"
    except Exception: return "unknown"
json.dump({
  "teleporter_version": tver, "package_version": pver,
  "date": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "hostname": socket.gethostname(),
  "services": {s: state(s) for s in services.split()},
}, open(os.path.join(tmp, "backup.json"), "w"), indent=2)
PY
  ( cd "$TMP" && find data conf backup.json -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
  tar -czf "$dest" -C "$TMP" backup.json SHA256SUMS data conf || die "could not create $dest"
  chmod 600 "$dest"
  ok "Backup written: $dest ($(du -h "$dest" | cut -f1)) — mode 600, it contains passwords and tokens"

  # Verify what we just wrote
  hdr "Self-check"
  if cmd_check_quiet "$dest"; then ok "archive verified"; else die "the new archive failed verification"; fi
  echo; echo "${G}Backup completed.${N}  Next: teleporter check \"$dest\""
}

# ── CHECK ─────────────────────────────────────────────────────────────────────
# check_archive <archive> <extract-dir> ; fills counters, returns 1 on hard errors
check_archive() {
  local archive="$1" dir="$2" entry rel f size
  [ -f "$archive" ] || { err "file not found: $archive"; return 1; }
  archive_is_safe "$archive" || return 1
  extract_archive "$archive" "$dir" || return 1

  [ -f "$dir/backup.json" ] || { err "backup.json missing — not a Pi Console backup"; return 1; }
  validate_json "$dir/backup.json" || { err "backup.json is not valid JSON"; return 1; }

  if [ -f "$dir/SHA256SUMS" ]; then
    if ( cd "$dir" && sha256sum --quiet -c SHA256SUMS >/dev/null 2>&1 ); then ok "checksums match"
    else err "checksum mismatch — the archive is corrupted or was modified"; return 1; fi
  else warn "no SHA256SUMS (backup made by an older teleporter)"; fi

  local found=0
  for entry in "${DATA_FILES[@]}"; do
    rel="${entry%%|*}"; f="$dir/$rel"
    if [ ! -f "$f" ]; then warn "$rel — not in backup"; continue; fi
    found=$((found+1)); size=$(du -h "$f" | cut -f1)
    if [[ "$rel" == *.json ]]; then
      if validate_json "$f"; then ok "$rel ($size) — valid JSON"; else err "$rel — INVALID JSON"; fi
    else
      local rows
      if rows=$(validate_sqlite "$f"); then ok "$rel ($size) — SQLite OK, $rows rows"
      else err "$rel — SQLite CORRUPT"; fi
    fi
  done
  [ "$found" -gt 0 ] || { err "the backup contains no data files"; return 1; }
  if [ -f "$dir/data/users.json" ]; then
    users_have_admin "$dir/data/users.json" || err "data/users.json has no users — restoring it would lock you out"
  else warn "data/users.json not in backup: current users will be kept"; fi
  for entry in "${CONF_FILES[@]}"; do
    rel="${entry%%|*}"
    [ -f "$dir/$rel" ] && ok "$rel" || warn "$rel — not in backup"
  done
  [ "$ERRORS" -eq 0 ]
}

cmd_check_quiet() { local d; d=$(mktemp -d) || return 1; ( check_archive "$1" "$d" >/dev/null 2>&1 ); local rc=$?; rm -rf "$d"; return $rc; }

cmd_check() {
  need_tools
  [ $# -ge 1 ] || die "usage: teleporter check <file.tar.gz>"
  TMP=$(mktemp -d) || die "cannot create a temporary directory"
  echo "${B}Pi Console Teleporter — check${N}"
  echo "  Backup: $1"
  hdr "Archive"
  check_archive "$1" "$TMP"; local rc=$?
  if [ -f "$TMP/backup.json" ]; then
    hdr "Origin"
    python3 -I - "$TMP/backup.json" <<'PY' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
print("  Host:     %s" % d.get("hostname", "?"))
print("  Date:     %s" % d.get("date", "?"))
print("  Package:  %s   teleporter %s" % (d.get("package_version", "?"), d.get("teleporter_version", "?")))
PY
  fi
  echo
  if [ $rc -ne 0 ]; then echo "${R}Backup NOT usable — $ERRORS error(s), $WARNINGS warning(s).${N}"; exit 1
  elif [ $WARNINGS -gt 0 ]; then echo "${Y}Backup OK with $WARNINGS warning(s) (missing optional files).${N}"
  else echo "${G}Backup OK.${N}"; fi
}

# ── RESTORE ───────────────────────────────────────────────────────────────────
SERVICES_STOPPED=0
start_services() {
  [ "$SKIP_SYSTEM" = "1" ] && return 0
  systemctl daemon-reload 2>/dev/null || true
  local s
  for s in $SERVICES; do
    if systemctl start "$s" 2>/dev/null; then ok "$s started"
    else err "$s failed to start — journalctl -u $s -n 20"; fi
  done
}
RESTORE_FINISHED=0; RM_SOURCE=""
on_exit_restore() {
  local rc=$?
  # Always bring the services back, even after an abort.
  if [ "$SERVICES_STOPPED" -eq 1 ]; then SERVICES_STOPPED=0; echo; echo "Restarting services after abort…"; start_services; fi
  [ "$RESTORE_FINISHED" -eq 1 ] || echo "RESULT: failed"
  if [ -n "$RM_SOURCE" ]; then
    case "$(dirname "$RM_SOURCE")" in /var/tmp/teleporter.*) rm -rf -- "$(dirname "$RM_SOURCE")";; *) rm -f -- "$RM_SOURCE";; esac
  fi
  cleanup
  return $rc
}

install_file() {  # src dst mode owner:group
  local src="$1" dst="$2" mode="$3" owner="$4" tmpf
  mkdir -p "$(dirname "$dst")" || return 1
  tmpf="$dst.teleporter.$$"
  cp -- "$src" "$tmpf" && chmod "$mode" "$tmpf" || { rm -f "$tmpf"; return 1; }
  [ "$SKIP_SYSTEM" = "1" ] || chown "$owner" "$tmpf" 2>/dev/null || true
  mv -f -- "$tmpf" "$dst"          # atomic replace; also replaces a stray symlink
}

cmd_restore() {
  need_root restore "$@"; need_tools
  local archive="" assume_yes=0 with_nut=1 with_nginx=0 rm_source=0 a
  for a in "$@"; do case "$a" in
    -y|--yes) assume_yes=1;;
    --no-nut) with_nut=0;;
    --nginx) with_nginx=1;;
    --rm-source) rm_source=1;;
    -*) die "unknown option: $a";;
    *) archive="$a";;
  esac; done
  [ -n "$archive" ] || die "usage: sudo teleporter restore <file.tar.gz> [-y] [--no-nut] [--nginx]"
  RM_SOURCE=""; [ "$rm_source" -eq 1 ] && RM_SOURCE="$archive"
  take_lock
  [ -d "$PI_HOME" ] || die "$PI_HOME not found — install the package first: sudo dpkg -i pi-console_*.deb"
  if [ "$SKIP_SYSTEM" != "1" ]; then svc_user_exists || die "system user '$SERVICE_USER' not found — install the package first"; fi

  TMP=$(mktemp -d) || die "cannot create a temporary directory"
  trap on_exit_restore EXIT
  umask 077
  echo "${B}Pi Console Teleporter — restore${N}"
  echo "  Backup: $archive"

  hdr "Verifying backup (nothing is changed yet)"
  check_archive "$archive" "$TMP" || die "the backup failed verification — aborting, no changes were made"

  echo
  echo "${Y}  This will OVERWRITE the current Pi Console data and NUT/nginx configuration.${N}"
  if [ "$assume_yes" -ne 1 ]; then
    read -r -p "  Continue? [y/N] " ans || ans=""
    [[ "$ans" =~ ^[yYsS]$ ]] || { echo "Cancelled."; exit 0; }
  fi

  hdr "Safety snapshot of the current state"
  mkdir -p "$SAFETY_DIR" && chmod 700 "$SAFETY_DIR"
  local snap="$SAFETY_DIR/pre-restore-$(date +%Y%m%d_%H%M%S).tar.gz"
  if ( ERRORS=0; cmd_backup "$snap" >/dev/null 2>&1 ); then ok "saved to $snap"
  else warn "could not create the safety snapshot (continuing)"; fi

  hdr "Stopping services"
  if [ "$SKIP_SYSTEM" != "1" ]; then
    local s; SERVICES_STOPPED=1
    for s in $SERVICES; do systemctl stop "$s" 2>/dev/null && ok "$s stopped" || warn "$s was not running"; done
  fi

  hdr "Restoring data"
  local entry rel dst src mode owner
  owner="$SERVICE_USER:$SERVICE_USER"
  mkdir -p "$DATA_DIR"
  [ "$SKIP_SYSTEM" = "1" ] || { chown "$owner" "$DATA_DIR" 2>/dev/null; chmod 750 "$DATA_DIR"; }
  for entry in "${DATA_FILES[@]}"; do
    rel="${entry%%|*}"; dst="${entry#*|}"; src="$TMP/$rel"
    [ -f "$src" ] || { warn "$rel — not in backup, current file kept"; continue; }
    [[ "$rel" == *.db ]] && rm -f "$dst-wal" "$dst-shm" "$dst-journal"
    if install_file "$src" "$dst" 600 "$owner"; then ok "$rel"; else err "$rel — could not be restored"; fi
  done

  hdr "Auth links"
  mkdir -p "$AUTH_DIR"
  ln -sf "$PI_HOME/auth/auth.py" "$AUTH_DIR/auth.py"
  ln -sf "$DATA_DIR/users.json" "$AUTH_DIR/users.json"
  ln -sf "$DATA_DIR/sessions.json" "$AUTH_DIR/sessions.json"
  if [ "$SKIP_SYSTEM" != "1" ]; then chown "$owner" "$AUTH_DIR"; chown -h "$owner" "$AUTH_DIR"/* 2>/dev/null; fi
  ok "$AUTH_DIR → $DATA_DIR"

  hdr "System configuration"
  local nginx_bak=""
  for entry in "${CONF_FILES[@]}"; do
    rel="${entry%%|*}"; dst="${entry#*|}"; src="$TMP/$rel"
    [ -f "$src" ] || { warn "$dst — not in backup, kept"; continue; }
    case "$rel" in
      conf/nut/*)
        if [ "$with_nut" -ne 1 ]; then warn "$dst — NUT restore disabled, kept"; continue; fi
        if [ ! -d "$NUT_DIR" ]; then warn "$NUT_DIR does not exist (is 'nut' installed?) — skipped"; continue; fi
        mode=640; grp=root; getent group nut >/dev/null 2>&1 && grp=nut
        install_file "$src" "$dst" "$mode" "root:$grp" && ok "$dst" || err "$dst — could not be restored";;
      conf/nginx/*)
        if [ "$with_nginx" -ne 1 ]; then warn "$dst — kept (the package ships its own; use --nginx to overwrite)"; continue; fi
        [ -f "$dst" ] && { nginx_bak="$TMP/nginx.prev"; cp -- "$dst" "$nginx_bak"; }
        install_file "$src" "$dst" 644 "root:root" && ok "$dst" || err "$dst — could not be restored";;
    esac
  done
  if [ "$SKIP_SYSTEM" != "1" ] && [ -f "$NGINX_CONF" ]; then
    ln -sf "$NGINX_CONF" "$NGINX_ENABLED"
    rm -f /etc/nginx/sites-enabled/default
    if command -v nginx >/dev/null 2>&1; then
      if nginx -t >/dev/null 2>&1; then systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null; ok "nginx reloaded"
      else
        err "nginx -t failed with the restored config"
        if [ -n "$nginx_bak" ]; then cp -- "$nginx_bak" "$NGINX_CONF" && nginx -t >/dev/null 2>&1 \
          && { systemctl reload nginx 2>/dev/null; warn "previous nginx config put back"; }; fi
      fi
    fi
  fi

  hdr "Permissions"
  if [ "$SKIP_SYSTEM" != "1" ]; then chown -R "$owner" "$PI_HOME"; fi
  ok "ownership of $PI_HOME fixed"

  hdr "Starting services"
  SERVICES_STOPPED=0
  start_services

  echo
  if [ "$ERRORS" -eq 0 ]; then echo "${G}Restore completed.${N}"; else echo "${Y}Restore finished with $ERRORS error(s) — review the messages above.${N}"; fi
  echo "  URL: http://$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "  Previous state: $snap"
  RESTORE_FINISHED=1
  if [ "$ERRORS" -eq 0 ]; then echo "RESULT: ok"; else echo "RESULT: errors"; fi
  [ "$ERRORS" -eq 0 ]
}

# ── lock (one backup/restore at a time) ───────────────────────────────────────
LOCK_HELD=0
take_lock() {
  [ "$LOCK_HELD" = 1 ] && return 0
  command -v flock >/dev/null 2>&1 || return 0
  mkdir -p "$(dirname "$LOCK_FILE")" 2>/dev/null || return 0
  { exec 9>"$LOCK_FILE"; } 2>/dev/null || return 0
  flock -n 9 || die "another backup/restore is already running"
  LOCK_HELD=1
}
release_lock() { exec 9>&-; LOCK_HELD=0; }

# ── admin-panel entry points (run through sudo as root; strict argument checks) ─
NAME_RE='^(pi-console-[A-Za-z0-9._-]{1,80}|upload-[0-9]{8}_[0-9]{6})\.tar\.gz$'
spool_init() {
  mkdir -p "$SPOOL_DIR" && chmod 700 "$SPOOL_DIR"
  [ "$SKIP_SYSTEM" = "1" ] || chown "$SERVICE_USER:$SERVICE_USER" "$SPOOL_DIR" 2>/dev/null || true
}
spool_prune() {  # keep the newest 5 backups, drop uploads older than a day
  local f i=0
  while IFS= read -r f; do i=$((i+1)); [ $i -gt 5 ] && rm -f -- "$f"; done < <(ls -1t "$SPOOL_DIR"/pi-console-*.tar.gz 2>/dev/null)
  find "$SPOOL_DIR" -maxdepth 1 -name 'upload-*.tar.gz' -mmin +1440 -delete 2>/dev/null || true
}

cmd_gui_backup() {
  need_root gui-backup "$@"; need_tools; take_lock
  spool_init
  local name="pi-console-$(hostname -s | tr -c 'A-Za-z0-9.\n-' '_')-$(date +%Y%m%d_%H%M%S).tar.gz"
  [[ "$name" =~ $NAME_RE ]] || die "could not build a valid backup name"
  cmd_backup "$SPOOL_DIR/$name" || exit 1
  [ "$SKIP_SYSTEM" = "1" ] || chown "$SERVICE_USER:$SERVICE_USER" "$SPOOL_DIR/$name" 2>/dev/null || true
  spool_prune
  echo "BACKUP_FILE=$name"
}

cmd_gui_restore() {  # <name> <nut:0|1> <nginx:0|1>
  need_root gui-restore "$@"; need_tools; take_lock
  local name="${1:-}" nut="${2:-1}" ngx="${3:-0}" src copy
  [[ "$name" =~ $NAME_RE ]] || die "invalid backup name"
  [[ "$nut" =~ ^[01]$ && "$ngx" =~ ^[01]$ ]] || die "invalid option"
  src="$SPOOL_DIR/$name"
  [ -f "$src" ] && [ ! -L "$src" ] || die "backup not found: $name"
  # Work on a root-owned private copy so the unprivileged user cannot swap the
  # file between verification and extraction.
  copy=$(mktemp -d /var/tmp/teleporter.XXXXXX) || die "cannot create a temporary directory"
  cp -- "$src" "$copy/restore.tar.gz" || { rm -rf "$copy"; die "could not copy the backup"; }
  chmod 600 "$copy/restore.tar.gz"
  local flags=(-y --rm-source); [ "$nut" = 0 ] && flags+=(--no-nut); [ "$ngx" = 1 ] && flags+=(--nginx)
  local log="$SPOOL_DIR/restore.log"
  release_lock   # the detached job takes it again
  spool_init; rm -f -- "$log"
  # Detached from the admin-panel cgroup: the restore stops and restarts that very service.
  if [ "$SKIP_SYSTEM" != "1" ] && command -v systemd-run >/dev/null 2>&1; then
    systemctl reset-failed pi-console-restore.service 2>/dev/null || true
    systemd-run --quiet --collect --unit=pi-console-restore \
      -p StandardOutput="file:$log" -p StandardError="file:$log" \
      "$0" restore "$copy/restore.tar.gz" "${flags[@]}" \
      || { rm -rf "$copy"; die "could not start the restore job"; }
  else
    ( setsid "$0" restore "$copy/restore.tar.gz" "${flags[@]}" >"$log" 2>&1 & )
  fi
  echo "RESTORE_STARTED=1"
}

# ── main ──────────────────────────────────────────────────────────────────────
usage() {
  cat <<EOF
Pi Console Teleporter v$TELEPORTER_VERSION

  teleporter backup  [file.tar.gz]        create a backup (default: $SAFETY_DIR/)
  teleporter check   <file.tar.gz>        verify a backup, changes nothing
  teleporter restore <file.tar.gz> [-y] [--no-nut] [--nginx]
                                          restore on this Pi (verifies first, takes a
                                          safety snapshot, restarts services). nginx is
                                          only overwritten with --nginx; --no-nut keeps
                                          the current NUT configuration.

Backup contents: users/sessions, WOL devices, UPS servers + history.db,
Net Monitor hosts + config (SNMP), Proxmox clusters, NUT config, nginx site.
The archive holds passwords and tokens (mode 600) — keep it private.
EOF
}
CMD="${1:-}"; [ $# -gt 0 ] && shift
case "$CMD" in
  backup)  cmd_backup "$@";;
  check)   cmd_check "$@";;
  restore) cmd_restore "$@";;
  gui-backup)  cmd_gui_backup "$@";;
  gui-restore) cmd_gui_restore "$@";;
  -h|--help|help|"") usage; [ -n "$CMD" ] || exit 1;;
  *) echo "Unknown command: $CMD" >&2; usage; exit 1;;
esac
