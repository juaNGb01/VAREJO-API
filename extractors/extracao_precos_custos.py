import concurrent.futures
import logging
import time
import glob # lib usada para buscar arquivos e diretórios
import os
import duckdb
import requests
import pandas as pd
from SQL.script_extracao import QUERY_PRODUTO, QUERY_PRECOS

# ---------------- Configuração de logging ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("extracao_precos.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ---------------- Configurações iniciais ----------------
HEADERS = {
    "x-api-key": "4e7f6f32aa8702f0195e03e6ab3049e2",
    "Content-Type": "application/json",
}
URL = "https://mercadinhovaledosol.varejofacil.com/api/v1/produto/precos"

PASTA_PARTES = "parquet_partes/precos_custos"
PARQUET_FILE = "PRECOS_CUSTOS_V1.parquet"
PAGE = 1
PAGE_SIZE = 100
WORKERS = 4
LOTE_PAGINAS = 50
MAX_LOTES = 500


def get_pages(page: int):
    try:
        inicio = time.monotonic()
        response = requests.get(
            URL, headers=HEADERS,
            params={"page": page, "pageSize": PAGE_SIZE},
            timeout=10
        )
        
        duracao = time.monotonic() - inicio

        if response.status_code == 200:
            #transforma o resultado da api em json
            dados = response.json()
            items = dados.get("items", [])
            total = dados.get("total")  # captura o total informado pela API

            
            #cria um dataframe a partir do json retornado, caso não haja itens, retorna um dataframe vazio
            log.debug(f"Página {page}: {len(items)} itens em {duracao:.2f}s")
            df = pd.json_normalize(items) if items else pd.DataFrame()
            
            return df, total
        
        else:
            #log de aviso caso a página retorne um status diferente de 200
            log.warning(f"Página {page}: status {response.status_code} ({duracao:.2f}s)")
            return None, None

    except Exception as e:
        log.error(f"Erro ao buscar a página {page}: {e}")
        return None, None


def main():
    global PAGE

    os.makedirs(PASTA_PARTES, exist_ok=True)

    inicio_total = time.monotonic()
    total_registros = 0
    total_paginas_ok = 0
    total_paginas_vazias = 0
    total_paginas_erro = 0
    lote_num = 0
    total_esperado = None  # <- fix 1

    log.info("Iniciando extração de preços...")

    while True:
        lote_num += 1

        if lote_num > MAX_LOTES:
            log.error(
                f"Limite de segurança atingido ({MAX_LOTES} lotes). "
                f"Abortando para evitar loop infinito. Última página tentada: {PAGE}"
            )
            break

        paginas_lote = list(range(PAGE, PAGE + LOTE_PAGINAS))
        log.info(f"Lote {lote_num}: buscando páginas {paginas_lote[0]}–{paginas_lote[-1]}...")

        inicio_lote = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as executor:
            resultados = list(executor.map(get_pages, paginas_lote))
        duracao_lote = time.monotonic() - inicio_lote

        com_erro = [p for p, (df, tot) in zip(paginas_lote, resultados) if df is None]
        df_vazios = [df for df, tot in resultados if df is not None and df.empty]
        df_validos = [df for df, tot in resultados if df is not None and not df.empty]

        if total_esperado is None:
            totais = [tot for _, tot in resultados if tot is not None]
            if totais:
                total_esperado = totais[0]
                log.info(f"Total de registros esperado pela API: {total_esperado}")

        total_paginas_ok += len(df_validos)
        total_paginas_vazias += len(df_vazios)
        total_paginas_erro += len(com_erro)

        if com_erro:
            log.warning(f"Lote {lote_num}: falha em {len(com_erro)} páginas: {com_erro}")

        if df_validos:
            df_lote = pd.concat(df_validos, ignore_index=True)
            total_registros += len(df_lote)

            caminho_parte = os.path.join(PASTA_PARTES, f"parte_{lote_num:05d}.parquet")
            duckdb.sql(f"COPY df_lote TO '{caminho_parte}' (FORMAT PARQUET);")

            log.info(
                f"Lote {lote_num} processado em {duracao_lote:.1f}s | "
                f"{len(df_lote)} registros salvos em {caminho_parte} | "
                f"total acumulado: {total_registros} registros, "
                f"{total_paginas_ok} páginas válidas"
            )
        else:
            log.info(f"Lote {lote_num}: nenhum dado válido ({duracao_lote:.1f}s)")

        if total_esperado and total_registros >= total_esperado:
            log.info(f"Total esperado ({total_esperado}) atingido. Encerrando.")
            break

        if df_vazios and not df_validos:
            log.info("Última página alcançada (fim real dos dados). Encerrando.")
            break

        if not df_validos and not df_vazios:
            log.error(f"Lote {lote_num}: todas as páginas falharam. Encerrando por segurança.")
            break

        PAGE += LOTE_PAGINAS  # <- fix 2: agora dentro do while

    duracao_total = time.monotonic() - inicio_total
    log.info(
        f"Extração finalizada em {duracao_total/60:.1f} min | "
        f"lotes: {lote_num} | registros: {total_registros} | "
        f"páginas ok: {total_paginas_ok} | vazias: {total_paginas_vazias} | erro: {total_paginas_erro}"
    )

   
    #validação quatno a quantidade de registros esperados e a quantidade de registros extraídos
    partes = glob.glob(os.path.join(PASTA_PARTES, "*.parquet"))
    if partes:
        
        log.info(f"Consolidando {len(partes)} arquivos parciais em '{PARQUET_FILE}'...")
        #Cria um unico arquivo com todas as partes de parquet geradas
        duckdb.sql(f"""
            COPY (SELECT * FROM read_parquet('{PASTA_PARTES}/*.parquet'))
            TO '{PARQUET_FILE}' (FORMAT PARQUET);
        """)
        log.info("Consolidação concluída.")
    else:
        log.warning("Nenhum arquivo parcial gerado — nada para consolidar.")

    result = duckdb.sql(QUERY_PRECOS)
    print(result)

if __name__ == "__main__":
    main()