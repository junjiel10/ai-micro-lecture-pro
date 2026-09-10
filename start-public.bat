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
echo   公网上的任何人都能打开这个网址，没有口令就守不住：
echo   别人点「开始制作」烧的是你的电脑和 DeepSeek 额度。
echo.
set /p PW=  请输入口令（直接回车则用 wonderkourse）：

if "%PW%"=="" set PW=wonderkourse

rem ------------------------------------------------------------------
rem  下面两行是公网分享的关键，别删：
rem
rem  ACCESS_PASSWORD     浏览器原生登录框的密码（用户名 demo）
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
start "wk-server" /min cmd /c ".venv\Scripts\python.exe app.py"
timeout /t 5 /nobreak >nul
echo   服务已启动（127.0.0.1:8000）

echo.
echo ------------------------------------------------------------
echo   第 3 步：建立隧道
echo ------------------------------------------------------------
echo   下面会打印一行 https://xxxx.lhr.life —— 那就是分享网址。
echo   把它发给别人，用户名为 demo，口令是你刚设的那个。
echo.
echo   本窗口关闭 = 停止分享（服务窗口会自动一起关掉）
echo ============================================================
echo.

rem 目标是显式写 127.0.0.1 而不是 localhost：
rem Windows 上 localhost 会优先解析成 IPv6 的 ::1，而服务只监听 IPv4，
rem 隧道建起来了请求却转不进去（表现为 Empty reply from server）
rem
rem 想换成 cloudflared（地址同样是随机但更稳）的话，先跑
rem tools\get-cloudflared.bat 下载，再把下面这行换成：
rem    "tools\bin\cloudflared.exe" tunnel --url http://127.0.0.1:8000
ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=20 ^
    -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes ^
    -R 80:127.0.0.1:8000 nokey@localhost.run

echo.
echo 隧道已停止，正在关掉后台服务...
rem 窗口标题特意用 ASCII：中文标题在 GBK/UTF-8 两种代码页下
rem 匹配结果不一样，taskkill 可能杀不掉，留个孤儿进程占着 8000 端口
taskkill /FI "WINDOWTITLE eq wk-server*" /T /F >nul 2>nul
echo 完成。
pause
endlocal
