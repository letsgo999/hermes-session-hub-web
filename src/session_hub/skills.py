import hashlib
import re
from pathlib import Path


MAX_FILE_BYTES = 256 * 1024
MAX_RESULTS = 50
SNIPPET_CHARS = 240
PREVIEW_CHARS = 12000
ID_RE = re.compile(r"^[a-f0-9]{64}$")
EXCLUDED_DIR_MARKERS = {
    ".cache", ".git", ".hg", ".svn", ".venv", "__pycache__", "cache",
    "dist", "node_modules", "temp", "tmp", "vendor",
}
EXCLUDED_NAME_PARTS = ("backup", "archive", "staging")


def search_skills(profiles, query="", profile=None):
    terms = _terms(query)
    results = []
    for item in _iter_skill_records(profiles):
        if profile and item["profile"] != profile:
            continue
        haystack = " ".join([
            item["name"],
            item["description"],
            " ".join(item["tags"]),
            item["_body"],
        ]).casefold()
        if terms and not all(term in haystack for term in terms):
            continue
        results.append(_public_result(item, terms))
        if len(results) >= MAX_RESULTS:
            break
    return {"results": results, "limit": MAX_RESULTS}


def preview_skill(profiles, skill_id):
    if not ID_RE.fullmatch(skill_id or ""):
        raise ValueError("invalid_skill_id")
    for item in _iter_skill_records(profiles):
        if item["id"] == skill_id:
            return {
                "id": item["id"],
                "profile": item["profile"],
                "name": item["name"],
                "description": item["description"],
                "tags": item["tags"],
                "category": item["category"],
                "preview": item["_text"][:PREVIEW_CHARS],
                "truncated": len(item["_text"]) > PREVIEW_CHARS,
            }
    raise FileNotFoundError(skill_id)


def _iter_skill_records(profiles):
    for profile in profiles:
        if profile.get("unsupported") or not profile.get("dbPath"):
            continue
        profile_id = str(profile.get("id") or "")
        root = (Path(profile["dbPath"]).parent / "skills").resolve()
        if not root.exists() or not root.is_dir():
            continue
        yield from _scan_root(profile_id, root)


def _scan_root(profile_id, root):
    for current, dirs, files in _safe_walk(root):
        if "SKILL.md" not in files:
            continue
        path = (current / "SKILL.md").resolve()
        if not _is_within(path, root) or path.stat().st_size > MAX_FILE_BYTES:
            continue
        text = path.read_bytes()[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        meta, body = _parse_frontmatter(text)
        rel_dir = current.relative_to(root)
        name = str(meta.get("name") or current.name).strip() or current.name
        description = str(meta.get("description") or "").strip()
        tags = _parse_tags(meta.get("tags"))
        category = "" if rel_dir.parent == Path(".") else rel_dir.parent.as_posix()
        skill_id = _skill_id(profile_id, rel_dir.as_posix())
        yield {
            "id": skill_id,
            "profile": profile_id,
            "name": name,
            "description": description,
            "tags": tags,
            "category": category,
            "_body": body,
            "_text": text,
        }


def _safe_walk(root):
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name.casefold())
        except OSError:
            continue
        dirs = []
        files = []
        for entry in entries:
            name = entry.name
            if entry.is_dir() and not entry.is_symlink():
                if not _excluded_dir(name):
                    dirs.append(entry)
            elif entry.is_file():
                files.append(name)
        stack.extend(reversed(dirs))
        yield current, dirs, files


def _excluded_dir(name):
    folded = name.casefold()
    return (
        folded.startswith(".")
        or folded in EXCLUDED_DIR_MARKERS
        or any(part in folded for part in EXCLUDED_NAME_PARTS)
    )


def _parse_frontmatter(text):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw = text[4:end].splitlines()
    body = text[text.find("\n", end + 1) + 1:]
    meta = {}
    current_key = None
    for line in raw:
        if not line.strip():
            continue
        if line.startswith((" ", "\t")) and current_key:
            value = line.strip()
            if value.startswith("-"):
                meta.setdefault(current_key, []).append(value[1:].strip())
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        current_key = key.strip()
        cleaned = value.strip()
        if cleaned.startswith("[") and cleaned.endswith("]"):
            meta[current_key] = [part.strip().strip("'\"") for part in cleaned[1:-1].split(",") if part.strip()]
        elif cleaned:
            meta[current_key] = cleaned.strip("'\"")
        else:
            meta[current_key] = []
    return meta, body


def _parse_tags(value):
    if isinstance(value, list):
        return [str(tag).strip() for tag in value if str(tag).strip()][:20]
    if isinstance(value, str):
        return [tag.strip() for tag in value.split(",") if tag.strip()][:20]
    return []


def _public_result(item, terms):
    body = item["_body"]
    return {
        "id": item["id"],
        "profile": item["profile"],
        "name": item["name"],
        "description": item["description"],
        "tags": item["tags"],
        "category": item["category"],
        "snippet": _snippet(body, terms),
    }


def _snippet(text, terms):
    collapsed = " ".join(text.split())
    if not collapsed:
        return ""
    folded = collapsed.casefold()
    idx = -1
    for term in terms:
        idx = folded.find(term)
        if idx >= 0:
            break
    if idx < 0:
        idx = 0
    start = max(0, idx - 60)
    return collapsed[start:start + SNIPPET_CHARS]


def _terms(query):
    return [part.casefold() for part in str(query or "").split() if part.strip()][:8]


def _skill_id(profile_id, rel):
    return hashlib.sha256(f"{profile_id}\0{rel}".encode("utf-8")).hexdigest()


def _is_within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
