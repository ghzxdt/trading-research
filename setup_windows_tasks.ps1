# Recreates the app's Windows scheduled tasks and the desktop shortcut for the signed-in user.
# Run from the project folder after .venv exists:  powershell -ExecutionPolicy Bypass -File .\setup_windows_tasks.ps1
# Times are the computer's local time (US Central). Triggers start tomorrow so nothing fires during setup.
# Settings (LOG.md, 2026-11-07): start late if missed, run on battery, don't wake the computer,
# run only while the user is signed in (no stored password).
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "Missing $pythonw; build .venv first." }
$user = "$env:USERDOMAIN\$env:USERNAME"
$days = 'Monday','Tuesday','Wednesday','Thursday','Friday'
$start = (Get-Date).Date.AddDays(1)

function Register-AppTask($name, $script, $arguments, $times, $limitHours, $description) {
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument ("`"$(Join-Path $root $script)`" $arguments").Trim() -WorkingDirectory $root
    $triggers = foreach ($t in $times) { New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At ($start + [TimeSpan]::Parse($t)) }
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours $limitHours) -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Settings $settings -Principal $principal `
        -Description $description -Force | Out-Null
    Write-Output "Registered: $name ($($times -join ', '))"
}

Register-AppTask 'Trading Research Evening Refresh' 'scheduled_refresh.py' '' @('15:45') 20 `
    'Waits for the VIX close, refreshes the app, records paper decisions, commits and pushes data. Log: work\scheduled_refresh.log'
Register-AppTask 'Trading Research Market Snapshots' 'market_snapshot.py' '--scheduled' @('08:00','15:05') 2 `
    'Kalshi perps and macro markets, futures, inflation nowcast. Log: work\market_snapshot.log'
Register-AppTask 'Trading Research Intraday Collection' 'scheduled_collect.py' '' @('09:30','11:30','13:30','14:50','19:10') 4 `
    'Liquidity samples, minute bars, option chains, OCC volume, data backup. Log: work\intraday_collect.log'

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Trading Research Control Panel.lnk'))
$lnk.TargetPath = $pythonw
$lnk.Arguments = "`"$(Join-Path $root 'desktop_app.pyw')`""
$lnk.WorkingDirectory = $root
$lnk.Description = 'Trading Research Control Panel'
$lnk.Save()
Write-Output "Shortcut: $($lnk.FullName)"
