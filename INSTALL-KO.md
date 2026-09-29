# 설치 및 제거

## 설치

1. `Hermes-Session-Hub-Web-v0.1.0-preview.1-win-x64.zip`의 압축을 원하는 사용자 폴더에 풉니다.
2. `Start.exe`를 실행합니다.
3. 처음 열린 화면에서 로컬 전용 원칙, 감지된 프로필, 저장 위치를 확인한 뒤 `시작`을 누릅니다.

관리자 권한, Python 설치, 자동 시작 등록은 필요하지 않습니다.

## 종료

`Stop.exe`를 실행합니다. 이 앱이 기록한 소유 프로세스만 대상으로 합니다.

## 롤백/제거

1. `Stop.exe`로 앱을 종료합니다.
2. 압축을 푼 앱 폴더를 삭제합니다.
3. 프로젝트 Registry를 보존하려면 `%LOCALAPPDATA%/HermesX/SessionHubStudent`를 남겨둡니다.
4. Registry까지 제거하려면 위 폴더를 직접 삭제합니다.

Hermes 원본 세션 DB와 Kanban DB는 앱이 쓰지 않습니다.
