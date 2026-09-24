# Especificação — Pacotes por função em `sei_insights`

Data: 2026-09-24. Estado do repositório: reorg src-layout concluída (branch `feat/sei-insights-tasks-1-7`, HEAD `589c7cf`); pacote plano em `src/sei_insights/`.

## 1. Objetivo

Organizar os 11 módulos de `src/sei_insights/` em **subpacotes por função** (a bagunça dos arquivos jogados na raiz do pacote). Mudança é **estrutural + refatoração leve**: módulos ganham pasta e imports são reescritos; além disso, um módulo novo de configuração (`config/__init__.py`) centraliza constantes hoje espalhadas, e dois módulos são renomeados para evitar `pacote.modulo` com o mesmo nome. **Sem mudança de comportamento**: nenhuma lógica de função/constante/símbolo alterada; suíte permanece idêntica à baseline (58 testes, OK).

## 2. Escopo acordado (brainstorm)

- **Abordagem 1**: pacotes por fronteira externa — config/, clients/, documents/, storage/, utils/.
- **Refatoração leve permitida**: extrair constantes para `config/__init__.py` e consultá-las de `cli.py` e `sei_client.py`.
- **Renomear para não repetir nome**: `utils/utils.py` → `utils/helpers.py`; `storage/store.py` → `storage/mirror.py`.

## 3. Árvore de destino

```
src/sei_insights/
  __init__.py            # __version__ = "0.1.0" (inalterado)
  __main__.py            # inalterado
  cli.py                 # entry point, na raiz (inalterado em posição)
  config/
    __init__.py          # NOVO: constantes/settings (não vazio)
    rules.py             # (ex rules.py)
  clients/
    __init__.py          # vazio
    sei_client.py        # (ex sei_client.py)
    discovery.py         # (ex discovery.py)
    rate_limit.py        # (ex rate_limit.py)
    captcha_solver.py    # (ex captcha_solver.py)
  documents/
    __init__.py          # vazio
    tree.py              # (ex tree.py)
    text_ing.py          # (ex text_ing.py)
  storage/
    __init__.py          # vazio
    mirror.py            # (ex store.py — RENOMEADO)
    report.py            # (ex report.py)
  utils/
    __init__.py          # vazio
    helpers.py           # (ex utils.py — RENOMEADO)
```

`packages.find` (`where = ["src"]`) já em `pyproject.toml` descobre os subpacotes automaticamente — **`pyproject.toml` não muda**.

## 4. Novo módulo `config/__init__.py`

Conteúdo exato (constantes copiadas, valores idênticos aos atuais):

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

Origem de cada constante:
- `STATE_DIR`, `DATABASE_PATH` — era `cli.py:18-19` (e `STATE_DIR.mkdir(...)` em `main()` continua usando a constante importada).
- `REGRAS_JSON` — substitui o literal `Path("regras.json")` em `cli.py:124`.
- `DEFAULT_ORGAO/UNIDADE/DIAS/MIN_DELAY/MAX_DELAY/SAIDA` — eram os `default=` literais de `parse_arguments` (`cli.py:28-37`).
- `DEFAULT_TIMEOUT_MS` — era `sei_client.py:20`.

**Permanecem locais** em `clients/sei_client.py` (fora do escopo acordado): `BASE_URL`, `PUBLIC_SEARCH_URL`, `SEARCH_PAGE_SIZE`, `MAX_RETRIES`, `SEARCH_RESULT_DELAY_MS`.

## 5. Mudanças nos módulos

Só imports; **nada de lógica**. Regra: `from sei_insights.X import ...` → `from sei_insights.<pacote>.X import ...`, com os 2 renames mapeados.

### `cli.py` (raiz)
- Remover linhas `STATE_DIR = Path(".state")` e `DATABASE_PATH = STATE_DIR / "sei_insights.sqlite3"`.
- **Import novo no topo**: `from sei_insights.config import STATE_DIR, DATABASE_PATH, REGRAS_JSON, DEFAULT_ORGAO, DEFAULT_UNIDADE, DEFAULT_DIAS, DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY, DEFAULT_SAIDA`.
- Topo, trocar:
  - `from sei_insights.report import ...` → `from sei_insights.storage.report import build_resumo, write_spreadsheet`
  - `from sei_insights.sei_client import ProcessResult, SeiClient` → `from sei_insights.clients.sei_client import ProcessResult, SeiClient`
  - `from sei_insights.store import MirrorStore, ProcessRow` → `from sei_insights.storage.mirror import MirrorStore, ProcessRow`
- `parse_arguments`: substituir cada `default=` literal pela constante do config (`default=DEFAULT_ORGAO`, etc.).
- Dentro de `main()`:
  - `from sei_insights.discovery import expected_total, pagination_params, parse_response  # noqa: F401` → `from sei_insights.clients.discovery import ...`
  - `from sei_insights.rate_limit import RateLimiter` → `from sei_insights.clients.rate_limit import RateLimiter`
  - `from sei_insights.rules import RulesEngine` → `from sei_insights.config.rules import RulesEngine`
  - `from sei_insights.sei_client import (  # noqa: F401` → `from sei_insights.clients.sei_client import (  # noqa: F401` (a linha `ProcessResult, SeiClient)` continua igual)
  - `from sei_insights.text_ing import extract_text_from_pdf` → `from sei_insights.documents.text_ing import extract_text_from_pdf`
  - `from sei_insights.tree import correlate_urls, parse_tree, select_last_despacho` → `from sei_insights.documents.tree import ...`
  - `from sei_insights.utils import normalize_process_number  # noqa: F401` → `from sei_insights.utils.helpers import normalize_process_number  # noqa: F401`
- `RulesEngine.from_file(Path("regras.json"))` → `RulesEngine.from_file(REGRAS_JSON)`.
- `from pathlib import Path` permanece (ainda há `Path(args.saida)`).

### `clients/sei_client.py`
- `from sei_insights.discovery import expected_total, pagination_params, parse_response` → `from sei_insights.clients.discovery import ...`
- `from sei_insights.rate_limit import RateLimiter` → `from sei_insights.clients.rate_limit import RateLimiter`
- `from sei_insights.utils import normalize_process_number, safe_filename, calculate_sha256, extension_from_content_type, looks_like_html, unique_path` → `from sei_insights.utils.helpers import normalize_process_number, safe_filename, calculate_sha256, extension_from_content_type, looks_like_html, unique_path`
- Remover `DEFAULT_TIMEOUT_MS = 90_000`; adicionar (junto ao bloco de imports do topo) `from sei_insights.config import DEFAULT_TIMEOUT_MS`.

### `clients/discovery.py`
- `from sei_insights.utils import normalize_process_number` → `from sei_insights.utils.helpers import normalize_process_number`

### `storage/report.py`
- `from sei_insights.store import FIELDS, ProcessRow` → `from sei_insights.storage.mirror import FIELDS, ProcessRow`

### Sem imports internos (conteúdo intocado)
- `config/rules.py`, `clients/rate_limit.py`, `clients/captcha_solver.py`, `documents/tree.py`, `documents/text_ing.py`, `utils/helpers.py` (ex `utils.py` — conteúdo byte-idêntico, mantém shebang/header).

## 6. Mocks de teste (strings)

- `tests/test_captcha_solver.py`: 4 ocorrências de `'sei_insights.captcha_solver.CaptchaSolver.solve_from_base64'` → `'sei_insights.clients.captcha_solver.CaptchaSolver.solve_from_base64'` (replace-all).
- `tests/test_rate_limit.py`: trocar o prefixo `sei_insights.rate_limit.` → `sei_insights.clients.rate_limit.` em todos os alvos (4 strings: `time.sleep` ×2, `random.uniform`, `time.monotonic`).

## 7. Imports dos testes (substituições exatas)

- `tests/test_cli.py`:
  - `from sei_insights.cli import build_rows, now_str, parse_arguments` — **inalterado** (cli permanece na raiz).
  - `from sei_insights.sei_client import ProcessResult` → `from sei_insights.clients.sei_client import ProcessResult`
  - `from sei_insights.store import ProcessRow` → `from sei_insights.storage.mirror import ProcessRow`
  - (dentro de `EmptyResultTest.test_calcula_resumo_vazio_sem_erro`): `from sei_insights.report import build_resumo` → `from sei_insights.storage.report import build_resumo`
- `tests/test_sei_client.py`: `from sei_insights.sei_client import SeiClient, extract_process` → `from sei_insights.clients.sei_client import SeiClient, extract_process`
- `tests/test_discovery.py`: → `from sei_insights.clients.discovery import expected_total, pagination_params, parse_response`
- `tests/test_tree.py`: → `from sei_insights.documents.tree import correlate_urls, parse_tree, select_last_despacho`
- `tests/test_rules.py`: `from sei_insights.rules import RulesEngine` → `from sei_insights.config.rules import RulesEngine`
- `tests/test_store.py`: `from sei_insights.store import MirrorStore, ProcessRow, despacho_hash` → `from sei_insights.storage.mirror import MirrorStore, ProcessRow, despacho_hash`
- `tests/test_report.py`:
  - `from sei_insights.report import build_resumo, write_spreadsheet` → `from sei_insights.storage.report import ...`
  - `from sei_insights.store import ProcessRow` → `from sei_insights.storage.mirror import ProcessRow`
- `tests/test_text_ing.py`: → `from sei_insights.documents.text_ing import extract_text_from_pdf`
- `tests/test_utils.py`: `from sei_insights.utils import (` → `from sei_insights.utils.helpers import (` (lista multi-linha dos 6 nomes continua igual)
- `tests/test_captcha_solver.py`: `from sei_insights.captcha_solver import CaptchaSolver` → `from sei_insights.clients.captcha_solver import CaptchaSolver` (+ mocks da §6)
- `tests/test_rate_limit.py`: `from sei_insights.rate_limit import RateLimiter` → `from sei_insights.clients.rate_limit import RateLimiter` (+ mocks da §6)

## 8. README

Atualizar a tabela "Estrutura do projeto": linhas dos módulos passam a refletir os subpacotes, incluindo `config/` (configuração/regras) e os renames `utils/helpers.py` e `storage/mirror.py`. Não há menção a `python main.py` para corrigir (já zerado). Seções de instalação/execução/testes permanecem válidas (entry points inalterados; exemplos `python -m unittest tests.test_*` referem módulos de testes, cujos nomes não mudam).

## 9. Restrictions e invariantes

- **Zero mudança de comportamento**: corpos intactos; única diferença = imports, remoção das constantes movidas, e os 2 renames de arquivo. Símbolos públicos inalterados: `MirrorStore`, `FIELDS`, `ProcessRow`, `despacho_hash`, `RulesEngine`, `SeiClient`, `ProcessResult`, `extract_process`, `build_rows`, `now_str`, `parse_arguments`, `main`, `RateLimiter`, `CaptchaSolver`, `build_resumo`, `write_spreadsheet`, `expected_total`, `pagination_params`, `parse_response`, `correlate_urls`, `parse_tree`, `select_last_despacho`, `extract_text_from_pdf`, `normalize_process_number`, `safe_filename`, `calculate_sha256`, `extension_from_content_type`, `looks_like_html`, `unique_path`.
- **`regras.json` e `.state/` permanecem na raiz** do repo, resolução CWD-relativa. Testes rodam SEMPRE da raiz.
- **Entry points**: `python -m sei_insights` e comando `sei-insights` (via `[project.scripts] sei_insights.cli:main`) **inalterados**.
- **`pyproject.toml` e `.gitignore` inalterados** (packages.find já cobre subpacotes; egg-info já ignorado).
- **Staging**: NUNCA `git add -A`/`-u .` (re-encenariam `SEI_ColaboraGov_handoff_context.*` deletados e `.worktrees/`). Usar `git mv` para os 11 módulos (2 com rename) e `git add` direcionado para novos módulos (`config/__init__.py`, `*/__init__.py` novos).
- **Baseline**: suíte deve permanecer idêntica (58 testes, OK; `Ran 58 tests`, 0 skip). Commando canônico: `& .venv\Scripts\python.exe -m unittest discover -s tests -v` da raiz.

## 10. Critérios de aceite

1. `src/sei_insights/` com as 5 subpastas e `cli.py`/`__main__.py`/`__init__.py` na raiz; nenhum `.py` órfão de módulo solto (exceto os 3 da raiz).
2. Nenhum import resolvendo módulo via caminho antigo — dois greps, ambos vazios (em `src\sei_insights\*.py`, subpastas e `tests\*.py`):
   - imports de módulo legados no formato plano (nome do módulo logo após `sei_insights.`):
     `^\s*from sei_insights\.(utils|store|rules|report|sei_client|discovery|rate_limit|captcha_solver|tree|text_ing) import`
     — casa `from sei_insights.utils import ...` e `from sei_insights.sei_client import ...` (antigos); NÃO casa `from sei_insights.utils.helpers import ...` (entre `sei_insights.` e `utils` vem `.`) nem `from sei_insights.clients.sei_client import ...` (o segmento após `sei_insights.` é `clients`, não o nome do módulo). Como todo caminho novo insere o pacote entre `sei_insights.` e o módulo, o padrão contíguo antigo jamais reaparece.
   - strings de mock legadas:
     `sei_insights\.(rate_limit|captcha_solver)\.`
3. Suíte idêntica à baseline (58 testes, OK).
4. Smoke: `python -m sei_insights --help` e `sei-insights.exe --help` funcionam.
5. `git status` sem artifacts de build; `pyproject.toml`/`.gitignore` sem diff.
6. README consistente.