# -*- coding: utf-8 -*-
"""访问口令 / 登录页流程 · 端到端回归测试

不依赖任何第三方库（只用标准库 http.client），也不改任何数据：
它只是按顺序发请求并检查状态码与响应内容。

用法（在项目根目录）：
    # 先起一个带口令的实例
    $env:HOST='127.0.0.1'; $env:PORT='8001'; $env:ACCESS_PASSWORD='你设的口令'
    .\.venv\Scripts\python.exe app.py

    # 另开一个终端跑测试
    python tools\test_login.py

可用环境变量：TEST_HOST（默认 127.0.0.1）、TEST_PORT（默认 8001）、
TEST_PASSWORD（默认 wk-demo-2026）—— 要跟服务端 ACCESS_PASSWORD 一致。

注意：最后两项会故意连续输错口令触发限流，会把本机 IP 锁 10 分钟，
所以它们放在最后；测完建议重启服务清掉锁定状态。
"""
import http.client
import os
import sys
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = os.environ.get("TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("TEST_PORT", "8001"))
PW = os.environ.get("TEST_PASSWORD", "wk-demo-2026")

results = []


def req(method, path, body=None, headers=None, cookie=None):
    """发一个请求。http.client 不会自动跟随重定向，正好用来观察 303。"""
    h = dict(headers or {})
    if cookie:
        h["Cookie"] = cookie
    if body is not None:
        h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    c = http.client.HTTPConnection(HOST, PORT, timeout=20)
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read().decode("utf-8", "replace")
    status, hdrs = r.status, {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return status, hdrs, data


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))


print("=" * 66)
print(f"  访问口令登录流程测试  ->  {HOST}:{PORT}")
print("=" * 66)

# ---------- 免口令路径 ----------
st, hd, _ = req("GET", "/api/health")
check("1  健康检查免口令放行", st == 200, f"HTTP {st}")

st, hd, _ = req("GET", "/static/logo.svg")
check("2  登录页图标免口令放行", st == 200, f"HTTP {st}")

st, hd, _ = req("GET", "/static/css/style.css")
check("3  其余静态资源仍受保护", st in (303, 401), f"HTTP {st}")

st, hd, _ = req("GET", "/favicon.ico")
check("4  favicon 指向 logo（不再 404）",
      st == 307 and hd.get("location") == "/static/logo.svg",
      f"HTTP {st} -> {hd.get('location')}")

# ---------- 未登录跳转 ----------
st, hd, _ = req("GET", "/")
check("5  未登录访问首页 -> 303 跳登录页",
      st == 303 and "/login" in hd.get("location", ""),
      f"HTTP {st} -> {hd.get('location')}")

st, hd, _ = req("GET", "/create")
check("6  未登录访问 /create -> 保留目标页",
      st == 303 and "next=%2Fcreate" in hd.get("location", ""),
      f"-> {hd.get('location')}")

st, hd, _ = req("GET", "/guide")
check("6b 未登录访问 /guide -> 保留目标页",
      st == 303 and "next=%2Fguide" in hd.get("location", ""),
      f"-> {hd.get('location')}")

st, hd, body = req("GET", "/api/")
check("7  未登录访问接口 -> 401（不跳转）", st in (401, 404), f"HTTP {st}")

st, hd, body = req("GET", "/api/projects")
check("8  API 未登录返 401 JSON",
      st == 401 and "未登录" in body, f"HTTP {st} {body[:40]}")

# ---------- 登录页 ----------
st, hd, body = req("GET", "/login")
check("9  登录页可访问", st == 200, f"HTTP {st}")
check("10 登录页含口令输入框", 'type="password"' in body and 'name="password"' in body)
check("11 登录页是提交表单而非纯文本", "<form" in body and 'action="/login"' in body)
check("12 登录页不再出现裸文本「需要访问口令」", "需要访问口令" not in body)
check("13 登录页自带样式（不依赖被保护的 css）", "<style>" in body)

st, hd, body = req("GET", "/login?next=%2Fcreate")
check("14 next 参数被带进表单", 'value="/create"' in body)

st, hd, body = req("GET", "/login?next=//evil.com")
check("15 开放跳转被拦截（//evil.com -> /）",
      'value="/"' in body and 'value="//evil.com"' not in body)

# ---------- 错口令 ----------
st, hd, body = req("POST", "/login", body="password=wrong&next=/")
check("16 错口令 -> 留在登录页并提示",
      st == 200 and "口令不对" in body, f"HTTP {st}")

# ---------- 对口令 ----------
st, hd, body = req("POST", "/login",
                   body="password=" + urllib.parse.quote(PW) + "&next=/")
sc = hd.get("set-cookie", "")
check("17 对口令 -> 303 跳首页", st == 303 and hd.get("location") == "/",
      f"HTTP {st} -> {hd.get('location')}")
check("18 下发会话 Cookie", sc.startswith("wk_pass="), sc[:40])
check("19 Cookie 带 HttpOnly", "httponly" in sc.lower())
check("20 Cookie 带 SameSite=Lax", "samesite=lax" in sc.lower())
check("21 本地 http 下不带 Secure（否则写不进浏览器）",
      "; secure" not in sc.lower())

cookie = sc.split(";")[0]

# ---------- 带 Cookie 访问 ----------
st, hd, body = req("GET", "/", cookie=cookie)
check("22 带 Cookie 访问首页 -> 200", st == 200, f"HTTP {st}")
check("23 首页拿到的是真内容",
      "妙课生花" in body or "WonderKourse" in body)

st, hd, _ = req("GET", "/static/css/style.css", cookie=cookie)
check("24 带 Cookie 可加载受保护静态资源", st == 200, f"HTTP {st}")

st, hd, body = req("GET", "/api/projects", cookie=cookie)
check("25 带 Cookie 可调用接口", st == 200, f"HTTP {st}")

st, hd, body = req("POST", "/api/settings/llm",
                   body="api_key=sk-evil", cookie=cookie)
check("26 改配置接口仍被 403 挡住（公网安全）", st == 403, f"HTTP {st}")

# ---------- 伪造 Cookie ----------
st, hd, _ = req("GET", "/", cookie="wk_pass=forged-value")
check("27 伪造 Cookie 无效 -> 303", st == 303, f"HTTP {st}")

st, hd, _ = req("GET", "/", cookie="wk_pass=")
check("28 空 Cookie 无效 -> 303", st == 303, f"HTTP {st}")

# ---------- 兼容 Basic 认证 ----------
import base64
tok = base64.b64encode(f"demo:{PW}".encode()).decode()
st, hd, _ = req("GET", "/", headers={"Authorization": "Basic " + tok})
check("29 Basic 认证仍可用（curl -u 不破坏）", st == 200, f"HTTP {st}")

bad = base64.b64encode(f"demo:wrong".encode()).decode()
st, hd, _ = req("GET", "/", headers={"Authorization": "Basic " + bad})
check("30 错误的 Basic 认证被拒", st == 303, f"HTTP {st}")

# ---------- 已登录时的登录页 ----------
st, hd, _ = req("GET", "/login", cookie=cookie)
check("31 已登录再访问 /login 直接送回首页",
      st == 303 and hd.get("location") == "/", f"HTTP {st}")

# ---------- 退出 ----------
st, hd, _ = req("GET", "/logout", cookie=cookie)
check("32 退出 -> 303 回登录页",
      st == 303 and hd.get("location") == "/login", f"HTTP {st}")
check("33 退出时清除 Cookie", "wk_pass=" in hd.get("set-cookie", ""))

# ---------- 限流（放最后，因为会锁住本机 IP） ----------
locked_at = 0
for i in range(1, 16):
    st, hd, body = req("POST", "/login", body="password=nope&next=/")
    if "次数过多" in body:
        locked_at = i
        break
check("34 连续错口令会触发限流锁定",
      0 < locked_at <= 13, f"第 {locked_at} 次被锁")

st, hd, body = req("POST", "/login",
                   body="password=" + urllib.parse.quote(PW) + "&next=/")
check("35 锁定期间即使口令正确也拒绝", "次数过多" in body)

print("=" * 66)
ok = sum(1 for _, c, _ in results if c)
print(f"  通过 {ok}/{len(results)}")
if ok != len(results):
    print("  失败项：")
    for n, c, d in results:
        if not c:
            print(f"    - {n} {d}")
print("=" * 66)
sys.exit(0 if ok == len(results) else 1)
