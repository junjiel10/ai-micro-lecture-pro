/* ==========================================================================
   妙课生花 WonderKourse · 全站共用的小交互
   --------------------------------------------------------------------------
   1) 轻提示 Toast          —— toast(msg)
   2) 顶栏「登录 / 注册」    —— 演示版占位，点一下说明现状，不跳转
   3) 顶栏折叠菜单           —— 顶部 .nav / .topbar，需要对应的面板与开关元素
   4) 弹窗 .modal-mask       —— 支持 Esc 与点遮罩空白处关闭

   不依赖任何页面专属脚本，index / guide 都直接引入。
   设计原则同 .reveal：**默认可用**。JS 没跑起来时导航仍是平铺的横向链接，
   不会出现「按钮在、点不动」或者「菜单收起来、没有入口」的死状态。
   ========================================================================== */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  /* ==================== 1. 轻提示 ==================== */
  var toastTimer = null;

  function toast(msg) {
    var host = $("toastHost");
    if (!host) {
      host = document.createElement("div");
      host.id = "toastHost";
      host.className = "toast-host";
      document.body.appendChild(host);
    }
    host.innerHTML =
      '<div class="toast" role="status" aria-live="polite" title="点击关闭">' +
      '<span class="toast-mark" aria-hidden="true"></span>' +
      '<span class="toast-text">' + esc(msg) + "</span></div>";
    host.firstElementChild.addEventListener("click", hideToast);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, 4600);   // 连点只留最新一条，并重新计时
  }

  function hideToast() {
    clearTimeout(toastTimer);
    var host = $("toastHost");
    var el = host && host.firstElementChild;
    if (!el) return;
    el.classList.add("is-out");
    setTimeout(function () { host.innerHTML = ""; }, 240);
  }

  var LOGIN_NOTICE = "演示版免登录，直接体验；正式版将支持账号体系与个人作品库。";

  window.toast = toast;   // 供调试与后续复用

  /* 口令状态缓存。
     /api/auth 返回 {required, authed} —— 只说明「要不要口令」「当前过没过」，
     不含口令本身。每次都问会白跑请求，所以缓存住；验证成功后再作废。 */
  var authPromise = null;

  function fetchAuth() {
    if (!authPromise) {
      authPromise = fetch("/api/auth", { cache: "no-store" })
        .then(function (r) {
          return r.ok ? r.json() : { required: false, authed: true };
        })
        .catch(function () {
          // 探测失败就当作「不需要口令」，让请求照发 ——
          // 后端仍会自己校验，真需要的话会返 401，由调用方提示。
          return { required: false, authed: true };
        });
    }
    return authPromise;
  }

  window.getAuth = fetchAuth;      // 供 create.js 判断要不要显示「删除」
  window.ensurePass = ensurePass;  // 需要口令的动作，调用前先 await 它

  /* ==================== 2 / 3. 顶栏 ==================== */
  var collapses = [];   // 每个折叠实例：{ box, set }

  /* 一个折叠实例 = 一个「外壳」+ 一块「面板」+ 一个开关按钮 */
  function initCollapse(box, panel, toggle) {
    if (!box || !panel || !toggle) return null;

    // 只有 JS 确认接管了，窄屏才把面板收起来（CSS 认这个类）
    box.classList.add("nav-collapse");

    var api = {
      box: box,
      set: function (open) {
        box.classList.toggle("nav-open", open);
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        toggle.setAttribute("aria-label", open ? "关闭导航菜单" : "打开导航菜单");
      }
    };

    toggle.addEventListener("click", function (e) {
      e.stopPropagation();                    // 别让下面那个「点外部关闭」立刻把它关上
      api.set(!box.classList.contains("nav-open"));
    });

    // 点面板里的任意项（链接或按钮）后收起，避免面板盖住刚跳过去的内容
    panel.addEventListener("click", function (e) {
      if (e.target.closest("a, button")) api.set(false);
    });

    collapses.push(api);
    return api;
  }

  function initNav() {
    /* 「登录 / 注册」是视觉占位：不跳转、不登录，点一下只说明现状。
       云端在「开始制作」时会另外弹口令框，跟这个按钮没关系。 */
    var login = $("loginBtn");
    if (login) login.addEventListener("click", function () { toast(LOGIN_NOTICE); });

    initCollapse(document.querySelector(".nav"), $("navLinks"), $("navToggle"));       // 首页 / 指南页
    initCollapse(document.querySelector(".topbar"), $("topActions"), $("topToggle"));  // 创作台
    if (!collapses.length) return;

    var each = function (fn) { collapses.forEach(fn); };
    each(function (c) { c.set(false); });     // 初始一律收起

    document.addEventListener("click", function (e) {
      each(function (c) { if (!c.box.contains(e.target)) c.set(false); });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") each(function (c) { c.set(false); });
    });

    // 拉回桌面宽度时复位，免得再缩回来时残留展开态
    window.addEventListener("resize", function () {
      if (window.innerWidth > 768) each(function (c) { c.set(false); });
    });
  }

  /* ==================== 4. 弹窗：Esc / 点遮罩关闭 ==================== */
  /* 只针对 .modal-mask。
     播放器用的是 .player-mask，它关闭时要暂停并清掉 video.src，
     得走 closePlayer()，不能在这里一刀切。 */
  function initModals() {
    var masks = document.querySelectorAll(".modal-mask");
    if (!masks.length) return;

    Array.prototype.forEach.call(masks, function (mask) {
      mask.addEventListener("click", function (e) {
        // 只有点在遮罩本身（弹窗外的空白）才关，点弹窗内部不关
        if (e.target === mask) mask.classList.remove("show");
      });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      Array.prototype.forEach.call(
        document.querySelectorAll(".modal-mask.show"),
        function (mask) { mask.classList.remove("show"); }
      );
    });
  }

  /* ==================== 5. 创作口令弹窗 ==================== */
  /* 浏览全站不需要口令，只有「开始创作」这类会真烧 CPU 和大模型额度的动作
     才要。后端在那些接口上强制校验（绕过页面直接打接口照样 401），
     这里只负责在那一刻把框弹出来。
     ensurePass() 返回 Promise<boolean>： true = 可以继续，false = 用户取消。 */
  var passEls = null;
  var passResolve = null;
  var passPromise = null;

  function buildPassModal() {
    if (passEls) return;
    var mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.id = "passModal";
    mask.innerHTML =
      '<div class="modal" style="width:min(420px,100%)">' +
        '<div class="modal-head">' +
          '<b>开始创作需要口令</b>' +
          '<span class="fx" data-pass="cancel">✕</span>' +
        '</div>' +
        '<p class="modal-tip">浏览全站和播放示例都不用口令。<br>' +
          '但<b>生成视频会真实占用服务器 CPU 和大模型额度</b>，' +
          '所以在这一步核一下身份。</p>' +
        '<div class="field">' +
          '<label for="passInput">访问口令</label>' +
          '<input id="passInput" type="password" autocomplete="current-password" ' +
            'placeholder="请输入口令">' +
        '</div>' +
        '<p class="pass-err" id="passErr" role="alert"></p>' +
        '<div class="modal-foot">' +
          '<button class="btn ghost" type="button" data-pass="cancel">取消</button>' +
          '<button class="btn primary" type="button" data-pass="go">确认并开始</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(mask);

    passEls = {
      mask: mask,
      input: mask.querySelector("#passInput"),
      err: mask.querySelector("#passErr"),
      go: mask.querySelector('[data-pass="go"]')
    };

    mask.addEventListener("click", function (e) {
      if (e.target === mask) { settlePass(false); return; }   // 点遮罩空白 = 取消
      var act = e.target.getAttribute && e.target.getAttribute("data-pass");
      if (act === "cancel") settlePass(false);
      else if (act === "go") submitPass();
    });
    // Esc 取消：输入框有焦点，keydown 会冒泡到面板上
    mask.addEventListener("keydown", function (e) {
      if (e.key === "Escape") settlePass(false);
    });
    passEls.input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); submitPass(); }
    });
  }

  function settlePass(ok) {
    var done = passResolve;
    passResolve = null;
    passPromise = null;
    if (passEls) passEls.mask.classList.remove("show");
    if (done) done(ok);
  }

  function openPassModal() {
    buildPassModal();
    if (passPromise) return passPromise;      // 已经在问了，别重复弹
    passEls.err.textContent = "";
    passEls.input.value = "";
    passEls.mask.classList.add("show");
    setTimeout(function () { passEls.input.focus(); }, 60);
    passPromise = new Promise(function (resolve) { passResolve = resolve; });
    return passPromise;
  }

  async function submitPass() {
    var pw = (passEls.input.value || "").trim();
    if (!pw) { passEls.err.textContent = "请先输入口令。"; return; }
    passEls.go.disabled = true;
    passEls.go.textContent = "验证中…";
    try {
      var fd = new FormData();
      fd.append("password", pw);
      var r = await fetch("/api/auth", { method: "POST", body: fd });
      var d = await r.json().catch(function () { return {}; });
      if (!r.ok) {
        passEls.err.textContent = d.error || ("验证失败（" + r.status + "）");
        passEls.input.select();
        return;
      }
      authPromise = null;        // 状态变了，作废缓存
      settlePass(true);
    } catch (e) {
      passEls.err.textContent = "网络错误：" + e.message;
    } finally {
      passEls.go.disabled = false;
      passEls.go.textContent = "确认并开始";
    }
  }

  function ensurePass() {
    return fetchAuth().then(function (a) {
      if (!a.required || a.authed) return true;
      return openPassModal();
    });
  }

  function boot() {
    initNav();
    initModals();
    // 先建好藏着。它晚于 initModals 建，所以 Esc / 点遮罩由自己的监听接管，
    // 与 initModals 里那套互不干扰。
    buildPassModal();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
