# Recreates the app's Windows scheduled tasks and the desktop shortcut for the signed-in user.
# Run from the project folder after .venv exists:  powershell -ExecutionPolicy Bypass -File .\setup_windows_tasks.ps1
# Times are the computer's local time (US Central). Triggers start tomorrow so nothing fires during setup.
# Settings: start late if missed, run on battery, wake the computer to run (since 2026-11-13),
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
    $triggers = @(foreach ($t in $times) { New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At ($start + [TimeSpan]::Parse($t)) })
    # Also two minutes after sign-in (user, 2026-11-13): after a night with the laptop off, each job catches up
    # as soon as the user is back in. Each script decides what to do from the time of day, so this is safe.
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $user
    $logon.Delay = 'PT2M'
    $triggers += $logon
    # -WakeToRun (2026-11-13): the old laptop slept through every daytime run. Windows only honours it when the
    # power plan's "Allow wake timers" is Enabled (Control Panel > Power Options > Sleep); the user sets that.
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
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
Register-AppTask 'Trading Research Intraday Collection' 'scheduled_collect.py' '' @('09:00','09:30','11:30','13:30','14:50','19:10') 4 `
    'Same-day option snapshots, liquidity samples, pre-close check, minute bars, option chains, OCC volume, data backup. Log: work\intraday_collect.log'

# Dashboard server at sign-in, so the page is there without opening the control panel.
$dash = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$(Join-Path $root 'start_dashboard.py')`"" -WorkingDirectory $root
Register-ScheduledTask -TaskName 'Trading Research Dashboard' -Action $dash -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $user) `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5)) `
    -Principal (New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited) `
    -Description 'Starts the local dashboard server (start_dashboard.py). It never refreshes data.' -Force | Out-Null
Write-Output 'Registered: Trading Research Dashboard (at sign-in)'

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Trading Research Control Panel.lnk'))
$lnk.TargetPath = $pythonw
$lnk.Arguments = "`"$(Join-Path $root 'desktop_app.pyw')`""
$lnk.WorkingDirectory = $root
$lnk.IconLocation = "$(Join-Path $root 'assets\app.ico'),0"
$lnk.Description = 'Trading Research Control Panel'
$lnk.Save()
Write-Output "Shortcut: $($lnk.FullName)"
