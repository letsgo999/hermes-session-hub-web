# Hermes Session Hub Web / 0.1.0-preview.2

## 한국어

Hermes Session Hub Web은 공식 Hermes Desktop 사용자를 위한 Windows 10/11 로컬 전용 브라우저 앱입니다.

### 기능

- 첫 실행 고지 동의를 로컬 Registry에 저장합니다.
- 프로젝트 이름, 상태, 우선순위, 마감일, 담당 프로필, 다음 작업, 고정, 보관을 관리합니다. 삭제 기능은 없습니다.
- 세션은 메타데이터만 목록으로 보여주고, 메시지는 사용자가 펼칠 때만 읽습니다.
- 세션 워크스페이스 이름과 Kanban 메타데이터 기반 연결 후보를 보여주며, 사용자가 `연결 확인`을 누른 뒤에만 프로젝트 링크를 저장합니다.
- 선택 Kanban DB는 읽기 전용 메타데이터만 표시합니다.
- 감지된 Skills는 읽기 전용 검색과 안전한 평문 미리보기를 제공합니다.
- Registry 내보내기/복원, redacted 진단 ZIP, privacy-safe 파일럿 영수증 다운로드를 제공합니다.
- `Open in Hermes`는 선택한 기존 세션의 공식 `hermes://open/<encoded-session-id>` URL을 제공합니다. 공식 URI에는 프로필 정보가 없어 활성 Desktop 프로필의 세션만 열 수 있으며 자동 교차 프로필 전환은 지원하지 않습니다.

### 제한

- 서버는 `127.0.0.1`에만 바인딩하며 외부 네트워크, 계정, 로그인, 텔레메트리, 클라우드 업로드, 외부 에셋이 없습니다.
- 화면과 진단 내보내기는 기본적으로 절대 경로, 메시지 본문, Kanban 본문/결과, 인증 정보를 노출하지 않습니다.
- Hermes schema `26-30` 범위만 지원합니다. 범위 밖 DB는 fail-closed로 처리합니다.
- Kanban DB가 없는 상태는 정상입니다.

### 개발 실행

```powershell
python -m session_hub.server
python -m unittest discover -s tests -v
```

### 빌드

```powershell
python -m pip install -r requirements-build.txt
python scripts/build_windows.py --build-root .build --output-root .out
```

ZIP 루트에는 `Start.exe`, `Stop.exe`, `README-KO.txt`, `VERSION`만 포함됩니다. 릴리스 생성은 CI에서 하지 않습니다.

### 롤백

Registry 복원은 현재 Registry의 안전 백업을 먼저 만든 뒤 새 JSON을 적용합니다. 문제가 있으면 `%LOCALAPPDATA%/HermesX/SessionHubStudent` 아래의 `registry.backup.*.json`을 복원 입력으로 다시 적용하세요.

## English

Hermes Session Hub Web is a Windows 10/11 local-only browser app for official Hermes Desktop users.

### Features

- Persists first-run disclosure acceptance in the local Registry.
- Manages project name, status, priority, due date, owner profile, next action, pinned, and archived state. There is no delete action.
- Lists session metadata only; messages are read only when the user expands a session.
- Shows unconfirmed project-link candidates from session workspace names and Kanban metadata. Links are saved only after explicit confirmation.
- Shows optional Kanban metadata read-only.
- Preserves the read-only Skills search and safe plain-text preview feature.
- Supports Registry export/restore, redacted diagnostics ZIP download, and privacy-safe pilot receipt download.
- `Open in Hermes` returns the official `hermes://open/<encoded-session-id>` URL for the selected existing session. The official URI carries no profile identity, so the session must belong to the active Desktop profile; automatic cross-profile switching is unsupported.

### Limitations

- The server binds only to `127.0.0.1`; there is no external network access, account, login, telemetry, cloud upload, or external asset.
- UI and diagnostic exports avoid absolute paths, message bodies, Kanban body/result fields, credentials, and personal identifiers by default.
- Only Hermes schema `26-30` is supported. Other schemas fail closed.
- Missing Kanban data is normal.

### Development

```powershell
python -m session_hub.server
python -m unittest discover -s tests -v
```

### Build

```powershell
python -m pip install -r requirements-build.txt
python scripts/build_windows.py --build-root .build --output-root .out
```

The ZIP root contains only `Start.exe`, `Stop.exe`, `README-KO.txt`, and `VERSION`. CI does not create releases.

### Rollback

Registry restore creates a safety backup before applying new JSON. If needed, paste a `registry.backup.*.json` file from `%LOCALAPPDATA%/HermesX/SessionHubStudent` into the restore control.
