# SEI Insights — Design

Data: 2026-09-22
Status: aprovado (brainstorming)

## 1. Contexto e objetivo

O projeto **sei-insights** acompanha os processos públicos da unidade
`MMULHERES-SE-SGA-CGATI-CTI-DTI` do órgão MMulheres na Pesquisa Pública do
SEI/ColaboraGov (`https://colaboragov.sei.gov.br/`).

A cada execução o sistema deve:

1. descobrir os processos públicos vinculados à unidade no período
   (janela configurável, padrão últimos 7 dias);
2. identificar os processos **novos** em relação à execução anterior;
3. para cada processo, localizar o **último Despacho** da árvore de
   documentos e extrair o texto dele;
4. interpretar o despacho com regras determinísticas e classificar a
   **situação atual** (ex.: "na CTI", "pendente de assinatura") e a
   **pendência** (o que falta / próximo passo);
5. gravar uma **planilha** (fonte da verdade) com uma linha por processo,
   incluindo a data da execução, além de abas de Novos e Resumo.

Escopo: apenas informação pública. O sistema **não** burla CAPTCHA, não
acessa documentos restritos e não resolve CAPTCHA de forma automática para
contornar controle (o CAPTCHA é tratado como o fluxo humano: OCR próprio ou
manual no navegador — mesmo comportamento já solidificado no coletor).

## 2. Base de partida

O sistema é **standalone** (novo diretório/projeto), mas **copia e
reaproveita** o que já funciona no projeto `sei-colaboragov`:

- sincronização AJAX da Pesquisa Pública (não esperar `.retorno-ajax`
  visível; observar a resposta POST usando `isPaginacao`; filtra por
  `acao_ajax_externo=protocolo_pesquisar`);
- resolução de CAPTCHA (OCR via `ddddocr` ou `--manual-captcha`);
- rate limit (pausa aleatória entre requisições; retry com backoff para
  429/5xx; tratamento de `Retry-After`);
- download de documentos via `context.request` (reutiliza cookies da
  sessão; salva `.part`; calcula SHA-256; determina extensão pelo MIME;
  rejeita HTML/vazio; evita colisão de nomes);
- banco SQLite base (modo WAL, retomada, `--force`);
- pontos de tolerância a variações de HTML (screenshots/HTML de diagnóstico
  em `.state/debug/`).

O coletor de origem fica intacto; nada de `sei-colaboragov` é alterado.

## 3. Variáveis de configuração

| Parâmetro | Default | Descrição |
|---|---|---|
| `--orgao` | `MMulheres` | Órgão gerador selecionado na pesquisa. |
| `--unidade` | `MMULHERES-SE-SGA-CGATI-CTI-DTI` | Unidade geradora selecionada na pesquisa. |
| `--dias` | `7` | Janela: de hoje-`dias` até hoje. |
| `--inicio` / `--fim` | derivados de `--dias` | Substituem a janela por datas explícitas. |
| `--manual-captcha` | OCR | Resolve o CAPTCHA no navegador em vez de OCR. |
| `--min-delay` / `--max-delay` | `2` / `5` | Pausa aleatória entre requisições (segundos). |
| `--force` | off | Reanalisa tudo ignorando o cache de hash. |
| `--saida` | `sei_insights.xlsx` | Caminho da planilha gerada. |

## 4. Pipeline

```
busca por unidade+período (+ 3 tipos marcados)
  --> lista de números únicos
  --> diff com o espelho anterior (SQLite)  -> novos
  --> para cada processo:
        página pública
        -> árvore de documentos
        -> último Despacho
        -> download do documento público
        -> extração de texto (pypdf)
        -> motor de regras
        -> linha da planilha
  --> grava planilha (espelho + Novos + Resumo)
  --> reconstrói SQLite como espelho exato da planilha
```

Execução **sequencial** (sem paralelismo, por propósito), com as pausas e
retries copiados do coletor.

## 5. Descoberta de processos (módulo `discovery`)

Nova rotina de busca na Pesquisa Pública:

- **Pesquisar em**: marcar as três opções — Processos, Documentos Gerados,
  Documentos Externos;
- **Órgão Gerador**: `--orgao`; **Unidade Geradora**: `--unidade`;
- **Período**: variável (`--inicio`/`--fim` ou `--dias`);
- preencher o formulário real (`#seiSearch`), submeter com a observação
  AJAX já instalada antes do submit (padrão do coletor);
- **paginação**: `rowsSolr=50`, avançar `inicio` a cada página até não
  haver mais `itens` (ou o módulo indicar o fim);
- deduplicar números de processo (via `normalize_process_number`);
- tolerância: resultado é tratado como "processos visíveis publicamente
  vinculados à unidade no período".

**Limitação conhecida:** processos que *chegaram* à CTI vindos de outras
unidades podem não aparecer como "gerados por ela". Se a busca pública não
os revelar, ficam de fora nesta versão; uma lista complementar de números
pode ser adicionada futuramente sem mudanças estruturais.

## 6. Leitura da árvore e último Despacho (módulo `tree`)

A página pública do processo (`md_pesq_processo_exibir.php`) monta a árvore
de documentos via JS. A leitura captura, para cada nó da árvore:

- **série documental** (rótulo — ex.: "Despacho", "Ofício", "Documento
  Externo");
- **número documental** (5+ dígitos, quando presente);
- **data** (dd/mm/aaaa, quando presente no rótulo);
- **posição** na árvore (ordem de renderização).

**Seleção do último Despacho:**
1. filtra os nós cuja série contém "Despacho";
2. escolhe o de **maior data**;
3. desempate por **posição mais recente** na árvore;
4. se não houver data no DOM, usa o **último nó** "Despacho" em ordem da
   árvore;
5. se não houver nenhum nó de série "Despacho", a situação do processo é
   **"Sem despacho público"** — sem download, sem análise, sem erro.

## 7. Download e extração de texto (módulos `download`/`text_ing`)

- Baixa **somente o documento do último Despacho**, usando o link público
  (`md_pesq_documento_consulta_externa.php`) entregue pela própria árvore;
- regras de download copiadas do coletor (`context.request`, rate limit,
  retries, `.part`, SHA-256, MIME);
- extração de texto com **pypdf**;
- se o PDF não tiver camada de texto (digitalizado), a situação é
  **"Texto não extraível (digitalizado?)"** — sem OCR nesta versão.

## 8. Motor de regras (módulo `rules` + `regras.json`)

Classificação determinística do texto do último Despacho. Produz quatro
campos por processo:

- **situacao** — enumeração normalizada (ver taxonomia inicial abaixo);
- **destino** — unidade/órgão para onde o processo foi encaminhado;
- **acao_esperada** — ação pedida (análise, validação, assinatura,
  retorno, providências, expedição etc.);
- **pendencia_curta** — resumo de 1 linha: o que falta e quem está com o
  processo.

Taxonomia inicial de `situacao` (configurável em `regras.json`):

| Situação | Gatilho típico |
|---|---|
| Em <unidade> | "encaminha-se ... à/ao <unidade>" |
| Pendente de assinatura | "para assinatura" / "assinatura" |
| Aguardando retorno de <X> | "aguardando retorno" / "retorno a ..." |
| Encaminhado a órgão externo | destinatário externo (ex.: Detran/DF) |
| Em <unidade> para ciência e validação | "para ciência e validação" |
| Na CTI | processos cujo despacho aponta ação na própria CTI |
| Sem despacho público | nenhum nó "Despacho" na árvore pública (sem ação identificável) |
| Sem documento público | processo sem documentos públicos |
| Texto não extraível (digitalizado?) | PDF sem camada de texto |
| Erro / retry | falha de coleta do processo |

As regras usam catálogo de verbos/destinos e têm leitura em `regras.json`
(termos, destinatários, sinônimos) para o usuário ajustar sem alterar
código.

## 9. Persistência e delta (módulo `store`)

Princípio definido com o usuário: **a planilha é a fonte da verdade; o
SQLite é apenas um espelho sincronizado dela**. Nada no BD pode impedir a
escrita de uma linha na planilha.

- Cada execução **sempre** grava na planilha **todos** os processos da
  coleta atual (o BD não é consultado para decidir o que entra);
- ao fim de uma execução bem-sucedida, o SQLite é **reconstruído por
  inteiro** para conter exatamente as linhas da planilha (mesmos processos,
  mais `hash_do_texto` do último despacho);
- **novos** = processos da coleta atual que **não** estavam no espelho
  anterior (leitura do SQLite no início da execução);
- **cache de velocidade (não bloqueante):** se o `hash_do_texto` não mudou
  e a situação já foi calculada, o processo não é rebaixado nem re-analisado
  — mas a linha dele continua sendo gravada na planilha;
- falha no meio da execução: o SQLite permanece com o último estado
  completo anterior, e a próxima rodada calcula "novos" corretamente;
- não existe conceito de `completed` permanente: se o número reaparecer na
  coleta atual, entra na planilha normalmente.

Banco: `.state/sei_insights.sqlite3` (modo WAL).

## 10. Planilha (módulo `report`)

Formato: **xlsx** (`openpyxl`). Arquivo: `sei_insights.xlsx`
(`--saida`).

**Aba principal — espelho do estado atual:** uma linha por processo, com:

| Coluna | Conteúdo |
|---|---|
| número | número do processo (normalizado) |
| título | título exibido na pesquisa pública |
| data execução | data/hora da execução que gerou a linha |
| data_ultimo_despacho | data do último despacho (quando conhecida) |
| situacao | situação classificada |
| destino | unidade/órgão de destino |
| acao_esperada | ação esperada |
| pendencia_curta | resumo do que falta |
| link_process | URL pública do processo |
| status_coleta | concluído / erro (mensagem) |

**Aba Novos:** processos que não estavam no espelho anterior, com a mesma
estrutura da aba principal.

**Aba Resumo:** contagens — total, novos, por situação, por status_coleta.

A planilha é **substituída a cada execução** (espelho do momento).

## 11. Componentes e estrutura do projeto

```
sei-insights/
├── main.py            # CLI e orquestração
├── sei_client.py      # base copiada do coletor (navegação, CAPTCHA, AJAX, download)
├── captcha_solver.py  # copiado
├── rate_limit.py      # copiado
├── discovery.py       # busca por unidade+período, paginação, dedupe
├── tree.py            # leitura da árvore + seleção do último despacho
├── text_ing.py        # extração de texto (pypdf)
├── rules.py           # motor de regras
├── regras.json        # taxonomia/termos configuráveis
├── store.py           # SQLite espelho e delta
├── report.py          # planilha xlsx
├── requirements.txt
├── downloads/         # cache de documentos por processo (gerado)
├── .state/            # SQLite + diagnóstico (gerado)
├── tests/             # unittest
└── README.md
```

`requirements.txt`:

```
playwright>=1.52,<2
beautifulsoup4>=4.13,<5
ddddocr>=1.4.0
opencv-python-headless>=4.8.0
pypdf>=5.0
openpyxl>=3.1
```

> `lxml` fica de fora (quebra no Python 3.14/Windows). `pypdf` e `openpyxl`
> são 100% Python e compatíveis.

## 12. CLI

```
python main.py
python main.py --dias 14
python main.py --inicio 2026-09-01 --fim 2026-09-22
python main.py --unidade "MMULHERES-SE-SGA-CGATI-CTI-DTI" --manual-captcha
python main.py --min-delay 3 --max-delay 7 --force
```

Padrão dos argumentos de validação copiado do coletor
(`--max-delay >= --min-delay`, valores não negativos etc.).

## 13. Tratamento de erro e retomada

- processamento sequencial; a falha de um processo não interrompe os demais
  (`status_coleta` = erro com mensagem na planilha);
- rate limit: pausa aleatória 2–5s; 429 respeita `Retry-After`; 5xx e erros
  de conexão usam backoff (código copiado);
- retomada: processos ainda não finalizados na rodada podem ser retomados na
  próxima execução; `--force` força re-análise ignorando o cache de hash.

## 14. Testes

`unittest` (padrão da base). Coberturas:

- `tree`: extração de árvore a partir de HTML de exemplo; seleção do último
  despacho por data/posição; ausência de despacho;
- `text_ing`: extração de texto de um PDF de exemplo; PDF sem camada de
  texto;
- `rules`: despachos exemplares cobrindo as situações da taxonomia;
- `store`: reconstrução do espelho; cálculo de novos; cache por hash não
  bloqueia gravação;
- `report`: escrita da planilha e conteúdo das abas;
- `discovery`: parsing/paginação com fixture da resposta JSON.

## 15. Fora de escopo (futuro possível)

- OCR de PDFs digitalizados;
- LLM / busca semântica / RAG;
- lista complementar de números mantida pelo usuário;
- agendamento automático (Task Scheduler);
- destinação/notificação (e-mail, dashboards).