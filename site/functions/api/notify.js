// Cloudflare Pages Function: POST /api/notify
// Stores honey-notify signups in a KV namespace bound as NOTIFY_KV.
// Pages project → Settings → Functions → KV namespace bindings → add "NOTIFY_KV".
// Without the binding this returns 501 and the page shows the "email us" fallback.

export async function onRequestPost({ request, env }) {
  if (!env.NOTIFY_KV) return new Response("not configured", { status: 501 });
  let body;
  try { body = await request.json(); } catch { return new Response("bad json", { status: 400 }); }
  const email = String(body.email || "").trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254) {
    return new Response("bad email", { status: 400 });
  }
  await env.NOTIFY_KV.put("signup:" + email, JSON.stringify({
    email,
    at: new Date().toISOString(),
    ua: request.headers.get("user-agent") || ""
  }));
  return new Response(JSON.stringify({ ok: true }), {
    headers: { "Content-Type": "application/json" }
  });
}
