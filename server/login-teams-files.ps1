$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectDir

docker compose --profile teams build teams-sync
if ($LASTEXITCODE -ne 0) { throw "Teams 수집기 이미지 빌드에 실패했습니다." }
docker compose --profile teams run --rm --entrypoint python teams-sync /app/teams_sync/device_login.py
if ($LASTEXITCODE -ne 0) { throw "Teams 파일 로그인에 실패했습니다." }
