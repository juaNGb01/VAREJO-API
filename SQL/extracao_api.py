QUERY_CLIENTE = """
SELECT 
    item.* EXCLUDE (enderecos),
    endereco.*
FROM '../VAREJO-API/staging_data/CLIENTES.json',
UNNEST(items) AS t(item),
UNNEST(item.enderecos) AS t2(endereco);
"""

QUERY_FORNECEDORES = """
SELECT 
    item.* EXCLUDE (endereco),
    UNNEST(item.endereco)
FROM '../VAREJO-API/staging_data/FORNECEDORES.json',
UNNEST(items) AS t(item);
"""


QUERY_PRECOS = """
SELECT 
    *
FROM 'PRECOS.parquet'

"""

