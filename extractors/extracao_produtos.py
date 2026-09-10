"""
extracao_produtos.py
--------------------
Extractor do endpoint /produto/produtos da API Varejo Facil.

Fluxo:
  1. Le credenciais e caminhos padronizados do config.py
  2. Chama base_extractor.fetch_all_pages()
  3. Salva backup bruto em staging_data/PRODUTOS.json
  4. Converte para DataFrame pandas
  5. Grava tabela PRODUTOS_V1 em Database/VALESOL.duckdb (CREATE OR REPLACE)
  6. Valida e loga a contagem final

Executar:
    python extractors/extracao_produtos.py
    python -m extractors.extracao_produtos
"""

import json
import sys
import time
from pathlib import Path

# ──────────────────── Bootstrap de sys.path ──────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb
import pandas as pd

from config import DB_PATH, HEADERS, STAGING_DIR, URL_PRODUTOS, setup_logger
from extractors.base_extractor import fetch_all_pages

# ──────────────────── Logging ────────────────────────────────
log = setup_logger(__name__, "extracao_produtos.log")

# ──────────────────── Configuracao ───────────────────────────
TABLE = "PRODUTOS_V1"
COUNT = 100  # limite maximo por pagina deste endpoint na API
WORKERS = 4
JSON_OUTPUT = STAGING_DIR / "PRODUTOS.json"


def main():
    t_total = time.monotonic()
    log.info("=" * 60)
    log.info("INICIO: extracao de PRODUTOS")
    log.info("Endpoint : %s", URL_PRODUTOS)
    log.info("Banco    : %s", DB_PATH.resolve())
    log.info("Tabela   : %s", TABLE)
    log.info("Arquivo  : %s", JSON_OUTPUT.resolve())
    log.info("=" * 60)

    if not URL_PRODUTOS:
        log.error("URL_PRODUTOS nao configurada no .env. Abortando.")
        return

    # 1. Extrai todos os produtos via base_extractor
    items = fetch_all_pages(URL_PRODUTOS, HEADERS, count=COUNT, workers=WORKERS)

    if not items:
        log.error("Nenhum dado retornado pela API. Abortando.")
        return

    log.info("Items recebidos da API: %d", len(items))

    # 2. Salva copia em staging_data/PRODUTOS.json de forma segura
    JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(JSON_OUTPUT, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, ensure_ascii=False, indent=2)
    log.info("Arquivo JSON salvo com sucesso em: %s", JSON_OUTPUT)

    # 3. Converte para DataFrame
    df_raw = pd.DataFrame(items)
    log.info(
        "DataFrame bruto: %d linhas x %d colunas",
        len(df_raw), len(df_raw.columns),
    )

    # 4. Grava no DuckDB
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.register("df_raw", df_raw)

    log.info("Criando tabela %s no DuckDB...", TABLE)
    con.execute(f"CREATE OR REPLACE TABLE {TABLE} AS SELECT * FROM df_raw")

    # 5. Validacao
    total_db = con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    log.info("=" * 60)
    log.info(
        "CONCLUIDO: %s | %d registros na tabela | %d itens da API",
        TABLE, total_db, len(items),
    )
    log.info("Tempo total: %.1f s", time.monotonic() - t_total)
    log.info("=" * 60)
    con.close()


if __name__ == "__main__":
    main()

