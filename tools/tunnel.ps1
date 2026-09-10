<#
  妙课生花 WonderKourse · 公网隧道管理

  为什么单独写成 PowerShell 而不是塞进 .bat：
  它要一边读 ssh 的输出、一边定期探活、一边在掉线后重连，
  这些事在批处理里写出来又长又脆。

  它做三件事：
    1. 建 ssh 反向隧道，从输出里认出分享网址并大字打印出来
    2. 每 60 秒往隧道里打一次请求 —— 免费匿名隧道有「闲置超时」，
       一段时间没有流量经过就会被服务端掐断（实测就是这样掉线的）
    3. 真断了就自动重连（重连后网址会变，会重新打印）

  用法：由 start-public.bat 调用，一般不用直接跑。
        手工跑： powershell -ExecutionPolicy Bypass -File tools\tunnel.ps1 -Port 8010
#>
[CmdletBinding()]
param(
    [int]$Port = 8010,
    [string]$Bind = '127.0.0.1'
)

$ErrorActionPreference = 'Continue'
# 刻意不设 [Console]::OutputEncoding：
# start-public.bat 已经 chcp 65001，PowerShell 会自己跟随；
# 强行指定反而会和实际代码页打架，中文出现「正正在在」这种字符翻倍。

$logOut = Join-Path $env:TEMP 'wk-tunnel.out.log'
$logErr = Join-Path $env:TEMP 'wk-tunnel.err.log'
$urlPattern = 'https://[0-9a-z]+\.lhr\.life'

function Read-Log([string]$path) {
    <#
      为什么不用 Get-Content：
      ssh 正开着这个文件往里写（由 cmd 的重定向句柄持有），
      Get-Content 可能因共享模式而读失败。这里显式用 FileShare.ReadWrite
      打开，保证一边写一边读也拿得到内容。
    #>
    if (-not (Test-Path $path)) { return '' }
    try {
        $fs = [System.IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
        $sr = New-Object System.IO.StreamReader($fs)
        $t = $sr.ReadToEnd()
        $sr.Close(); $fs.Close()
        return $t
    } catch {
        return ''
    }
}

$round = 0
while ($true) {
    $round++
    Remove-Item $logOut, $logErr -ErrorAction SilentlyContinue

    # 目标是显式写 127.0.0.1 而不是 localhost：
    # Windows 上 localhost 会优先解析成 IPv6 的 ::1，而服务只监听 IPv4，
    # 隧道建起来了请求却转不进去（表现为 Empty reply from server）
    $sshArgs = @(
        '-o', 'StrictHostKeyChecking=accept-new'
        '-o', 'ServerAliveInterval=20'
        '-o', 'ServerAliveCountMax=3'
        '-o', 'ExitOnForwardFailure=yes'
        '-R', "80:${Bind}:${Port}"
        'nokey@localhost.run'
    )

    if ($round -gt 1) {
        Write-Host ''
        Write-Host "  [$round] 重新建立隧道…" -ForegroundColor DarkYellow
    }

    $proc = $null
    try {
        <#
          为什么套一层 cmd 而不直接用 Start-Process -RedirectStandardOutput：
          那种写法下 PowerShell 是建一根管道，再靠后台线程把内容搬到文件。
          主线程在跑密集轮询时数据搬不过去 —— 实测日志一直是 0 字节，
          同一个 ssh 命令手工单独跑却有输出。
          交给 cmd 做 “> 文件” 重定向，ssh 直接写文件句柄，就没这个问题。
        #>
        $argLine = ($sshArgs | ForEach-Object {
            if ($_ -match '[ "]') { '"' + $_ + '"' } else { $_ }
        }) -join ' '
        $cmdLine = "ssh $argLine > `"$logOut`" 2> `"$logErr`""
        $proc = Start-Process -FilePath $env:ComSpec -ArgumentList '/c', $cmdLine `
            -NoNewWindow -PassThru
    } catch {
        Write-Host "  [!] 起不来 ssh：$($_.Exception.Message)" -ForegroundColor Red
        Start-Sleep -Seconds 5
        continue
    }

    Write-Host '  正在建立隧道…（首次约 3~8 秒）' -ForegroundColor DarkGray

    $url = $null
    $lastPing = Get-Date
    $waited = 0
    $failStreak = 0

    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 1
        $waited++

        if (-not $url) {
            $text = (Read-Log $logOut) + "`n" + (Read-Log $logErr)
            $m = [regex]::Match($text, $urlPattern)
            if ($m.Success) {
                $url = $m.Value
                Write-Host ''
                Write-Host '  ------------------------------------------' -ForegroundColor Green
                Write-Host '   分享网址（复制这一行）：' -ForegroundColor Green
                Write-Host ''
                Write-Host "     $url" -ForegroundColor Yellow
                Write-Host ''
                Write-Host '   对方不用口令就能浏览全站（含示例作品）；' -ForegroundColor Green
                Write-Host '   只有点「开始制作」时才会弹框要口令。' -ForegroundColor Green
                Write-Host '  ------------------------------------------' -ForegroundColor Green
                Write-Host ''
                Write-Host '  隧道自动保活与重连；本窗口关掉 = 停止分享。' -ForegroundColor DarkGray
                Write-Host ''
            } elseif ($waited -ge 30) {
                Write-Host '  [!] 30 秒还没拿到网址，网络可能不通。继续等…' -ForegroundColor DarkYellow
                $waited = 0
            }
        }

        # ---- 保活：防止免费隧道因闲置被服务端掐断 ----
        # 为什么用 curl.exe 而不是 Invoke-WebRequest：
        # PowerShell 5.1 的 Invoke-WebRequest 会走系统代理，用户开着代理时
        # 请求可能被路由到别处，探活就成了假成功（或假失败）。
        # curl.exe + --noproxy 走直连，行为可控；Windows 10+ 自带 curl。
        if ($url -and ((Get-Date) - $lastPing).TotalSeconds -ge 60) {
            $lastPing = Get-Date
            $code = & curl.exe -s -o NUL -w '%{http_code}' --noproxy '*' `
                                --max-time 15 "$url/api/health" 2>$null
            $stamp = (Get-Date).ToString('HH:mm:ss')
            if ("$code" -eq '200') {
                $failStreak = 0
                Write-Host "  [保活] $stamp  正常" -ForegroundColor DarkGray
            } else {
                $failStreak++
                Write-Host "  [保活] $stamp  没通（HTTP $code），连续 $failStreak 次" -ForegroundColor DarkYellow
                <#
                  关键：localhost.run 可以把隧道作废而 SSH 连接依然活着，
                  那时候返回 503 / 连不上，但 ssh 进程不会退出，
                  “等 HasExited” 就永远等不到。所以探活连续失败时要主动重建。
                  杀整个进程树（cmd → ssh），循环条件就会感知到并重连。
                #>
                if ($failStreak -ge 2) {
                    Write-Host '  连续两次没通，判定隧道已失效，正在重建…' -ForegroundColor DarkYellow
                    & taskkill /PID $proc.Id /T /F 2>$null | Out-Null
                }
            }
        }
    }

    Write-Host ''
    Write-Host '  [!] 隧道断开。免费匿名隧道有闲置超时，属于正常现象。' -ForegroundColor DarkYellow
    if ($url) {
        Write-Host '      重连后网址会变，以新打印的为准（旧地址立刻失效）。' -ForegroundColor DarkYellow
    } else {
        Write-Host '      没能拿到网址。' -ForegroundColor DarkYellow
    }
    Write-Host '      3 秒后自动重连…（按 Ctrl+C 可以彻底停掉）' -ForegroundColor DarkYellow
    Start-Sleep -Seconds 3
}
