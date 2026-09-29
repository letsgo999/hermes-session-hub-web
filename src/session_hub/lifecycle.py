import json
import os
import socket
import sys
import time
from pathlib import Path

from . import PRODUCT_NAME


class InstanceLock:
    def __init__(self, run_dir):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.run_dir / "instance.json"
        self._owned = False
        self._pid = None

    def acquire(self, pid=None, port=None, token=None, nonce=None, csrf=None):
        pid = pid or os.getpid()
        if self.lock_file.exists():
            try:
                data = json.loads(self.lock_file.read_text(encoding="utf-8"))
                if data.get("product") == PRODUCT_NAME and not _pid_alive(int(data.get("pid", -1))):
                    self.lock_file.unlink()
                else:
                    return False
            except Exception:
                stale = self.run_dir / f"instance.stale.{int(time.time())}.json"
                self.lock_file.replace(stale)
        payload = {
            "product": PRODUCT_NAME,
            "pid": pid,
            "port": port,
            "token": token,
            "nonce": nonce,
            "csrf": csrf,
            "executable": str(Path(sys.executable).resolve()),
        }
        try:
            fd = os.open(self.lock_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            return False
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            self.lock_file.unlink(missing_ok=True)
            raise
        self._owned = True
        self._pid = int(pid)
        return True

    def release(self):
        if self._owned and self.lock_file.exists():
            try:
                data = json.loads(self.lock_file.read_text(encoding="utf-8"))
                if data.get("product") == PRODUCT_NAME and int(data.get("pid", -1)) == self._pid:
                    self.lock_file.unlink()
            except Exception:
                pass
        self._owned = False
        self._pid = None


def _pid_alive(pid):
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def validate_stop_request(lock_file, requester_pid, nonce=None):
    try:
        data = json.loads(Path(lock_file).read_text(encoding="utf-8"))
    except Exception:
        return False
    if data.get("product") != PRODUCT_NAME or int(data.get("pid", -1)) != int(requester_pid):
        return False
    if nonce is not None and data.get("nonce") != nonce:
        return False
    return True


def free_loopback_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
