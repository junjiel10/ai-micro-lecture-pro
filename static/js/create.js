/* 创作台逻辑：7 步流水线可视化 + 实时事件流 + 预览导出 */

const state = {
  projectId: null,
  files: [],          // [{file_id, name, chars, meta}]
  events: 0,          // 已消费的事件下标
  timer: null,
  subtitle: true,
  detail: null,
  fmt: "landscape",
  themeIndex: 0,
  themes: ["deepsea", "scholar", "sunrise"],
  running: false,
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDur = (s) => {
  s = Math.round(s || 0);
  return s ? `${Math.floor(s / 60)}分${String(s % 60).padStart(2, "0")}秒` : "—";
};

/* ==================== 初始化 ==================== */
async function init() {
  buildPipeline([
    { icon: "①", name: "文档解析" },
    { icon: "②", name: "知识结构化" },
    { icon: "③", name: "分镜脚本" },
    { icon: "④", name: "配音配乐" },
    { icon: "⑤", name: "画面生成" },
    { icon: "⑥", name: "剪辑合成" },
    { icon: "⑦", name: "质检打分" },
  ]);
  await loadHealth();
  await loadProjects();

  const q = new URLSearchParams(location.search);
  if (q.get("topic")) { $("topicInput").value = q.get("topic"); startCreate(); }
  if (q.get("mode") === "doc") { $("fileInput").click(); }
  if (q.get("project")) { state.themeIndex = -1; openProject(q.get("project")); }
}

async function loadHealth() {
  try {
    const d = await (await fetch("/api/health")).json();
    $("modeHint").textContent = "脚本来源：" + d.llm_mode;
    $("topicPresets").innerHTML = d.presets.map((p) => `<option value="${p}"></option>`).join("");
    if (d.themes) state.themes = d.themes.map((t) => t.key);
    state.themeIndex = state.themes.indexOf($("themeSel").value);
    if (d.formats) {
      $("fmtSel").innerHTML = d.formats
        .map((f) => `<option value="${f.key}" title="${f.desc}">${f.name}（${f.desc}）</option>`)
        .join("");
    }
  } catch (e) {
    $("modeHint").textContent = "后端未连接";
  }
}

/* ==================== 大模型设置 ==================== */
function openLlm() { $("llmModal").classList.add("show"); }
function closeLlm() { $("llmModal").classList.remove("show"); }

async function saveLlm() {
  $("llmGo").disabled = true;
  $("llmGo").textContent = "保存中…";
  const fd = new FormData();
  fd.append("api_key", $("llmKey").value.trim());
  fd.append("base_url", $("llmBase").value.trim());
  fd.append("model", $("llmModel").value.trim());
  fd.append("voice", $("llmVoice").value);
  try {
    const d = await (await fetch("/api/settings/llm", { method: "POST", body: fd })).json();
    if (d.error) throw new Error(d.error);
    $("modeHint").textContent = "脚本来源：" + d.llm_mode;
    appendLog("success", "配置已保存并生效：" + d.llm_mode);
    $("llmKey").value = "";
    closeLlm();
  } catch (e) {
    appendLog("warning", "保存失败：" + e.message);
  } finally {
    $("llmGo").disabled = false;
    $("llmGo").textContent = "保存并生效";
  }
}

/* ==================== 流水线 UI ==================== */
const PIPE_KEYS = ["document", "structure", "script", "audio", "visual", "edit", "review"];

function buildPipeline(items) {
  $("pipeline").innerHTML = items.map((a, i) => `
    <div class="pipe-item" id="pipe-${PIPE_KEYS[i]}">
      <span class="pi-idx">${a.icon}</span>
      <span class="pi-name">${a.name}</span>
      <span class="pi-detail">待执行</span>
    </div>`).join("");
}

function setAgent(key, status, detail) {
  const el = $("pipe-" + key);
  if (!el) return;
  const label = { running: "执行中…", done: detail || "完成", retry: detail || "重做中",
                  failed: detail || "失败", skip: detail || "已跳过" }[status] || status;
  if (status === "running") { el.classList.remove("done", "retry", "failed"); }
  el.classList.toggle("running", status === "running");
  el.classList.toggle("done", status === "done" || status === "skip");
  el.classList.toggle("retry", status === "retry");
  el.classList.toggle("failed", status === "failed");
  el.querySelector(".pi-detail").textContent = label;
}

function resetPipeline() {
  PIPE_KEYS.forEach((k) => {
    const el = $("pipe-" + k);
    if (!el) return;
    el.className = "pipe-item";
    el.querySelector(".pi-detail").textContent = "待执行";
  });
  clearDots();
}

/* ==================== 文档上传 ==================== */
$("fileInput").addEventListener("change", async (ev) => {
  for (const f of Array.from(ev.target.files)) {
    await uploadOne(f);
  }
  ev.target.value = "";
});

async function uploadOne(file) {
  appendLog("info", `上传并预检文档：${file.name}`);
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    const d = await res.json();
    if (d.error) { appendLog("warning", d.error); return; }
    state.files.push(d);
    renderFiles();
    appendLog("观察", `「${d.name}」预检通过：${d.chars} 字`
      + (d.keywords && d.keywords.length ? `，关键词 ${d.keywords.join("、")}` : ""));
  } catch (e) {
    appendLog("warning", "上传失败：" + e.message);
  }
}

function renderFiles() {
  $("fileList").innerHTML = state.files.map((f, i) => `
    <div class="file-item">
      <span>📄</span>
      <span>${esc(f.name)}<br><span style="color:var(--muted-2)">${f.chars} 字</span></span>
      <span class="fx" onclick="removeFile(${i})">✕</span>
    </div>`).join("");
}

function removeFile(i) { state.files.splice(i, 1); renderFiles(); }

/* ==================== 开始制作 ==================== */
async function startCreate() {
  if (state.running) return;
  const topic = $("topicInput").value.trim();
  if (!topic && !state.files.length) {
    alert("请输入知识主题，或至少上传一份文档");
    return;
  }
  state.running = true;
  state.events = 0;
  state.detail = null;
  $("startBtn").disabled = true;
  $("startBtn").textContent = "⏳ Agent 工作中…";
  $("logBox").innerHTML = "";
  resetPipeline();
  hideResult();
  $("progressWrap").classList.add("show");
  setStage(true);
  setProgress(0, "启动编排器…", 1);

  const fd = new FormData();
  fd.append("topic", topic);
  fd.append("file_ids", state.files.map((f) => f.file_id).join(","));
  fd.append("minutes", $("minutesSel").value);
  fd.append("theme", $("themeSel").value);
  fd.append("style", $("styleSel").value);
  fd.append("fmt", $("fmtSel").value);
  fd.append("illustrations", $("illSel").value);
  fd.append("audience", $("audienceInput").value || "本科生");

  try {
    const res = await fetch("/api/projects", { method: "POST", body: fd });
    const d = await res.json();
    if (d.error) throw new Error(d.error);
    state.projectId = d.project_id;
    poll();
  } catch (e) {
    appendLog("warning", "启动失败：" + e.message);
    finishRun(false);
  }
}

function poll() {
  if (state.timer) clearTimeout(state.timer);
  state.timer = setTimeout(async () => {
    if (!state.projectId) return;
    try {
      const r = await fetch(`/api/projects/${state.projectId}/events?since=${state.events}`);
      if (!r.ok) throw new Error("任务不存在（服务可能重启过）");
      const d = await r.json();
      (d.events || []).forEach(handleEvent);
      state.events = d.total;
      if (d.status === "done") {
        onDone(d.result);
        return;
      }
      if (d.status === "error") {
        appendLog("warning", "制作失败：" + (d.error || "未知错误"));
        finishRun(false);
        return;
      }
      poll();
    } catch (e) {
      appendLog("warning", e.message);
      finishRun(false);
    }
  }, 600);
}

function handleEvent(e) {
  switch (e.type) {
    case "log":
      appendLog(e.level, e.msg, e.t);
      break;
    case "step":
      setProgress((e.index - 1) / e.total,
                  `第 ${e.index}/${e.total} 步 · ${e.label}`, e.index);
      $("stageText").textContent = `第 ${e.index}/${e.total} 步 · ${e.label}`;
      setAgent(e.agent, "running");
      break;
    case "agent":
      setAgent(e.agent, e.status, e.detail);
      break;
    case "progress":
      setProgress(e.value, null);
      break;
    case "plan":
      appendLog("观察", `分镜脚本已就绪：${e.shots.length} 个分镜，预估 ${e.minutes} 分钟`);
      renderShotSkeleton(e.shots);
      break;
    case "review":
      renderReport(e);
      break;
    case "rework":
      appendLog("warning", `定向重做：${e.what}`);
      break;
    case "docs":
      if (e.items && e.items.length) {
        appendLog("观察", "文档解析结果：" +
          e.items.map((i) => `${i.name}（${i.chars} 字）`).join("、"));
      }
      break;
    case "result":
      break;
  }
}

function setProgress(v, text, stepIdx) {
  const pct = Math.max(2, Math.min(100, Math.round((v || 0) * 100)));
  $("progressFill").style.width = pct + "%";
  $("progressPct").textContent = pct + "%";
  if (text) $("progressText").textContent = text;
  if (stepIdx != null) setDots(stepIdx);
}

/* 七点步进指示：已完成 / 进行中 / 未开始 */
function setDots(active) {
  const box = $("progressDots");
  if (box.children.length !== PIPE_KEYS.length) {
    box.innerHTML = PIPE_KEYS.map(() => "<i></i>").join("");
  }
  [...box.children].forEach((el, i) => {
    const n = i + 1;
    el.className = n < active ? "done" : (n === active ? "current" : "");
  });
}

function clearDots() { $("progressDots").innerHTML = ""; }

function setStage(active) {
  $("progressWrap").classList.toggle("is-active", !!active);
}

function setProgressText(t) { $("progressText").textContent = t; }

/* ==================== 完成 ==================== */
function onDone(result) {
  if (!result) { finishRun(false); return; }
  state.projectId = result.project_id;      // 后端任务号与项目目录名一致
  setProgress(1, "制作完成", 8);
  setStage(false);
  $("stageText").textContent = "✅ 制作完成";
  finishRun(true);

  const bar = $("resultBar");
  bar.className = "result-bar show";
  bar.innerHTML = `
    <span>🎬 <b>${esc(result.title)}</b></span>
    <span>分镜 ${result.shots.length} 个</span>
    <span>${result.format_name || ""} ${result.resolution || ""}</span>
    <span>时长 ${fmtDur(result.duration)}</span>
    <span>${result.size_mb} MB</span>
    <span>质检 <b>${result.review.score}</b> 分</span>
    <span>${result.source}</span>
    ${result.elapsed ? `<span>耗时 ${result.elapsed}s</span>` : ""}`;

  playVideo(result.project_id, true, result.fmt);
  loadDetail(result.project_id);
  loadProjects();
}

function finishRun(ok) {
  state.running = false;
  setStage(false);
  $("startBtn").disabled = false;
  $("startBtn").textContent = ok ? "▶ 再做一个" : "▶ 开始制作";
  if (!ok) $("progressWrap").classList.remove("show");
}

function hideResult() {
  $("resultBar").className = "result-bar";
  $("report").classList.add("hidden");
  $("shotsStrip").innerHTML =
    '<div class="empty" style="padding:24px 0">生成后这里会显示每个分镜的画面</div>';
  $("player").style.display = "none";
  $("player").removeAttribute("src");
  $("placeholder").style.display = "block";
  $("exportBtn").disabled = true;
  $("srtBtn").disabled = true;
  $("reviseBtn").disabled = true;
  $("progressFill").style.width = "0%";
  $("progressPct").textContent = "0%";
  clearDots();
  $("stageText").textContent = "等待开始";
}

/* ==================== 预览与分镜 ==================== */
function playVideo(pid, withSubs, fmt) {
  if (fmt) setStageAspect(fmt);
  const p = $("player");
  p.src = `/api/projects/${encodeURIComponent(pid)}/video?subs=${withSubs ? 1 : 0}&t=${Date.now()}`;
  p.style.display = "block";
  $("placeholder").style.display = "none";
  $("exportBtn").disabled = false;
  $("srtBtn").disabled = false;
  $("reviseBtn").disabled = false;
}

/* 竖版项目用 9:16 的预览框，横版用 16:9 */
function setStageAspect(fmt) {
  state.fmt = fmt || "landscape";
  $("videoStage").classList.toggle("is-portrait", state.fmt === "portrait");
}

async function loadDetail(pid) {
  try {
    const d = await (await fetch(`/api/projects/${encodeURIComponent(pid)}/detail`)).json();
    if (d.error) return;
    state.detail = d;
    if (d.fmt) setStageAspect(d.fmt);
    renderShots(d);
    if (d.review) renderReport(d.review);
  } catch (e) { /* 忽略 */ }
}

function renderShotSkeleton(shots) {
  /* 分镜方案已就绪但画面还没渲染出来 —— 先给骨架屏，避免长时间空白 */
  $("shotsStrip").innerHTML = shots.map((s) => `
    <div class="shot-card skeleton" title="${esc(s.narration)}">
      <div class="thumb"></div>
      <div class="cap"><b>${String(s.index).padStart(2, "0")}</b>
      <span>${esc(s.scene)}</span></div>
    </div>`).join("");
}

function renderShots(d) {
  const strip = $("shotsStrip");
  strip.innerHTML = "";
  (d.images || []).forEach((img, i) => {
    const s = (d.shots || [])[i] || {};
    const card = document.createElement("div");
    card.className = "shot-card";
    card.title = s.narration || "";
    card.innerHTML = `
      <img loading="lazy" src="/api/projects/${encodeURIComponent(d.id)}/frames/${img}" alt="">
      <div class="cap"><b>${String(s.index || i + 1).padStart(2, "0")}</b>
      <span>${esc(s.scene || "分镜")}</span>
      <i class="edit-ico" title="修改这一镜的旁白"
         onclick="event.stopPropagation();openRevise(${s.index || i + 1})">✎</i></div>`;
    card.onclick = () => {
      const p = $("player");
      const t = (d.playAt || [])[i] || 0;
      if (p.readyState >= 1) { p.currentTime = t; p.play(); }
      document.querySelectorAll(".shot-card").forEach((c) => c.classList.remove("active"));
      card.classList.add("active");
    };
    strip.appendChild(card);
  });
}

function renderReport(r) {
  const box = $("report");
  box.classList.remove("hidden");
  $("reportScore").textContent = r.score;
  $("reportTitle").textContent = r.pass ? "质检通过 ✅" : "质检未通过（已自动回退重做）⚠️";
  $("reportSub").textContent =
    `第 ${r.round || 1} 轮 · ${(r.checks || []).filter((c) => c.ok).length}/${(r.checks || []).length} 项合格`
    + (r.issues && r.issues.length ? ` · ${r.issues.map((i) => i.message).join("；")}` : "");
  $("reportChecks").innerHTML = (r.checks || []).map((c) => `
    <div class="check">
      <span class="mark ${c.ok ? "ok" : "no"}">${c.ok ? "✔" : "✘"}</span>
      <span>${esc(c.name)}<span class="detail"> · ${esc(c.detail)}</span></span>
    </div>`).join("");
}

/* ==================== 工具栏 ==================== */
function toggleSubtitle() {
  state.subtitle = !state.subtitle;
  $("subtitleBtn").textContent = "字幕：" + (state.subtitle ? "开" : "关");
  $("subtitleBtn").classList.toggle("on", state.subtitle);
  if (state.projectId) {
    const t = $("player").currentTime;
    playVideo(state.projectId, state.subtitle, state.fmt);
    $("player").addEventListener("loadedmetadata", function once() {
      $("player").currentTime = t;
      $("player").removeEventListener("loadedmetadata", once);
    });
  }
}

function toggleFullscreen() {
  const el = $("videoStage");
  if (!document.fullscreenElement) {
    (el.requestFullscreen || el.webkitRequestFullscreen || (() => {})).call(el);
  } else {
    document.exitFullscreen();
  }
}

function exportVideo() {
  if (!state.projectId) return;
  const a = document.createElement("a");
  a.href = `/api/projects/${encodeURIComponent(state.projectId)}/video?subs=1`;
  a.download = (state.detail && state.detail.title ? state.detail.title : state.projectId) + ".mp4";
  document.body.appendChild(a); a.click(); a.remove();
}

function downloadSrt() {
  if (!state.projectId) return;
  window.open(`/api/projects/${encodeURIComponent(state.projectId)}/srt`, "_blank");
}

/* ==================== 少量干预点：修改后重做 ==================== */
function openRevise(focusIndex) {
  const d = state.detail;
  if (!d || !(d.shots || []).length) {
    alert("请先生成一个项目，再来修改。");
    return;
  }
  const sel = $("reviseTheme");
  sel.innerHTML = state.themes.map((t) =>
    `<option value="${t}" ${t === (d.theme || "deepsea") ? "selected" : ""}>${themeName(t)}</option>`).join("");

  $("editList").innerHTML = d.shots.map((s) => `
    <div class="edit-row">
      <div class="no">${String(s.index).padStart(2, "0")}<br>
        <span style="color:var(--muted-2);font-weight:400">${esc(s.scene)}</span></div>
      <textarea data-index="${s.index}" placeholder="（保持原样）">${esc(s.narration)}</textarea>
    </div>`).join("");
  $("reviseModal").classList.add("show");
  if (focusIndex) {
    const ta = $("editList").querySelector(`textarea[data-index="${focusIndex}"]`);
    if (ta) { ta.scrollIntoView({ block: "center" }); ta.focus(); }
  }
}

function closeRevise() { $("reviseModal").classList.remove("show"); }

function themeName(key) {
  return { deepsea: "深海蓝", scholar: "书院青", sunrise: "晨光橙" }[key] || key;
}

async function submitRevise() {
  if (!state.projectId) return;
  const theme = $("reviseTheme").value;
  const original = {};
  (state.detail.shots || []).forEach((s) => { original[s.index] = s.narration; });

  const edits = [];
  $("editList").querySelectorAll("textarea").forEach((ta) => {
    const idx = Number(ta.dataset.index);
    const val = ta.value.trim();
    if (val && val !== (original[idx] || "")) edits.push({ index: idx, narration: val });
  });

  const themeChanged = theme !== (state.detail.theme || "deepsea");
  if (!edits.length && !themeChanged) {
    appendLog("info", "没有检测到修改。");
    closeRevise();
    return;
  }

  $("reviseGo").disabled = true;
  $("reviseGo").textContent = "重做中…";
  const fd = new FormData();
  fd.append("theme", theme);
  fd.append("edits", JSON.stringify(edits));

  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(state.projectId)}/revise`,
      { method: "POST", body: fd });
    const d = await res.json();
    if (d.error) throw new Error(d.error);
    closeRevise();
    state.events = 0;
    state.running = true;
    resetPipeline();
    $("startBtn").disabled = true;
    $("startBtn").textContent = "⏳ Agent 重做中…";
    $("progressWrap").classList.add("show");
    setStage(true);
    setProgress(0, "正在定向重做…", 1);
    appendLog("warning", `开始重做：改文案 ${edits.length} 处`
      + (themeChanged ? `｜换配色 ${themeName(theme)}` : ""));
    poll();
  } catch (e) {
    appendLog("warning", "重做失败：" + e.message);
  } finally {
    $("reviseGo").disabled = false;
    $("reviseGo").textContent = "开始重做";
  }
}

/* ==================== 历史项目 ==================== */
async function loadProjects() {
  try {
    const d = await (await fetch("/api/projects")).json();
    const ul = $("projectList");
    ul.innerHTML = "";
    (d.items || []).forEach((p) => {
      const li = document.createElement("li");
      li.className = p.id === state.projectId ? "active" : "";
      li.innerHTML = `<span class="pt">${esc(p.title)}</span>
        <span class="pm">${p.created} · ${p.shots} 镜 · ${fmtDur(p.duration)}
        ${p.score != null ? " · 质检 " + p.score : ""}</span>`;
      li.onclick = () => {
        state.projectId = p.id;
        state.themeIndex = state.themes.indexOf(p.theme);
        setStageAspect(p.fmt);
        if (p.done) {
          playVideo(p.id, state.subtitle, p.fmt);
          loadDetail(p.id);
        } else {
          appendLog("info", "该项目尚未生成成片。");
        }
        document.querySelectorAll(".project-list li").forEach((x) => x.classList.remove("active"));
        li.classList.add("active");
      };
      ul.appendChild(li);
    });
    if (!(d.items || []).length) {
      ul.innerHTML = '<div class="empty" style="padding:16px 0">暂无历史项目</div>';
    }
  } catch (e) { /* 忽略 */ }
}

function openProject(pid) {
  state.projectId = pid;
  playVideo(pid, true);
  loadDetail(pid);
}

/* ==================== 日志 ==================== */
function appendLog(level, msg, t) {
  const box = $("logBox");
  const empty = box.querySelector(".log-empty");
  if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = "log-line " + (level || "info");
  div.innerHTML = `<span class="log-time">${t || ""}</span><span>${esc(msg)}</span>`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

init();
