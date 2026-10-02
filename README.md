# SEI Insights

Acompanha os **processos públicos** da unidade `MMULHERES-SE-SGA-CGATI-CTI` do
órgão **MMulheres** na **Pesquisa Pública do SEI/ColaboraGov**
([colaboragov.sei.gov.br](https://colaboragov.sei.gov.br/)) e gera uma planilha
com a situação de cada processo.

O diferencial em relação a um "download de PDFs" é a camada de **interpretação**:
o texto do último Despacho é classificado por um motor de regras determinístico.
Por exemplo, *"encaminham-se os autos para análise e providências da SGA"* vira
situação **"Aguardando providências da SGA"**, com `destino`, `acao_esperada` e
`pendencia_curta` preenchidos. As regras ficam em `regras.json` e podem ser
ajustadas **sem tocar no código**.

> **Importante:** o programa **não** burla CAPTCHA, **não** acessa documentos
> restritos e **não** contorna bloqueios. Usa apenas os links públicos do SEI,
> seguindo o mesmo fluxo de um usuário humano. O CAPTCHA é resolvido por OCR
> local ou manualmente no navegador.

## O que o script faz

A cada execução o programa:

1. **descobre** os processos públicos vinculados à unidade no período
   configurado (padrão: últimos 7 dias);
2. identifica os processos **novos** em relação à execução anterior;
3. localiza o **último Despacho** da árvore de documentos e extrai o texto dele;
4. **interpreta** o despacho com regras determinísticas e classifica a
   **situação atual** e a **pendência**;
5. grava uma **planilha XLSX** (fonte da verdade) com uma linha por processo e
   uma aba **Resumo da última execução**;
6. reconstrói o banco **SQLite** como espelho exato da planilha.

## Começando

Pré-requisitos: **Python 3.10+**, pip e acesso à internet. A instalação detalhada
por sistema — incluindo as notas de OCR — está em
[Instalação](docs/instalacao.md).

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
python -m playwright install chromium
```

Na pasta do projeto, com o ambiente virtual ativado:

```bash
python -m sei_insights
```

O comando `sei-insights` é equivalente (disponível após `pip install -e .`). Sem
o install, `python -m sei_insights` falha com `ModuleNotFoundError`.

### Opções da linha de comando

| Opção                | Descrição                                                      |
| -------------------- | -------------------------------------------------------------- |
| `--orgao`            | Órgão gerador na pesquisa (padrão: `MMulheres`).               |
| `--unidade`          | Unidade geradora na pesquisa (padrão: `MMULHERES-SE-SGA-CGATI-CTI`). |
| `--dias`             | Janela de busca: de hoje-`dias` até hoje (padrão: `7`; deve ser > 0). |
| `--inicio`           | Data inicial explícita (`DD/MM/AAAA`); substitui `--dias`.     |
| `--fim`              | Data final explícita (`DD/MM/AAAA`); padrão: hoje.             |
| `--manual-captcha`   | Resolve o CAPTCHA manualmente no navegador (padrão: OCR automático). |
| `--min-delay`        | Pausa mínima entre requisições, em segundos (padrão: `2.0`).   |
| `--max-delay`        | Pausa máxima entre requisições, em segundos (padrão: `5.0`).   |
| `--force`            | Reanalisa todos os processos ignorando o cache de hash.        |
| `--saida`            | Caminho da planilha gerada (padrão: `sei_insights.xlsx`).      |

```bash
# Execução padrão (últimos 7 dias)
python -m sei_insights

# Período explícito
python -m sei_insights --inicio 01/09/2026 --fim 22/09/2026

# Ritmo mais lento + força reanálise
python -m sei_insights --min-delay 3 --max-delay 7 --force
```

> **CAPTCHA manual:** quando ativo, preencha o CAPTCHA **no navegador**. Não
> pressione ENTER no terminal — o programa continua sozinho assim que o campo é
> preenchido.

## O que é gerado

- **`sei_insights.xlsx`** (ou o caminho de `--saida`) — a fonte da verdade, com
  a aba principal (uma linha por processo) e a aba **Resumo da última execução**.
  As colunas e o significado de cada uma estão em
  [Operação](docs/operacao.md#as-colunas-da-planilha).
- **`.state/sei_insights.sqlite3`** — espelho exato da planilha, reconstruído a
  cada execução.
- **`downloads/`** — os PDFs dos Despachos lidos.

`*.xlsx`, `.state/` e `downloads/` são gerados pelo programa e **não devem ser
versionados**.

## Estrutura do projeto

| Arquivo / pasta                          | Função                                                            |
| ---------------------------------------- | ----------------------------------------------------------------- |
| `pyproject.toml`                         | Metadados do pacote e comando `sei-insights`.                     |
| `src/sei_insights/cli.py`                | CLI e orquestração (argumentos, `build_rows`, espelho).           |
| `src/sei_insights/config/`               | Configuração central (caminhos, padrões) e motor de regras.       |
| `regras.json`                            | Lista ordenada de regras de classificação (editável).             |
| `src/sei_insights/clients/`              | Pesquisa pública, paginação, dedupe, CAPTCHA e rate limit.        |
| `src/sei_insights/documents/`            | Árvore de documentos e extração de texto do PDF.                  |
| `src/sei_insights/storage/`              | Espelho SQLite e geração da planilha XLSX.                        |
| `src/sei_insights/utils/`                | Apoio: normalização de número, SHA-256, MIME, nomes seguros.      |
| `requirements.txt`                       | Dependências Python do projeto.                                   |
| `tests/`                                 | Testes automatizados (`unittest`).                                |

## Solução de problemas (FAQ)

**`python: command not found` / "Python was not found"** — verifique se o Python
está no PATH. No Windows, reinstale marcando *"Add Python to PATH"* ou use o `py`.

**`ModuleNotFoundError: No module named 'playwright'` / `'bs4'` / ...** —
dependências não instaladas: `pip install -r requirements.txt`.

**`Executable doesn't exist at ...chromium`** — navegador do Playwright não
instalado: `python -m playwright install chromium` (no Linux, `--with-deps`).

**CAPTCHA não é resolvido / OCR falha** — use `--manual-captcha` (o programa abre
o navegador; não precisa teclar ENTER). No Linux, verifique `libgomp1`.

**Um processo aparece como "Sem despacho público"** — a árvore pública não tem nó
da série "Despacho" (ou não há documentos públicos). Não é erro de execução: é a
classificação correta.

**Muitos processos aparecem como "Verificar manualmente" (fallback)** — nenhuma
regra casou e o cabeçalho não traz uma sigla limpa. Revise o `regras.json` (veja
[Regras e classificação](docs/regras.md)) e adicione um padrão para o caso real
observado.

**O processo ficou com `status_coleta = erro: ...`** — uma falha não interrompe os
demais. Corrija a causa indicada e rode `--force`.

**Rodei e nada foi baixado — só "concluído (cache)"** — normal: o último Despacho
não mudou e o PDF não é rebaixado. O cache **não** confere se o PDF existe em
`downloads/`; use `--force` para rebuscar.

**O processo apareceu com um `numero` que não era o que vi na busca** — a busca
devolve linhas de **documentos** (além de processos); o programa deduplica pela
URL e usa o número canônico do cabeçalho. O número da planilha é sempre o do
**processo**.

**A biblioteca `ddddocr` não instala (Linux/Windows)** — depende de
`onnxruntime`/`opencv-python-headless`; se falhar, instale o
`opencv-python-headless` primeiro. O `--manual-captcha` não depende do OCR.

**Como vejo o que está acontecendo?** — o programa registra tudo no terminal
(`data | nível | mensagem`). Em falhas estruturais, screenshots/HTML são salvos em
`.state/debug/`.

## Testes

A suíte usa apenas a biblioteca padrão (`unittest`) e deve rodar **a partir da
raiz do repositório** (os testes leem `regras.json` relativo ao diretório atual):

```bash
python -m unittest discover -s tests -v
```

Para um módulo específico: `python -m unittest tests.test_rules -v`.

## Documentação

| Documento | Conteúdo |
| --------- | -------- |
| [Instalação](docs/instalacao.md) | Passo a passo por sistema operacional e notas de OCR. |
| [Como funciona](docs/como-funciona.md) | Fluxo, descoberta, paginação, árvore, último Despacho e persistência. |
| [Regras e classificação](docs/regras.md) | Motor de regras, `regras.json`, campos e exemplos rastreados. |
| [Operação](docs/operacao.md) | Colunas da planilha, cache e limpeza de dados. |
