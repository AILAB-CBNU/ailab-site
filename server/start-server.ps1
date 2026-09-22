$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectDir

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop을 먼저 설치하고 실행하세요. Python은 따로 필요하지 않습니다."
}
docker compose version | Out-Null

if (-not (Test-Path ".env")) {
    & (Join-Path $PSScriptRoot "setup.ps1")
}

$EnvValues = @{}
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') { $EnvValues[$matches[1].Trim()] = $matches[2].Trim() }
}
$Required = @("TEAMS_TENANT_ID", "TEAMS_CLIENT_ID", "TEAMS_CLIENT_SECRET", "TEAMS_TEAM_ID", "TEAMS_CHANNEL_ID")
$Missing = @($Required | Where-Object { -not $EnvValues[$_] })
if ($Missing.Count -gt 0) { throw "설정이 비어 있습니다: $($Missing -join ', ')" }

@("seminar-data", "seminar-inbox", "teams-sync-state") | ForEach-Object {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectDir $_) | Out-Null
}
if (-not (Test-Path "teams-sync-state/delegated-token.json")) {
    & (Join-Path $PSScriptRoot "login-teams-files.ps1")
}

docker compose --profile teams up -d --build
if ($LASTEXITCODE -ne 0) { throw "서비스 시작에 실패했습니다." }

$Port = if ($EnvValues["AILAB_PORT"]) { $EnvValues["AILAB_PORT"] } else { "8765" }
$HealthUrl = "http://127.0.0.1:$Port/api/health"
$SeminarUrl = "http://127.0.0.1:$Port/seminars.html"
for ($i = 0; $i -lt 30; $i++) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 2 | Out-Null
        Write-Host "AI Lab 세미나 서버가 실행 중입니다: $SeminarUrl"
        docker compose --profile teams ps
        Start-Process $SeminarUrl
        exit 0
    } catch {
        Start-Sleep -Seconds 1
    }
}

docker compose --profile teams logs --tail=80 website teams-sync
throw "서버 상태 확인에 실패했습니다."
