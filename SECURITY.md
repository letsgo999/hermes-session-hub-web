# Security Policy

Report security issues privately through the repository maintainer contact path.

Do not include real Hermes session rows, logs, cookies, tokens, credentials, local usernames, Drive paths, or screenshots in public issues.

Security boundaries:

- Loopback only: `127.0.0.1`.
- Per-run random auth cookie and CSRF token.
- Host and Origin validation.
- Restrictive CSP and no CORS.
- Source databases are opened read-only with SQLite query-only and authorizer checks.
- Skills are scanned read-only from allowed detected profile skill roots only. Backup/archive/staging, hidden, cache, temp, and vendor directories are excluded by default.
- Skill identifiers are opaque hashes; preview requests reject traversal-style or unknown identifiers and never follow paths outside an allowed skill root.
