import json
import mimetypes
import os
import re
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import PRODUCT_NAME, SUPPORTED_SCHEMA_MAX, SUPPORTED_SCHEMA_MIN, VERSION
from .diagnostics import diagnostics_zip_bytes, pilot_receipt
from .lifecycle import InstanceLock, free_loopback_port
from .registry import Registry
from .skills import preview_skill, search_skills
from .sources import HermesSource, KanbanSource, detect_kanban, detect_profiles


STATIC_ROOT = Path(__file__).resolve().parent / "static"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
SAFE_ATTACHMENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
MAX_BODY = 256 * 1024


def _safe_profiles(profiles):
    safe = []
    for profile in profiles:
        item = {k: v for k, v in profile.items() if k not in {"dbPath"}}
        safe.append(item)
    return safe


def _safe_id(value, name="id"):
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _attachment(name):
    if not SAFE_ATTACHMENT_RE.fullmatch(name):
        raise ValueError("invalid filename")
    return f'attachment; filename="{name}"'


def _win_quote(value):
    _safe_id(value)
    return '"' + value.replace('"', '\\"') + '"'


class HubServer:
    def __init__(self, localapp=None, registry_root=None, host="127.0.0.1", port=0, open_browser=True):
        if host != "127.0.0.1":
            raise ValueError("Server must bind only 127.0.0.1")
        self.host = host
        self.port = port or free_loopback_port()
        self.localapp = Path(localapp or os.environ.get("LOCALAPPDATA", Path.home()))
        self.registry_root = Path(registry_root or self.localapp / "HermesX" / "SessionHubStudent")
        self.registry = Registry(self.registry_root)
        self.auth_token = secrets.token_urlsafe(24)
        self.csrf_token = secrets.token_urlsafe(24)
        self.shutdown_nonce = secrets.token_urlsafe(24)
        self.open_browser = open_browser
        self.httpd = None
        self.thread = None

    def start_in_thread(self):
        handler = self._handler()
        self.httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="session-hub-server", daemon=True)
        self.thread.start()
        if self.open_browser:
            webbrowser.open(f"http://127.0.0.1:{self.port}/")
        return self.thread

    def serve_forever(self):
        self.start_in_thread()
        self.thread.join()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

    def _profiles(self):
        return detect_profiles(self.localapp)

    def _profile_source(self, profile_id):
        _safe_id(profile_id, "profile")
        for profile in self._profiles():
            if profile["id"] == profile_id and not profile.get("unsupported"):
                return HermesSource(profile["dbPath"], profile_id)
        raise KeyError(profile_id)

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "HermesSessionHubWeb/0.1"

            def log_message(self, fmt, *args):
                return

            def _origin_set(self):
                return {f"http://127.0.0.1:{outer.port}", f"http://localhost:{outer.port}"}

            def _host_ok(self):
                hosts = self.headers.get_all("Host") or []
                return len(hosts) == 1 and hosts[0] in {f"127.0.0.1:{outer.port}", f"localhost:{outer.port}"}

            def _cookie_ok(self):
                cookie = SimpleCookie()
                try:
                    cookie.load(self.headers.get("Cookie", ""))
                except Exception:
                    return False
                morsel = cookie.get("hshw_auth")
                return bool(morsel and morsel.value == outer.auth_token)

            def _state_headers_ok(self):
                origin = self.headers.get("Origin")
                return origin in self._origin_set() and self.headers.get("X-CSRF-Token") == outer.csrf_token

            def _basic_request_ok(self):
                if self.headers.get("X-HTTP-Method-Override"):
                    self._json({"error": "method_override_rejected"}, HTTPStatus.BAD_REQUEST)
                    return False
                if not self._host_ok():
                    self._json({"error": "bad_host"}, HTTPStatus.FORBIDDEN)
                    return False
                return True

            def _send(self, status=200, body=b"", content_type="application/json", cookie=False, download=None):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'")
                if download:
                    self.send_header("Content-Disposition", _attachment(download))
                if cookie:
                    self.send_header("Set-Cookie", f"hshw_auth={outer.auth_token}; HttpOnly; SameSite=Strict; Path=/")
                    self.send_header("X-CSRF-Token", outer.csrf_token)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, payload, status=200, cookie=False):
                self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json", cookie)

            def _read_json(self):
                ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                if ctype != "application/json":
                    raise ValueError("invalid_content_type")
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                except ValueError:
                    raise ValueError("invalid_length")
                if length < 0 or length > MAX_BODY:
                    raise ValueError("body_too_large")
                raw = self.rfile.read(length)
                try:
                    data = json.loads(raw.decode("utf-8") or "{}")
                except Exception:
                    raise ValueError("malformed_json")
                if not isinstance(data, dict):
                    raise ValueError("json_object_required")
                return data

            def _deny_api(self, state_change=False):
                if not self._basic_request_ok():
                    return True
                if not self._cookie_ok():
                    self._json({"error": "auth_required"}, HTTPStatus.UNAUTHORIZED)
                    return True
                if state_change and not self._state_headers_ok():
                    self._json({"error": "csrf_failed"}, HTTPStatus.FORBIDDEN)
                    return True
                return False

            def do_HEAD(self):
                return self._json({"error": "method_not_allowed"}, HTTPStatus.METHOD_NOT_ALLOWED)

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path
                if not self._basic_request_ok():
                    return
                if path == "/":
                    return self._static("index.html", cookie=True)
                if path.startswith("/static/"):
                    return self._static(path.removeprefix("/static/"))
                if self._deny_api(False):
                    return
                qs = parse_qs(parsed.query, keep_blank_values=False)
                try:
                    return self._route_get(path, qs)
                except (ValueError, KeyError) as exc:
                    return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

            def do_POST(self):
                parsed = urlparse(self.path)
                path = parsed.path
                if self._deny_api(True):
                    return
                try:
                    payload = self._read_json()
                    return self._route_post(path, payload)
                except json.JSONDecodeError:
                    return self._json({"error": "malformed_json"}, HTTPStatus.BAD_REQUEST)
                except (ValueError, KeyError) as exc:
                    return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

            def do_PATCH(self):
                parsed = urlparse(self.path)
                path = parsed.path
                if self._deny_api(True):
                    return
                try:
                    payload = self._read_json()
                    if path.startswith("/api/projects/"):
                        project_id = path.rsplit("/", 1)[-1]
                        return self._json({"project": outer.registry.update_project(project_id, payload)})
                    return self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                except (ValueError, KeyError) as exc:
                    return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

            def do_DELETE(self):
                if not self._basic_request_ok():
                    return
                return self._json({"error": "method_not_allowed"}, HTTPStatus.METHOD_NOT_ALLOWED)

            def do_PUT(self):
                if not self._basic_request_ok():
                    return
                return self._json({"error": "method_not_allowed"}, HTTPStatus.METHOD_NOT_ALLOWED)

            def do_OPTIONS(self):
                if not self._basic_request_ok():
                    return
                return self._json({"error": "method_not_allowed"}, HTTPStatus.METHOD_NOT_ALLOWED)

            def _route_get(self, path, qs):
                if path == "/api/bootstrap":
                    profiles = outer._profiles()
                    return self._json({
                        "product": PRODUCT_NAME,
                        "version": VERSION,
                        "csrfToken": outer.csrf_token,
                        "disclosureAccepted": outer.registry.disclosure_accepted(),
                        "dataLocations": {
                            "registry": "LOCALAPPDATA/HermesX/SessionHubStudent",
                            "hermes": "LOCALAPPDATA/hermes",
                        },
                        "compatibility": {"schemaMin": SUPPORTED_SCHEMA_MIN, "schemaMax": SUPPORTED_SCHEMA_MAX},
                        "profiles": _safe_profiles(profiles),
                        "kanban": bool(detect_kanban(outer.localapp)),
                    })
                if path == "/api/profiles":
                    return self._json({"profiles": _safe_profiles(outer._profiles())})
                if path == "/api/projects":
                    return self._json({"projects": outer.registry.list_projects()})
                if path == "/api/sessions":
                    return self._json({"sessions": self._sessions(qs)})
                if path == "/api/messages":
                    return self._json({"messages": self._messages(qs)})
                if path == "/api/candidates":
                    return self._json({"candidates": self._candidates()})
                if path == "/api/kanban":
                    return self._json({"tasks": self._kanban(qs)})
                if path == "/api/registry/export":
                    body = outer.registry.export_json().encode("utf-8")
                    return self._send(200, body, "application/json", download="registry-export.json")
                if path == "/api/diagnostics/summary":
                    return self._json({
                        "product": PRODUCT_NAME,
                        "version": VERSION,
                        "compatibility": f"Hermes schema {SUPPORTED_SCHEMA_MIN}-{SUPPORTED_SCHEMA_MAX}",
                        "dataLocations": ["LOCALAPPDATA/HermesX/SessionHubStudent", "LOCALAPPDATA/hermes"],
                        "kanban": "감지됨" if detect_kanban(outer.localapp) else "없음",
                    })
                if path == "/api/open-url":
                    sid = qs.get("sessionId", [""])[0]
                    profile = qs.get("profile", [""])[0]
                    _safe_id(sid, "sessionId")
                    _safe_id(profile, "profile")
                    src = outer._profile_source(profile)
                    if not src.has_session(sid):
                        raise KeyError("session_not_found")
                    url = f"hermes://session/open?profile={quote(profile)}&sessionId={quote(sid)}"
                    command = f"hermes --profile {_win_quote(profile)} session open {_win_quote(sid)}"
                    return self._json({"url": url, "sessionId": sid, "profile": profile, "command": command})
                if path == "/api/skills":
                    return self._json(search_skills(outer._profiles(), qs.get("q", [""])[0][:100], qs.get("profile", [""])[0] or None))
                if path.startswith("/api/skills/"):
                    skill_id = path.rsplit("/", 1)[-1]
                    try:
                        return self._json(preview_skill(outer._profiles(), skill_id))
                    except FileNotFoundError:
                        return self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

            def _route_post(self, path, payload):
                if path == "/api/disclosure/accept":
                    outer.registry.accept_disclosure()
                    return self._json({"disclosureAccepted": True})
                if path == "/api/projects":
                    return self._json({"project": outer.registry.create_project(payload)}, HTTPStatus.CREATED)
                if path == "/api/candidates/confirm":
                    project_id = payload.get("projectId")
                    candidate = payload.get("candidate")
                    if candidate not in self._candidates():
                        raise ValueError("candidate_not_available")
                    return self._json({"project": outer.registry.confirm_candidate(project_id, candidate)})
                if path == "/api/registry/restore":
                    if set(payload) != {"registryJson"}:
                        raise ValueError("Unknown fields")
                    raw = payload["registryJson"]
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    backup = outer.registry.restore_json(data)
                    return self._json({"backup": backup.name, "projects": outer.registry.list_projects()})
                if path == "/api/diagnostics/zip":
                    body = diagnostics_zip_bytes({"profileCount": len(outer._profiles()), "kanban": bool(detect_kanban(outer.localapp))})
                    return self._send(200, body, "application/zip", download="diagnostics-redacted.zip")
                if path == "/api/diagnostics/receipt":
                    body = pilot_receipt({"profileCount": len(outer._profiles())}).encode("utf-8")
                    return self._send(200, body, "text/plain; charset=utf-8", download="pilot-receipt.txt")
                if path == "/api/shutdown":
                    if payload.get("nonce") != outer.shutdown_nonce:
                        return self._json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                    self._json({"stopping": True})
                    threading.Thread(target=outer.stop, daemon=True).start()
                    return
                return self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

            def _sessions(self, qs):
                query = qs.get("q", [""])[0][:100]
                profile_filter = qs.get("profile", [""])[0]
                source = qs.get("source", [""])[0][:40] or None
                date_from = qs.get("from", [""])[0][:40] or None
                date_to = qs.get("to", [""])[0][:40] or None
                limit = int(qs.get("limit", ["100"])[0] or "100")
                content = qs.get("content", ["false"])[0].lower() == "true"
                rows = []
                for profile in outer._profiles():
                    if profile.get("unsupported"):
                        continue
                    if profile_filter and profile["id"] != _safe_id(profile_filter, "profile"):
                        continue
                    rows.extend(HermesSource(profile["dbPath"], profile["id"]).list_sessions(
                        query=query, source=source, date_from=date_from, date_to=date_to, limit=limit, search_content=content
                    ))
                return rows[:max(1, min(limit, 200))]

            def _messages(self, qs):
                profile_id = qs.get("profile", [""])[0]
                session_id = qs.get("sessionId", [""])[0]
                limit = int(qs.get("limit", ["50"])[0] or "50")
                src = outer._profile_source(profile_id)
                if not src.has_session(_safe_id(session_id, "sessionId")):
                    raise KeyError("session_not_found")
                return src.read_messages(session_id, limit=limit)

            def _candidates(self):
                candidates = []
                seen = set()
                for profile in outer._profiles():
                    if profile.get("unsupported"):
                        continue
                    for session in HermesSource(profile["dbPath"], profile["id"]).list_sessions(limit=100):
                        workspace = session.get("workspaceName")
                        if not workspace:
                            continue
                        key = ("session", profile["id"], session["id"])
                        if key not in seen:
                            seen.add(key)
                            candidates.append({
                                "type": "session",
                                "profile": profile["id"],
                                "sessionId": session["id"],
                                "workspaceName": workspace,
                                "title": session.get("title") or session["id"],
                                "confirmed": False,
                            })
                kanban = detect_kanban(outer.localapp)
                if kanban:
                    for task in KanbanSource(kanban["dbPath"]).list_tasks(limit=100):
                        if task.get("project_id") or task.get("workspaceName"):
                            candidates.append({
                                "type": "kanban",
                                "projectId": task.get("project_id"),
                                "workspaceName": task.get("workspaceName"),
                                "title": task.get("title") or task.get("id"),
                                "confirmed": False,
                            })
                return candidates[:100]

            def _kanban(self, qs):
                detected = detect_kanban(outer.localapp)
                if not detected:
                    return []
                status = qs.get("status", [""])[0][:40]
                assignee = qs.get("assignee", [""])[0][:80]
                tasks = KanbanSource(detected["dbPath"]).list_tasks(limit=int(qs.get("limit", ["100"])[0] or "100"))
                if status:
                    tasks = [t for t in tasks if t.get("status") == status]
                if assignee:
                    tasks = [t for t in tasks if t.get("assignee") == assignee]
                return tasks

            def _static(self, rel, cookie=False):
                target = (STATIC_ROOT / rel).resolve()
                if STATIC_ROOT not in target.parents and target != STATIC_ROOT:
                    return self._json({"error": "bad_path"}, HTTPStatus.FORBIDDEN)
                if not target.exists() or target.is_dir():
                    return self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                self._send(200, target.read_bytes(), content_type, cookie)

        return Handler


def main():
    localapp = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    run_dir = localapp / "HermesX" / "SessionHubStudent" / "run"
    server = HubServer(localapp=localapp)
    lock = InstanceLock(run_dir)
    if not lock.acquire(os.getpid(), server.port, server.auth_token, server.shutdown_nonce, server.csrf_token):
        print("Hermes Session Hub Web is already running.")
        return 2
    try:
        server.serve_forever()
    finally:
        server.stop()
        lock.release()


if __name__ == "__main__":
    main()
