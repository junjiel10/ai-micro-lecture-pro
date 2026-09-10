@echo off
chcp 65001 >nul
title 妙课生花 · 公网分享模式（本机跑 + SSH 隧道）
cd /d "%~dp0"
setlocal

echo ============================================================
echo   妙课生花 WonderKourse · 公网分享模式
echo   程序跑在你自己电脑上，通过 SSH 反向隧道给公网一个网址
echo ============================================================
echo.
echo   优点：出片速度用你本机的 CPU（约 70 秒/支，比 Render 免费档快 20 多倍）
echo         不需要下载任何额外软件（用的是 Windows 自带的 ssh）
echo   代价：这个窗口关掉，网址就失效（电脑必须开着）
echo.
echo   注意：免费隧道的网址是随机的，而且每开一次换一个，
echo         重连后地址还可能轮换。变了就重新运行本脚本取新地址。
echo.

where ssh >nul 2>nul
if errorlevel 1 (
    echo   [!] 没找到 ssh。请在「设置 → 应用 → 可选功能」里
    echo       添加「OpenSSH 客户端」，然后重新运行本脚本。
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo   [!] 没找到虚拟环境，请先双击 start.bat 完成首次安装
    echo.
    pause
    exit /b 1
)

echo ------------------------------------------------------------
echo   第 1 步：设一个访问口令
echo ------------------------------------------------------------
echo   浏览不用口令：拿到网址的人可以直接看首页、看指南、
echo   播你已做好的示例作品。
echo.
echo   只有点「开始制作」时才会弹框要口令 —— 因为那一刻开始
echo   真烧你电脑的 CPU 和 DeepSeek 额度，得拦一下。
echo.
set /p PW=  请输入口令（直接回车则用 wonderkourse）：

if "%PW%"=="" set PW=wonderkourse

rem ------------------------------------------------------------------
rem  下面两行是公网分享的关键，别删：
rem
rem  ACCESS_PASSWORD     访问口令。别人打开站点会先看到登录页，
rem                     输入这个口令才能进（页面上不用填用户名）。
rem
rem  ALLOW_WEB_SETTINGS  关掉网页端「大模型设置」的写入。
rem      为什么必须显式关：程序判断"能否改配置"的依据是
rem      「服务是不是只监听本机」。走隧道时服务仍然监听 127.0.0.1，
rem      程序会以为很安全，可实际上外面已经能进来了 —— 拿到网址的人
rem      可以把接口地址改到自己的服务器，把你的 API Key 套走。
rem ------------------------------------------------------------------
set ACCESS_USER=demo
set ACCESS_PASSWORD=%PW%
set ALLOW_WEB_SETTINGS=0

echo.
echo ------------------------------------------------------------
echo   第 2 步：启动服务
echo ------------------------------------------------------------
rem 刻意用一个独立端口（8010）而不是默认的 8000。
rem 8000 很可能是你自己那个「本机自用」实例在用 —— 那边没有口令。
rem 一旦撞上，本脚本的服务会启动失败，而隧道却会把你那个
rem 没口令的实例暴露到公网上去。用独立端口就没这个隐患。
set HOST=127.0.0.1
set PORT=8010

netstat -ano | findstr /r /c:":8010 .*LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo   [!] 端口 8010 已被占用，可能是上次的分享没退干净。
    echo       双击 stop-public.bat 清一下，或者重启电脑后再试。
    echo.
    pause
    exit /b 1
)

start "wk-server" /min cmd /c ".venv\Scripts\python.exe app.py"

rem 等服务真的就绪（最多 20 秒），而不是死等 5 秒
set READY=
set /a TRIES=0
:waitup
set /a TRIES+=1
curl.exe -s -o NUL --max-time 2 "http://127.0.0.1:8010/api/health"
if not errorlevel 1 set READY=1
if defined READY goto up
if %TRIES% geq 20 goto upfail
timeout /t 1 /nobreak >nul
goto waitup

:upfail
echo.
echo   [!] 服务没起来。看一下那个最小化的 wk-server 窗口里报了什么错。
echo.
pause
exit /b 1

:up
echo   服务已就绪（127.0.0.1:8010）。

echo.
echo ------------------------------------------------------------
echo   第 3 步：建立隧道（自带保活与断线重连）
echo ------------------------------------------------------------
echo   下面会大字打印分享网址。
echo.
echo   两个关键点，解释一下为什么值得等：
echo     · 免费匿名隧道有「闲置超时」—— 一段时间没流量经过就会被

echo       服务端掉断（实测就是这样掉的），所以脚本每 60 秒探一次活。
echo     · 真断了会自动重连，但重连后网址会变，以新打印的为准。
echo.
echo   本窗口关掉 = 停止分享。
echo ============================================================
echo.

if not exist "tools\tunnel.ps1" (
    echo   [!] 没找到 tools\tunnel.ps1，无法建隧道。
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\tunnel.ps1" -Port 8010

echo.
echo 隧道已停止，正在关掉后台服务...
rem 窗口标题特意用 ASCII：中文标题在 GBK/UTF-8 两种代码页下
rem 匹配结果不一样，taskkill 可能杀不掉，留个孤儿进程占着端口
taskkill /FI "WINDOWTITLE eq wk-server*" /T /F >nul 2>nul
rem 兜底：万一窗口标题没匹配上，直接按端口找进程
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8010 .*LISTENING"') do taskkill /PID %%p /T /F >nul 2>nul
echo 完成。
pause
endlocal
