"""
extracao_fornecedores.py
------------------------
Extractor do endpoint /pessoa/fornecedores da API Varejo Facil.

Fluxo:
  1. Le credenciais e caminhos padronizados do config.py
  2. Chama base_extractor.fetch_all_pages() -- dados ficam em memoria, sem JSON em disco
  3. Converte para DataFrame pandas
  4. Registra o DataFrame no DuckDB e aplica normalizacao de endereco
  5. Grava tabela FORNECEDORES_V1 em Database/VALESOL.duckdb (CREATE OR REPLACE)
  6. Valida e loga a contagem final

Executar:
    python extractors/extracao_fornecedores.py
    python -m extractors.extracao_fornecedores
"""

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

# ──────────────────── Logging ────────────────────────────────
log = setup_logger(__name__, "extracao_fornecedores.log")

# ──────────────────── Configuracao ───────────────────────────
TABLE   = "FORNECEDORES_V1"
COUNT   = 500   # maximo por request na API
WORKERS = 4     # threads paralelas (dataset menor que clientes)


def main():
    t_total = time.monotonic()
    log.info("=" * 60)
    log.info("INICIO: extracao de FORNECEDORES")
    log.info("Endpoint : %s", URL_FORNECEDORES)
    log.info("Banco    : %s", DB_PATH.resolve())
    log.info("Tabela   : %s", TABLE)
    log.info("=" * 60)

    if not URL_FORNECEDORES:
        log.error("URL_FORNECEDORES nao configurada no .env. Abortando.")
        return

    # 1. Extrai todos os items direto da API (sem salvar JSON em disco)
    items = fetch_all_pages(URL_FORNECEDORES, HEADERS, count=COUNT, workers=WORKERS)

    if not items:
        log.error("Nenhum dado retornado pela API. Abortando.")
        return

    log.info("Items recebidos da API: %d", len(items))

    # 2. Transforma em DataFrame normalizado via pandas (json_normalize).
    #    Motivo: DuckDB nao consegue inferir STRUCT de colunas pandas object,
    #    portanto o UNNEST via SQL em DataFrames registrados falha.
    #
    #    'endereco' em fornecedores e um struct unico (nao array), portanto
    #    usamos json_normalize direto — sem explode.
    df_raw = pd.DataFrame(items)
    log.info(
        "DataFrame bruto: %d linhas x %d colunas",
        len(df_raw), len(df_raw.columns),
    )

    # Normaliza os campos do endereco em colunas flat se a coluna existir
    if "endereco" in df_raw.columns:
        df_addr = pd.json_normalize(df_raw["endereco"].fillna({}).tolist())
        df_addr.index = df_raw.index
        df_main = df_raw.drop(columns=["endereco"]).reset_index(drop=True)
        df_final = pd.concat([df_main, df_addr.reset_index(drop=True)], axis=1)
    else:
        df_final = df_raw

    log.info(
        "DataFrame final (apos normalize de endereco): %d linhas x %d colunas",
        len(df_final), len(df_final.columns),
    )

    # 3. Conecta ao DuckDB e insere o DataFrame ja normalizado
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.register("df_final", df_final)

    log.info("Criando tabela %s no DuckDB...", TABLE)
    con.execute(f"CREATE OR REPLACE TABLE {TABLE} AS SELECT * FROM df_final")

    # 4. Validacao
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
