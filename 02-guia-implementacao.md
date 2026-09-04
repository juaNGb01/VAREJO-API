# Guia de implementação — passo a passo por níveis

Este guia está dividido em níveis progressivos. Cada nível tem um objetivo claro, o que fazer, um teste prático para validar o que foi feito, e um critério para saber que você pode avançar. Não pule níveis — cada um existe para você confirmar que o anterior está sólido antes de aumentar a complexidade.

Leia o documento 1 (visão geral) antes de começar, para entender o porquê de cada camada.

---

## Nível 0 — Antes de começar

**Objetivo:** garantir que você tem o mínimo necessário antes de escrever qualquer coisa.

**O que verificar:**
- Você tem credenciais/token de API de pelo menos um cliente de teste no Varejo Fácil.
- Você tem acesso à documentação da API (quais endpoints existem, como autenticar, como funciona a paginação).
- Python está instalado na sua máquina.

**Critério para avançar:** você consegue explicar, em uma frase, o que cada uma das cinco camadas da arquitetura faz.

---

## Nível 1 — Configuração do ambiente

**Objetivo:** ter um ambiente Python isolado, com as bibliotecas certas.

**O que fazer:**
- Criar uma pasta para o projeto.
- Criar um ambiente virtual (`venv`) dentro dela.
- Instalar as dependências: `requests`, `duckdb`, `python-dotenv`.
- Criar um arquivo `.env` (fora do controle de versão) com a URL base e o token da API do cliente de teste. Nunca deixe credencial escrita direto no código.

**Teste prático:** escreva um script mínimo que só importa `duckdb` e `requests` e imprime a versão de cada biblioteca. Se rodar sem erro, o ambiente está pronto.

**Critério para avançar:** o teste acima roda sem erro de instalação/importação.

---

## Nível 2 — Primeira extração (endpoint simples)

**Objetivo:** confirmar que você consegue autenticar e trazer dados reais, começando pelo endpoint mais simples (clientes ou fornecedores).

**O que fazer:**
- Fazer uma chamada autenticada ao endpoint de clientes.
- Salvar a resposta bruta (JSON), sem tratar nada ainda.
- Abrir o arquivo salvo e conferir visualmente se os campos batem com o que a documentação da API descreve.

**Teste prático:** compare a quantidade de registros retornados pela API com a quantidade que aparece na tela de clientes do próprio sistema Varejo Fácil daquele cliente de teste.

**Critério para avançar:** a contagem bate, e você tem um JSON bruto salvo localmente.

---

## Nível 3 — Primeiro contato com o DuckDB

**Objetivo:** aprender a mecânica de carregar dado no DuckDB, isolado do problema de join.

**O que fazer:**
- Criar um arquivo de banco DuckDB (ex: `cliente_teste.duckdb`).
- Carregar o JSON de clientes extraído no Nível 2 como uma tabela chamada `clientes`.
- Rodar uma consulta simples (`SELECT COUNT(*)`, e depois `SELECT *` limitado) para ver os dados carregados.

**Teste prático:** a contagem de linhas na tabela do DuckDB deve ser idêntica à contagem validada no Nível 2.

**Critério para avançar:** você consegue abrir o arquivo `.duckdb` e consultar a tabela sem erro.

---

## Nível 4 — Extração de volume maior (produtos) e paginação

**Objetivo:** lidar com os 50 mil+ produtos sem travar o processo.

**O que fazer:**
- Implementar a paginação do endpoint de produtos, respeitando o limite de itens por página da API.
- Medir e registrar quanto tempo leva para trazer tudo.
- Verificar na documentação se a API aceita algum filtro por data de alteração — anote isso, será usado mais adiante para extrair só o que mudou.

**Teste prático:** rode a extração completa e compare a contagem total de produtos retornados com o total informado no próprio sistema.

**Critério para avançar:** extração completa, sem página faltando, contagem batendo com o sistema.

---

## Nível 5 — Dados complementares e primeiro join local

**Objetivo:** trazer os dados que hoje exigiam cruzamento "no meio do caminho" (preços, custos, tributação) e aprender a cruzá-los fora da API.

**O que fazer:**
- Extrair os endpoints de preços/custos e de tributação da mesma forma que os produtos (bruto, salvo localmente).
- Carregar cada um como tabela própria no DuckDB (`produtos`, `precos_custos`, `tributacao`).
- Escrever sua primeira consulta de junção em um arquivo `.sql` separado (não direto dentro do script Python), relacionando as tabelas pelo id do produto.

**Teste prático:** escolha 5 produtos ao acaso no resultado do join e confira manualmente, na tela do Varejo Fácil, se o preço e a tributação batem com o que o sistema mostra.

**Critério para avançar:** os 5 produtos conferidos batem 100% com o sistema de origem.

---

## Nível 6 — Orquestração

**Objetivo:** automatizar a sequência inteira atrás de um único comando.

**O que fazer:**
- Escrever um script orquestrador que recebe qual cliente e quais entidades extrair.
- O script deve, na ordem: extrair → carregar no DuckDB → executar o(s) `.sql` de transformação → exportar o resultado em CSV.
- Garantir que rodar o script duas vezes seguidas não duplica dado (usando substituição de tabela, não inserção cega).

**Teste prático:** rode o script do zero, em ambiente limpo, e confira se o CSV final sai correto sem nenhuma intervenção manual no meio do processo. Rode de novo em seguida e confirme que o resultado não muda.

**Critério para avançar:** o processo roda de ponta a ponta sem passos manuais, e é repetível sem gerar dado duplicado.

---

## Nível 7 — Validação e replicabilidade

**Objetivo:** confirmar que o processo está maduro o suficiente para virar padrão para outros clientes Varejo Fácil.

**O que fazer:**
- Criar checagens automáticas simples: contagem de linhas do CSV final comparada ao staging bruto; nenhum produto sem preço/tributação quando deveria ter.
- Rodar o mesmo script em um segundo cliente Varejo Fácil, trocando apenas a configuração (URL/credencial), sem alterar código.

**Teste prático:** execute o processo completo para o segundo cliente e veja se funciona sem qualquer ajuste manual no script ou no SQL.

**Critério de sucesso do guia:** se precisar mexer em código para rodar em um cliente diferente, é sinal de que algo ainda está fixo no código que deveria estar em configuração — volte e ajuste antes de considerar o processo pronto.
