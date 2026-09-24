# SEI Insights

Acompanha os **processos públicos** da unidade
`MMULHERES-SE-SGA-CGATI-CTI-DTI` do órgão **MMulheres** na **Pesquisa
Pública do SEI/ColaboraGov**
([colaboragov.sei.gov.br](https://colaboragov.sei.gov.br/)).

A cada execução o programa:

1. **descobre** os processos públicos vinculados à unidade no período
   configurado (padrão: últimos 7 dias);
2. identifica os processos **novos** em relação à execução anterior;
3. para cada processo, localiza o **último Despacho** da árvore de
   documentos e extrai o texto dele;
4. **interpreta** o despacho com regras determinísticas (arquivo
   `regras.json`) e classifica a **situação atual** e a **pendência**
   (o que falta / quem está com o processo);
5. grava uma **planilha XLSX** (fonte da verdade) com uma linha por
   processo, além de abas de Novos e Resumo;
6. reconstrói o banco **SQLite** como **espelho exato** da planilha.

> **Importante:** o programa **não** burla CAPTCHA, **não** acessa
> documentos restritos e **não** contorna bloqueios. Ele utiliza apenas
> os links públicos fornecidos pelo próprio SEI, seguindo o mesmo fluxo
> de um usuário humano. O CAPTCHA é tratado como no coletor de origem:
> resolução automática via OCR local ou manual no navegador.

---

## Índice

- [O que o script faz](#o-que-o-script-faz)
- [Como funciona](#como-funciona)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Pré-requisitos](#pré-requisitos)
- [Instalação das dependências](#instalação-das-dependências)
  - [Windows](#windows)
  - [Linux](#linux)
  - [macOS](#macos)
  - [Notas sobre a dependência de OCR](#notas-sobre-a-dependência-de-ocr)
- [Executando o programa](#executando-o-programa)
  - [Opções da linha de comando](#opções-da-linha-de-comando)
  - [Exemplos de uso](#exemplos-de-uso)
- [O que é gerado](#o-que-é-gerado)
  - [Planilha XLSX](#planilha-xlsx)
  - [`.state/`](#state)
- [As heurísticas do `regras.json`](#as-heurísticas-do-regrasjson)
  - [Como o motor decide](#como-o-motor-decide)
  - [Regras específicas da unidade](#regras-específicas-da-unidade)
  - [Regras genéricas](#regras-genéricas)
  - [O fallback "Em análise"](#o-fallback-em-análise)
- [Cache: por que um despacho novo é reanalisado](#cache-por-que-um-despacho-novo-é-reanalisado)
- [Como limpar os dados (ou reprocessar)](#como-limpar-os-dados-ou-reprocessar)
  - [Reprocessar tudo (`--force`)](#reprocessar-tudo---force)
  - [Apagar o histórico e recomeçar](#apagar-o-histórico-e-recomeçar)
  - [Limpar com o cliente SQLite](#limpar-com-o-cliente-sqlite)
- [Solução de problemas (FAQ)](#solução-de-problemas-faq)
- [Testes](#testes)

---

## O que o script faz

O **SEI Insights** é uma ferramenta de linha de comando (standalone, em
Python) que automatiza o acompanhamento da tramitação de processos
**públicos** de uma unidade do SEI/ColaboraGov. Em vez de abrir o portal
manualmente para conferir cada processo, o usuário roda o script e recebe
uma planilha com o **estado de cada processo**: qual a última movimentação
(Despacho), qual a situação atual calculada e o que falta para a pendência
ser resolvida.

O diferencial em relação a um simples "download de PDFs" é a camada de
**interpretação**: o texto do último Despacho é classificado por um motor
de regras determinístico — por exemplo, um despacho que diz
*"encaminham-se os autos para análise e providências da SGA"* resulta em
situação **"Aguardando providências da SGA"**, com `destino`, `acao_esperada`
e `pendencia_curta` preenchidos. As regras ficam em `regras.json` e podem
ser ajustadas **sem tocar no código**.

---

## Como funciona

O fluxo de execução é o seguinte:

```
busca por unidade + período (+ 3 tipos de pesquisa marcados)
  → lista de números de processos públicos (deduplicada)
  → diff com o espelho anterior (SQLite) → "novos"
  → para cada processo:
        página pública
        → árvore de documentos
        → último Despacho (+ URL pública correlacionada)
        → download do documento público
        → extração do texto (pypdf)
        → motor de regras (regras.json)
        → linha da planilha
  → grava a planilha XLSX (Aba principal + Novos + Resumo)
  → reconstrói o SQLite como espelho exato da planilha
```

1. **Descoberta** (`discovery.py` + `sei_client.py`): a pesquisa pública
   é preenchida com Órgão (`MMulheres`), Unidade
   (`MMULHERES-SE-SGA-CGATI-CTI-DTI`), período e as três opções
   "Pesquisar em" (Processos, Documentos Gerados, Documentos Externos).
   A resposta AJAX (POST com paginação `isPaginacao`) é observada e os
   números de processo são extraídos e **deduplicados**.

2. **Paginação**: o módulo devolve até 50 resultados por página
   (`rowsSolr=50`). Páginas seguintes avançam o parâmetro `inicio`; como
   no SEI, cada página pode exigir um novo CAPTCHA.

3. **Navegação ao processo** (`sei_client.py`): segue o link público
   `md_pesq_processo_exibir.php` fornecido pelo próprio resultado da
   pesquisa — nenhum link é fabricado.

4. **Árvore de documentos** (`tree.py`): a página pública monta a árvore
   via JavaScript. Para cada documento são lidos a **série documental**
   (ex.: "Despacho"), o **número documental** (5+ dígitos), a **data**
   (dd/mm/aaaa, quando presente) e a **posição** na árvore. O nó é
   correlacionado à URL pública pelo **número documental** (fallback:
   ordem de renderização).

5. **Último Despacho** (`tree.py`): entre os nós da série "Despacho",
   escolhe o de **maior data** (desempate: maior posição na árvore); sem
   data no DOM, usa o **último** nó "Despacho". Se não houver nenhum,
   a situação do processo é **"Sem despacho público"**.

6. **Download e texto** (`text_ing.py`): baixa **somente** o documento do
   último Despacho (usando a sessão/cookies do navegador, com pausas,
   retry e verificação de SHA-256) e extrai o texto com `pypdf`. Se o PDF
   não tiver camada de texto (digitalizado), a situação é
   **"Texto não extraível (digitalizado?)"** — sem OCR nesta versão.

7. **Classificação** (`rules.py` + `regras.json`): o texto é normalizado
   (espaços em excesso colapsados) e testado contra a lista ordenada de
   regras. A primeira regra que casar vence e produz os campos
   `situacao`, `destino`, `acao_esperada` e `pendencia_curta`. Nenhuma
   regra casou → **fallback "Em análise"**.

8. **Persistência** (`report.py` + `store.py`): gera a planilha XLSX e
   reconstrói o SQLite por inteiro, como **cópia idêntica** das linhas da
   planilha.

O programa é **sequencial** (nada de paralelismo, por propósito), aplica
pausas aleatórias entre requisições (padrão de 2 a 5 segundos) e trata
429 (`Retry-After`), 5xx e erros de conexão com backoff — comportamento
copiado do coletor de origem.

---

## Estrutura do projeto

| Arquivo / pasta                          | Função                                                            |
| ---------------------------------------- | ----------------------------------------------------------------- |
| `pyproject.toml`                         | Metadados do pacote e comando `sei-insights` (deps via `requirements.txt`). |
| `src/sei_insights/cli.py`                | CLI e orquestração (argumentos, `build_rows`, espelho).           |
| `src/sei_insights/config/__init__.py`    | Configuração central: caminhos (`.state`, `regras.json`) e padrões do CLI. |
| `src/sei_insights/config/rules.py`       | Motor de regras determinístico (lê `regras.json`).                |
| `regras.json`                            | Lista ordenada de regras de classificação (editável).             |
| `src/sei_insights/clients/sei_client.py` | Cliente da Pesquisa Pública (pesquisa, processo, CAPTCHA, download). |
| `src/sei_insights/clients/discovery.py`  | Parsing da resposta AJAX, paginação, dedupe.                      |
| `src/sei_insights/clients/rate_limit.py` | Pausa aleatória entre requisições (2–5s, configurável).            |
| `src/sei_insights/clients/captcha_solver.py` | Resolução de CAPTCHA por OCR (`ddddocr`), com retry.          |
| `src/sei_insights/documents/tree.py`     | Leitura da árvore de documentos, correlação nó → URL, último Despacho. |
| `src/sei_insights/documents/text_ing.py` | Extração de texto de PDF via `pypdf`.                             |
| `src/sei_insights/storage/mirror.py`     | Espelho SQLite da planilha (`MirrorStore`).                        |
| `src/sei_insights/storage/report.py`     | Geração da planilha XLSX (abas principal, Novos, Resumo).         |
| `src/sei_insights/utils/helpers.py`      | Apoio: normalização de número, SHA-256, MIME, nomes seguros.      |
| `requirements.txt`                       | Dependências Python do projeto (fonte única).                     |
| `tests/`                                 | Testes automatizados (`unittest`).                                 |
| `.state/`                                | Banco SQLite espelho + diagnósticos (gerado).                      |

> As pastas `.state/` e os arquivos `*.xlsx` são criados pelo programa e
> não devem ser versionados.

---

## Pré-requisitos

- **Python 3.10 ou superior** (recomendado; o Playwright tem suporte
  oficial aos três sistemas);
- pip (acompanha o Python);
- acesso à internet;
- sistema operacional **Windows**, **Linux** ou **macOS**.

---

## Instalação das dependências

As dependências estão listadas em `requirements.txt`:

```
playwright>=1.52,<2
beautifulsoup4>=4.13,<5
ddddocr>=1.4.0
opencv-python-headless>=4.8.0
pypdf>=5.0
openpyxl>=3.1
```

A instalação é a mesma para os três sistemas (criar o ambiente virtual,
instalar os pacotes e instalar o navegador). As únicas diferenças são os
comandos de ativação do ambiente virtual e, no Linux, as bibliotecas de
sistema. Clique na aba do seu sistema operacional para ver os passos:

### Windows

<details>
<summary>Instalação no Windows</summary>

1. Instale o Python em [python.org](https://www.python.org/downloads/).
   Durante a instalação, marque a opção **"Add Python to PATH"**.

2. Abra o **Prompt de Comando** ou o **PowerShell** na pasta do projeto.

3. Crie e ative um ambiente virtual (recomendado):

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Instale as dependências:

   ```powershell
   pip install -r requirements.txt
   pip install -e .
   ```

5. Instale o navegador Chromium usado pelo Playwright:

   ```powershell
   python -m playwright install chromium
   ```

> Se o comando `python` não funcionar, use `py` (executor oficial do
> Windows). Se o PowerShell bloquear a ativação do ambiente virtual com
> "Runnning scripts is disabled", execute uma vez:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`.

</details>

### Linux

<details>
<summary>Instalação no Linux</summary>

1. Instale o Python e o `venv` (exemplo no Ubuntu/Debian):

   ```bash
   sudo apt update
   sudo apt install python3 python3-venv
   ```

   Em distribuições baseadas em Fedora/RHEL:

   ```bash
   sudo dnf install python3 python3-pip
   ```

2. Na pasta do projeto, crie e ative um ambiente virtual:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Instale as dependências:

   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```

4. Instale o navegador e as dependências de sistema necessárias:

   ```bash
   python -m playwright install chromium --with-deps
   ```

   > O `--with-deps` instala as dependências de sistema do Chromium e
   > normalmente exige `sudo` (`pip install playwright` não cobre as
   > bibliotecas de sistema).
   >
   > Se preferir instalar manualmente depois:
   > `python -m playwright install-deps chromium`.

</details>

### macOS

<details>
<summary>Instalação no macOS</summary>

1. Instale o Python (recomendado via Homebrew):

   ```bash
   brew install python
   ```

2. Na pasta do projeto, crie e ative um ambiente virtual:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Instale as dependências:

   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```

4. Instale o navegador:

   ```bash
   python -m playwright install chromium
   ```

</details>

### Notas sobre a dependência de OCR

- O `ddddocr` usa `onnxruntime` e `opencv-python-headless`. Em algumas
  distribuições Linux pode ser necessário instalar `libgomp` para o
  onnxruntime funcionar:

  ```bash
  sudo apt install libgomp1
  ```

- O OCR é usado apenas para o CAPTCHA **automático**. Se ele não funcionar
  no seu ambiente, use a flag `--manual-captcha` (resolve o CAPTCHA no
  navegador; o programa detecta quando o campo é preenchido).

---

## Executando o programa

Na pasta do projeto, com o ambiente virtual ativado: (o comando `sei-insights` é equivalente e também está disponível após `pip install -e .`; sem o install, `python -m sei_insights` falha com `ModuleNotFoundError`).

```bash
python -m sei_insights
```

O programa descobre os processos públicos da unidade no período
configurado, classifica cada um e grava `sei_insights.xlsx` + o espelho
`.state/sei_insights.sqlite3`.

### Opções da linha de comando

| Opção                | Descrição                                                      |
| -------------------- | -------------------------------------------------------------- |
| `--orgao`            | Órgão gerador na pesquisa (padrão: `MMulheres`).               |
| `--unidade`          | Unidade geradora na pesquisa (padrão: `MMULHERES-SE-SGA-CGATI-CTI-DTI`). |
| `--dias`             | Janela de busca: de hoje-`dias` até hoje (padrão: `7`; deve ser > 0). |
| `--inicio`           | Data inicial explícita no formato `DD/MM/AAAA`; substitui `--dias`. |
| `--fim`              | Data final explícita no formato `DD/MM/AAAA`; padrão: hoje.    |
| `--manual-captcha`   | Resolve o CAPTCHA manualmente no navegador (padrão: OCR automático). |
| `--min-delay`        | Pausa mínima entre requisições, em segundos (padrão: `2.0`).   |
| `--max-delay`        | Pausa máxima entre requisições, em segundos (padrão: `5.0`).   |
| `--force`            | Reanalisa todos os processos ignorando o cache de hash.        |
| `--saida`            | Caminho da planilha gerada (padrão: `sei_insights.xlsx`).      |

### Exemplos de uso

```bash
# Execução padrão (últimos 7 dias)
python -m sei_insights

# Janela maior
python -m sei_insights --dias 14

# Período explícito
python -m sei_insights --inicio 01/09/2026 --fim 22/09/2026

# Outra unidade e CAPTCHA manual
python -m sei_insights --unidade "MMULHERES-SE-SGA-CGATI-CTI-DTI" --manual-captcha

# Ritmo mais lento (menos pressão no servidor) + força reanálise
python -m sei_insights --min-delay 3 --max-delay 7 --force

# Planilha em outro caminho
python -m sei_insights --saida relatorios/setembro.xlsx
```

> **CAPTCHA manual:** quando ativo, preencha o CAPTCHA **no navegador**.
> Não pressione ENTER no terminal — o programa continua sozinho assim que
> o campo é preenchido.

---

## O que é gerado

### Planilha XLSX

Arquivo `sei_insights.xlsx` (ou o caminho de `--saida`) com **três abas**:

- **Aba principal** — espelho do estado atual: **uma linha por processo**
  com as colunas abaixo;
- **Novos** — processos que **não** estavam no espelho anterior (mesma
  estrutura da aba principal);
- **Resumo** — contagens: total, novos, por situação e por status de
  coleta.

| Coluna               | Conteúdo                                                    |
| -------------------- | ----------------------------------------------------------- |
| `numero`             | Número do processo (normalizado).                           |
| `titulo`             | Título exibido na pesquisa pública.                         |
| `data_execucao`      | Data/hora da execução que gerou a linha.                    |
| `data_analise`       | Data/hora em que a situação foi calculada. Uma "vitória do cache" pode mantê-la mais antiga que a execução. |
| `data_ultimo_despacho` | Data do último Despacho (quando conhecida).              |
| `situacao`           | Situação classificada (ex.: "Aguardando providências de X"). |
| `destino`            | Unidade/órgão de destino.                                   |
| `acao_esperada`      | Ação pedida (análise, assinatura, retorno, providências...). |
| `pendencia_curta`    | Resumo de 1 linha: o que falta e quem está com o processo.  |
| `link_process`       | URL pública do processo.                                    |
| `status_coleta`      | `concluído`, `concluído (cache)` ou `erro: <mensagem>`.     |
| `hash_ultimo_despacho` | Hash SHA-256 do identificador do último Despacho (usado pelo cache). |

A planilha é **substituída a cada execução** (espelho do momento). Um
resultado vazio (0 processos) é válido: a planilha é gerada com as abas
vazias e o Resumo zerado, sem erro.

### `.state/`

| Arquivo                              | Conteúdo                                                   |
| ------------------------------------ | ---------------------------------------------------------- |
| `.state/sei_insights.sqlite3`        | Banco SQLite **espelho exato** da planilha (modo WAL).     |
| `.state/debug/`                      | Screenshots/HTML quando algo falha (diagnóstico).          |

O SQLite é reconstruído **por inteiro** ao fim de cada execução bem-sucedida
para conter **exatamente as linhas da planilha** (mesmas colunas; a chave
primária é `numero`). A planilha é a fonte da verdade; nada no banco impede
uma linha de ser gravada.

---

## As heurísticas do `regras.json`

### Como o motor decide

O motor (`rules.py`) lê `regras.json` — uma **lista ordenada** de regras.
Para cada despacho:

1. o texto é **normalizado**: múltiplos espaços/quebras viram um único
   espaço (`re.sub(r"\s+", " ", text)`);
2. as regras são testadas **na ordem do arquivo**, com a primeira
   correspondência vencendo (`re.search(..., re.IGNORECASE)`, caixa
   indiferente);
3. a regra vencedora preenche os quatro campos de saída. `destino`,
   `situacao`, `acao_esperada` e `pendencia_curta` podem usar
   **backreferences** (`\1`, `\2`...) que são expandidos pelos grupos
   capturados do padrão;
4. se **nenhuma** regra casar, vale o **fallback** (padrão: situação
   `"Em análise"`).

Cada regra tem a forma:

```json
{
  "pattern": "regex de busca (sem delimitadores)",
  "situacao": "Situação resultante (pode usar \\1)",
  "destino": "Destino extraído (pode usar \\1)",
  "acao_esperada": "Ação pedida",
  "pendencia_curta": "Resumo da pendência (pode usar \\1)"
}
```

### Regras específicas da unidade

As **5 primeiras** regras são as mais específicas e remetem diretamente à
unidade utilizada, `MMULHERES-SE-SGA-CGATI-CTI-DTI`. Para casar tanto o
nome completo quanto a forma curta, os padrões usam:

- **Nome completo**: `MMULHERES-SE-SGA-CGATI-CTI-DTI`;
- **Forma curta** (`...CTI`): `MMULHERES-SE-SGA-CGATI-CTI(?!-DTI)` — o
  **lookahead negativo** `(?!-DTI)` evita que a forma curta case "por
  dentro" do nome completo (senão `...CTI` casaria também em
  `...CTI-DTI` e a regra "curta" nunca seria a escolha correta).

Os hífens são opcionais nos padrões (`MMULHERES[\- ]SE[\- ]SGA...`), para
tolerar variações de formatação do SEI. As situações geradas:

| Regra | Gatilho no despacho | Situação gerada |
| ----- | ------------------- | --------------- |
| 1 | "retorno a esta/essa/a **unidade**", "aguardando retorno da/de **unidade**", "retorno para **unidade**" | `Aguardando retorno de <unidade>` |
| 2 | "para/com vistas a (ciência\|análise\|manifestação\|parecer\|providências) da/do/de **unidade**" | `Aguardando <ação> de <unidade>` |
| 3 | "adote-se/adotem-se/providencie-se/adotar providências/tomar providências ... **unidade**" | `Aguardando providências de <unidade>` |
| 4 | "dê-se ciência/cientifique-se/para ciência da/do/de **unidade**" | `Para ciência de <unidade>` |
| 5 | "encaminha-se/remete-se (os autos) a/para **unidade**" | `Encaminhado a <unidade> (nossa unidade)` |

A preferência por essas regras **antes** das genéricas é intencional:
quando o despacho fala da própria unidade, queremos o **nome exato** como
destino, e não um "destino qualquer".

### Regras genéricas

Depois das regras da unidade, vêm padrões que capturam **qualquer
destino/destinatária** (grupo genérico `[A-Za-zÀ-ÿ...]+?` terminado por
vírgula, ponto ou fim do texto) e padrões temáticos sem destino:

| Regra | Gatilho | Situação |
| ----- | ------- | -------- |
| 6 | "para/aguardando/pendente de **assinatura**" | `Pendente de assinatura` |
| 7 | "retorno a/aguardando retorno de/retorno para <destino>" | `Aguardando retorno` |
| 8 | "encaminha-se/remete-se (os autos) a/para <destino>" | `Encaminhado a <destino>` |
| 9 | "para/com vistas a (ação) de <destino>" | `Aguardando <ação> de <destino>` |
| 10–11 | "determino/determina-se o arquivamento", "arquive-se", "pelo arquivamento" | `Arquivado` |
| 12 | "devolva-se/devolvam-se/devolução dos autos" | `Devolvido` |
| 13 | "converta-se/transforme-se/conversão em (ofício\|nota técnica\|memorial\|termo)" | `Em conversão/transformação` |
| 14 | "dê-se ciência/cientifique-se/para ciência de <destino>" | `Para ciência de <destino>` |
| 15 | "adote-se/providencie-se/tomar providências (por) <destino>" | `Aguardando providências de <destino>` |
| 16 | "no prazo de/em até/prazo de **N** (dias\|horas\|meses)" | `Com prazo (N dias)` |
| 17 | "\b(defiro\|indefiro\|parcialmente procedente\|improcedente\|procedente)\b" | `Decisão: <termo>` |
| 18 | "cumpra-se/para cumprimento/determino cumprimento" | `Para cumprimento` |
| 19 | menção a unidade interna (`SGA`, `CCL`, `CTI`, `SCL`, `SG`, `COORDENAÇÃO`, `DIRETORIA`, `SECRETARIA`, `GERÊNCIA`, `NÚCLEO`, `DEPARTAMENTO`...) | `Em <unidade>` |
| 20 | órgão externo (`Ministério Público`, `Tribunal de Contas`, `Controladoria`, `Polícia Federal`, `Receita Federal`, `INSS`, `AGU`, `PGFN`, `MPF`, `TCU`, `CGU`...) | `Encaminhado a órgão externo (<órgão>)` |

> **Ordem importa.** Por serem avaliadas na ordem do arquivo, regras mais
> específicas devem vir primeiro. Uma regra genérica que casa quase tudo
> (ex.: a de órgão externo) fica no fim, para não "roubar" casos que as
> regras anteriores já teriam classificado melhor.
>
> **Ajuste de padrões:** por serem expressões regulares, adicionar/editar
> uma regra exige cuidado com escapes no JSON. Uma backreference no JSON
> é escrita como `\\1` (dois caracteres: `\` e `1`), que o `json.load`
> converte para `\1` antes de chegar ao motor.

### O fallback "Em análise"

Se nenhuma regra casar — texto irrelevante, conteúdo digitalizado sem
texto útil, formato inesperado — o processo recebe a situação padrão
**"Em análise"**, com `destino`, `acao_esperada` e `pendencia_curta`
vazios. Isso impede que um despacho desconhecido "trave" o restante da
execução: a linha é gravada na planilha mesmo assim.

---

## Cache: por que um despacho novo é reanalisado

Para não repetir download/análise de tudo a cada execução, o programa
guarda o **identificador do último Despacho** (número documental + data) e
grava o **hash SHA-256** dele na coluna `hash_ultimo_despacho`.

No início de cada execução, o espelho anterior (SQLite) é lido. Para cada
processo:

- **sem cache ou com `--force`** → analisa do zero;
- **com cache e hash inalterado** → usa os dados da análise anterior
  (campo `data_analise` preservado), marcando `status_coleta` como
  `concluído (cache)`. A linha continua sendo gravada na planilha;
- **com cache e hash mudou** (novo Despacho no SEI) → **reanalisa**
  o processo com a análise nova;
- **falha ao analisar** → gera linha `Erro / retry` com `status_coleta`
  = `erro: <mensagem>`, sem interromper os demais processos.

O hash é calculado sobre o **identificador do Despacho**, **não** sobre o
texto extraído. Isso é intencional: um PDF digitalizado (sem camada de
texto) não "congela" o processo — se o Despacho mudar, o identificador
muda e o processo é rebaixado e reanalisado na próxima execução.

> **Nota sobre a janela:** o espelho guarda apenas a última execução.
> Alternar a janela entre execuções (ex.: `--dias 7` ↔ `--dias 30`) pode
> sinalizar como "novos" processos já vistos antes — o efeito fica
> registrado na aba Resumo.

---

## Como limpar os dados (ou reprocessar)

### Reprocessar tudo (`--force`)

A forma mais simples de reanalisar todos os processos da janela,
ignorando o cache de hash:

```bash
python -m sei_insights --force
```

Nada é excluído: o `--force` apenas força a reanálise. O espelho é
reconstruído normalmente ao final.

### Apagar o histórico e recomeçar

Para limpar **todo** o histórico (banco espelho e diagnósticos) e começar
do zero:

**Windows (PowerShell):**

```powershell
Remove-Item -Recurse -Force .state
```

**Windows (Prompt de Comando):**

```cmd
rmdir /s /q .state
```

**Linux / macOS:**

```bash
rm -rf .state
```

Após isso, execute `python -m sei_insights` novamente: todos os processos da
janela serão tratados como novos.

### Limpar com o cliente SQLite

Se tiver o cliente `sqlite3` instalado, pode manipular o banco
diretamente:

```bash
sqlite3 .state/sei_insights.sqlite3
```

Exemplos úteis:

```sql
-- Ver todos os processos e seus status
SELECT numero, situacao, status_coleta
FROM processes ORDER BY numero;

-- Ver processos com pendência identificada
SELECT numero, situacao, pendencia_curta
FROM processes WHERE pendencia_curta != '';

-- Zerar o espelho por completo
DELETE FROM processes;
```

---

## Solução de problemas (FAQ)

**`python: command not found` / "Python was not found"**
Verifique se o Python está instalado e no PATH. No Windows, instale pela
[python.org](https://www.python.org/downloads/) marcando *"Add Python to
PATH"* ou use o `py` launcher.

**`ModuleNotFoundError: No module named 'playwright'` / `'bs4'` / ...**
As dependências não foram instaladas. Execute:
`pip install -r requirements.txt`.

**`Executable doesn't exist at ...chromium`**
O navegador do Playwright não foi instalado. Execute:
`python -m playwright install chromium` (no Linux, use `--with-deps`).

**CAPTCHA não é resolvido / OCR falha**
A dependência `ddddocr` pode não ter funcionado no seu sistema. Use a
opção `--manual-captcha`: o programa abre o navegador e você resolve o
CAPTCHA manualmente (não precisa teclar ENTER no terminal). No Linux,
verifique se `libgomp1` está instalado.

**Um processo aparece como "Sem despacho público"**
Significa que a árvore pública do processo não tem nenhum nó da série
"Despacho" — ou o processo não possui documentos públicos. Não é um erro
de execução; é a classificação correta para essa situação.

**Tudo aparece como "Em análise" (fallback)**
Nenhuma regra do `regras.json` casou com o texto do Despacho. Revise o
arquivo (veja [As heurísticas do `regras.json`](#as-heurísticas-do-regrasjson))
e adicione um padrão para o caso real observado.

**O processo ficou com `status_coleta = erro: ...`**
Um processo com falha não interrompe os demais. Corrija a causa indicada
na mensagem e rode `--force` para tentar novamente.

**A biblioteca `ddddocr` não instala (Linux/Windows)**
Ela depende de `onnxruntime`/`opencv-python-headless`; em caso de
problema, instale o `opencv-python-headless` primeiro e tente de novo. O
OCR só é usado para o CAPTCHA automático — o `--manual-captcha` não
depende dele.

**Como vejo o que está acontecendo?**
O programa registra tudo no terminal (formato
`data | nível | mensagem`). Em falhas estruturais, screenshots/HTML são
salvos em `.state/debug/` para diagnóstico.

---

## Testes

A suíte usa apenas a biblioteca padrão (`unittest`). É preciso ter o pacote
instalado (veja [Instalação das dependências](#instalação-das-dependências),
que inclui `pip install -e .`) e rodar **a partir da raiz do repositório**
(os testes leem `regras.json` relativo ao diretório atual):

```bash
python -m unittest discover -s tests -v
```

Para rodar um módulo específico:

```bash
python -m unittest tests.test_rules -v
python -m unittest tests.test_store -v
```