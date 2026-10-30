(function () {
  var cfg = window.PVF_CONFIG || {};
  var frame = document.getElementById("stream-frame");
  var placeholder = document.getElementById("stream-placeholder");
  var pill = document.getElementById("live-pill");
  var watch = document.getElementById("watch-on-yt");

  // --- Live stream ---------------------------------------------------------
  // Order of preference: YouTube Live (when STREAM_ENABLED), else the direct HLS feed,
  // else the "coming soon" card.
  var channel = (cfg.YT_CHANNEL_ID || "").trim();
  var video = (cfg.YT_VIDEO_ID || "").trim();
  var useYouTube = cfg.STREAM_ENABLED && (video || channel);
  var hlsUrl = (cfg.HLS_URL || "").trim();

  function setPill(state, text) { pill.dataset.state = state; pill.lastChild.textContent = text; }
  function showCard(text) {
    placeholder.hidden = false;
    placeholder.querySelector("p").textContent = text;
  }

  if (useYouTube) {
    var src = video
      ? "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(video)
      : "https://www.youtube-nocookie.com/embed/live_stream?channel=" + encodeURIComponent(channel);
    src += (src.indexOf("?") === -1 ? "?" : "&") + "autoplay=1&mute=1&playsinline=1&rel=0";
    var iframe = document.createElement("iframe");
    iframe.src = src;
    iframe.title = "Pachamama Valley Farm bee yard, live";
    iframe.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    iframe.setAttribute("allowfullscreen", "");
    placeholder.hidden = true;
    frame.appendChild(iframe);
    watch.href = video
      ? "https://www.youtube.com/watch?v=" + encodeURIComponent(video)
      : "https://www.youtube.com/channel/" + encodeURIComponent(channel) + "/live";
    setPill("live", "Live");
  } else if (hlsUrl) {
    var v = document.createElement("video");
    v.muted = true; v.autoplay = true; v.playsInline = true; v.controls = true;
    v.setAttribute("muted", ""); v.setAttribute("playsinline", "");
    v.title = "Pachamama Valley Farm bee yard, live";
    v.hidden = true;
    frame.appendChild(v);
    setPill("offline", "Connecting");

    var retryTimer = null, hls = null;
    function onPlaying() { placeholder.hidden = true; v.hidden = false; setPill("live", "Live"); }
    function onDown() {
      v.hidden = true;
      showCard("The bee yard camera is taking a break. It reconnects on its own; check back in a few minutes.");
      setPill("offline", "Offline");
      clearTimeout(retryTimer); retryTimer = setTimeout(start, 30000);
    }
    v.addEventListener("playing", onPlaying);

    function startHlsJs() {
      if (hls) { hls.destroy(); }
      hls = new window.Hls({ liveSyncDurationCount: 2, lowLatencyMode: false, manifestLoadingMaxRetry: 2 });
      hls.on(window.Hls.Events.ERROR, function (_e, data) { if (data.fatal) { hls.destroy(); hls = null; onDown(); } });
      hls.loadSource(hlsUrl);
      hls.attachMedia(v);
      hls.on(window.Hls.Events.MANIFEST_PARSED, function () { v.play().catch(function () {}); });
    }
    function start() {
      if (v.canPlayType("application/vnd.apple.mpegurl")) {          // Safari, iOS
        v.src = hlsUrl + "?t=" + Date.now();
        v.onerror = onDown;
        v.play().catch(function () {});
      } else if (window.Hls) {
        startHlsJs();
      } else {
        var sc = document.createElement("script");
        sc.src = "https://cdnjs.cloudflare.com/ajax/libs/hls.js/1.5.13/hls.min.js";
        sc.onload = function () { window.Hls && window.Hls.isSupported() ? startHlsJs() : onDown(); };
        sc.onerror = onDown;
        document.head.appendChild(sc);
      }
    }
    start();

    // Watchdog switch: when the mini PC reports YouTube is live, show YouTube (4K with sound);
    // otherwise keep the farm's own feed. Re-checked every minute.
    var statusUrl = (cfg.STATUS_URL || "").trim(), ytFrame = null, ytId = null;
    function useYouTube(id) {
      if (ytFrame && ytId === id) return;
      if (ytFrame) ytFrame.remove();
      ytId = id;
      ytFrame = document.createElement("iframe");
      ytFrame.src = "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(id) + "?autoplay=1&mute=1&playsinline=1&rel=0";
      ytFrame.title = "Pachamama Valley Farm bee yard, live";
      ytFrame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
      ytFrame.setAttribute("allowfullscreen", "");
      frame.appendChild(ytFrame);
      v.hidden = true; v.pause(); placeholder.hidden = true;
      if (hls) { hls.destroy(); hls = null; }
      clearTimeout(retryTimer);
      watch.href = "https://www.youtube.com/watch?v=" + encodeURIComponent(id);
      setPill("live", "Live");
    }
    function useFarmFeed() {
      if (!ytFrame) return;
      ytFrame.remove(); ytFrame = null; ytId = null;
      start();
    }
    function poll() {
      fetch(statusUrl + "?t=" + Date.now(), { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (st) { if (st && st.youtube_live && st.video_id) useYouTube(st.video_id); else useFarmFeed(); })
        .catch(function () {});
    }
    if (statusUrl) { poll(); setInterval(poll, 60000); }
  } else {
    setPill("offline", "Coming soon");
  }

  // --- Local time in the caption ------------------------------------------
  var timeEl = document.getElementById("local-time");
  function tick() {
    try {
      var now = new Date();
      timeEl.textContent = now.toLocaleTimeString("en-US", {
        hour: "numeric", minute: "2-digit", timeZone: cfg.TIMEZONE || "America/Chicago", timeZoneName: "short"
      }) + " at the farm";
      timeEl.setAttribute("datetime", now.toISOString());
    } catch (e) { timeEl.textContent = ""; }
  }
  tick();
  setInterval(tick, 30000);

  // --- Footer year ----------------------------------------------------------
  var y = document.getElementById("year");
  if (y) y.textContent = String(new Date().getFullYear());

  // --- Honey notify form ----------------------------------------------------
  // Static site: there is no server. This posts to a Cloudflare Pages Function
  // at /api/notify if one exists; otherwise it just confirms locally.
  var form = document.getElementById("notify-form");
  var note = document.getElementById("notify-note");
  if (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var input = document.getElementById("notify-email");
      var email = (input.value || "").trim();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        note.textContent = "That doesn't look like an email address.";
        note.dataset.state = "error";
        input.focus();
        return;
      }
      note.textContent = "Saving…";
      fetch("/api/notify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email })
      }).then(function (r) {
        if (!r.ok) throw new Error("no endpoint");
        note.textContent = "Saved. You'll get one email when the first jars are ready.";
        note.dataset.state = "done";
        form.reset();
      }).catch(function () {
        note.textContent = "Signups aren't wired up yet. Email info@pachamamavalleyfarm.com and we'll add you by hand.";
        note.dataset.state = "error";
      });
    });
  }
})();

/* Gallery: filters + lightbox */
(function () {
  var grid = document.getElementById("g-grid");
  var box = document.getElementById("g-box");
  if (!grid || !box) return;
  var items = Array.prototype.slice.call(grid.querySelectorAll(".g-item"));
  var img = document.getElementById("g-img"), cap = document.getElementById("g-cap");
  var cur = 0;

  document.querySelectorAll(".g-filters button").forEach(function (b) {
    b.addEventListener("click", function () {
      var f = b.dataset.f;
      document.querySelectorAll(".g-filters button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
      items.forEach(function (it) { it.hidden = !(f === "all" || it.dataset.cat === f); });
    });
  });

  function visible() { return items.filter(function (it) { return !it.hidden; }); }
  function show(i) {
    var v = visible(); if (!v.length) return;
    cur = (i + v.length) % v.length;
    var it = v[cur], a = it.querySelector("a"), t = it.querySelector("img");
    img.src = a.dataset.full; img.alt = t.alt; cap.textContent = it.querySelector("figcaption").textContent;
  }
  if (typeof box.showModal !== "function") return; // old browsers: links open the full image

  items.forEach(function (it) {
    it.querySelector("a").addEventListener("click", function (e) {
      e.preventDefault();
      show(visible().indexOf(it));
      box.showModal();
    });
  });
  box.addEventListener("click", function (e) {
    var act = e.target.closest && e.target.closest("[data-act]");
    if (act) {
      var a = act.dataset.act;
      if (a === "close") box.close(); else show(cur + (a === "next" ? 1 : -1));
    } else if (e.target === box) box.close();
  });
  document.addEventListener("keydown", function (e) {
    if (!box.open) return;
    if (e.key === "ArrowRight") show(cur + 1);
    if (e.key === "ArrowLeft") show(cur - 1);
  });
  var x0 = null;
  box.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; }, { passive: true });
  box.addEventListener("touchend", function (e) {
    if (x0 === null) return;
    var dx = e.changedTouches[0].clientX - x0; x0 = null;
    if (Math.abs(dx) > 50) show(cur + (dx < 0 ? 1 : -1));
  });
})();

/* Hero parallax: photo moves at ~40% of scroll speed */
(function () {
  var hero = document.querySelector(".hero"), photo = document.querySelector(".hero-photo");
  if (!hero || !photo) return;
  if (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  var ticking = false;
  function update() {
    ticking = false;
    var h = hero.offsetHeight, y = window.scrollY;
    if (y > h) return;
    photo.style.setProperty("--parallax", (y * 0.4).toFixed(1) + "px");
  }
  window.addEventListener("scroll", function () { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
  update();
})();
