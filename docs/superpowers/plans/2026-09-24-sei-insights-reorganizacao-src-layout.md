# Reorganização em src-layout — Plano de Implementação

> **Status: ✅ IMPLEMENTADO** — verificado em 24/09/2026. Todos os passos concluídos (commits `ba8f010`, `ca99e8b`, `9bba651`, `589c7cf`); suíte verde (58 testes OK); estrutura `src/sei_insights/` confirmada.

> **Para workers agentic:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa-a-tarefa. Passos usam caixa de seleção (`- [ ]`) para rastreio.

**Goal:** Organizar todos os módulos Python do `sei-insights` em um pacote `sei_insights` com src-layout, sem nenhuma mudança de comportamento, criando `pyproject.toml`, `__main__.py` e atualizando README/.gitignore.

**Architecture:** Pacote único plano `src/sei_insights/` com os mesmos 11 módulos (renomeando `main.py` → `cli.py`); imports internos viram `from sei_insights.X import ...`; alvos de `mock.patch`/`patch` nos testes também são reescritos; testes permanecem flat em `tests/` importando do pacote instalado via `pip install -e .`; `regras.json` segue na raiz (config editável, CWD-relativa).

**Tech Stack:** Python (>=3.10), unittest (stdlib), setuptools (pyproject, src-layout, PEP 660 editable), Windows/PowerShell.

**Spec:** `docs/superpowers/specs/2026-09-24-sei-insights-reorganizacao-src-layout-design.md`

## Global Constraints

Corrige de cópia, uma linha cada — valem para todas as tarefas:

- **Zero mudança de comportamento**: os corpos das funções/classes/constantes são cópias exatas; a única diferença é imports e o deslocamento do bloco `__main__`.
- **Nomes não mudam**: `MirrorStore`, `RulesEngine`, `SeiClient`, `build_rows`, `now_str`, `parse_arguments`, `main`, `FIELDS`, `ProcessRow`, `ProcessResult`, `DocNode`, `RuleResult`, `RateLimiter`, `CaptchaSolver`.
- **Regra de imports**: `from X import ...` → `from sei_insights.X import ...`. Exceção única: `from main import ...` → `from sei_insights.cli import ...`.
- **Alvos de mock são strings e também mudam**: `rate_limit.time.sleep` → `sei_insights.rate_limit.time.sleep` (idem `random.uniform`, `time.monotonic`); `captcha_solver.CaptchaSolver.solve_from_base64` → `sei_insights.captcha_solver.CaptchaSolver.solve_from_base64`.
- **`regras.json` permanece na raiz**, resolvido relativo ao CWD. **Testes rodam SEMPRE da raiz do repositório**.
- **Entry points exigem `pip install -e .`** no venv; sem ele `python -m sei_insights` dá `ModuleNotFoundError` e o comando `sei-insights` não existe.
- **Dependências**: fonte única `requirements.txt` (lida por `[tool.setuptools.dynamic]`); Python >= 3.10.
- **Staging**: NUNCA `git add -A` nem `git add -u .` (re-encenariam `SEI_ColaboraGov_handoff_context.*` deletados e `.worktrees/` untracked). Use `git mv` para arquivos que mudam de lugar e `git add <caminho>` direcionado para novos/modificados.
- **Ambiente**: Windows; venv em `.venv` (já no `.gitignore`); invoque o Python do venv como `& .venv\Scripts\python.exe`. Deps já provisionadas no venv pela Tarefa 1.

## Review Focus

Classes de entrada/modas de falha que a spec implica e que nenhum teste unitário novo cobre; cada linha é exercitada na tarefa/ passo indicado:

1. **Módulo órfão na raiz após a reorganização** — usuário rodaria com módulos duplicados. → Tarefa 3, passo de verificação + Tarefa 5.
2. **`mock.patch` com caminho antigo** — patch silenciosamente errado / `ModuleNotFoundError`. → reescrita dos alvos na Tarefa 3 (exercitada pela própria suíte).
3. **Testes rodados fora da raiz** — `test_rules.py` lê `regras.json` relativo ao CWD e falha com `FileNotFoundError`. → todos os comandos de execução do plano usam `workdir` = raiz do repo.
4. **Install editável ausente** — `python -m sei_insights` falha. → Tarefa 2 (install + import) e Tarefa 5 (smoke).
5. **Artifacts de build vazando para o git** (`*.egg-info/`) — sujaria `git status`. → `.gitignore` na Tarefa 2 e checagem na Tarefa 5.

---

### Task 1: Provisionar ambiente canônico e registrar baseline

**Files:** nenhum (infra; `.venv/` é gerado e gitignored).

**Interfaces:**
- Consumes: `requirements.txt` (deps), `tests/` (suíte atual importando módulos da raiz).
- Produces: o comando canônico de execução de testes usado por todas as tarefas seguintes:
  `& .venv\Scripts\python.exe -m unittest discover -s tests -v` (da raiz do repo) e a **tally da baseline** (contagem pass/skip/fail).

- [x] **Passo 1: criar o venv**

```powershell
python -m venv .venv
```

Expected: pasta `.venv/` criada.

- [x] **Passo 2: provisionar as dependências no venv (fonte única: requirements.txt)**

```powershell
& .venv\Scripts\python.exe -m pip install -r requirements.txt
```

Expected: instala `playwright`, `beautifulsoup4`, `ddddocr` (+transitivas), `opencv-python-headless`, `pypdf`, `openpyxl`. **Se falhar** (ex.: rodas para Python 3.14 no Windows), PARE e reporte o bloqueio — não continue o plano sem resolver.

- [x] **Passo 3: rodar a baseline e registrar a tally**

```powershell
& .venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: suíte **verde** (deps instaladas agora), contagem de pass/skip/fail. Anote a tally exata (número de testes e de skips — `test_captcha_solver` roda porque ddddocr está presente). Registre-a em `C:\Users\WERMES~1.SIL\AppData\Local\Temp\opencode\sei-insights-baseline.txt` (evidência para comparar na Tarefa 3 e 5):
- `Ran N tests`
- erros/falhas/skips

Se a baseline tiver qualquer erro/falha, PARE e diagnostique antes de prosseguir.

**Deliverable:** ambiente canônico provisionado + tally da baseline registrada. Nenhum commit (nada de arquivo versionado mudou).

---

### Task 2: Esqueleto do pacote, pyproject.toml, .gitignore e install editável

**Files:**
- Create: `src/sei_insights/__init__.py`
- Create: `pyproject.toml`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: venv da Tarefa 1.
- Produces: pacote `sei_insights` importável no venv (via editable install); comando de verificação `& .venv\Scripts\python.exe -c "import sei_insights; print(sei_insights.__version__)"` → deve imprimir `0.1.0`. Os módulos ainda estão na raiz (migração é a Tarefa 3).

- [x] **Passo 1: criar `src/sei_insights/__init__.py`**

Conteúdo exato:

```python
__version__ = "0.1.0"
```

- [x] **Passo 2: criar `pyproject.toml` na raiz**

Conteúdo exato:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "sei-insights"
version = "0.1.0"
description = "Acompanhamento dos processos públicos da unidade MMULHERES-SE-SGA-CGATI-CTI-DTI no SEI/ColaboraGov"
requires-python = ">=3.10"
readme = "README.md"

[project.scripts]
sei-insights = "sei_insights.cli:main"

[tool.setuptools.dynamic]
dependencies = {file = ["requirements.txt"]}

[tool.setuptools.packages.find]
where = ["src"]
```

Nota: `sei_insights.cli` ainda não existe (será criado na Tarefa 3) — isso não impede o install editável.

- [x] **Passo 3: atualizar `.gitignore`** (acrescentar ao final)

Acrescente estas 3 linhas ao arquivo atual:

```
*.egg-info/
build/
dist/
```

- [x] **Passo 4: instalar o pacote editável no venv**

```powershell
& .venv\Scripts\python.exe -m pip install -e .
```

Expected: sucesso (build isolado com setuptools>=68; deps já instaladas são no-op). Isto cria `src/sei_insights.egg-info/`, ignorado pelo `.gitignore` (Passo 3).

- [x] **Passo 5: verificar que o pacote é importável**

```powershell
& .venv\Scripts\python.exe -c "import sei_insights; print(sei_insights.__version__)"
```

Expected: imprime `0.1.0`. (Não rode `sei-insights --help` aqui — `cli.py` ainda não existe.)

- [x] **Passo 6: confirmar que a suíte continua idêntica à baseline**

```powershell
& .venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: mesma tally da Tarefa 1 (nada de comportamento mudou; testes ainda importam módulos da raiz).

- [x] **Passo 7: commit**

```powershell
git add pyproject.toml src/sei_insights/__init__.py .gitignore
git commit -m "chore: esqueleto do pacote sei_insights e pyproject (src-layout)"
```

**Deliverable:** `pip install -e .` funcionando nesta máquina (Windows/Python 3.14) + pacote importável + suíte verde — pré-requisito verificado antes de qualquer movimentação.

---

### Task 3: Mover módulos para o pacote e reescrever imports

**Files:**
- Move: `main.py` → `src/sei_insights/cli.py`; `sei_client.py`, `discovery.py`, `tree.py`, `text_ing.py`, `rules.py`, `store.py`, `report.py`, `captcha_solver.py`, `rate_limit.py`, `utils.py` → `src/sei_insights/`
- Rename: `tests/test_main.py` → `tests/test_cli.py`
- Create: `src/sei_insights/__main__.py`
- Modify: todos os 11 módulos movidos (só imports) e todos os 11 arquivos de teste (só imports/strings)

**Interfaces:**
- Consumes: pacote editável da Tarefa 2; suíte da baseline da Tarefa 1.
- Produces: layout de destino do §3 da spec; entry points `python -m sei_insights` e `sei-insights`; suíte com tally **idêntica** à baseline.

- [x] **Passo 1: mover os 11 módulos com `git mv`**

```powershell
git mv sei_client.py discovery.py tree.py text_ing.py rules.py store.py report.py captcha_solver.py rate_limit.py utils.py src/sei_insights/
git mv main.py src/sei_insights/cli.py
```

Expected: `git status` mostra 11 renames do tipo `rename ... -> src/sei_insights/...`, sem deleções órfãs na raiz.

- [x] **Passo 2: criar `src/sei_insights/__main__.py`**

Conteúdo exato (bloco que antes vivia no final de `main.py`):

```python
import sys

from sei_insights.cli import main


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Passo 3: reescrever imports nos 10 módulos que não são o cli**

Conteúdo dos módulos movidos, exceto `cli.py` — substituições EXATAS de linha:

- `src/sei_insights/sei_client.py`:
  - `from discovery import expected_total, pagination_params, parse_response` → `from sei_insights.discovery import expected_total, pagination_params, parse_response`
  - `from rate_limit import RateLimiter` → `from sei_insights.rate_limit import RateLimiter`
  - `from utils import normalize_process_number, safe_filename, calculate_sha256, extension_from_content_type, looks_like_html, unique_path` → `from sei_insights.utils import normalize_process_number, safe_filename, calculate_sha256, extension_from_content_type, looks_like_html, unique_path`
- `src/sei_insights/discovery.py`:
  - `from utils import normalize_process_number` → `from sei_insights.utils import normalize_process_number`
- `src/sei_insights/report.py`:
  - `from store import FIELDS, ProcessRow` → `from sei_insights.store import FIELDS, ProcessRow`
- `src/sei_insights/utils.py`, `tree.py`, `text_ing.py`, `rules.py`, `store.py`, `captcha_solver.py`, `rate_limit.py`: **nenhum import interno — nada a mudar**.

Verificação: nenhum outro `from <módulo interno>` sem o prefixo `sei_insights.` restante:

```powershell
Select-String -Path src\sei_insights\*.py -Pattern '^\s*from (discovery|sei_client|store|report|utils|rules|tree|text_ing|rate_limit) import'
```

Expected: nenhum resultado.

- [x] **Passo 4: reescrever imports no `src/sei_insights/cli.py` (antigo main.py)**

- Bloco de imports no topo:
  - `from report import build_resumo, write_spreadsheet` → `from sei_insights.report import build_resumo, write_spreadsheet`
  - `from sei_client import ProcessResult, SeiClient` → `from sei_insights.sei_client import ProcessResult, SeiClient`
  - `from store import MirrorStore, ProcessRow` → `from sei_insights.store import MirrorStore, ProcessRow`
- Bloco de imports de dentro de `main()` (linhas ~116-123):
  - `from discovery import expected_total, pagination_params, parse_response  # noqa: F401` → `from sei_insights.discovery import expected_total, pagination_params, parse_response  # noqa: F401`
  - `from rate_limit import RateLimiter` → `from sei_insights.rate_limit import RateLimiter`
  - `from rules import RulesEngine` → `from sei_insights.rules import RulesEngine`
  - `from sei_client import (  # noqa: F401` → `from sei_insights.sei_client import (  # noqa: F401` (a linha de baixo `ProcessResult, SeiClient)` continua igual)
  - `from text_ing import extract_text_from_pdf` → `from sei_insights.text_ing import extract_text_from_pdf`
  - `from tree import correlate_urls, parse_tree, select_last_despacho` → `from sei_insights.tree import correlate_urls, parse_tree, select_last_despacho`
  - `from utils import normalize_process_number  # noqa: F401` → `from sei_insights.utils import normalize_process_number  # noqa: F401`
- Remover o bloco final inteiro:

```python
if __name__ == "__main__":
    sys.exit(main())
```

- Remover o agora-desnecessário `import sys` do topo (era usado só pelo bloco removido; `sys` não aparece em nenhum outro lugar do arquivo).

Verificação:

```powershell
Select-String -Path src\sei_insights\cli.py -Pattern '^\s*from (discovery|sei_client|store|report|utils|rules|tree|text_ing|rate_limit) import'
```

Expected: nenhum resultado; e `Select-String -Path src\sei_insights\cli.py -Pattern '__main__'` → nenhum resultado.

- [x] **Passo 5: renomear o arquivo de teste**

```powershell
git mv tests/test_main.py tests/test_cli.py
```

- [x] **Passo 6: reescrever imports nos testes** (substituições EXATAS por arquivo)

- `tests/test_cli.py` (antes `test_main.py`):
  - `from main import build_rows, now_str, parse_arguments` → `from sei_insights.cli import build_rows, now_str, parse_arguments`
  - `from sei_client import ProcessResult` → `from sei_insights.sei_client import ProcessResult`
  - `from store import ProcessRow` → `from sei_insights.store import ProcessRow`
  - (dentro de `EmptyResultTest.test_calcula_resumo_vazio_sem_erro`): `from report import build_resumo` → `from sei_insights.report import build_resumo`
- `tests/test_sei_client.py`:
  - `from sei_client import SeiClient, extract_process` → `from sei_insights.sei_client import SeiClient, extract_process`
- `tests/test_discovery.py`:
  - `from discovery import expected_total, pagination_params, parse_response` → `from sei_insights.discovery import expected_total, pagination_params, parse_response`
- `tests/test_tree.py`:
  - `from tree import correlate_urls, parse_tree, select_last_despacho` → `from sei_insights.tree import correlate_urls, parse_tree, select_last_despacho`
- `tests/test_rules.py`:
  - `from rules import RulesEngine` → `from sei_insights.rules import RulesEngine`
- `tests/test_store.py`:
  - `from store import MirrorStore, ProcessRow, despacho_hash` → `from sei_insights.store import MirrorStore, ProcessRow, despacho_hash`
- `tests/test_report.py`:
  - `from report import build_resumo, write_spreadsheet` → `from sei_insights.report import build_resumo, write_spreadsheet`
  - `from store import ProcessRow` → `from sei_insights.store import ProcessRow`
- `tests/test_text_ing.py`:
  - `from text_ing import extract_text_from_pdf` → `from sei_insights.text_ing import extract_text_from_pdf`
- `tests/test_utils.py`:
  - `from utils import (` → `from sei_insights.utils import (` (a lista multi-linha dos 6 nomes continua igual)
- `tests/test_captcha_solver.py`:
  - `from captcha_solver import CaptchaSolver` → `from sei_insights.captcha_solver import CaptchaSolver`
  - Substitua **todas as 4 ocorrências** de `'captcha_solver.CaptchaSolver.solve_from_base64'` por `'sei_insights.captcha_solver.CaptchaSolver.solve_from_base64'` (use replace-all)
- `tests/test_rate_limit.py`:
  - `from rate_limit import RateLimiter` → `from sei_insights.rate_limit import RateLimiter`
  - `"rate_limit.time.sleep"` → `"sei_insights.rate_limit.time.sleep"`
  - `"rate_limit.random.uniform"` → `"sei_insights.rate_limit.random.uniform"`
  - `"rate_limit.time.monotonic"` → `"sei_insights.rate_limit.time.monotonic"`

Verificação final — nenhum import de módulo da raiz restante nos testes:

```powershell
Select-String -Path tests\test_*.py -Pattern '^\s*from (main|discovery|sei_client|store|report|utils|rules|tree|text_ing|rate_limit|captcha_solver) import'
```

Expected: nenhum resultado.

- [x] **Passo 7: rodar a suíte completa e comparar com a baseline**

```powershell
& .venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: tally **idêntica** à registrada na Tarefa 1 (mesmo `Ran N tests`, mesmo fluxo, `OK` ou `skipped=N` correspondente). Se qualquer teste falhar/errar, use systematic-debugging ANTES de continuar — não "conserta" no improviso.

- [x] **Passo 8: verificar que não há módulo órfão na raiz**

```powershell
Get-ChildItem -Path . -Filter *.py | Select-Object Name
& .venv\Scripts\python.exe -c "import sei_insights.cli, sei_insights.utils; print('ok')"
```

Expected: lista vazia na raiz (nenhum `.py`); import dos módulos do pacote imprime `ok`.

- [x] **Passo 9: limpar `__pycache__` órfão da raiz (se existir)**

```powershell
Remove-Item -Recurse -Force __pycache__ -ErrorAction SilentlyContinue
```

Expected: sem erro (pode não existir).

- [x] **Passo 10: commit**

```powershell
git add src/sei_insights/ tests/
git commit -m "refactor: move módulos para o pacote sei_insights (src-layout)"
```

(`git mv` já encenou renames/deleções; `git add` dos dois diretórios encena as edições de imports. Não usar `-A`.)

**Deliverable:** todos os módulos em `src/sei_insights/`, testes verdes idênticos à baseline, entry points prontos.

---

### Task 4: Atualizar o README

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: layout final (Tarefa 3), comandos que passam a existir (`python -m sei_insights`, `sei-insights`, pré-requisito `pip install -e .`).
- Produces: README consistente com o novo layout; zero menções a `python main.py`.

- [x] **Passo 1: tabela "Estrutura do projeto" (linhas ~152-170)**

Substitua a tabela atual pela seguinte (alinhada ao src-layout):

```
| Arquivo / pasta              | Função                                                          |
| ---------------------------- | --------------------------------------------------------------- |
| `pyproject.toml`             | Metadados do pacote e comando `sei-insights` (deps via `requirements.txt`). |
| `src/sei_insights/cli.py`    | CLI e orquestração (argumentos, `build_rows`, espelho).         |
| `src/sei_insights/sei_client.py` | Cliente da Pesquisa Pública (pesquisa, processo, CAPTCHA, download). |
| `src/sei_insights/discovery.py`  | Parsing da resposta AJAX, paginação, dedupe.                |
| `src/sei_insights/tree.py`       | Leitura da árvore de documentos, correlação nó → URL, último Despacho. |
| `src/sei_insights/text_ing.py`   | Extração de texto de PDF via `pypdf`.                       |
| `src/sei_insights/rules.py`      | Motor de regras determinístico (lê `regras.json`).          |
| `regras.json`                    | Lista ordenada de regras de classificação (editável).       |
| `src/sei_insights/store.py`      | Espelho SQLite da planilha (`MirrorStore`).                 |
| `src/sei_insights/report.py`     | Geração da planilha XLSX (abas principal, Novos, Resumo).   |
| `src/sei_insights/captcha_solver.py` | Resolução de CAPTCHA por OCR (`ddddocr`), com retry.    |
| `src/sei_insights/rate_limit.py`    | Pausa aleatória entre requisições (2–5s, configurável).  |
| `src/sei_insights/utils.py`         | Apoio: normalização de número, SHA-256, MIME, nomes seguros. |
| `requirements.txt`            | Dependências Python do projeto (fonte única).                  |
| `tests/`                      | Testes automatizados (`unittest`).                              |
| `.state/`                     | Banco SQLite espelho + diagnósticos (gerado).                   |
```

- [x] **Passo 2: seções de instalação (Windows/Linux/macOS, linhas ~222-316)**

Logo **após** cada bloco `pip install -r requirements.txt` (linhas 225, 269, 308), acrescente o passo "instale o pacote em modo editável (habilita os comandos `sei-insights` e `python -m sei_insights`)":

```bash
pip install -e .
```

Nos três blocos de código (powershell/bash), adicione a linha correspondente em sintaxe compatível com o shell de cada aba:
- `pip install -e .` (funciona nos três shells).

- [x] **Passo 3: seção "Executando o programa" (linhas ~335-341)**

Substitua o bloco:

```bash
python main.py
```

por:

```bash
python -m sei_insights
```

E na frase introdutória ("Na pasta do projeto, com o ambiente virtual ativado:"), acrescente: "(o comando `sei-insights` é equivalente e também está disponível após `pip install -e .`; sem o install, `python -m sei_insights` falha com `ModuleNotFoundError`)."

- [x] **Passo 4: bloco "Exemplos de uso" (linhas ~364-382)**

Substitua cada ocorrência de `python main.py` por `python -m sei_insights`, mantendo os argumentos idênticos. As 6 linhas viram:

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

- [x] **Passo 5: seção "Como limpar os dados" (linhas ~574-605)**

- Linha 575: `python main.py --force` → `python -m sei_insights --force`
- Linha 604 (texto): "execute `python main.py` novamente" → "execute `python -m sei_insights` novamente"

- [x] **Passo 6: seção "Testes" (linhas ~681-694)**

Substitua a seção inteira por:

```
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
```

- [x] **Passo 7: verificar que não sobraram referências a `python main.py`**

```powershell
Select-String -Path README.md -Pattern 'python main\.py'
```

Expected: nenhum resultado.

- [x] **Passo 8: commit**

```powershell
git add README.md
git commit -m "docs: atualiza README para src-layout (comandos python -m sei_insights)"
```

**Deliverable:** README sem referências a `main.py`, com tabela e comandos do novo layout.

---

### Task 5: Verificação final

**Files:** nenhum (somente checagens).

**Interfaces:**
- Consumes: repo reorganizado (Tarefas 2-4), baseline (Tarefa 1).

- [x] **Passo 1: suíte final idêntica à baseline**

```powershell
& .venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: mesma tally da Tarefa 1.

- [x] **Passo 2: smoke test dos entry points (venv, da raiz)**

```powershell
& .venv\Scripts\python.exe -m sei_insights --help
& .venv\Scripts\sei-insights.exe --help
```

Expected: ambos imprimem o help do argparse (com as mesmas opções de `--orgao` a `--saida`). Observação cosmética aceita: `usage:` pode exibir `__main__.py`/`sei-insights` como prog.

- [x] **Passo 3: `git status` limpo e módulos da raiz removidos**

```powershell
git status --short
Get-ChildItem -Path . -Filter *.py | Select-Object Name
```

Expected:
- `git status` mostra apenas alterações esperadas do branch (NUNCA `*.egg-info/`, `build/`, `dist/`, `.worktrees/`, nem deleções `SEI_ColaboraGov_handoff_context.*`);
- nenhum `.py` na raiz;
- `src/sei_insights/` com os 13 arquivos `__init__.py`, `__main__.py`, `cli.py`, `sei_client.py`, `discovery.py`, `tree.py`, `text_ing.py`, `rules.py`, `store.py`, `report.py`, `captcha_solver.py`, `rate_limit.py`, `utils.py`.

- [x] **Passo 4: diff de lógica — corpos intactos**

```powershell
git diff --find-renames -M --name-status 4879249..HEAD
git diff --find-renames -M 4879249..HEAD -- 'src/sei_insights/cli.py'
```

Expected: o primeiro comando lista os 11 módulos como renames — **`R100`** para `sei_client.py`, `discovery.py`, `tree.py`, `text_ing.py`, `rules.py`, `store.py`, `report.py`, `captcha_solver.py`, `rate_limit.py`, `utils.py` (conteúdo idêntico: 100% similarity) e **`R`** com modificação apenas para `cli.py` (antigo `main.py`). O segundo comando mostra em `cli.py` unicamente: mudança dos imports (prefixo `sei_insights.`) e remoção do bloco `if __name__ == "__main__"` + `import sys`. Nenhum outro diff de conteúdo nos módulos.

- [x] **Passo 5: resumo final**

Apresente: renames efetuados, tally da suíte = baseline, smoke ok, `git status` limpo. Não faça merge/push (fora do escopo).

**Deliverable:** reorganização verificada ponta-a-ponta, pronta para revisão de branch.