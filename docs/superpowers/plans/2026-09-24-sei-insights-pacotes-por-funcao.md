# Pacotes por função em sei_insights — Plano de Implementação

> **Status: ✅ IMPLEMENTADO** — verificado em 24/09/2026. Todos os passos concluídos (commits `60ff919`, `4c33d0e`, `273e4be`); suíte verde (58 testes OK); subpacotes `config/`, `clients/`, `documents/`, `storage/`, `utils/` confirmados.

> **Para workers agentic:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa-a-tarefa. Passos usam caixa de seleção (`- [ ]`) para rastreio.

**Goal:** Organizar os 11 módulos de `src/sei_insights/` (hoje planos) em subpacotes por função — `config/`, `clients/`, `documents/`, `storage/`, `utils/` — sem mudança de comportamento e com suíte idêntica à baseline (58 testes, OK).

**Architecture:** Módulos de hoje migram para 5 subpacotes (2 renomeados: `utils.py`→`utils/helpers.py`, `store.py`→`storage/mirror.py`). Um módulo novo `config/__init__.py` centraliza constantes hoje espalhadas em `cli.py`/`sei_client.py`. Entry points (`cli.py`, `__main__.py`, console script `sei-insights`) ficam na raiz e não mudam; `pyproject.toml`/`.gitignore` não mudam (`packages.find where=["src"]` já descobre subpacotes).

**Tech Stack:** Python (>=3.10), unittest (stdlib), setuptools (src-layout, PEP 660 editable), Windows/PowerShell.

**Spec:** `docs/superpowers/specs/2026-09-24-sei-insights-pacotes-por-funcao-design.md`

## Global Constraints

Corrige de cópia, uma linha cada — valem para todas as tarefas:

- **Zero mudança de comportamento**: corpos intactos; a única diferença é imports, remoção das constantes movidas para `config`, e os 2 renames de arquivo. Símbolos públicos inalterados: `MirrorStore`, `FIELDS`, `ProcessRow`, `despacho_hash`, `RulesEngine`, `SeiClient`, `ProcessResult`, `extract_process`, `build_rows`, `now_str`, `parse_arguments`, `main`, `RateLimiter`, `CaptchaSolver`, `build_resumo`, `write_spreadsheet`, `expected_total`, `pagination_params`, `parse_response`, `correlate_urls`, `parse_tree`, `select_last_despacho`, `extract_text_from_pdf`, `normalize_process_number`, `safe_filename`, `calculate_sha256`, `extension_from_content_type`, `looks_like_html`, `unique_path`.
- **Módulos sem imports internos ficam byte-idênticos**: `config/rules.py`, `clients/rate_limit.py`, `clients/captcha_solver.py`, `documents/tree.py`, `documents/text_ing.py`, `utils/helpers.py` (preserva shebang/header/docstring de `utils.py`).
- **`regras.json` e `.state/` permanecem na raiz**, resolução CWD-relativa. **Testes rodam SEMPRE da raiz do repositório**.
- **Entry points inalterados**: `python -m sei_insights` e comando `sei-insights` (via `[project.scripts] sei_insights.cli:main`). **`pyproject.toml` e `.gitignore` inalterados**.
- **Nunca criar `utils/` antes da Tarefa 2**: package `sei_insights.utils` e módulo plano `sei_insights/utils.py` colidem no import (o pacote vence) — criado junto com o `git mv`.
- **Baseline**: suíte idêntica (58 testes, OK, 0 skip). Comando canônico: `& .venv\Scripts\python.exe -m unittest discover -s tests -v` da raiz.
- **Staging**: NUNCA `git add -A` nem `git add -u .` (re-encenariam `SEI_ColaboraGov_handoff_context.*` deletados e `.worktrees/` untracked). Use `git mv` para movimentos e `git add <caminho>` direcionado para novos/modificados.
- **Ambiente**: Windows; venv em `.venv` (Python 3.14.7); invoke o Python do venv como `& .venv\Scripts\python.exe`. Deps provisionadas e baseline da Tarefa 1 do plano anterior registrada em `C:\Users\WERMES~1.SIL\AppData\Local\Temp\opencode\sei-insights-baseline.txt` (58 passed / 0 skipped / 0 failed / 0 errors).

## Review Focus

Classes de entrada/modas de falha que a spec implica e que nenhum teste unitário novo cobre; cada linha é exercitada na tarefa/passo indicado:

1. **Renames órfãos** (`store`→`storage/mirror`, `utils`→`utils/helpers`) sem atualizar consumers — import antigo em módulo ou teste → `ModuleNotFoundError`. → Tarefa 2 (greps) e Tarefa 3 (grep final).
2. **Subpacote/config não descoberto pelo install editável** — `from sei_insights.config import ...` falha. → Tarefa 1, passo de verificação de import.
3. **Mock com string antiga** — `patch('sei_insights.rate_limit...')`/`'sei_insights.captcha_solver...'` deixa de atingir o alvo (teste passaria com comportamento errado). → Tarefa 2 (substituição exata; exercitada pelo próprio board de patches da suíte).
4. **Conflito de nome `utils`** — criar `utils/__init__.py` antes de mover `utils.py` quebra `from sei_insights.utils import ...` em cli/tests (pacote vence módulo plano). → Tarefa 2 cria `utils/` junto com o `git mv`, nunca antes.
5. **README com caminhos antigos** — tabela apontando `src/sei_insights/utils.py`/`store.py`. → Tarefa 3 (grep + tabela nova).
6. **Staging amplo** — `git add -A` re-encenaria `SEI_ColaboraGov_handoff_context.*` e `.worktrees/`. → Restrições globais; todas as tarefas usam `git mv` + `git add` direcionado.

---

### Task 1: Módulo de configuração e esqueleto dos subpacotes

**Files:**
- Create: `src/sei_insights/config/__init__.py` (constantes/settings)
- Create: `src/sei_insights/clients/__init__.py` (vazio)
- Create: `src/sei_insights/documents/__init__.py` (vazio)
- Create: `src/sei_insights/storage/__init__.py` (vazio)

`src/sei_insights/utils/__init__.py` **NÃO** é criado nesta tarefa (viria a colidir com `utils.py` ainda na raiz do pacote — véem restrição global).

**Interfaces:**
- Consumes: venv com install editável da reorg anterior (baseline 58 testes OK).
- Produces: `sei_insights.config` importável expondo as constantes `STATE_DIR`, `DATABASE_PATH`, `REGRAS_JSON`, `DEFAULT_ORGAO`, `DEFAULT_UNIDADE`, `DEFAULT_DIAS`, `DEFAULT_MIN_DELAY`, `DEFAULT_MAX_DELAY`, `DEFAULT_SAIDA`, `DEFAULT_TIMEOUT_MS`; dirs `clients/`, `documents/`, `storage/` presentes (consumidos pela Tarefa 2). Suite continua 58/OK (nada consumidor mudou ainda).

- [x] **Passo 1: criar `src/sei_insights/config/__init__.py`**

Conteúdo exato:

```python
from pathlib import Path

STATE_DIR = Path(".state")
DATABASE_PATH = STATE_DIR / "sei_insights.sqlite3"
REGRAS_JSON = Path("regras.json")

DEFAULT_ORGAO = "MMulheres"
DEFAULT_UNIDADE = "MMULHERES-SE-SGA-CGATI-CTI-DTI"
DEFAULT_DIAS = 7
DEFAULT_MIN_DELAY = 2.0
DEFAULT_MAX_DELAY = 5.0
DEFAULT_SAIDA = "sei_insights.xlsx"

DEFAULT_TIMEOUT_MS = 90_000
```

- [x] **Passo 2: criar os 3 `__init__.py` vazios**

Crie `src/sei_insights/clients/__init__.py`, `src/sei_insights/documents/__init__.py` e `src/sei_insights/storage/__init__.py`, cada um com conteúdo vazio (0 bytes).

- [x] **Passo 3: verificar que o config importa e a suíte segue verde**

```powershell
& .venv\Scripts\python.exe -c "from sei_insights.config import STATE_DIR, DATABASE_PATH, REGRAS_JSON, DEFAULT_ORGAO, DEFAULT_UNIDADE, DEFAULT_DIAS, DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY, DEFAULT_SAIDA, DEFAULT_TIMEOUT_MS; print(STATE_DIR, DATABASE_PATH, REGRAS_JSON, DEFAULT_DIAS, DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY, DEFAULT_SAIDA, DEFAULT_TIMEOUT_MS)"
& .venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: o import imprime os valores (`.state .state\sei_insights.sqlite3 regras.json 7 2.0 5.0 sei_insights.xlsx 90000` em algum formato equivalente) e a suíte termina com `Ran 58 tests` + `OK`.

Se `import sei_insights.config` falhar com `ModuleNotFoundError` (install editável não enxergando subpacote), rode `& .venv\Scripts\python.exe -m pip install -e .` e repita a verificação — é o remedo esperado; se ainda falhar, PARE e reporte BLOCKED.

- [x] **Passo 4: commit**

```powershell
git add src/sei_insights/config/__init__.py src/sei_insights/clients/__init__.py src/sei_insights/documents/__init__.py src/sei_insights/storage/__init__.py
git commit -m "feat: módulo de configuração central e esqueleto dos subpacotes"
```

**Deliverable:** `sei_insights.config` importável com todos os valores corretos; suíte inalterada (58/OK).

---

### Task 2: Mover módulos para os subpacotes e reescrever imports (pacote + testes)

**Files:**
- Move: `sei_client.py`, `discovery.py`, `rate_limit.py`, `captcha_solver.py` → `src/sei_insights/clients/`; `tree.py`, `text_ing.py` → `src/sei_insights/documents/`; `report.py` → `src/sei_insights/storage/`; `rules.py` → `src/sei_insights/config/`
- Rename: `store.py` → `src/sei_insights/storage/mirror.py`; `utils.py` → `src/sei_insights/utils/helpers.py`
- Create: `src/sei_insights/utils/__init__.py` (vazio, criado junto com o git mv)
- Modify: `src/sei_insights/cli.py` (só imports/constantes), todos os módulos movidos (só imports nos 3 que têm) e os 11 arquivos de teste (só imports/strings)

**Interfaces:**
- Consumes: `config` da Tarefa 1; dirs `clients/`, `documents/`, `storage/` da Tarefa 1; baseline 58/OK.
- Produces: layout do §3 da spec; todos os imports internos e mocks apontando aos novos caminhos; suíte com tally **idêntica** à baseline.

- [x] **Passo 1: criar `src/sei_insights/utils/__init__.py` (vazio) e mover os 11 módulos com `git mv`**

Para evitar o conflito de nome da restrição global, o diretório `utils/` nasce nesta tarefa, junto com o movimento:

```powershell
New-Item -ItemType File -Path "src\sei_insights\utils\__init__.py" | Out-Null
git mv sei_client.py discovery.py rate_limit.py captcha_solver.py src/sei_insights/clients/
git mv tree.py text_ing.py src/sei_insights/documents/
git mv report.py src/sei_insights/storage/
git mv store.py src/sei_insights/storage/mirror.py
git mv utils.py src/sei_insights/utils/helpers.py
git mv rules.py src/sei_insights/config/
```

Expected: `git status` mostra os 11 renames (2 com caminho final diferente do plano) e `?? src/sei_insights/utils/__init__.py`.

- [x] **Passo 2: reescrever imports nos 3 módulos movidos com imports internos**

Aplicar as substituições EXATAS de linha:

- `src/sei_insights/clients/sei_client.py`:
  - `from sei_insights.discovery import expected_total, pagination_params, parse_response` → `from sei_insights.clients.discovery import expected_total, pagination_params, parse_response`
  - `from sei_insights.rate_limit import RateLimiter` → `from sei_insights.clients.rate_limit import RateLimiter`
  - `from sei_insights.utils import normalize_process_number, safe_filename, calculate_sha256, extension_from_content_type, looks_like_html, unique_path` → `from sei_insights.utils.helpers import normalize_process_number, safe_filename, calculate_sha256, extension_from_content_type, looks_like_html, unique_path`
  - Remover a linha `DEFAULT_TIMEOUT_MS = 90_000` e adicionar, junto ao bloco de imports do topo (logo após `from bs4 import BeautifulSoup`), a linha `from sei_insights.config import DEFAULT_TIMEOUT_MS`.
- `src/sei_insights/clients/discovery.py`:
  - `from sei_insights.utils import normalize_process_number` → `from sei_insights.utils.helpers import normalize_process_number`
- `src/sei_insights/storage/report.py`:
  - `from sei_insights.store import FIELDS, ProcessRow` → `from sei_insights.storage.mirror import FIELDS, ProcessRow`

`src/sei_insights/config/rules.py`, `clients/rate_limit.py`, `clients/captcha_solver.py`, `documents/tree.py`, `documents/text_ing.py`, `utils/helpers.py`: **nenhum import interno — conteúdo byte-idêntico** (não editar nada).

- [x] **Passo 3: reescrever `src/sei_insights/cli.py`**

Substituições EXATAS:

- Topo, no bloco de imports do pacote:
  - `from sei_insights.report import build_resumo, write_spreadsheet` → `from sei_insights.storage.report import build_resumo, write_spreadsheet`
  - `from sei_insights.sei_client import ProcessResult, SeiClient` → `from sei_insights.clients.sei_client import ProcessResult, SeiClient`
  - `from sei_insights.store import MirrorStore, ProcessRow` → `from sei_insights.storage.mirror import MirrorStore, ProcessRow`
- Remover as duas linhas das constantes:
  - `STATE_DIR = Path(".state")`
  - `DATABASE_PATH = STATE_DIR / "sei_insights.sqlite3"`
  e adicionar no bloco de imports do topo (após o bloco de imports do pacote acima):
  - `from sei_insights.config import STATE_DIR, DATABASE_PATH, REGRAS_JSON, DEFAULT_ORGAO, DEFAULT_UNIDADE, DEFAULT_DIAS, DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY, DEFAULT_SAIDA`
- `parse_arguments` — trocar os `default=` literais pelos nomes:
  - `default="MMulheres"` → `default=DEFAULT_ORGAO`
  - `default="MMULHERES-SE-SGA-CGATI-CTI-DTI"` → `default=DEFAULT_UNIDADE`
  - `type=int, default=7` → `type=int, default=DEFAULT_DIAS`
  - `type=float, default=2.0` → `type=float, default=DEFAULT_MIN_DELAY`
  - `type=float, default=5.0` → `type=float, default=DEFAULT_MAX_DELAY`
  - `default="sei_insights.xlsx"` → `default=DEFAULT_SAIDA`
- Dentro de `main()`, bloco de imports:
  - `from sei_insights.discovery import expected_total, pagination_params, parse_response  # noqa: F401` → `from sei_insights.clients.discovery import expected_total, pagination_params, parse_response  # noqa: F401`
  - `from sei_insights.rate_limit import RateLimiter` → `from sei_insights.clients.rate_limit import RateLimiter`
  - `from sei_insights.rules import RulesEngine` → `from sei_insights.config.rules import RulesEngine`
  - `from sei_insights.sei_client import (  # noqa: F401` → `from sei_insights.clients.sei_client import (  # noqa: F401` (a linha de baixo `ProcessResult, SeiClient)` continua igual)
  - `from sei_insights.text_ing import extract_text_from_pdf` → `from sei_insights.documents.text_ing import extract_text_from_pdf`
  - `from sei_insights.tree import correlate_urls, parse_tree, select_last_despacho` → `from sei_insights.documents.tree import correlate_urls, parse_tree, select_last_despacho`
  - `from sei_insights.utils import normalize_process_number  # noqa: F401` → `from sei_insights.utils.helpers import normalize_process_number  # noqa: F401`
- `rules = RulesEngine.from_file(Path("regras.json"))` → `rules = RulesEngine.from_file(REGRAS_JSON)`

`from pathlib import Path` permanece (ainda há `Path(args.saida)`).

- [x] **Passo 4: reescrever imports e mocks nos testes** (substituições EXATAS por arquivo)

- `tests/test_cli.py`:
  - `from sei_insights.cli import build_rows, now_str, parse_arguments` — **inalterado**.
  - `from sei_insights.sei_client import ProcessResult` → `from sei_insights.clients.sei_client import ProcessResult`
  - `from sei_insights.store import ProcessRow` → `from sei_insights.storage.mirror import ProcessRow`
  - (linha 110, dentro de `EmptyResultTest.test_calcula_resumo_vazio_sem_erro`): `from sei_insights.report import build_resumo` → `from sei_insights.storage.report import build_resumo`
- `tests/test_sei_client.py`:
  - `from sei_insights.sei_client import SeiClient, extract_process  # extract_process is a module function below` → `from sei_insights.clients.sei_client import SeiClient, extract_process  # extract_process is a module function below`
- `tests/test_discovery.py`:
  - `from sei_insights.discovery import expected_total, pagination_params, parse_response` → `from sei_insights.clients.discovery import expected_total, pagination_params, parse_response`
- `tests/test_tree.py`:
  - `from sei_insights.tree import correlate_urls, parse_tree, select_last_despacho` → `from sei_insights.documents.tree import correlate_urls, parse_tree, select_last_despacho`
- `tests/test_rules.py`:
  - `from sei_insights.rules import RulesEngine` → `from sei_insights.config.rules import RulesEngine`
- `tests/test_store.py`:
  - `from sei_insights.store import MirrorStore, ProcessRow, despacho_hash` → `from sei_insights.storage.mirror import MirrorStore, ProcessRow, despacho_hash`
- `tests/test_report.py`:
  - `from sei_insights.report import build_resumo, write_spreadsheet` → `from sei_insights.storage.report import build_resumo, write_spreadsheet`
  - `from sei_insights.store import ProcessRow` → `from sei_insights.storage.mirror import ProcessRow`
- `tests/test_text_ing.py`:
  - `from sei_insights.text_ing import extract_text_from_pdf` → `from sei_insights.documents.text_ing import extract_text_from_pdf`
- `tests/test_utils.py`:
  - `from sei_insights.utils import (` → `from sei_insights.utils.helpers import (` (a lista multi-linha dos 6 nomes continua igual)
- `tests/test_captcha_solver.py`:
  - `from sei_insights.captcha_solver import CaptchaSolver` → `from sei_insights.clients.captcha_solver import CaptchaSolver`
  - Substitua **todas as 4 ocorrências** de `sei_insights.captcha_solver.CaptchaSolver.solve_from_base64` por `sei_insights.clients.captcha_solver.CaptchaSolver.solve_from_base64` (use replace-all nas linhas 67, 82, 93, 108).
- `tests/test_rate_limit.py`:
  - `from sei_insights.rate_limit import RateLimiter` → `from sei_insights.clients.rate_limit import RateLimiter`
  - Substitua **todas as 4 ocorrências** da sub-string `sei_insights.rate_limit.` por `sei_insights.clients.rate_limit.` (linhas 18-20 e 32: `time.sleep` ×2, `random.uniform`, `time.monotonic` — use replace-all do prefixo).

- [x] **Passo 5: verificação — nenhum caminho antigo restante**

```powershell
Select-String -Path (Get-ChildItem -Path src\sei_insights -Recurse -Filter *.py | ForEach-Object FullName) -Pattern '^\s*from sei_insights\.(utils|store|rules|report|sei_client|discovery|rate_limit|captcha_solver|tree|text_ing) import'
Select-String -Path tests\test_*.py -Pattern '^\s*from sei_insights\.(utils|store|rules|report|sei_client|discovery|rate_limit|captcha_solver|tree|text_ing) import'
Select-String -Path (Get-ChildItem -Path src\sei_insights -Recurse -Filter *.py | ForEach-Object FullName), tests\test_*.py -Pattern 'sei_insights\.(rate_limit|captcha_solver)\.'
```

Expected: os três comandos sem resultado (vazio). (O `^(...) import` exige o nome do módulo logo após `sei_insights.`; caminhos novos inserem o pacote entre ambos e não casam.)

- [x] **Passo 6: rodar a suíte completa e comparar com a baseline**

```powershell
& .venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: tally **idêntica** à baseline (`Ran 58 tests`, `OK`, 58 passed / 0 skipped / 0 failed / 0 errors). Se qualquer teste falhar/errar, use systematic-debugging ANTES de continuar — não "conserta" no improviso.

- [x] **Passo 7: verificar layout final (sem módulo órfão) e smoke de imports**

```powershell
Get-ChildItem -Path src\sei_insights -Recurse -Filter *.py | ForEach-Object { $_.FullName.Replace((Get-Location).Path + '\', '') }
& .venv\Scripts\python.exe -c "import sei_insights.cli, sei_insights.config.rules, sei_insights.clients.sei_client, sei_insights.clients.discovery, sei_insights.clients.rate_limit, sei_insights.clients.captcha_solver, sei_insights.documents.tree, sei_insights.documents.text_ing, sei_insights.storage.mirror, sei_insights.storage.report, sei_insights.utils.helpers; print('ok')"
```

Expected: a lista mostra apenas arquivos em subpastas + `cli.py`, `__main__.py`, `__init__.py` na raiz de `sei_insights`; import imprime `ok`.

- [x] **Passo 8: limpar `__pycache__` órfão da raiz do pacote antiga (se existir)**

```powershell
Remove-Item -Recurse -Force src\sei_insights\__pycache__ -ErrorAction SilentlyContinue
```

Expected: sem erro (pode não existir).

- [x] **Passo 9: commit**

```powershell
git add src/sei_insights/ tests/
git commit -m "refactor: separa módulos em subpacotes por função (config, clients, documents, storage, utils)"
```

(`git mv` já encenou renames/deleções; `git add` dos dois diretórios encena o `utils/__init__.py` novo e as edições de imports. Não usar `-A`.)

**Deliverable:** layout do §3 da spec completo; suíte idêntica à baseline; entry points prontos (`python -m sei_insights`, `sei-insights`).

---

### Task 3: Atualizar o README e verificação final

**Files:**
- Modify: `README.md` (tabela "Estrutura do projeto", linhas ~154-171 — localize pelo conteúdo, não pela linha)

**Interfaces:**
- Consumes: layout final da Tarefa 2 (caminhos `sei_insights.<pacote>.<módulo>`).
- Produces: README consistente com os subpacotes; verificação final ponta-a-ponta (suíte, smoke, greps, git status).

- [x] **Passo 1: substituir a tabela "Estrutura do projeto"**

Substitua a tabela atual pela seguinte (alinhada aos subpacotes):

```
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
```

Não toque em nenhuma outra seção do README (instalação/execução/testes já estão corretos — entry points e nomes de módulos de teste não mudaram).

- [x] **Passo 2: verificar que o README está consistente**

```powershell
Select-String -Path README.md -Pattern 'sei_insights/(utils\.py|store\.py|rules\.py|report\.py|sei_client\.py|discovery\.py|rate_limit\.py|captcha_solver\.py|tree\.py|text_ing\.py)'
Select-String -Path README.md -Pattern 'python main\.py'
```

Expected: ambos sem resultado (nenhum caminho antigo na tabela nem referência legada).

- [x] **Passo 3: suíte final idêntica à baseline**

```powershell
& .venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: `Ran 58 tests`, `OK` (tally idêntica).

- [x] **Passo 4: smoke test dos entry points (venv, da raiz)**

```powershell
& .venv\Scripts\python.exe -m sei_insights --help
& .venv\Scripts\sei-insights.exe --help
```

Expected: ambos imprimem o help do argparse (privadas: `--orgao` a `--saida`). Divergência cosmética em `usage:` aceita.

- [x] **Passo 5: `git status` sem artifacts e módulos da raiz removidos**

```powershell
git status --short
Get-ChildItem -Path . -Filter *.py | Select-Object Name
```

Expected:
- `git status` mostra apenas as 3 entradas pré-existentes/intencionais (`D SEI_ColaboraGov_handoff_context.md`, `D SEI_ColaboraGov_handoff_context.txt`, `?? .worktrees/`) — NUNCA `*.egg-info/`, `build/`, `dist/`, nem nada novo além dos commits do plano;
- nenhum `.py` na raiz do repo;
- `src/sei_insights/` com: raiz (`__init__.py`, `__main__.py`, `cli.py`) + 5 subpastas (`config/`, `clients/`, `documents/`, `storage/`, `utils/`), cada uma com seu(s) módulo(s) e `__init__.py`.

- [x] **Passo 6: commit**

```powershell
git add README.md
git commit -m "docs: README reflete subpacotes por função (config, clients, documents, storage, utils)"
```

- [x] **Passo 7: resumo final**

Apresente: renames/movimentos efetuados, tally da suíte = baseline, smoke ok, greps vazios, `git status` limpo. Não faça merge/push (fora do escopo).

**Deliverable:** README consistente com os subpacotes; reorganização verificada ponta-a-ponta, pronta para revisão de branch.