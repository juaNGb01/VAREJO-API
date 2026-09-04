import asyncio
import csv
import tkinter as tk
from tkinter import ttk

import aiohttp


# Configuracoes de requisicao HTTP para acessar a API do sistema Rede Leve.
# A chave x-api-key deve ser mantida atualizada e protegida em ambientes de producao.
HEADERS = {
    "x-api-key": "769f81fc13921e166952894b0c491fdd",
    "Content-Type": "application/json",
}

DATA_MINIMA = "2026-01-01"
STATUS_VALIDOS = {"ABERTO", "PARCIALMENTE_LIQUIDADO"}
DATA_MAXIMA = ""  # Example: "2026-12-31" -> empty means no upper limit
WORKERS = 5
PAGE_SIZE = 500
MODO_PADRAO = "pagar"


# Configuracoes de extracao para cada modo.
# Cada modo inclui a URL da API, o arquivo CSV de saida, colunas e mapeamento de campos.
# O mapeamento pode conter:
# - string: nome do campo no retorno da API
# - dict literal: valor fixo para a coluna CSV
# - tuple/list: campos combinados como texto formatado
MODOS = {
    "pagar": {
        "base_url": "https://redeleve.varejofacil.com/api/v1/financeiro/contas-pagar",
        "arquivo_saida": "contas_pagar_v2.csv",
        "colunas_csv": [
            "Condicao",
            "Codigo_Cliente_Fornecedor",
            "CNPJCPF",
            "Inscricao_Estadual",
            "Nome",
            "Empresa",
            "Titulo",
            "Digito",
            "Emissao",
            "Vencimento",
            "Valor",
            "Observacao",
            "Forma_Pagamento",
            "Conta_Contabil_Credito",
            "Conta_Contabil_Debito",
            "Codigo_Barras",
            "###@@###",
        ],
        "mapeamento_campos": {
            "Condicao": {"literal": "CCO"},
            "Codigo_Cliente_Fornecedor": "fornecedorId",
            "CNPJCPF": None,
            "Inscricao_Estadual": None,
            "Nome": None,
            "Empresa": "lojaId",
            "Titulo": "numeroDocumento",
            "Digito": "numeroDeTitulos",
            "Emissao": "dataEmissao",
            "Vencimento": "vencimento",
            "Valor": "valor",
            "Observacao": ("condicaoDePagamento", "numeroDocumento"),
            "Forma_Pagamento": {"literal": 24},
            "Conta_Contabil_Credito": None,
            "Conta_Contabil_Debito": None,
            "Codigo_Barras": None,
            "###@@###": {"literal": "###@@###"},
        },
    },
    "receber": {
        "base_url": "https://redeleve.varejofacil.com/api/v1/financeiro/contas-receber",
        "arquivo_saida": "contas_receber_v1.csv",
        "colunas_csv": [
            "Condicao",
            "Codigo_Cliente_Fornecedor",
            "CNPJCPF",
            "Inscricao_Estadual",
            "Nome",
            "Empresa",
            "Titulo",
            "Digito",
            "Emissao",
            "Vencimento",
            "Valor",
            "Observacao",
            "Forma_Pagamento",
            "Conta_Contabil_Credito",
            "Conta_Contabil_Debito",
            "Nosso_Numero",
            "Mora_Diaria",
            "###@@###",
        ],
        "mapeamento_campos": {
            "Condicao": {"literal": "CCO"},
            "Codigo_Cliente_Fornecedor": "clienteId",
            "CNPJCPF": None,
            "Inscricao_Estadual": None,
            "Nome": None,
            "Empresa": "lojaId",
            "Titulo": "numeroDocumento",
            "Digito": "numeroDeTitulos",
            "Emissao": "dataEmissao",
            "Vencimento": "vencimento",
            "Valor": "valor",
            "Observacao": ("condicaoDePagamento", "numeroDocumento"),
            "Forma_Pagamento": {"literal": 2},
            "Conta_Contabil_Credito": None,
            "Conta_Contabil_Debito": None,
            "Nosso_Numero": "nossoNumero",
            "Mora_Diaria": "moraDiariaPorAtraso",
            "###@@###": {"literal": "###@@###"},
        },
    },
}


BASE_URL = MODOS[MODO_PADRAO]["base_url"]
ARQUIVO_SAIDA = MODOS[MODO_PADRAO]["arquivo_saida"]
COLUNAS_CSV = list(MODOS[MODO_PADRAO]["colunas_csv"])
MAPEAMENTO_CAMPOS = dict(MODOS[MODO_PADRAO]["mapeamento_campos"])
COLUNAS = COLUNAS_CSV
MODO_SELECIONADO = MODO_PADRAO


def aplicar_configuracao(modo: str) -> None:
    global BASE_URL, ARQUIVO_SAIDA, COLUNAS_CSV, MAPEAMENTO_CAMPOS, COLUNAS, MODO_SELECIONADO

    # Valida o modo selecionado e atualiza as variaveis globais com a configuracao correta.
    if modo not in MODOS:
        raise ValueError(f"Modo invalido: {modo}")

    configuracao = MODOS[modo]
    BASE_URL = configuracao["base_url"]
    ARQUIVO_SAIDA = configuracao["arquivo_saida"]
    COLUNAS_CSV = list(configuracao["colunas_csv"])
    MAPEAMENTO_CAMPOS = dict(configuracao["mapeamento_campos"])
    COLUNAS = COLUNAS_CSV
    MODO_SELECIONADO = modo


def selecionar_modo_via_popup() -> str:
    selecionado = {"modo": MODO_PADRAO}

    root = tk.Tk()
    root.title("Extracao de contas")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = ttk.Frame(root, padding=18)
    frame.grid(row=0, column=0, sticky="nsew")

    ttk.Label(
        frame,
        text="Escolha o tipo de extracao antes de iniciar.",
        wraplength=320,
        justify="center",
    ).grid(row=0, column=0, columnspan=3, pady=(0, 10))

    modo_var = tk.StringVar(value=f"Modo atual: {selecionado['modo']}")
    ttk.Label(frame, textvariable=modo_var).grid(row=1, column=0, columnspan=3, pady=(0, 14))

    def atualizar_modo(modo: str) -> None:
        selecionado["modo"] = modo
        modo_var.set(f"Modo atual: {modo}")

    def iniciar() -> None:
        root.destroy()

    def cancelar() -> None:
        selecionado["modo"] = ""
        root.destroy()

    ttk.Button(frame, text="Iniciar", width=12, command=iniciar).grid(row=2, column=0, padx=4)
    ttk.Button(frame, text="Pagar", width=12, command=lambda: atualizar_modo("pagar")).grid(row=2, column=1, padx=4)
    ttk.Button(frame, text="Receber", width=12, command=lambda: atualizar_modo("receber")).grid(row=2, column=2, padx=4)

    root.protocol("WM_DELETE_WINDOW", cancelar)
    root.mainloop()

    if not selecionado["modo"]:
        raise SystemExit("Extracao cancelada pelo usuario.")

    return selecionado["modo"]


def inicializar_csv() -> None:
    # Cria o arquivo de saida e escreve o cabecalho com as colunas definidas.
    with open(ARQUIVO_SAIDA, mode="w", newline="", encoding="utf-8-sig") as arquivo:
        csv.DictWriter(arquivo, fieldnames=COLUNAS, delimiter=";").writeheader()
    print(f"Arquivo criado: {ARQUIVO_SAIDA}\n")


def inserir_no_csv(linhas: list[dict]) -> None:
    # Anexa linhas de resultado ao arquivo CSV, se houver dados para gravar.
    if not linhas:
        return

    with open(ARQUIVO_SAIDA, mode="a", newline="", encoding="utf-8-sig") as arquivo:
        csv.DictWriter(arquivo, fieldnames=COLUNAS, delimiter=";").writerows(linhas)


def obter_valor(item: dict, titulo: dict, campo_origem):
    # Retorna o valor a ser escrito no CSV com base no tipo de mapeamento configurado.
    # - None: campo vazio.
    # - literal: valor fixo.
    # - int: valor numérico direto.
    # - tuple/list: concatena campos de titulo/item separados por ' | '.
    # - string: busca o campo no titulo ou no item.
    if campo_origem is None:
        return ""
    if isinstance(campo_origem, dict) and "literal" in campo_origem:
        return campo_origem["literal"]
    if isinstance(campo_origem, int):
        return campo_origem
    if campo_origem == "###@@###":
        return "###@@###"
    if isinstance(campo_origem, (list, tuple)):
        partes = []
        for chave in campo_origem:
            valor = titulo.get(chave) if chave in titulo else item.get(chave)
            partes.append("" if valor is None else str(valor))
        return " | ".join([parte for parte in partes if parte])
    if campo_origem in titulo:
        valor = titulo.get(campo_origem)
    else:
        valor = item.get(campo_origem)
    return "" if valor is None else valor


def extrair_linhas(items: list) -> tuple[list, bool, bool]:
    # Converte cada item retornado pela API em linhas de CSV filtradas e mapeadas.
    # Retorna tambem flags que indicam se todas as paginas recebidas sao anteriores ou posteriores ao intervalo.
    resultado = []
    todos_anteriores = True
    todos_posteriores = True if DATA_MAXIMA else False

    for item in items:
        data_emissao = item.get("dataEmissao", "")

        if data_emissao:
            if data_emissao >= DATA_MINIMA:
                todos_anteriores = False
            if DATA_MAXIMA and data_emissao <= DATA_MAXIMA:
                todos_posteriores = False
            if not DATA_MAXIMA:
                todos_posteriores = False

        if data_emissao and data_emissao < DATA_MINIMA:
            continue
        if DATA_MAXIMA and data_emissao and data_emissao > DATA_MAXIMA:
            continue

        for titulo in item.get("titulos", []):
            if titulo.get("status") not in STATUS_VALIDOS:
                continue

            linha = {}
            for coluna_csv, campo_origem in MAPEAMENTO_CAMPOS.items():
                linha[coluna_csv] = obter_valor(item, titulo, campo_origem)
            resultado.append(linha)

    return resultado, todos_anteriores, todos_posteriores


async def buscar_pagina(session: aiohttp.ClientSession, start: int) -> tuple[int, dict | None]:
    # Realiza uma consulta paginada à API e retorna o start associado com os dados.
    # Retorna None em caso de erro para que o processamento continue nas outras paginas.
    params = {
        "start": start,
        "count": PAGE_SIZE,
        "status": list(STATUS_VALIDOS),
        "dataEmissao": DATA_MINIMA,
    }

    try:
        async with session.get(
            BASE_URL,
            headers=HEADERS,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resposta:
            if resposta.status == 200:
                return start, await resposta.json()
            print(f"Erro HTTP {resposta.status} em start={start}")
            return start, None
    except Exception as exc:
        print(f"Erro em start={start}: {exc}")
        return start, None


async def processar() -> None:
    # Fluxo principal de extracao:
    # 1. inicializa o arquivo CSV de saida
    # 2. consulta a primeira pagina para descobrir total de registros
    # 3. busca paginas em lotes paralelos
    # 4. filtra e mapeia registros para linhas de CSV
    # 5. para antecipadamente se o intervalo maximo for atingido
    print("=" * 60)
    print(f"Modo        : {MODO_SELECIONADO}")
    print(f"API         : {BASE_URL}")
    print(f"Status      : {', '.join(STATUS_VALIDOS)}")
    if DATA_MAXIMA:
        print(f"dataEmissao : entre {DATA_MINIMA} e {DATA_MAXIMA}")
    else:
        print(f"dataEmissao : >= {DATA_MINIMA}")
    print(f"Workers     : {WORKERS} requisicoes paralelas")
    print("=" * 60)
    print()

    inicializar_csv()

    async with aiohttp.ClientSession() as session:
        _, primeira = await buscar_pagina(session, 0)

    if not primeira:
        print("Nao foi possivel conectar a API.")
        return

    total_api = primeira.get("total", 0)
    print(f"Total de registros na API: {total_api}")
    print()

    todos_starts = list(range(0, total_api, PAGE_SIZE))

    total_inseridos = 0
    paginas_puladas = 0
    parada_por_maxima = False

    async with aiohttp.ClientSession() as session:
        for indice in range(0, len(todos_starts), WORKERS):
            lote_starts = todos_starts[indice: indice + WORKERS]
            tarefas = [buscar_pagina(session, start) for start in lote_starts]
            resultados = await asyncio.gather(*tarefas)
            resultados.sort(key=lambda item: item[0])

            lote_inseridos = 0
            for start, dados in resultados:
                if not dados:
                    continue

                items = dados.get("items", [])
                if not items:
                    continue

                linhas, toda_anterior, toda_posterior = extrair_linhas(items)

                if toda_anterior:
                    paginas_puladas += 1
                    print(f"  start={start} - pagina toda anterior a {DATA_MINIMA}, pulando...")
                    continue

                if toda_posterior:
                    print(f"  start={start} - pagina toda posterior a {DATA_MAXIMA}, finalizando leitura.")
                    parada_por_maxima = True
                    break

                inserir_no_csv(linhas)
                total_inseridos += len(linhas)
                lote_inseridos += len(linhas)

            lidos = min((indice + WORKERS) * PAGE_SIZE, total_api)
            percentual = (lidos / total_api * 100) if total_api else 0
            print(
                f"  [{lidos:>6} / {total_api}]"
                f"  +{lote_inseridos} linhas inseridas"
                f"  ({percentual:.1f}% lido)"
                f"  - total no arquivo: {total_inseridos}"
            )

            if parada_por_maxima:
                break

    print()
    print("=" * 60)
    print("Concluido!")
    print(f"Arquivo        : {ARQUIVO_SAIDA}")
    print(f"Total inserido : {total_inseridos} linhas")
    if DATA_MAXIMA:
        print(f"Paginas puladas : {paginas_puladas} (todas anteriores a {DATA_MINIMA})")
        print(f"Intervalo usado : {DATA_MINIMA} - {DATA_MAXIMA}")
    else:
        print(f"Paginas puladas : {paginas_puladas} (todas anteriores a {DATA_MINIMA})")
    print("=" * 60)


if __name__ == "__main__":
    modo = selecionar_modo_via_popup()
    aplicar_configuracao(modo)
    asyncio.run(processar())
