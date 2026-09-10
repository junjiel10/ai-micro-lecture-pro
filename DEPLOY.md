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
| `ACCESS_PASSWORD` | **强烈建议** | 设置后：浏览全开，但「开始创作」需要口令 |
| `ACCESS_USER` | 否 | `curl -u 用户名:口令` 里的用户名，默认 `demo`（浏览器里不需要用） |
| `HOST` | 是 | 填 `0.0.0.0`（表示对外监听）。`render.yaml` 已自动带上 |
| `PORT` | 否 | 云平台通常自动注入，不用管 |
| `ALLOW_WEB_SETTINGS` | 否 | 线上建议 `0`，禁止网页端改服务器配置 |

> **绝对不要把 `.env` 提交到仓库。** 本仓库的 `.gitignore` 已经排除它，
> `Dockerfile` 的 `.dockerignore` 也排除了，Key 只应该存在云平台的环境变量里。

---

## 2. 关于访问口令（重要）

设计取向是 **浏览完全开放，创作才要口令**：

| | 要不要口令 | 为什么 |
|---|---|---|
| 首页 / 使用指南 / 创作台界面 | 不要 | 让人先看明白这是什么、能干什么 |
| 示例作品、历史项目、成片与字幕 | 不要 | 这些都是已经做好的东西，看着不花钱 |
| **开始制作** | **要** | 会真吃 CPU（逐镜渲染 + 剪辑合成）和大模型额度 |
| 修改后重做 / 取消任务 | 要 | 同上，重做等于再跑一遍 |
| 删除作品 | 要 | 防人把作品删了 |
| 写大模型配置 | 要 | 否则能把 `LLM_BASE_URL` 改到自己服务器上把 Key 接走 |

不设 `ACCESS_PASSWORD` 的话上表最后一栏全部失效 —— **任何拿到你网址的人
都能点「开始制作」**，烧的是你的 CPU 和 DeepSeek 额度。

设了之后：访客点「开始制作」时会弹一个口令框，输对了才继续，
输对了之后 30 天内不再问。

> ### 为什么不用 HTTP Basic 认证浏览器原生登录框
>
> 我们最初就是那么做的，然后踩了坑：那个弹窗**完全依赖浏览器的实现**。
> VS Code 内置浏览器、各类 App 的 webview、部分手机浏览器压根不弹，
> 用户只会看到一行 401 的纯文本「需要访问口令」，
> **页面上没有任何地方能输入**，完全没法用。
> 所以改成自己的弹窗 + 独立登录页，每个浏览器都一样能用。
>
> Basic 认证仍然**兼容保留**（`curl -u demo:口令`），方便脚本和命令行调用。

其他细节：

| 行为 | 说明 |
|---|---|
| 口令入口 ① | 点「开始制作」时自动弹出（主要方式） |
| 口令入口 ② | 顶栏右侧的按钮。未通过时显示「输入口令」，通过后变「退出登录」 |
| 口令入口 ③ | 直接打开 `/login`，有独立的整页登录表单 |
| 退出 | 访问 `/logout`，或点顶栏的「退出登录」 |
| 会话时长 | 30 天；**改口令会立即失效所有旧会话**（令牌是口令派生的） |
| 跨重启 | Cookie 由口令派生，服务重启后仍然有效（Render 免费档爱休眠，这点很重要） |
| 防暴力破解 | 同一 IP 连续错 10 次锁 10 分钟（锁不影响浏览） |
| 永远免口令 | `/login`、`/logout`、`/api/auth`、`/api/health`、`/favicon.ico`、`/static/logo.svg` |

两个如实说明的边界：

- **退出登录后旧 Cookie 在服务重启前一直有效。** 因为令牌是口令派生的、
  服务端无状态（就是为了跨重启），登出只是把这个令牌记入内存里的黑名单。
  重启会丢掉黑名单。要一次性踢掉所有人，**改口令**最彻底。
- **上传接口不要口令**（它很轻）。为此加了 30 MB 单文件上限，
  免得有人丢个大文件把内存吃光（免费档只有 512MB）。

`/api/health` 也不做校验：它只有版本号、模型名、字体名这类信息，
不含任何密钥，而云平台要靠它判断容器是否健康（被 401 挡住会被反复重启）。

> 提示：部署上线的站点，**大模型设置页会返回 403**（不让网页改配置，
> 否则拿到网址的人能把 `LLM_BASE_URL` 改到自己服务器上把 Key 接走）。
> 需要改 Key 请改平台的环境变量。详见方式 D 末尾的警告块。

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
| **访问口令** | Public Space 意味着「网址公开」。但因为浏览本来就是开放的，口令只卡在「开始创作」那一步，所以公开反而是没关系的 |
| **会休眠** | 免费 Space 闲置约 48 小时后休眠，下次访问等约 1 分钟冷启动 |
| **磁盘是临时的** | 重启后 `output/` 清空，成片记得及时下载 |
| **本地文件系统** | 容器默认可能以非 root 用户运行，`Dockerfile` 里已把 `/app/output` 设为可写 |

#### 如果 Space 报「应用启动失败」

首页 `/` 和 `/api/health` 本来就不需要口令，现在会直接返回 200，
所以这个问题在新版里不会再出现。

### 方式 D：用自己电脑当服务器 + 免费内网穿透（零成本、最快）

本机出一支 3 分钟成片只要**约 70 秒**（比 Render 免费档快约 25 倍），
所以「本机跑 + 穿透一个公网地址」是演示场景里最划算的方案。

仓库里已备好双击即用的脚本（**不需要下载任何东西**，用的是 Windows 自带的 `ssh`）：

| 脚本 | 作用 |
|---|---|
| `start-public.bat` | 开始分享：提示输入口令 → 启服务（8010）→ 建隧道 → 打印网址 |
| `stop-public.bat` | 停止分享：按端口找进程结束，不依赖窗口标题匹配 |
| `tools\tunnel.ps1` | 隧道本体：保活 + 断线自动重连（由 start-public.bat 调用） |
| `tools\get-cloudflared.bat` | 可选备用：换成 cloudflared 隧道（要下 52MB，国内可能很慢） |

> **为什么用 8010 而不是默认的 8000**：8000 很可能是你「本机自用」
> 实例的端口 —— 那边没有口令。一旦撞上，脚本的服务会启动失败，
> 而隧道却会把那个没口令的实例暴露到公网去。

手工做法也可以（等价于脚本里干的事）：

```powershell
# 终端 1：启动服务（注意这几个环境变量，见下方警告）
$env:HOST='127.0.0.1'
$env:PORT='8010'          # 避开本机自用的 8000
$env:ALLOW_WEB_SETTINGS='0'
$env:ACCESS_PASSWORD='自己定的口令'
.\.venv\Scripts\python.exe app.py

# 终端 2：建隧道 + 保活 + 自动重连（推荐就直接用它）
powershell -NoProfile -ExecutionPolicy Bypass -File tools\tunnel.ps1 -Port 8010
```

拿到形如 `https://xxxx.lhr.life` 的地址就能分享出去。
对方打开**不用口令就能看完整站**（包括你的示例作品）；
只有点「开始制作」时才会弹框要口令。

> **四个坑，踩过了所以写在这：**
>
> 1. **转发目标写 `127.0.0.1`，别写 `localhost`。**
>    Windows 上 `localhost` 会优先解析成 IPv6 的 `::1`，而程序只监听 IPv4，
>    结果隧道建起来了但请求转不进去，访问报 `Empty reply from server`。
> 2. **免费匿名隧道有「闲置超时」。** 实测跑着跑着会收到
>    `Received disconnect: tunnel inactivity timeout` —— 一段时间没有流量
>    经过就会被服务端掐断。`tunnel.ps1` 每 60 秒探一次活就是为了治这个。
> 3. **重连后网址可能会变**，以新打印的为准（旧地址立刻失效）。
>    想彻底固定可以注册 localhost.run 账号并绑 SSH 公钥，或改用 cloudflared。
> 4. **不要用 8000 端口做分享**（理由见上面那个提示框）。
>
> 另外，写 PowerShell 脚本时踩的三个编码/环境坑（已修，别改回去）：
>
> - **`.ps1` 必须带 UTF-8 BOM。** Windows PowerShell 5.1 读 `.ps1` 默认按
>   ANSI（中文系统是 GBK），UTF-8 无 BOM 时中文会把引号解析错，
>   报「字符串缺少终止符」。
> - **不要强行设 `[Console]::OutputEncoding`**，会和实际代码页打架，
>   中文出现「正正在在」这种字符翻倍。
> - **探活用 `curl.exe --noproxy '*'` 而不是 `Invoke-WebRequest`**：
>   后者会走系统代理，用户开着代理时请求会被路由到别处，
>   探活就成了假成功，看日志才发现根本没到服务器。

| | 说明 |
|---|---|
| 优点 | 零成本、速度最快（用你本机的 CPU 与内存） |
| 缺点 | **电脑必须开着**，休眠 / 关机链接就失效；免费隧道的网址重启后会换 |
| 适合 | 课堂演示、答辩、临时给几个人试用 |

> ### ⚠️ 走隧道建议关掉「网页端改配置」
>
> 程序判断「能否改配置」的依据是**服务是不是只监听本机**（`127.0.0.1`）。
> 走隧道时服务**仍然监听 127.0.0.1**，程序会以为很安全，但外面其实已经能进来了。
>
> 现在这条链路上有两道锁：`POST /api/settings/llm` 已经**先用口令确认身份**
> （所以拿到网址但不知道口令的人已经进不来了），再看 `ALLOW_WEB_SETTINGS`。
> 但两道锁比一道稳，所以 `start-public.bat` 仍然会自动设
> `ALLOW_WEB_SETTINGS=0`，手工启动时也别省这一条 ——
> 否则知道口令的人就能把 `LLM_BASE_URL` 改到自己服务器上**把真 Key 接走**。
>
> 顺带解释一个常见疑问：Render 上那个设置面板点不动，是因为那边监听的是
> `0.0.0.0`，程序判断「这是公网环境」自动禁用了——**那是设计如此，不是坏了**。

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
