
import concurrent.futures
import duckdb
import logging
import requests
import pandas as pd
import glob
import os
import time
from dotenv import load_dotenv

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# Carrega variáveis do arquivo .env
load_dotenv()
API_KEY = os.getenv("API_KEY") or "4e7f6f32aa8702f0195e03e6ab3049e2"

HEADERS = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json",
}

URL = "https://mercadinhovaledosol.varejofacil.com/api/v1/produto/produtos"
PAGE_SIZE = 500  # Limite máximo suportado pela API por requisição
WORKERS = 6      # Quantidade de threads simultâneas
PARTES_DIR = "parquet_partes/produtos"

os.makedirs(PARTES_DIR, exist_ok=True)

# Limpa arquivos de execuções anteriores para evitar contagem duplicada
for f in glob.glob(os.path.join(PARTES_DIR, "*.parquet")):
    try:
        os.remove(f)
    except OSError:
        pass


def get_chunk(start: int) -> bool:
    try:
        # A API Varejo Fácil pagina usando 'start' (offset) e 'count' (limit)
        response = requests.get(
            URL, 
            headers=HEADERS, 
            params={"start": start, "count": PAGE_SIZE}, 
            timeout=30
        )
        if response.status_code != 200:
            log.error(f"Start {start} -> HTTP {response.status_code}")
            return False

        items = response.json().get("items", [])
        if not items:
            return True

        df_page = pd.json_normalize(items)
        path_saida = os.path.join(PARTES_DIR, f"produtos_{start:07d}.parquet")
        duckdb.sql(f"COPY df_page TO '{path_saida}' (FORMAT PARQUET);")
        return True
    except Exception as e:
        log.error(f"[ERRO] Start {start} -> {e}")
        return False


def main():
    # 1. Busca o primeiro lote para obter o total de registros
    log.info("Obtendo informações iniciais e primeiro lote...")
    r0 = requests.get(URL, headers=HEADERS, params={"start": 0, "count": PAGE_SIZE}, timeout=30).json()
    total = r0.get("total", 0)
    df0 = pd.json_normalize(r0.get("items", []))
    duckdb.sql(f"COPY df0 TO '{os.path.join(PARTES_DIR, 'produtos_0000000.parquet')}' (FORMAT PARQUET);")

    log.info(f"Total de produtos no cadastro: {total}")

    # 2. Gera todos os offsets necessários (500, 1000, 1500...)
    starts_restantes = list(range(PAGE_SIZE, total, PAGE_SIZE))
    log.info(f"Extraindo os dados restantes em {len(starts_restantes)} requisições com {WORKERS} threads...")

    t_inicio = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as executor:
        resultados = list(executor.map(get_chunk, starts_restantes))

    duracao = time.monotonic() - t_inicio
    log.info(f"Extração concluída em {duracao:.2f}s!")

    # --- CONSULTA UNIFICADA NO DUCKDB ---
    query_unificada = f"""
    SELECT 
        count(*) as total_registros,
        count(distinct id) as produtos_unicos
    FROM '{PARTES_DIR}/*.parquet';
    """
    result = duckdb.sql(query_unificada)
    print(result)


if __name__ == "__main__":
    main()

