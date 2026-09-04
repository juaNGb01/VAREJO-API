import asyncio
import csv
import json
import math
import time

import aiohttp


BASE_URL = "https://mercadinhovaledosol.varejofacil.com/api" # ajustar conforme necessário 
HEADERS = {
    "x-api-key": "4e7f6f32aa8702f0195e03e6ab3049e2",
    "Content-Type": "application/json",
}

URL_FORNECEDORES = f"{BASE_URL}/v1/pessoa/clientes"
ARQUIVO_SAIDA = r"C:\script_py_varejo\outputs\CLIFOR\CLIENTES_V1.csv"
TIMEOUT_TOTAL = 120
PAGE_SIZE = 500

MAPEAMENTO_CAMPOS = {
    "id": "Codigo_Cliente_Fornecedor",
    "contato": "Contato1",
    "observacao": "Observacao",
    "tipoDeFornecedor": "Ramo_Atividade",
    "regimeEstadualTributarioId": "Regime_Federal",
    "inscricaoEstadual": "Inscricao_Estadual",
    "numeroDoDocumento": "CNPJCPF",
    "numeroDeIdentificacao": "RG",
    "orgaoExpedidor": "Orgao_Emissor_RG",
    "inscricaoMunicipal": "Inscricao_Municipal",
    "nome": "Nome",
    "fantasia": "Apelido_Fantasia",
    "telefone1": "Fone_Comercial",
    "telefone2": "Fone_Residencial",
    "fax": "Fax",
    "email": "Email",
    "tipoDePessoa": "Pessoa",
    "criadoEm": "Data_Cadastro",
    "endereco.cep": "Cep",
    "endereco.uf": "UF",
    "endereco.codigoIbge": "IBGE",
    "endereco.municipio": "Cidade",
    "endereco.logradouro": "Endereco",
    "endereco.numero": "Numero",
    "endereco.bairro": "Bairro",
    "endereco.complemento": "Complemento",
}


def log(mensagem: str, inicio: float) -> None:
    decorrido = time.time() - inicio
    print(f"[{decorrido:8.1f}s] {mensagem}")


async def buscar_pagina(session: aiohttp.ClientSession, start: int) -> dict:
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_TOTAL)
    params = {"sort": "id", "start": start, "count": PAGE_SIZE}
    async with session.get(URL_FORNECEDORES, headers=HEADERS, params=params, timeout=timeout) as resposta:
        corpo = await resposta.text()

        if resposta.status != 200:
            raise RuntimeError(
                f"Falha ao consultar fornecedores. "
                f"HTTP {resposta.status}: {corpo[:500]}"
            )

        try:
            return json.loads(corpo)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "A API nao retornou JSON valido para a listagem de fornecedores. "
                f"Corpo recebido: {corpo[:500]}"
            ) from exc


def extrair_valor(dados: dict, caminho: str):
    valor = dados
    for chave in caminho.split("."):
        if not isinstance(valor, dict):
            return None
        valor = valor.get(chave)
        if valor is None:
            return None
    return valor


def transformar_para_csv(dados: dict) -> dict:
    linha = {}
    for campo_json, coluna_csv in MAPEAMENTO_CAMPOS.items():
        linha[coluna_csv] = extrair_valor(dados, campo_json)
    return linha


def inicializar_csv() -> None:
    colunas = list(MAPEAMENTO_CAMPOS.values())
    with open(ARQUIVO_SAIDA, "w", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=colunas, delimiter=";")
        writer.writeheader()


def inserir_no_csv(linhas: list[dict]) -> None:
    if not linhas:
        return

    colunas = list(MAPEAMENTO_CAMPOS.values())
    with open(ARQUIVO_SAIDA, "a", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=colunas, delimiter=";")
        writer.writerows(linhas)


def transformar_itens_em_linhas(itens: list[dict]) -> list[dict]:
    linhas = []
    for item in itens:
        if isinstance(item, dict):
            linhas.append(transformar_para_csv(item))
    return linhas


async def run() -> None:
    inicio = time.time()
    log("Execucao iniciada.", inicio)
    inicializar_csv()
    log(f"Arquivo CSV inicializado: {ARQUIVO_SAIDA}.", inicio)

    total_inseridos = 0

    timeout = aiohttp.ClientTimeout(total=TIMEOUT_TOTAL)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        primeira_pagina = await buscar_pagina(session, 0)

        total_registros = primeira_pagina.get("total", 0)
        total_paginas = max(1, math.ceil(total_registros / PAGE_SIZE)) if total_registros else 1
        log(
            f"Total de fornecedores na API: {total_registros} | "
            f"Tamanho da pagina: {PAGE_SIZE} | "
            f"Total de paginas: {total_paginas}.",
            inicio,
        )

        itens = primeira_pagina.get("items", [])
        linhas = transformar_itens_em_linhas(itens)
        inserir_no_csv(linhas)
        total_inseridos += len(linhas)
        log(
            f"Pagina 1/{total_paginas} recebida | "
            f"Registros na pagina: {len(itens)} | "
            f"Ja inseridos no CSV: {total_inseridos}.",
            inicio,
        )

        for numero_pagina, start in enumerate(range(PAGE_SIZE, total_registros, PAGE_SIZE), start=2):
            pagina = await buscar_pagina(session, start)
            itens = pagina.get("items", [])
            linhas = transformar_itens_em_linhas(itens)
            inserir_no_csv(linhas)
            total_inseridos += len(linhas)
            log(
                f"Pagina {numero_pagina}/{total_paginas} recebida | "
                f"Registros na pagina: {len(itens)} | "
                f"Ja inseridos no CSV: {total_inseridos}/{total_registros}.",
                inicio,
            )

    log(
        f"EXTRACAO FINALIZADA| Total informado pela API: {total_registros} | "
        f"Total inserido no CSV: {total_inseridos}.",
        inicio,
    )


if __name__ == "__main__":
    ...
#   asyncio.run(main())
