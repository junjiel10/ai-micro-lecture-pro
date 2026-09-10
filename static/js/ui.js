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
  var LOGOUT_HINT = "已通过访问口令进入。点击退出后，下次需要重新输入口令。";

  window.toast = toast;   // 供调试与后续复用

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
    /* 「登录 / 注册」按部署环境自动变身：
         · 本机自用（没设口令）—— 保留占位按钮，点一下说明「免登录」
         · 公网部署（设了口令）—— 已经是登录状态，按钮改成「退出登录」
       不然会很难受：页面上写着「登录 / 注册」，点一下却告诉你「免登录」，
       可你刚刚才输过口令。 */
    var login = $("loginBtn");
    if (login) {
      login.addEventListener("click", function () {
        if (login.dataset.logout === "1") { window.location.href = "/logout"; return; }
        toast(LOGIN_NOTICE);
      });
      // 先按占位行为渲染，探测到要口令再改（探测失败就保持占位）
      fetch("/api/health", { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || !d.auth_required) return;
          login.textContent = "退出登录";
          login.dataset.logout = "1";
          login.title = LOGOUT_HINT;
          login.setAttribute("aria-label", "退出登录");
        })
        .catch(function () { /* 保持占位行为 */ });
    }

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

  function boot() {
    initNav();
    initModals();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
