# Regras e classificação

O motor (`rules.py`) lê `regras.json` — uma **lista ordenada** de regras. A
classificação é 100% determinística: expressões regulares mais texto escrito à
mão. **Nada que não esteja no texto do despacho (nem no `regras.json`) entra na
planilha.** Não há IA, modelo de linguagem nem consulta a sistema externo.

## Como o motor decide

1. O texto é separado em **cabeçalho** e **corpo**. Só o **corpo** alimenta as
   regras de situação/ação. Antes de casar, três blocos são descartados:
   - o **timbrado** inicial (linhas de órgão/unidade), sem limite de tamanho;
   - o **bloco de assinatura** (de `assinado digitalmente` em diante): nome,
     cargo e unidade da signatária nunca são destinatário;
   - as linhas de metadados (`Assunto:`, `C/c:`, `Processo nº`,
     `Documento assinado...`, `A autenticidade...`).
2. Do cabeçalho é lido o **destinatário**, nesta precedência:
   1. o campo **`Destino:`**, que alguns despachos trazem impresso;
   2. as linhas **`À/Ao/Aos/Às <nome>`** (ignorando `C/c:` e cortando em
      `Assunto:`/`Referência:`/`Processo nº`). Um despacho pode endereçar
      **mais de uma unidade**; elas ficam na mesma célula separadas por `"; "`,
      com a sigla reduzida **por destinatário**;
   3. sem os dois, não há destinatário no cabeçalho.
3. O corpo normalizado (espaços/quebras colapsados) é testado contra as regras
   **na ordem do arquivo**, com a primeira correspondência vencendo
   (`re.search`, caixa indiferente).
4. A regra vencedora preenche os quatro campos; `situacao`, `acao_esperada` e
   `pendencia_curta` podem usar **backreferences** (`\1`, `\2`...) e o
   placeholder `{destino}`.
5. O `destino` do **cabeçalho** **sobrepõe** o da regra quando existe; mesmo sem
   regra casando, o destinatário preenche `destino` no fallback.
6. Se **nenhuma** regra casar, vale o fallback (padrão: `"Em análise"`).

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

## Nomes de destino e siglas

Cada nome é mantido **por extenso e exato** (sem o `Aos/Ao/Às/À`). Ele vira
**sigla** quando:

- o **nome inteiro** é chave do mapa `siglas` do `regras.json` (comparação
  normalizada, ignorando acentos e hífens) — ex.: `Gabinete da
  Secretaria-Executiva` → `SE`; mas o **nome exato** que vale
  (`Gabinete da Secretaria-Executiva` não vira `SE`);
- a sigla aparece entre parênteses (`(CGATI)`) ou após travessão (`– COSIS`);
- o nome por extenso vem com o código de memória do SEI no fim
  (`Coordenação-Geral de Tecnologia da Informação - CGTI/MMULHERES` → `CGTI`).

## O placeholder `{destino}`

A maior parte das regras descreve a situação pela **ação** pedida
(`Encaminhado a conhecimento e deliberação`). A regra de unidade interna não
pode: o corpo só diz *"retorno a esta Coordenação"*, e `"Em \\1"` produzia `Em
Coordenação` — genérico. A solução é o placeholder **`{destino}`**, expandido com
o **destinatário já resolvido** (portanto o do cabeçalho, quando existe):

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

- **o texto é literal** — a substituição é `str.replace`, não regex: um `\1` que
  faça parte do nome do destinatário é copiado, nunca consumido;
- **`{destino}` nunca fica exposto** — sem destinatário, expande para
  `(destino não identificado)`, para não gerar a frase quebrada `Em `;
- **só substitui depois** das backreferences, ou seja, `{destino}` sempre recebe
  o destino **efetivo** (cabeçalho > captura do corpo).

Quando não existe linha de destinatário **e** o corpo nomeia só o substantivo, o
destino efetivo é esse substantivo e a situação repete o texto (`Em Coordenação`)
— sem inventar sigla.

## De onde vem cada campo

Cada valor vem de uma destas fontes, todas **literais**:

| # | Fonte | O que é |
| - | ----- | ------- |
| 1 | **Cabeçalho do despacho** | o destinatário impresso no cabeçalho (`Destino:` ou `À/...`), como está no documento |
| 2 | **Trecho capturado do corpo** | a(s) palavra(s) que o `pattern` casou, devolvidas por `\1`, `\2`... |
| 3 | **Texto fixo da regra** | frase escrita à mão em `regras.json`, com `{destino}` expandindo para o destinatário resolvido |

Não havendo nenhuma dessas fontes, a célula fica **vazia** — "o despacho não diz
isso", nunca uma hipótese. O único preenchimento automático é o fallback
`situacao = "Em análise"`.

| Campo | Fonte | Quando fica vazio |
| ----- | ----- | ----------------- |
| `situacao` | texto fixo (3) e/ou `\1`/`\2` (2) | nunca: sem regra casando entra `Em análise` |
| `destino` | cabeçalho (1); sem ele, `\1`/`\2` do corpo (2) | despacho sem destinatário **e** sem regra que capture um |
| `acao_esperada` | texto fixo (3) e/ou `\1`/`\2` (2) | a regra descreve a situação mas não a ação |
| `pendencia_curta` | texto fixo (3) e/ou `\1`/`\2` (2) | idem |

## Exemplos rastreados

Os textos abaixo são os mesmos de `tests/test_rules.py`, portanto reproduzíveis
(`python -m unittest tests.test_rules`).

**1. `21260.003611/2026-66` — destino pelo cabeçalho, ação pelo corpo**

> `À Coordenação-Geral de Administração e Tecnologia da Informação`
> ... *"encaminham-se os autos à Coordenação-Geral de Administração e Tecnologia
> da Informação (CGATI), para conhecimento e deliberação..."*

| `destino` | `situacao` | `acao_esperada` | `pendencia_curta` |
| --------- | ---------- | --------------- | ----------------- |
| `CGATI` | `Encaminhado a conhecimento e deliberação` | `conhecimento e deliberação` | `Aguardando conhecimento e deliberação do destinatário` |

**2. `14021.072944/2026-92` — nenhuma regra casou (fallback)**

> `À Secretaria-Executiva` / `Assunto: ...`
> ... *"Encaminho o presente processo para análise e providências."*

| `destino` | `situacao` | `acao_esperada` | `pendencia_curta` |
| --------- | ---------- | --------------- | ----------------- |
| `SE` | `Em análise` | *(vazia)* | *(vazia)* |

Caso honesto: o texto não casou com nenhum padrão, então `Em análise` e as colunas
de ação ficam vazias. `Em análise` **não** vira `Em SE`: o fallback marca
"precisa de leitura humana", e o destinatário já está em `destino` ao lado.

**3. `21260.000680/2025-37` — destino pelo campo `Destino:`**

> `Destino:` / `Assessoria Especial de Comunicação Social - ASCOM`
> ... *"informamos que já foram recebidos e anexados a este processo parte dos
> currículos..."*

| `destino` | `situacao` | `acao_esperada` | `pendencia_curta` |
| --------- | ---------- | --------------- | ----------------- |
| `ASCOM` | `Em análise` | *(vazia)* | *(vazia)* |

Sem linha `À/Ao/Aos/Às`, o destinatário está no campo `Destino:`. `ASCOM` não foi
adivinhado: o próprio despacho escreve o nome por extenso seguido da sigla.

**4. `21260.001106/2026-87` — encerramento acima do cargo da signatária**

> `Termo de Encerramento de Processo`
> ... *"procedo ao seu encerramento."*
> `assinado digitalmente` / `ANA CAROLINA SANTANA MOREIRA` /
> `Assessora Técnica` / `Assessoria Especial de Controle Interno - AECI`

| `destino` | `situacao` | `acao_esperada` | `pendencia_curta` |
| --------- | ---------- | --------------- | ----------------- |
| *(vazia)* | `Encerrado` | `nenhuma (processo encerrado)` | `Processo encerrado, sem ação pendente` |

Sem destino: o despacho encerra o processo e não encaminha nada. A regra de
encerramento vem **antes** da de unidade interna porque o bloco de assinatura
carrega `Assessoria` e a linha viraria `Em Assessoria` — pendência que não existe.

## Regras específicas da unidade

As **5 primeiras** regras remetem à unidade `MMULHERES-SE-SGA-CGATI-CTI`, nas duas
formas citáveis: com sufixo legado `-DTI` e sem sufixo (o **lookahead negativo**
`(?!-DTI)` evita casar "por dentro" da forma legada). Os hífens são opcionais nos
padrões. Elas vêm **antes** das genéricas de propósito: quando o despacho fala da
própria unidade, queremos o nome exato como destino.

| Regra | Gatilho no despacho | Situação gerada |
| ----- | ------------------- | --------------- |
| 1 | "retorno a esta/essa/a **unidade**", "aguardando retorno da/de **unidade**", "retorno para **unidade**" | `Aguardando retorno de <unidade>` |
| 2 | "para/com vistas a (ciência\|análise\|manifestação\|parecer\|providências) da/do/de **unidade**" | `Aguardando <ação> de <unidade>` |
| 3 | "adote-se/adotem-se/providencie-se/adotar/tomar providências ... **unidade**" | `Aguardando providências de <unidade>` |
| 4 | "dê-se ciência/cientifique-se/para ciência da/do/de **unidade**" | `Para ciência de <unidade>` |
| 5 | "encaminha-se/remete-se (os autos) a/para **unidade**" | `Encaminhado a <unidade> (nossa unidade)` |

## Regras genéricas

Depois vêm padrões que capturam **qualquer destino/destinatária** e padrões
temáticos sem destino:

| Regra | Gatilho | Situação |
| ----- | ------- | -------- |
| 6 | "para/aguardando/pendente de **assinatura**" | `Pendente de assinatura` |
| 7 | "retorno a/aguardando retorno de/retorno para <destino>" | `Aguardando retorno` |
| 8 | "encaminha-se/remete-se (os autos) a **<alvo>**, para **<ação>**" (fecho; ex.: "... à CGATI, para conhecimento e deliberação") | `Encaminhado a <ação>` |
| 9 | "encaminho o presente processo para <ação> quanto à ..." | `Encaminhado a <ação>` |
| 10 | "encaminho/remeto **para <ação>**" sem citar autos nem unidade | `Encaminhado a <ação>` |
| 11 | "encaminha-se/remete-se (os autos) a/para <destino>" | `Encaminhado a <destino>` |
| 12 | "para/com vistas a (ação) de <destino>" | `Aguardando <ação> de <destino>` |
| 13–14 | "determino/determina-se o arquivamento", "arquive-se", "pelo arquivamento" | `Arquivado` |
| 15 | "devolva-se/devolvam-se/devolução dos autos" | `Devolvido` |
| 16 | "converta-se/transforme-se/conversão em (ofício\|nota técnica\|memorial\|termo)" | `Em conversão/transformação` |
| 17 | "dê-se ciência/cientifique-se/para ciência de <destino>" | `Para ciência de <destino>` |
| 18 | "adote-se/providencie-se/tomar providências (por) <destino>" | `Aguardando providências de <destino>` |
| 19 | "no prazo de/em até/prazo de **N** (dias\|horas\|meses)" | `Com prazo (N dias)` |
| 20 | `\b(defiro\|indefiro\|parcialmente procedente\|improcedente\|procedente)\b` | `Decisão: <termo>` |
| 21 | "cumpra-se/para cumprimento/determino cumprimento" | `Para cumprimento` |
| 22 | "sugere-se ... seja retomada/retomado ... planejamento" | `Aguardando retomada (avaliação futura)` |
| 23 | "termo de encerramento", "cumpriu seu objetivo", "procedo ao seu encerramento" | `Encerrado` |
| 24 | menção a unidade interna (`SGA`, `CCL`, `CTI`, `SCL`, `SG`, `COORDENAÇÃO`, `DIRETORIA`, `SECRETARIA`, `GERÊNCIA`, `NÚCLEO`, `DEPARTAMENTO`...) | `Em {destino}` |
| 25 | órgão externo (`Ministério Público`, `Tribunal de Contas`, `Controladoria`, `Polícia Federal`, `Receita Federal`, `INSS`, `AGU`, `PGFN`, `MPF`, `TCU`, `CGU`...) | `Encaminhado a órgão externo (<órgão>)` |

Duas regras existem por ordem, não por assunto:

- a **23 (encerramento)** vem **antes** da 24 (unidade interna) porque o bloco de
  assinatura de um termo carrega cargo/unidade da signatária, que casariam a 24 e
  produziriam uma pendência inexistente;
- a **24** é a única que usa `{destino}`: com linha de destinatário, a situação
  cita a **unidade** (`Em CGATI`) em vez do substantivo genérico do corpo
  (`Em Coordenação`); sem linha, repete o que o texto diz.

## Ordem e manutenção

- **Ordem importa.** Regras mais específicas vêm primeiro; uma regra genérica que
  casa quase tudo (ex.: órgão externo) fica no fim. As regras 8 e 9 vêm antes da
  10 e também lidam com quebra de linha na extração do PDF (`en\ncaminho`).
- **Ajuste de padrões.** Por serem regex, adicionar/editar regra exige cuidado com
  escapes no JSON: uma backreference é escrita `\\1` (dois caracteres), que o
  `json.load` converte para `\1`.

## O fallback "Em análise"

Se nenhuma regra casar, a situação padrão é **"Em análise"**. O `destino` ainda é
preenchido quando o cabeçalho cita o destinatário. O fallback **não** vira
`Em <destino>`: é o marcador de "nenhuma regra casou, precisa de leitura humana".

## Quando não há texto para interpretar

Algumas linhas refletem o estado da coleta, não uma regra. Os campos de
interpretação ficam vazios **de propósito** ("não foi possível ler", não "não
aplica"):

| `situacao` | Origem | Campos de interpretação |
| ---------- | ------ | ----------------------- |
| `Sem despacho público` | a árvore não tem nó da série "Despacho" (ou o despacho não pôde ser baixado) | todos vazios |
| `Texto não extraível (digitalizado?)` | o PDF foi baixado, mas o `pypdf` não extraiu texto | todos vazios |
| `Erro / retry` | a coleta do processo falhou; o motivo está em `status_coleta` | todos vazios |
| `Encerrado (verificar manualmente)` | Termo de Encerramento é o último documento | só a pendência de conferência |
| `Em análise` | texto lido, nenhuma regra casou | só `destino`, se o cabeçalho citar destinatário |
| (`status_coleta = concluído (cache)`) | o último Despacho não mudou: campos **copiados** da análise anterior | preservados |

## Como auditar uma linha

1. abra `link_process` no navegador (página pública real do processo);
2. baixe o **último Despacho** (mesmo critério: série "Despacho", maior data);
3. compare o texto com `regras.json`, **na ordem do arquivo** — a primeira regra
   que casar é a vencedora;
4. se a classificação estiver errada, corrija o **`regras.json`** e rode com
   `--force`. A planilha **não** se edita à mão: ela é regenerada a cada execução.
