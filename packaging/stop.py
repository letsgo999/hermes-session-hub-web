import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PRODUCT_NAME = "Hermes Session Hub Web"


def _is_start_exe(pid, expected):
    if os.name != "nt":
        return False
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        f"(Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue).Path",
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=5)
    image = result.stdout.strip()
    if not image:
        return False
    return str(Path(image).resolve()).casefold() == str(Path(expected).resolve()).casefold()


def _post_shutdown(port, token, nonce, csrf):
    opener = urllib.request.build_opener()
    base = f"http://127.0.0.1:{int(port)}"
    opener.addheaders.append(("Cookie", f"hshw_auth={token}"))
    body = json.dumps({"nonce": nonce}).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/shutdown",
        data=body,
        method="POST",
        headers={
            "Host": f"127.0.0.1:{int(port)}",
            "Origin": base,
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        },
    )
    opener.open(req, timeout=5).read()


def main():
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HermesX" / "SessionHubStudent" / "run"
    lock = root / "instance.json"
    if not lock.exists():
        print("Hermes Session Hub Web is not running.")
        return 0
    data = json.loads(lock.read_text(encoding="utf-8"))
    if data.get("product") != PRODUCT_NAME:
        print("No validated Hermes Session Hub Web process found.")
        return 1
    pid = int(data.get("pid", -1))
    port = data.get("port")
    token = data.get("token")
    nonce = data.get("nonce")
    csrf = data.get("csrf")
    expected = Path(sys.executable).resolve().with_name("Start.exe")
    recorded_executable = data.get("executable")
    if (
        pid <= 0 or not port or not token or not nonce or not csrf
        or not recorded_executable
        or str(Path(recorded_executable).resolve()).casefold() != str(expected).casefold()
    ):
        print("No valid owned process found.")
        return 1
    try:
        _post_shutdown(port, token, nonce, csrf)
        for _ in range(30):
            if not lock.exists():
                print("Hermes Session Hub Web stopped.")
                return 0
            time.sleep(0.2)
        print("Shutdown requested; process is still closing.")
        return 0
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        pass
    if _is_start_exe(pid, expected):
        subprocess.run(["taskkill", "/PID", str(pid), "/T"], check=False)
        print("Fallback stop sent to validated Start.exe process.")
        return 0
    print("Fallback refused: process image is not validated Start.exe.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
