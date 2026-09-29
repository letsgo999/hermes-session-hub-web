import json
import re
import time
import zipfile
import io
from pathlib import Path

from . import PRODUCT_NAME, VERSION


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:0\d{1,2}[-.\s]?)?\d{3,4}[-.\s]?\d{4}\b")
TOKEN_RE = re.compile(r"(?i)\b(token|secret|cookie|key)\s*[:=]\s*[A-Za-z0-9._\-]+")
WIN_PATH_RE = re.compile(r"[A-Za-z]:[\\/](?:[^\\/\s]+[\\/])*[^\\/\s]*")
UNIX_PATH_RE = re.compile(r"(?<!\w)/(?:home|Users|var|tmp)/[^\s]+")


def redact_text(text):
    value = str(text)
    value = EMAIL_RE.sub("[redacted-email]", value)
    value = PHONE_RE.sub("[redacted-phone]", value)
    value = TOKEN_RE.sub(lambda m: f"{m.group(1)}=[redacted-token]", value)
    value = WIN_PATH_RE.sub("[redacted-path]", value)
    value = UNIX_PATH_RE.sub("[redacted-path]", value)
    return value


def _safe(obj):
    if isinstance(obj, dict):
        return {k: _safe(v) for k, v in obj.items() if "path" not in k.lower()}
    if isinstance(obj, list):
        return [_safe(v) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def create_diagnostics_zip(output_dir, info):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / "hermes-session-hub-diagnostics-redacted.zip"
    payload = {
        "product": PRODUCT_NAME,
        "version": VERSION,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "info": _safe(info),
        "note": "No source database rows, message text, credentials, or local paths are included.",
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("diagnostics.json", json.dumps(payload, ensure_ascii=False, indent=2))
    return zip_path


def diagnostics_zip_bytes(info):
    payload = {
        "product": PRODUCT_NAME,
        "version": VERSION,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "info": _safe(info),
        "note": "No source database rows, message text, credentials, profile ids, or local paths are included.",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("diagnostics.json", json.dumps(payload, ensure_ascii=False, indent=2))
    return buf.getvalue()


def pilot_receipt(info):
    safe = _safe(info)
    return (
        f"{PRODUCT_NAME} {VERSION}\n"
        "Privacy-safe pilot receipt\n"
        f"profiles={safe.get('profileCount', 0)}\n"
        "storageRoot=[local-app-data]\n"
        "telemetry=none\n"
    )
