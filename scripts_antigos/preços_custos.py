import concurrent.futures
import csv
import os
import re
import tkinter as tk
from tkinter import messagebox, ttk

import requests


BASE_URL = "https://mercadinhovaledosol.varejofacil.com/api"
HEADERS = {
    "x-api-key": "4e7f6f32aa8702f0195e03e6ab3049e2", ## ajustar conforme chave da api
    "Content-Type": "application/json",
}

DIRETORIO_SAIDA = r"C:\tmp" ## Diretório onde os arquivos CSV serão salvos
PAGE_SIZE = 500 ## Quantidade de registros a serem buscados por requisição (ajustável conforme necessidade)
CONDICAO_PADRAO = "CCO" ## Condição padrão a ser preenchida no campo "Condicao" do CSV (ajustável conforme necessidade)
MAX_WORKERS = 8 ## Quantidade de requisições paralelas por endpoint (suba/desça conforme resposta da API)

## Definição das colunas do CSV na ordem desejada para importação no sistema de destino
COLUNAS = [
    "Condicao",
    "Empresa",
    "codigo_produto",
    "Codigo_produto_derivado",
    "Codigo_produto_externo",
    "codigo_barras",
    "descricao",
    "preco_varejo",
    "Margem_varejo",
    "Preco_atacado",
    "Margem_atacado",
    "Preco_prom_Varejo",
    "Dt_Inicio_Prom_Varejo",
    "Dt_Fim_Prom_Varejo",
    "Qtd_Min_Prom_Varejo",
    "Preco_Prom_Atacado",
    "Dt_Inicio_Prom_Atacado",
    "Dt_Fim_Prom_Atacado",
    "Qtd_Min_Prom_Atacado",
    "custo_reposicao",
    "custo_Gerencial",
    "custo_Nota_fiscal",
    "custo_ultima_compra",
]

sessao = requests.Session()
sessao.headers.update(HEADERS)
_adapter = requests.adapters.HTTPAdapter(pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS)
sessao.mount("https://", _adapter)
sessao.mount("http://", _adapter)


def _buscar_pagina(url_base: str, start: int) -> list[dict]:
    response = sessao.get(f"{url_base}start={start}&count={PAGE_SIZE}")
    if response.status_code == 200:
        return response.json().get("items", [])
    print(f"Falha na pagina start={start}. Codigo: {response.status_code}")
    return []


def buscar_dados_completos(endpoint: str, max_workers: int = MAX_WORKERS) -> list[dict]:
    print(f"Baixando dados de {endpoint}...")
    url_base = f"{BASE_URL}{endpoint}?"

    primeira = sessao.get(f"{url_base}start=0&count={PAGE_SIZE}").json()
    total = primeira.get("total", 0)
    itens = list(primeira.get("items", []))

    starts = range(PAGE_SIZE, total, PAGE_SIZE)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_buscar_pagina, url_base, s) for s in starts]
        for future in concurrent.futures.as_completed(futures):
            itens.extend(future.result())

    print(f" -> Concluido: {len(itens)} registros de {endpoint}.")
    return itens


def coletar_precos(lojas_selecionadas: set | None, max_workers: int = MAX_WORKERS) -> list[dict]:
    print("\nBuscando todos os registros de precos...")
    url_base = f"{BASE_URL}/v1/produto/precos?"

    primeira = sessao.get(f"{url_base}start=0&count={PAGE_SIZE}").json()
    total = primeira.get("total", 0)
    print(f" -> Total de precos na API: {total}")

    def filtrar(itens: list[dict]) -> list[dict]:
        if lojas_selecionadas is None:
            return itens
        return [p for p in itens if normalizar_loja_id(p.get("lojaId")) in lojas_selecionadas]

    registros_validos = filtrar(primeira.get("items", []))

    starts = range(PAGE_SIZE, total, PAGE_SIZE)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_buscar_pagina, url_base, s) for s in starts]
        for future in concurrent.futures.as_completed(futures):
            registros_validos.extend(filtrar(future.result()))
            print(f" -> {len(registros_validos)} registros filtrados ate agora...")

    return registros_validos


def inicializar_csv(caminho_arquivo: str) -> None:
    with open(caminho_arquivo, mode="w", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=COLUNAS, delimiter=";")
        writer.writeheader()


def salvar_lote(caminho_arquivo: str, dados: list[dict]) -> None:
    if not dados:
        return

    with open(caminho_arquivo, mode="a", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=COLUNAS, delimiter=";")
        writer.writerows(dados)


def selecionar_lojas_via_dialogo() -> list[int] | None:
    resultado = {"lojas": None}

    root = tk.Tk()
    root.title("Precos e custos")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")

    ttk.Label(
        frame,
        text="Escolha abaixo se deseja gerar todas as lojas ou apenas algumas.\n"
        "Para lojas especificas, informe os IDs separados por virgula.",
        justify="center",
        wraplength=360,
    ).grid(row=0, column=0, columnspan=2, pady=(0, 12))

    modo_var = tk.StringVar(value="todas")
    lojas_var = tk.StringVar(value="")

    radio_todas = ttk.Radiobutton(frame, text="Todas as lojas", variable=modo_var, value="todas")
    radio_especificas = ttk.Radiobutton(frame, text="Lojas especificas", variable=modo_var, value="especificas")
    entry_lojas = ttk.Entry(frame, textvariable=lojas_var, width=30)

    radio_todas.grid(row=1, column=0, sticky="w", pady=2)
    radio_especificas.grid(row=2, column=0, sticky="w", pady=2)
    entry_lojas.grid(row=2, column=1, padx=(8, 0), pady=2, sticky="ew")
    entry_lojas.configure(state="disabled")

    ttk.Label(
        frame,
        text="Exemplo: 1, 3, 5",
        foreground="#666666",
    ).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(2, 10))

    def atualizar_estado() -> None:
        estado = "normal" if modo_var.get() == "especificas" else "disabled"
        entry_lojas.configure(state=estado)

    def confirmar() -> None:
        if modo_var.get() == "todas":
            resultado["lojas"] = None
            root.destroy()
            return

        texto = lojas_var.get().strip()
        if not texto:
            messagebox.showerror("Selecao invalida", "Informe pelo menos um ID de loja ou escolha 'Todas as lojas'.")
            return

        lojas: list[int] = []
        for parte in re.split(r"[,\s;]+", texto):
            if not parte:
                continue
            try:
                lojas.append(int(parte))
            except ValueError:
                messagebox.showerror("Selecao invalida", f"ID de loja invalido: {parte}")
                return

        if not lojas:
            messagebox.showerror("Selecao invalida", "Informe pelo menos um ID de loja valido.")
            return

        resultado["lojas"] = sorted(set(lojas))
        root.destroy()

    def cancelar() -> None:
        resultado["lojas"] = []
        root.destroy()

    def marcar_especificas() -> None:
        modo_var.set("especificas")
        atualizar_estado()

    radio_todas.configure(command=atualizar_estado)
    radio_especificas.configure(command=marcar_especificas)

    botoes = ttk.Frame(frame)
    botoes.grid(row=4, column=0, columnspan=2, pady=(12, 0))
    ttk.Button(botoes, text="Cancelar", command=cancelar, width=12).grid(row=0, column=0, padx=4)
    ttk.Button(botoes, text="Iniciar", command=confirmar, width=12).grid(row=0, column=1, padx=4)

    root.protocol("WM_DELETE_WINDOW", cancelar)
    root.mainloop()

    if resultado["lojas"] == []:
        raise SystemExit("Execucao cancelada pelo usuario.")

    return resultado["lojas"]


def normalizar_loja_id(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return valor


def montar_registro(p: dict, mapa_descricoes: dict, mapa_barras: dict) -> dict:
    prod_id = p.get("produtoId")
    loja_id = p.get("lojaId")

    return {
        "Condicao": CONDICAO_PADRAO,
        "Empresa": loja_id,
        "codigo_produto": prod_id,
        "Codigo_produto_derivado": prod_id,
        "Codigo_produto_externo": prod_id,
        "codigo_barras": mapa_barras.get(prod_id, prod_id),
        "descricao": mapa_descricoes.get(prod_id, ""),
        "preco_varejo": p.get("precoVenda1", ""),
        "Margem_varejo": "",
        "Preco_atacado": "",
        "Margem_atacado": "",
        "Preco_prom_Varejo": "",
        "Dt_Inicio_Prom_Varejo": "",
        "Dt_Fim_Prom_Varejo": "",
        "Qtd_Min_Prom_Varejo": "",
        "Preco_Prom_Atacado": "",
        "Dt_Inicio_Prom_Atacado": "",
        "Dt_Fim_Prom_Atacado": "",
        "Qtd_Min_Prom_Atacado": "",
        "custo_reposicao": p.get("precoMedioDeReposicao", ""),
        "custo_Gerencial": p.get("custoProduto", ""),
        "custo_Nota_fiscal": p.get("precoFiscalDeReposicao", ""),
        "custo_ultima_compra": p.get("precoFiscalDeReposicao", ""),
    }


def processar_incremental() -> None:
    lojas_selecionadas = selecionar_lojas_via_dialogo()
    selecionadas_set = None if lojas_selecionadas is None else {normalizar_loja_id(loja) for loja in lojas_selecionadas}

    os.makedirs(DIRETORIO_SAIDA, exist_ok=True)

    registros_preco = coletar_precos(selecionadas_set)

    if not registros_preco:
        print("\nNenhum registro foi encontrado para os filtros selecionados.")
        return

    print("\nIniciando buscas paralelas...")
    endpoints = [
        "/v1/produto/produtos",
        "/v1/produto/codigos-auxiliares",
    ]

    resultados: dict[str, list[dict]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_to_endpoint = {executor.submit(buscar_dados_completos, ep): ep for ep in endpoints}
        for future in concurrent.futures.as_completed(future_to_endpoint):
            ep = future_to_endpoint[future]
            resultados[ep] = future.result()

    lista_produtos = resultados["/v1/produto/produtos"]
    mapa_descricoes = {p.get("id"): p.get("descricao", "") for p in lista_produtos}

    lista_codigos = resultados["/v1/produto/codigos-auxiliares"]
    mapa_barras = {}
    for codigo in lista_codigos:
        prod_id = codigo.get("produtoId")
        if prod_id not in mapa_barras:
            mapa_barras[prod_id] = codigo.get("id", "")

    print(f"\n[INFO] {len(mapa_descricoes)} produtos mapeados.")
    print(f"[INFO] {len(mapa_barras)} codigos de barras mapeados.")

    if lojas_selecionadas is None:
        # Quando selecionado "Todas as lojas", salva tudo junto em um único arquivo CSV
        caminho_arquivo = os.path.join(DIRETORIO_SAIDA, "precos_custos_todas_lojas.csv")
        inicializar_csv(caminho_arquivo)

        todos_registros = []
        for p in registros_preco:
            loja_id = normalizar_loja_id(p.get("lojaId"))
            if loja_id is None:
                continue
            todos_registros.append(montar_registro(p, mapa_descricoes, mapa_barras))

        salvar_lote(caminho_arquivo, todos_registros)
        print(f"\nArquivo único gerado com sucesso para todas as empresas: {caminho_arquivo}")
        print(f"Total de registros exportados: {len(todos_registros)}")
    else:
        # Quando selecionadas lojas específicas, gera arquivos separados por loja
        lotes_por_loja: dict = {}
        for p in registros_preco:
            loja_id = normalizar_loja_id(p.get("lojaId"))
            if loja_id is None:
                continue

            registro = montar_registro(p, mapa_descricoes, mapa_barras)
            lotes_por_loja.setdefault(loja_id, []).append(registro)

        arquivos_criados: set = set()
        for loja_id, registros in lotes_por_loja.items():
            caminho_arquivo = os.path.join(DIRETORIO_SAIDA, f"precos_loja_{loja_id}.csv")
            inicializar_csv(caminho_arquivo)
            salvar_lote(caminho_arquivo, registros)
            arquivos_criados.add(loja_id)

        if not arquivos_criados:
            print("\nNenhum arquivo foi gerado.")
            return

        print(f"\nArquivos gerados com sucesso em {DIRETORIO_SAIDA}!")
        print(f"Total de registros exportados: {len(registros_preco)}")


if __name__ == "__main__":
    processar_incremental()
