@echo off
chcp 65001 >nul
title 下载 cloudflared（穿透工具）
cd /d "%~dp0.."

echo ============================================================
echo   下载 cloudflared（Cloudflare 官方穿透客户端）
echo ============================================================
echo.
echo   用途：把本机运行的服务通过一条隧道暴露到公网，
echo         别人就能用 https://xxx.trycloudflare.com 访问。
echo.
echo   来源：github.com/cloudflare/cloudflared 官方发布页
echo   体积：约 52 MB，只需下载一次
echo.

if not exist "tools\bin" mkdir "tools\bin"

if exist "tools\bin\cloudflared.exe" (
    echo [提示] tools\bin\cloudflared.exe 已存在，要重新下载吗？
    choice /c YN /n /m "  按 Y 重新下载，按 N 跳过："
    if errorlevel 2 goto done
)

echo.
echo 正在查询最新版本并下载，请稍候（视网速 1~10 分钟）...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "try {" ^
  "  $r = Invoke-RestMethod 'https://api.github.com/repos/cloudflare/cloudflared/releases/latest' -TimeoutSec 60;" ^
  "  $a = $r.assets | Where-Object { $_.name -eq 'cloudflared-windows-amd64.exe' };" ^
  "  if (-not $a) { throw '在最新发布里没找到 windows-amd64 版' }" ^
  "  Write-Host ('  版本 ' + $r.tag_name + '，' + [math]::Round($a.size/1MB,1) + ' MB');" ^
  "  $ProgressPreference='SilentlyContinue';" ^
  "  Invoke-WebRequest $a.browser_download_url -OutFile 'tools\bin\cloudflared.exe' -TimeoutSec 900;" ^
  "} catch { Write-Host ('[错误] ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }"

if errorlevel 1 (
    echo.
    echo   [失败] 下载没成功。常见原因：网络连不上 GitHub。
    echo          可以开代理后再运行一次本脚本。
    pause
    exit /b 1
)

rem 校验：真 exe 的前两个字节是 MZ，且体积应大于 40MB（防止下到错误页）
powershell -NoProfile -Command ^
  "$f = Get-Item 'tools\bin\cloudflared.exe';" ^
  "$b = [System.IO.File]::ReadAllBytes($f.FullName)[0..1];" ^
  "if ($b[0] -ne 0x4D -or $b[1] -ne 0x5A) { Write-Host '[错误] 下到的不是可执行文件' -ForegroundColor Red; exit 1 };" ^
  "if ($f.Length -lt 40MB) { Write-Host '[错误] 文件偏小，可能没下完' -ForegroundColor Red; exit 1 };" ^
  "Write-Host ('  ✅ 校验通过：' + [math]::Round($f.Length/1MB,1) + ' MB')"

if errorlevel 1 (
    del "tools\bin\cloudflared.exe" >nul 2>nul
    echo   [失败] 文件校验不通过，已删除。请重试。
    pause
    exit /b 1
)

echo.
"tools\bin\cloudflared.exe" --version

:done
echo.
echo 完成。现在可以双击 start-public.bat 启动公网分享模式了。
pause
