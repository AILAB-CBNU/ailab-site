# Discord 세미나 자료 자동 등록

대상: CBNU AI LAB → 세미나-자료
채널 링크: https://discord.com/channels/<SERVER_ID>/<CHANNEL_ID>

## Windows 서버에서 실행

1. `cbnu-ailab-windows-discord-addon.zip`을 기존 `ailab-site-v1` 폴더 안에 풀어주세요. `09-SETUP-DISCORD.bat`와 기존 `06-START-HTTPS-WEBSITE.bat`가 같은 폴더에 있어야 합니다.
2. 홈페이지 실행 창(06번)은 켜두세요.
3. Discord 개발자 포털 → AI Lab Seminar → 봇 → 토큰 초기화에서 직접 새 토큰을 발급하고 복사합니다. 기존 토큰을 보관하고 있다면 그것을 써도 됩니다.
4. `09-SETUP-DISCORD.bat` 실행 → Bot token에 붙여넣고 Enter. 입력 문자는 보이지 않습니다. 채널 질문은 Enter만 누르면 위 세미나 채널을 사용합니다.
5. `Setup complete` 확인 후 `10-START-DISCORD-SYNC.bat` 실행. `Collector ready`가 나오면 새 파일을 채널에 업로드하세요.
6. 약 15~20초 뒤 홈페이지 `/seminars.html`을 새로고침합니다. 글 첫 줄은 제목, 서버 닉네임은 발표자, 메시지 작성 시각은 업로드 날짜로 저장됩니다. 서버 닉네임이 없으면 Discord 표시 이름/계정 이름을 사용합니다.

Docker, Hyper-V, pip, 별도 Python 설치는 필요 없습니다. 기존 무설치 패키지의 runtime/python을 사용합니다. 추가 인바운드 포트 설정도 필요 없습니다. 학교망에서 Discord API/CDN으로 나가는 HTTPS는 허용되어야 합니다.

## 동작 범위

- 설정 완료 시점 이후 새 메시지의 직접 첨부파일만 수집합니다. 이미 있던 자료는 다시 업로드하세요. 설정을 다시 실행하면 수집 시작점도 현재 시점으로 변경됩니다.
- 일반 텍스트/공지 채널 한 개를 수집합니다. 포럼·스레드·DM, 외부 파일 링크는 지원하지 않습니다.
- 메시지 수정·삭제를 홈페이지에 반영하지 않습니다. 다운로드한 자료는 홈페이지 서버에 보관됩니다.
- 전체 첨부파일을 저장한 뒤 manifest를 발행합니다. 실패 시 재시도하고 재시작 후 마지막 처리 지점부터 이어갑니다.
- 홈페이지가 꺼져 있으면 inbox에 대기하고 홈페이지가 켜질 때 등록됩니다. 날짜 내림차순 정렬과 중복 방지는 기존 세미나 서비스를 사용합니다.
- 기본 허용 형식: PDF, PPT/PPTX, DOC/DOCX, XLS/XLSX, ZIP, TXT, MD, PNG/JPG/JPEG/WEBP. 메시지당 합계 100MiB. 허용하지 않는 형식·빈 파일·초과 파일은 건너뛰고 `discord-sync-state/rejected-*.json`에 기록합니다.
- REST 방식으로 수집하므로 Discord에서 봇이 오프라인으로 표시될 수 있습니다. 실행 창의 `Collector ready`, `logs/discord-sync.log`, 실제 홈페이지 등록 결과로 확인하세요.
- 서버 재부팅 후에는 06번과 10번을 다시 실행해야 합니다. 자동 시작 등록은 이 추가 패키지에 포함하지 않았습니다.

## 보관 및 문제 해결

토큰은 서버의 `discord-sync-state/config.json`에 저장됩니다. 이 폴더를 공유하거나 공개 웹 폴더 안에 옮기지 마세요. 배포 ZIP에는 토큰이 포함되지 않습니다.

- HTTP 401: 토큰을 확인하고 09번으로 다시 설정합니다.
- HTTP 403: 봇이 해당 채널을 볼 수 있고 메시지 기록을 읽을 수 있는지 채널 권한을 확인합니다.
- Message Content Intent 오류: 개발자 포털의 봇 페이지에서 해당 설정을 켜고 저장합니다.
- Queued만 나오고 홈페이지에 없음: 홈페이지 실행 여부와 `seminar-inbox/*.error.txt`를 확인합니다.
- 한 서버 PC에서 10번은 하나만 실행하세요. 중복 실행 시 로컬 포트 잠금으로 두 번째 프로그램을 중단합니다.

구현 참고: [Discord 메시지 API](https://docs.discord.com/developers/resources/message), [요청 제한](https://docs.discord.com/developers/topics/rate-limits), [서버 멤버 API](https://docs.discord.com/developers/resources/guild#get-guild-member).
