# 部署到公网（让别人打开链接就能用）

本机运行请看 [README](README.md)；这份文档只讲怎么把它放到服务器上。

---

## 0. 先搞清楚这东西为什么不能放 GitHub Pages

妙课生花不是静态网页，它要 **Python + FFmpeg 真的在服务器上跑**才能出片。
GitHub Pages 只能托管 HTML/CSS/JS，放上去打开会显示「服务未连接」。
所以正确姿势是：

```
GitHub 仓库存代码   →   云平台拉取并运行（Docker）   →   给你一个可访问的网址
```

本仓库已经准备好 `Dockerfile` 和 `render.yaml`，不需要你写运维配置。

---

## 1. 需要设置的环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `LLM_API_KEY` | 推荐 | DeepSeek 等大模型的 Key。**不填也能跑**，只是脚本改用内置教学引擎，内容会朴素一些 |
| `LLM_BASE_URL` | 否 | 默认 `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 否 | 默认 `deepseek-chat` |
| `ACCESS_PASSWORD` | **强烈建议** | 设置后启用访问口令（见下一节） |
| `ACCESS_USER` | 否 | 口令对应的用户名，默认 `demo` |
| `HOST` | 是 | 填 `0.0.0.0`（表示对外监听）。`render.yaml` 已自动带上 |
| `PORT` | 否 | 云平台通常自动注入，不用管 |
| `ALLOW_WEB_SETTINGS` | 否 | 线上建议 `0`，禁止网页端改服务器配置 |

> **绝对不要把 `.env` 提交到仓库。** 本仓库的 `.gitignore` 已经排除它，
> `Dockerfile` 的 `.dockerignore` 也排除了，Key 只应该存在云平台的环境变量里。

---

## 2. 关于访问口令（重要）

不设 `ACCESS_PASSWORD` 的话，**任何拿到你网址的人都能点「开始制作」**，
消耗你的服务器 CPU 和 DeepSeek 额度。

设了之后走 HTTP Basic 认证 —— 浏览器会弹一个原生登录框，不需要额外登录页：

```
用户名：ACCESS_USER 的值（默认 demo）
密码：  ACCESS_PASSWORD 的值
```

例外：`/api/health` 不做校验。它只有版本号、模型名、字体名这类信息，
不含任何密钥，而云平台要靠它判断容器是否健康（被 401 挡住会被反复重启）。

---

## 3. 部署方式

### 方式 A：Render（有免费档，最省事，推荐）

1. 把仓库推到 GitHub（公开或私有都行）。
2. 打开 <https://render.com> 用 GitHub 登录。
3. **New → Blueprint** → 选中这个仓库 → Render 会读到 `render.yaml` 自动建服务。
4. 弹出输入框时填 `LLM_API_KEY` 和 `ACCESS_PASSWORD`（这两个标了 `sync: false`，
   意思是不写进仓库、由你在面板上填）。
5. 等构建完成，拿到形如 `https://wonderkourse.onrender.com` 的网址。

如果要改内存规格，在 `render.yaml` 里把 `plan: free` 改成 `starter`。

### 方式 B：任何支持 Docker 的服务器

```bash
git clone <你的仓库地址> && cd ai-micro-lecture-pro
docker build -t wonderkourse .
docker run -d --name wonderkourse -p 80:8000 \
  -e HOST=0.0.0.0 \
  -e LLM_API_KEY=sk-xxxx \
  -e ACCESS_USER=demo \
  -e ACCESS_PASSWORD=换个长口令 \
  -v wonderkourse-output:/app/output \
  wonderkourse
```

`-v` 挂一个卷，容器重建时已生成的成片不会丢。

### 方式 C：Hugging Face Spaces / Railway 等

只要平台支持「用 Dockerfile 构建」就能跑，把端口对上即可。
HF Spaces 免费档给的内存更大（适合出 1080p 长片），但容器端口要改成 `7860`：

```bash
docker run -e PORT=7860 ...
```

---

## 4. 免费档够不够用：实测数据

Render 免费实例是 **0.1 CPU / 512 MB**（官方定价页原文：`free: 0.1 CPU / 512 MB RAM`）。
本项目在「约 3 分钟 / 横版 1080p」下的实测开销：

| 环节 | 峰值内存 | 说明 |
|---|---|---|
| Python 主进程 | 171 MB | 含画面渲染、背景音乐合成、事件流 |
| 单个 ffmpeg | 310 MB | 烧字幕时整片重编码，是最重的单次调用 |
| **合计（保守相加）** | **481 MB** | 512MB 限额之内，但余量不大 |

> 这两个峰值**不在同一时刻**：Python 的峰值出现在画面/音乐生成阶段，
> ffmpeg 的峰值出现在剪辑阶段，所以实际占用比 481MB 更宽松一些。

**为了让它能塞进 512MB，代码里做了三件事**（改动前会直接 OOM 被杀）：

1. **编码 preset 用 `veryfast`**，不用 `medium`
   画面是「静止图片 + 定格」，没有运动搜索的价值。实测同一镜头：
   `medium` 5.0s / 峰值 683MB，`veryfast` 2.9s / 471MB，画质肉眼无差。
2. **按 cgroup 限额限制 x264 线程数**（`config.ffmpeg_threads()`）
   x264 默认按「宿主机核数」开线程，容器里会误判成 8~32 核，每个线程都要
   缓存整帧 1080p。实测：自动线程 683MB → 2 线程 337MB → 1 线程 290MB。
3. **背景音乐合成改为分块**（`music.build_bgm`）
   原来 `stereo * 32767` → `clip` → `astype` 会同时产生三个 75MB 的 float64
   大数组，106 秒音频峰值 244MB；改成分块写入 int16 后降到 125MB。

### 但 CPU 是另一个瓶颈

0.1 CPU 只有普通笔记本单核的十分之一左右。同样一支 3 分钟 1080p 成片：

| 方案 | 规格 | 大致耗时 |
|---|---|---|
| Render Free | 0.1 CPU / 512MB | **约 30 分钟** |
| Render Starter | 0.5 CPU / 512MB | 约 6 分钟（内存仍是 512MB，余量很小） |
| Render Standard | 1 CPU / 2GB | 约 3 分钟 |
| Hugging Face Spaces | 2 vCPU / 16GB | **约 1~2 分钟（免费档最划算）** |

**只想免费又要快 → 用 HF Spaces**（把端口改成 `7860` 即可，见上面方式 C）。

### 另外两件事

| 事项 | 说明 | 对策 |
|---|---|---|
| **会休眠** | 免费实例闲置约 15 分钟后休眠，下次访问要等 30~60 秒冷启动 | 属正常现象；介意就升配 |
| **磁盘是临时的** | 重新部署 / 重启后 `output/` 清空，之前生成的成片会消失 | 及时下载 MP4；或挂持久卷（方式 B 的 `-v`） |

---

## 5. 出问题先查这几条

**画面 / 字幕里的中文变成方块（□□□）**
镜像没装中文字体。确认 `Dockerfile` 里的 `fonts-noto-cjk` 装上了，
启动日志会打印实际用到的字体名。

**字幕完全不显示**
启动日志里看 `FFmpeg` 那行，必须是带 `libass` 的构建。
`imageio-ffmpeg` 自带的二进制默认支持；用自编译 ffmpeg 时容易漏掉。

**部署成功但打开是 502 / 服务未启动**
多半是端口没对上：应用必须监听 `0.0.0.0` 和平台注入的 `PORT`。
本项目 `app.py` 已经读 `HOST` / `PORT` 两个变量。

**网页端「⚙ 大模型设置」保存失败**
线上默认禁止（`web_settings_allowed()` 返回 False），
请改到平台的环境变量里设置 Key。这是有意为之的安全设计。

---

## 6. 想改回本机运行

云上的环境变量不会影响本机。本机直接：

```powershell
.\.venv\Scripts\python.exe app.py
# 默认监听 127.0.0.1:8000，且允许网页端改配置
```
