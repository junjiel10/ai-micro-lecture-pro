<#
  把本机 output/ 里出好的成片「发布」到云端展示。

  为什么要绕一道 examples/：
    Render 免费档的文件系统是临时的 —— 直接在 output/ 里生成的东西，
    容器一重启（闲置休眠、或代码重新部署）就全没了。
    只有随镜像打进仓库的文件能活下来：examples/ 会随镜像走，
    服务启动时再复制进 output/（见 app.py 里的 _seed_examples）。
    所以流程是：本机出片 → 本脚本整理进 examples/ → 提交推送 →
    云端重新部署后自动挂出来，而且重启也不丢。

  用法：双击 publish-example.bat（会列出可选成片让你挑）
        或者：
        powershell -ExecutionPolicy Bypass -File tools\publish-example.ps1
        powershell -ExecutionPolicy Bypass -File tools\publish-example.ps1 -Id 20260911-113618-xxx
#>
param([string]$Id = '')

$ErrorActionPreference = 'Continue'

# 仓库根目录 = 本脚本所在目录（tools/）的上一级
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outputDir = Join-Path $root 'output'
$examplesDir = Join-Path $root 'examples'

# 展示必需的就这几样。中间产物（clips / shots / bgm.wav / raw.mp4 …）
# 一个都不带 —— 它们能有好几十 MB，白白把仓库撑大。
$keepFiles = @('final.mp4', 'project.json', 'plan.json',
               'narration.srt', 'narration.ass')


function Read-Meta([string]$dir) {
    $p = Join-Path $dir 'project.json'
    if (-not (Test-Path $p)) { return $null }
    try { return (Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { return $null }
}


Write-Host ''
Write-Host '  ============================================================' -ForegroundColor Cyan
Write-Host '    发布成片到云端（妙课生花 WonderKourse）' -ForegroundColor Cyan
Write-Host '  ============================================================' -ForegroundColor Cyan
Write-Host ''
Write-Host '  它会做三件事：' -ForegroundColor DarkGray
Write-Host '    1. 把成片、元数据、字幕、分镜帧图整理进 examples/' -ForegroundColor DarkGray
Write-Host '    2. 提交到本地仓库' -ForegroundColor DarkGray
Write-Host '    3. 推送到 GitHub（云端会自动重新部署）' -ForegroundColor DarkGray
Write-Host ''

# ---------------------------------------------------------------- 挑项目
# 按成片时间倒序：刚出好的排在最前，符合「生成完就发布」的实际节奏
$projects = @(
    Get-ChildItem -Path $outputDir -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -notlike '_*' -and
            (Test-Path (Join-Path $_.FullName 'final.mp4'))
        } |
        Sort-Object { (Get-Item (Join-Path $_.FullName 'final.mp4')).LastWriteTime } `
            -Descending
)

if ($projects.Count -eq 0) {
    Write-Host '  [!] output/ 里还没有出过成片的项目。' -ForegroundColor Yellow
    Write-Host '      先在创作台生成一支，再回来发布。' -ForegroundColor Yellow
    exit 1
}

if ($Id) {
    # 支持只写前段：项目号往往带中文（形如 20260911-113618-生成式AI如何赋能教学设计），
    # 在命令行里传中文容易因代码页出问题，所以按「包含」模糊匹配就够用。
    $found = @($projects | Where-Object { $_.Name -like "*$Id*" })
    if ($found.Count -eq 0) {
        Write-Host "  [!] output/ 里找不到匹配：$Id" -ForegroundColor Red
        exit 1
    }
    if ($found.Count -gt 1) {
        Write-Host "  [!] 匹配到多个项目，请写得更具体一些：" -ForegroundColor Red
        $found | ForEach-Object { Write-Host "      $($_.Name)" -ForegroundColor DarkGray }
        exit 1
    }
    $pick = $found[0]
} else {
    Write-Host '  可发布的成片：' -ForegroundColor White
    Write-Host ''
    for ($i = 0; $i -lt $projects.Count; $i++) {
        $m = Read-Meta $projects[$i].FullName
        $title = if ($m -and $m.title) { $m.title } else { $projects[$i].Name }
        $sizeMb = [math]::Round(
            (Get-Item (Join-Path $projects[$i].FullName 'final.mp4')).Length / 1MB, 1)
        $already = if (Test-Path (Join-Path $examplesDir $projects[$i].Name)) {
            '   ← 已在云端'
        } else { '' }
        Write-Host ("   [{0}] {1}" -f ($i + 1), $title)
        Write-Host ("        {0}" -f $projects[$i].Name) -ForegroundColor DarkGray
        Write-Host ("        {0} MB{1}" -f $sizeMb, $already) -ForegroundColor DarkGray
        Write-Host ''
    }
    $sel = Read-Host '  要发布哪一支？输入编号（直接回车取消）'
    if ([string]::IsNullOrWhiteSpace($sel)) {
        Write-Host '  已取消。'
        exit 0
    }
    $n = 0
    if (-not [int]::TryParse($sel.Trim(), [ref]$n) -or
        $n -lt 1 -or $n -gt $projects.Count) {
        Write-Host '  [!] 编号不对。' -ForegroundColor Red
        exit 1
    }
    $pick = $projects[$n - 1]
}

$meta = Read-Meta $pick.FullName
$title = if ($meta -and $meta.title) { $meta.title } else { $pick.Name }

Write-Host ''
Write-Host "  选中的是：$title" -ForegroundColor White
Write-Host "  项目号　：$($pick.Name)" -ForegroundColor DarkGray
Write-Host ''

# ---------------------------------------------------------------- 整理文件
$dst = Join-Path $examplesDir $pick.Name
if (Test-Path $dst) {
    # 先整个清掉再复制：避免上一次发布残留的旧帧图混在里面
    Remove-Item $dst -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $dst -Force | Out-Null

$nFile = 0
foreach ($f in $keepFiles) {
    $src = Join-Path $pick.FullName $f
    if (Test-Path $src) {
        Copy-Item $src -Destination $dst
        $nFile++
    }
}

$framesDst = Join-Path $dst 'frames'
New-Item -ItemType Directory -Path $framesDst -Force | Out-Null
$nFrame = 0
Get-ChildItem -Path (Join-Path $pick.FullName 'frames') -Filter 'shot_*.png' `
        -ErrorAction SilentlyContinue |
    ForEach-Object { Copy-Item $_.FullName -Destination $framesDst; $nFrame++ }

$totalMb = (Get-ChildItem $dst -Recurse -File |
            Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host ("  [1/3] 已整理：{0} 个文件 + {1} 张帧图，共 {2:N1} MB" -f `
            $nFile, $nFrame, $totalMb) -ForegroundColor Green

# 同一支片重新生成会拿到新的项目号，旧的示例目录会留在 examples/ 里 ——
# 那样云端首页会出现两张同名卡片。这里按标题把同名旧目录清掉。
$titleNow = if ($meta -and $meta.title) { $meta.title } else { $null }
if ($titleNow) {
    Get-ChildItem -Path $examplesDir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne $pick.Name } |
        ForEach-Object {
            $other = Read-Meta $_.FullName
            if ($other -and $other.title -eq $titleNow) {
                Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
                Write-Host "  已移除同名的旧示例：$($_.Name)" -ForegroundColor DarkYellow
            }
        }
}

# ---------------------------------------------------------------- 提交
Set-Location $root
# 整个 examples/ 一起暂存：这样新增示例和「移除同名旧示例」的删除
# 会在同一次提交里，不会出现新旧两张同名卡片并存的情况。
& git add -A -- examples 2>&1 | Out-Null

$staged = & git status --porcelain -- examples 2>&1
if (-not $staged) {
    Write-Host '  [2/3] 与仓库里已有的一模一样，没有需要提交的改动。' -ForegroundColor DarkGray
} else {
    $msg = "发布示例作品：$title"
    & git commit -q -m $msg 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  [!] 提交失败，请检查 git 状态。' -ForegroundColor Red
        exit 1
    }
    Write-Host "  [2/3] 已提交：$msg" -ForegroundColor Green
}

# ---------------------------------------------------------------- 推送
# 网络时通时断（国内直连 GitHub 不稳），所以重试几次；开着代理就走代理
$proxy = ''
if (Test-NetConnection -ComputerName 127.0.0.1 -Port 7890 `
        -InformationLevel Quiet -WarningAction SilentlyContinue) {
    $proxy = 'http://127.0.0.1:7890'
    Write-Host '  检测到本地代理 7890，推送会走它。' -ForegroundColor DarkGray
}

Write-Host '  [3/3] 正在推送到 GitHub…' -ForegroundColor Green
$pushed = $false
for ($i = 1; $i -le 6; $i++) {
    $gitArgs = @()
    if ($proxy) { $gitArgs += @('-c', "http.proxy=$proxy", '-c', "https.proxy=$proxy") }
    $gitArgs += @('-c', 'http.postBuffer=524288000', '-c', 'http.version=HTTP/1.1')
    $gitArgs += @('push', 'origin', 'HEAD')

    $out = & git @gitArgs 2>&1
    if ($LASTEXITCODE -eq 0) { $pushed = $true; break }

    Write-Host "       第 $i 次没成功，等 15 秒重试…" -ForegroundColor DarkYellow
    Start-Sleep -Seconds 15
}

Write-Host ''
if ($pushed) {
    Write-Host '  ============================================================' -ForegroundColor Green
    Write-Host '    发布成功！' -ForegroundColor Green
    Write-Host '  ============================================================' -ForegroundColor Green
    Write-Host '    Render 会自动重新部署，约 2~5 分钟后这支片就永久挂在云端了：' -ForegroundColor Green
    Write-Host '      https://wonderkourse.onrender.com' -ForegroundColor Yellow
    Write-Host '    部署完成后重启容器也不会丢（它已经随镜像走了）。' -ForegroundColor DarkGray
} else {
    Write-Host '  [!] 推送没成功（网络问题，不是脚本的问题）。' -ForegroundColor Yellow
    Write-Host '      文件已经整理进 examples/ 了，等网络好了在项目目录手动执行一次：' -ForegroundColor Yellow
    Write-Host '        git push origin main' -ForegroundColor White
}
Write-Host ''
