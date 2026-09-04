# Visão geral — Pipeline de extração de dados do Varejo Fácil

## O que será feito

Construção de um processo automatizado para extrair dados de clientes que utilizam o sistema Varejo Fácil como retaguarda, via API (já que não há acesso direto ao banco de dados). O processo cobre entidades simples (clientes, fornecedores) e entidades complexas (produtos, que exigem cruzamento com preços, custos e tributação), entregando ao final um CSV pronto no layout padrão usado pelo time de tratamento/conversão de dados.

Hoje esse processo é feito por scripts Python que extraem e já formatam o CSV na mesma etapa. Isso funciona bem para volumes pequenos, mas não escala para produtos (50 mil+ registros, múltiplos endpoints envolvidos). A proposta é reestruturar o processo em camadas independentes, de forma que ele fique mais rápido, mais fácil de depurar e, principalmente, **replicável para outros clientes que também usam o Varejo Fácil**, sem reescrever código a cada novo cliente.

## Objetivo final

Ter um processo em que:

- Extrair, cruzar e exportar os dados de um cliente Varejo Fácil vire a execução de **um único script**, informando apenas o cliente e quais entidades deseja extrair.
- A lógica de extração e cruzamento seja **genérica** (a mesma para qualquer cliente Varejo Fácil) — o que muda de cliente para cliente fica isolado em configuração (URL, credenciais), não em código.
- Erros em campos críticos (preço, tributação) sejam detectáveis automaticamente, e não descobertos manualmente depois que o dado já foi usado.
- Qualquer pessoa do time (não só quem escreveu o script) consiga rodar o processo e entender o resultado, com rastreabilidade até os dados brutos originais.

## Arquitetura

O processo é dividido em cinco camadas, cada uma com uma responsabilidade única:

1. **Configuração do cliente** — URL base, credenciais/token e quais entidades extrair. É a única parte que muda de cliente para cliente.
2. **Extração bruta** — chama a API do Varejo Fácil, pagina os resultados e salva o JSON de cada entidade sem transformar nada ainda. Aqui entra suporte a extração incremental (só o que mudou desde a última execução), quando a API permitir.
3. **Staging local (DuckDB)** — os arquivos brutos extraídos são carregados como tabelas dentro de um banco DuckDB local (ex: `produtos`, `precos_custos`, `tributacao`). É aqui que os dados passam a existir "fora da rede", prontos para serem cruzados sem custo de chamadas repetidas à API.
4. **Junção e transformação (SQL)** — os cruzamentos entre tabelas (ex: produto + preço + tributação) são escritos como arquivos `.sql` versionados, não embutidos no código Python. Isso torna a regra de negócio legível, auditável e reaproveitável entre clientes.
5. **Exportação (CSV)** — o resultado final da transformação é exportado no layout padrão esperado pelo time de tratamento, usando a exportação nativa do DuckDB.

Um script orquestrador em Python amarra as cinco camadas: ele não faz a lógica de cruzamento, apenas decide a ordem de execução (extrair → carregar → transformar → exportar) a partir da configuração do cliente escolhido.

## Ferramentas necessárias

| Ferramenta | Para que serve |
|---|---|
| Python 3.11+ | Linguagem do script orquestrador e da extração via API |
| `venv` (nativo do Python) | Isolar as dependências do projeto |
| `requests` (ou `httpx`) | Fazer as chamadas HTTP à API do Varejo Fácil |
| `duckdb` (biblioteca Python) | Staging local e execução dos joins via SQL |
| `python-dotenv` | Guardar credenciais/token fora do código-fonte |
| Git | Versionar o script orquestrador e os arquivos `.sql` de transformação |
| Editor de código (VSCode recomendado) | Desenvolvimento e leitura dos arquivos `.sql`/`.py` |
| Credenciais válidas da API do Varejo Fácil | Necessário ter acesso a pelo menos um cliente de teste |
| DuckDB CLI ou DBeaver (opcional) | Inspecionar manualmente os dados durante o desenvolvimento |

O documento de guia (arquivo 2) detalha, passo a passo, como configurar cada um desses itens e validar que cada etapa está funcionando antes de avançar para a próxima.
