"""
extracao_clientes.py
--------------------
Extractor do endpoint /pessoa/clientes da API Varejo Facil.

Fluxo:
  1. Le credenciais e caminhos padronizados do config.py
  2. Chama base_extractor.fetch_all_pages() -- dados ficam em memoria, sem JSON em disco
  3. Converte para DataFrame pandas e normaliza os campos de endereco (explode)
  4. Grava tabela CLIENTES_V1 em Database/VALESOL.duckdb (CREATE OR REPLACE)
  5. Valida e loga a contagem final

Executar:
    python extractors/extracao_clientes.py
    python -m extractors.extracao_clientes
"""

import logging
import sys
import time
from pathlib import Path

# ──────────────────── Bootstrap de sys.path ──────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb
import pandas as pd

from config import DB_PATH, HEADERS, URL_CLIENTES, setup_logger
from extractors.base_extractor import fetch_all_pages

# ──────────────────── Logging Padronizado ────────────────────
setup_logger("extractors", "extracao_clientes.log")
log = logging.getLogger("extractors.extracao_clientes")

# ──────────────────── Configuracao ───────────────────────────
TABLE   = "CLIENTES_V1"
COUNT   = 500   # maximo por request na API
WORKERS = 6     # threads paralelas


def main():
    t_total = time.monotonic()
    log.info("=" * 60)
    log.info("INICIO: Extracao de CLIENTES")
    log.info("Endpoint : %s", URL_CLIENTES)
    log.info("Destino  : DuckDB (%s -> tabela %s)", DB_PATH.name, TABLE)
    log.info("=" * 60)

    if not URL_CLIENTES:
        log.error("URL_CLIENTES nao configurada no .env. Abortando.")
        return

    # 1. Extrai todos os items direto da API via base_extractor
    items = fetch_all_pages(URL_CLIENTES, HEADERS, count=COUNT, workers=WORKERS)

    if not items:
        log.error("Nenhum dado retornado pela API. Abortando.")
        return

    # 2. Transforma em DataFrame normalizado via pandas (explode + json_normalize)
    df_raw = pd.DataFrame(items)

    if "enderecos" in df_raw.columns:
        df_exploded = df_raw.explode("enderecos").reset_index(drop=True)
        enderecos_list = [e if isinstance(e, dict) else {} for e in df_exploded["enderecos"]]
        df_addr = pd.json_normalize(enderecos_list)
        df_addr.index = df_exploded.index

        cols_excluir = ["enderecos", "referencias", "dependentes"]
        df_main = df_exploded.drop(
            columns=[c for c in cols_excluir if c in df_exploded.columns]
        ).reset_index(drop=True)

        df_final = pd.concat([df_main, df_addr.reset_index(drop=True)], axis=1)
    else:
        df_final = df_raw

    log.info(
        "Tratamento de enderecos concluido: %d registros normalizados (%d colunas)",
        len(df_final), len(df_final.columns),
    )

    # 3. Conecta ao DuckDB e grava a tabela
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.register("df_final", df_final)

    log.info("Gravando tabela %s no DuckDB...", TABLE)
    con.execute(f"CREATE OR REPLACE TABLE {TABLE} AS SELECT * FROM df_final")

    # 4. Validacao e resumo final
    total_db = con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    con.close()

    log.info("=" * 60)
    log.info(
        "SUCESSO: %s gravada com %d registros no DuckDB (Tempo total: %.2fs)",
        TABLE, total_db, time.monotonic() - t_total,
    )
    log.info("=" * 60)


if __name__ == "__main__":
    main()

