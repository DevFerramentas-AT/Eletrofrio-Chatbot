import requests
import urllib3
import traceback
import time
from urllib.parse import urlencode

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_KEY = "LMzGdKP2Ui8IYb8OOQK3rHFL4H65s"
API_TOKEN = "HhkuUSjq3UgkhCdJaegbRJNtZranqmi1"
BASE_URL = "https://api.auvo.com.br/v2"


def obter_bearer_token():
    url = f"{BASE_URL}/login"
    payload = {"apiKey": API_KEY, "apiToken": API_TOKEN}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers, verify=False, timeout=15)
        dados = response.json()
        token = dados.get("result", {}).get("accessToken")
        if token:
            print(f"[+] Token obtido! Expira em: {dados['result'].get('expiration')}")
        return token
    except Exception as e:
        print(f"[-] Erro ao autenticar: {e}")
        return None


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
    pagina = 1
    page_size = 10
    total_verificados = 0

    print(f"\n[*] Buscando cliente com externalId = '{external_id}'...")

    while True:
        url = f"{BASE_URL}/customers/?{urlencode({'page': pagina, 'pageSize': page_size})}"
        try:
            response = requests.get(url, headers=headers, verify=False, timeout=60)
            if response.status_code != 200:
                print(f"[-] Erro HTTP {response.status_code}")
                return None

            clientes = extrair_lista(response.json())
            if not clientes:
                print(f"[-] Cliente não encontrado após {total_verificados} registros.")
                return None

            for cliente in clientes:
                total_verificados += 1
                if str(cliente.get("externalId", "")).strip() == external_id.strip():
                    print(f"[+] Cliente encontrado! id = {cliente.get('id')}")
                    return cliente

            if len(clientes) < page_size:
                print(f"[-] Fim dos registros. Cliente não encontrado.")
                return None

            pagina += 1
            time.sleep(1)

        except Exception as e:
            print(f"[-] Erro: {type(e).__name__}: {e}")
            traceback.print_exc()
            return None


def buscar_equipamentos_por_cliente(token, customer_id):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    pagina = 1
    page_size = 50  # Máximo possível para reduzir número de páginas
    encontrados = []
    total_verificados = 0

    print(f"\n[*] Buscando equipamentos para associatedCustomerId = {customer_id}...")

    while True:
        url = f"{BASE_URL}/equipments/?{urlencode({'page': pagina, 'pageSize': page_size})}"

        try:
            print(f"[*] Página {pagina} ({page_size} registros)...")
            response = requests.get(url, headers=headers, verify=False, timeout=60)

            if response.status_code != 200:
                print(f"[-] Erro HTTP {response.status_code}: {response.text}")
                break

            equipamentos = extrair_lista(response.json())

            if not equipamentos:
                print(f"[-] Página {pagina} vazia. Encerrando.")
                break

            for equip in equipamentos:
                total_verificados += 1
                if str(equip.get("associatedCustomerId", "")).strip() == str(customer_id):
                    encontrados.append(equip)

            print(f"    {len(equipamentos)} verificados | {len(encontrados)} correspondentes até agora")

            if len(equipamentos) < page_size:
                print(f"[*] Fim dos registros. Total verificado: {total_verificados}")
                break

            pagina += 1

        except requests.exceptions.Timeout:
            print(f"[-] Timeout na página {pagina}.")
            break
        except Exception as e:
            print(f"[-] Erro: {type(e).__name__}: {e}")
            traceback.print_exc()
            break

    if not encontrados:
        print(f"\n[-] Nenhum equipamento encontrado para o cliente id = {customer_id}.")
        return []

    print(f"\n[+] {len(encontrados)} equipamento(s) encontrado(s):\n")
    print("=" * 60)
    for i, equip in enumerate(encontrados, 1):
        print(f"\n--- Equipamento {i} ---")
        print(f"  description    : {equip.get('description', 'N/A')}")
        print(f"  expirationDate : {equip.get('expirationDate', 'N/A')}")
    print("\n" + "=" * 60)

    return encontrados


if __name__ == "__main__":
    EXTERNAL_ID = "19300620"

    print("[*] Autenticando...")
    token = obter_bearer_token()

    if not token:
        print("[-] Falha na autenticação.")
        exit()

    cliente = buscar_cliente_paginado(token, EXTERNAL_ID)
    if not cliente:
        print("[-] Fluxo encerrado: cliente não encontrado.")
        exit()

    customer_id = cliente.get("id")
    print(f"[*] id do cliente: {customer_id}")

    buscar_equipamentos_por_cliente(token, customer_id)