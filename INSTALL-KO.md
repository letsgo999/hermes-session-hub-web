# Hermes Session Hub Web 설치·사용·복구 안내

대상 버전: `0.1.0-preview.1` / Windows 10·11 x64

## 설치와 실행

1. 배포자가 제공한 SHA-256 값과 ZIP의 체크섬이 같은지 확인합니다.
2. `Hermes-Session-Hub-Web-v0.1.0-preview.1-win-x64.zip`의 압축을 원하는 사용자 폴더에 풉니다.
3. `Start.exe`를 실행합니다. 로컬 서버가 시작되고 기본 브라우저가 자동으로 열립니다.
4. 처음 열린 화면에서 로컬 전용 원칙, 감지된 Hermes 버전·프로필, 저장 위치를 확인한 뒤 `시작`을 누릅니다.

관리자 권한, 별도 Python 설치, 로그인, 자동 시작 등록은 필요하지 않습니다. 서버는 `127.0.0.1`에서만 동작하며 중앙 텔레메트리나 데이터 전송이 없습니다.

## 주요 기능

- 프로젝트와 오늘의 실행목록을 만들고 수정하거나 보관합니다. 영구 삭제 기능은 없습니다.
- 세션·선택적 Kanban 메타데이터를 읽기 전용으로 조회합니다. 메시지는 사용자가 펼칠 때만 로컬에서 읽습니다.
- 활성 Hermes 프로필의 Skills를 이름·설명·태그·본문으로 검색하고 `SKILL.md`를 읽기 전용으로 미리 봅니다. 스킬 편집·설치·삭제는 하지 않습니다.
- `Open in Hermes`가 열리지 않으면 화면의 세션 ID와 대체 명령을 복사해 사용합니다.
- 진단 화면에서 개인정보를 제거한 진단 ZIP과 파일럿 영수증을 직접 내려받을 수 있습니다.

## 종료

`Stop.exe`를 실행합니다. 이 앱이 기록한 `Start.exe` 소유 프로세스만 종료 대상으로 삼습니다.

## Registry 백업과 복구

- 프로젝트 데이터는 `%LOCALAPPDATA%/HermesX/SessionHubStudent`에 유지됩니다.
- 프로젝트 화면의 `Registry 내보내기`로 JSON 백업을 내려받습니다.
- 복구할 때는 JSON 내용을 `Registry 복원` 칸에 붙여넣고 `복원`을 누릅니다.
- 복원 직전의 Registry는 같은 데이터 폴더에 `registry.backup.*.json`으로 자동 보관됩니다.
- Hermes 세션 DB, Kanban DB, Skills 파일은 읽기 전용이며 복구 작업의 대상이 아닙니다.

## 업데이트

1. `Stop.exe`로 현재 버전을 종료합니다.
2. Registry JSON을 내보내 별도로 보관합니다.
3. 새 ZIP을 새 폴더에 압축 해제한 뒤 새 `Start.exe`를 실행합니다.
4. `%LOCALAPPDATA%/HermesX/SessionHubStudent`는 삭제하지 않습니다. 기존 프로젝트 데이터가 그대로 사용됩니다.
5. 새 버전이 정상 동작하면 이전 실행 폴더만 삭제합니다.

## 롤백과 제거

1. `Stop.exe`로 앱을 종료합니다.
2. 롤백하려면 이전 ZIP을 새 폴더에 다시 풀고 `Start.exe`를 실행합니다.
3. 제거하려면 압축을 푼 앱 폴더를 삭제합니다.
4. 프로젝트 Registry를 보존하려면 `%LOCALAPPDATA%/HermesX/SessionHubStudent`를 남겨둡니다.
5. Registry까지 완전히 제거하려는 경우에만 위 데이터 폴더를 사용자가 직접 삭제합니다.

Hermes 원본 세션 DB, Kanban DB, Skills 파일은 앱이 쓰지 않습니다.
