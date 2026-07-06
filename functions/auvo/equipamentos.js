// functions/auvo/equipamentos.js
// Porta do auvo_proxy.py (Flask) para Cloudflare Pages Functions.
//
// Endpoint: POST /auvo/equipamentos
// Body:     { "externalId": "PED 077-055/19", "descricaoFiltro": "teste" (opcional) }
//
// Variáveis de ambiente necessárias (configurar no dashboard do Cloudflare Pages
// em Settings > Environment variables):
//   AUVO_API_KEY
//   AUVO_API_TOKEN
//
// Opcional: se você criar um KV namespace e vincular como `AUVO_KV`,
// o token de login passa a ser reaproveitado entre chamadas (ver comentário
// na função obterToken). Sem o KV, a function simplesmente faz login a cada
// requisição — funciona normalmente, só gasta uma chamada extra à Auvo.

const BASE_URL = "https://api.auvo.com.br/v2";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...CORS_HEADERS },
  });
}

export async function onRequestOptions() {
  return new Response(null, { headers: CORS_HEADERS });
}

// ── Helpers ──────────────────────────────────────────────────────────────

function formatarDataBR(dataIso) {
  if (!dataIso) return "";
  const texto = String(dataIso).trim();
  const match = texto.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return texto; // não reconheceu o formato — devolve como veio
  const [, ano, mes, dia] = match;
  return `${dia}/${mes}/${ano}`;
}

function extrairLista(dados) {
  const result = dados?.result;
  if (Array.isArray(result)) return result;
  if (result && typeof result === "object") {
    return result.entityList || result.data || [];
  }
  if (Array.isArray(dados)) return dados;
  return [];
}

async function obterToken(env) {
  // Cache simples via KV, se o binding AUVO_KV estiver configurado.
  if (env.AUVO_KV) {
    const cached = await env.AUVO_KV.get("auvo_token", { type: "json" });
    if (cached && cached.expiration - Date.now() / 1000 > 300) {
      return cached.token;
    }
  }

  const resp = await fetch(`${BASE_URL}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apiKey: env.AUVO_API_KEY, apiToken: env.AUVO_API_TOKEN }),
  });

  if (!resp.ok) {
    throw new Error(`Login Auvo falhou com HTTP ${resp.status}`);
  }

  const dados = await resp.json();
  const token = dados?.result?.accessToken;
  if (!token) throw new Error("Login Auvo não retornou accessToken");

  let expirationTs = Date.now() / 1000 + 3600; // fallback: 1h
  const expStr = dados.result?.expiration;
  if (expStr) {
    const parsed = Date.parse(expStr.replace(" ", "T"));
    if (!Number.isNaN(parsed)) expirationTs = parsed / 1000;
  }

  if (env.AUVO_KV) {
    await env.AUVO_KV.put(
      "auvo_token",
      JSON.stringify({ token, expiration: expirationTs }),
      { expirationTtl: Math.max(60, Math.floor(expirationTs - Date.now() / 1000)) }
    );
  }

  return token;
}

async function buscarClientePaginado(token, externalId) {
  const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  let pagina = 1;
  const pageSize = 10;

  while (true) {
    const url = `${BASE_URL}/customers/?${new URLSearchParams({ page: pagina, pageSize })}`;
    const resp = await fetch(url, { headers });
    if (!resp.ok) return null;

    const clientes = extrairLista(await resp.json());
    if (!clientes.length) return null;

    const encontrado = clientes.find(
      (c) => String(c.externalId ?? "").trim() === externalId.trim()
    );
    if (encontrado) return encontrado;

    if (clientes.length < pageSize) return null;

    pagina += 1;
    await new Promise((r) => setTimeout(r, 500));
  }
}

async function buscarEquipamentosPorCliente(token, customerId) {
  const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  let pagina = 1;
  const pageSize = 50;
  const encontrados = [];

  while (true) {
    const url = `${BASE_URL}/equipments/?${new URLSearchParams({ page: pagina, pageSize })}`;
    let resp;
    try {
      resp = await fetch(url, { headers });
    } catch {
      break;
    }
    if (!resp.ok) break;

    const equipamentos = extrairLista(await resp.json());
    if (!equipamentos.length) break;

    for (const equip of equipamentos) {
      if (String(equip.associatedCustomerId ?? "").trim() === String(customerId)) {
        encontrados.push(equip);
      }
    }

    if (equipamentos.length < pageSize) break;
    pagina += 1;
  }

  return encontrados;
}

function selecionarEquipamentoPorDescricao(equipamentosNormalizados, descricaoAlvo) {
  const alvo = descricaoAlvo.trim().toLowerCase();
  return (
    equipamentosNormalizados.find(
      (e) => String(e.descricao ?? "").trim().toLowerCase() === alvo
    ) || null
  );
}

// ── Handler ──────────────────────────────────────────────────────────────

export async function onRequestPost({ request, env }) {
  let body;
  try {
    body = await request.json();
  } catch {
    body = {};
  }

  const externalId = (body.externalId || "").trim();
  const descricaoFiltro = (body.descricaoFiltro || "teste").trim();

  if (!externalId) {
    return jsonResponse({ ok: false, erro: "Campo 'externalId' é obrigatório." }, 400);
  }

  let token;
  try {
    token = await obterToken(env);
  } catch (e) {
    return jsonResponse({ ok: false, erro: `Falha na autenticação Auvo: ${e.message}` }, 502);
  }

  let cliente;
  try {
    cliente = await buscarClientePaginado(token, externalId);
  } catch (e) {
    return jsonResponse({ ok: false, erro: `Erro ao buscar cliente: ${e.message}` }, 502);
  }

  if (!cliente) {
    return jsonResponse(
      { ok: false, erro: `Cliente com externalId '${externalId}' não encontrado.` },
      404
    );
  }

  const customerId = cliente.id;

  let equipamentosRaw;
  try {
    equipamentosRaw = await buscarEquipamentosPorCliente(token, customerId);
  } catch (e) {
    return jsonResponse({ ok: false, erro: `Erro ao buscar equipamentos: ${e.message}` }, 502);
  }

  const equipamentosNormalizados = equipamentosRaw.map((equip) => ({
    id: equip.id,
    descricao: equip.description || "",
    vencimento: formatarDataBR(equip.expirationDate || ""),
    expirationDate: equip.expirationDate || "",
    modelo: equip.model || "",
    serie: equip.serialNumber || "",
  }));

  const equipamentoFiltrado = selecionarEquipamentoPorDescricao(
    equipamentosNormalizados,
    descricaoFiltro
  );

  const primeiro = equipamentosNormalizados[0];

  return jsonResponse({
    ok: true,
    clienteId: customerId,
    clienteNome: cliente.name || "",
    totalEquipamentos: equipamentosNormalizados.length,
    equipamentos: equipamentosNormalizados,

    equip1Descricao: primeiro?.descricao || "",
    equip1Vencimento: primeiro?.vencimento || "",
    equip1ExpirationDate: primeiro?.expirationDate || "",
    equip1Modelo: primeiro?.modelo || "",
    equip1Serie: primeiro?.serie || "",

    equipamentoFiltradoEncontrado: Boolean(equipamentoFiltrado),
    equipamentoFiltradoDescricao: equipamentoFiltrado?.descricao || "",
    equipamentoFiltradoVencimento: equipamentoFiltrado?.vencimento || "",
    equipamentoFiltradoExpirationDate: equipamentoFiltrado?.expirationDate || "",
    equipamentoFiltradoModelo: equipamentoFiltrado?.modelo || "",
    equipamentoFiltradoSerie: equipamentoFiltrado?.serie || "",
  });
}
