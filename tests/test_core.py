import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hshw-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def make_state_db(self, path, version=26, with_workspace=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path)
        cols = ", workspace_path text" if with_workspace else ""
        con.executescript(
            f"""
            create table schema_version(version integer);
            insert into schema_version values ({version});
            create table sessions(
                id text primary key, title text, source text, chat_type text,
                thread_id text, started_at text, last_activity_at text,
                message_count integer{cols}
            );
            create table messages(
                id text primary key, session_id text, role text, content text,
                timestamp text, active integer
            );
            insert into sessions values (
                'sess_alpha', '테스트 세션', 'desktop', 'chat', 'thread_alpha',
                '2026-01-01T00:00:00Z', '2026-01-01T00:02:00Z', 1
                {", 'C:/Synthetic/ProjectA'" if with_workspace else ""}
            );
            insert into messages values (
                'msg_alpha', 'sess_alpha', 'user', '민감하지 않은 합성 메시지',
                '2026-01-01T00:01:00Z', 1
            );
            """
        )
        con.commit()
        con.close()

    def make_kanban_db(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path)
        con.executescript(
            """
            create table tasks(
                id text primary key, title text, body text, assignee text,
                status text, priority text, workspace_path text, result text,
                session_id text, project_id text
            );
            insert into tasks values (
                'task_alpha', '합성 작업', '본문 비공개', 'student',
                'todo', 'high', 'C:/Synthetic/ProjectA', '결과 비공개',
                'sess_alpha', 'kanban_proj'
            );
            """
        )
        con.commit()
        con.close()

    def test_source_db_read_only_and_immutable(self):
        from session_hub.sources import HermesSource

        db = self.tmp / "state.db"
        self.make_state_db(db)
        before = (hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns)
        source = HermesSource(db, profile_id="default")
        sessions = source.list_sessions()
        self.assertEqual(sessions[0]["id"], "sess_alpha")
        with self.assertRaises(sqlite3.DatabaseError):
            source.write_probe_for_tests()
        after = (hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns)
        self.assertEqual(before, after)
        self.assertFalse((self.tmp / "state.db-wal").exists())
        self.assertFalse((self.tmp / "state.db-shm").exists())
        self.assertFalse((self.tmp / "state.db-journal").exists())

    def test_wal_source_reads_committed_frames_without_creating_sidecars(self):
        from session_hub.sources import HermesSource

        db = self.tmp / "state.db"
        self.make_state_db(db)
        writer = sqlite3.connect(db)
        self.addCleanup(writer.close)
        self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "sess_wal", "WAL 세션", "desktop", "chat", "thread_wal",
                "2026-01-02T00:00:00Z", "2026-01-02T00:01:00Z", 0,
                "C:/Synthetic/ProjectWAL",
            ),
        )
        writer.commit()
        self.assertGreater((self.tmp / "state.db-wal").stat().st_size, 0)
        self.assertTrue((self.tmp / "state.db-shm").exists())
        before_names = {item.name for item in self.tmp.iterdir()}

        sessions = HermesSource(db, profile_id="default").list_sessions()

        self.assertIn("sess_wal", {row["id"] for row in sessions})
        self.assertEqual(before_names, {item.name for item in self.tmp.iterdir()})
        self.assertFalse((self.tmp / "state.db-journal").exists())

    def test_incomplete_wal_sidecars_fail_closed(self):
        from session_hub.sources import HermesSource, UnsafeSourceStateError

        db = self.tmp / "state.db"
        self.make_state_db(db)
        (self.tmp / "state.db-wal").write_bytes(b"incomplete")

        with self.assertRaisesRegex(UnsafeSourceStateError, "incomplete"):
            HermesSource(db, profile_id="default")
        self.assertFalse((self.tmp / "state.db-shm").exists())

    def test_profile_absence_kanban_absence_and_auto_detection(self):
        from session_hub.sources import detect_profiles, detect_kanban

        empty = self.tmp / "localapp"
        self.assertEqual(detect_profiles(empty), [])
        self.assertIsNone(detect_kanban(empty))
        self.make_state_db(empty / "hermes" / "state.db")
        self.make_state_db(empty / "hermes" / "profiles" / "student" / "state.db")
        profiles = detect_profiles(empty)
        self.assertEqual([p["id"] for p in profiles], ["default", "student"])

    def test_supported_and_unsupported_schema_fail_closed(self):
        from session_hub.sources import HermesSource, UnsupportedSchemaError

        ok = self.tmp / "ok.db"
        bad = self.tmp / "bad.db"
        self.make_state_db(ok, version=30)
        self.make_state_db(bad, version=31)
        self.assertEqual(HermesSource(ok, "ok").schema_version, 30)
        with self.assertRaises(UnsupportedSchemaError):
            HermesSource(bad, "bad")

    def test_registry_project_lifecycle_export_restore_backup(self):
        from session_hub.registry import Registry

        reg = Registry(self.tmp / "registry")
        project = reg.create_project({"name": "합성 프로젝트", "priority": "high"})
        reg.update_project(project["id"], {"status": "active", "pinned": True})
        reg.archive_project(project["id"])
        exported = reg.export_json()
        backup = reg.restore_json(exported)
        self.assertTrue(backup.exists())
        restored = reg.list_projects()[0]
        self.assertTrue(restored["archived"])
        self.assertEqual(restored["name"], "합성 프로젝트")
        with self.assertRaises(ValueError):
            reg.restore_json('{"schemaVersion": 999}')
        with self.assertRaises(ValueError):
            reg.create_project({"name": "x", "unknown": True})

    def test_redaction_diagnostic_zip_and_receipt_are_privacy_safe(self):
        from session_hub.diagnostics import create_diagnostics_zip, pilot_receipt, redact_text

        raw = "a.person@example.com 010-1234-5678 token=abc123 C:/Users/Alice/Secret /home/bob/x"
        redacted = redact_text(raw)
        self.assertNotIn("a.person@example.com", redacted)
        self.assertNotIn("010-1234-5678", redacted)
        self.assertNotIn("Alice", redacted)
        zip_path = create_diagnostics_zip(
            self.tmp / "diag", {"detectedProfiles": [{"id": "default", "path": str(self.tmp / "state.db")}]}
        )
        data = zip_path.read_bytes()
        self.assertNotIn(str(self.tmp).encode(), data)
        receipt = pilot_receipt({"profileCount": 1, "storageRoot": str(self.tmp)})
        self.assertNotIn(str(self.tmp), receipt)
        self.assertIn("Hermes Session Hub Web", receipt)

    def test_loopback_config_host_origin_csrf_auth_and_flow(self):
        from session_hub.server import HubServer

        localapp = self.tmp / "localapp"
        self.make_state_db(localapp / "hermes" / "state.db")
        srv = HubServer(localapp=localapp, registry_root=self.tmp / "reg", open_browser=False)
        thread = srv.start_in_thread()
        self.addCleanup(srv.stop)
        self.assertEqual(srv.host, "127.0.0.1")
        base = f"http://127.0.0.1:{srv.port}"

        with self.assertRaises(urllib.error.HTTPError) as unauth:
            urllib.request.urlopen(base + "/api/profiles", timeout=5)
        unauth.exception.close()

        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        opener.open(base + "/", timeout=5).read()
        req = urllib.request.Request(base + "/api/profiles", headers={"Host": f"127.0.0.1:{srv.port}"})
        profiles = json.loads(opener.open(req, timeout=5).read())
        self.assertEqual(profiles["profiles"][0]["id"], "default")
        self.assertNotIn("dbPath", profiles["profiles"][0])

        bad = urllib.request.Request(
            base + "/api/projects",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json", "Origin": "http://evil.invalid"},
        )
        with self.assertRaises(urllib.error.HTTPError) as forbidden:
            opener.open(bad, timeout=5)
        forbidden.exception.close()

        good = urllib.request.Request(
            base + "/api/projects",
            data=json.dumps({"name": "흐름 프로젝트"}).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Origin": base,
                "X-CSRF-Token": srv.csrf_token,
            },
        )
        created = json.loads(opener.open(good, timeout=5).read())
        self.assertEqual(created["project"]["name"], "흐름 프로젝트")
        self.assertFalse(thread is None)

    def test_single_instance_and_start_stop_ownership(self):
        from session_hub.lifecycle import InstanceLock, validate_stop_request

        lock1 = InstanceLock(self.tmp / "run")
        self.assertTrue(lock1.acquire(os.getpid(), token="auth", nonce="nonce", csrf="csrf"))
        lock2 = InstanceLock(self.tmp / "run")
        self.assertFalse(lock2.acquire(67890))
        self.assertTrue(validate_stop_request(lock1.lock_file, os.getpid(), "nonce"))
        self.assertFalse(validate_stop_request(lock1.lock_file, 67890))
        lock1.release()

    def test_pid_liveness_detects_another_running_process(self):
        from session_hub.lifecycle import _pid_alive

        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.assertTrue(_pid_alive(child.pid))
        finally:
            child.terminate()
            child.wait(timeout=10)
        self.assertFalse(_pid_alive(child.pid))

    def test_stale_lock_is_recovered_atomically(self):
        from session_hub.lifecycle import InstanceLock

        lock1 = InstanceLock(self.tmp / "run")
        self.assertTrue(lock1.acquire(987654321, token="old", nonce="old", csrf="old"))
        lock2 = InstanceLock(self.tmp / "run")
        self.assertTrue(lock2.acquire(os.getpid(), token="new", nonce="new", csrf="new"))
        data = json.loads(lock2.lock_file.read_text(encoding="utf-8"))
        self.assertEqual(data["token"], "new")
        lock2.release()

    def test_new_api_flow_candidates_filters_downloads_and_shutdown(self):
        from session_hub.server import HubServer

        localapp = self.tmp / "localapp"
        self.make_state_db(localapp / "hermes" / "state.db")
        self.make_kanban_db(localapp / "hermes" / "kanban.db")
        srv = HubServer(localapp=localapp, registry_root=self.tmp / "reg", open_browser=False)
        srv.start_in_thread()
        self.addCleanup(srv.stop)
        base = f"http://127.0.0.1:{srv.port}"
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        opener.open(base + "/", timeout=5).read()

        bootstrap = json.loads(opener.open(base + "/api/bootstrap", timeout=5).read())
        self.assertFalse(bootstrap["disclosureAccepted"])
        self.assertNotIn(str(localapp), json.dumps(bootstrap, ensure_ascii=False))

        headers = {"Content-Type": "application/json", "Origin": base, "X-CSRF-Token": srv.csrf_token}
        accept = urllib.request.Request(base + "/api/disclosure/accept", data=b"{}", method="POST", headers=headers)
        self.assertTrue(json.loads(opener.open(accept, timeout=5).read())["disclosureAccepted"])

        project_req = urllib.request.Request(
            base + "/api/projects",
            data=json.dumps({"name": "합성 프로젝트", "priority": "high", "pinned": True}).encode(),
            method="POST",
            headers=headers,
        )
        project = json.loads(opener.open(project_req, timeout=5).read())["project"]
        candidates = json.loads(opener.open(base + "/api/candidates", timeout=5).read())["candidates"]
        self.assertTrue(candidates)
        self.assertNotIn("C:/Synthetic", json.dumps(candidates, ensure_ascii=False))
        confirm = urllib.request.Request(
            base + "/api/candidates/confirm",
            data=json.dumps({"projectId": project["id"], "candidate": candidates[0]}).encode(),
            method="POST",
            headers=headers,
        )
        linked = json.loads(opener.open(confirm, timeout=5).read())["project"]
        self.assertEqual(len(linked["links"]), 1)

        sessions = json.loads(opener.open(base + "/api/sessions?profile=default&source=desktop&limit=5", timeout=5).read())["sessions"]
        self.assertEqual(sessions[0]["id"], "sess_alpha")
        self.assertNotIn("content", json.dumps(sessions, ensure_ascii=False))
        msgs = json.loads(opener.open(base + "/api/messages?profile=default&sessionId=sess_alpha", timeout=5).read())["messages"]
        self.assertEqual(msgs[0]["content"], "민감하지 않은 합성 메시지")

        kanban = json.loads(opener.open(base + "/api/kanban?status=todo", timeout=5).read())["tasks"]
        self.assertEqual(kanban[0]["id"], "task_alpha")
        self.assertNotIn("본문 비공개", json.dumps(kanban, ensure_ascii=False))
        self.assertNotIn("결과 비공개", json.dumps(kanban, ensure_ascii=False))

        opened = json.loads(opener.open(base + "/api/open-url?profile=default&sessionId=sess_alpha", timeout=5).read())
        self.assertEqual(opened["sessionId"], "sess_alpha")
        self.assertIn('hermes --profile "default" session open "sess_alpha"', opened["command"])

        exported = opener.open(base + "/api/registry/export", timeout=5)
        self.assertIn("attachment", exported.headers["Content-Disposition"])
        self.assertIn("합성 프로젝트", exported.read().decode("utf-8"))

        diag_req = urllib.request.Request(base + "/api/diagnostics/zip", data=b"{}", method="POST", headers=headers)
        zip_bytes = opener.open(diag_req, timeout=5).read()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            self.assertEqual(zf.namelist(), ["diagnostics.json"])
            diag_text = zf.read("diagnostics.json").decode("utf-8")
            self.assertNotIn(str(localapp), diag_text)
            self.assertNotIn("default", diag_text)

        shutdown = urllib.request.Request(
            base + "/api/shutdown",
            data=json.dumps({"nonce": srv.shutdown_nonce}).encode(),
            method="POST",
            headers=headers,
        )
        self.assertTrue(json.loads(opener.open(shutdown, timeout=5).read())["stopping"])

    def test_security_rejects_bad_content_method_override_and_unknown_method(self):
        from session_hub.server import HubServer

        srv = HubServer(localapp=self.tmp / "localapp", registry_root=self.tmp / "reg", open_browser=False)
        srv.start_in_thread()
        self.addCleanup(srv.stop)
        base = f"http://127.0.0.1:{srv.port}"
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        opener.open(base + "/", timeout=5).read()

        bad_type = urllib.request.Request(
            base + "/api/projects",
            data=b"name=x",
            method="POST",
            headers={"Content-Type": "text/plain", "Origin": base, "X-CSRF-Token": srv.csrf_token},
        )
        with self.assertRaises(urllib.error.HTTPError) as type_err:
            opener.open(bad_type, timeout=5)
        self.assertEqual(type_err.exception.code, 400)
        type_err.exception.close()

        override = urllib.request.Request(
            base + "/api/projects",
            data=b"{}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Origin": base,
                "X-CSRF-Token": srv.csrf_token,
                "X-HTTP-Method-Override": "DELETE",
            },
        )
        with self.assertRaises(urllib.error.HTTPError) as override_err:
            opener.open(override, timeout=5)
        self.assertEqual(override_err.exception.code, 400)
        override_err.exception.close()

        put = urllib.request.Request(base + "/api/projects", data=b"{}", method="PUT", headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as method_err:
            opener.open(put, timeout=5)
        self.assertEqual(method_err.exception.code, 405)
        self.assertEqual(method_err.exception.headers["X-Frame-Options"], "DENY")
        method_err.exception.close()

    def test_static_ui_markers_and_no_external_urls(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "src" / "session_hub" / "static" / "index.html").read_text(encoding="utf-8")
        js = (root / "src" / "session_hub" / "static" / "app.js").read_text(encoding="utf-8")
        css = (root / "src" / "session_hub" / "static" / "style.css").read_text(encoding="utf-8")
        joined = html + js + css
        for marker in ["로컬 전용", "프로젝트", "오늘의 실행목록", "최근 세션", "진단", "Kanban", "Open in Hermes"]:
            self.assertIn(marker, joined)
        self.assertNotRegex(joined, r"https?://")
        self.assertIn("textContent", js)
        self.assertNotIn("innerHTML", js)


if __name__ == "__main__":
    unittest.main()
