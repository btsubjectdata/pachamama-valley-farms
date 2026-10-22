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

  // Set to true once the restream is running, so the page embeds the live player
  // instead of the "coming soon" card.
  STREAM_ENABLED: false,

  // Direct live feed from the farm (HLS via Cloudflare Tunnel on the Mac mini).
  // Used whenever it's set; the YouTube embed takes over when STREAM_ENABLED is true.
  HLS_URL: "https://cam.pachamamavalleyfarms.com/bees.m3u8",
};
