# Como funciona

O **SEI Insights** acompanha os processos **públicos** de uma unidade do
SEI/ColaboraGov e devolve uma planilha com o estado de cada processo. Ele usa
apenas os links públicos do SEI, seguindo o mesmo fluxo de um usuário humano:
**não** burla CAPTCHA, **não** acessa documentos restritos e **não** contorna
bloqueios.

## Fluxo de execução

```
busca por unidade + período (+ 3 tipos de pesquisa marcados)
  → linhas de resultado (processos E documentos — 1 linha por item)
  → dedupe pela URL do processo → 1 resultado por processo
  → número canônico do processo (cabeçalho "Processo:" da página pública)
  → diff com o espelho anterior (SQLite) → "novos"
  → para cada processo:
        página pública → árvore de documentos → último Despacho
        → download do documento público → extração de texto (pypdf)
        → motor de regras (regras.json) → linha da planilha
  → grava a planilha XLSX (aba principal + Resumo da última execução)
  → reconstrói o SQLite como espelho exato da planilha
```

## 1. Descoberta e dedupe

A pesquisa pública é preenchida com Órgão, Unidade, período e os três "Pesquisar
em" (Processos, Documentos Gerados, Documentos Externos). Como os três tipos
estão marcados, o SEI devolve **uma linha por item** que casar: processos **e**
documentos. Uma linha de documento aponta para o **processo-pai**, então o mesmo
processo pode aparecer várias vezes.

A **dedupe é feita pela URL do processo**, não pelo número: todas as linhas que
apontam para a mesma página colapsam em um único resultado. Sem isso, um processo
descoberto por N documentos era visitado e baixado N vezes.

> **Por que o total do SEI é maior que o número de linhas da planilha?**
> São grandezas diferentes, e a diferença não é perda de coleta. O total
> (`data.itens`) conta **linhas/itens**; a planilha tem **uma linha por processo
> único**, depois da dedupe. Vários itens podem pertencer ao mesmo processo-pai.
> O total do SEI é sempre **≥** o da planilha, e a diferença é explicada pelas
> linhas repetidas. Um processo nunca some por isso: basta ser descoberto por
> qualquer uma das suas linhas.

## 2. Paginação

Cada página traz até 50 resultados (`rowsSolr=50`); páginas seguintes avançam o
parâmetro `inicio`, e cada página pode exigir um novo CAPTCHA.

- **O fim é decidido por LINHAS, não por processos.** O total do SEI vem em
  `data.itens` e é a régua: enquanto `inicio < itens`, há página a buscar.
  Comparar o total de processos **únicos** com o tamanho da página fazia a
  primeira página parecer a última (bug real). Sem `itens` (CAPTCHA rejeitado),
  cai no critério antigo de página cheia.
- **O offset avança pelas linhas lidas, nunca por `page_size`.** Uma página pode
  vir curta; somar `50` pularia linhas e a soma não fecharia com `itens`. Somar o
  tamanho real da página anterior resolve; uma página cheia continua avançando 50.

Cada página é registrada no log com `offset`, `linha(s)` e `acumulado`, e a busca
fecha com `Busca concluída: N página(s) lida(s), M processo(s) único(s), L linha(s)
lida(s) de T informada(s)`. Como a dedupe apaga a distinção entre "processo visto
por três linhas" e "processo nunca visto", a conferência de cobertura é a **soma
das linhas lidas contra `data.itens`** — não o total de processos.

- **CAPTCHA rejeitado não é "sem resultados".** O SEI responde **HTTP 200** com
  o HTML de erro em `.sem-resultado` (`Código de confirmação inválido`). O cliente
  detecta isso (`is_captcha_error`), resolve um novo CAPTCHA, refaz os critérios e
  repete até 3 vezes; esgotadas as tentativas, a execução **falha com erro explícito**
  em vez de mentir que o período não tem processos. Uma busca legitimamente vazia
  continua sendo zero, sem retry.
- **A busca só sai com todos os critérios marcados.** `_verify_search_criteria`
  lê o DOM e impede a busca se faltar: os três checkboxes
  (`chkSinProcessos`, `chkSinDocumentosGerados`, `chkSinDocumentosRecebidos`), o
  órgão alvo em `#selOrgaoPesquisa`, e o id da unidade em `#hdnIdUnidade` com o
  código conferindo em `#txtUnidade`. A comparação da unidade é **estrita**
  (aceita o formato "código - nome"), para não aceitar a unidade legada
  `...-CGATI-CTI-DTI` como se fosse a pedida. Em falha, a página é salva em
  `.state/debug/criterios_incompletos.*`.

## 3. Número canônico do processo

Ao abrir a página pública, o programa lê o cabeçalho (`#tblCabecalho`, linha
`Processo:`) e usa esse número como o **canônico**. Assim, mesmo quando o processo
foi descoberto por uma linha de documento (que só tem o número do documento), a
linha da planilha e a pasta em `downloads/` usam o número real do processo.
Nenhum link é fabricado: navega-se pelo link público fornecido pelo resultado.

## 4. Árvore de documentos

A árvore é montada por JavaScript na página pública. Para cada documento, o
parser (`tree.py`) lê:

- a **série documental** (ex.: "Despacho") e o **título completo** do rótulo;
- o **número documental** (5+ dígitos);
- a **data de inclusão** (coluna "Data de Inclusão", `dd/mm/aaaa`; fallback: data
  no rótulo);
- a **posição** na árvore.

O nó é correlacionado à URL pública pelo **número documental** (fallback: ordem
de renderização).

## 5. Último Despacho

Entre os nós da série "Despacho", escolhe o de **maior data** (desempate: maior
posição na árvore). A comparação é **cronológica**, não textual: `dd/mm/aaaa`
ordena errado como texto (`30/06` > `05/07`), e isso trocaria o andamento atual
por um antigo na virada de dezena. Despacho sem data é descartado quando existe
algum datado (com aviso no log); sem nenhuma data, usa-se a posição.

Se o Despacho mais recente **não tiver download público** (restrito), tenta os
Despachos anteriores, do mais recente ao mais antigo, até um público. A data
gravada é a do Despacho **realmente lido**, e um aviso nomeia o restrito e o
lido.

## 6. Processo encerrado

Se o **último documento** da árvore for um **Termo de Encerramento de Processo
Eletrônico**, o processo está encerrado: o programa **não baixa nem classifica
Despacho** e grava a situação `Encerrado (verificar manualmente)`. A precaução
existe porque o script não pode afirmar sozinho que o processo não andou mais. Um
Termo que **não** seja o último documento não dispara a detecção — o processo
seguiu em andamento.

## 7. Download e texto

É baixado **somente** o documento do último Despacho, usando a sessão/cookies do
navegador, com pausas, retry e verificação de SHA-256. O texto é extraído com
`pypdf`; se o PDF não tiver camada de texto (digitalizado), a situação é
`Texto não extraível (digitalizado?)` — sem OCR nesta versão.

## 8. Classificação

O texto é normalizado e testado contra a lista ordenada de regras de
`regras.json`. A primeira que casar vence e produz `situacao`, `destino`,
`acao_esperada` e `pendencia_curta`. Nenhuma casando: com um cabeçalho de sigla
limpa a situação vira `Em <destino>`; caso contrário, vale o fallback
(`Verificar manualmente`). Os detalhes estão em
[Regras e classificação](regras.md).

## 9. Persistência

Gera a planilha XLSX (`report.py`) e reconstrói o SQLite **por inteiro**
(`mirror.py`), como espelho exato das linhas da planilha. A planilha é a fonte
da verdade. Veja [Operação](operacao.md).

## Ritmo e resiliência

A execução é **sequencial** (por propósito), com pausas aleatórias entre
requisições (padrão de 2 a 5 segundos) e tratamento de 429 (`Retry-After`), 5xx
e erros de conexão com backoff — comportamento copiado do coletor de origem.
