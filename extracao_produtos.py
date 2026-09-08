import os
import json
import requests
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

# ==============================================================================
# CONFIGURAÇÕES E CREDENCIAIS
# ==============================================================================
# Carrega as variáveis de ambiente definidas no arquivo .env
load_dotenv()

API_KEY = os.getenv("API_KEY")
URL = (os.getenv("URL_PRODUTOS") or "").strip()

# Cabeçalhos necessários para autenticação na API do VarejoFácil
HEADERS = {
    "x-api-key": API_KEY,
    "content-type": "application/json"
}

# Configurações de paginação e paralelismo
PAGE_SIZE = 100  # Quantidade de itens por página/requisição
WORKERS = 4      # Quantidade de workers (threads) executando requisições em paralelo
ARQUIVO_SAIDA = "./staging_data/PRODUTOS.json"


# ==============================================================================
# FUNÇÃO PARA BUSCAR UMA PÁGINA ESPECÍFICA
# ==============================================================================
def buscar_pagina(start: int) -> list:
    """
    Faz a requisição para a API buscando uma página específica a partir do índice 'start'.
    Essa função será executada em paralelo pelos workers.
    """
    params = {"start": start, "count": PAGE_SIZE}
    resp = requests.get(URL, headers=HEADERS, params=params)
    resp.raise_for_status()
    
    dados = resp.json()
    return dados.get("items", [])


# ==============================================================================
# FLUXO PRINCIPAL DE VARREDURA
# ==============================================================================
def varrer_api_paralelo() -> list:
    """
    Coordena a extração dos produtos:
    1. Faz uma 1ª requisição inicial para saber o total de produtos disponíveis.
    2. Calcula os pontos de partida (offsets) das páginas restantes.
    3. Distribui as requisições restantes entre os 4 workers do ThreadPoolExecutor.
    """
    print("Iniciando primeira requisição para identificar o total de produtos...")
    
    # 1. Primeira requisição manual para pegar o total e o primeiro lote (start=0)
    params_inicial = {"start": 0, "count": PAGE_SIZE}
    resp_inicial = requests.get(URL, headers=HEADERS, params=params_inicial)
    resp_inicial.raise_for_status()
    
    dados_iniciais = resp_inicial.json()
    total_registros = dados_iniciais.get("total", 0)
    primeiros_itens = dados_iniciais.get("items", [])
    
    print(f"Total de produtos cadastrados na API: {total_registros}")
    
    # Lista onde acumularemos todos os produtos
    todos_produtos = list(primeiros_itens)
    print(f"Coletados: {len(todos_produtos)} de {total_registros} produtos...")
    
    # Se não houver mais registros além do primeiro lote, encerra
    if total_registros <= PAGE_SIZE:
        return todos_produtos

    # 2. Gera a lista de 'start' restantes: [100, 200, 300, ..., total]
    starts_restantes = list(range(PAGE_SIZE, total_registros, PAGE_SIZE))
    print(f"Disparando {len(starts_restantes)} requisições com {WORKERS} workers simultâneos...\n")

    # 3. ThreadPoolExecutor: executa as requisições em paralelo
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        # executor.map envia cada 'start' para a função buscar_pagina
        # e devolve os resultados na ordem dos offsets
        for itens_pagina in executor.map(buscar_pagina, starts_restantes):
            todos_produtos.extend(itens_pagina)
            print(f"Coletados: {len(todos_produtos)} de {total_registros} produtos...")

    return todos_produtos


# ==============================================================================
# EXECUÇÃO DO SCRIPT
# ==============================================================================
if __name__ == "__main__":
    # 1. Executa a varredura paralela
    dados = varrer_api_paralelo()
    
    # 2. Garante que a pasta de destino exista
    os.makedirs(os.path.dirname(ARQUIVO_SAIDA), exist_ok=True)
    
    # 3. Salva o resultado no formato padronizado {"items": [...]}
    print(f"\nSalvando dados em {ARQUIVO_SAIDA}...")
    with open(ARQUIVO_SAIDA, "w", encoding="utf-8") as f:
        json.dump({"items": dados}, f, ensure_ascii=False, indent=4)
        
    print(f"Extração concluída com sucesso! Total de itens salvos: {len(dados)}")

