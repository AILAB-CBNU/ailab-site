# Teams · Hermes · 세미나 자료실 연동

## 현재 구현한 구조

운영 서버 PC가 지정한 Teams 채널을 60초마다 읽고, 새 게시물의 SharePoint 첨부 파일을 내려받아 `seminar-inbox/`에 넣습니다. 웹 서비스가 이 inbox를 검증한 뒤 `seminar-data/`에 보관하고 `/seminars.html`에 표시합니다.

```text
Teams 전용 세미나 채널
  → Microsoft Graph 읽기 전용 수집기
  → seminar-inbox (처리 대기)
  → 파일 검증 + Discord 닉네임 변환
  → seminar-data (영구 보관)
  → /api/seminars
  → 세미나 자료실 화면
```

이 방식은 연구실 서버를 인터넷에서 들어오는 웹훅에 노출하지 않습니다. Teams의 채널 파일은 SharePoint에 저장되므로 Graph로 메시지와 실제 파일을 함께 읽습니다. Microsoft 문서상 채널 메시지는 `GET /teams/{team-id}/channels/{channel-id}/messages`, 채널 파일 위치는 `GET /teams/{team-id}/channels/{channel-id}/filesFolder`로 조회할 수 있습니다.

- [List channel messages](https://learn.microsoft.com/en-us/graph/api/channel-list-messages?view=graph-rest-1.0)
- [Get filesFolder](https://learn.microsoft.com/en-us/graph/api/channel-get-filesfolder?view=graph-rest-1.0)
- [Download driveItem content](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content?view=graph-rest-1.0)

## 1. Teams 채널 준비

세미나 자료 전용 표준 채널을 하나 만듭니다. 업로드 규칙은 간단합니다.

1. 채널에서 **새 게시물**을 작성합니다. 답글은 사용하지 않습니다.
2. 첫 줄이나 게시물 제목에 세미나 제목을 씁니다.
3. PDF, PPTX 등 발표 파일을 첨부합니다.
4. 게시물 작성 시각이 웹사이트의 업로드 시각이 되며 최신순으로 정렬됩니다.

전용 채널의 모든 첨부 게시물을 수집합니다. 한 채널을 다른 용도와 함께 쓴다면 `.env`의 `TEAMS_REQUIRED_TAG=#세미나`를 설정하고 본문에 해당 태그를 넣습니다.

## 2. Microsoft Entra 앱 등록과 권한 방식 선택

Entra 앱은 서버가 Graph 토큰을 받는 신원입니다.

1. [Microsoft Entra 관리 센터](https://entra.microsoft.com/)에서 **App registrations → New registration**을 선택합니다.
2. 이름을 `CBNU AI Lab Seminar Sync`로 정하고 학교 테넌트의 계정만 허용합니다.
3. Overview의 **Directory (tenant) ID**와 **Application (client) ID**를 기록합니다.
4. **Certificates & secrets → Client secrets → New client secret**에서 비밀 값을 만듭니다. 화면에 한 번 표시되는 **Value**를 보관합니다.
5. **Authentication → Advanced settings → Allow public client flows**를 `Yes`로 저장합니다. 서버 PC의 최초 파일 로그인에 필요합니다.

### 권장: 세미나 팀 하나만 승인하는 RSC

일반 학생 계정에서 **Grant admin consent**가 비활성화되어 있으면 이 방식을 사용합니다. 권한을 두 부분으로 나눕니다.

- Teams 앱의 `ChannelMessage.Read.Group`: 앱을 설치한 팀의 채널 메시지만 읽기
- 서버에 한 번 로그인하는 연구실 계정의 위임 `Files.Read.All`: 그 계정이 접근할 수 있는 Teams/SharePoint 첨부 파일 읽기

RSC 권한은 Entra의 **API permissions**에 추가하지 않습니다. Teams 앱 manifest에 선언하며, 팀 소유자가 앱을 해당 팀에 설치할 때 승인합니다. `Files.Read.All`은 사용자 위임 권한이라 기본적으로 학교 전체 관리자 승인이 필요하지 않으며, 서버 최초 실행에서 해당 팀과 파일에 접근 가능한 연구실 계정으로 한 번 승인합니다. Microsoft 문서도 RSC는 Entra 관리 센터가 아니라 Teams 앱 manifest에서 정의하고 팀 소유자가 설치 시 승인할 수 있다고 설명합니다.

먼저 서버의 공개 HTTPS 주소로 앱 패키지를 만듭니다.

```sh
python3 scripts/build_teams_app.py \
  --app-id 'Entra-Application-Client-ID' \
  --public-url 'https://seminar.example.ac.kr'
```

생성된 `dist/cbnu-ailab-seminar-teams-app.zip`을 Teams의 **앱 관리 → 사용자 지정 앱 업로드**에서 올리고 세미나 팀에 추가합니다. 추가 화면에 팀 메시지 읽기 권한이 표시되며, 팀 소유자가 저장하면 승인됩니다.

- [Teams RSC 권한 관리](https://learn.microsoft.com/en-us/microsoftteams/manage-consent-app-permissions)
- [RSC 앱 manifest와 테스트](https://learn.microsoft.com/en-us/microsoftteams/platform/graph-api/rsc/test-resource-specific-consent)

학교 정책에서 사용자 지정 앱 업로드, 팀 RSC 또는 사용자 위임 동의를 막아 두었다면 이 경로도 Teams 관리자가 허용해야 합니다. Microsoft 정책을 우회하는 방법은 없습니다.

### 대안: 학교 전체 관리자 승인

Teams 사용자 지정 앱을 사용할 수 없다면 **API permissions → Microsoft Graph → Application permissions**에 `ChannelMessage.Read.All`, `Files.Read.All`을 추가하고 **Privileged Role Administrator** 이상의 학교 관리자에게 승인을 요청합니다. 두 권한의 상태가 `Granted for 충북대학교`로 바뀌기 전에는 수집기가 동작하지 않습니다.

## 3. 팀 ID와 채널 ID 확인

Teams에서 팀과 채널의 **링크 복사**를 선택합니다.

- 팀 링크의 `groupId`가 `TEAMS_TEAM_ID`입니다.
- 채널 링크의 `/channel/<인코딩된 값>/` 부분을 URL 디코딩한 값이 `TEAMS_CHANNEL_ID`입니다. 보통 `19:...@thread.tacv2` 모양입니다.
- 링크의 `tenantId`는 앞에서 기록한 `TEAMS_TENANT_ID`와 같아야 합니다.

확실하지 않으면 Microsoft Graph Explorer에서 `GET /me/joinedTeams`와 `GET /teams/{team-id}/channels`를 실행해 표시 이름과 ID를 대조합니다.

## 4. 서버 설정

서버 PC에는 Docker Engine과 Docker Compose만 설치하면 됩니다. 호스트 Python은 필요하지 않습니다. 설정용 Python도 컨테이너 안에서 실행됩니다. 현재 등록한 충북대학교 tenant ID와 Entra 앱 ID가 기본값으로 들어 있습니다.

```sh
./server/setup-with-docker.sh
```

Windows 10/11과 Docker Desktop을 사용한다면 PowerShell에서 다음을 실행합니다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
./server/setup.ps1
./server/install-launcher.ps1
```

### Docker와 Hyper-V를 사용할 수 없는 Windows PC

미리 만든 `dist/cbnu-ailab-windows-portable.zip`을 서버 PC로 복사해 압축을 풉니다. 이 패키지에는 Python 공식 Windows 임베디드 런타임이 포함되어 있으므로 Docker, Hyper-V, 시스템 Python 설치가 필요하지 않습니다.

1. 압축을 푼 `ailab-site-v1` 폴더에서 `04-START-FULL-SERVICE.bat`를 더블클릭합니다.
2. 최초 설정과 Microsoft 파일 로그인을 완료합니다.
3. 생성된 `dist/cbnu-ailab-seminar-teams-app.zip`을 Teams 세미나 팀에 한 번 설치합니다.
4. 이후에는 `04-START-FULL-SERVICE.bat`만 실행합니다. 검은 창을 닫으면 서버도 종료됩니다.

로그는 `logs/`, 보관 자료는 `seminar-data/`, 로그인 갱신 정보는 `teams-sync-state/`에 저장됩니다. 폴더를 다른 위치로 옮길 때는 이 세 폴더와 `.env`를 함께 옮깁니다.

Teams 연동 전에 홈페이지만 먼저 공개하려면 `01-ALLOW-PORT-80-AS-ADMIN.bat`를 우클릭해 관리자 권한으로 한 번 실행한 뒤 `02-START-WEBSITE.bat`를 더블클릭합니다. 이 실행기는 별도 설정 없이 `0.0.0.0:80`으로 웹사이트를 엽니다. `03-CHECK-WEBSITE.bat`는 80번 포트, `localhost`, `ailab.cbnu.ac.kr` 응답을 차례로 확인합니다.

HTTPS로 전환할 때는 실행 중인 `02-START-WEBSITE.bat` 창을 먼저 닫습니다. `05-ALLOW-HTTPS-AS-ADMIN.bat`를 관리자 권한으로 한 번 실행해 443번 포트를 연 다음 `06-START-HTTPS-WEBSITE.bat`를 실행합니다. Caddy가 80/443번 포트를 맡고 내부의 Python 웹앱(`127.0.0.1:8765`)으로 요청을 전달합니다. DNS가 현재 서버의 공인 IP를 가리키고 외부에서 80/443번 포트에 접근할 수 있으면 공개 인증서 발급, 갱신, HTTP에서 HTTPS로의 이동이 자동 처리됩니다. 최초 발급은 약 1분 걸릴 수 있으며 `07-CHECK-HTTPS.bat`로 결과를 확인합니다.

관리자 페이지를 사용하려면 서버 PC에서 `08-SET-ADMIN-PASSWORD.bat`를 실행해 비밀번호를 설정하고 `https://ailab.cbnu.ac.kr/admin.html`에 로그인합니다. 홈, 연구, 구성원, 논문, 과제, 소식, 세미나, 강의·자료, 연락처의 텍스트와 링크를 페이지별로 편집할 수 있고, 공통 헤더와 푸터는 한 번 수정하면 모든 페이지에 반영됩니다. 변경 데이터와 관리자 인증 파일은 `seminar-data/`에 있으므로 서버 이전이나 백업 때 함께 보존합니다.

설정기는 `.env`, 업로드 토큰, RSC Teams 앱 패키지를 만듭니다. client secret, 팀 ID, 채널 ID, 공개 HTTPS 주소는 최초 한 번 입력해야 합니다. 첫 실행에서는 Microsoft 로그인 주소와 코드가 표시되며, 세미나 팀 파일에 접근할 수 있는 연구실 계정으로 `Files.Read.All` 위임 권한을 승인합니다. 토큰은 `teams-sync-state/delegated-token.json`에 저장되고 자동 갱신됩니다.

직접 설정하려면 프로젝트 루트에서 다음처럼 시작합니다.

프로젝트 루트에서 설정 파일을 만듭니다.

```sh
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

마지막 명령의 결과를 `SEMINAR_UPLOAD_TOKEN`에 넣고 다음 값을 채웁니다.

```dotenv
TEAMS_TENANT_ID=학교-테넌트-ID
TEAMS_CLIENT_ID=등록한-앱-ID
TEAMS_CLIENT_SECRET=발급한-secret-value
TEAMS_TEAM_ID=세미나-팀-ID
TEAMS_CHANNEL_ID=세미나-채널-ID
TEAMS_PUBLIC_URL=https://세미나-사이트-주소
TEAMS_DELEGATED_SCOPES=offline_access Files.Read.All User.Read
TEAMS_IMPORT_EXISTING=false
```

첫 실행에서 `TEAMS_IMPORT_EXISTING=false`이면 현재 채널에 이미 있는 게시물은 기준점으로만 기록하고, 그다음 새 게시물부터 가져옵니다. 기존 자료도 최근 메시지부터 가져오려면 첫 실행 전에만 `true`로 바꿉니다. 한 번 처리한 Teams 메시지 ID는 `teams-sync-state/state.json`에 저장되어 재시작해도 중복되지 않습니다.

## 5. Discord 서버 닉네임 연결

채널 메시지에는 Discord 닉네임이 없으므로 Teams 사용자의 Entra Object ID를 한 번 대응시켜야 합니다. `seminar_service/config/presenter-map.json`을 다음처럼 편집합니다.

```json
{
  "by_teams_user_id": {
    "11111111-2222-3333-4444-555555555555": "Discord 서버 닉네임"
  },
  "by_email": {}
}
```

Teams 채널 수집에는 이메일이 항상 포함되지 않으므로 `by_teams_user_id` 사용을 권장합니다. Object ID는 Entra 관리 센터의 Users에서 확인합니다. 매핑되지 않은 사용자의 자료는 버리지 않고 `seminar-inbox/*.error.txt`에 이유를 남긴 채 대기합니다. 대응표를 추가하면 감시기가 다시 처리합니다.

## 6. 실행과 확인

Linux 서버 PC 바탕화면에 원클릭 실행 아이콘을 만드는 명령은 한 번만 실행합니다.

```sh
./server/install-launcher.sh
```

Windows에서는 위의 `server/install-launcher.ps1`이 같은 역할을 합니다.

그다음부터 **AI Lab 세미나 서버** 아이콘을 실행하면 웹사이트와 Teams 수집기를 함께 빌드·시작하고 자료실을 엽니다. 터미널에서 직접 실행할 때는 다음 명령과 같습니다.

```sh
docker compose --profile teams up -d --build
docker compose ps
docker compose logs -f teams-sync website
```

학교 로그인 정책 변경 등으로 파일 로그인이 만료되면 다음 명령으로 다시 연결합니다.

```sh
./server/login-teams-files.sh
```

첫 실행 로그에 `initialized at current channel position`이 나오면 기준점이 저장된 것입니다. 그 뒤 Teams 채널에 새 게시물과 파일을 올리고 다음을 확인합니다.

```sh
curl http://127.0.0.1:8765/api/health
curl http://127.0.0.1:8765/api/seminars
```

브라우저에서는 `http://127.0.0.1:8765/seminars.html`을 엽니다. 보관 데이터는 호스트의 `seminar-data/`에 있으므로 컨테이너 이미지를 교체해도 유지됩니다.

## Hermes 연결

Hermes가 나중에 Teams 플러그인을 정상적으로 사용할 수 있게 되면 Graph 수집기를 대신하거나 보조할 수 있습니다. Hermes는 파일을 모두 내려받은 뒤 마지막에 JSON manifest를 `seminar-inbox/` 최상위에 원자적으로 생성하면 됩니다. 형식은 [seminar-inbox/README.md](../seminar-inbox/README.md)에 있습니다.

HTTP 방식이 편하면 `scripts/ingest_seminar.py`를 호출할 수도 있습니다.

```sh
export SEMINAR_UPLOAD_TOKEN='서버와-같은-토큰'
python3 scripts/ingest_seminar.py 발표자료.pdf \
  --title '주간 논문 세미나' \
  --teams-user-id 'Entra-Object-ID' \
  --message-id 'Teams-메시지-ID'
```

Hermes가 보내는 `source_message_id`는 Teams 메시지마다 고유하고 변하지 않아야 합니다. 같은 ID를 다시 보내면 서버가 중복 자료를 만들지 않습니다.

## Teams 봇을 별도로 만드는 방법

현재 구현은 채널을 자동 감시하므로 Teams 봇을 설치할 필요가 없습니다. 대화형 봇에게 개인 채팅으로 파일을 보내고 “등록 완료” 답장을 받는 화면이 필요할 때만 별도 봇을 만듭니다.

Microsoft의 현재 Teams Developer CLI 절차는 다음과 같습니다.

```sh
npm install -g @microsoft/teams.cli
teams login
teams status
teams project new python ailab-seminar-bot
cd ailab-seminar-bot
# 먼저 3978 포트를 공개 HTTPS dev tunnel에 연결
teams app create \
  --name ailab-seminar-bot \
  --endpoint https://<공개-터널-호스트>/api/messages \
  --env .env
pip install -e .
python src/main.py
```

`teams status`에서 `Sideloading: enabled`여야 하며 비활성 상태라면 학교 Teams 관리자에게 사용자 지정 앱 업로드 허용을 요청해야 합니다. Teams 서버가 봇에 접속해야 하므로 로컬 테스트도 공개 HTTPS tunnel이 필요합니다. 등록 명령이 출력하는 **Install in Teams** 링크로 앱을 설치합니다.

- [Teams 앱 등록 Quickstart](https://learn.microsoft.com/en-us/microsoftteams/platform/teams-sdk/get-started/quickstart-register)
- [Teams bot 구성 요소와 sideloading](https://learn.microsoft.com/en-us/microsoftteams/platform/teams-sdk/teams/core-concepts)
- [Teams에서 파일 송수신](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/bots-filesv4)

개인 채팅 봇의 파일 수신은 Teams SDK의 file consent API를 쓸 수 있지만 이 API는 개인 채팅에서만 동작합니다. 연구실 **채널**에 올린 파일을 자동 수집하려면 현재 프로젝트처럼 Microsoft Graph를 사용해야 합니다.

Teams의 “Outgoing Webhook”은 `@봇이름` 멘션이 있어야 실행되고 다른 Teams API에 접근할 수 없어 채널 첨부 파일 자동 보관에는 맞지 않습니다. 단순히 웹훅을 만들었는데 파일이 연결되지 않은 경우 이 제한에 걸렸을 가능성이 큽니다. [Microsoft의 Outgoing Webhook 문서](https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-outgoing-webhook)도 공개 채널·멘션 기반이며 팀 목록 같은 다른 API를 사용할 수 없다고 설명합니다.

## 서버 PC 배포

1. Linux 서버 PC에는 Docker Engine과 Compose를 설치합니다. Windows 10/11이라면 WSL 2 기반 Docker Desktop을 설치합니다. 호스트 Python은 필요하지 않습니다.
2. 이 프로젝트와 `.env`를 복사합니다. `seminar-data/`, `seminar-inbox/`, `teams-sync-state/`는 별도 백업 대상입니다.
3. `AILAB_BIND_ADDRESS=127.0.0.1`을 유지하고 Caddy 또는 Nginx에서 TLS를 종료해 `website:8000`으로 프록시합니다. 사내망에서만 직접 열 때는 서버 방화벽 정책에 맞춰 bind 주소를 정합니다.
4. Linux는 `./server/setup-with-docker.sh`, Windows는 `./server/setup.ps1`로 최초 설정과 Teams 앱 패키지를 생성합니다.
5. 생성된 Teams 앱을 세미나 팀에 한 번 설치합니다.
6. `./server/install-launcher.sh`로 바탕화면 아이콘을 만듭니다.
7. 이후에는 **AI Lab 세미나 서버** 아이콘을 실행합니다.
8. 이미지 갱신 전 `seminar-data/`를 백업하고, 갱신 후 `/api/health`와 Teams 새 업로드 한 건을 확인합니다.

`TEAMS_CLIENT_SECRET`에는 만료일이 있습니다. Entra에서 새 secret을 발급해 `.env`를 바꾼 뒤 `docker compose --profile teams up -d`로 컨테이너를 다시 만들면 됩니다.
