import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI(
    title="Ponte Genérica Dinâmica API Auvo",
    description="API Intermediária com configurações via Variáveis de Ambiente no Render."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/auvo/{endpoint:path}")
def consultar_auvo(endpoint: str, request: Request):
    """
    Rota dinâmica que repassa QUALQUER consulta GET para a Auvo.
    Exemplo: /auvo/customers ou /auvo/tasks
    """
    # 1. Busca as variáveis de ambiente configuradas no painel do Render a cada requisição
    auvo_token = os.getenv("AUVO_TOKEN")
    base_url = os.getenv("BASE_URL")

    # 2. Validações de segurança para garantir que você configurou o Render corretamente
    if not auvo_token:
        raise HTTPException(
            status_code=500, 
            detail="Erro de Configuração: A variável de ambiente 'AUVO_TOKEN' não foi encontrada no Render."
        )
        
    if not base_url:
        raise HTTPException(
            status_code=500, 
            detail="Erro de Configuração: A variável de ambiente 'BASE_URL' não foi encontrada no Render."
        )

    # Remove barras extras no final da URL caso você tenha digitado com '/' no painel do Render
    base_url = base_url.rstrip("/")

    # 3. Captura automaticamente todos os parâmetros enviados pelo seu Chatbot
    params = dict(request.query_params)

    # 4. Monta a URL exata para onde a requisição vai viajar
    url_completa = f"{base_url}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {auvo_token}",
        "Content-Type": "application/json"
    }

    try:
        # 5. Faz a busca na Auvo escondendo as suas credenciais
        response = requests.get(url_completa, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        
        # 6. Devolve o JSON completo diretamente para o bloco de Query do Chatbot
        return response.json()

    except requests.exceptions.RequestException as e:
        status_code = response.status_code if 'response' in locals() else 500
        raise HTTPException(status_code=status_code, detail=f"Erro na integração com a Auvo: {str(e)}")