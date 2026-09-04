import asyncio
import csv
import json
import math
import time
from pathlib import Path

import aiohttp


BASE_URL = "https://redeleve.varejofacil.com/api"
HEADERS = {
    "x-api-key": "769f81fc13921e166952894b0c491fdd",
    "Content-Type": "application/json",
}

URL_PRODUTOS = f"{BASE_URL}/v1/produto/produtos"
ARQUIVO_IDS_PRODUTOS = "teste_prodforn_ids.csv"
ARQUIVO_SAIDA = "teste_prodforn.csv"
TIMEOUT_TOTAL = 120
PAGE_SIZE = 500
CONCORRENCIA_FORNECEDORES = 3
TENTATIVAS_REQUISICAO = 8
ESPERA_BASE_RETRY = 15
INTERVALO_MINIMO_REQUISICAO = 0.35
PAUSA_ENTRE_PAGINAS_PRODUTO = 1.0
TAMANHO_LOTE_IDS = 300
PAUSA_ENTRE_LOTES_IDS = 5.0

COLUNAS_IDS = ["produtoId"]
COLUNAS_CSV = [
    "Condicao",
    "Codigo_Produto",
    "Codigo_Produto_Derivado",
    "Codigo_Produto_Externo",
    "Codigo_Barras",
    "Descricao",
    "Condicao_Cliente_Fornecedor",
    "Codigo_Cliente_Fornecedor",
    "CNPJCPF",
    "Inscricao_Estadual",
    "Nome",
    "Codigo_Interno",
    "Fornecedor_Padrao",
    "Embalagem_Padrao",
    "Gramatura_Padrao",
    "Valor_Unitario",
    "##@@##",
]


def log(mensagem: str, inicio: float) -> None:
    decorrido = time.time() - inicio
    print(f"[{decorrido:8.1f}s] {mensagem}")


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


async def buscar_json(
    session: aiohttp.ClientSession,
    rate_limiter: RateLimiter,
    url: str,
    mensagem_erro: str,
    params: dict | None = None,
) -> dict:
    for tentativa in range(1, TENTATIVAS_REQUISICAO + 1):
        await rate_limiter.aguardar()

        try:
            async with session.get(url, headers=HEADERS, params=params) as resposta:
                corpo = await resposta.text()
        except asyncio.TimeoutError:
            if tentativa < TENTATIVAS_REQUISICAO:
                espera = ESPERA_BASE_RETRY + tentativa * 2
                print(
                    f"{mensagem_erro}. Timeout na tentativa {tentativa}/{TENTATIVAS_REQUISICAO}; "
                    f"aguardando {espera}s."
                )
                await rate_limiter.aplicar_pausa_extra(espera)
                continue
            raise RuntimeError(f"{mensagem_erro}. Timeout apos {TENTATIVAS_REQUISICAO} tentativas.")

        if resposta.status == 200:
            try:
                return json.loads(corpo)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{mensagem_erro}. A API nao retornou JSON valido. "
                    f"Corpo recebido: {corpo[:500]}"
                ) from exc

        if resposta.status in {429, 500, 502, 503, 504} and tentativa < TENTATIVAS_REQUISICAO:
            espera = ESPERA_BASE_RETRY * tentativa if resposta.status == 429 else 5 * tentativa
            print(
                f"{mensagem_erro}. HTTP {resposta.status}. "
                f"Tentativa {tentativa}/{TENTATIVAS_REQUISICAO}; aguardando {espera}s."
            )
            await rate_limiter.aplicar_pausa_extra(espera)
            continue

        raise RuntimeError(
            f"{mensagem_erro}. HTTP {resposta.status}: {corpo[:500]}"
        )

    raise RuntimeError(f"{mensagem_erro}. Falha apos {TENTATIVAS_REQUISICAO} tentativas.")


# Etapa 1: buscar todos os IDs de produtos e armazenar em CSV para reutilizacao.
async def buscar_pagina_produtos(
    session: aiohttp.ClientSession,
    rate_limiter: RateLimiter,
    start: int,
) -> dict:
    return await buscar_json(
        session,
        rate_limiter,
        URL_PRODUTOS,
        "Falha ao consultar a lista de produtos",
        params={"sort": "id", "start": start, "count": PAGE_SIZE},
    )


def inicializar_csv_ids() -> None:
    with open(ARQUIVO_IDS_PRODUTOS, "w", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=COLUNAS_IDS, delimiter=";")
        writer.writeheader()


def inserir_ids_no_csv(produtos_ids: list[int]) -> None:
    if not produtos_ids:
        return

    with open(ARQUIVO_IDS_PRODUTOS, "a", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=COLUNAS_IDS, delimiter=";")
        writer.writerows({"produtoId": produto_id} for produto_id in produtos_ids)


async def gerar_csv_ids_produtos(
    session: aiohttp.ClientSession,
    rate_limiter: RateLimiter,
    inicio: float,
) -> int:
    inicializar_csv_ids()
    primeira_pagina = await buscar_pagina_produtos(session, rate_limiter, 0)
    total_produtos = primeira_pagina.get("total", 0)
    total_paginas = max(1, math.ceil(total_produtos / PAGE_SIZE)) if total_produtos else 1
    total_ids_salvos = 0

    log(
        f"Gerando CSV de IDs | Total de produtos na API: {total_produtos} | "
        f"Total de paginas: {total_paginas}.",
        inicio,
    )

    for numero_pagina, start in enumerate(range(0, total_produtos or PAGE_SIZE, PAGE_SIZE), start=1):
        pagina = primeira_pagina if start == 0 else await buscar_pagina_produtos(session, rate_limiter, start)
        produtos = pagina.get("items", [])
        produtos_ids = [
            produto.get("id")
            for produto in produtos
            if isinstance(produto, dict) and produto.get("id") is not None
        ]
        inserir_ids_no_csv(produtos_ids)
        total_ids_salvos += len(produtos_ids)
        percentual = (total_ids_salvos / total_produtos * 100) if total_produtos else 100

        log(
            f"IDs salvos | Pagina {numero_pagina}/{total_paginas} | "
            f"Produtos lidos: {total_ids_salvos}/{total_produtos} ({percentual:.2f}%).",
            inicio,
        )

        if len(produtos) < PAGE_SIZE:
            break

        await asyncio.sleep(PAUSA_ENTRE_PAGINAS_PRODUTO)

    return total_ids_salvos


def carregar_ids_do_csv() -> list[int]:
    caminho = Path(ARQUIVO_IDS_PRODUTOS)
    if not caminho.exists():
        return []

    ids: list[int] = []
    with open(caminho, "r", newline="", encoding="utf-8-sig") as arquivo:
        reader = csv.DictReader(arquivo, delimiter=";")
        for linha in reader:
            valor = (linha or {}).get("produtoId")
            if not valor:
                continue
            try:
                ids.append(int(valor))
            except ValueError:
                continue
    return ids


# Etapa 2: ler o CSV de IDs e consultar apenas a rota de fornecedores.
async def buscar_fornecedores_do_produto(
    session: aiohttp.ClientSession,
    rate_limiter: RateLimiter,
    produto_id: int,
) -> list[dict]:
    url = f"{BASE_URL}/v1/produto/produtos/{produto_id}/fornecedores"
    primeira_pagina = await buscar_json(
        session,
        rate_limiter,
        url,
        f"Falha ao consultar fornecedores do produto {produto_id}",
        params={"sort": "id", "start": 0, "count": PAGE_SIZE},
    )

    itens = primeira_pagina.get("items", [])
    total = primeira_pagina.get("total", len(itens))
    if len(itens) >= total:
        return itens

    for start in range(PAGE_SIZE, total, PAGE_SIZE):
        pagina = await buscar_json(
            session,
            rate_limiter,
            url,
            f"Falha ao consultar fornecedores do produto {produto_id}",
            params={"sort": "id", "start": start, "count": PAGE_SIZE},
        )
        itens.extend(pagina.get("items", []))

    return itens


def transformar_em_linhas(registros: list[dict]) -> list[dict]:
    linhas = []
    for registro in registros:
        if not isinstance(registro, dict):
            continue
        linhas.append(
            {
                "Condicao": "CCO",
                "Codigo_Produto": registro.get("produtoId"),
                "Codigo_Produto_Derivado": registro.get("produtoId"),
                "Codigo_Produto_Externo": "",
                "Codigo_Barras": "",
                "Descricao": "",
                "Condicao_Cliente_Fornecedor": "CCO",
                "Codigo_Cliente_Fornecedor": registro.get("fornecedorId"),
                "CNPJCPF": "",
                "Inscricao_Estadual": "",
                "Nome": "",
                "Codigo_Interno": registro.get("referencia"),
                "Fornecedor_Padrao": registro.get("nivel"),
                "Embalagem_Padrao": registro.get("unidade"),
                "Gramatura_Padrao": registro.get("quantidade"),
                "Valor_Unitario": "",
                "##@@##": "##@@##",
            }
        )
    return linhas


def inicializar_csv_saida() -> None:
    with open(ARQUIVO_SAIDA, "w", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=COLUNAS_CSV, delimiter=";")
        writer.writeheader()


def inserir_no_csv(linhas: list[dict]) -> None:
    if not linhas:
        return

    with open(ARQUIVO_SAIDA, "a", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=COLUNAS_CSV, delimiter=";")
        writer.writerows(linhas)


async def processar_lote_ids(
    session: aiohttp.ClientSession,
    rate_limiter: RateLimiter,
    produto_ids: list[int],
) -> tuple[list[dict], int]:
    semaforo = asyncio.Semaphore(CONCORRENCIA_FORNECEDORES)

    async def processar_produto(produto_id: int):
        async with semaforo:
            return produto_id, await buscar_fornecedores_do_produto(session, rate_limiter, produto_id)

    tarefas = [processar_produto(produto_id) for produto_id in produto_ids]
    resultados = await asyncio.gather(*tarefas, return_exceptions=True)

    linhas_lote: list[dict] = []
    erros_lote = 0
    for resultado in resultados:
        if isinstance(resultado, Exception):
            erros_lote += 1
            print(f"Erro ao processar lote de fornecedores: {resultado}")
            continue

        produto_id, fornecedores = resultado
        if fornecedores:
            linhas_lote.extend(transformar_em_linhas(fornecedores))
        else:
            _ = produto_id

    return linhas_lote, erros_lote


async def extrair_relacoes_produto_fornecedor(
    session: aiohttp.ClientSession,
    rate_limiter: RateLimiter,
    inicio: float,
) -> None:
    produto_ids = carregar_ids_do_csv()
    total_produtos = len(produto_ids)
    inicializar_csv_saida()

    log(
        f"Iniciando leitura do CSV de IDs | Total de produtos para consultar: {total_produtos} | "
        f"Lote por ciclo: {TAMANHO_LOTE_IDS} | Concorrencia: {CONCORRENCIA_FORNECEDORES}.",
        inicio,
    )

    total_produtos_lidos = 0
    total_registros_inseridos = 0
    total_erros = 0

    for indice_inicial in range(0, total_produtos, TAMANHO_LOTE_IDS):
        lote_ids = produto_ids[indice_inicial:indice_inicial + TAMANHO_LOTE_IDS]
        linhas_lote, erros_lote = await processar_lote_ids(session, rate_limiter, lote_ids)
        inserir_no_csv(linhas_lote)

        total_produtos_lidos += len(lote_ids)
        total_registros_inseridos += len(linhas_lote)
        total_erros += erros_lote
        percentual = (total_produtos_lidos / total_produtos * 100) if total_produtos else 100

        log(
            f"Fornecedores consultados | Produtos lidos: {total_produtos_lidos}/{total_produtos} "
            f"({percentual:.2f}%) | Registros inseridos: {total_registros_inseridos} | "
            f"Erros: {total_erros}.",
            inicio,
        )

        if total_produtos_lidos < total_produtos:
            await asyncio.sleep(PAUSA_ENTRE_LOTES_IDS)


async def main() -> None:
    inicio = time.time()
    log("Execucao iniciada.", inicio)

    timeout = aiohttp.ClientTimeout(total=TIMEOUT_TOTAL)
    connector = aiohttp.TCPConnector(limit=CONCORRENCIA_FORNECEDORES + 2)
    rate_limiter = RateLimiter(INTERVALO_MINIMO_REQUISICAO)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        total_ids = await gerar_csv_ids_produtos(session, rate_limiter, inicio)
        log(f"CSV de IDs concluido com {total_ids} produtos.", inicio)
        await asyncio.sleep(PAUSA_ENTRE_LOTES_IDS)
        await extrair_relacoes_produto_fornecedor(session, rate_limiter, inicio)

    log(f"Execucao finalizada | Arquivos gerados: {ARQUIVO_IDS_PRODUTOS} e {ARQUIVO_SAIDA}.", inicio)


if __name__ == "__main__":
    asyncio.run(main())
