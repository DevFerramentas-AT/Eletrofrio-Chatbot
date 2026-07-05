"""
auvo_proxy.py — Proxy Flask para a API Auvo
Expõe endpoints REST simples que o Chatbot Flow Builder consome via nó Consulta API.

Endpoints:
  POST /auvo/equipamentos
       Body JSON: { "externalId": "PED 077-055/19" }
       Retorno:   { "ok": true, "clienteId": 123, "clienteNome": "...",
                    "totalEquipamentos": 2,
                    "equipamentos": [
                      { "id": 1, "descricao": "...", "vencimento": "...", "expirationDate": "...", "modelo": "...", "serie": "..." },
                      ...
                    ] }

  GET  /auvo/ping
       Retorno:   { "ok": true, "msg": "auvo_proxy online" }

Uso:
  pip install flask requests
  python auvo_proxy.py

Por padrão sobe na porta 5050. Altere PORT abaixo se necessário.
"""

import time
import traceback
from datetime import datetime
from urllib.parse import urlencode

import requests
import urllib3
from flask import Flask, jsonify, request
from flask_cors import CORS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def formatar_data_br(data_iso):
    """
    Converte uma data ISO retornada pela Auvo (ex: '2027-06-17T00:00:00')
    para o formato brasileiro 'DD/MM/AAAA' (ex: '17/06/2027').
    Se não conseguir interpretar a string, devolve o valor original sem quebrar.
    """
    if not data_iso:
        return ""

    texto = str(data_iso).strip()
    # remove milissegundos/timezone se vierem (ex: '2027-06-17T00:00:00.000Z')
    texto_limpo = texto.split(".")[0].replace("Z", "")

    formatos = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]
    for fmt in formatos:
        try:
            return datetime.strptime(texto_limpo, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue

    return texto  # não reconheceu o formato — devolve como veio, não quebra a resposta

# ── Configuração ────────────────────────────────────────────────────────────
API_KEY   = "LMzGdKP2Ui8IYb8OOQK3rHFL4H65s"
API_TOKEN = "HhkuUSjq3UgkhCdJaegbRJNtZranqmi1"
BASE_URL  = "https://api.auvo.com.br/v2"
PORT      = 5050

# Cache de token em memória (evita login a cada requisição)
_token_cache = {"token": None, "expiration": 0}

app = Flask(__name__)
CORS(app)  # permite chamadas do browser (construtor no Cloudflare Pages)


# ── Helpers Auvo ────────────────────────────────────────────────────────────

def obter_token():
    """Retorna token em cache ou faz novo login se expirado."""
    import time as _time
    agora = _time.time()

    # Usa cache se ainda válido (com 5 min de margem)
    if _token_cache["token"] and _token_cache["expiration"] - agora > 300:
        return _token_cache["token"]

    url = f"{BASE_URL}/login"
    payload = {"apiKey": API_KEY, "apiToken": API_TOKEN}
    headers = {"Content-Type": "application/json"}

    resp = requests.post(url, json=payload, headers=headers, verify=False, timeout=15)
    resp.raise_for_status()
    dados = resp.json()

    token = dados.get("result", {}).get("accessToken")
    if not token:
        raise ValueError("Login Auvo não retornou accessToken")

    # Calcula expiração (campo "expiration": "2026-06-27 19:19:12")
    from datetime import datetime
    try:
        exp_str = dados["result"].get("expiration", "")
        exp_dt  = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S")
        _token_cache["expiration"] = exp_dt.timestamp()
    except Exception:
        _token_cache["expiration"] = agora + 3600  # fallback: 1h

    _token_cache["token"] = token
    print(f"[auvo] Token renovado. Expira em: {dados['result'].get('expiration')}")
    return token


def extrair_lista(dados):
    result = dados.get("result")
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("entityList") or result.get("data") or []
    if isinstance(dados, list):
        return dados
    return []


def buscar_cliente_paginado(token, external_id):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    pagina    = 1
    page_size = 10

    print(f"[auvo] Buscando cliente externalId='{external_id}'...")

    while True:
        url = f"{BASE_URL}/customers/?{urlencode({'page': pagina, 'pageSize': page_size})}"
        resp = requests.get(url, headers=headers, verify=False, timeout=60)

        if resp.status_code != 200:
            print(f"[auvo] Erro HTTP {resp.status_code} em /customers/")
            return None

        clientes = extrair_lista(resp.json())
        if not clientes:
            print(f"[auvo] Fim dos registros. Cliente não encontrado.")
            return None

        for cliente in clientes:
            if str(cliente.get("externalId", "")).strip() == external_id.strip():
                print(f"[auvo] Cliente encontrado! id={cliente.get('id')}")
                return cliente

        if len(clientes) < page_size:
            print("[auvo] Última página. Cliente não encontrado.")
            return None

        pagina += 1
        time.sleep(0.5)


def selecionar_equipamento_por_descricao(equipamentos_normalizados, descricao_alvo):
    """
    Procura, na lista já normalizada, o primeiro equipamento cujo campo
    'descricao' seja igual (case-insensitive) a descricao_alvo.
    Retorna o dict do equipamento ou None se não encontrar.
    """
    alvo = descricao_alvo.strip().lower()
    for equip in equipamentos_normalizados:
        if str(equip.get("descricao", "")).strip().lower() == alvo:
            return equip
    return None


def buscar_equipamentos_por_cliente(token, customer_id):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    pagina    = 1
    page_size = 50
    encontrados = []

    print(f"[auvo] Buscando equipamentos para customerId={customer_id}...")

    while True:
        url = f"{BASE_URL}/equipments/?{urlencode({'page': pagina, 'pageSize': page_size})}"
        try:
            resp = requests.get(url, headers=headers, verify=False, timeout=60)
            if resp.status_code != 200:
                print(f"[auvo] Erro HTTP {resp.status_code} em /equipments/")
                break

            equipamentos = extrair_lista(resp.json())
            if not equipamentos:
                break

            for equip in equipamentos:
                if str(equip.get("associatedCustomerId", "")).strip() == str(customer_id):
                    encontrados.append(equip)

            print(f"[auvo] Página {pagina}: {len(equipamentos)} verificados, "
                  f"{len(encontrados)} correspondentes")

            if len(equipamentos) < page_size:
                break

            pagina += 1

        except requests.exceptions.Timeout:
            print(f"[auvo] Timeout na página {pagina}.")
            break
        except Exception as e:
            print(f"[auvo] Erro: {e}")
            traceback.print_exc()
            break

    return encontrados


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.route("/auvo/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True, "msg": "auvo_proxy online"})


@app.route("/auvo/equipamentos", methods=["POST"])
def equipamentos():
    """
    Body: { "externalId": "PED 077-055/19" }
    Retorna lista de equipamentos do cliente com esse externalId.
    """
    body = request.get_json(silent=True) or {}
    external_id = (body.get("externalId") or "").strip()
    # Descrição usada para escolher o equipamento "válido" dentre os encontrados.
    # Pode ser sobrescrita no body: { "externalId": "...", "descricaoFiltro": "teste" }
    descricao_filtro = (body.get("descricaoFiltro") or "teste").strip()

    if not external_id:
        return jsonify({"ok": False, "erro": "Campo 'externalId' é obrigatório."}), 400

    try:
        token = obter_token()
    except Exception as e:
        print(f"[auvo] Falha no login: {e}")
        return jsonify({"ok": False, "erro": f"Falha na autenticação Auvo: {e}"}), 502

    try:
        cliente = buscar_cliente_paginado(token, external_id)
    except Exception as e:
        print(f"[auvo] Erro ao buscar cliente: {e}")
        return jsonify({"ok": False, "erro": f"Erro ao buscar cliente: {e}"}), 502

    if not cliente:
        return jsonify({
            "ok": False,
            "erro": f"Cliente com externalId '{external_id}' não encontrado."
        }), 404

    customer_id = cliente.get("id")

    try:
        equipamentos_raw = buscar_equipamentos_por_cliente(token, customer_id)
    except Exception as e:
        print(f"[auvo] Erro ao buscar equipamentos: {e}")
        return jsonify({"ok": False, "erro": f"Erro ao buscar equipamentos: {e}"}), 502

    # Normaliza a lista para o construtor inserindo o campo original igual ao api.py
    equipamentos_normalizados = [
        {
            "id":             equip.get("id"),
            "descricao":      equip.get("description", ""),
            "vencimento":     formatar_data_br(equip.get("expirationDate", "")), # formato BR: dd/mm/aaaa
            "expirationDate": equip.get("expirationDate", ""), # mantido em ISO, igual à Auvo
            "modelo":         equip.get("model", ""),
            "serie":          equip.get("serialNumber", ""),
        }
        for equip in equipamentos_raw
    ]

    # Equipamento "válido" — aquele cujo description bate com descricao_filtro
    # (no exemplo do cliente, equipamentos com data padrão 0001-01-01 são placeholders
    # sem data real; o equipamento com descricao == "teste" é o que tem a data real).
    equipamento_filtrado = selecionar_equipamento_por_descricao(equipamentos_normalizados, descricao_filtro)

    return jsonify({
        "ok":               True,
        "clienteId":        customer_id,
        "clienteNome":      cliente.get("name", ""),
        "totalEquipamentos": len(equipamentos_normalizados),
        "equipamentos":     equipamentos_normalizados,
        # Atalhos para o primeiro equipamento (facilita mapeamento direto no construtor)
        "equip1Descricao":       equipamentos_normalizados[0]["descricao"]  if equipamentos_normalizados else "",
        "equip1Vencimento":      equipamentos_normalizados[0]["vencimento"] if equipamentos_normalizados else "",
        "equip1ExpirationDate":  equipamentos_normalizados[0]["expirationDate"] if equipamentos_normalizados else "", # Adicionado para mapeamento direto
        "equip1Modelo":          equipamentos_normalizados[0]["modelo"]     if equipamentos_normalizados else "",
        "equip1Serie":           equipamentos_normalizados[0]["serie"]      if equipamentos_normalizados else "",
        # Atalhos para o equipamento filtrado por descrição (descricaoFiltro, default "teste")
        "equipamentoFiltradoEncontrado":      bool(equipamento_filtrado),
        "equipamentoFiltradoDescricao":       equipamento_filtrado["descricao"]      if equipamento_filtrado else "",
        "equipamentoFiltradoVencimento":      equipamento_filtrado["vencimento"]     if equipamento_filtrado else "",
        "equipamentoFiltradoExpirationDate":  equipamento_filtrado["expirationDate"] if equipamento_filtrado else "",
        "equipamentoFiltradoModelo":          equipamento_filtrado["modelo"]         if equipamento_filtrado else "",
        "equipamentoFiltradoSerie":           equipamento_filtrado["serie"]          if equipamento_filtrado else "",
    })


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[auvo_proxy] Iniciando na porta {PORT}...")
    print(f"[auvo_proxy] Endpoint: POST http://localhost:{PORT}/auvo/equipamentos")
    print(f"[auvo_proxy] Health:   GET  http://localhost:{PORT}/auvo/ping")
    app.run(host="0.0.0.0", port=PORT, debug=False)