# Hermes inbox

Hermes가 Teams 파일을 내려받은 뒤 이 폴더에 파일과 JSON manifest를 둡니다.
서비스는 최상위 `*.json` manifest만 처리하며 원본 파일은 삭제하지 않습니다.

예시 `2026-09-16-seminar.json`:

```json
{
  "source": "teams-hermes",
  "source_message_id": "teams-message-id",
  "source_user_id": "teams-user-object-id",
  "source_user_email": "senior@cbnu.ac.kr",
  "title": "9월 3주차 연구실 세미나",
  "summary": "선택 사항",
  "uploaded_at": "2026-09-16T15:00:00+09:00",
  "files": [
    { "path": "seminar.pdf" }
  ]
}
```

발표자는 `seminar_service/config/presenter-map.json`에서 Teams 사용자와 디스코드 서버 닉네임을 연결합니다.
성공한 manifest는 `.processed/`로 이동합니다. 실패하면 같은 이름의 `.error.txt`가 생성됩니다.
