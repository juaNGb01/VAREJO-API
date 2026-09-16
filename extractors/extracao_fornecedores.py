"""
extracao_fornecedores.py
------------------------
Extractor do endpoint /pessoa/fornecedores da API Varejo Facil.

Fluxo:
  1. Le credenciais e caminhos padronizados do config.py
  2. Chama base_extractor.fetch_all_pages() -- dados ficam em memoria, sem JSON em disco
  3. Converte para DataFrame pandas e normaliza os campos de endereco
  4. Grava tabela FORNECEDORES_V1 em Database/VALESOL.duckdb (CREATE OR REPLACE)
  5. Valida e loga a contagem final

Executar:
    python extractors/extracao_fornecedores.py
    python -m extractors.extracao_fornecedores
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

from config import DB_PATH, HEADERS, URL_FORNECEDORES, setup_logger
from extractors.base_extractor import fetch_all_pages

# ──────────────────── Logging Padronizado ────────────────────
# Configura o logger raiz do pacote 'extractors' para evitar repeticao e unificar formatacao
setup_logger("extractors", "extracao_fornecedores.log")
log = logging.getLogger("extractors.extracao_fornecedores")

# ──────────────────── Configuracao ───────────────────────────
TABLE   = "FORNECEDORES_V1"
COUNT   = 500   # maximo por request na API
WORKERS = 4     # threads paralelas


def main():
    t_total = time.monotonic()
    log.info("=" * 60)
    log.info("INICIO: Extracao de FORNECEDORES")
    log.info("Endpoint : %s", URL_FORNECEDORES)
    log.info("Destino  : DuckDB (%s -> tabela %s)", DB_PATH.name, TABLE)
    log.info("=" * 60)

    if not URL_FORNECEDORES:
        log.error("URL_FORNECEDORES nao configurada no .env. Abortando.")
        return

    # 1. Extrai todos os items direto da API via base_extractor
    items = fetch_all_pages(URL_FORNECEDORES, HEADERS, count=COUNT, workers=WORKERS)

    if not items:
        log.error("Nenhum dado retornado pela API. Abortando.")
        return

    # 2. Transforma em DataFrame e normaliza campos de endereco
    df_raw = pd.DataFrame(items)

    if "endereco" in df_raw.columns:
        df_addr = pd.json_normalize(df_raw["endereco"].fillna({}).tolist())
        df_addr.index = df_raw.index
        df_main = df_raw.drop(columns=["endereco"]).reset_index(drop=True)
        df_final = pd.concat([df_main, df_addr.reset_index(drop=True)], axis=1)
    else:
        df_final = df_raw

    log.info(
        "Normalizacao de endereco concluida: %d fornecedores (%d colunas)",
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
