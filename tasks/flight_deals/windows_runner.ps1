# Standalone runner & installer for Windows 10/11 Pro (e.g. NAS Windows VM)
# Runs 100% locally with Python + Playwright (zero Gemini Web access).
#
# Full one-shot setup (venv + daily 13:00 Task Scheduler + background LAN server on :8787 + first run):
#   powershell -ExecutionPolicy Bypass -File .\tasks\flight_deals\windows_runner.ps1 -InstallAll -RunNow

param(
    [switch]$InstallAll,
    [switch]$RegisterSchedule,
    [switch]$RunNow,
    [string]$DailyTime = "13:00",
    [int]$DashboardPort = 8787,
    [int]$Concurrency = 2
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$RepoDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$WbHome = if ($env:WB_HOME) { $env:WB_HOME } else { Join-Path $env:LOCALAPPDATA "gemini-workbench-local" }
$VenvDir = Join-Path $WbHome "venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$PythonwExe = Join-Path $VenvDir "Scripts\pythonw.exe"
$DashDir = Join-Path $WbHome "dashboard"
$LogsDir = Join-Path $WbHome "logs"

New-Item -ItemType Directory -Force -Path `
    (Join-Path $WbHome "runs"), `
    (Join-Path $DashDir "snapshots"), `
    (Join-Path $DashDir "reports"), `
    $LogsDir | Out-Null

function Ensure-Venv {
    if (-not (Test-Path $PythonExe)) {
        Write-Host "[windows_runner] Initializing isolated Python venv at $VenvDir..."
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
}

function Ensure-DashboardServer {
    $Listening = Get-NetTCPConnection -LocalPort $DashboardPort -State Listen -ErrorAction SilentlyContinue
    if (-not $Listening) {
        $RunnerPy = if (Test-Path $PythonwExe) { $PythonwExe } else { $PythonExe }
        $ServeScript = Join-Path $RepoDir "tasks\flight_deals\serve_dashboard.py"
        Start-Process -FilePath $RunnerPy -ArgumentList "`"$ServeScript`" --dir `"$DashDir`" --port $DashboardPort" -WindowStyle Hidden
        Start-Sleep -Seconds 1
    }
}

function Get-LanIPv4 {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown" } |
        Select-Object -First 1 -ExpandProperty IPAddress)
    if ($ip) { return $ip }
    return "127.0.0.1"
}

if ($InstallAll -or $RegisterSchedule) {
    Ensure-Venv
    $ScriptPath = $MyInvocation.MyCommand.Path

    # 1. Daily 13:00 Flight Deals Verification Task
    $DailyAction = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`" -DashboardPort $DashboardPort -Concurrency $Concurrency"
    $DailyTrigger = New-ScheduledTaskTrigger -Daily -At $DailyTime
    $TaskSettings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask -TaskName "DailyFlightDeals15Routes" -Action $DailyAction -Trigger $DailyTrigger -Settings $TaskSettings -Force | Out-Null

    # 2. Background LAN Dashboard HTTP Server Task (AtLogOn + immediate start)
    $RunnerPy = if (Test-Path $PythonwExe) { $PythonwExe } else { $PythonExe }
    $ServeScript = Join-Path $RepoDir "tasks\flight_deals\serve_dashboard.py"
    $SrvAction = New-ScheduledTaskAction -Execute $RunnerPy -Argument "`"$ServeScript`" --dir `"$DashDir`" --port $DashboardPort"
    $SrvTrigger = New-ScheduledTaskTrigger -AtLogOn
    $SrvSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName "FlightDealsDashboardServer" -Action $SrvAction -Trigger $SrvTrigger -Settings $SrvSettings -Force | Out-Null

    # 3. Private-LAN Firewall rule (succeeds if elevated; otherwise prints helper command)
    try {
        if (-not (Get-NetFirewallRule -DisplayName "FlightDealsDashboard_LAN_$DashboardPort" -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName "FlightDealsDashboard_LAN_$DashboardPort" `
                -Direction Inbound -Profile Private -Protocol TCP -LocalPort $DashboardPort -Action Allow -ErrorAction Stop | Out-Null
            Write-Host "[windows_runner] Opened Windows Firewall TCP port $DashboardPort (Private LAN only)."
        }
    } catch {
        Write-Host "[windows_runner] Note: To access from other LAN devices (Mac/iPhone), run once in Administrator PowerShell:"
        Write-Host "  New-NetFirewallRule -DisplayName 'FlightDealsDashboard_LAN_$DashboardPort' -Direction Inbound -Profile Private -Protocol TCP -LocalPort $DashboardPort -Action Allow"
    }

    Ensure-DashboardServer
    $LanIp = Get-LanIPv4
    Write-Host "[windows_runner] Registered 'DailyFlightDeals15Routes' (Daily at $DailyTime) & 'FlightDealsDashboardServer' (Port $DashboardPort)."
    Write-Host "[windows_runner] LAN Dashboard URL: http://${LanIp}:${DashboardPort}/"

    if (-not $RunNow) {
        exit 0
    }
}

Ensure-Venv

# Prune temporary run directories older than 7 days
Get-ChildItem -Path (Join-Path $WbHome "runs") -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# Pull latest parser updates from public repo quietly (non-fatal if offline)
try {
    git -C $RepoDir pull --ff-only origin main 2>$null | Out-Null
} catch {}

$RunDate = (Get-Date).ToString("yyyy-MM-dd")
$RunStamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
$RunDir = Join-Path (Join-Path $WbHome "runs") "$RunStamp-flight-deals"
$ReportPath = Join-Path (Join-Path $DashDir "reports") "$RunDate.md"
$LatestReport = Join-Path (Join-Path $DashDir "reports") "latest.md"
$SnapPath = Join-Path (Join-Path $DashDir "snapshots") "$RunDate.json"
$IndexHtml = Join-Path $DashDir "index.html"
$LogFile = Join-Path $LogsDir "last_run.log"

& $PythonExe (Join-Path $RepoDir "tasks\flight_deals\run.py") `
    --run-dir $RunDir `
    --out $ReportPath `
    --json-out $SnapPath `
    --concurrency $Concurrency `
    --save-parquet *>&1 | Tee-Object -FilePath $LogFile

Copy-Item -Force $ReportPath $LatestReport

& $PythonExe (Join-Path $RepoDir "tasks\flight_deals\dashboard.py") `
    --snapshots-dir (Join-Path $DashDir "snapshots") `
    --out $IndexHtml `
    --mode standalone

Ensure-DashboardServer
$LanIp = Get-LanIPv4
Write-Host "[windows_runner] Completed! Report: $LatestReport"
Write-Host "[windows_runner] Dashboard live at: http://${LanIp}:${DashboardPort}/"
