"""Extrai a tributação do produto 23 para CSV no layout padrão.

Colunas do CSV:
  Codigo_Produto               → produto.id
  UF                           → itens.uf  (sub-item)
  ICMS_Entrada_Tipo            → NULL (em branco)
  ICMS_Entrada_CST             → itens.cstId   (quando tipoDeOperacao == ENTRADA)
  ICMS_Entrada_Percentual      → itens.aliquota (quando tipoDeOperacao == ENTRADA)
  ICMS_Entrada_Reducao_Percentual → NULL
  ICMS_Saida_Tipo              → NULL
  ICMS_Saida_CST               → itens.cstId   (quando tipoDeOperacao == SAIDA)
  ICMS_Saida_Percentual        → itens.aliquota (quando tipoDeOperacao == SAIDA)
  ICMS_Saida_Reducao_Percentual → NULL
  ICMS_Saida_IVA               → NULL
  ST_Per_Reducao               → NULL
  ST_Per_ICMS                  → NULL
  ST_Per_Margem                → NULL
  Per_Fundo_Combate_Pobreza    → NULL
  ###@@###                     → literal "###@@###"

Cada linha do CSV representa uma UF única. Quando a mesma UF aparece
em múltiplos sub-itens (ex: AM / ENTRADA_DE_INDUSTRIA + ENTRADA_DE_DISTRIBUIDOR),
usa-se apenas o PRIMEIRO sub-item encontrado para cada tipo de operação.
"""

import asyncio
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import aiohttp


# ── Configurações ─────────────────────────────────────────────────────────────
PRODUTO_ID   = 3097
ARQUIVO_SAIDA = "tributacao_produto_23.csv"
TIMEOUT_TOTAL = 120   # segundos

COLUNAS = [
    "Codigo_Produto",
    "UF",
    "ICMS_Entrada_Tipo",
    "ICMS_Entrada_CST",
    "ICMS_Entrada_Percentual",
    "ICMS_Entrada_Reducao_Percentual",
    "ICMS_Saida_Tipo",
    "ICMS_Saida_CST",
    "ICMS_Saida_Percentual",
    "ICMS_Saida_Reducao_Percentual",
    "ICMS_Saida_IVA",
    "ST_Per_Reducao",
    "ST_Per_ICMS",
    "ST_Per_Margem",
    "Per_Fundo_Combate_Pobreza",
    "###@@###",
]


# ── Leitura do configs.txt ────────────────────────────────────────────────────
def ler_configuracao() -> tuple[str, str, dict[str, str]]:
    """Lê URLs e x-api-key do arquivo de configuração."""
    arquivo = next(
        (Path(nome) for nome in ("configs.txt", "configo.txt") if Path(nome).exists()),
        None,
    )
    if arquivo is None:
        raise FileNotFoundError("Arquivo de configuração não encontrado (configs.txt).")

    texto = arquivo.read_text(encoding="utf-8")
    m_produto = re.search(r"URL\s+PRODUTOS\s*=\s*(\S+)", texto, re.IGNORECASE)
    m_tabelas = re.search(r"URL\s+TABELA_TRIBUTARIAS\s*=\s*(\S+)", texto, re.IGNORECASE)
    m_key     = re.search(r"x-api-key\s*:\s*([^,\s}]+)", texto, re.IGNORECASE)

    if not (m_produto and m_tabelas and m_key):
        raise ValueError(
            f"Configuração incompleta em '{arquivo}'. "
            "Verifique: URL PRODUTOS, URL TABELA_TRIBUTARIAS, x-api-key."
        )

    url_produto = m_produto.group(1).replace("{Idproduto}", str(PRODUTO_ID))
    url_tabelas = m_tabelas.group(1)
    headers     = {"x-api-key": m_key.group(1), "Content-Type": "application/json"}
    return url_produto, url_tabelas, headers


# ── Requisição HTTP ───────────────────────────────────────────────────────────
async def get_json(
    session: aiohttp.ClientSession, url: str, headers: dict[str, str]
) -> Any:
    async with session.get(url, headers=headers) as resp:
        corpo = await resp.text()
        if not (200 <= resp.status < 300):
            raise RuntimeError(f"HTTP {resp.status} em {url}:\n{corpo[:500]}")
        try:
            return json.loads(corpo)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Resposta inválida (não-JSON) em {url}:\n{corpo[:500]}") from exc


# ── Extração dos registros de tabela tributária ───────────────────────────────
def extrair_tabelas(dados: Any) -> list[dict]:
    """Devolve a lista de registros de tabela tributária."""
    if isinstance(dados, list):
        return [r for r in dados if isinstance(r, dict)]
    if isinstance(dados, dict):
        for chave in ("items", "itens", "content", "data", "results", "registros"):
            valor = dados.get(chave)
            if isinstance(valor, list):
                return [r for r in valor if isinstance(r, dict)]
        return [dados]
    return []


# ── Filtragem por situacaoFiscalId ────────────────────────────────────────────
def filtrar_por_situacao(registros: list[dict], situacao_id: Any) -> list[dict]:
    ref = str(situacao_id)
    return [r for r in registros if str(r.get("situacaoFiscalId", "")) == ref]


# ── Montagem das linhas do CSV ────────────────────────────────────────────────
def montar_linhas_csv(
    produto_id: Any,
    tributacoes: list[dict],
) -> list[dict]:
    """
    Agrupa os sub-itens por UF e monta uma linha por UF, preenchendo
    colunas de ENTRADA e SAIDA com o PRIMEIRO sub-item encontrado por UF
    para cada tipo de operação.

    Estrutura de cada tributacao (nível raiz):
        {
            "tipoDeOperacao": "ENTRADA" | "SAIDA",
            "itens": [
                { "uf": "AM", "cstId": 0, "aliquota": 20.0, ... },
                { "uf": "SP", "cstId": 0, "aliquota": 20.0, ... },
                ...
            ]
        }
    """
    # dicionário: uf → {"entrada": {...}, "saida": {...}}
    por_uf: dict[str, dict] = defaultdict(lambda: {"entrada": None, "saida": None})

    for trib in tributacoes:
        tipo = str(trib.get("tipoDeOperacao", "")).upper()
        for item in trib.get("itens", []):
            if not isinstance(item, dict):
                continue
            uf = str(item.get("uf", "")).strip()
            if not uf:
                continue

            # Guarda apenas o PRIMEIRO sub-item por (UF, tipo de operação)
            if tipo == "ENTRADA" and por_uf[uf]["entrada"] is None:
                por_uf[uf]["entrada"] = item
            elif tipo == "SAIDA" and por_uf[uf]["saida"] is None:
                por_uf[uf]["saida"] = item

    # Ordena UFs para resultado consistente
    linhas: list[dict] = []
    for uf in sorted(por_uf.keys()):
        entrada = por_uf[uf]["entrada"] or {}
        # Se não houver SAIDA para a UF, replica os dados de ENTRADA
        saida   = por_uf[uf]["saida"] or entrada

        linha = {
            "Codigo_Produto":               produto_id,
            "UF":                           uf,
            "ICMS_Entrada_Tipo":            "",
            "ICMS_Entrada_CST":             entrada.get("cstId", ""),
            "ICMS_Entrada_Percentual":      entrada.get("aliquota", ""),
            "ICMS_Entrada_Reducao_Percentual": "",
            "ICMS_Saida_Tipo":              "",
            "ICMS_Saida_CST":              saida.get("cstId", ""),
            "ICMS_Saida_Percentual":        saida.get("aliquota", ""),
            "ICMS_Saida_Reducao_Percentual": "",
            "ICMS_Saida_IVA":              "",
            "ST_Per_Reducao":              "",
            "ST_Per_ICMS":                "",
            "ST_Per_Margem":              "",
            "Per_Fundo_Combate_Pobreza":  "",
            "###@@###":                   "###@@###",
        }
        linhas.append(linha)

    return linhas


# ── Gravação do CSV ───────────────────────────────────────────────────────────
def salvar_csv(linhas: list[dict], caminho: str) -> None:
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(linhas)
    print(f"CSV salvo: {caminho}")


# ── Main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    url_produto, url_tabelas, headers = ler_configuracao()

    print(f"[1/3] Consultando produto {PRODUTO_ID}...")
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_TOTAL)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        dados_produto = await get_json(session, url_produto, headers)
        print(f"[2/3] Consultando tabelas tributárias...")
        dados_tabelas = await get_json(session, url_tabelas, headers)

    if not isinstance(dados_produto, dict):
        raise RuntimeError(f"Resposta inesperada do produto: {type(dados_produto)}")

    situacao_fiscal_id = dados_produto.get("situacaoFiscalId")
    if situacao_fiscal_id is None:
        raise RuntimeError(f"Campo 'situacaoFiscalId' não encontrado no produto {PRODUTO_ID}.")

    produto_id  = dados_produto.get("id", PRODUTO_ID)
    descricao   = dados_produto.get("descricao", "")
    print(f"      Produto: [{produto_id}] {descricao}")
    print(f"      situacaoFiscalId: {situacao_fiscal_id}")

    print(f"[3/3] Filtrando e montando CSV...")
    todos    = extrair_tabelas(dados_tabelas)
    filtrado = filtrar_por_situacao(todos, situacao_fiscal_id)
    print(f"      Tabelas tributárias correspondentes: {len(filtrado)} registro(s)")

    linhas = montar_linhas_csv(produto_id, filtrado)
    print(f"      Linhas geradas no CSV (por UF): {len(linhas)}")

    salvar_csv(linhas, ARQUIVO_SAIDA)
    print(f"\nConcluído! {len(linhas)} linha(s) salva(s) em '{ARQUIVO_SAIDA}'.")


if __name__ == "__main__":
    asyncio.run(main())
