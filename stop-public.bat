@echo off
chcp 65001 >nul
title 妙课生花 · 停止公网分享
cd /d "%~dp0"

echo ============================================================
echo   妙课生花 WonderKourse · 停止公网分享
echo ============================================================
echo.
echo   会做两件事：
echo     1. 关掉分享用的后台服务（监听 8010 端口的那个）
echo     2. 把隧道脚本窗口也收掉
echo.
echo   注意：只动 8010。你本机自用的那个实例（默认 8000）
echo         不受影响。
echo.

set FOUND=

echo [1/3] 结束占用 8010 端口的进程...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8010 .*LISTENING"') do (
    echo       PID %%p
    taskkill /PID %%p /T /F >nul 2>nul
    set FOUND=1
)
if not defined FOUND echo       没有被占用的 8010。

echo [2/3] 关掉后台服务窗口...
taskkill /FI "WINDOWTITLE eq wk-server*" /T /F >nul 2>nul

echo [3/3] 关掉隧道脚本（powershell 里跑的 tunnel.ps1）...
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe' OR Name='ssh.exe' OR Name='pwsh.exe'\" |" ^
  "  Where-Object { $_.CommandLine -match 'tunnel\.ps1|localhost\.run' } |" ^
  "  ForEach-Object { Write-Host ('       PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo.
echo ============================================================
echo   完成。现在那个分享网址应该已经打不开了。
echo ============================================================
timeout /t 4 >nul
