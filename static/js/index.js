/* 首页逻辑：运行环境 / 快捷开始 / 示例作品播放 */

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDur = (s) => {
  s = Math.round(s || 0);
  return s ? `${Math.floor(s / 60)}分${String(s % 60).padStart(2, "0")}秒` : "—";
};

let WORKS = {};
let playerState = { id: null, subs: true };

/* ==================== 运行环境 ==================== */
async function loadHealth() {
  try {
    const d = await (await fetch("/api/health")).json();
    $("presets").innerHTML = d.presets.map((p) => `<option value="${esc(p)}"></option>`).join("");
    $("heroChips").innerHTML = d.presets.slice(0, 5)
      .map((p) => `<span class="chip" onclick="fill('${esc(p)}')">${esc(p)}</span>`).join("");
  } catch (e) {
    // 页脚只在「后端没起来」这种真需要提示的时候才出一行字
    $("footEnv").textContent = "服务未连接，请先启动后端";
  }
}

function fill(t) { $("quickTopic").value = t; $("quickTopic").focus(); }

function quickStart(ev) {
  ev.preventDefault();
  const t = $("quickTopic").value.trim();
  location.href = "/create" + (t ? "?topic=" + encodeURIComponent(t) : "");
  return false;
}

/* ==================== 示例作品 ==================== */
async function loadWorks() {
  const grid = $("worksGrid");
  try {
    const d = await (await fetch("/api/projects")).json();
    const items = (d.items || []).filter((x) => x.done).slice(0, 8);
    WORKS = {};
    if (!items.length) {
      grid.innerHTML = '<div class="empty">还没有作品，进入创作台生成第一支微课吧。</div>';
      return;
    }
    items.forEach((p) => { WORKS[p.id] = p; });
    grid.innerHTML = items.map((p) => {
      const portrait = p.fmt === "portrait";
      const id = esc(p.id);
      return `
      <article class="work-card" role="button" tabindex="0"
               onclick="openPlayer('${id}')"
               onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openPlayer('${id}')}">
        <div class="work-thumb ${portrait ? "is-portrait" : ""}">
          <img loading="lazy" alt="${esc(p.title)}"
               src="/api/projects/${encodeURIComponent(p.id)}/frames/shot_01.png"
               onerror="this.style.display='none'">
          <div class="badge-row">
            <span class="badge">${portrait ? "竖版 9:16" : "横版 16:9"}</span>
            ${p.score != null ? `<span class="badge brand">质检 ${p.score}</span>` : ""}
          </div>
          <div class="work-play"><span>▶</span></div>
        </div>
        <div class="work-body">
          <h4>${esc(p.title)}</h4>
          <div class="work-meta">
            <span>${p.shots} 个分镜</span>
            <span>${fmtDur(p.duration)}</span>
            <span>${esc(p.subject || "")}</span>
          </div>
        </div>
      </article>`;
    }).join("");
  } catch (e) {
    grid.innerHTML = '<div class="empty">读取作品列表失败。</div>';
  }
}

/* ==================== 播放弹窗 ==================== */
function openPlayer(id) {
  const p = WORKS[id] || {};
  playerState = { id, subs: true };
  $("playerShell").classList.toggle("is-portrait", p.fmt === "portrait");
  $("playerTitle").textContent = p.title || "示例作品";
  $("playerMeta").textContent = p.shots
    ? `${p.shots} 个分镜 · ${fmtDur(p.duration)}${p.score != null ? " · 质检 " + p.score + " 分" : ""}`
    : "";
  $("playerSubBtn").textContent = "字幕：开";
  $("playerSubBtn").classList.add("on");
  $("playerVideo").src = `/api/projects/${encodeURIComponent(id)}/video?subs=1`;
  $("playerMask").classList.add("show");
  $("playerVideo").play().catch(() => {});
  document.body.style.overflow = "hidden";
}

function closePlayer() {
  const v = $("playerVideo");
  v.pause();
  v.removeAttribute("src");
  v.load();
  $("playerMask").classList.remove("show");
  document.body.style.overflow = "";
}

function togglePlayerSubs() {
  if (!playerState.id) return;
  playerState.subs = !playerState.subs;
  $("playerSubBtn").textContent = "字幕：" + (playerState.subs ? "开" : "关");
  $("playerSubBtn").classList.toggle("on", playerState.subs);
  const v = $("playerVideo");
  const t = v.currentTime;
  v.src = `/api/projects/${encodeURIComponent(playerState.id)}/video?subs=${playerState.subs ? 1 : 0}`;
  v.addEventListener("loadedmetadata", function once() {
    v.currentTime = t;
    v.play().catch(() => {});
    v.removeEventListener("loadedmetadata", once);
  });
}

function downloadPlayer() {
  if (!playerState.id) return;
  const a = document.createElement("a");
  a.href = `/api/projects/${encodeURIComponent(playerState.id)}/video?subs=1`;
  a.download = (WORKS[playerState.id] && WORKS[playerState.id].title || playerState.id) + ".mp4";
  document.body.appendChild(a); a.click(); a.remove();
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && $("playerMask").classList.contains("show")) closePlayer();
});

/* ==================== 滚动入场（渐进增强） ==================== */
function initReveal() {
  const els = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window)) return;      // 不支持就保持默认可见，什么都不做

  // 告诉页头那段内联脚本「主脚本已经接管」，它会放弃自己的兜底逻辑
  document.documentElement.classList.add("motion-on");

  const io = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (en.isIntersecting) { en.target.classList.add("is-in"); io.unobserve(en.target); }
    });
  }, { rootMargin: "0px 0px -12% 0px", threshold: 0.05 });
  els.forEach((el) => io.observe(el));
}

/* ==================== 启动 ==================== */
// 顶栏的「登录 / 注册」与窄屏折叠菜单由 ui.js 统一接管（index / guide 共用）

// 在创作台删掉某个项目后切回首页，作品列表要跟着更新，
// 否则会看到一张点开已经没有数据的卡片
if ("visibilityState" in document) {
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) loadWorks();
  });
}

loadHealth();
loadWorks();
initReveal();
