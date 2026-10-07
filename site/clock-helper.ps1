<#
  DRG clock helper - lets the "Set PC clock" buttons of the DRG Double XP site set this PC's clock.
  Windows only. Nothing is sent over the network.

  Install (once):
    powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\clock-helper.ps1"
  Uninstall:
    powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\clock-helper.ps1" -Uninstall

  What it installs, and nothing else:
    1. A "drgtime://" link handler for your Windows user (registry key HKCU\Software\Classes\drgtime).
       It runs %LOCALAPPDATA%\DrgClock\drgtime-link.ps1, which checks the link, writes a one-line
       request file and starts the scheduled task below.
    2. A scheduled task "DrgClock-Set" (on demand only, your account only, highest privileges) that
       runs "C:\Program Files\DrgClock\set-time.ps1". That folder is writable by administrators only.
       The task script re-checks the request and accepts nothing but:
         "set <UTC time>"  a time between 2020 and 2035: stops Windows Time sync and sets the clock
         "reset"           resumes Windows Time sync and resyncs the clock
  Requires the administrator account you are logged in with.
#>
param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'

$taskName  = 'DrgClock-Set'
$adminDir  = Join-Path $env:ProgramFiles 'DrgClock'
$userDir   = Join-Path $env:LOCALAPPDATA 'DrgClock'
$request   = Join-Path $userDir 'request.txt'
$regKey    = 'HKCU:\Software\Classes\drgtime'

$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Administrator rights are needed once. Accept the Windows prompt...'
    $again = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    if ($Uninstall) { $again += '-Uninstall' }
    Start-Process -FilePath 'powershell.exe' -ArgumentList $again -Verb RunAs
    exit
}

function Remove-Installation($task, $key, $folders) {
    Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $key) { Remove-Item -LiteralPath $key -Recurse -Force }
    foreach ($folder in $folders) {
        if (Test-Path -LiteralPath $folder) { Remove-Item -LiteralPath $folder -Recurse -Force }
    }
}

if ($Uninstall) {
    Remove-Installation $taskName $regKey @($adminDir, $userDir)
    Start-Service -Name w32time -ErrorAction SilentlyContinue
    Write-Host 'DRG clock helper removed. Windows Time sync is running again.'
    Read-Host 'Press Enter to close'
    exit
}

# ---- Script run by the scheduled task (administrator) ----
$setTimeScript = @'
param([Parameter(Mandatory = $true)][string]$Request)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Request)) { exit 1 }
$line = (Get-Content -LiteralPath $Request -Raw).Trim()
Remove-Item -LiteralPath $Request -Force

if ($line -eq 'reset') {
    Start-Service -Name w32time -ErrorAction SilentlyContinue
    & w32tm.exe /resync /force | Out-Null
    exit 0
}
if ($line -cmatch '^set (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)$') {
    $style  = [Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal
    $target = [DateTime]::ParseExact($Matches[1], "yyyy-MM-dd'T'HH:mm:ss'Z'", [Globalization.CultureInfo]::InvariantCulture, $style)
    if ($target.Year -lt 2020 -or $target.Year -gt 2035) { exit 1 }
    Stop-Service -Name w32time -ErrorAction SilentlyContinue
    Set-Date -Date $target.ToLocalTime() | Out-Null
    exit 0
}
exit 1
'@

# ---- Script run by the drgtime:// link (your user, no special rights) ----
$linkScript = @'
param([string]$Url)
$Url = $Url -replace '%3A', ':'
$dir = Join-Path $env:LOCALAPPDATA 'DrgClock'
if ($Url -match '(?i)^drgtime://set/?\?t=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)/?$') {
    $line = 'set ' + $Matches[1].ToUpperInvariant()
} elseif ($Url -match '(?i)^drgtime://reset/?$') {
    $line = 'reset'
} else {
    exit 1
}
Set-Content -LiteralPath (Join-Path $dir 'request.txt') -Value $line -Encoding ASCII
Start-ScheduledTask -TaskName 'DrgClock-Set'
'@

# Administrator-only folder for the elevated script (a script the user can modify would be a privilege hole).
New-Item -ItemType Directory -Path $adminDir -Force | Out-Null
& icacls.exe $adminDir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null
New-Item -ItemType Directory -Path $userDir -Force | Out-Null
Set-Content -LiteralPath (Join-Path $adminDir 'set-time.ps1') -Value $setTimeScript -Encoding UTF8
Set-Content -LiteralPath (Join-Path $userDir 'drgtime-link.ps1') -Value $linkScript -Encoding UTF8

# drgtime:// link handler
New-Item -Path $regKey -Force | Out-Null
Set-ItemProperty -Path $regKey -Name '(default)' -Value 'URL:DRG clock helper'
New-ItemProperty -Path $regKey -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
New-Item -Path "$regKey\shell\open\command" -Force | Out-Null
$command = 'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" "%1"' -f (Join-Path $userDir 'drgtime-link.ps1')
Set-ItemProperty -Path "$regKey\shell\open\command" -Name '(default)' -Value $command

# On-demand scheduled task with highest privileges
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Request "{1}"' -f (Join-Path $adminDir 'set-time.ps1'), $request)
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
Register-ScheduledTask -TaskName $taskName -Action $action -Principal $taskPrincipal -Settings $settings -Force | Out-Null

# Self-test with a harmless "reset" request (resyncs the clock, does not move it anywhere)
Set-Content -LiteralPath $request -Value 'reset' -Encoding ASCII
Start-ScheduledTask -TaskName $taskName
$worked = $false
foreach ($i in 1..10) {
    Start-Sleep -Milliseconds 500
    if (-not (Test-Path -LiteralPath $request)) { $worked = $true; break }
}
if ($worked) {
    Write-Host 'Installed. Self-test OK.' -ForegroundColor Green
    Write-Host 'Go back to the site and press "Set PC clock" on a mission.'
    Write-Host 'Your browser will ask once whether to open the helper: allow it.'
} else {
    Write-Warning 'Installed, but the self-test failed: the scheduled task did not run.'
}
Read-Host 'Press Enter to close'
