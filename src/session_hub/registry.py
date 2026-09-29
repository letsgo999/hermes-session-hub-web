import json
import os
import shutil
import tempfile
import time
import uuid
import re
from pathlib import Path


PROJECT_FIELDS = {"name", "status", "priority", "dueDate", "ownerProfile", "nextAction", "pinned", "archived", "links"}
CREATE_FIELDS = PROJECT_FIELDS - {"archived", "links"}
UPDATE_FIELDS = PROJECT_FIELDS
STATUS_VALUES = {"active", "waiting", "done", "archived"}
PRIORITY_VALUES = {"low", "normal", "high", "urgent"}
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


class Registry:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "registry.json"
        if not self.path.exists():
            self._write({"schemaVersion": 1, "disclosureAccepted": False, "projects": []})

    def _read(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._validate(data)
        return data

    def _write(self, data):
        self._validate(data)
        fd, tmp = tempfile.mkstemp(prefix="registry-", suffix=".json", dir=self.root)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def _validate(self, data):
        if not isinstance(data, dict) or data.get("schemaVersion") != 1:
            raise ValueError("Unsupported registry schema")
        if "disclosureAccepted" not in data:
            data["disclosureAccepted"] = False
        if not isinstance(data.get("disclosureAccepted"), bool):
            raise ValueError("Invalid disclosureAccepted")
        if not isinstance(data.get("projects"), list):
            raise ValueError("Invalid projects")
        for project in data["projects"]:
            if not isinstance(project, dict) or set(project) - (PROJECT_FIELDS | {"id", "createdAt", "updatedAt"}):
                raise ValueError("Invalid project")
            self._validate_project(project, partial=False)

    def _require_known(self, attrs, allowed):
        unknown = set(attrs) - allowed
        if unknown:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")

    def _validate_id(self, value, field="id"):
        if not isinstance(value, str) or not ID_RE.fullmatch(value):
            raise ValueError(f"Invalid {field}")
        return value

    def _validate_project(self, project, partial):
        if not partial:
            self._validate_id(project.get("id", ""), "project id")
        if "name" in project:
            if not isinstance(project["name"], str) or not project["name"].strip() or len(project["name"]) > 120:
                raise ValueError("Project name is required")
        elif not partial:
            raise ValueError("Project name is required")
        if "status" in project and project["status"] not in STATUS_VALUES:
            raise ValueError("Invalid status")
        if "priority" in project and project["priority"] not in PRIORITY_VALUES:
            raise ValueError("Invalid priority")
        for key in ("dueDate", "ownerProfile", "nextAction"):
            if key in project and project[key] is not None:
                if not isinstance(project[key], str) or len(project[key]) > 200:
                    raise ValueError(f"Invalid {key}")
        for key in ("pinned", "archived"):
            if key in project and not isinstance(project[key], bool):
                raise ValueError(f"Invalid {key}")
        if "links" in project:
            if not isinstance(project["links"], list) or len(project["links"]) > 100:
                raise ValueError("Invalid links")
            for link in project["links"]:
                if not isinstance(link, dict) or set(link) - {"type", "profile", "sessionId", "projectId", "workspaceName"}:
                    raise ValueError("Invalid link")
                if link.get("type") not in {"session", "kanban"}:
                    raise ValueError("Invalid link type")
                for key in ("profile", "sessionId", "projectId"):
                    if key in link and link[key] is not None:
                        self._validate_id(link[key], key)
                if "workspaceName" in link and (not isinstance(link["workspaceName"], str) or len(link["workspaceName"]) > 120):
                    raise ValueError("Invalid workspaceName")

    def list_projects(self):
        return self._read()["projects"]

    def disclosure_accepted(self):
        return self._read().get("disclosureAccepted", False)

    def accept_disclosure(self):
        data = self._read()
        data["disclosureAccepted"] = True
        self._write(data)
        return True

    def create_project(self, attrs):
        self._require_known(attrs, CREATE_FIELDS)
        self._validate_project(attrs, partial=True)
        data = self._read()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        project = {
            "id": f"proj_{uuid.uuid4().hex[:12]}",
            "name": attrs["name"].strip(),
            "links": [],
            "status": attrs.get("status", "active"),
            "priority": attrs.get("priority", "normal"),
            "dueDate": attrs.get("dueDate"),
            "ownerProfile": attrs.get("ownerProfile"),
            "nextAction": attrs.get("nextAction", ""),
            "pinned": bool(attrs.get("pinned", False)),
            "archived": False,
            "createdAt": now,
            "updatedAt": now,
        }
        data["projects"].append(project)
        self._write(data)
        return project

    def update_project(self, project_id, attrs):
        self._validate_id(project_id, "project id")
        self._require_known(attrs, UPDATE_FIELDS)
        self._validate_project(attrs, partial=True)
        data = self._read()
        for project in data["projects"]:
            if project["id"] == project_id:
                for key, value in attrs.items():
                    if key == "name" and isinstance(value, str):
                        value = value.strip()
                    if key == "archived" and value:
                        project["status"] = "archived"
                    project[key] = value
                project["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                self._write(data)
                return project
        raise KeyError(project_id)

    def archive_project(self, project_id):
        return self.update_project(project_id, {"archived": True})

    def export_json(self):
        return json.dumps(self._read(), ensure_ascii=False, indent=2, sort_keys=True)

    def restore_json(self, raw):
        data = json.loads(raw) if isinstance(raw, str) else raw
        self._validate(data)
        backup = self.root / f"registry.backup.{time.time_ns()}.{uuid.uuid4().hex[:8]}.json"
        shutil.copy2(self.path, backup)
        self._write(data)
        return backup

    def confirm_candidate(self, project_id, candidate):
        self._validate_id(project_id, "project id")
        if not isinstance(candidate, dict):
            raise ValueError("Invalid candidate")
        link = {
            "type": candidate.get("type"),
            "profile": candidate.get("profile"),
            "sessionId": candidate.get("sessionId"),
            "projectId": candidate.get("projectId"),
            "workspaceName": candidate.get("workspaceName"),
        }
        link = {k: v for k, v in link.items() if v is not None}
        self._validate_project({"links": [link]}, partial=True)
        data = self._read()
        for project in data["projects"]:
            if project["id"] == project_id:
                if link not in project["links"]:
                    project["links"].append(link)
                project["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                self._write(data)
                return project
        raise KeyError(project_id)
