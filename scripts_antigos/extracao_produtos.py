import asyncio
import csv
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

import aiohttp

# ── Configurações Padrão ──────────────────────────────────────────────────────
BASE_URL_PADRAO           = "https://mercadinhovaledosol.varejofacil.com/api"
URL_PRODUTOS_PADRAO       = f"{BASE_URL_PADRAO}/v1/produto/produtos"
API_KEY_PADRAO            = "4e7f6f32aa8702f0195e03e6ab3049e2"
DIRETORIO_SAIDA           = r"C:\script_py_varejo\outputs\PRODUTOS"
ARQUIVO_SAIDA             = os.path.join(DIRETORIO_SAIDA, "PRODUTOS_V2.csv")

PAGE_SIZE                 = 500   # Quantidade de itens por página na API
CONCORRENCIA_PAGINAS      = 5    # Workers/páginas simultâneas
INTERVALO_MINIMO_REQ      = 0.25  # Intervalo mínimo (s) entre requisições
TENTATIVAS_REQUISICAO     = 8     # Tentativas em caso de timeout / 429 / 5xx
ESPERA_BASE_RETRY         = 12    # Tempo base (s) para retentativas de 429/timeouts
PAUSA_ENTRE_LOTES         = 0.5   # Pausa suave entre lotes de páginas
TIMEOUT_TOTAL             = 60    # Timeout total da requisição em segundos

# ── Mapeamento dos Campos para o CSV ──────────────────────────────────────────
MAPEAMENTO_CAMPOS: dict[str, Any] = {
    "Codigo_Produto": "id",
    "Descricao": "descricao",
    "SubDescricao": None,
    "Descricao_Resumida": "descricaoReduzida",
    "Marca_Fabricante": None,
    "Codigo_Barras": None,
    "Embalagem_Entrada": "unidadeDeCompra",
    "Gramatura_Entrada": "itensEmbalagem",
    "Embalagem_Saida": "unidadeDeVenda",
    "Gramatura_Saida": "itensEmbalagemVenda",
    "Modelo": None,
    "Tipo_Baixa": None,
    "Exporta_Balanca": ("enviaBalanca", "enviabalanca"),
    "Dias_Validade": None,
    "Status": "foraDeLinha",
    "Inativo_Compra": None,
    "Inativo_Venda": None,
    "NCM": ("ncmId", "ncmid", "nomeclaturaMercosulId"),
    "Codigo_CEST": "cest",
    "Multiplicador_Venda": None,
    "Utiliza_Lote": None,
    "Peso_Bruto": ("pesoBruto", "peso_bruto"),
    "Peso_Liquido": ("pesoLiquido", "peso_liquido"),
    "Codigo_Produto_Externo": None,
    "Referencia": None,
    "Tipo_Item": None,
    "Altura": "altura",
    "Comprimento": "comprimento",
    "Largura": "largura",
    "Cor": None,
    "Tamanho": None,
    "Per_Com_A_Vista": None,
    "Per_Com_A_Prazo": None,
    "Tipo": None,
    "Modelo_2": None,
    "Data_Cadastro": ("dataInclusao", "data_inclusao"),
    "Especificacoes_Tecnicas": None,
    "Divisao": None,
    "Secao": ("secaoId", "idSecao", "secao_id"),
    "Grupo": ("grupoId", "idGrupo", "grupo_id"),
    "Subgrupo": ("subgrupoId", "subGrupoId", "idSubGrupo", "subgrupo_id"),
    "Preco_Varejo": None,
    "Margem_Varejo": None,
    "Preco_Atacado": None,
    "Margem_Atacado": None,
    "Preco_Varejo_Promocao": None,
    "Dt_Inicio_Prom_Varejo": None,
    "Dt_Fim_Prom_Varejo": None,
    "Qtd_Min_Prom_Var": None,
    "Preco_Atacado_Promocao": None,
    "Dt_Inicio_Prom_Atacado": None,
    "Dt_Fim_Prom_Atacado": None,
    "Qtd_Min_Prom_Atac": None,
    "Custo_Reposicao": None,
    "Custo_Gerencial": None,
    "Custo_Nota_Fiscal": None,
    "Custo_Ultima_Compra": None,
    "CST_PISCOFINS_Entrada": None,
    "CST_PISCOFINS_Saida": None,
    "Natureza_PISCOFINS_Saida": None,
    "CST_IPI_Entrada": None,
    "Per_IPI_Entrada": None,
    "CST_IPI_Saida": None,
    "Per_IPI_Saida": None,
    "###@@###": {"literal": "###@@###"},
}


# ── Leitura de configurações (configs.txt) ────────────────────────────────────
def carregar_configuracoes() -> tuple[str, dict[str, str]]:
    """Carrega as URLs e Headers a partir do configs.txt, se disponível."""
    caminhos_possiveis = [
        Path("configs.txt"),
        Path("configo.txt"),
        Path(r"C:\script_py_varejo\configs.txt"),
        Path(__file__).resolve().parent.parent / "configs.txt",
    ]

    arquivo_config = next((p for p in caminhos_possiveis if p.exists()), None)
    url_produtos = URL_PRODUTOS_PADRAO
    headers = {
        "x-api-key": API_KEY_PADRAO,
        "Content-Type": "application/json",
    }

    if arquivo_config:
        try:
            texto = arquivo_config.read_text(encoding="utf-8")
            m_url = re.search(r"URL\s+PRODUTOS\s*=\s*(\S+)", texto, re.IGNORECASE)
            if m_url:
                url_limpa = re.sub(r"/\{Idproduto\}", "", m_url.group(1), flags=re.IGNORECASE)
                url_produtos = url_limpa.strip()

            m_key = re.search(r"x-api-key\s*:\s*([^,\s}]+)", texto, re.IGNORECASE)
            if m_key:
                headers["x-api-key"] = m_key.group(1).strip()

            m_content = re.search(r"Content-Type\s*:\s*([^,\s}]+)", texto, re.IGNORECASE)
            if m_content:
                headers["Content-Type"] = m_content.group(1).strip()
        except Exception as e:
            print(f"[AVISO] Erro ao ler configs.txt ({e}). Utilizando valores padrão.")

    return url_produtos, headers


# ── Rate Limiter com Pausa Dinâmica ───────────────────────────────────────────
class RateLimiter:
    """Controla o intervalo entre requisições e suporta pausas extras em caso de 429/timeout."""
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


# ── Requisição HTTP Resiliente com Callbacks ──────────────────────────────────
async def buscar_json(
    session: aiohttp.ClientSession,
    rate_limiter: RateLimiter,
    url: str,
    headers: dict[str, str],
    params: Optional[dict] = None,
    label: str = "",
    on_retry_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """Executa requisição GET com backoff exponencial para 429, timeouts e erros 5xx."""
    timeout_config = aiohttp.ClientTimeout(total=TIMEOUT_TOTAL)

    for tentativa in range(1, TENTATIVAS_REQUISICAO + 1):
        await rate_limiter.aguardar()
        try:
            async with session.get(url, headers=headers, params=params, timeout=timeout_config) as resp:
                corpo = await resp.text()

                if resp.status == 200:
                    try:
                        return json.loads(corpo)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(f"JSON inválido recebido de {url}: {corpo[:300]}") from exc

                # Limite de requisições excedido (429) ou erro transitório do servidor (5xx)
                if resp.status in {429, 500, 502, 503, 504} and tentativa < TENTATIVAS_REQUISICAO:
                    espera = ESPERA_BASE_RETRY * tentativa if resp.status == 429 else 5 * tentativa
                    motivo = "Rate Limit (429)" if resp.status == 429 else f"HTTP {resp.status}"
                    msg = (
                        f"[{motivo}] {label} - Tentativa {tentativa}/{TENTATIVAS_REQUISICAO}. "
                        f"Aguardando {espera}s antes de nova tentativa..."
                    )
                    print(msg)
                    if on_retry_callback:
                        on_retry_callback(msg)

                    await rate_limiter.aplicar_pausa_extra(espera)
                    continue

                raise RuntimeError(f"HTTP {resp.status} ao consultar {url}: {corpo[:300]}")

        except asyncio.TimeoutError:
            if tentativa < TENTATIVAS_REQUISICAO:
                espera = ESPERA_BASE_RETRY + (tentativa * 2)
                msg = (
                    f"[TIMEOUT] {label} - Tentativa {tentativa}/{TENTATIVAS_REQUISICAO}. "
                    f"Aguardando {espera}s..."
                )
                print(msg)
                if on_retry_callback:
                    on_retry_callback(msg)

                await rate_limiter.aplicar_pausa_extra(espera)
                continue
            raise RuntimeError(f"Timeout após {TENTATIVAS_REQUISICAO} tentativas: {label}")

        except Exception as exc:
            if tentativa < TENTATIVAS_REQUISICAO:
                espera = ESPERA_BASE_RETRY
                msg = f"[ERRO DE CONEXAO] {label}: {exc} - Aguardando {espera}s..."
                print(msg)
                if on_retry_callback:
                    on_retry_callback(msg)

                await rate_limiter.aplicar_pausa_extra(espera)
                continue
            raise

    raise RuntimeError(f"Falha ao consultar {label} após {TENTATIVAS_REQUISICAO} tentativas.")


# ── Utilitários de Mapeamento e CSV ───────────────────────────────────────────
def extrair_valor(dados: dict, caminho: Any) -> Any:
    """Extrai valores do JSON com suporte a caminhos aninhados, literais e tuplas de fallback."""
    if caminho is None:
        return ""
    if isinstance(caminho, dict) and "literal" in caminho:
        return caminho["literal"]
    if caminho == "###@@###":
        return "###@@###"
    if isinstance(caminho, (list, tuple)):
        for sub_caminho in caminho:
            val = extrair_valor(dados, sub_caminho)
            if val is not None and val != "":
                return val
        return ""

    if not isinstance(dados, dict):
        return ""

    valor = dados
    for chave in caminho.split("."):
        if not isinstance(valor, dict):
            return ""
        valor = valor.get(chave)
        if valor is None:
            return ""
    return valor


def transformar_item_para_csv(item: dict) -> dict:
    """Mapeia um item da API para a linha correspondente do CSV."""
    linha = {}
    for coluna_csv, campo_json in MAPEAMENTO_CAMPOS.items():
        linha[coluna_csv] = extrair_valor(item, campo_json)
    return linha


def transformar_itens_em_linhas(itens: list[dict]) -> list[dict]:
    """Converte uma lista de itens retornados pela API em lista de linhas para o CSV."""
    linhas = []
    for item in itens:
        if isinstance(item, dict):
            linhas.append(transformar_item_para_csv(item))
    return linhas


def inicializar_csv(caminho_arquivo: str) -> None:
    """Inicializa o arquivo CSV criando diretórios se necessário e escrevendo o cabeçalho."""
    diretorio = os.path.dirname(caminho_arquivo)
    if diretorio:
        os.makedirs(diretorio, exist_ok=True)

    colunas = list(MAPEAMENTO_CAMPOS.keys())
    with open(caminho_arquivo, "w", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=colunas, delimiter=";")
        writer.writeheader()


def inserir_no_csv(linhas: list[dict], caminho_arquivo: str) -> None:
    """Insere um lote de linhas no arquivo CSV."""
    if not linhas:
        return

    colunas = list(MAPEAMENTO_CAMPOS.keys())
    with open(caminho_arquivo, "a", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=colunas, delimiter=";")
        writer.writerows(linhas)


# ── Execução Principal da Extração ────────────────────────────────────────────
async def run(
    log_callback: Optional[Callable[[str], None]] = None,
    caminho_saida: str = ARQUIVO_SAIDA,
) -> None:
    """
    Executa a extração completa de todos os produtos do Varejo Fácil.
    Pode ser executado diretamente ou chamado pelo Hub GUI (main.py).
    """
    inicio = time.time()

    def log(mensagem: str) -> None:
        decorrido = time.time() - inicio
        texto = f"[{decorrido:7.1f}s] {mensagem}"
        print(texto)
        if log_callback:
            log_callback(mensagem)

    url_produtos, headers = carregar_configuracoes()

    log("Iniciando extração de produtos...")
    log(f"URL API: {url_produtos}")
    log(f"Arquivo CSV de saída: {caminho_saida}")

    inicializar_csv(caminho_saida)
    log("Arquivo CSV inicializado.")

    rate_limiter = RateLimiter(INTERVALO_MINIMO_REQ)
    connector = aiohttp.TCPConnector(limit=CONCORRENCIA_PAGINAS + 2)
    timeout_sessao = aiohttp.ClientTimeout(total=TIMEOUT_TOTAL)

    total_inseridos = 0

    async with aiohttp.ClientSession(connector=connector, timeout=timeout_sessao) as session:
        # 1. Consulta a primeira página para identificar o total de registros
        primeira_pagina = await buscar_json(
            session=session,
            rate_limiter=rate_limiter,
            url=url_produtos,
            headers=headers,
            params={"sort": "id", "start": 0, "count": PAGE_SIZE},
            label="Produtos Pág 1",
            on_retry_callback=log_callback,
        )

        total_registros = primeira_pagina.get("total", 0)
        total_paginas = max(1, math.ceil(total_registros / PAGE_SIZE)) if total_registros else 1

        log(
            f"Total de produtos na API: {total_registros:,} | "
            f"Tamanho da página: {PAGE_SIZE} | "
            f"Total de páginas: {total_paginas} | "
            f"Concorrência: {CONCORRENCIA_PAGINAS} workers."
        )

        # Grava os itens da primeira página
        itens_p1 = primeira_pagina.get("items", [])
        linhas_p1 = transformar_itens_em_linhas(itens_p1)
        inserir_no_csv(linhas_p1, caminho_saida)
        total_inseridos += len(linhas_p1)

        pct_p1 = (total_inseridos / total_registros * 100) if total_registros else 100
        log(
            f"Pág 1/{total_paginas} recebida | "
            f"Registros na página: {len(itens_p1)} | "
            f"Inseridos no CSV: {total_inseridos:,}/{total_registros:,} ({pct_p1:.1f}%)."
        )

        # 2. Processa as páginas restantes em lotes concorrentes controlados
        starts_restantes = list(range(PAGE_SIZE, total_registros, PAGE_SIZE))
        semaforo = asyncio.Semaphore(CONCORRENCIA_PAGINAS)

        async def baixar_e_transformar_pagina(start_idx: int, num_pagina: int) -> tuple[int, list[dict]]:
            async with semaforo:
                pag = await buscar_json(
                    session=session,
                    rate_limiter=rate_limiter,
                    url=url_produtos,
                    headers=headers,
                    params={"sort": "id", "start": start_idx, "count": PAGE_SIZE},
                    label=f"Produtos Pág {num_pagina}",
                    on_retry_callback=log_callback,
                )
                itens = pag.get("items", [])
                linhas = transformar_itens_em_linhas(itens)
                return num_pagina, linhas

        # Processamento em blocos com gravação incremental
        TAMANHO_BLOCO = CONCORRENCIA_PAGINAS * 2
        for i in range(0, len(starts_restantes), TAMANHO_BLOCO):
            bloco_starts = starts_restantes[i:i + TAMANHO_BLOCO]
            tarefas = [
                baixar_e_transformar_pagina(s, (s // PAGE_SIZE) + 1)
                for s in bloco_starts
            ]
            resultados = await asyncio.gather(*tarefas, return_exceptions=True)

            linhas_bloco = []
            for res in resultados:
                if isinstance(res, Exception):
                    log(f"[ERRO] Falha ao processar lote de páginas: {res}")
                    continue
                num_pag, linhas_pag = res
                linhas_bloco.extend(linhas_pag)

            inserir_no_csv(linhas_bloco, caminho_saida)
            total_inseridos += len(linhas_bloco)

            pct = (total_inseridos / total_registros * 100) if total_registros else 100
            ultima_pag_bloco = min(total_paginas, (bloco_starts[-1] // PAGE_SIZE) + 1)

            log(
                f"Progresso: Pág {ultima_pag_bloco}/{total_paginas} | "
                f"Inseridos no CSV: {total_inseridos:,}/{total_registros:,} ({pct:.1f}%)."
            )

            await asyncio.sleep(PAUSA_ENTRE_LOTES)

    log("=" * 60)
    log(
        f"EXTRACAO FINALIZADA COM SUCESSO! | "
        f"Total informado pela API: {total_registros:,} | "
        f"Total inserido no CSV: {total_inseridos:,} | "
        f"Arquivo: {caminho_saida}"
    )
    log("=" * 60)


if __name__ == "__main__":
    asyncio.run(run())
