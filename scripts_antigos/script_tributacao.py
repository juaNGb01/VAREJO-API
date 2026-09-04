"""Script de extração de tributação de TODOS os produtos do Varejo Fácil.

Características de alta performance e resiliência:
  1. Consulta a tabela tributária UMA VEZ no início e pré-calcula os templates
     de tributação por situacaoFiscalId em memória (acesso O(1)).
  2. Pagina o endpoint /v1/produto/produtos com count=500 (111 páginas para ~55k produtos).
     Como o endpoint de listagem já retorna 'id' e 'situacaoFiscalId', a extração
     ocorre em segundos em vez de horas.
  3. Grava o CSV de forma incremental página a página (streaming), mantendo o uso
     de memória mínimo (< 20 MB).
  4. Rate limiter e retry com backoff exponencial para proteger contra 429 e instabilidades de rede.
  5. Layout idêntico ao validado:
     - Uma linha por UF para cada produto.
     - Quando a SAÍDA não estiver presente para uma UF, replica os dados de ENTRADA.
     - Colunas não utilizadas permanecem vazias.
     - Coluna '###@@###' com valor literal '###@@###'.
"""

import asyncio
import csv
import json
import math
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import aiohttp


# ── Configurações ─────────────────────────────────────────────────────────────
PAGE_SIZE                 = 500   # Quantidade de produtos por requisição na API
CONCORRENCIA_PAGINAS      = 4     # Concorrência máxima de páginas simultâneas
INTERVALO_MINIMO_REQ      = 0.25  # Intervalo mínimo (segundos) entre requisições
TENTATIVAS_REQUISICAO     = 8     # Tentativas em caso de timeout / 429 / 5xx
ESPERA_BASE_RETRY         = 10    # Espera base para retentativas
PAUSA_ENTRE_LOTES         = 0.5   # Pausa suave entre lotes de páginas
TIMEOUT_TOTAL             = 60   # Timeout por requisição

ARQUIVO_SAIDA             = "tributacao_todos_produtos.csv"
ARQUIVO_TMP_IDS           = "tmp_produtos_situacao.csv"

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


# ── Leitura de configurações (configs.txt) ────────────────────────────────────
def ler_configuracao() -> tuple[str, str, dict[str, str]]:
    """Lê as URLs e x-api-key do arquivo configs.txt."""
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

    # URL base da listagem de produtos
    url_prod = m_produto.group(1)
    url_lista_produtos = re.sub(r"/\{Idproduto\}", "", url_prod, flags=re.IGNORECASE)
    url_tabelas = m_tabelas.group(1)
    headers = {
        "x-api-key": m_key.group(1),
        "Content-Type": "application/json",
    }
    return url_lista_produtos, url_tabelas, headers


# ── Utilitário de Log ─────────────────────────────────────────────────────────
def log(msg: str, inicio: float) -> None:
    decorrido = time.time() - inicio
    print(f"[{decorrido:7.1f}s] {msg}")


# ── Rate Limiter ──────────────────────────────────────────────────────────────
class RateLimiter:
    def __init__(self, intervalo_minimo: float) -> None:
        self.intervalo_minimo = intervalo_minimo
        self.proximo_horario = 0.0
        self.lock = asyncio.Lock()

    async def aguardar(self) -> None:
        async with self.lock:
            agora = time.monotonic()
            espera = self.proximo_horario - agora
            if espera > 0:
                await asyncio.sleep(espera)
                agora = time.monotonic()
            self.proximo_horario = agora + self.intervalo_minimo

    async def aplicar_pausa_extra(self, segundos: float) -> None:
        async with self.lock:
            base = max(self.proximo_horario, time.monotonic())
            self.proximo_horario = base + segundos


# ── Requisição HTTP robusta com retry ──────────────────────────────────────────
async def buscar_json(
    session: aiohttp.ClientSession,
    rate_limiter: RateLimiter,
    url: str,
    headers: dict[str, str],
    params: dict | None = None,
    label: str = "",
) -> Any:
    for tentativa in range(1, TENTATIVAS_REQUISICAO + 1):
        await rate_limiter.aguardar()
        try:
            async with session.get(url, headers=headers, params=params) as resp:
                corpo = await resp.text()
        except asyncio.TimeoutError:
            if tentativa < TENTATIVAS_REQUISICAO:
                espera = ESPERA_BASE_RETRY + tentativa * 2
                print(f"[TIMEOUT] {label} (tentativa {tentativa}/{TENTATIVAS_REQUISICAO}) -> aguardando {espera}s")
                await rate_limiter.aplicar_pausa_extra(espera)
                continue
            raise RuntimeError(f"Timeout após {TENTATIVAS_REQUISICAO} tentativas: {label}")
        except Exception as exc:
            if tentativa < TENTATIVAS_REQUISICAO:
                espera = ESPERA_BASE_RETRY
                print(f"[ERRO REDE] {label}: {exc} -> aguardando {espera}s")
                await rate_limiter.aplicar_pausa_extra(espera)
                continue
            raise

        if resp.status == 200:
            try:
                return json.loads(corpo)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"JSON inválido em {url}: {corpo[:300]}") from exc

        if resp.status in {429, 500, 502, 503, 504} and tentativa < TENTATIVAS_REQUISICAO:
            espera = ESPERA_BASE_RETRY * tentativa if resp.status == 429 else 5 * tentativa
            print(f"[HTTP {resp.status}] {label} (tentativa {tentativa}/{TENTATIVAS_REQUISICAO}) -> aguardando {espera}s")
            await rate_limiter.aplicar_pausa_extra(espera)
            continue

        raise RuntimeError(f"HTTP {resp.status} ao consultar {url}: {corpo[:300]}")

    raise RuntimeError(f"Falha após {TENTATIVAS_REQUISICAO} tentativas: {label}")


# ── Pré-computação das tabelas tributárias por situacaoFiscalId ─────────────────
def extrair_tabelas(dados: Any) -> list[dict]:
    if isinstance(dados, list):
        return [r for r in dados if isinstance(r, dict)]
    if isinstance(dados, dict):
        for chave in ("items", "itens", "content", "data", "results", "registros"):
            valor = dados.get(chave)
            if isinstance(valor, list):
                return [r for r in valor if isinstance(r, dict)]
        return [dados]
    return []


def precomputar_templates_tributacao(dados_tabelas: Any) -> dict[str, list[dict]]:
    """
    Agrupa as tabelas por situacaoFiscalId e pré-calcula a lista de UF e impostos.
    Retorna:
      {
        "1": [ {"UF": "AM", "cst_e": "0", "aliq_e": "20.0", "cst_s": "0", "aliq_s": "20.0"}, ... ],
        "9": [ ... ]
      }
    Isso permite que a geração de linhas de qualquer produto seja O(1).
    """
    todos = extrair_tabelas(dados_tabelas)
    por_situacao: dict[str, list[dict]] = defaultdict(list)

    for reg in todos:
        sid = str(reg.get("situacaoFiscalId", "")).strip()
        if sid:
            por_situacao[sid].append(reg)

    templates_por_situacao: dict[str, list[dict]] = {}

    for sid, lista_regs in por_situacao.items():
        por_uf: dict[str, dict] = defaultdict(lambda: {"entrada": None, "saida": None})

        for trib in lista_regs:
            tipo = str(trib.get("tipoDeOperacao", "")).upper()
            for item in trib.get("itens", []):
                if not isinstance(item, dict):
                    continue
                uf = str(item.get("uf", "")).strip()
                if not uf or uf.upper() == "EX":
                    continue

                if tipo == "ENTRADA" and por_uf[uf]["entrada"] is None:
                    por_uf[uf]["entrada"] = item
                elif tipo == "SAIDA" and por_uf[uf]["saida"] is None:
                    por_uf[uf]["saida"] = item

        linhas_template = []
        for uf in sorted(por_uf.keys()):
            entrada = por_uf[uf]["entrada"] or {}
            # Regra: se não houver correspondência na SAÍDA, replica a ENTRADA
            saida   = por_uf[uf]["saida"] or entrada

            linhas_template.append({
                "UF": uf,
                "ICMS_Entrada_CST": entrada.get("cstId", ""),
                "ICMS_Entrada_Percentual": entrada.get("aliquota", ""),
                "ICMS_Saida_CST": saida.get("cstId", ""),
                "ICMS_Saida_Percentual": saida.get("aliquota", ""),
            })

        templates_por_situacao[sid] = linhas_template

    return templates_por_situacao


# ── Montagem de linhas para um lote de produtos ───────────────────────────────
def gerar_linhas_para_produtos(
    produtos: list[dict],
    templates_tributacao: dict[str, list[dict]],
) -> list[dict]:
    """Gera todas as linhas de CSV para uma lista de produtos."""
    linhas_resultado: list[dict] = []

    for p in produtos:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        if pid is None:
            continue

        sid = str(p.get("situacaoFiscalId", "")).strip()
        template = templates_tributacao.get(sid)

        if not template:
            # Caso o produto não tenha situacaoFiscalId ou ela não esteja na tabela
            continue

        for t in template:
            linhas_resultado.append({
                "Codigo_Produto":                  pid,
                "UF":                              t["UF"],
                "ICMS_Entrada_Tipo":               "",
                "ICMS_Entrada_CST":                t["ICMS_Entrada_CST"],
                "ICMS_Entrada_Percentual":         t["ICMS_Entrada_Percentual"],
                "ICMS_Entrada_Reducao_Percentual": "",
                "ICMS_Saida_Tipo":                 "",
                "ICMS_Saida_CST":                  t["ICMS_Saida_CST"],
                "ICMS_Saida_Percentual":           t["ICMS_Saida_Percentual"],
                "ICMS_Saida_Reducao_Percentual":   "",
                "ICMS_Saida_IVA":                  "",
                "ST_Per_Reducao":                  "",
                "ST_Per_ICMS":                     "",
                "ST_Per_Margem":                   "",
                "Per_Fundo_Combate_Pobreza":       "",
                "###@@###":                        "###@@###",
            })

    return linhas_resultado


# ── Gravação Incremental em CSV ───────────────────────────────────────────────
def inicializar_csv(caminho: str) -> None:
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        writer.writeheader()


def gravar_lote_csv(linhas: list[dict], caminho: str) -> None:
    if not linhas:
        return
    with open(caminho, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        writer.writerows(linhas)


# ── Execução Principal ────────────────────────────────────────────────────────
async def main() -> None:
    inicio = time.time()
    log("Iniciando extração de tributação de todos os produtos...", inicio)

    url_lista_produtos, url_tabelas, headers = ler_configuracao()

    timeout = aiohttp.ClientTimeout(total=TIMEOUT_TOTAL)
    connector = aiohttp.TCPConnector(limit=CONCORRENCIA_PAGINAS + 2)
    rate_limiter = RateLimiter(INTERVALO_MINIMO_REQ)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        # 1. Carrega as tabelas tributárias e pré-computa templates
        log("Consultando tabelas tributárias...", inicio)
        dados_tabelas = await buscar_json(
            session, rate_limiter, url_tabelas, headers, label="Tabelas Tributárias"
        )
        templates = precomputar_templates_tributacao(dados_tabelas)
        log(f"Templates pré-computados para {len(templates)} situações fiscais distintas.", inicio)

        # 2. Inicializa o CSV de saída
        inicializar_csv(ARQUIVO_SAIDA)

        # 3. Consulta a primeira página de produtos para obter o total
        log("Consultando contagem total de produtos...", inicio)
        primeira_pag = await buscar_json(
            session,
            rate_limiter,
            url_lista_produtos,
            headers,
            params={"sort": "id", "start": 0, "count": PAGE_SIZE},
            label="Produtos Pág 1",
        )

        total_produtos = primeira_pag.get("total", 0)
        total_paginas = max(1, math.ceil(total_produtos / PAGE_SIZE)) if total_produtos else 1
        log(f"Total de produtos: {total_produtos:,} em {total_paginas} páginas (lotes de {PAGE_SIZE}).", inicio)

        # Processa a primeira página já obtida
        produtos_p1 = primeira_pag.get("items", [])
        linhas_p1 = gerar_linhas_para_produtos(produtos_p1, templates)
        gravar_lote_csv(linhas_p1, ARQUIVO_SAIDA)

        total_produtos_processados = len(produtos_p1)
        total_linhas_csv = len(linhas_p1)

        log(
            f"Pág 1/{total_paginas} | Produtos: {total_produtos_processados}/{total_produtos} "
            f"({(total_produtos_processados/total_produtos*100):.1f}%) | Linhas geradas: {total_linhas_csv}",
            inicio,
        )

        # 4. Processa as páginas restantes em lotes concorrentes controlados
        starts_restantes = list(range(PAGE_SIZE, total_produtos, PAGE_SIZE))
        semaforo = asyncio.Semaphore(CONCORRENCIA_PAGINAS)

        async def baixar_e_processar_pagina(start_idx: int, num_pagina: int):
            async with semaforo:
                pag = await buscar_json(
                    session,
                    rate_limiter,
                    url_lista_produtos,
                    headers,
                    params={"sort": "id", "start": start_idx, "count": PAGE_SIZE},
                    label=f"Produtos Pág {num_pagina}",
                )
                prods = pag.get("items", [])
                linhas = gerar_linhas_para_produtos(prods, templates)
                return len(prods), linhas, num_pagina

        # Agrupa páginas em lotes para streaming contínuo no CSV
        TAMANHO_BLOCO_PAGINAS = 10
        for i in range(0, len(starts_restantes), TAMANHO_BLOCO_PAGINAS):
            bloco = starts_restantes[i:i + TAMANHO_BLOCO_PAGINAS]
            tarefas = [
                baixar_e_processar_pagina(s, (s // PAGE_SIZE) + 1)
                for s in bloco
            ]
            resultados = await asyncio.gather(*tarefas, return_exceptions=True)

            linhas_bloco = []
            for res in resultados:
                if isinstance(res, Exception):
                    log(f"[AVISO] Erro ao processar página: {res}", inicio)
                    continue
                n_prods, linhas_pag, num_pag = res
                total_produtos_processados += n_prods
                linhas_bloco.extend(linhas_pag)

            gravar_lote_csv(linhas_bloco, ARQUIVO_SAIDA)
            total_linhas_csv += len(linhas_bloco)
            pct = (total_produtos_processados / total_produtos * 100) if total_produtos else 100

            log(
                f"Progresso: {total_produtos_processados}/{total_produtos} produtos ({pct:.1f}%) | "
                f"Total linhas no CSV: {total_linhas_csv:,}",
                inicio,
            )

            await asyncio.sleep(PAUSA_ENTRE_LOTES)

    log("=" * 60, inicio)
    log(f"Extração concluída com sucesso em {time.time() - inicio:.2f}s!", inicio)
    log(f"Total de produtos processados: {total_produtos_processados:,}", inicio)
    log(f"Total de linhas salvas no CSV: {total_linhas_csv:,}", inicio)
    log(f"Arquivo gerado: {ARQUIVO_SAIDA}", inicio)
    log("=" * 60, inicio)


if __name__ == "__main__":
    asyncio.run(main())
