# 妙课生花 WonderKourse · 云部署镜像
#
# 为什么需要 Docker：这个项目不是纯静态网页，
# 它要跑 Python + ffmpeg 才能出片，而且必须自带中文字体，
# 否则画面和字幕里的中文会全变成「豆腐块」。
#
#   docker build -t wonderkourse .
#   docker run -p 8000:8000 -e LLM_API_KEY=sk-xxx wonderkourse
#
FROM python:3.12-slim

# ----------------------------------------------------------------------
# 中文字体（关键！）
#   slides.py / agents.py 用 Pillow 直接画中文，Linux 基础镜像默认没有中文字体；
#   fonts-noto-cjk 同时提供 /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc，
#   这个路径已经写在 config._FONT_CANDIDATES 里，装完就能被自动找到。
#   fonts-dejavu-core 负责 ▶ ◎ ★ 这类符号字形。
# ----------------------------------------------------------------------
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        fonts-noto-cjk \
        fonts-dejavu-core \
        fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app

# 依赖单独一层，改代码时不用重装依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 云平台会注入 PORT；HOST=0.0.0.0 表示对外监听
ENV HOST=0.0.0.0 \
    PORT=8000

# 出片产物写在 output/ 里，给它一个可写目录
RUN mkdir -p /app/output
VOLUME ["/app/output"]

EXPOSE 8000

# 用 app.py 启动：它会读 HOST / PORT，并打印字体与 ffmpeg 自检信息
CMD ["python", "app.py"]
