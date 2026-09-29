import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class SkillsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hshw-skills-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def make_state_db(self, path, version=26):
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path)
        con.executescript(
            f"""
            create table schema_version(version integer);
            insert into schema_version values ({version});
            create table sessions(
                id text primary key, title text, source text, chat_type text,
                thread_id text, started_at text, last_activity_at text,
                message_count integer, workspace_path text
            );
            create table messages(
                id text primary key, session_id text, role text, content text,
                timestamp text, active integer
            );
            """
        )
        con.commit()
        con.close()

    def write_skill(self, root, rel, body):
        target = root / rel / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8", newline="\n")
        return target

    def detected_profiles(self, localapp):
        from session_hub.sources import detect_profiles

        return detect_profiles(localapp)

    def test_active_profile_skill_detection_and_search_fields(self):
        from session_hub.skills import search_skills

        localapp = self.tmp / "localapp"
        self.make_state_db(localapp / "hermes" / "state.db")
        self.make_state_db(localapp / "hermes" / "profiles" / "student" / "state.db")
        self.write_skill(
            localapp / "hermes" / "skills",
            "writer",
            "---\nname: Draft Helper\ndescription: Korean document drafting\ntags: [writing, docs]\n---\nBody keyword alpha.",
        )
        self.write_skill(
            localapp / "hermes" / "profiles" / "student" / "skills",
            "reviewer",
            "---\nname: Review Helper\ndescription: Finds issues\ntags:\n  - qa\n---\nBody keyword beta.",
        )

        profiles = self.detected_profiles(localapp)
        by_name = search_skills(profiles, "draft")
        by_description = search_skills(profiles, "document")
        by_tag = search_skills(profiles, "qa")
        by_body = search_skills(profiles, "beta")

        self.assertEqual(by_name["results"][0]["profile"], "default")
        self.assertEqual(by_description["results"][0]["name"], "Draft Helper")
        self.assertEqual(by_tag["results"][0]["profile"], "student")
        self.assertEqual(by_body["results"][0]["name"], "Review Helper")

    def test_backup_archive_staging_hidden_cache_temp_vendor_excluded_by_default(self):
        from session_hub.skills import search_skills

        localapp = self.tmp / "localapp"
        self.make_state_db(localapp / "hermes" / "state.db")
        root = localapp / "hermes" / "skills"
        self.write_skill(root, "active", "---\nname: Active Skill\n---\nneedle")
        for rel in ["backup/old", "archive/old", "staging/new", ".hidden/x", "__pycache__/x", "node_modules/x", "vendor/x", "tmp/x"]:
            self.write_skill(root, rel, f"---\nname: Excluded {rel}\n---\nneedle")

        results = search_skills(self.detected_profiles(localapp), "needle")["results"]

        self.assertEqual([r["name"] for r in results], ["Active Skill"])

    def test_absence_is_normal(self):
        from session_hub.skills import search_skills

        localapp = self.tmp / "localapp"
        self.make_state_db(localapp / "hermes" / "state.db")

        payload = search_skills(self.detected_profiles(localapp), "anything")

        self.assertEqual(payload["results"], [])

    def test_preview_traversal_rejection_read_only_and_no_absolute_paths(self):
        from session_hub.skills import preview_skill, search_skills

        localapp = self.tmp / "localapp"
        self.make_state_db(localapp / "hermes" / "state.db")
        skill = self.write_skill(
            localapp / "hermes" / "skills",
            "safe",
            "---\nname: Safe Skill\ndescription: Preview target\ntags: safe\n---\nPreview body gamma.",
        )
        before = (hashlib.sha256(skill.read_bytes()).hexdigest(), skill.stat().st_mtime_ns)
        profiles = self.detected_profiles(localapp)
        found = search_skills(profiles, "gamma")["results"][0]
        preview = preview_skill(profiles, found["id"])
        after = (hashlib.sha256(skill.read_bytes()).hexdigest(), skill.stat().st_mtime_ns)

        self.assertEqual(before, after)
        self.assertIn("Preview body gamma", preview["preview"])
        self.assertNotIn(str(localapp), json.dumps(found, ensure_ascii=False))
        self.assertNotIn(str(localapp), json.dumps(preview, ensure_ascii=False))
        with self.assertRaises(ValueError):
            preview_skill(profiles, "../safe")

    def test_server_skills_endpoints_no_absolute_paths_and_preview(self):
        from session_hub.server import HubServer

        localapp = self.tmp / "localapp"
        self.make_state_db(localapp / "hermes" / "state.db")
        self.write_skill(localapp / "hermes" / "skills", "safe", "---\nname: Safe Skill\n---\nserver needle")
        srv = HubServer(localapp=localapp, registry_root=self.tmp / "reg", open_browser=False)
        srv.start_in_thread()
        self.addCleanup(srv.stop)
        base = f"http://127.0.0.1:{srv.port}"
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        opener.open(base + "/", timeout=5).read()

        data = json.loads(opener.open(base + "/api/skills?q=server", timeout=5).read())
        item = data["results"][0]
        self.assertEqual(item["name"], "Safe Skill")
        self.assertNotIn(str(localapp), json.dumps(data, ensure_ascii=False))
        preview = json.loads(opener.open(base + f"/api/skills/{item['id']}", timeout=5).read())
        self.assertIn("server needle", preview["preview"])
        with self.assertRaises(urllib.error.HTTPError) as forbidden:
            opener.open(base + "/api/skills/..%2Fsecret", timeout=5)
        forbidden.exception.close()

    def test_static_korean_skills_ui_markers(self):
        html = (ROOT / "src" / "session_hub" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "src" / "session_hub" / "static" / "app.js").read_text(encoding="utf-8")
        joined = html + js

        for marker in ["스킬", "읽기 전용 Skills", "스킬 검색", "미리보기", "/api/skills"]:
            self.assertIn(marker, joined)
        self.assertIn("textContent", js)
        self.assertNotIn("innerHTML", js)


if __name__ == "__main__":
    unittest.main()
