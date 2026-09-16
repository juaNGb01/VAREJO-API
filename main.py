# main.py
"""
Hub de Extracao de Dados - Varejo Facil
Permite execucao com interface grafica (Tkinter) ou via linha de comando (CLI).
"""

import argparse
import sys
import threading
from datetime import datetime
from pathlib import Path

# ──────────────────── Bootstrap de sys.path ──────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import setup_logger
from extractors import extracao_clientes, extracao_fornecedores, extracao_produtos

log = setup_logger("main", "hub_extratores.log")

EXTRACTORS = {
    "Clientes": extracao_clientes.main,
    "Fornecedores": extracao_fornecedores.main,
    "Produtos": extracao_produtos.main,
}


def run_cli(extrator_nome: str):
    """Executa o extrator via terminal/CLI."""
    if extrator_nome == "Todos":
        for nome, func in EXTRACTORS.items():
            print(f"\n[Hub] Executando extrator: {nome}")
            func()
    elif extrator_nome in EXTRACTORS:
        print(f"\n[Hub] Executando extrator: {extrator_nome}")
        EXTRACTORS[extrator_nome]()
    else:
        print(f"Erro: Extrator '{extrator_nome}' desconhecido. Opcoes: {list(EXTRACTORS.keys()) + ['Todos']}")
        sys.exit(1)


def run_gui():
    """Executa a interface grafica Tkinter."""
    import tkinter as tk
    from tkinter import ttk, scrolledtext

    class HubExtratores(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Hub de Extração de Dados - Varejo Fácil")
            self.geometry("650x450")

            # Seleção do extrator
            ttk.Label(self, text="Selecione o extrator:", font=("Segoe UI", 10, "bold")).pack(pady=(12, 0))
            opcoes = list(EXTRACTORS.keys()) + ["Todos"]
            self.combo = ttk.Combobox(self, values=opcoes, state="readonly", width=30)
            self.combo.pack(pady=5)
            self.combo.current(0)

            # Botão executar
            self.btn_executar = ttk.Button(self, text="Executar Extração", command=self.executar)
            self.btn_executar.pack(pady=5)

            # Log de saída
            self.log_box = scrolledtext.ScrolledText(self, state="disabled", height=18, font=("Consolas", 9))
            self.log_box.pack(fill="both", expand=True, padx=10, pady=10)

        def log_msg(self, msg):
            self.log_box.configure(state="normal")
            self.log_box.insert("end", f"[{datetime.now():%H:%M:%S}] {msg}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        def executar(self):
            nome = self.combo.get()
            self.btn_executar.config(state="disabled")
            self.log_msg(f"Iniciando: {nome}")

            # Roda em thread separada para não travar a GUI
            thread = threading.Thread(target=self._run_thread, args=(nome,), daemon=True)
            thread.start()

        def _run_thread(self, nome):
            try:
                if nome == "Todos":
                    for sub_nome, func in EXTRACTORS.items():
                        self.after(0, self.log_msg, f"-> Executando {sub_nome}...")
                        func()
                else:
                    EXTRACTORS[nome]()
                self.after(0, self.log_msg, f"Concluído com sucesso: {nome}")
            except Exception as e:
                self.after(0, self.log_msg, f"Erro em {nome}: {e}")
            finally:
                self.after(0, lambda: self.btn_executar.config(state="normal"))

    app = HubExtratores()
    app.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hub de Extração de Dados - Varejo Fácil")
    parser.add_argument(
        "--extrator",
        choices=list(EXTRACTORS.keys()) + ["Todos"],
        help="Executar extrator diretamente via linha de comando sem GUI.",
    )
    args = parser.parse_args()

    if args.extrator:
        run_cli(args.extrator)
    else:
        try:
            run_gui()
        except Exception as err:
            print(f"Não foi possível iniciar a interface gráfica ({err}). Use --extrator [Clientes|Fornecedores|Produtos|Todos]")