@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   Rima backend + Cloudflare tunnel
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv\Scripts\python.exe not found. Run this from the project
    echo folder, after creating the virtual environment.
    pause
    exit /b 1
)

where cloudflared >nul 2>&1
if errorlevel 1 (
    echo ERROR: cloudflared.exe was not found on PATH. Install it first.
    pause
    exit /b 1
)

if not exist logs mkdir logs

echo Stopping any backend/tunnel already running from a previous run...
powershell -NoProfile -Command "Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force" >nul 2>&1
powershell -NoProfile -Command "foreach ($c in @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) { $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; if ($p -and $p.ProcessName -match '^(python|pythonw|uvicorn)') { Stop-Process -Id $p.Id -Force } elseif ($p) { Write-Host ('Port 8000 is used by ' + $p.ProcessName); exit 3 } }"
if errorlevel 3 goto portbusy
del /q logs\backend.log >nul 2>&1
del /q logs\tunnel.log >nul 2>&1

echo.
echo Starting the backend on port 8000...
start "Rima Backend" /MIN cmd /c "".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000 > logs\backend.log 2>&1"

echo Waiting for the backend to answer...
set /a BACKEND_TRIES=0
:waitbackend
set /a BACKEND_TRIES+=1
if !BACKEND_TRIES! gtr 30 (
    echo.
    echo ERROR: the backend did not come up within 60 seconds.
    echo Check logs\backend.log for what went wrong.
    pause
    exit /b 1
)
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8000/health).StatusCode } catch { 0 }" > logs\_health.tmp 2>nul
set /p HEALTH=<logs\_health.tmp
if not "%HEALTH%"=="200" (
    "%SystemRoot%\System32\timeout.exe" /t 2 /nobreak >nul
    goto waitbackend
)
echo Backend is up.

echo.
echo Starting the Cloudflare tunnel...
start "Rima Tunnel" /MIN cmd /c "cloudflared tunnel --url http://127.0.0.1:8000 > logs\tunnel.log 2>&1"

echo Waiting for the tunnel link (this can take up to a minute)...
set TUNNEL_URL=
set /a TUNNEL_TRIES=0
:waittunnel
set /a TUNNEL_TRIES+=1
if !TUNNEL_TRIES! gtr 40 (
    echo.
    echo ERROR: no tunnel link appeared within 80 seconds.
    echo Check logs\tunnel.log for what went wrong.
    pause
    exit /b 1
)
for /f "usebackq tokens=*" %%A in (`powershell -NoProfile -Command "if (Test-Path logs\tunnel.log) { $m = Select-String -Path logs\tunnel.log -Pattern 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' | Select-Object -First 1; if ($m) { $m.Matches[0].Value } }"`) do set TUNNEL_URL=%%A
if "!TUNNEL_URL!"=="" (
    "%SystemRoot%\System32\timeout.exe" /t 2 /nobreak >nul
    goto waittunnel
)

echo.
echo ============================================================
echo   Ready. Put this address in the app's server settings:
echo.
echo   !TUNNEL_URL!
echo.
echo   This link has no login - anyone who has it can read and
echo   write your real accounting data. Don't share it further,
echo   and keep this window open only as long as you need it.
echo ============================================================
echo.
echo Press any key in this window to STOP the backend and the tunnel.
pause >nul

echo.
echo Stopping the backend and the tunnel...
powershell -NoProfile -Command "Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force" >nul 2>&1
powershell -NoProfile -Command "foreach ($c in @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) { $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; if ($p -and $p.ProcessName -match '^(python|pythonw|uvicorn)') { Stop-Process -Id $p.Id -Force } }" >nul 2>&1
echo Done.
"%SystemRoot%\System32\timeout.exe" /t 2 /nobreak >nul
endlocal
exit /b 0

:portbusy
echo.
echo ERROR: port 8000 is already used by another program ^(for example Docker^).
echo Stop that program first, then run this file again.
pause
exit /b 1
