// ================================================================
// Cloudflare Worker — Construtor de Chatbot
//
// Faz duas coisas:
//   GET  /          → serve o construtor.html
//   GET  /config    → retorna as credenciais do Firebase (salvas
//                     como Secrets no Cloudflare, nunca no HTML)
// ================================================================

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // ── Rota /config — entrega as credenciais do Firebase ──────
    // O construtor.html busca esse endpoint ao iniciar.
    // As variáveis vêm dos Secrets configurados no painel do Cloudflare.
    if (url.pathname === '/config') {
      const config = {
        apiKey:            env.FB_API_KEY,
        authDomain:        env.FB_AUTH_DOMAIN,
        projectId:         env.FB_PROJECT_ID,
        storageBucket:     env.FB_STORAGE_BUCKET,
        messagingSenderId: env.FB_MESSAGING_SENDER_ID,
        appId:             env.FB_APP_ID,
      };
      return new Response(JSON.stringify(config), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // ── Rota / — serve o construtor.html ───────────────────────
    // O HTML fica nos Static Assets do Worker (você faz upload dele).
    return env.ASSETS.fetch(request);
  },
};
