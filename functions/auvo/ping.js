export async function onRequestGet() {
  return Response.json({ ok: true, msg: "auvo_proxy online (Cloudflare Pages Functions)" });
}

export async function onRequestOptions() {
  return new Response(null, {
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
}
