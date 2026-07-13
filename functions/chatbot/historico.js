// functions/chatbot/historico.js
//
// Recebe eventos do chat (interface.html) e grava o histórico da conversa
// no Firestore, coleção "Historico", 1 documento por protocolo.
//
// Por que via Function e não direto do navegador?
// Este endpoint autentica no Firestore com uma Service Account (acesso
// Admin), o que permite deixar a coleção "Historico" totalmente fechada
// para leitura/escrita pública nas regras de segurança do Firestore —
// só esta Function (rodando no servidor da Cloudflare) consegue gravar.
//
// ── Variáveis de ambiente necessárias (Cloudflare Pages → Settings → Environment variables) ──
//   FIREBASE_PROJECT_ID    → ex: chatbot-eletrofro
//   FIREBASE_CLIENT_EMAIL  → do JSON da service account (campo "client_email")
//   FIREBASE_PRIVATE_KEY   → do JSON da service account (campo "private_key", COM as quebras
//                             de linha \n literais — cole exatamente como está no JSON)
//
// Como gerar a service account:
//   Firebase Console → Configurações do projeto → Contas de serviço →
//   "Gerar nova chave privada" → baixa um JSON com client_email e private_key.

const FIRESTORE_SCOPE = 'https://www.googleapis.com/auth/datastore';
const PROTOCOLO_RE = /^EF-\d{8}-\d{6}-\d{3}$/;
const TEXTO_MAX = 4000;

let _cachedToken = null; // { token, exp } — reaproveitado enquanto o isolate da Function viver

export async function onRequestOptions() {
  return new Response(null, { headers: corsHeaders() });
}

export async function onRequestPost({ request, env }) {
  try {
    const body = await request.json();
    const { protocolo, tipo } = body;

    if (!PROTOCOLO_RE.test(protocolo || '')) {
      return jsonResponse({ error: 'protocolo inválido' }, 400);
    }
    if (!['inicio', 'mensagem', 'fim'].includes(tipo)) {
      return jsonResponse({ error: 'tipo inválido' }, 400);
    }

    const accessToken = await getAccessToken(env);
    const docPath = `Historico/${protocolo}`;

    if (tipo === 'inicio') {
      await firestoreCommit(env, accessToken, [
        {
          update: {
            name: docName(env, docPath),
            fields: {
              protocolo:  fsString(protocolo),
              userName:   fsString(body.userName  || ''),
              userCargo:  fsString(body.userCargo || ''),
              userPhone:  fsString(body.userPhone || ''),
              pedido:     fsString(body.pedido    || ''),
              cliente:    fsString(body.cliente   || ''),
              status:     fsString('em_andamento'),
              mensagens:  { arrayValue: { values: [] } }
            }
          }
        },
        {
          transform: {
            document: docName(env, docPath),
            fieldTransforms: [
              { fieldPath: 'iniciadoEm',   setToServerValue: 'REQUEST_TIME' },
              { fieldPath: 'atualizadoEm', setToServerValue: 'REQUEST_TIME' }
            ]
          }
        }
      ]);
    }

    if (tipo === 'mensagem') {
      const role  = body.role === 'user' ? 'user' : 'bot';
      const texto = String(body.texto || '').slice(0, TEXTO_MAX);
      if (!texto) return jsonResponse({ ok: true }); // nada a salvar

      await firestoreCommit(env, accessToken, [
        {
          transform: {
            document: docName(env, docPath),
            fieldTransforms: [
              {
                fieldPath: 'mensagens',
                appendMissingElements: {
                  values: [{
                    mapValue: {
                      fields: {
                        role:  fsString(role),
                        texto: fsString(texto),
                        hora:  fsString(new Date().toISOString())
                      }
                    }
                  }]
                }
              },
              { fieldPath: 'atualizadoEm', setToServerValue: 'REQUEST_TIME' }
            ]
          }
        }
      ]);
    }

    if (tipo === 'fim') {
      await firestoreCommit(env, accessToken, [
        {
          update: { name: docName(env, docPath), fields: { status: fsString('finalizado') } },
          updateMask: { fieldPaths: ['status'] }
        },
        {
          transform: {
            document: docName(env, docPath),
            fieldTransforms: [{ fieldPath: 'atualizadoEm', setToServerValue: 'REQUEST_TIME' }]
          }
        }
      ]);
    }

    return jsonResponse({ ok: true });
  } catch (err) {
    console.error('[historico] erro:', err);
    return jsonResponse({ error: 'Falha ao salvar histórico' }, 500);
  }
}

// ── Firestore REST helpers ─────────────────────────────────────────────

function docName(env, path) {
  return `projects/${env.FIREBASE_PROJECT_ID}/databases/(default)/documents/${path}`;
}

function fsString(v) {
  return { stringValue: String(v) };
}

async function firestoreCommit(env, accessToken, writes) {
  const url = `https://firestore.googleapis.com/v1/projects/${env.FIREBASE_PROJECT_ID}/databases/(default)/documents:commit`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${accessToken}`
    },
    body: JSON.stringify({ writes })
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Firestore commit falhou (${res.status}): ${errText}`);
  }
  return res.json();
}

// ── Autenticação via Service Account (JWT assinado → access_token OAuth2) ──

async function getAccessToken(env) {
  const now = Math.floor(Date.now() / 1000);
  if (_cachedToken && _cachedToken.exp - 60 > now) {
    return _cachedToken.token;
  }

  const privateKey = env.FIREBASE_PRIVATE_KEY.replace(/\\n/g, '\n');
  const clientEmail = env.FIREBASE_CLIENT_EMAIL;

  const header = { alg: 'RS256', typ: 'JWT' };
  const claims = {
    iss: clientEmail,
    scope: FIRESTORE_SCOPE,
    aud: 'https://oauth2.googleapis.com/token',
    iat: now,
    exp: now + 3600
  };

  const unsigned = `${base64url(JSON.stringify(header))}.${base64url(JSON.stringify(claims))}`;
  const signature = await signRS256(unsigned, privateKey);
  const jwt = `${unsigned}.${signature}`;

  const res = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
      assertion: jwt
    })
  });

  if (!res.ok) {
    throw new Error(`Falha ao obter access_token (${res.status}): ${await res.text()}`);
  }

  const data = await res.json();
  _cachedToken = { token: data.access_token, exp: now + data.expires_in };
  return _cachedToken.token;
}

async function signRS256(data, pemPrivateKey) {
  const key = await crypto.subtle.importKey(
    'pkcs8',
    pemToArrayBuffer(pemPrivateKey),
    { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const sig = await crypto.subtle.sign(
    'RSASSA-PKCS1-v1_5',
    key,
    new TextEncoder().encode(data)
  );
  return base64url(sig);
}

function pemToArrayBuffer(pem) {
  const b64 = pem
    .replace('-----BEGIN PRIVATE KEY-----', '')
    .replace('-----END PRIVATE KEY-----', '')
    .replace(/\s/g, '');
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

function base64url(input) {
  let bytes;
  if (typeof input === 'string') {
    bytes = new TextEncoder().encode(input);
  } else {
    bytes = new Uint8Array(input);
  }
  let str = '';
  for (let i = 0; i < bytes.length; i++) str += String.fromCharCode(bytes[i]);
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

// ── CORS ─────────────────────────────────────────────────────────────

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type'
  };
}

function jsonResponse(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders() }
  });
}
