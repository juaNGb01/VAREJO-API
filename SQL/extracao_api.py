"""
SQL/extracao_api.py
-------------------
Constantes de queries SQL usadas pelos extractors e notebooks.

Apos a migracao para DuckDB centralizado (Database/VALESOL.duckdb),
as queries leem diretamente das tabelas persistentes — sem depender
de arquivos JSON ou parquet em disco.

Uso:
    from SQL.extracao_api import QUERY_CLIENTE, QUERY_FORNECEDORES
    con = duckdb.connect("Database/VALESOL.duckdb")
    result = con.sql(QUERY_CLIENTE)
"""

# ──────────────────────────────────────────────────────────────────────
# CLIENTES
# Tabela populada por: extractors/extracao_clientes.py
# Uma linha por (cliente, endereco) — ja normalizada com UNNEST
# ──────────────────────────────────────────────────────────────────────
QUERY_CLIENTE = "SELECT * FROM CLIENTES_V1"


# ──────────────────────────────────────────────────────────────────────
# FORNECEDORES
# Tabela populada por: extractors/extracao_fornecedores.py
# Uma linha por fornecedor — endereco expandido como colunas flat
# ──────────────────────────────────────────────────────────────────────
QUERY_FORNECEDORES = "SELECT * FROM FORNECEDORES_V1"
