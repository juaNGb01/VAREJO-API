QUERY_PRODUTO = """
SELECT 
    item.*
FROM 'PRODUTOS.json',
UNNEST(items) AS t(item);
"""


QUERY_CLIENTE = """
SELECT 
    item.* EXCLUDE (enderecos),
    endereco.*
FROM 'CLIENTES.json',
UNNEST(items) AS t(item),
UNNEST(item.enderecos) AS t2(endereco);
"""

QUERY_PRECOS = """
SELECT 
    *
FROM 'PRECOS.parquet'

"""

