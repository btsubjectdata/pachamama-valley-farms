(function () {
  var cfg = window.PVF_CONFIG || {};
  var frame = document.getElementById("stream-frame");
  var placeholder = document.getElementById("stream-placeholder");
  var pill = document.getElementById("live-pill");
  var watch = document.getElementById("watch-on-yt");

  // --- Live stream embed -------------------------------------------------
  var channel = (cfg.YT_CHANNEL_ID || "").trim();
  var video = (cfg.YT_VIDEO_ID || "").trim();
  var configured = cfg.STREAM_ENABLED && (video || (channel && channel.indexOf("REPLACE") === -1));

  if (configured) {
    var src = video
      ? "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(video)
      : "https://www.youtube-nocookie.com/embed/live_stream?channel=" + encodeURIComponent(channel);
    src += (src.indexOf("?") === -1 ? "?" : "&") + "autoplay=1&mute=1&playsinline=1&rel=0";

    var iframe = document.createElement("iframe");
    iframe.src = src;
    iframe.title = "Pachamama Valley Farms bee yard, live";
    iframe.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    iframe.setAttribute("allowfullscreen", "");
    iframe.loading = "lazy";
    placeholder.hidden = true;
    frame.appendChild(iframe);

    watch.href = video
      ? "https://www.youtube.com/watch?v=" + encodeURIComponent(video)
      : "https://www.youtube.com/channel/" + encodeURIComponent(channel) + "/live";
    pill.dataset.state = "live";
  } else {
    pill.dataset.state = "offline";
    pill.lastChild.textContent = "Coming soon";
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
