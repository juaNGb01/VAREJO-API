"""
base_extractor.py
-----------------
Modulo generico de extracao para endpoints da API Varejo Facil.

Responsabilidade unica: buscar todos os registros de um endpoint paginado
(start/count) em paralelo e retornar a lista completa de dicts brutos da API.

NAO salva arquivos em disco.
NAO sabe nada sobre DuckDB ou transformacoes especificas de cada entidade.
Cada extractor de endpoint especifico importa este modulo.

Uso:
    from extractors.base_extractor import fetch_all_pages

    items = fetch_all_pages(
        url="https://.../api/v1/pessoa/clientes",
        headers={"x-api-key": "..."},
        count=500,
        workers=6,
    )
    # items: list[dict] — todos os registros, ordenados por offset
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

log = logging.getLogger(__name__)


def fetch_all_pages(
    url: str,
    headers: dict,
    count: int = 500,
    workers: int = 6,
    timeout: int = 30,
) -> list:
    """
    Varre todos os registros de um endpoint paginado (start/count).

    Fluxo:
      1. Request inicial (start=0) -> le campo 'total' da resposta
      2. Calcula todos os offsets restantes: range(count, total, count)
      3. Baixa todas as paginas em paralelo com ThreadPoolExecutor
      4. Ordena resultados por offset e retorna lista completa de items

    Args:
        url:     URL base do endpoint (sem parametros)
        headers: Headers HTTP (x-api-key, content-type, etc.)
        count:   Itens por pagina -- maximo suportado pela API (padrao: 500)
        workers: Numero de threads paralelas (padrao: 6)
        timeout: Timeout por request em segundos (padrao: 30)

    Returns:
        list[dict]: Todos os items da API, ordenados por offset de origem.
                    Retorna lista vazia se o endpoint nao tiver dados.

    Raises:
        requests.HTTPError: Se a primeira request falhar (erro irrecuperavel).
    """


    """Responsável pela busca de 1 pagina. Retorna (start, items) -- nunca lanca excecao."""
    def _fetch_page(start):
        
        try:
            t0 = time.monotonic()
            resp = requests.get(
                url,
                headers=headers,
                params={"start": start, "count": count},
                timeout=timeout,
            )
            resp.raise_for_status()
            
            
            
            data = resp.json()
            items = data.get("items", [])
            log.debug(
                "offset=%-6d  %3d itens  %.2fs",
                start,
                len(items),
                time.monotonic() - t0,
            )
            return start, items
        except Exception as exc:
            log.error("Erro ao buscar offset=%d: %s", start, exc)
            return start, []

    # ------------------------------------------------------------------ #
    # Primeira request -- descobre o total de registros e traz o 1o lote #
    # ------------------------------------------------------------------ #
    log.info("Consultando endpoint: %s", url)
    t_inicio = time.monotonic()

    resp0 = requests.get(
        url,
        headers=headers,
        params={"start": 0, "count": count},
        timeout=timeout,
    )
    
    
    resp0.raise_for_status()
    data0 = resp0.json()

    #acessa o total de registros retornados pela api
    total = data0.get("total", 0)
    primeiros = data0.get("items", [])

    log.info(
        "Total de registros informado pela API: %d | 1a pagina: %d itens  (%.2fs)",
        total,
        len(primeiros),
        time.monotonic() - t_inicio,
    )

    if total == 0 or not primeiros:
        log.warning("Endpoint nao retornou dados.")
        return []



    # ------------------------------------------------------------------ #
    # Calcula offsets restantes e faz download paralelo                   #
    # ------------------------------------------------------------------ #
    
    #como já foi buscado 1 lote passa a buscar apenas os restantes
    offsets_restantes = list(range(count, total, count))

    # Mapa offset -> items (garante ordem na montagem final)
    resultados = {0: primeiros}


    if offsets_restantes:
        log.info(
            "Buscando %d pagina(s) restante(s) com %d workers...",
            len(offsets_restantes),
            workers,
        )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_fetch_page, offset): offset
                for offset in offsets_restantes
            }

            concluidos = 0
            for future in as_completed(futures):
                offset, items = future.result()
                resultados[offset] = items
                concluidos += 1

                if concluidos % 10 == 0 or concluidos == len(offsets_restantes):
                    acumulado = sum(len(v) for v in resultados.values())
                    log.info(
                        "  Progresso: %d/%d paginas concluidas | %d/%d registros",
                        concluidos,
                        len(offsets_restantes),
                        acumulado,
                        total,
                    )

    # ------------------------------------------------------------------ #
    # Monta lista ordenada pelo offset de origem                          #
    # ------------------------------------------------------------------ #
    todos = []
    for offset in sorted(resultados):
        todos.extend(resultados[offset])

    duracao = time.monotonic() - t_inicio
    log.info(
        "Extracao finalizada: %d registros coletados (esperado: %d) em %.1fs",
        len(todos),
        total,
        duracao,
    )

    # retorna caso exista divergencia entre o total esperado e o total retornado
    if len(todos) != total:
        log.warning(
            "ATENCAO: divergencia de contagem -- coletados %d vs. esperados %d",
            len(todos),
            total,
        )

    #retorna toda a lista com os valores
    return todos
