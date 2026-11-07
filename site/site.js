(function () {
  var cfg = window.PVF_CONFIG || {};

  // --- Live players --------------------------------------------------------
  // One player per camera. Each shows the farm's own HLS feed, and switches to the YouTube
  // player (higher quality, with sound) whenever the mini PC's watchdog reports that camera
  // live on YouTube (status.json, re-checked every minute). If YouTube drops, it falls back.
  function mountPlayer(o) {
    var frame = document.getElementById(o.frame), placeholder = document.getElementById(o.placeholder);
    var pill = document.getElementById(o.pill), watch = document.getElementById(o.watch);
    if (!frame || !placeholder || !pill) return null;
    var hlsUrl = (o.hlsUrl || "").trim();

    function setPill(state, text) { pill.dataset.state = state; pill.lastChild.textContent = text; }
    function showCard(text) { placeholder.hidden = false; placeholder.querySelector("p").textContent = text; }

    if (!hlsUrl) { setPill("offline", "Coming soon"); return null; }

    var v = document.createElement("video");
    v.muted = true; v.autoplay = true; v.playsInline = true; v.controls = true;
    v.setAttribute("muted", ""); v.setAttribute("playsinline", "");
    v.title = o.title;
    v.hidden = true;
    frame.appendChild(v);
    setPill("offline", "Connecting");

    var retryTimer = null, hls = null, ytFrame = null, ytId = null;
    v.addEventListener("playing", function () { placeholder.hidden = true; v.hidden = false; setPill("live", "Live"); });
    function onDown() {
      if (ytFrame) return;                      // YouTube is showing; the farm feed can stay quiet
      v.hidden = true;
      showCard(o.offlineText);
      setPill("offline", "Offline");
      clearTimeout(retryTimer); retryTimer = setTimeout(start, 30000);
    }
    function startHlsJs() {
      if (hls) { hls.destroy(); }
      hls = new window.Hls({ liveSyncDurationCount: 2, lowLatencyMode: false, manifestLoadingMaxRetry: 2 });
      hls.on(window.Hls.Events.ERROR, function (_e, data) { if (data.fatal) { hls.destroy(); hls = null; onDown(); } });
      hls.loadSource(hlsUrl);
      hls.attachMedia(v);
      hls.on(window.Hls.Events.MANIFEST_PARSED, function () { v.play().catch(function () {}); });
    }
    function start() {
      if (ytFrame) return;
      if (v.canPlayType("application/vnd.apple.mpegurl")) {          // Safari, iOS
        v.src = hlsUrl + "?t=" + Date.now();
        v.onerror = onDown;
        v.play().catch(function () {});
      } else if (window.Hls) {
        startHlsJs();
      } else {
        loadHlsJs(function (ok) { ok ? startHlsJs() : onDown(); });
      }
    }
    function useYouTube(id) {
      if (ytFrame && ytId === id) return;
      if (ytFrame) ytFrame.remove();
      ytId = id;
      ytFrame = document.createElement("iframe");
      ytFrame.src = "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(id) + "?autoplay=1&mute=1&playsinline=1&rel=0";
      ytFrame.title = o.title;
      ytFrame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
      ytFrame.setAttribute("allowfullscreen", "");
      frame.appendChild(ytFrame);
      v.hidden = true; v.pause(); placeholder.hidden = true;
      if (hls) { hls.destroy(); hls = null; }
      clearTimeout(retryTimer);
      if (watch) watch.href = "https://www.youtube.com/watch?v=" + encodeURIComponent(id);
      setPill("live", "Live");
    }
    function useFarmFeed() {
      if (!ytFrame) return;
      ytFrame.remove(); ytFrame = null; ytId = null;
      if (watch && o.watchDefault) watch.href = o.watchDefault;
      start();
    }
    start();
    return { update: function (st) { if (st && st.youtube_live && st.video_id) useYouTube(st.video_id); else useFarmFeed(); } };
  }

  var hlsLoading = null;
  function loadHlsJs(cb) {
    if (window.Hls) return cb(window.Hls.isSupported());
    if (!hlsLoading) {
      hlsLoading = [];
      var sc = document.createElement("script");
      sc.src = "https://cdnjs.cloudflare.com/ajax/libs/hls.js/1.5.13/hls.min.js";
      sc.onload = function () { var ok = !!(window.Hls && window.Hls.isSupported()); hlsLoading.forEach(function (f) { f(ok); }); hlsLoading = null; };
      sc.onerror = function () { hlsLoading.forEach(function (f) { f(false); }); hlsLoading = null; };
      document.head.appendChild(sc);
    }
    hlsLoading.push(cb);
  }

  var players = {
    bees: mountPlayer({
      frame: "stream-frame", placeholder: "stream-placeholder", pill: "live-pill", watch: "watch-on-yt",
      hlsUrl: cfg.HLS_URL, title: "Pachamama Valley Farm bee yard, live",
      watchDefault: "https://www.youtube.com/@PachamamaValleyFarm/live",
      offlineText: "The bee yard camera is taking a break. It reconnects on its own; check back in a few minutes."
    }),
    hog: mountPlayer({
      frame: "hog-frame", placeholder: "hog-placeholder", pill: "hog-pill", watch: "hog-watch-on-yt",
      hlsUrl: cfg.HOG_HLS_URL, title: "Pachamama Valley Farm hog trap, live",
      watchDefault: "https://www.youtube.com/@PachamamaValleyFarm/streams",
      offlineText: "The hog trap camera is taking a break. It reconnects on its own; check back in a few minutes."
    })
  };

  var statusUrl = (cfg.STATUS_URL || "").trim();
  function poll() {
    fetch(statusUrl + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (st) {
        var cams = (st && st.cams) || {};
        if (players.bees) players.bees.update(cams.bees || st);     // older status files had only the bee cam at top level
        if (players.hog) players.hog.update(cams.hog);
      })
      .catch(function () {});
  }
  if (statusUrl) { poll(); setInterval(poll, 60000); }

  // --- Local time in the caption ------------------------------------------
  var timeEls = Array.prototype.slice.call(document.querySelectorAll(".local-time"));
  function tick() {
    var now = new Date(), text = "";
    try {
      text = now.toLocaleTimeString("en-US", {
        hour: "numeric", minute: "2-digit", timeZone: cfg.TIMEZONE || "America/Chicago", timeZoneName: "short"
      }) + " at the farm";
    } catch (e) {}
    timeEls.forEach(function (el) { el.textContent = text; el.setAttribute("datetime", now.toISOString()); });
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
