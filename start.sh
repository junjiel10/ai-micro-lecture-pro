#!/usr/bin/env bash
# 妙课生花 WonderKourse · macOS / Linux 一键启动
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "  妙课生花 WonderKourse  一键启动"
echo "============================================================"

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/3] 创建虚拟环境..."
  python3 -m venv .venv
else
  echo "[1/3] 虚拟环境已存在"
fi

echo "[2/3] 检查并安装依赖..."
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt

echo "[3/3] 启动服务..."
echo
echo "  浏览器打开 http://127.0.0.1:8000"
echo "  （macOS 可执行： open http://127.0.0.1:8000 ）"
echo
.venv/bin/python app.py
