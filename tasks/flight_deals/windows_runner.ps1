# Standalone runner & installer for Windows 10/11 Pro (e.g. NAS Windows VM)
# Runs 100% locally with Python + Playwright (zero Gemini Web access).
#
# Full one-shot setup (venv + daily 13:00 Task Scheduler + background LAN/Tailscale server on :8787):
#   powershell -ExecutionPolicy Bypass -File .\tasks\flight_deals\windows_runner.ps1 -InstallAll

param(
    [switch]$InstallAll,
    [switch]$RegisterSchedule,
    [switch]$RestartServerOnly,
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

function Ensure-FirewallRule {
    $RuleName = "FlightDealsDashboard_LAN_$DashboardPort"
    try {
        # Remove older Private-only rule if present; NAS virtual NICs & Tailscale adapters often default
        # to Windows 'Public' (Unidentified network) profile, so scope safely via RemoteAddress instead!
        Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
        New-NetFirewallRule -DisplayName $RuleName `
            -Direction Inbound `
            -Profile Any `
            -RemoteAddress @("LocalSubnet", "100.64.0.0/10", "192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12") `
            -Protocol TCP `
            -LocalPort $DashboardPort `
            -Action Allow `
            -ErrorAction Stop | Out-Null
        Write-Host "[windows_runner] Configured Windows Firewall TCP port $DashboardPort (LAN + Tailscale 100.64.0.0/10)."
    } catch {
        Write-Host "[windows_runner] Note: Run once in Administrator PowerShell to open Firewall for LAN & Tailscale:"
        Write-Host "  New-NetFirewallRule -DisplayName '$RuleName' -Direction Inbound -Profile Any -RemoteAddress LocalSubnet,100.64.0.0/10,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12 -Protocol TCP -LocalPort $DashboardPort -Action Allow"
    }
}

function Register-DashboardServerTask {
    $RunnerPy = if (Test-Path $PythonwExe) { $PythonwExe } else { $PythonExe }
    $ServeScript = Join-Path $RepoDir "tasks\flight_deals\serve_dashboard.py"
    $SrvAction = New-ScheduledTaskAction -Execute $RunnerPy -Argument "`"$ServeScript`" --dir `"$DashDir`" --port $DashboardPort"
    $SrvTrigger = New-ScheduledTaskTrigger -AtLogOn
    $SrvSettings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName "FlightDealsDashboardServer" -Action $SrvAction -Trigger $SrvTrigger -Settings $SrvSettings -Force | Out-Null
}

function Ensure-DashboardServer {
    $Listening = Get-NetTCPConnection -LocalPort $DashboardPort -State Listen -ErrorAction SilentlyContinue
    if (-not $Listening) {
        # Start via Task Scheduler first so the server survives outside ephemeral agent/SSH shells!
        if (Get-ScheduledTask -TaskName "FlightDealsDashboardServer" -ErrorAction SilentlyContinue) {
            Start-ScheduledTask -TaskName "FlightDealsDashboardServer" -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
        $Listening = Get-NetTCPConnection -LocalPort $DashboardPort -State Listen -ErrorAction SilentlyContinue
        if (-not $Listening) {
            $RunnerPy = if (Test-Path $PythonwExe) { $PythonwExe } else { $PythonExe }
            $ServeScript = Join-Path $RepoDir "tasks\flight_deals\serve_dashboard.py"
            Start-Process -FilePath $RunnerPy -ArgumentList "`"$ServeScript`" --dir `"$DashDir`" --port $DashboardPort" -WindowStyle Hidden
            Start-Sleep -Seconds 2
        }
    }
    $FinalCheck = Get-NetTCPConnection -LocalPort $DashboardPort -State Listen -ErrorAction SilentlyContinue
    if ($FinalCheck) {
        Write-Host "[windows_runner] Dashboard HTTP server is LISTENING on 0.0.0.0:$DashboardPort"
    } else {
        Write-Warning "[windows_runner] Dashboard HTTP server failed to bind port $DashboardPort"
    }
}

function Print-AccessUrls {
    $AllIps = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -ExpandProperty IPAddress
    foreach ($ip in $AllIps) {
        if ($ip -like "100.*") {
            Write-Host "  -> Tailscale URL (works across NAT): http://${ip}:${DashboardPort}/"
        } else {
            Write-Host "  -> Adapter IP URL                 : http://${ip}:${DashboardPort}/"
        }
    }
}

if ($RestartServerOnly) {
    Ensure-Venv
    Register-DashboardServerTask
    Ensure-FirewallRule
    Ensure-DashboardServer
    Print-AccessUrls
    exit 0
}

if ($InstallAll -or $RegisterSchedule) {
    Ensure-Venv
    $ScriptPath = $MyInvocation.MyCommand.Path

    $DailyAction = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`" -DashboardPort $DashboardPort -Concurrency $Concurrency"
    $DailyTrigger = New-ScheduledTaskTrigger -Daily -At $DailyTime
    $TaskSettings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
    Register-ScheduledTask -TaskName "DailyFlightDeals15Routes" -Action $DailyAction -Trigger $DailyTrigger -Settings $TaskSettings -Force | Out-Null

    Register-DashboardServerTask
    Ensure-FirewallRule
    Ensure-DashboardServer
    Write-Host "[windows_runner] Registered 'DailyFlightDeals15Routes' (Daily at $DailyTime) & 'FlightDealsDashboardServer'."
    Print-AccessUrls

    if (-not $RunNow) {
        exit 0
    }
}

Ensure-Venv

Get-ChildItem -Path (Join-Path $WbHome "runs") -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

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
Write-Host "[windows_runner] Completed! Report: $LatestReport"
Print-AccessUrls
