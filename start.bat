@echo off
chcp 65001 >nul
title 妙课生花 WonderKourse
cd /d "%~dp0"

echo ============================================================
echo   妙课生花 WonderKourse  一键启动
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有找到 Python，请先安装 Python 3.10 以上版本
    echo        安装时记得勾选 "Add Python to PATH"
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 首次运行，正在创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
) else (
    echo [1/3] 虚拟环境已存在
)

echo [2/3] 检查并安装依赖（首次约 1~3 分钟，之后会很快）...
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络连接
    pause
    exit /b 1
)

echo [3/3] 启动服务...
echo.
echo   浏览器将自动打开 http://127.0.0.1:8000
echo   关闭本窗口即可停止服务
echo.
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" app.py

pause
