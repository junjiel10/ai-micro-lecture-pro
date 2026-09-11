@echo off
chcp 65001 >nul
title 妙课生花 · 发布成片到云端
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "tools\publish-example.ps1" %*

echo.
pause
