import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from . import SUPPORTED_SCHEMA_MAX, SUPPORTED_SCHEMA_MIN


class UnsupportedSchemaError(RuntimeError):
    pass


class UnsafeSourceStateError(RuntimeError):
    pass


def _dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _readonly_connection(path: Path):
    # A sidecar-free WAL-mode snapshot must use immutable=1. Plain mode=ro can
    # create -wal/-shm files even though SQL writes are disabled. When a live
    # source already has both WAL sidecars, keep mode=ro so committed WAL frames
    # remain visible. Refuse incomplete/hot sidecar states instead of silently
    # returning stale or inconsistent data.
    wal = Path(f"{path}-wal")
    shm = Path(f"{path}-shm")
    journal = Path(f"{path}-journal")
    if journal.exists():
        raise UnsafeSourceStateError("Source has a rollback journal")
    if wal.exists() != shm.exists():
        raise UnsafeSourceStateError("Source WAL sidecars are incomplete")
    immutable = not wal.exists()
    params = "mode=ro&immutable=1" if immutable else "mode=ro"
    uri = f"file:{quote(str(path.resolve()).replace(os.sep, '/'), safe=':/')}?{params}"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = _dict_factory
    con.execute("PRAGMA query_only=ON")

    def authorizer(action, arg1, arg2, dbname, source):
        denied = {
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_ALTER_TABLE,
            sqlite3.SQLITE_DROP_TABLE,
            sqlite3.SQLITE_DROP_INDEX,
            sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_DROP_VIEW,
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_CREATE_TRIGGER,
            sqlite3.SQLITE_CREATE_VIEW,
            sqlite3.SQLITE_ATTACH,
            sqlite3.SQLITE_DETACH,
        }
        if action in denied:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA and str(arg1).lower() not in {"query_only", "table_info"}:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    con.set_authorizer(authorizer)
    return con


def _columns(con, table):
    return {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}


def _basename(value):
    if not value:
        return ""
    return Path(str(value)).name[:120]


class HermesSource:
    def __init__(self, path, profile_id):
        self.path = Path(path)
        self.profile_id = profile_id
        self.schema_version = self._read_schema_version()
        if not (SUPPORTED_SCHEMA_MIN <= self.schema_version <= SUPPORTED_SCHEMA_MAX):
            raise UnsupportedSchemaError(f"Unsupported Hermes schema {self.schema_version}")

    def _connect(self):
        return _readonly_connection(self.path)

    def _read_schema_version(self):
        with closing(self._connect()) as con:
            row = con.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
        if not row:
            raise UnsupportedSchemaError("Missing schema_version")
        return int(row["version"])

    def _required_columns(self, con):
        sessions = _columns(con, "sessions")
        messages = _columns(con, "messages")
        required_sessions = {"id", "title", "source", "chat_type", "thread_id", "started_at", "last_activity_at", "message_count"}
        required_messages = {"id", "session_id", "role", "content", "timestamp"}
        if not required_sessions.issubset(sessions) or not required_messages.issubset(messages):
            raise UnsupportedSchemaError("Missing required columns")

    def fingerprint(self):
        data = self.path.read_bytes()
        return {
            "sha256": hashlib.sha256(data).hexdigest(),
            "mtimeNs": self.path.stat().st_mtime_ns,
            "size": self.path.stat().st_size,
        }

    def list_sessions(self, query=None, limit=100, profile=None, source=None, date_from=None, date_to=None, search_content=False):
        limit = max(1, min(int(limit or 100), 200))
        with closing(self._connect()) as con:
            self._required_columns(con)
            cols = _columns(con, "sessions")
            select = [
                "id", "title", "source", "chat_type", "thread_id",
                "started_at", "last_activity_at", "message_count",
            ]
            if "workspace_path" in cols:
                select.append("workspace_path")
            sql = f"SELECT {', '.join(select)} FROM sessions"
            params = []
            where = []
            if query:
                where.append("(title LIKE ? OR id LIKE ?)")
                params.extend([f"%{query}%", f"%{query}%"])
                if search_content:
                    where[-1] = where[-1][:-1] + " OR id IN (SELECT session_id FROM messages WHERE content LIKE ?))"
                    params.append(f"%{query}%")
            if source:
                where.append("source=?")
                params.append(source)
            if date_from:
                where.append("COALESCE(last_activity_at, started_at) >= ?")
                params.append(date_from)
            if date_to:
                where.append("COALESCE(last_activity_at, started_at) <= ?")
                params.append(date_to)
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT ?"
            params.append(limit)
            rows = con.execute(sql, params).fetchall()
        for row in rows:
            row["profile_id"] = self.profile_id
            if "workspace_path" in row:
                row["workspaceName"] = _basename(row.pop("workspace_path"))
        return rows

    def read_messages(self, session_id, limit=50):
        limit = max(1, min(int(limit or 50), 200))
        with closing(self._connect()) as con:
            self._required_columns(con)
            return con.execute(
                "SELECT id, session_id, role, content, timestamp, active FROM messages "
                "WHERE session_id=? AND COALESCE(active, 1)=1 ORDER BY timestamp LIMIT ?",
                (session_id, limit),
            ).fetchall()

    def has_session(self, session_id):
        with closing(self._connect()) as con:
            self._required_columns(con)
            row = con.execute("SELECT id FROM sessions WHERE id=? LIMIT 1", (session_id,)).fetchone()
        return bool(row)

    def write_probe_for_tests(self):
        with closing(self._connect()) as con:
            con.execute("CREATE TABLE should_not_write(id integer)")


def detect_profiles(localapp=None):
    base = Path(localapp or os.environ.get("LOCALAPPDATA", "")) / "hermes"
    candidates = []
    if (base / "state.db").exists():
        candidates.append(("default", base / "state.db"))
    profiles_dir = base / "profiles"
    if profiles_dir.exists():
        for child in sorted(profiles_dir.iterdir()):
            if (child / "state.db").exists():
                candidates.append((child.name, child / "state.db"))
    found = []
    for profile_id, db in candidates:
        try:
            src = HermesSource(db, profile_id)
            found.append({
                "id": profile_id,
                "dbPath": str(db),
                "schemaVersion": src.schema_version,
                "mtime": db.stat().st_mtime,
            })
        except (UnsupportedSchemaError, UnsafeSourceStateError) as exc:
            found.append({"id": profile_id, "dbPath": str(db), "unsupported": str(exc)})
    return found


def detect_kanban(localapp=None):
    base = Path(localapp or os.environ.get("LOCALAPPDATA", ""))
    roots = [base / "hermes", base / "hermes" / "kanban", base / "hermes" / "boards"]
    profiles = base / "hermes" / "profiles"
    if profiles.exists():
        roots.extend(child for child in profiles.iterdir() if child.is_dir())
        roots.extend(child / "kanban" for child in profiles.iterdir() if child.is_dir())
    for root in roots:
        for name in ("kanban.db", "tasks.db", "hermes-kanban.db", "board.db"):
            db = root / name
            if db.exists():
                return {"dbPath": str(db), "rootName": root.name}
    return None


class KanbanSource:
    def __init__(self, path):
        self.path = Path(path)

    def list_tasks(self, limit=100):
        limit = max(1, min(int(limit or 100), 200))
        with closing(_readonly_connection(self.path)) as con:
            cols = _columns(con, "tasks")
            wanted = [
                "id", "title", "assignee", "status", "priority",
                "created_at", "started_at", "completed_at", "workspace_path",
                "session_id", "project_id",
            ]
            select = [c for c in wanted if c in cols]
            if not select:
                return []
            rows = con.execute(f"SELECT {', '.join(select)} FROM tasks LIMIT ?", (limit,)).fetchall()
        for row in rows:
            if "workspace_path" in row:
                row["workspaceName"] = _basename(row.pop("workspace_path"))
        return rows
