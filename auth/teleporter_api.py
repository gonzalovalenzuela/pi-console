"""Teleporter helpers for the admin panel: list, create, upload, verify and restore
backups. Privileged work is done by /usr/local/bin/teleporter.sh through sudo; this
module only validates names/sizes and talks to that script."""
import os, re, subprocess, time
from pathlib import Path

BIN        = os.environ.get("TELEPORTER_BIN", "/usr/local/bin/teleporter.sh")
SUDO       = os.environ.get("TELEPORTER_SUDO", "sudo -n").split()
SPOOL      = Path(os.environ.get("TELEPORTER_SPOOL", "/var/lib/pi-console/teleporter"))
MAX_UPLOAD = int(os.environ.get("TELEPORTER_MAX_UPLOAD", 200 * 1024 * 1024))
NAME_RE    = re.compile(r"^(pi-console-[A-Za-z0-9._-]{1,80}|upload-\d{8}_\d{6})\.tar\.gz$")
RESULT_RE  = re.compile(r"^RESULT: (\w+)\s*$", re.M)
OUT_LIMIT  = 20000


def valid_name(name):
    return isinstance(name, str) and bool(NAME_RE.match(name))


def path_of(name):
    """Return the spool path for a validated name (never follows symlinks)."""
    if not valid_name(name):
        return None
    p = SPOOL / name
    return p if p.is_file() and not p.is_symlink() else None


def available():
    return os.path.isfile(BIN)


def _tail(text, limit=OUT_LIMIT):
    return text if len(text) <= limit else "…" + text[-limit:]


def run(args, sudo=False, timeout=180):
    cmd = (SUDO if sudo else []) + [BIN] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "The operation timed out"
    except FileNotFoundError:
        return False, "teleporter.sh is not installed"
    except Exception as e:
        return False, f"Could not run teleporter.sh: {e}"
    out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
    return p.returncode == 0, _tail(out.strip())


def list_backups():
    items = []
    try:
        for p in SPOOL.iterdir():
            if not valid_name(p.name) or p.is_symlink() or not p.is_file():
                continue
            st = p.stat()
            items.append({"name": p.name, "size": st.st_size, "mtime": int(st.st_mtime),
                          "kind": "upload" if p.name.startswith("upload-") else "backup"})
    except FileNotFoundError:
        pass
    items.sort(key=lambda i: i["mtime"], reverse=True)
    return items


def create_backup():
    ok, out = run(["gui-backup"], sudo=True, timeout=300)
    name = None
    m = re.search(r"^BACKUP_FILE=(\S+)\s*$", out, re.M)
    if m and valid_name(m.group(1)):
        name = m.group(1)
    return ok and name is not None, name, out


def save_upload(rfile, length):
    """Stream `length` bytes from rfile into the spool. Returns (name, error)."""
    if length <= 0:
        return None, "Empty upload"
    if length > MAX_UPLOAD:
        return None, f"File too large (limit {MAX_UPLOAD // (1024 * 1024)} MB)"
    try:
        SPOOL.mkdir(parents=True, exist_ok=True)
        os.chmod(SPOOL, 0o700)
    except OSError as e:
        return None, f"Cannot use the backup directory: {e}"
    tmp = SPOOL / f".upload-{os.getpid()}.tmp"
    got, first = 0, b""
    try:
        with open(tmp, "wb") as f:
            os.chmod(tmp, 0o600)
            while got < length:
                chunk = rfile.read(min(1 << 20, length - got))
                if not chunk:
                    break
                if not first:
                    first = chunk[:2]
                f.write(chunk)
                got += len(chunk)
        if got != length:
            tmp.unlink(missing_ok=True)
            return None, "Upload interrupted"
        if first != b"\x1f\x8b":
            tmp.unlink(missing_ok=True)
            return None, "Not a .tar.gz file"
        for _ in range(5):
            name = time.strftime("upload-%Y%m%d_%H%M%S.tar.gz")
            dest = SPOOL / name
            if not dest.exists():
                os.replace(tmp, dest)
                return name, None
            time.sleep(1.1)
        tmp.unlink(missing_ok=True)
        return None, "Could not allocate a file name"
    except OSError as e:
        try: tmp.unlink(missing_ok=True)
        except OSError: pass
        return None, f"Could not save the upload: {e}"


def verify(name):
    p = path_of(name)
    if not p:
        return False, "Backup not found"
    return run(["check", str(p)], sudo=False, timeout=180)


def start_restore(name, nut=True, nginx=False):
    if not path_of(name):
        return False, "Backup not found"
    ok, out = run(["gui-restore", name, "1" if nut else "0", "1" if nginx else "0"],
                  sudo=True, timeout=60)
    return ok and "RESTORE_STARTED=1" in out, out


def delete(name):
    p = path_of(name)
    if not p:
        return False
    try:
        p.unlink()
        return True
    except OSError:
        return False


def restore_status():
    log = SPOOL / "restore.log"
    try:
        st = log.stat()
        text = log.read_text(errors="replace")
    except (FileNotFoundError, PermissionError):
        return {"state": "idle", "log": ""}
    m = RESULT_RE.findall(text)
    if m:
        state = m[-1]                      # ok | errors | failed
    elif time.time() - st.st_mtime < 900:
        state = "running"
    else:
        state = "failed"
    return {"state": state, "log": _tail(text, 8000), "mtime": int(st.st_mtime)}
