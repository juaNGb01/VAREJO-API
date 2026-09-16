"""
config.py
---------
Modulo central de configuracao e definicao de caminhos para o projeto VAREJO-API.

Garante que todos os caminhos (Database, logs, staging_data, SQL, .env) sejam
absolutos e determinados a partir da raiz do projeto (PROJECT_ROOT), eliminando
problemas de dependencia do diretorio de trabalho corrente (os.getcwd()).
"""

import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────────────
# RAIZ DO PROJETO E SYS.PATH
# ──────────────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent

# Garante que a raiz do projeto esteja no sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Carrega explicitamente o arquivo .env a partir da raiz do projeto
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(ENV_FILE)

# ──────────────────────────────────────────────────────────────────────────────
# DIRETORIOS PADRONIZADOS
# ──────────────────────────────────────────────────────────────────────────────
DATABASE_DIR = PROJECT_ROOT / "Database"
LOGS_DIR = PROJECT_ROOT / "logs"
STAGING_DIR = PROJECT_ROOT / "staging_data"
SQL_DIR = PROJECT_ROOT / "SQL"
SQL_QUERYS_DIR = SQL_DIR / "querys_extracao"

# Garante a criacao de todos os diretorios necessarios
for directory in (DATABASE_DIR, LOGS_DIR, STAGING_DIR, SQL_DIR, SQL_QUERYS_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# BANCO DE DADOS DUCKDB
# ──────────────────────────────────────────────────────────────────────────────
DB_NAME = os.getenv("DB_NAME", "VALESOL.duckdb")
DB_PATH = DATABASE_DIR / DB_NAME

# ──────────────────────────────────────────────────────────────────────────────
# CREDENCIAIS E ENDPOINTS DA API VAREJO FACIL
# ──────────────────────────────────────────────────────────────────────────────
API_KEY = (os.getenv("API_KEY") or "").strip()
URL_CLIENTES = (os.getenv("URL_CLIENTES") or "").strip()
URL_FORNECEDORES = (os.getenv("URL_FORNECEDORES") or "").strip()
URL_PRODUTOS = (os.getenv("URL_PRODUTOS") or "").strip()

HEADERS = {
    "x-api-key": API_KEY,
    "content-type": "application/json",
}

# ──────────────────────────────────────────────────────────────────────────────
# LOGGING PADRONIZADO
# ──────────────────────────────────────────────────────────────────────────────
def setup_logger(name: str = "extractors", log_filename: str = "pipeline.log", level: int = logging.INFO) -> logging.Logger:
    """
    Configura e retorna um logger padronizado com saida em console e arquivo.
    O arquivo e salvo de forma deterministica em LOGS_DIR com codificacao UTF-8.
    Desabilita propagate para evitar mensagens duplicadas no terminal.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    # Limpa handlers existentes para evitar duplicacao caso chamado novamente
    if logger.handlers:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler de arquivo na pasta logs/
    log_filepath = LOGS_DIR / log_filename
    file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Handler do terminal / stdout
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


# ──────────────────────────────────────────────────────────────────────────────
# CARREGADOR DE CONSULTAS SQL
# ──────────────────────────────────────────────────────────────────────────────
def load_sql_query(sql_name: str) -> str:
    """
    Carrega o conteudo de um arquivo .SQL a partir do diretorio SQL/querys_extracao.
    Aceita 'CLIENTES' ou 'CLIENTES.SQL'.
    """
    if not sql_name.upper().endswith(".SQL"):
        sql_name = f"{sql_name}.SQL"
    
    query_file = SQL_QUERYS_DIR / sql_name
    if not query_file.exists():
        # Fallback para procurar em SQL_DIR direto
        query_file = SQL_DIR / sql_name
    
    if not query_file.exists():
        raise FileNotFoundError(f"Arquivo de query SQL nao encontrado: {query_file}")

    return query_file.read_text(encoding="utf-8").strip()

