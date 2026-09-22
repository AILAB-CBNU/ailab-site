# CBNU AI Lab website

기존 연구실 웹사이트의 실제 콘텐츠를 새 디자인으로 옮긴 사이트와 세미나 자료 자동 수집 서비스를 함께 보관합니다.

## 구성

- `site/`: 웹사이트 화면과 이관된 콘텐츠
- `seminar_service/`: 정적 사이트, 세미나 목록 API, 인증된 업로드 API, 로컬 inbox 감시
- `teams_sync/`: Microsoft Graph로 지정한 Teams 채널을 읽는 선택형 수집기
- `seminar-data/`: 공개할 세미나 메타데이터와 파일
- `seminar-inbox/`: Hermes 또는 Teams 수집기가 완료된 파일을 넘기는 폴더
- `seminar_service/config/presenter-map.json`: Teams 사용자와 Discord 서버 닉네임의 대응표

## 로컬 실행

```sh
cp .env.example .env
cp seminar_service/config/presenter-map.example.json seminar_service/config/presenter-map.json
# .env의 SEMINAR_UPLOAD_TOKEN을 openssl rand -hex 32 결과로 교체
docker compose up -d --build
```

브라우저에서 <http://127.0.0.1:8765>를 엽니다. Teams 자동 수집은 Entra 설정을 마친 뒤 다음과 같이 켭니다.

```sh
docker compose --profile teams up -d --build
```

설정 절차와 운영 방법은 [Teams 및 서버 연동 가이드](docs/teams-integration.md)를 참고하세요. 콘텐츠 이관 근거는 [migration/README.md](migration/README.md)에 있습니다.

서버 PC에는 Docker Engine과 Docker Compose만 필요하며 호스트 Python은 필요하지 않습니다. Linux에서는 최초 한 번 `./server/setup-with-docker.sh`와 `./server/install-launcher.sh`를 실행합니다. Windows 10/11에서는 Docker Desktop을 실행한 뒤 PowerShell에서 `./server/setup.ps1`와 `./server/install-launcher.ps1`를 실행합니다. 이후에는 바탕화면의 **AI Lab 세미나 서버** 아이콘으로 웹사이트와 Teams 수집기를 함께 시작할 수 있습니다.

Hyper-V/WSL 문제로 Docker를 실행할 수 없는 Windows PC는 `dist/cbnu-ailab-windows-portable.zip`을 복사해 압축을 풀고 `04-START-FULL-SERVICE.bat`를 실행합니다. 공식 Windows 임베디드 Python이 포함되어 있어 Docker, Hyper-V, Python 설치가 모두 필요하지 않습니다.

Teams 설정 전에 홈페이지부터 공개하려면 무설치 ZIP에서 `01-ALLOW-PORT-80-AS-ADMIN.bat`를 관리자 권한으로 한 번 실행하고 `02-START-WEBSITE.bat`를 더블클릭합니다. 홈페이지가 `0.0.0.0:80`에서 실행되며 `03-CHECK-WEBSITE.bat`로 로컬과 `ailab.cbnu.ac.kr` 응답을 확인할 수 있습니다.

정식 HTTPS를 켜려면 실행 중인 02번 창을 닫고 `05-ALLOW-HTTPS-AS-ADMIN.bat`를 관리자 권한으로 한 번 실행한 뒤 `06-START-HTTPS-WEBSITE.bat`를 실행합니다. 포함된 Caddy가 Python 웹앱을 `127.0.0.1:8765`에 두고 80/443번 포트에서 프록시하며, `ailab.cbnu.ac.kr`의 공개 인증서 발급·갱신과 HTTP→HTTPS 이동을 자동 처리합니다. `07-CHECK-HTTPS.bat`로 최종 응답을 확인합니다. 배치 파일은 영문 ASCII와 Windows CRLF로 저장되어 한글 Windows 명령 프롬프트의 인코딩 영향을 받지 않습니다.

관리자 페이지는 `/admin.html`입니다. 서버 PC에서 `08-SET-ADMIN-PASSWORD.bat`를 실행해 12자 이상의 비밀번호를 최초 설정한 뒤 로그인합니다. 페이지별 본문과 링크, 공통 헤더·푸터의 한국어·영어 텍스트를 미리보기와 함께 수정할 수 있습니다. 비밀번호는 PBKDF2-SHA256 해시로 `seminar-data/admin-auth.json`에 저장되며 원문은 저장하지 않습니다. 편집 결과는 `seminar-data/site-content-overrides.json`에 보관됩니다.


## 비공개 GitHub 저장소와 서버 업데이트

이 저장소에는 코드와 이미 공개된 연구실 콘텐츠만 포함합니다. `.env`, 봇 토큰, 관리자 인증 해시, Teams 토큰 캐시, 실제 사용자 매핑, 세미나 파일/목록, 관리자 편집값, 로그, 인증서와 원본 DB는 포함하지 않습니다. 비공개 저장소에서도 이러한 파일을 커밋하지 마십시오.

기존 서버에 업데이트할 때는 `site/`를 백업한 후 새 `site/`를 복사합니다. `.env`, `seminar-data/`, `*-sync-state/`, `runtime/`과 인증서를 유지합니다. 기존 설정 파일을 예시 파일로 덮어쓰지 마십시오. GitHub push만으로 운영 서버가 배포되지는 않습니다.

신규 설치에는 로컬 설정이 필요합니다. Discord는 09번 설정에서 토큰과 세미나 채널 ID를 입력합니다. Teams는 Entra 앱 ID와 테넌트 ID를 입력합니다. ZIP은 저장소에 넣지 않으며 Python이 설치된 개발 PC에서 `python scripts/build_windows_portable.py`로 만듭니다. 생성된 ZIP에는 운영 자료나 비밀번호를 포함하지 않습니다.

최근 수상·소식·논문의 확인 기준과 링크: [콘텐츠 출처](docs/content-sources.md).

## Windows 홈페이지 자동 업데이트

공개 저장소의 `main`에 올라온 `site/` 변경을 5분마다 적용할 수 있습니다. 기존 무설치 서버에서 `11-INSTALL-AUTO-UPDATE.bat`를 한 번 실행하십시오. 추가 Git 설치와 GitHub 로그인은 필요하지 않습니다. Windows 로그인 중 동작하며, 수동 실행은 12번, 자동 실행 중단은 13번입니다. 최근 홈페이지 백업 3개를 유지합니다. [설치·복구 안내](docs/windows-auto-update.md)
