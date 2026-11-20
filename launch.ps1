# Start Reroll if it is not already up, then open it in an app window.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Reroll {
    try {
        $request = [System.Net.WebRequest]::Create("http://127.0.0.1:8000/api/health")
        $request.Timeout = 400
        $request.Method = "GET"
        $response = $request.GetResponse()
        $response.Close()
        return $true
    } catch {
        return $false
    }
}

function Show-Fail([string]$message) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($message, "Reroll") | Out-Null
}

if (-not (Test-Reroll)) {
    $python = $null
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        $pythonw = Join-Path (Split-Path $cmd.Source) "pythonw.exe"
        if (Test-Path $pythonw) { $python = $pythonw } else { $python = $cmd.Source }
    }
    if (-not $python) {
        Show-Fail "Python was not found on PATH, so Reroll could not start."
        exit 1
    }
    $log = Join-Path $env:TEMP "reroll-launch.log"
    $err = Join-Path $env:TEMP "reroll-launch.err"
    Start-Process -FilePath $python -ArgumentList "-m","uvicorn","backend.app:app","--host","127.0.0.1","--port","8000" -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err
    $deadline = (Get-Date).AddSeconds(40)
    while ((Get-Date) -lt $deadline -and -not (Test-Reroll)) {
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-Reroll)) {
        $detail = ""
        if (Test-Path $log) { $detail = Get-Content -Path $log -Raw -ErrorAction SilentlyContinue }
        if (Test-Path $err) { $detail += Get-Content -Path $err -Raw -ErrorAction SilentlyContinue }
        Show-Fail "Reroll did not start.`r`n`r`n$detail"
        exit 1
    }
}

$edge = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $edge) {
    Show-Fail "Microsoft Edge was not found, so the Reroll window could not open."
    exit 1
}

$profile = Join-Path $env:LOCALAPPDATA "Reroll\edge"
New-Item -ItemType Directory -Force -Path $profile | Out-Null
$edgeArgs = "--app=http://127.0.0.1:8000 --user-data-dir=`"$profile`" --window-size=1280,800"
Start-Process -FilePath $edge -ArgumentList $edgeArgs
