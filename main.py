# main.py
import asyncio
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import datetime
from scripts_antigos import extracao_produtos
from scripts_antigos import extracao_clientes, extracao_fornecedores

EXTRACTORS = {
    "Clientes": extracao_clientes.run,
    "Fornecedores": extracao_fornecedores.run,
    "Produtos": extracao_produtos.run,
}


class HubExtratores(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Hub de Extração de Dados")
        self.geometry("600x400")

        # Seleção do extrator
        ttk.Label(self, text="Selecione o extrator:").pack(pady=(10, 0))
        self.combo = ttk.Combobox(self, values=list(EXTRACTORS.keys()), state="readonly")
        self.combo.pack(pady=5)
        self.combo.current(0)

        # Botão executar
        self.btn_executar = ttk.Button(self, text="Executar", command=self.executar)
        self.btn_executar.pack(pady=5)

        # Log de saída
        self.log = scrolledtext.ScrolledText(self, state="disabled", height=15)
        self.log.pack(fill="both", expand=True, padx=10, pady=10)

    def log_msg(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", f"[{datetime.now():%H:%M:%S}] {msg}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def executar(self):
        nome = self.combo.get()
        func = EXTRACTORS[nome]
        self.btn_executar.config(state="disabled")
        self.log_msg(f"Iniciando: {nome}")

        # Roda em thread separada para não travar a GUI
        thread = threading.Thread(target=self._run_async, args=(func, nome), daemon=True)
        thread.start()

    def _run_async(self, func, nome):
        try:
            asyncio.run(func())
            self.after(0, self.log_msg, f"Concluído: {nome}")
        except Exception as e:
            self.after(0, self.log_msg, f"Erro em {nome}: {e}")
        finally:
            self.after(0, lambda: self.btn_executar.config(state="normal"))


if __name__ == "__main__":
    app = HubExtratores()
    app.mainloop()