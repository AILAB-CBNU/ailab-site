$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectDir

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop을 먼저 설치하고 실행하세요. Python은 따로 필요하지 않습니다."
}
docker compose version | Out-Null

@("seminar-data", "seminar-inbox", "teams-sync-state", "dist") | ForEach-Object {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectDir $_) | Out-Null
}

docker run --rm -it `
    -e HOME=/tmp `
    -v "${ProjectDir}:/project" `
    -w /project `
    python:3.11-slim `
    python server/setup.py

if ($LASTEXITCODE -ne 0) { throw "최초 설정에 실패했습니다." }
