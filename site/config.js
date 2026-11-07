// Pachamama Valley Farm — site configuration
// Edit this file only. Nothing else needs to change when the stream moves.

window.PVF_CONFIG = {
  // YouTube channel ID (starts with "UC"). YouTube Studio → Settings → Channel → Advanced settings.
  // With the channel ID the page always embeds whatever is live on the channel right now,
  // so you never have to update the site when a stream restarts.
  YT_CHANNEL_ID: "UCC_K8NxiSnY6MprpPPB7NRg",

  // Optional: pin a specific live video instead of "whatever is live". Leave empty to use the channel.
  YT_VIDEO_ID: "",

  // Shown in the caption under the feed.
  TIMEZONE: "America/Chicago",

  // Local weather in the caption, from the National Weather Service (free, no key).
  // KJDD = Wood County Airport, Quitman, the nearest reporting station to the farm. Empty string turns it off.
  WEATHER_STATION: "KJDD",

  // Set to true once the restream is running, so the page embeds the live player
  // instead of the "coming soon" card.
  STREAM_ENABLED: false,

  // Direct live feeds from the farm (HLS via Cloudflare Tunnel from the mini PC).
  // Used whenever set; the YouTube player takes over whenever the watchdog says that camera is live there.
  HLS_URL: "https://cam.pachamamavalleyfarms.com/bees.m3u8",
  HOG_HLS_URL: "https://cam.pachamamavalleyfarms.com/hog.m3u8",

  // Written every 2 minutes by the YouTube watchdog on the mini PC. Per camera (cams.bees, cams.hog): when it says YouTube is live,
  // the page shows the YouTube player (with sound); otherwise it stays on the farm feed.
  STATUS_URL: "https://cam.pachamamavalleyfarms.com/status.json",
};
