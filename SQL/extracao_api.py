"""
SQL/extracao_api.py
-------------------
Constantes de queries SQL e helpers de conexao usados pelos extractors e notebooks.

Apos a migracao para DuckDB centralizado (Database/VALESOL.duckdb),
as queries leem diretamente das tabelas persistentes — sem depender
de arquivos JSON ou parquet em disco.

Uso:
    from SQL.extracao_api import get_connection, QUERY_CLIENTE, QUERY_FORNECEDORES
    con = get_connection()
    result = con.sql(QUERY_CLIENTE).df()
"""

import sys
from pathlib import Path

# ──────────────────── Bootstrap de sys.path ──────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb
from config import DB_PATH, load_sql_query


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """
    Retorna uma conexao DuckDB pronta apontando para o banco de dados oficial do projeto.
    Garante que o caminho seja sempre absoluto independente do diretorio corrente de execucao.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DB_PATH), read_only=read_only)


# ──────────────────────────────────────────────────────────────────────
# QUERIES SQL PADRONIZADAS (carregadas dinamicamente de SQL/querys_extracao/)
# ──────────────────────────────────────────────────────────────────────
try:
    QUERY_CLIENTE = load_sql_query("CLIENTES.SQL")
except Exception:
    QUERY_CLIENTE = "SELECT * FROM CLIENTES_V1"

try:
    QUERY_FORNECEDORES = load_sql_query("FORNECEDORES.SQL")
except Exception:
    QUERY_FORNECEDORES = "SELECT * FROM FORNECEDORES_V1"

try:
    QUERY_PRODUTO = load_sql_query("PRODUTOS.SQL")
except Exception:
    QUERY_PRODUTO = "SELECT * FROM PRODUTOS_V1"
