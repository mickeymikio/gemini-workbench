# PowerShell runner for direct execution on Windows 10/11 Pro (e.g. NAS Windows VM)
# Runs completely standalone with Python + Playwright (never accesses gemini.google.com).
#
# One-time Task Scheduler registration (Daily at 13:00):
#   powershell -ExecutionPolicy Bypass -File .\tasks\flight_deals\windows_runner.ps1 -RegisterSchedule

param(
    [switch]$RegisterSchedule,
    [string]$DailyTime = "13:00",
    [int]$ServePort = 0
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$RepoDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$WbHome = if ($env:WB_HOME) { $env:WB_HOME } else { Join-Path $env:LOCALAPPDATA "gemini-workbench-local" }
$VenvDir = Join-Path $WbHome "venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$DashDir = Join-Path $WbHome "dashboard"

New-Item -ItemType Directory -Force -Path (Join-Path $WbHome "runs"), (Join-Path $DashDir "snapshots"), (Join-Path $DashDir "reports") | Out-Null

if ($RegisterSchedule) {
    $ScriptPath = $MyInvocation.MyCommand.Path
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""
    $Trigger = New-ScheduledTaskTrigger -Daily -At $DailyTime
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName "DailyFlightDeals15Routes" -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
    Write-Host "[windows_runner] Registered Windows Scheduled Task 'DailyFlightDeals15Routes' at $DailyTime daily."
    Write-Host "[windows_runner] Dashboard output path: $DashDir\index.html"
    exit 0
}

if (-not (Test-Path $PythonExe)) {
    Write-Host "[windows_runner] Creating isolated Python venv at $VenvDir..."
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv venv $VenvDir
        uv pip install --python $PythonExe duckdb polars pyarrow pydantic httpx selectolax beautifulsoup4 playwright tenacity
    } else {
        python -m venv $VenvDir
        & $PythonExe -m pip install --upgrade pip
        & $PythonExe -m pip install duckdb polars pyarrow pydantic httpx selectolax beautifulsoup4 playwright tenacity
    }
    & (Join-Path $VenvDir "Scripts\playwright.exe") install chromium
}

$RunDate = (Get-Date).ToString("yyyy-MM-dd")
$RunStamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
$RunDir = Join-Path (Join-Path $WbHome "runs") "$RunStamp-flight-deals"
$ReportPath = Join-Path (Join-Path $DashDir "reports") "$RunDate.md"
$LatestReport = Join-Path (Join-Path $DashDir "reports") "latest.md"
$SnapPath = Join-Path (Join-Path $DashDir "snapshots") "$RunDate.json"
$IndexHtml = Join-Path $DashDir "index.html"

& $PythonExe (Join-Path $RepoDir "tasks\flight_deals\run.py") `
    --run-dir $RunDir `
    --out $ReportPath `
    --json-out $SnapPath `
    --save-parquet

Copy-Item -Force $ReportPath $LatestReport

& $PythonExe (Join-Path $RepoDir "tasks\flight_deals\dashboard.py") `
    --snapshots-dir (Join-Path $DashDir "snapshots") `
    --out $IndexHtml `
    --mode standalone

Write-Host "[windows_runner] Updated report: $LatestReport"
Write-Host "[windows_runner] Updated dashboard: $IndexHtml"

if ($ServePort -gt 0) {
    & $PythonExe (Join-Path $RepoDir "tasks\flight_deals\serve_dashboard.py") --dir $DashDir --port $ServePort
}
