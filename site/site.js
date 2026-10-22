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
    iframe.title = "Pachamama Valley Farms bee yard, live";
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
    v.title = "Pachamama Valley Farms bee yard, live";
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
        note.textContent = "Signups aren't wired up yet. Email info@pachamamavalleyfarms.com and we'll add you by hand.";
        note.dataset.state = "error";
      });
    });
  }
})();
