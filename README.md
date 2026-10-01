# SEI Insights

Acompanha os **processos públicos** da unidade
`MMULHERES-SE-SGA-CGATI-CTI` do órgão **MMulheres** na **Pesquisa
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
   processo e uma aba **Resumo da última execução**;
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
  - [O placeholder `{destino}`](#o-placeholder-destino)
  - [De onde vem cada campo (nada é inventado)](#de-onde-vem-cada-campo-nada-e-inventado)
    - [Quando não há texto para interpretar](#quando-não-há-texto-para-interpretar)
    - [Como auditar uma linha da planilha](#como-auditar-uma-linha-da-planilha)
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
  → linhas de resultado (itens: processos E documentos — 1 linha por item)
  → dedupe pela URL do processo → 1 resultado por processo
    (o "total" do SEI conta LINHAS, não processos: várias linhas podem
     apontar para o mesmo processo-pai, então o total que ele informa é
     sempre ≥ o número de linhas da planilha — ver "Como funciona")
  → número canônico do processo (cabeçalho "Processo:" da página pública)
  → diff com o espelho anterior (SQLite) → "novos"
  → para cada processo:
        página pública
        → árvore de documentos
        → último Despacho (+ URL pública correlacionada)
        → download do documento público
        → extração do texto (pypdf)
        → motor de regras (regras.json)
        → linha da planilha
  → grava a planilha XLSX (Aba principal + Resumo da última execução)
  → reconstrói o SQLite como espelho exato da planilha
```

1. **Descoberta** (`discovery.py` + `sei_client.py`): a pesquisa pública
   é preenchida com Órgão (`MMulheres`), Unidade
   (`MMULHERES-SE-SGA-CGATI-CTI`), período e as três opções
   "Pesquisar em" (Processos, Documentos Gerados, Documentos Externos).
   A resposta AJAX (POST com paginação `isPaginacao`) é observada e as
   linhas de resultado são extraídas.

   Como os três tipos de pesquisa estão marcados, o SEI devolve **uma
   linha por item que casar**: processos **e** documentos. Uma linha de
   documento carrega o `data-prot` = número do **documento** e um link
   (`md_pesq_processo_exibir.php`) para o **processo-pai** — ou seja, o
   mesmo processo pode aparecer várias vezes na busca (uma vez por
   documento seu). A **dedupe é feita pela URL do processo**, não pelo
   número: todas as linhas que apontam para a mesma página de processo
   colapsam em um único resultado. Sem isso, um processo descoberto por
   N documentos era visitado e baixado N vezes (bug real).

   > **Por que o total que o SEI informa é maior que o número de linhas
   > da planilha?**
   >
   > São grandezas diferentes, e a diferença **não** é perda de coleta.
   >
   > - o total do SEI (`data.itens`) conta **linhas**, isto é, **itens**
   >   casados pela pesquisa;
   > - a planilha tem **uma linha por processo único**, depois da dedupe.
   >
   > Como a pesquisa marca **Processos + Documentos Gerados + Documentos
   > Recebidos**, cada linha é um *item* encontrado, e vários itens podem
   > pertencer ao **mesmo processo-pai**. Um processo com três documentos
   > na árvore gera três linhas apontando para a mesma página dele, que
   > viram **uma** só linha na planilha.
   >
   > *Exemplo hipotético:* se o SEI casar **183 linhas** e elas se
   > distribuírem por **67 processos-pai**, a planilha sai com 67 linhas —
   > média de ~2,7 linhas por processo. A razão **não tem valor fixo**:
   > depende de quantos documentos cada processo tem e do período
   > pesquisado. O que é fixo é a **relação**: o total do SEI é sempre
   > **igual ou maior** que o da planilha, e a diferença é inteiramente
   > explicada pelas linhas repetidas do mesmo processo-pai.
   >
   > Por isso o log reporta as duas grandezas separadamente:
   >
   > ```
   > SEI informou 183 resultado(s) no total; a primeira página trouxe 47 linha(s).
   >   página 1: offset 0, 47 linha(s), processo(s) ... .. ...
   >   página 2: offset 47, 50 linha(s), processo(s) ... .. ... (acumulado 97/183 linha(s))
   >   ...
   > Busca concluída: 5 página(s) lida(s), 67 processo(s) único(s), 183 linha(s) lida(s) de 183 informada(s).
   > ```
   >
   > (O exemplo acima usa os mesmos números do caso real de
   > 01/01/2026 a 31/03/2026; numa execução qualquer os valores mudam.)
   >
   > A contagem de páginas **não é um número fixo**: depende de quantas
   > linhas o SEI devolve em cada requisição. O que precisa fechar é a soma
   > das linhas — por isso o log mostra `offset`, `linha(s)` e `acumulado`
   > em cada página. Se a soma final não bater com `itens`, sobrou buraco.
   >
   > Um processo **nunca** some por isso: ele pode ter sido descoberto por
   > qualquer uma das suas linhas (o próprio processo, um documento gerado
   > ou um recebido) e, uma vez descoberto, a página do processo é
   > consolidada em **uma** linha da planilha.

2. **Paginação**: o módulo devolve até 50 resultados por página
   (`rowsSolr=50`). Páginas seguintes avançam o parâmetro `inicio`; como
   no SEI, cada página pode exigir um novo CAPTCHA.

   **O fim da paginação é decidido por LINHAS, não por processos.** Como os
   três tipos de pesquisa estão marcados, uma página cheia de 50 linhas pode
   conter bem menos processos: documentos do mesmo processo repetem o número
   nas linhas seguintes. Encerrar o laço comparando o total de processos
   **únicos** com o tamanho da página fazia a primeira página parecer a
   última sempre que ela trouxesse menos de 50 processos distintos — o
   coletor parava na primeira página e devolvia um recorte incompleto sem
   nenhum aviso (bug real).

   **O total do SEI é a régua, e ele vem em `data.itens`.** O JS da própria
   página de pesquisa é a autoridade do contrato:

   ```js
   var buscaInicio = 0; var rowsSolr = 50; var qtdeItens = 0;
   qtdeItens = data.itens;
   function verificarRegistros(){
       var totalTela = $('table tbody tr.pesquisaTituloRegistro').length;
       if(totalTela < 10 && buscaInicio < qtdeItens){ carregarProximaPaginaInicial(); }
   }
   ```

   Enquanto `inicio < itens`, há página para buscar. Uma documentação
   anterior afirmava que o JSON **não** trazia total e que o fim era
   "página curta" — conclusão tirada de uma resposta de **CAPTCHA
   rejeitado**, que de fato é só `{"html": ...}` sem `itens`. No sucesso o
   campo existe, e é ele que manda. Sem `itens` (CASO de CAPTCHA
   rejeitado) o laço ainda cai no critério antigo de página cheia.

   **O offset avança pelas linhas lidas, nunca por `page_size`.** Uma
   página pode vir curta — é comum a primeira vir com menos linhas que o
   `rowsSolr` pedido — e somar `50` ao offset pularia para sempre as linhas
   do intervalo entre o fim da página e o salto. No caso real isso dava
   180 linhas lidas contra 183 informadas (bug real, mesma execução de
   01/01/2026 a 31/03/2026). Somando o **tamanho real da página anterior**
   ao offset, nenhum intervalo é pulado e a soma das linhas fecha com o
   total informado. Uma página cheia continua avançando 50, então o caso
   comum não muda.

   Cada execução registra uma linha por página com o `offset` pedido, as
   `linha(s)` recebidas e o `acumulado`, e fecha com
   `Busca concluída: N página(s) lida(s), M processo(s) único(s),
   L linha(s) lida(s) de T informada(s)`. Uma página que volta vazia no
   meio — ou a busca terminando com `inicio < itens` — gera aviso em vez de
   truncar calado.

   **O log é a auditoria, não a decoração.** Como a dedupe apaga a
   distinção entre "processo visto por três linhas" e "processo nunca
   visto", o total de processos é cego a linhas faltantes: duas execuções
   com buracos diferentes podem reportar o mesmo número de processos. Por
   isso a conferência de cobertura é a **soma das linhas lidas contra
   `data.itens`**, e é ela que precisa fechar — não o total de processos.

   **CAPTCHA rejeitado não é "sem resultados".** Quando o OCR erra o código,
   o SEI **não** responde 4xx: responde **HTTP 200** com o HTML de erro
   dentro de `.sem-resultado` (`Código de confirmação inválido 1.`). Como
   esse HTML não tem linhas de processo, o parser devolvia **zero
   resultados** e a planilha saía vazia sem nenhum aviso — bug real que
   zerou a execução de 01/01/2026 a 31/03/2026. Hoje o cliente detecta esse
   HTML (`is_captcha_error`), **resolve um novo CAPTCHA, refaz os critérios
   e repete** a busca (e a paginação) até 3 vezes. Esgotadas as tentativas,
   a execução **falha com erro explícito** em vez de mentir que o período
   não tem processos. Uma busca legitimamente vazia ("Nenhum documento
   localizado.") continua sendo zero, sem retry.

   **A busca só sai com todos os critérios marcados.** Preencher o
   formulário não é o mesmo que tê-lo aplicado: o `#hdnIdUnidade` só recebe
   o id quando uma opção do autocomplete é clicada, e o plugin de órgãos
   pode não aceitar a seleção. Antes, cada falha degradava em silêncio —
   órgão não mapeado virava *todos os órgãos*, unidade não resolvida deixava
   a busca **sem filtro de unidade** (o SEI devolvia o recorte do órgão
   inteiro, que parece um resultado completo e não é). Agora
   `_verify_search_criteria` lê o DOM e **impede a busca** se faltar
   qualquer um destes:
   - os três checkboxes `chkSinProcessos`, `chkSinDocumentosGerados` e
     `chkSinDocumentosRecebidos`;
   - o órgão alvo selecionado em `#selOrgaoPesquisa` (`MMULHERES` → `11`);
   - o id da unidade em `#hdnIdUnidade` **e** o código confere em
     `#txtUnidade`.

   A comparação da unidade é **estrita** (`_unidade_confere`), aceitando o
   formato "código - nome" do SEI
   (`MMULHERES-SE-SGA-CGATI-CTI - Coordenação de Tecnologia da
   Informação` → código `MMULHERES-SE-SGA-CGATI-CTI`). A comparação por
   substring usada no autocomplete aceitaria a unidade legada
   `...-CGATI-CTI-DTI` como se fosse a pedida, e a busca voltaria 0
   processos sem erro. A falha guarda a página em
   `.state/debug/criterios_incompletos.*` e lista o que faltou.

3. **Navegação ao processo** (`sei_client.py`): segue o link público
   `md_pesq_processo_exibir.php` fornecido pelo próprio resultado da
   pesquisa — nenhum link é fabricado. Ao abrir a página, o programa lê o
   cabeçalho (`#tblCabecalho`, linha **`Processo:`**) e usa esse número
   como o **número canônico** do processo — pasta da planilha e da
   `downloads/`. Assim, mesmo quando o processo foi descoberto por uma
   linha de documento (que só tem o número do documento), a linha da
   planilha e a pasta usam o número real do processo.

4. **Árvore de documentos** (`tree.py`): a página pública monta a árvore
   via JavaScript. Para cada documento são lidos a **série documental**
   (ex.: "Despacho"), o **número documental** (5+ dígitos), a **data de
   inclusão** (coluna "Data de Inclusão" da tabela, `dd/mm/aaaa` — a
   hora:minuto da célula é ignorada; fallback: data no rótulo do nó) e a
   **posição** na árvore. O nó é correlacionado à URL pública pelo
   **número documental** (fallback: ordem de renderização).

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
| `src/sei_insights/storage/report.py`     | Geração da planilha XLSX (abas principal e Resumo da última execução). |
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
| `--unidade`          | Unidade geradora na pesquisa (padrão: `MMULHERES-SE-SGA-CGATI-CTI`). |
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
python -m sei_insights --unidade "MMULHERES-SE-SGA-CGATI-CTI" --manual-captcha

# Ritmo mais lento (menos pressão no servidor) + força reanálise
python -m sei_insights --min-delay 3 --max-delay 7 --force

# Planilha em outro caminho
python -m sei_insights --saida relatorios/setembro.xlsx
```

> **CAPTCHA manual:** quando ativo, preencha o CAPTCHA **no navegador**.
> Não pressione ENTER no terminal — o programa continua sozinho assim que
> o campo é preenchido.

### O que o CLI loga

No `INFO` (padrão), o terminal mostra:

- **o período pesquisado** (`Pesquisa de DD/MM/AAAA a DD/MM/AAAA | órgão ... |
  unidade ...: N processo(s) encontrado(s)`) seguido da **listagem dos
  processos encontrados** na busca, com o número e o link;
- **cada processo consultado** ao longo da análise
  (`Consultando processo NNNNN.NNNNNN/AAAA-NN`);
- ao final, **`log_summary`**: a listagem dos processos da planilha
  (`N) número | situação | status`) e as **quantidades** — total, novos e
  a quebra por status de coleta (`concluído`, `concluído (cache)`,
  `erro: ...`) e por situação.

---

## O que é gerado

### Planilha XLSX

Arquivo `sei_insights.xlsx` (ou o caminho de `--saida`) com **duas abas**:

- **Aba principal** — espelho do estado atual: **uma linha por processo**
  com as colunas abaixo;
- **Resumo da última execução** — quando a execução rodou e contagens,
  em blocos: **Data e hora da execução** e **Período pesquisado**
  (início a fim, no formato `DD/MM/AAAA a DD/MM/AAAA`), **Visão geral**
  (`Total de processos`, `Novos`), tabela **Por situação** e tabela
  **Por status** (`Classificação | Quantidade`).

### As colunas da planilha

Cada linha da aba principal corresponde a **um processo**:

| Coluna | Explicação |
| ------ | ---------- |
| `numero` | Número **canônico** do processo (`NNNNN.NNNNNN/AAAA-NN`), lido do cabeçalho da página pública (`Processo:`), normalizado. Mesmo quando a busca descobre o processo via uma linha de documento, aqui vale o número do **processo** — nunca o número do documento. É a chave primária no espelho SQLite. |
| `data_ultimo_despacho` | Data do último Despacho da árvore de documentos, lida da coluna **"Data de Inclusão"** da tabela da página pública (`dd/mm/aaaa`; hora:minuto da célula é ignorado). Vazia quando não há despacho público ou a data não foi exibida. |
| `situacao` | Situação classificada pelo motor de regras a partir do texto do último Despacho (ex.: "Aguardando providências de X", "Em CGATI"). Valores especiais: `Sem despacho público`, `Texto não extraível (digitalizado?)`, fallback `Em análise` e `Erro / retry`. |
| `destino` | **Destinatário citado no cabeçalho do despacho** (`Ao/Aos/À/Às <nome>`, ignorando cópia `C/c:` e cortando em `Assunto:`/`Referência:`), ou no campo `Destino:` quando presente. Mantido **por extenso e exato** (sem o `Ao/Aos/À/Às`); vira **sigla** quando o **nome inteiro** equivaler a uma chave do mapa `siglas` do `regras.json` (normalização de acentos/hífens), quando citado como `(SIGLA)`/após travessão, ou quando vem com o código de memória do SEI no fim (`... - CGTI/MMULHERES` → `CGTI`) — ex.: `SE`, `CGATI`, `COSIS`, `SGA`, `CGTI` vs `Gabinete da Ministra`. Vários destinatários ficam na mesma célula separados por `"; "`, com a sigla reduzida um a um (ex.: `CPSG; CCL`). Sem cabeçalho de destinatário, é preenchido pela regra do corpo. Vazio quando não envolve destinatário. |
| `acao_esperada` | Ação pedida pelo despacho (análise, assinatura, retorno, providências, ciência...). Vazia quando não se aplica. |
| `pendencia_curta` | Resumo de uma linha: **quem está com o processo** e **o que falta**. Vazia quando não há pendência identificada. |
| `status_coleta` | Como a linha foi produzida: `concluído` (analisado nesta execução, com download quando aplicável), `concluído (cache)` (reaproveitada da execução anterior porque o hash não mudou) ou `erro: <mensagem>` (falha isolada, não interrompe os demais). |
| `hash_ultimo_despacho` | SHA-256 do identificador `número\|data` do último Despacho. Base do cache: inalterado → análise preservada; mudou → reanálise e novo download. É hash do **identificador**, não do texto do PDF (intencional). |
| `link_process` | URL pública do processo (`md_pesq_processo_exibir.php?TOKEN`) — **última coluna**. É a **identidade estável** do processo entre execuções: usada na dedupe da descoberta e como chave alternativa do cache. |

> **Como `situacao`, `destino`, `acao_esperada` e `pendencia_curta` são
> preenchidas?** Elas são **inferidas do texto do último Despacho** — não são
> cadastradas à mão nem geradas por adivinhação. A seção
> [De onde vem cada campo (nada é inventado)](#de-onde-vem-cada-campo-nada-e-inventado)
> mostra, campo a campo, a fonte literal de cada valor, exemplos
> reais rastreados e o que acontece quando a coluna fica vazia.

> **Todos os valores das abas são gravados como Texto** (formato `@`).
> Assim o Excel não tenta interpretar `numero`
> (`21260.002715/2026-53` tem `.`, `/`, `-`), hashes ou links como número,
> evitando triângulos de erro e conversões indesejadas. As quantidades do
> Resumo da última execução restam números reais.

> **Onde ficou `data_execucao`?** Ela não se repete mais em cada linha da
> planilha (redundante): a data/hora da execução fica **uma única vez** na
> aba **Resumo da última execução** (campo **Data e hora da execução**).
> No espelho SQLite (`.state/sei_insights.sqlite3`) a coluna
> `data_execucao` **continua em cada linha** — nada mudou no banco.

A planilha é **substituída a cada execução** (espelho do momento). Um
resultado vazio (0 processos) é válido: a planilha é gerada com a aba
principal vazia e o Resumo zerado, sem erro.

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

1. o texto é separado em **cabeçalho** e **corpo**. O cabeçalho é o bloco
   inicial do documento (órgão, `DESPACHO`, `Processo nº`, destinatário);
   o corpo é o que sobra. Só o **corpo** alimenta as regras de
   situação/ação — três blocos são descartados do texto antes de casar
   regras:
   - o **timbrado** inicial (linhas de órgão/unidade), sem limite de
     tamanho: o timbrado do MGI tem seis linhas e, colado no `DESPACHO`
     sem linha em branco, era lido como corpo — daí o falso
     `Em Secretaria` no processo `14021.109425/2025-14`;
   - o **bloco de assinatura** (do `assinado digitalmente` em diante):
     nome, cargo e unidade da signatária nunca são destinatário — sem esse
     corte, o `Termo de Encerramento` do processo `21260.001106/2026-87`
     virava `Em Assessoria` (nome do cargo da signatária);
   - as linhas de metadados (`Assunto:`, `C/c:`, `Processo nº`,
     `Documento assinado...`, `A autenticidade...`);
2. do cabeçalho é lido o **destinatário**, na seguinte precedência:
   1. o campo **`Destino:`** que alguns despachos trazem impresso
      (`Destino: Assessoria Especial de Comunicação Social - ASCOM`) —
      o processo `21260.000680/2025-37` é endereçado só por ele;
   2. as linhas **`À/Ao/Aos/Às <nome>`** do cabeçalho, ignorando cópia
      `C/c:` e cortando em `Assunto:`/`C/c`/`Referência:`/`Processo nº`.
      Um despacho pode endereçar **mais de uma unidade**: cada linha vira um
      destinatário, e eles ficam na mesma célula separados por `"; "` (sem
      `À` nem `Assunto` no meio). A redução de sigla é feita **por
      destinatário** — no processo `21260.001018/2026-85` são duas
      unidades, `CPSG` e `CCL`, e as duas aparecem;
   3. sem os dois, não há destinatário no cabeçalho (o timbrado é
      descartado). Cada nome é mantido **por extenso e exato** (sem o
      `Aos/Ao/Às/À`); vira **sigla** quando o **nome inteiro** for igual
      a uma chave do mapa `siglas` do `regras.json` (comparação normalizada,
      ignorando acentos e hífens), quando a sigla aparece entre parênteses
      (`(CGATI)`) ou após travessão (`– COSIS`), ou quando o nome por
      extenso vem com o código de memória do SEI no fim
      (`Coordenação-Geral de Tecnologia da Informação - CGTI/MMULHERES`,
      processo `21260.001552/2026-91` → `CGTI`). É **o nome exato** que
      vale: `Gabinete da Secretaria-Executiva` continua por extenso (não
      vira `SE`). Sem destinatário, `destino` vem da regra do corpo;
3. o corpo normalizado (múltiplos espaços/quebras viram um único espaço) é
   testado contra as regras **na ordem do arquivo**, com a primeira
   correspondência vencendo (`re.search(..., re.IGNORECASE)`, caixa
   indiferente);
4. a regra vencedora preenche os quatro campos de saída; `situacao`,
   `acao_esperada` e `pendencia_curta` podem usar **backreferences**
   (`\1`, `\2`...) expandidas pelos grupos capturados do padrão, e o
   **placeholder `{destino}`** (ver [abaixo](#o-placeholder-destino));
5. o `destino` do **cabeçalho** (passo 2) **sobrepõe** o da regra quando
   existe; mesmo sem regra casando, o destinatário preenche `destino` no
   **fallback**;
6. se **nenhuma** regra casar, vale o **fallback** (padrão: situação
   `"Em análise"`).

Cada regra tem a forma:

```json
{
  "pattern": "regex de busca (sem delimitadores)",
  "situacao": "Situação resultante (pode usar \\1 ou {destino})",
  "destino": "Destino extraído (pode usar \\1)",
  "acao_esperada": "Ação pedida (pode usar \\1 ou {destino})",
  "pendencia_curta": "Resumo da pendência (pode usar \\1 ou {destino})"
}
```

### O placeholder `{destino}`

A maior parte das regras descreve a situação pela **ação** pedida
(`Encaminhado a conhecimento e deliberação`). A regra de unidade interna
não pode: o corpo só diz *"retorno a esta Coordenação"*, e escrever
`"situacao": "Em \\1"` produzia `Em Coordenação` — genérico, sem dizer de
quem é o trabalho, em 7 dos 37 despachos medidos. A regra usa então o
placeholder **`{destino}`**, que o motor expande com o **destinatário já
resolvido** (portanto o do cabeçalho quando existe):

```json
{
  "pattern": "\\b(SGA|CCL|CTI|SCL|SG|COORDENA[ÇC][ÃA]O|DIRETORIA|SECRETARIA|SUPERINTEND[ÊE]NCIA|GER[ÊE]NCIA|ASSESSORIA|N[ÚU]CLEO|DIVIS[ÃA]O|DEPARTAMENTO)\\b",
  "situacao": "Em {destino}",
  "destino": "\\1",
  "acao_esperada": "análise",
  "pendencia_curta": "Processo com {destino} para análise/próximo passo"
}
```

Três garantias:

- **o texto é literal** — a substituição é `str.replace`, não regex: um
  `\1` que faça parte do nome do destinatário é copiado, nunca consumido
  como backreference;
- **`{destino}` nunca fica exposto** — sem destinatário, expande para
  `(destino não identificado)`, para não gerar a frase quebrada `Em `;
- **só substitui depois** das backreferences, ou seja, `{destino}` sempre
  recebe o destino **efetivo** (cabeçalho > captura do corpo).

Quando não existe linha de destinatário **e** o corpo nomeia só o
substantivo, o destino efetivo é esse substantivo e a situação repete o
que o texto diz (`Em Coordenação`) — sem inventar sigla nenhuma.


### De onde vem cada campo (nada é inventado)

Os quatro campos interpretados — `situacao`, `destino`, `acao_esperada` e
`pendencia_curta` — **não são adivinhados**. Não há modelo de linguagem,
IA ou "boa sensedoria" no caminho: o motor é uma lista ordenada de
expressões regulares mais texto escrito à mão. **Nada que não esteja no
texto do despacho (nem no `regras.json`) entra na planilha.**

Cada valor gravado vem de uma destas três fontes, todas **literais**:

| # | Fonte | O que é |
| --- | ----- | ------- |
| 1 | **Cabeçalho do despacho** | o destinatário impresso no cabeçalho: o campo `Destino:` ou a linha `À/Ao/Aos/Às <nome>`, exatamente como está no documento |
| 2 | **Trecho capturado do corpo** | a(s) palavra(s) que o `pattern` da regra casou, devolvidas por `\1`, `\2`... |
| 3 | **Texto fixo da regra** | frase escrita à mão em `regras.json` para aquela situação (ex.: `"situacao": "Pendente de assinatura"`), com `{destino}` expanding para o destinatário resolvido |

Não havendo nenhuma dessas três fontes, a célula fica **vazia**. Célula
vazia significa "o despacho não diz isso" — nunca "preenchemos com uma
hipótese". O único preenchimento automático é o **fallback**
`situacao = "Em análise"`, que também é uma informação honesta: o texto
foi lido, mas nenhuma regra reconhecida casou.

| Campo | Fonte | Quando fica vazio |
| ----- | ----- | ----------------- |
| `situacao` | texto fixo (3) e/ou `\1`/`\2` (2) da regra vencedora | nunca: sem regra casando entra o fallback `Em análise` |
| `destino` | cabeçalho (1); **sem** ele, `\1`/`\2` do corpo (2) | despacho sem destinatário **e** sem regra que capture um |
| `acao_esperada` | texto fixo (3) e/ou `\1`/`\2` (2) | a regra descreve a situação mas não a ação (ex.: as de arquivamento e de decisão) |
| `pendencia_curta` | texto fixo (3) e/ou `\1`/`\2` (2) | idem |

Quando cabeçalho e regra produzem `destino`, **vale o do cabeçalho**
(passo 5 de [Como o motor decide](#como-o-motor-decide)) — o endereço que
o despacho imprime é mais confiável do que o nome citado em uma menção
dentro do corpo. O mesmo vale para `{destino}`: ele recebe o destino
**efetivo**, já com essa precedência aplicada.

Para deixar isso concreto, sete exemplos rastreados. Cinco são despachos
reais — os mesmos textos de `tests/test_rules.py`, portanto reproduzíveis
(`python -m unittest tests.test_rules`); os outros dois são casos de
formato:


**1. `21260.003611/2026-66` — destino pelo cabeçalho, ação pelo corpo**

Trechos lidos do PDF público:

> `À Coordenação-Geral de Administração e Tecnologia da Informação`
> ... *"encaminham-se os autos à Coordenação-Geral de Administração e
> Tecnologia da Informação (CGATI), para conhecimento e deliberação quanto
> ao quantitativo de equipamentos..."*

| `destino` | `situacao` | `acao_esperada` | `pendencia_curta` |
| --------- | ---------- | --------------- | ----------------- |
| `CGATI` | `Encaminhado a conhecimento e deliberação` | `conhecimento e deliberação` | `Aguardando conhecimento e deliberação do destinatário` |

O cabeçalho diz *"Coordenação-Geral de Administração e Tecnologia da
Informação"*; esse nome inteiro é chave do mapa `siglas`, então a sigla
`CGATI` foi gravada. `conhecimento e deliberação` saiu literalmente do
corpo, por `\1` da regra que casou — não foi redigido.

**2. `21260.002715/2026-53` — sigla que já vem no próprio despacho**

> `À Coordenação de Sistemas e Soluções de Tecnologia da Informação – COSIS`
> ... *"encaminho o presente processo para análise e providências quanto à
> solicitação de disponibilização dos dados..."*

| `destino` | `situacao` | `acao_esperada` | `pendencia_curta` |
| --------- | ---------- | --------------- | ----------------- |
| `COSIS` | `Encaminhado a análise e providências` | `análise e providências` | `Aguardando análise e providências do destinatário` |

`COSIS` não foi adivinhado: o próprio despacho escreve o nome por extenso
seguido do travessão e da sigla. A regra que casou aqui define situação e
ação, mas **não** define `destino` — quem preencheu `destino` foi o
cabeçalho.

**3. Despacho sem linha de destinatário — destino pelo corpo**

Formato `Diante do exposto, encaminham-se os autos à <unidade>, para
<ação>.` (sem bloco `À/Ao/Aos/Às` no cabeçalho):

| `destino` | `situacao` | `acao_esperada` | `pendencia_curta` |
| --------- | ---------- | --------------- | ----------------- |
| `Secretaria de Enfrentamento a Violência contra Mulheres` | `Encaminhado a Secretaria de Enfrentamento a Violência contra Mulheres` | `análise e providências` | `Processo encaminhado para análise/providências` |

Sem cabeçalho, o nome vem do grupo capturado pelo `pattern`. Repare que
ficou **por extenso e exato**, sem virar sigla: só encolhe quando o nome
inteiro casa com o mapa `siglas`.

**4. `14021.072944/2026-92` — nenhuma regra casou (fallback)**

> `À Secretaria-Executiva`
> `Assunto: Regulamentação do Protocolo Não é Não...`
> ... *"Encaminho o presente processo para análise e providências."*

| `destino` | `situacao` | `acao_esperada` | `pendencia_curta` |
| --------- | ---------- | --------------- | ----------------- |
| `SE` | `Em análise` | *(vazia)* | *(vazia)* |

Este é o caso honesto: o texto **não** casou com nenhum padrão
reconhecido, então a situação é `Em análise` e as duas colunas de ação
ficam **vazias** — em vez de o programa inventar "Aguardando análise".
O `destino` (`SE`) ainda é aproveitado porque o cabeçalho cita
`Secretaria-Executiva`, que é chave do mapa `siglas`.

Repare no contrato: `Em análise` **não** vira `Em SE`. O fallback continua
marcando "nenhuma regra casou, precisa de leitura humana", e o
destinatário já está na coluna `destino` ao lado.

**5. `21260.000680/2025-37` — destino pelo campo `Destino:`**

> `Destino:` / `Assessoria Especial de Comunicação Social - ASCOM`
> `Assunto` / `Publicação de currículos - Seção "Quem é Quem"...`
> ... *"Em atenção às diretrizes de transparência ativa e ao prazo
> estabelecido pelo Ministério da Gestão e da Inovação, informamos que já
> foram recebidos e anexados a este processo parte dos currículos..."*

| `destino` | `situacao` | `acao_esperada` | `pendencia_curta` |
| --------- | ---------- | --------------- | ----------------- |
| `ASCOM` | `Em análise` | *(vazia)* | *(vazia)* |

Este despacho **não** tem linha `À/Ao/Aos/Às`: o destinatário está no
campo `Destino:`, que o SEI imprime quando o processo sai por outra via.
Antes da mudança, o timbrado (`Subsecretaria de Gestão e Administração`)
ia para o corpo e o destino saía `Secretaria` — a Assessoria de
Comunicação nunca era identificada. `ASCOM` não foi adivinhado: o
próprio despacho escreve o nome por extenso seguido do travessão e da
sigla.

**6. `21260.001144/2026-30` — situação citando o destinatário (`{destino}`)**

> `À Coordenação-Geral de Administração e Tecnologia da Informação`
> ... *"Retorno a esta Coordenação para análise e continuidade do processo."*

| `destino` | `situacao` | `acao_esperada` | `pendencia_curta` |
| --------- | ---------- | --------------- | ----------------- |
| `CGATI` | `Em CGATI` | `análise` | `Processo com CGATI para análise/próximo passo` |

A regra interna de unidade casou o substantivo `COORDENAÇÃO` no corpo, mas
a situação saiu `Em CGATI`, não `Em Coordenação`: o `{destino}` expandiu
com o nome inteiro do cabeçalho, reduzido a sigla pelo mapa. `CGATI` está
no documento.

**7. `21260.001106/2026-87` — encerramento acima do cargo da signatária**

> `Termo de Encerramento de Processo`
> ... *"Considerando que este processo cumpriu seu objetivo, procedo ao seu
> encerramento."*
> `assinado digitalmente` / `ANA CAROLINA SANTANA MOREIRA` / `Assessora
> Técnica` / `Assessoria Especial de Controle Interno - AECI`

| `destino` | `situacao` | `acao_esperada` | `pendencia_curta` |
| --------- | ---------- | --------------- | ----------------- |
| *(vazia)* | `Encerrado` | `nenhuma (processo encerrado)` | `Processo encerrado, sem ação pendente` |

Sem destino porque o despacho encerra o processo e não encaminha nada.
Antes, o bloco de assinatura entrava no corpo, a regra de unidade interna
via `ASSESSORIA` e a linha virava `Em Assessoria` — pendência que não
existe. A regra de encerramento vem **antes** da regra de unidade interna
pelo mesmo motivo.

#### Quando não há texto para interpretar

Nem toda linha é fruto de uma regra: algumas refletem o próprio estado da
coleta. Nesses casos os campos de interpretação ficam vazios **de
propósito** — são literalmente "não foi possível ler", e não "não
aplicável".

| `situacao` | Origem | Campos de interpretação |
| ---------- | ------ | ----------------------- |
| `Sem despacho público` | a árvore pública não tem nenhum nó da série "Despacho" (ou o despacho não pôde ser baixado) | todos vazios |
| `Texto não extraível (digitalizado?)` | o PDF foi baixado, mas o `pypdf` não extraiu texto (documento digitalizado) — **não existe texto para casar regra** | todos vazios |
| `Erro / retry` | a coleta do processo falhou; o motivo está em `status_coleta` | todos vazios |
| `Em análise` | texto lido, nenhuma regra casou | só `destino`, se o cabeçalho citar destinatário |
| (`status_coleta = concluído (cache)`) | o último Despacho não mudou desde a execução anterior: os campos foram **copiados** da análise de antes | preservados |

#### Como auditar uma linha da planilha

Nenhum passo da classificação é opaco. Para conferir qualquer linha:

1. abra a coluna `link_process` no navegador — é a página pública real do
   processo no SEI;
2. abra a árvore de documentos e baixe o **último Despacho** (mesmo critério
   do programa: série "Despacho", maior data);
3. compare o texto com `regras.json`, **na ordem do arquivo** — a primeira
   regra que casar é a vencedora (as anteriores têm precedência);
4. se a classificação estiver errada, a correção é **no `regras.json`**
   (ajustar ou inserir um padrão), e a próxima execução com `--force`
   reprocessa. A planilha **não** se edita à mão: ela é regenerada e
   sobrescrita a cada execução.

Nenhuma fonte externa ao despacho participa do resultado: não há consulta
a sistema interno, não há plano de trabalho, não há previsão de prazo.
O que não está no texto (nem no `regras.json`) não aparece na planilha.

### Regras específicas da unidade

As **5 primeiras** regras são as mais específicas e remetem diretamente à
unidade utilizada, `MMULHERES-SE-SGA-CGATI-CTI`. Os despachos podem citar a
unidade em qualquer das duas formas, então os padrões cobrem ambas:

- **Com sufixo `-DTI`** (nome legado, ainda citado em despachos antigos):
  `MMULHERES-SE-SGA-CGATI-CTI-DTI`;
- **Sem sufixo** (unidade padrão atual): `MMULHERES-SE-SGA-CGATI-CTI(?!-DTI)`
  — o **lookahead negativo** `(?!-DTI)` evita que a forma sem sufixo case
  "por dentro" da forma com sufixo (senão ela casaria também em
  `...CTI-DTI` e a regra da unidade atual nunca seria a escolha correta).

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
| 8 | "encaminha-se/remete-se (os autos) a **<alvo>**, para **<ação>**" (fecho do despacho; ex.: "... à CGATI, para conhecimento e deliberação") | `Encaminhado a <ação>` |
| 9 | "encaminho o presente processo para <ação> quanto à ..." | `Encaminhado a <ação>` |
| 10 | "encaminho/remeto **para <ação>**" sem citar os autos nem a unidade (ex.: "Encaminho para conhecimento e providências o DFD") | `Encaminhado a <ação>` |
| 11 | "encaminha-se/remete-se (os autos) a/para <destino>" | `Encaminhado a <destino>` |
| 12 | "para/com vistas a (ação) de <destino>" | `Aguardando <ação> de <destino>` |
| 13–14 | "determino/determina-se o arquivamento", "arquive-se", "pelo arquivamento" | `Arquivado` |
| 15 | "devolva-se/devolvam-se/devolução dos autos" | `Devolvido` |
| 16 | "converta-se/transforme-se/conversão em (ofício\|nota técnica\|memorial\|termo)" | `Em conversão/transformação` |
| 17 | "dê-se ciência/cientifique-se/para ciência de <destino>" | `Para ciência de <destino>` |
| 18 | "adote-se/providencie-se/tomar providências (por) <destino>" | `Aguardando providências de <destino>` |
| 19 | "no prazo de/em até/prazo de **N** (dias\|horas\|meses)" | `Com prazo (N dias)` |
| 20 | "\b(defiro\|indefiro\|parcialmente procedente\|improcedente\|procedente)\b" | `Decisão: <termo>` |
| 21 | "cumpra-se/para cumprimento/determino cumprimento" | `Para cumprimento` |
| 22 | "sugere-se ... seja retomada/retomado ... planejamento" (despacho que propõe retomar em ocasião futura, ex.: resposta a apoio orçamentário) | `Aguardando retomada (avaliação futura)` |
| 23 | "termo de encerramento", "cumprriu seu objetivo", "procedo ao seu encerramento" | `Encerrado` |
| 24 | menção a unidade interna (`SGA`, `CCL`, `CTI`, `SCL`, `SG`, `COORDENAÇÃO`, `DIRETORIA`, `SECRETARIA`, `GERÊNCIA`, `NÚCLEO`, `DEPARTAMENTO`...) | `Em {destino}` |
| 25 | órgão externo (`Ministério Público`, `Tribunal de Contas`, `Controladoria`, `Polícia Federal`, `Receita Federal`, `INSS`, `AGU`, `PGFN`, `MPF`, `TCU`, `CGU`...) | `Encaminhado a órgão externo (<órgão>)` |

Duas regras existem por ordem, não por assunto:

- a **23 (encerramento)** vem **antes** da 24 (unidade interna) porque o
  bloco de assinatura de um termo de encerramento carrega o cargo e a
  unidade da signatária (`Assessora Técnica` / `Assessoria Especial de
  Controle Interno`), que casariam a 24 e produziriam uma pendência
  inexistente (`Em Assessoria`);
- a **24** é a única que usa `{destino}`: quando existe linha de
  destinatário, a situação passa a citar a **unidade** (`Em CGATI`) em vez
  do substantivo genérico capturado no corpo (`Em Coordenação`). Sem linha
  de destinatário, ela repete o que o texto diz.

O vocabulário de ações dos padrões 8–12 e 16–18 é o que decide se um
despacho vira `Encaminhado a <ação>` ou cai no fallback `Em análise`.
Ações como `apreciação`, `publicação`, `pronunciamento`, `conhecimento`,
`deliberação` e `validação` estão na lista justamente porque aparecem em
despachos reais; acrescentar uma ação é **editar o `pattern`**, nunca a
planilha.


> **Ordem importa.** Por serem avaliadas na ordem do arquivo, regras mais
> específicas devem vir primeiro. Uma regra genérica que casa quase tudo
> (ex.: a de órgão externo) fica no fim, para não "roubar" casos que as
> regras anteriores já teriam classificado melhor. As regras 8 e 9
> (fecho com `para <ação>`) vêm antes da regra 10 genérica e lidam
> também com quebra de linha na extração do PDF (`en\ncaminho` → `en caminho`).
>
> **Ajuste de padrões:** por serem expressões regulares, adicionar/editar
> uma regra exige cuidado com escapes no JSON. Uma backreference no JSON
> é escrita como `\\1` (dois caracteres: `\` e `1`), que o `json.load`
> converte para `\1` antes de chegar ao motor.

### O fallback "Em análise"

Se nenhuma regra casar — texto irrelevante, conteúdo digitalizado sem
texto útil, formato inesperado — a situação padrão é **"Em análise"**.
O `destino` ainda é preenchido quando o cabeçalho cita o destinatário
(linha `À/Ao/Aos/Às <nome>` ou campo `Destino:`). Isso impede que um
despacho desconhecido "trave" o restante da execução: a linha é gravada
na planilha mesmo assim.

O fallback **não** vira `Em <destino>` mesmo havendo destinatário: é
justamente o marcador de "nenhuma regra casou, precisa de leitura humana",
e apagá-lo esconderia essa pendência. O destinatário continua visível na
coluna `destino`, ao lado.

---

## Cache: por que um despacho novo é reanalisado

Para não repetir download/análise de tudo a cada execução, o programa
guarda o **identificador do último Despacho** (número documental + data) e
grava o **hash SHA-256** dele na coluna `hash_ultimo_despacho`.

No início de cada execução, o espelho anterior (SQLite) é lido. Para cada
processo:

- **sem cache ou com `--force`** → analisa do zero;
- **com cache e hash inalterado** → usa os dados da análise anterior
  (situação, destino, ação esperada, pendência e data do despacho
  preservados), marcando `status_coleta` como `concluído (cache)`. A
  linha continua sendo gravada na planilha;
- **com cache e hash mudou** (novo Despacho no SEI) → **reanalisa**
  o processo com a análise nova;
- **falha ao analisar** → gera linha `Erro / retry` com `status_coleta`
  = `erro: <mensagem>`, sem interromper os demais processos.

A linha do espelho anterior é localizada primeiro pelo **número** e, se
não houver correspondência, pela **URL** (`link_process`). Isso importa
porque a descoberta pode usar números diferentes entre execuções (nº de
documento num dia, nº de documento de outro documento no dia seguinte),
mas a URL da página do processo é estável. Um processo é considerado
**"novo"** apenas quando **nunca** foi visto antes — não casa nem por
número nem por URL.

O hash é calculado sobre o **identificador do Despacho**, **não** sobre o
texto extraído. Isso é intencional: um PDF digitalizado (sem camada de
texto) não "congela" o processo — se o Despacho mudar, o identificador
muda e o processo é rebaixado e reanalisado na próxima execução.

> **Cache não verifica o arquivo em disco.** Quando o hash não muda, a
> análise anterior é reaproveitada **sem conferir se o PDF ainda existe**
> em `downloads/`. Se os arquivos forem apagados manualmente (ex.: para
> limpar os duplicados antigos), a próxima execução continuará marcando o
> processo como `concluído (cache)` e não baixará de novo. Para forçar o
> download, rode `python -m sei_insights --force` (ou limpe o histórico,
> veja [Como limpar os dados](#como-limpar-os-dados-ou-reprocessar)).

> **Nota sobre a janela:** o espelho guarda apenas a última execução.
> Alternar a janela entre execuções (ex.: `--dias 7` ↔ `--dias 30`) pode
> sinalizar como "novos" processos já vistos antes — o efeito fica
> registrado na aba Resumo da última execução (bloco **Visão geral**).

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

**Rodei e nada foi baixado — só "concluído (cache)"**
Normal. Quando o último Despacho não mudou desde a execução anterior
(mesmo `hash_ultimo_despacho`), o programa reaproveita a análise e **não
rebaixa o PDF** — é o comportamento do cache. Atenção: o cache **não**
confere se o PDF ainda existe em `downloads/`. Se você apagou os arquivos
à mão, use `python -m sei_insights --force` para baixar de novo.

**O processo apareceu com número `NNNNN.NNNNNN/AAAA-NN` que não era o que
eu vi na busca**
A busca devolve linhas de **documentos** (porque os "tipos de pesquisa"
também estão marcados) e uma linha de documento só mostra o número do
**documento**. O programa deduplica pela URL do processo e, ao abrir a
página, usa o número canônico do cabeçalho (`Processo:`). Ou seja, o
número da planilha é sempre o do **processo**, não o do documento.

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