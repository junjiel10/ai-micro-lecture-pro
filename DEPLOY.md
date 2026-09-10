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

### 方式 C：Hugging Face Spaces（**需要 PRO，$9/月**）

> ⚠️ **HF 已改政策，免费账号不能建 Docker Space**。官方文档原文：
> *"Static Spaces are free for everyone. **Gradio and Docker Spaces run on compute
> and require a paid plan to create: PRO** for personal accounts"。*
> 而 Static Space 只能托管静态文件，跑不了本项目的 Python + FFmpeg。
>
> 免费账号仅在「最多 2 个 ZeroGPU 版 Gradio Space」这一条上例外，
> 但那是给 GPU 短时推理用的，不适合本项目的长时间纯 CPU 任务。

开了 PRO 之后，硬件仍可选**免费**的 CPU Basic（2 vCPU / 16GB），
比 Render 免费档（0.1 CPU / 512MB）强得多。同一支 3 分钟 1080p 成片：

| 平台 | 免费档规格 | 大致耗时 |
|---|---|---|
| Render | 0.1 CPU / 512MB | 约 30 分钟 |
| **HF Spaces** | **2 vCPU / 16GB** | **约 1~2 分钟** |

#### 部署步骤

**1) 建 Space**（浏览器操作，约 1 分钟）

打开 <https://huggingface.co/new-space>（没有账号先注册，免费）：

| 填项 | 值 |
|---|---|
| Space name | `wonderkourse` |
| License | 随便选（如 `mit`） |
| Select the Space SDK | **Docker** → **Blank** |
| Space hardware | **CPU basic · 2 vCPU · 16GB · FREE** |
| Visibility | **Public**（免费档不支持 Private；访问控制靠下面的口令） |

**2) 建一个写入用的 token**

<https://huggingface.co/settings/tokens> → New token → 类型选 **Write** → 复制。

**3) 把代码推上去**

本仓库的 README 头部已经写好了 HF 需要的元信息（`sdk: docker` / `app_port: 8000`），
直接把仓库推成 Space 的 git 仓库即可：

```bash
git remote add hf https://huggingface.co/spaces/<你的用户名>/wonderkourse
git push hf main
# 提示输入账号密码时：用户名填 HF 用户名，密码粘贴上一步的 Write token
```

> 想以后一次 `git push` 同时更新 GitHub 和 HF，可以配双推送：
> ```bash
> git remote set-url --add --push origin https://github.com/<你>/ai-micro-lecture-pro.git
> git remote set-url --add --push origin https://huggingface.co/spaces/<你>/wonderkourse
> ```

**4) 配置两个密钥**（必须做，否则要么没大模型、要么谁都能用）

Space 页面 → **Settings** → **Variables and secrets** → New secret：

| Name | 值 |
|---|---|
| `LLM_API_KEY` | 你的 DeepSeek Key（不填也能跑，只是改用内置脚本引擎） |
| `ACCESS_PASSWORD` | 你自己定的访问口令（建议设，否则任何人都能烧你的额度） |

可选：`ACCESS_USER`（默认 `demo`）、`ALLOW_WEB_SETTINGS=0`。

改完会自动重新构建，等构建完成即可访问。

#### 注意事项

| 事项 | 说明 |
|---|---|
| **访问口令** | Public Space 意味着「网址公开」，但 `ACCESS_PASSWORD` 仍然会把内容挡在门外（浏览器弹原生登录框） |
| **会休眠** | 免费 Space 闲置约 48 小时后休眠，下次访问等约 1 分钟冷启动 |
| **磁盘是临时的** | 重启后 `output/` 清空，成片记得及时下载 |
| **本地文件系统** | 容器默认可能以非 root 用户运行，`Dockerfile` 里已把 `/app/output` 设为可写 |

#### 如果 Space 报「应用启动失败」

项目除 `/api/health` 外全部需要口令，返回 401。
绝大多数情况平台只检查端口是否响应，不受影响；万一它要求首页返回 200，
把 `app.py` 里 `_access_gate` 的放行条件加上 `or request.url.path == "/"` 即可。

### 方式 D：用自己电脑当服务器 + 免费内网穿透（零成本、最快）

本机出一支 3 分钟成片只要**约 70 秒**（比 Render 免费档快约 25 倍），
所以「本机跑 + 穿透一个公网地址」是演示场景里最划算的方案。

仓库里已备好两个双击即用的脚本：

| 脚本 | 作用 |
|---|---|
| `tools\get-cloudflared.bat` | 下载穿透工具（约 52MB，只需一次） |
| `start-public.bat` | 一键分享：提示输入口令 → 启服务 → 建隧道 → 打印网址 |

手工做法也可以（等价于脚本里干的事）：

```powershell
# 终端 1：启动服务（注意这两个环境变量，见下方警告）
$env:ALLOW_WEB_SETTINGS='0'
$env:ACCESS_PASSWORD='自己定的口令'
.\.venv\Scripts\python.exe app.py

# 终端 2：建立隧道
tools\bin\cloudflared.exe tunnel --url http://127.0.0.1:8000
```

拿到形如 `https://xxxx.trycloudflare.com` 的地址就能分享出去。

| | 说明 |
|---|---|
| 优点 | 零成本、速度最快（用你本机的 CPU 与内存） |
| 缺点 | **电脑必须开着**，休眠 / 关机链接就失效 |
| 适合 | 课堂演示、答辩、临时给几个人试用 |

> ### ⚠️ 走隧道必须关掉「网页端改配置」
>
> 程序判断「能否改配置」的依据是**服务是不是只监听本机**（`127.0.0.1`）。
> 走隧道时服务**仍然监听 127.0.0.1**，程序会以为很安全，但外面其实已经能进来了。
>
> 结果是：任何拿到网址的人都能调 `POST /api/settings/llm`，把 `LLM_BASE_URL`
> 改到自己的服务器，**把你真实的 API Key 接走**。
>
> 所以 `start-public.bat` 会自动设好 `ALLOW_WEB_SETTINGS=0`，
> 手工启动时千万别忘了这一条。
>
> 顺带解释一个常见疑问：Render 上那个设置面板点不动，是因为那边监听的是
> `0.0.0.0`，程序判断「这是公网环境」自动禁用了——**那是设计如此，不是坏了**。

### 方式 E：Railway / 其他支持 Dockerfile 的平台

只要平台支持「用 Dockerfile 构建」就能跑，把端口对上即可
（平台注入 `PORT` 时会自动覆盖镜像里的默认值）。

### 方式 E：Railway / 其他支持 Dockerfile 的平台

只要平台支持「用 Dockerfile 构建」就能跑，把端口对上即可
（平台注入 `PORT` 时会自动覆盖镜像里的默认值）。

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
| **Hugging Face PRO** | **2 vCPU / 16GB** | **约 1~2 分钟**（$9/月，但 CPU 是 Render Starter 的 4 倍、内存 32 倍） |

**只想免费又要快 → 用你自己的电脑跑 + 免费内网穿透**（见下方方式 D）。

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
