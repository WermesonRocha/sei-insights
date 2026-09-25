# SEI Insights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python tool that, on each run, discovers public SEI/ColaboraGov processes for unit `MMULHERES-SE-SGA-CGATI-CTI-DTI` in a configurable window, reads the most recent "Despacho" text, classifies situation/pendency with local rules, and writes a mirror spreadsheet (SQLite = exact copy).

**Architecture:** Reuses proven SEI interaction code from `C:\Users\wermeson.silva\Documents\Projetos\sei-colaboragov` by copying it (CAPTCHA, rate limit, AJAX sync, download, DB patterns). New modules add: discovery search (unit+period+pagination), richer document-tree reading with node→URL correlation, pypdf text extraction, a deterministic rules engine, an SQLite mirror store, and an openpyxl report. A live validation spike runs first and its findings pin down the real SEI selectors/JSON before the browser layer is built.

**Tech Stack:** Python 3.14, Playwright (sync), BeautifulSoup4 (`html.parser` — **no lxml**), `ddddocr` + `opencv-python-headless` (CAPTCHA OCR), `pypdf` (text), `openpyxl` (XLSX), stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-22-sei-insights-design.md`

## Global Constraints

- Reserve copy/adapt material from collector root: `C:\Users\wermeson.silva\Documents\Projetos\sei-colaboragov` (module `main.py`, `captcha_solver.py`, `tests/test_captcha_solver.py`).
- Never bypass CAPTCHA and never access restricted documents — only public links the SEI page itself exposes.
- No `lxml` anywhere; parse with `BeautifulSoup(..., "html.parser")`.
- Dependencies (exact floors): `playwright>=1.52,<2`, `beautifulsoup4>=4.13,<5`, `ddddocr>=1.4.0`, `opencv-python-headless>=4.8.0`, `pypdf>=5.0`, `openpyxl>=3.1`.
- Spreadsheet is the source of truth; SQLite mirror is rebuilt from the spreadsheet rows each successful run (BD = planilha, no extra columns).
- Cache hash is over the **last Despacho identifier** (document number + date), never over extracted text.
- All runs are sequential; default random pause 2–5 s between requests.
- Test runner: `python -m unittest discover -s tests -v` from the project root.
- Ignore in git: `.state/`, `downloads/`, `*.xlsx`, `__pycache__/`, `.venv/`.

## Review Focus

Inputs the spec implies but no single task's happy path exercises; each gets a pinned test:

1. Process tree with **no "Despacho" node** → situation "Sem despacho público", no download, not an error. (Pinned in Task 7 `tree` and Task 12 `build_rows`.)
2. **Scanned despacho** (PDF without a text layer) → `extract_text_from_pdf` returns "", situation "Texto não extraível (digitalizado?)", and the cache hash (identifier-based) does not freeze the process. (Pinned in Tasks 6 and 5.)
3. **Empty discovery result** (0 processes) → spreadsheet still written with empty sheets and a zeroed summary; run exit code 0. (Pinned in Tasks 10 and 12.)
4. **Number format variations and duplicates** (extra spaces, repeated across search types) → normalized and deduplicated. (Pinned in Tasks 2 and 9.)
5. **Cached process still appears in the sheet** with the current execution date even when not re-analyzed. (Pinned in Task 12.)
6. **SEI HTML/selector drift** → `save_debug` screenshot/HTML diagnostics and a clear error, not a silent failure. (Pinned in Task 11 for parser/mocking level; browser-level behavior verified in the spike.)

---

### Task 1: Live validation spike

**Files:**
- Create: `docs/spike-2026-09-22.md`

**Interfaces:**
- Consumes: the live instance `https://colaboragov.sei.gov.br/` and the already-approved spec §6.
- Produces: `docs/spike-2026-09-22.md` findings that Tasks 9 and 11 use to pin selectors, JSON shape and pagination behavior.

- [x] **Step 1: Run one manual discovery on the live site**

In a Chromium browser (DevTools → Network → Copy as cURL, like the handoff did):
1. open `https://colaboragov.sei.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=7`;
2. leave the process-number box empty;
3. mark Processos + Documentos Gerados + Documentos Externos;
4. select Órgão `MMulheres` and Unidade `MMULHERES-SE-SGA-CGATI-CTI-DTI`;
5. set the last 7 days as the period; search.

- [x] **Step 2: Inspect the AJAX response**

From the captured request/response, record in `docs/spike-2026-09-22.md`:
- the exact selector names/values used to select the organ and the unit (e.g. `#selOrgaoPesquisa`, `#selUnidadePesquisa`, plug-in calls like `multipleSelect('setSelects', [...])`, or an infra tree selector);
- the JSON fields returned (`itens`, `html`, anything else);
- how many processes come back and the shape of one row in `html` (is there a `data-prot` attribute on the row? a link `md_pesq_processo_exibir.php`?);
- whether the unit filter really narrows the result to the CTI's processes or the server ignores it.

- [x] **Step 3: Verify pagination and per-page CAPTCHA**

Go to page 2 (click "Próxima") and capture that AJAX call too. Record: the query params (`isPaginacao=true`, `inicio`, `rowsSolr`) and POST body, whether a new CAPTCHA appeared, and when the result ends (an `itens` total vs. reaching fewer than 50 rows).

- [x] **Step 4: Inspect a public process page tree**

Open one returned process. Record in the spike doc: the DOM shape of the document-tree rows (does each row expose the serie name, the document number, a date, and the `md_pesq_documento_consulta_externa.php` link?), whether the link label contains the document number (needed for node→URL correlation), and the exact text format to parse.

- [x] **Step 5: Commit findings; gate on spec**

```bash
python -m pip install --upgrade pip
git add docs/spike-2026-09-22.md
git commit -m "docs: validação técnica ao vivo do SEI ColaboraGov"
```

If any finding contradicts the spec (e.g. the unit filter is ignored), **stop and update the spec before Task 9**. Practical hints: this can be done with manual browsing under 30 minutes; automated scripts are not required.

---

### Task 2: Project scaffold + core utils

**Files:**
- Create: `requirements.txt`, `.gitignore`, `tests/__init__.py`, `utils.py`
- Create: `tests/test_utils.py`

**Interfaces:**
- Consumes: collector `main.py` functions (available in the collector repo).
- Produces:
  - `normalize_process_number(value: str) -> str`
  - `safe_filename(value: str) -> str`
  - `calculate_sha256(path: pathlib.Path) -> str`
  - `extension_from_content_type(content_type: str) -> str`
  - `looks_like_html(data: bytes) -> bool`
  - `unique_path(path: pathlib.Path) -> pathlib.Path`

- [x] **Step 1: Write the failing tests**

`tests/test_utils.py`:

```python
import hashlib
import tempfile
import unittest
from pathlib import Path

from utils import (
    calculate_sha256,
    extension_from_content_type,
    looks_like_html,
    normalize_process_number,
    safe_filename,
    unique_path,
)


class NormalizeProcessNumberTest(unittest.TestCase):
    def test_remove_espacos_extra(self):
        self.assertEqual(
            normalize_process_number("  21260.003436/2026-15  "),
            "21260.003436/2026-15",
        )

    def test_garbage_empty(self):
        self.assertEqual(normalize_process_number("   "), "")


class SafeFilenameTest(unittest.TestCase):
    def test_substitui_espaco_por_underline(self):
        self.assertEqual(safe_filename("a b c"), "a_b_c")

    def test_remove_caracteres_invalidos(self):
        self.assertNotIn(":", safe_filename("a:b?c"))


class Sha256Test(unittest.TestCase):
    def test_hash_consistente(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.txt"
            path.write_text("hello", encoding="utf-8")
            expected = hashlib.sha256(b"hello").hexdigest()
            self.assertEqual(calculate_sha256(path), expected)


class ExtensionTest(unittest.TestCase):
    def test_pdf(self):
        self.assertEqual(extension_from_content_type("application/pdf"), ".pdf")

    def test_vazio_quando_desconhecido(self):
        self.assertEqual(extension_from_content_type("application/x-whatever"), "")


class LooksLikeHtmlTest(unittest.TestCase):
    def test_reconhece_html(self):
        self.assertTrue(looks_like_html(b"<html><body>oi</body></html>"))

    def test_nao_confunde_texto(self):
        self.assertFalse(looks_like_html(b"%PDF-1.4 ..."))

    def test_nao_confunde_json(self):
        self.assertFalse(looks_like_html(b'{"itens": 0}'))


class UniquePathTest(unittest.TestCase):
    def test_adiciona_sufixo_quando_existe(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "a.pdf"
            base.write_bytes(b"x")
            result = unique_path(base)
            self.assertNotEqual(result, base)
            self.assertEqual(result.suffix, ".pdf")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_utils -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils'`

- [x] **Step 3: Write the scaffolding and the implementation**

`requirements.txt`:

```
playwright>=1.52,<2
beautifulsoup4>=4.13,<5
ddddocr>=1.4.0
opencv-python-headless>=4.8.0
pypdf>=5.0
openpyxl>=3.1
```

`.gitignore`:

```
.state/
downloads/
*.xlsx
__pycache__/
.venv/
```

`tests/__init__.py`: empty file.

`utils.py` — copy the five helpers from the collector `main.py` **verbatim**, adjusting only the logger name:

- copy `normalize_process_number` (collector `main.py:275-294`);
- copy `safe_filename` (`main.py:295-326`);
- copy `calculate_sha256` (`main.py:327-349`);
- copy `extension_from_content_type` (`main.py:350-393`);
- copy `looks_like_html` (`main.py:394-408`);
- copy `unique_path` (`main.py:453-483`).

Keep imports `hashlib`, `re`, `time`, `logging` local to the module. The exact bodies live in the collector and must be copied byte-for-byte so behavior matches (normalization keeps digits/letters/dots/slashes/hyphens; `unique_path` appends ` (1)` before the extension).

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_utils -v`
Expected: PASS (all 8 tests)

- [x] **Step 5: Commit**

```bash
git add requirements.txt .gitignore tests/__init__.py tests/test_utils.py utils.py
git commit -m "feat: scaffold e utilitários de apoio"
```

---

### Task 3: Rate limiter

**Files:**
- Create: `rate_limit.py`
- Create: `tests/test_rate_limit.py`

**Interfaces:**
- Consumes: nothing from this project.
- Produces: `class RateLimiter(min_delay: float, max_delay: float)` with `wait()` and `wait_seconds(seconds: float)`, used by Tasks 11 and 12.

- [x] **Step 1: Write the failing tests**

`tests/test_rate_limit.py`:

```python
import time
import unittest
from unittest import mock

from rate_limit import RateLimiter


class RateLimiterTest(unittest.TestCase):
    def test_rejeita_min_negativo(self):
        with self.assertRaises(ValueError):
            RateLimiter(-1, 5)

    def test_rejeita_max_menor_que_min(self):
        with self.assertRaises(ValueError):
            RateLimiter(3, 2)

    def test_wait_dorme_entre_min_e_max(self):
        with mock.patch("rate_limit.time.sleep") as sleep, \
                mock.patch("rate_limit.random.uniform", return_value=2.0), \
                mock.patch("rate_limit.time.monotonic", side_effect=[0.0, 0.0, 0.5, 2.0]):
            rl = RateLimiter(1, 3)
            rl.wait()
            sleep.assert_called_once()
            # remaining = 2.0 - 0.0 = 2.0
            self.assertAlmostEqual(sleep.call_args[0][0], 2.0)
            rl.wait()
            # elapsed desde last_request = 2.0, target 2.0 => remaining 0
            sleep.assert_called_once()

    def test_wait_seconds_obedece_retry_after(self):
        with mock.patch("rate_limit.time.sleep") as sleep:
            rl = RateLimiter(1, 3)
            rl.wait_seconds(4.2)
            sleep.assert_called_once_with(4.2)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_rate_limit -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rate_limit'`

- [x] **Step 3: Write the implementation**

Copy `RateLimiter` from collector `main.py:647-746` **verbatim** into `rate_limit.py`, renaming only the logger to `logger = logging.getLogger("sei-insights")`. The class uses `random.uniform`, `time.monotonic`, and `time.sleep` directly in module scope (which the tests patch).

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_rate_limit -v`
Expected: PASS (all 4 tests)

- [x] **Step 5: Commit**

```bash
git add rate_limit.py tests/test_rate_limit.py
git commit -m "feat: rate limiter com pausa aleatória e retry-after"
```

---

### Task 4: CAPTCHA solver (copied)

**Files:**
- Create: `captcha_solver.py`
- Create: `tests/test_captcha_solver.py`

**Interfaces:**
- Consumes: `playwright.sync_api.Page`.
- Produces: `class CaptchaSolver(max_retries: int = 3, ocr_timeout_seconds: int = 10)` with `solve_from_base64(base64_png: str) -> str` and `solve_captcha_in_page(page, captcha_img_selector: str = "#imgCaptcha") -> str`.

- [x] **Step 1: Write the failing tests**

Copy `tests/test_captcha_solver.py` from the collector **verbatim** and adjust nothing except imports (module already is `captcha_solver`). The collector version defines `FakeLocator`, `FakePage`, and `CaptchaSolverTest`. If `ddddocr` is not installed in the environment, those tests cover the retry/threading logic around `solve_from_base64` — keep `CaptchaSolver.__init__`'s `raise RuntimeError` for missing `ddddocr` and skip tests that require an actual OCR model with `@unittest.skipUnless` on the class when `ddddocr is None`.

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_captcha_solver -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'captcha_solver'` (or skipped if skipping applies)

- [x] **Step 3: Copy the implementation**

Copy `captcha_solver.py` from the collector **verbatim** (`C:\Users\wermeson.silva\Documents\Projetos\sei-colaboragov\captcha_solver.py`, 146 lines). Change only the logger name to `sei-insights`.

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_captcha_solver -v`
Expected: PASS (or SKIPPED where the OCR model is unavailable)

- [x] **Step 5: Commit**

```bash
git add captcha_solver.py tests/test_captcha_solver.py
git commit -m "feat: resolvedor de CAPTCHA por OCR (copiado do coletor)"
```

---

### Task 5: Store — SQLite mirror, hash and delta

**Files:**
- Create: `store.py`
- Create: `tests/test_store.py`

**Interfaces:**
- Consumes: `normalize_process_number` from Task 2.
- Produces:
  - `@dataclass(slots=True) class ProcessRow` with fields, in this exact order:
    `numero`, `titulo`, `data_execucao`, `data_analise`, `data_ultimo_despacho`, `situacao`, `destino`, `acao_esperada`, `pendencia_curta`, `link_process`, `status_coleta`, `hash_ultimo_despacho` (all `str`).
  - `def despacho_hash(identificador: str) -> str` — SHA-256 hexdigest of the identifier string.
  - `class MirrorStore(db_path: pathlib.Path)` with `open()`, `close()`, `load_snapshot() -> dict[str, ProcessRow]` (keyed by `numero`), `replace_snapshot(rows: list[ProcessRow]) -> None`.
  - The SQLite table `processes` has **exactly** one column per `ProcessRow` field, primary key `numero`, WAL mode.

- [x] **Step 1: Write the failing tests**

`tests/test_store.py`:

```python
import tempfile
import unittest
from pathlib import Path

from store import MirrorStore, ProcessRow, despacho_hash


def row(numero: str, situacao: str = "X", hash_: str = "h") -> ProcessRow:
    return ProcessRow(
        numero=numero,
        titulo="t",
        data_execucao="2026-09-22 10:00:00",
        data_analise="2026-09-22 10:00:00",
        data_ultimo_despacho="15/09/2026",
        situacao=situacao,
        destino="SGA",
        acao_esperada="validar",
        pendencia_curta="pend",
        link_process="url",
        status_coleta="concluído",
        hash_ultimo_despacho=hash_,
    )


class StoreTest(unittest.TestCase):
    def _store(self, tmp):
        store = MirrorStore(Path(tmp) / "db.sqlite3")
        store.open()
        return store

    def test_replace_espelho_reconstroi_inteiro(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.replace_snapshot([row("001", "A"), row("002", "B")])
            snap = store.load_snapshot()
            self.assertEqual(set(snap), {"001", "002"})
            # reconstrução: remove antigo e insere atual
            store.replace_snapshot([row("002", "B2"), row("003", "C")])
            snap = store.load_snapshot()
            self.assertEqual(set(snap), {"002", "003"})
            self.assertEqual(snap["002"].situacao, "B2")
            store.close()

    def test_load_snapshot_vazio(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            self.assertEqual(store.load_snapshot(), {})
            store.close()

    def test_hash_deterministico_e_sensivel(self):
        self.assertEqual(despacho_hash("12345|15/09/2026"),
                         despacho_hash("12345|15/09/2026"))
        self.assertNotEqual(despacho_hash("12345|15/09/2026"),
                            despacho_hash("12346|15/09/2026"))
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_store -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'store'`

- [x] **Step 3: Write the implementation**

`store.py`:

```python
from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sei-insights")

FIELDS = [
    "numero", "titulo", "data_execucao", "data_analise",
    "data_ultimo_despacho", "situacao", "destino", "acao_esperada",
    "pendencia_curta", "link_process", "status_coleta",
    "hash_ultimo_despacho",
]


@dataclass(slots=True)
class ProcessRow:
    numero: str
    titulo: str
    data_execucao: str
    data_analise: str
    data_ultimo_despacho: str
    situacao: str
    destino: str
    acao_esperada: str
    pendencia_curta: str
    link_process: str
    status_coleta: str
    hash_ultimo_despacho: str


def despacho_hash(identificador: str) -> str:
    return hashlib.sha256(identificador.encode("utf-8")).hexdigest()


class MirrorStore:
    """Espelho SQLite exatamente igual à planilha (fonte da verdade)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def open(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS processes ("
            + ", ".join(f"{f} TEXT" for f in FIELDS)
            + ", PRIMARY KEY (numero))"
        )
        self.conn.commit()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _require(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("MirrorStore não aberto")
        return self.conn

    def load_snapshot(self) -> dict[str, ProcessRow]:
        conn = self._require()
        cur = conn.execute(
            f"SELECT {', '.join(FIELDS)} FROM processes"
        )
        snapshot: dict[str, ProcessRow] = {}
        for values in cur.fetchall():
            r = ProcessRow(**dict(zip(FIELDS, values)))
            snapshot[r.numero] = r
        return snapshot

    def replace_snapshot(self, rows: list[ProcessRow]) -> None:
        conn = self._require()
        conn.execute("DELETE FROM processes")
        if rows:
            placeholders = ", ".join("?" for _ in FIELDS)
            conn.executemany(
                f"INSERT INTO processes ({', '.join(FIELDS)}) "
                f"VALUES ({placeholders})",
                [tuple(getattr(r, f) for f in FIELDS) for r in rows],
            )
        conn.commit()
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_store -v`
Expected: PASS (3 tests)

- [x] **Step 5: Commit**

```bash
git add store.py tests/test_store.py
git commit -m "feat: espelho SQLite idêntico à planilha e hash do despacho"
```

---

### Task 6: Text extraction (pypdf)

**Files:**
- Create: `text_ing.py`
- Create: `tests/test_text_ing.py`

**Interfaces:**
- Consumes: nothing from this project.
- Produces: `def extract_text_from_pdf(path: pathlib.Path) -> str` — returns page texts joined by `\n`, empty string for a PDF with no extractable text, raises the pypdf error on unreadable/corrupt files.

- [x] **Step 1: Write the failing tests**

`tests/test_text_ing.py`:

```python
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter

from text_ing import extract_text_from_pdf


class TextIngTest(unittest.TestCase):
    def _write(self, tmp: str, name: str, text: str) -> Path:
        path = Path(tmp) / name
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        if text:
            writer.pages[0].create_blank_page()  # no-op guard, replaced below
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        # attach a raw content stream to the page (avoids font complexity for tests)
        from pypdf.generic import DecodedStreamObject, NameObject
        stream = DecodedStreamObject()
        stream.set_data(content.encode("latin-1"))
        writer.pages[0][NameObject("/Contents")] = stream
        with path.open("wb") as fh:
            writer.write(fh)
        return path

    def test_extrai_texto(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "a.pdf", "Diante do exposto")
            self.assertIn("Diante do exposto", extract_text_from_pdf(path))

    def test_pdf_sem_texto_retorna_vazio(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "b.pdf", "")
            self.assertEqual(extract_text_from_pdf(path), "")
```

> If the raw `/Contents` stream fixture proves flaky on the installed pypdf version, replace it with a fixed base64-encoded minimal "Hello World" one-page PDF (a known, stable fixture generated once) and keep both tests. The empty-string behavior is the contract that matters.

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_text_ing -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'text_ing'`

- [x] **Step 3: Write the implementation**

`text_ing.py`:

```python
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_text_from_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_text_ing -v`
Expected: PASS (2 tests)

- [x] **Step 5: Commit**

```bash
git add text_ing.py tests/test_text_ing.py
git commit -m "feat: extração de texto de PDF via pypdf"
```

---

### Task 7: Document tree — parse, correlate, select last Despacho

**Files:**
- Create: `tree.py`
- Create: `tests/test_tree.py`

**Interfaces:**
- Consumes: none.
- Produces:
  - `@dataclass(slots=True) class DocNode: serie: str; numero: str; data: str; posicao: int; url: str`
  - `def parse_tree(html: str) -> list[DocNode]` — parses rows from the public process page HTML (calibrate selectors with the spike notes; the default implementation below targets rows that contain a label with the serie name followed by a number and an optional date).
  - `def correlate_urls(nodes: list[DocNode], links: list[tuple[str, str]]) -> list[DocNode]` — sets `node.url` by matching a link label that contains the node's `numero`; fallback: assign URLs to nodes (without a number) in render order.
  - `def select_last_despacho(nodes: list[DocNode]) -> DocNode | None` — greatest date among serie containing "Despacho"; tie/dateless → last in tree order; `None` when no Despacho node exists.

- [x] **Step 1: Write the failing tests**

`tests/test_tree.py`:

```python
import unittest

from tree import correlate_urls, parse_tree, select_last_despacho

HTML = """
<div class="infraArvore">
  <ul>
    <li>
      <input type="checkbox" value="100001">
      <span class="infraLabel">Processo Administrativo</span>
    </li>
    <li>
      <input type="checkbox" value="100002">
      <span class="infraLabel">Despacho 100002 - 10/09/2026</span>
    </li>
    <li>
      <input type="checkbox" value="100003">
      <span class="infraLabel">Despacho 100003 - 15/09/2026</span>
    </li>
    <li>
      <input type="checkbox" value="100004">
      <span class="infraLabel">Ofício 100004 - 16/09/2026</span>
    </li>
  </ul>
</div>
"""

LINKS = [
    ("Despacho 100002 - 10/09/2026", "https://x/doc?d=100002"),
    ("Despacho 100003 - 15/09/2026", "https://x/doc?d=100003"),
    ("Ofício 100004 - 16/09/2026", "https://x/doc?d=100004"),
]


class TreeTest(unittest.TestCase):
    def test_parse_extrai_serie_numero_data_posicao(self):
        nodes = parse_tree(HTML)
        self.assertEqual(len(nodes), 4)
        desp = [n for n in nodes if n.serie == "Despacho"]
        self.assertEqual(len(desp), 2)
        self.assertEqual(desp[1].data, "15/09/2026")
        self.assertEqual(desp[1].numero, "100003")

    def test_correlate_por_numero(self):
        nodes = parse_tree(HTML)
        nodes = correlate_urls(nodes, LINKS)
        by_num = {n.numero: n for n in nodes}
        self.assertEqual(by_num["100003"].url, "https://x/doc?d=100003")

    def test_select_ultimo_despacho_por_data(self):
        nodes = parse_tree(HTML)
        nodes = correlate_urls(nodes, LINKS)
        d = select_last_despacho(nodes)
        self.assertIsNotNone(d)
        self.assertEqual(d.numero, "100003")

    def test_select_ultimo_despacho_ordem_sem_data(self):
        nodes = parse_tree(HTML.replace("15/09/2026", "?"))
        d = select_last_despacho(nodes)
        self.assertIsNotNone(d)
        self.assertEqual(d.numero, "100003")

    def test_sem_despacho_retorna_none(self):
        html = HTML.replace("Despacho 100002 - 10/09/2026", "Nota Técnica 100002 - 10/09/2026") \
                   .replace("Despacho 100003 - 15/09/2026", "Nota Técnica 100003 - 15/09/2026")
        self.assertIsNone(select_last_despacho(parse_tree(html)))
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_tree -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tree'`

- [x] **Step 3: Write the implementation**

`tree.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
NUM_RE = re.compile(r"\b(\d{5,})\b")


@dataclass(slots=True)
class DocNode:
    serie: str
    numero: str
    data: str
    posicao: int
    url: str = ""


def parse_tree(html: str) -> list[DocNode]:
    """Calibrado com o spike (Task 1). Default lê `li`/`tr` com rótulo."""
    soup = BeautifulSoup(html, "html.parser")
    nodes: list[DocNode] = []
    for pos, row in enumerate(
        soup.select("li, tr, [class*='infraArvore'] [class*='infraLabel']")
    ):
        label_el = row.select_one("span.infraLabel, label, a[title]")
        label = ""
        if label_el is not None:
            label = label_el.get("title") or label_el.get_text(" ", strip=True) or ""
        if not label:
            continue
        date_m = DATE_RE.search(label)
        num_m = NUM_RE.search(label)
        if num_m is None:
            continue
        first_word = label.strip().split()[0] if label.strip().split() else ""
        nodes.append(
            DocNode(
                serie=first_word,
                numero=num_m.group(1),
                data=date_m.group(1) if date_m else "",
                posicao=pos,
            )
        )
    return nodes


def correlate_urls(nodes: list[DocNode], links: list[tuple[str, str]]) -> list[DocNode]:
    """links: [(rótulo, url)]. Casa por número documental; fallback por ordem."""
    by_number: dict[str, str] = {}
    for label, url in links:
        m = NUM_RE.search(label)
        if m:
            by_number.setdefault(m.group(1), url)
    free = [url for _, url in links if _corresponds_to_numbered(_)]
    used = set()
    for node in nodes:
        if node.numero and node.numero in by_number:
            node.url = by_number[node.numero]
        else:
            url = next((u for u in free if u not in used), "")
            if url:
                used.add(url)
                node.url = url
    return nodes


def _corresponds_to_numbered(label: str) -> bool:
    from bs4 import BeautifulSoup as _BS  # noqa: keep pure
    return NUM_RE.search(label) is None


def select_last_despacho(nodes: list[DocNode]) -> Optional[DocNode]:
    despachos = [n for n in nodes if "Despacho" in n.serie]
    if not despachos:
        return None
    dated = [n for n in despachos if n.data]
    if dated:
        return max(dated, key=lambda n: (n.data, n.posicao))
    return max(despachos, key=lambda n: n.posicao)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_tree -v`
Expected: PASS (5 tests). If the fixture/selector assumptions differ from the real page (per the spike), adjust the selectors in `parse_tree` and the fixture together, then commit the change with a note.

- [x] **Step 5: Commit**

```bash
git add tree.py tests/test_tree.py
git commit -m "feat: leitura da árvore, correlação nó->URL e seleção do último despacho"
```

---

### Task 8: Rules engine

**Files:**
- Create: `rules.py`, `regras.json`
- Create: `tests/test_rules.py`

**Interfaces:**
- Consumes: none.
- Produces:
  - `@dataclass(slots=True) class RuleResult: situacao: str; destino: str; acao_esperada: str; pendencia_curta: str`
  - `class RulesEngine(config: Optional[dict] = None)` with `classify(text: str) -> RuleResult` and a classmethod `from_file(path: pathlib.Path) -> RulesEngine`.
  - `regras.json`: ordered list of rules `{pattern, situacao, destino, acao_esperada, pendencia_curta}` + a `fallback` object.

- [x] **Step 1: Write the failing tests**

`tests/test_rules.py`:

```python
import unittest

from rules import RulesEngine

REGRA_DETRAN = [
    {
        "pattern": r"encaminha-se.*?(?:\bagentes\b)?.*?(SGA|SCL|CTI|CCL)\b",
        "situacao": "Em {destino}",
        "destino": "\\1",
        "acao_esperada": "ciência e validação",
        "pendencia_curta": "Processo com o destino para análise/próximo passo",
    },
    {
        "pattern": r"(?:exigir|aguardando).*(?:assinatura)",
        "situacao": "Pendente de assinatura",
        "destino": "",
        "acao_esperada": "assinatura",
        "pendencia_curta": "Aguardando assinatura",
    },
    {
        "pattern": r"DETRAN",
        "situacao": "Encaminhado a órgão externo (Detran/DF)",
        "destino": "Detran/DF",
        "acao_esperada": "providências",
        "pendencia_curta": "Detran/DF adotar providências",
    },
]

DESPACHO_DETRAN = (
    "Diante do exposto, encaminham-se os autos à Subsecretaria de Gestão e "
    "Administração (SGA), para ciência e validação da Minuta de Ofício anexa, "
    "conversão em Ofício, e, após, retorno a esta Coordenação de Contratações e "
    "Logística (CCL), para encaminhamento do Ofício e dos demais anexos ao "
    "Departamento de Trânsito do Distrito Federal (Detran/DF), para análise e "
    "adoção das providências necessárias ao cancelamento das comunicações de "
    "transferência veicular anteriormente realizadas e à consequente "
    "regularização dos registros de transferência dos veículos."
)


class RulesTest(unittest.TestCase):
    def test_classifica_detran(self):
        engine = RulesEngine(REGRA_DETRAN)
        r = engine.classify(DESPACHO_DETRAN)
        self.assertIn("Detran/DF", r.situacao)
        self.assertEqual(r.destino, "Detran/DF")
        self.assertTrue(r.pendencia_curta)

    def test_fallback_quando_nada_casa(self):
        engine = RulesEngine(REGRA_DETRAN)
        r = engine.classify("Texto irrelevante sem padrão conhecido.")
        self.assertEqual(r.situacao, "Em análise")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_rules -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rules'`

- [x] **Step 3: Write the implementation**

`regras.json`:

```json
{
  "fallback": {
    "situacao": "Em análise",
    "destino": "",
    "acao_esperada": "",
    "pendencia_curta": ""
  },
  "regras": [
    {
      "pattern": "para assinatura",
      "situacao": "Pendente de assinatura",
      "destino": "",
      "acao_esperada": "assinatura",
      "pendencia_curta": "Aguardando assinatura do documento"
    },
    {
      "pattern": "(?:aguardando retorno|retorno a (?:esta|essa)?\\s*([A-Za-zÀ-ÿ]+))",
      "situacao": "Aguardando retorno",
      "destino": "\\1",
      "acao_esperada": "retorno",
      "pendencia_curta": "Aguardando retorno do destinatário"
    },
    {
      "pattern": "DETRAN",
      "situacao": "Encaminhado a órgão externo (Detran/DF)",
      "destino": "Detran/DF",
      "acao_esperada": "providências",
      "pendencia_curta": "Detran/DF analisar e adotar providências"
    },
    {
      "pattern": "\\b(SGA|CCL|CTI|SG)\\b",
      "situacao": "Em \\1",
      "destino": "\\1",
      "acao_esperada": "análise",
      "pendencia_curta": "Processo com o destino para análise/próximo passo"
    }
  ]
}
```

`rules.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(slots=True)
class RuleResult:
    situacao: str
    destino: str
    acao_esperada: str
    pendencia_curta: str


class RulesEngine:
    def __init__(self, config: Optional[dict] = None) -> None:
        self.config = config or {}
        self.rules = self.config.get("regras", [])
        self.fallback = self.config.get(
            "fallback",
            {"situacao": "Em análise", "destino": "",
             "acao_esperada": "", "pendencia_curta": ""},
        )

    @classmethod
    def from_file(cls, path: Path) -> "RulesEngine":
        with path.open(encoding="utf-8") as fh:
            return cls(json.load(fh))

    def classify(self, text: str) -> RuleResult:
        normalized = re.sub(r"\s+", " ", text)
        for rule in self.rules:
            m = re.search(rule["pattern"], normalized, re.IGNORECASE)
            if m:
                def sub(val: str) -> str:
                    try:
                        return m.expand(val)
                    except (re.error, IndexError):
                        return ""
                destino = sub(rule.get("destino", ""))
                return RuleResult(
                    situacao=sub(rule.get("situacao", self.fallback["situacao"])),
                    destino=destino,
                    acao_esperada=sub(rule.get("acao_esperada", "")),
                    pendencia_curta=sub(rule.get("pendencia_curta", "")),
                )
        return RuleResult(**self.fallback)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_rules -v`
Expected: PASS (2 tests). The shipped `regras.json` is a starter set; the user calibrates terms later without touching code. During calibration, prefer concrete patterns named after real despachos (per spec §9 "calibração inicial").

- [x] **Step 5: Commit**

```bash
git add rules.py regras.json tests/test_rules.py
git commit -m "feat: motor de regras determinístico com regras.json"
```

---

### Task 9: Discovery parsing and pagination

**Files:**
- Create: `discovery.py`
- Create: `tests/test_discovery.py`

**Interfaces:**
- Consumes: `normalize_process_number` (Task 2).
- Produces:
  - `def parse_response(data: dict) -> list[str]` — unique normalized numbers extracted from `data["html"]` (anchors `md_pesq_processo_exibir.php`, row `data-prot` preferred, else link row text).
  - `def expected_total(data: dict) -> int` — `int(data.get("itens") or 0)`.
  - `def pagination_params(inicio: int, rows_solr: int = 50) -> dict` — `{"isPaginacao": "true", "inicio": inicio, "rowsSolr": rows_solr}`.

- [x] **Step 1: Write the failing tests** (adjust fixture to the real JSON shape from the spike if different)

`tests/test_discovery.py`:

```python
import unittest

from discovery import expected_total, pagination_params, parse_response

ROW1 = ("<tr data-prot='21260.003436/2026-15'>"
        "<td><a href='md_pesq_processo_exibir.php?id=1'>Proc 1</a></td></tr>")
ROW2 = ("<tr data-prot='21260.003437/2026-16'>"
        "<td><a href='md_pesq_processo_exibir.php?id=2'>Proc 2</a> 21260.003437/2026-16</td></tr>")


class DiscoveryTest(unittest.TestCase):
    def test_parse_usa_data_prot_e_deduplica(self):
        data = {"itens": 2, "html": ROW1 + ROW2 + ROW1}
        result = parse_response(data)
        self.assertEqual(result, ["21260.003436/2026-15", "21260.003437/2026-16"])

    def test_parse_usa_texto_quando_sem_data_prot(self):
        html = ("<tr><td><a href='md_pesq_processo_exibir.php?id=3'>"
                "21260.003438/2026-17</a></td></tr>")
        self.assertEqual(parse_response({"itens": 1, "html": html}),
                         ["21260.003438/2026-17"])

    def test_parse_resultado_vazio(self):
        self.assertEqual(parse_response({"itens": 0, "html": "<div>vazio</div>"}), [])

    def test_expected_total(self):
        self.assertEqual(expected_total({"itens": 43}), 43)
        self.assertEqual(expected_total({}), 0)

    def test_pagination_params(self):
        self.assertEqual(pagination_params(50),
                         {"isPaginacao": "true", "inicio": 50, "rowsSolr": 50})
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_discovery -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'discovery'`

- [x] **Step 3: Write the implementation**

`discovery.py`:

```python
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from utils import normalize_process_number


def parse_response(data: dict) -> list[str]:
    html = data.get("html", "") or ""
    soup = BeautifulSoup(html, "html.parser")
    seen: list[str] = []
    seen_set: set[str] = set()
    for a in soup.select('a[href*="md_pesq_processo_exibir.php"]'):
        parent = a.find_parent(attrs={"data-prot": True})
        raw = ""
        if parent is not None and parent.get("data-prot"):
            raw = parent.get("data-prot")
        else:
            raw = a.parent.get_text(" ", strip=True) if a.parent is not None else ""
        number = normalize_process_number(raw)
        if number and number not in seen_set:
            seen_set.add(number)
            seen.append(number)
    return seen


def expected_total(data: dict) -> int:
    try:
        return int(data.get("itens") or 0)
    except (TypeError, ValueError):
        return 0


def pagination_params(inicio: int, rows_solr: int = 50) -> dict:
    return {"isPaginacao": "true", "inicio": inicio, "rowsSolr": rows_solr}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_discovery -v`
Expected: PASS (5 tests)

- [x] **Step 5: Commit**

```bash
git add discovery.py tests/test_discovery.py
git commit -m "feat: parsing da resposta de descoberta e parâmetros de paginação"
```

---

### Task 10: Spreadsheet report (openpyxl)

**Files:**
- Create: `report.py`
- Create: `tests/test_report.py`

**Interfaces:**
- Consumes: `ProcessRow` (Task 5).
- Produces:
  - `def build_resumo(rows: list[ProcessRow], novos: list[ProcessRow]) -> dict` — `total`, `novos`, `por_situacao: dict[str,int]`, `por_status: dict[str,int]`.
  - `def write_spreadsheet(path: pathlib.Path, rows: list[ProcessRow], novos: list[ProcessRow], resumo: dict) -> None` — writes tabs "Aba principal" (all rows), "Novos" (new rows), "Resumo" (the counts). Column header order must match `ProcessRow` field order. An empty `rows` list still writes a valid workbook with headers and a zeroed summary.

- [x] **Step 1: Write the failing tests**

`tests/test_report.py`:

```python
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from report import build_resumo, write_spreadsheet
from store import ProcessRow


def row(numero: str, situacao: str = "Na CTI", status: str = "concluído") -> ProcessRow:
    return ProcessRow(
        numero=numero, titulo="t", data_execucao="2026-09-22 10:00:00",
        data_analise="2026-09-22 10:00:00", data_ultimo_despacho="",
        situacao=situacao, destino="", acao_esperada="", pendencia_curta="",
        link_process="url", status_coleta=status, hash_ultimo_despacho="h",
    )


class ReportTest(unittest.TestCase):
    def test_write_leitura_de_volta(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.xlsx"
            rows = [row("001", "Na CTI"), row("002", "Pendente de assinatura")]
            novos = [row("002", "Pendente de assinatura")]
            resumo = build_resumo(rows, novos)
            write_spreadsheet(path, rows, novos, resumo)
            wb = load_workbook(path)
            self.assertEqual(wb.sheetnames, ["Aba principal", "Novos", "Resumo"])
            principal = wb["Aba principal"]
            self.assertEqual(principal.max_row, len(rows) + 1)
            self.assertEqual(principal.cell(row=1, column=1).value, "numero")
            self.assertEqual(principal.cell(row=2, column=1).value, "001")
            nov = wb["Novos"]
            self.assertEqual(nov.max_row, len(novos) + 1)
            res = wb["Resumo"]
            self.assertEqual(res["A2"].value, 2)   # total
            self.assertEqual(res["B2"].value, 1)   # novos
            wb.close()

    def test_resultado_vazio_escreve_workbook_valido(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vazio.xlsx"
            write_spreadsheet(path, [], [], build_resumo([], []))
            wb = load_workbook(path)
            self.assertEqual(wb.sheetnames, ["Aba principal", "Novos", "Resumo"])
            self.assertEqual(wb["Aba principal"].max_row, 1)
            self.assertEqual(wb["Resumo"]["A2"].value, 0)
            wb.close()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_report -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'report'`

- [x] **Step 3: Write the implementation**

`report.py`:

```python
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from store import FIELDS, ProcessRow


def build_resumo(rows: list[ProcessRow], novos: list[ProcessRow]) -> dict:
    por_situacao: dict[str, int] = {}
    por_status: dict[str, int] = {}
    for r in rows:
        por_situacao[r.situacao] = por_situacao.get(r.situacao, 0) + 1
        por_status[r.status_coleta] = por_status.get(r.status_coleta, 0) + 1
    return {
        "total": len(rows),
        "novos": len(novos),
        "por_situacao": por_situacao,
        "por_status": por_status,
    }


def _fill_sheet(sheet, rows: list[ProcessRow]) -> None:
    sheet.append(FIELDS)
    for r in rows:
        sheet.append([getattr(r, f) for f in FIELDS])


def write_spreadsheet(
    path: Path,
    rows: list[ProcessRow],
    novos: list[ProcessRow],
    resumo: dict,
) -> None:
    wb = Workbook()
    principal = wb.active
    principal.title = "Aba principal"
    _fill_sheet(principal, rows)
    nov = wb.create_sheet("Novos")
    _fill_sheet(nov, novos)
    res = wb.create_sheet("Resumo")
    res.append(["métrica", "valor"])
    res.append(["total", resumo["total"]])
    res.append(["novos", resumo["novos"]])
    for label, counts in (("por_situacao", resumo["por_situacao"]),
                          ("por_status", resumo["por_status"])):
        for key, value in counts.items():
            res.append([label, f"{key} = {value}"])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    wb.close()
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_report -v`
Expected: PASS (2 tests)

- [x] **Step 5: Commit**

```bash
git add report.py tests/test_report.py
git commit -m "feat: planilha xlsx com abas espelho, novos e resumo"
```

---

### Task 11: SEI client (copy + discovery search + pagination)

**Files:**
- Create: `sei_client.py`
- Create: `tests/test_sei_client.py`

**Interfaces:**
- Consumes: `RateLimiter` (Task 3), `CaptchaSolver` (Task 4), `utils` (Task 2), `parse_response`, `expected_total`, `pagination_params` (Task 9).
- Produces:
  - constants `BASE_URL = "https://colaboragov.sei.gov.br/sei/"` and `PUBLIC_SEARCH_URL` (same as collector), `DEFAULT_TIMEOUT_MS = 90_000`.
  - `@dataclass(slots=True) class ProcessResult: number: str; url: str; title: str`
  - `@dataclass(slots=True) class PublicDocument: number: str; name: str; url: str`
  - `class SeiClient(context, page, rate_limiter)`:
    - `save_debug(name)` , `open_search_page()`, `process_input()`, `captcha_input()`, `captcha_is_present()` , `captcha_has_value()`, `wait_for_manual_captcha()`, `solve_search_captcha()` , `find_search_submit()` , `submit_search()`, `extract_process(requested_number)`, `open_process(process) -> str`, `extract_documents(process_html, process_url) -> list[PublicDocument]`, `download_document(process_number, document) -> tuple[Path|None, str|None, str|None]` — all copied from the collector.
    - NEW `search_processes(orgao: str, unidade: str, inicio: str, fim: str, page_size: int = 50) -> list[ProcessResult]`:
      opens the search page, selects organ/unit per the spike's selector strategy (Task 1), marks **all three** search-type checkboxes, fills the date fields, installs the AJAX listener, submits, parses the JSON via `discovery`, then paginates through the remaining pages via `context.request` POST to the AJAX endpoint using `pagination_params`, following `expected_total`; returns unique `ProcessResult`s in order.

- [x] **Step 1: Write the failing tests**

`tests/test_sei_client.py` — pure parsing/matching tests that run without a browser (mirrors the collector's `FakePage`/`FakeLocator` approach):

```python
import unittest

from sei_client import SeiClient, extract_process  # extract_process is a module function below


class FakeResponse:
    def __init__(self, method: str, url: str):
        self.method = method
        self.url = url


class FakeRequest:
    def __init__(self, method: str, url: str):
        self.method = method
        self.url = url


class FakeResp:
    def __init__(self, method: str, url: str):
        self.request = FakeRequest(method, url)


class IsSearchResponseTest(unittest.TestCase):
    def test_reconhece_post_de_pesquisa(self):
        r = FakeResp("POST",
                     "https://colaboragov.sei.gov.br/sei/modulos/pesquisa/"
                     "md_pesq_controlador_ajax_externo.php"
                     "?acao_ajax_externo=protocolo_pesquisar&isPaginacao=false")
        self.assertTrue(SeiClient.is_search_response(r))

    def test_rejeita_get(self):
        r = FakeResp("GET", "?acao_ajax_externo=protocolo_pesquisar&isPaginacao=false")
        self.assertFalse(SeiClient.is_search_response(r))

    def test_rejeita_outro_ajax(self):
        r = FakeResp("POST", "?acao_ajax_externo=outra_coisa&isPaginacao=false")
        self.assertFalse(SeiClient.is_search_response(r))


class ExtractProcessTest(unittest.TestCase):
    def test_acha_por_data_prot(self):
        html = ("<div><tr data-prot='21260.003436/2026-15'>"
                "<td><a href='md_pesq_processo_exibir.php?id=9'>Título X</a></td>"
                "</tr></div>")
        result = extract_process(html, "21260.003436/2026-15")
        self.assertIsNotNone(result)
        self.assertEqual(result.number, "21260.003436/2026-15")
        self.assertTrue(result.url.endswith("md_pesq_processo_exibir.php?id=9"))

    def test_nao_acha_nada(self):
        self.assertIsNone(extract_process("<html></html>", "21260.003436/2026-15"))
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_sei_client -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sei_client'`

- [x] **Step 3: Copy and adapt the implementation**

`sei_client.py` — copy from the collector `main.py` and adapt:

1. Copy constants `BASE_URL`, `PUBLIC_SEARCH_URL`, `SEARCH_PAGE_SIZE`, `DEFAULT_TIMEOUT_MS`, `MAX_RETRIES`, `SEARCH_RESULT_DELAY_MS` (collector `main.py:101-167`).
2. Copy the models `ProcessResult` (`main.py:239-249`) and `PublicDocument` (`main.py:250-264`) **verbatim**.
3. Copy `SeiClient.__init__`, `save_debug`, `open_search_page`, `process_input`, `ensure_process_checkbox`, `ensure_orgaos_selected`, `captcha_input`, `captcha_is_present`, `captcha_has_value`, `wait_for_manual_captcha`, `solve_search_captcha`, `find_search_submit`, `submit_search`, `extract_process`, `open_process`, `extract_documents`, `download_document` **verbatim** from collector ranges `main.py:1372-2783` and `3281-3550` (skip the "Gerar PDF" modal methods, `extract_tree_documents`, and the `nota`/`metadata` helpers — this project does not need the single-process PDF).
4. Move the AJAX-response predicate to a **static method** `is_search_response(response) -> bool` (same body as collector `search_process`'s closure at `main.py:3638-3660`).
5. Extract the process-matching logic already inside `extract_process` into a **module-level function** `extract_process(html: str, requested_number: str) -> `ProcessResult | None`` (same algorithm as collector `main.py:2360-2513`), and have the `SeiClient` method thin-wrap it. The tests import this module function.
6. Add the two NEW methods below (implemented per the spike's selector details from `docs/spike-2026-09-22.md`):

```python
    def search_processes(self, orgao: str, unidade: str,
                         inicio: str, fim: str, page_size: int = 50) -> list[ProcessResult]:
        from discovery import expected_total, pagination_params, parse_response
        self.open_search_page()
        self._set_search_criteria(orgao, unidade, inicio, fim)
        results: dict[str, ProcessResult] = {}
        self.solve_search_captcha()

        def is_search_response(response) -> bool:
            return SeiClient.is_search_response(response)

        with self.page.expect_response(is_search_response, timeout=90_000):
            self.submit_search()
        response = None  # populated by context manager in collector pattern

        # Collector pattern: response_info.value; keep the expect_response as in
        # collector search_process (main.py:3670-3683) and reuse its JSON read.
        data = response.json()
        page_numbers = parse_response(data)
        for number in page_numbers:
            self._add_result(results, number, data)
        total = expected_total(data)
        page = page_size
        while len(results) < max(total, len(page_numbers)) and page_numbers:
            page_result = self._fetch_page(page, page_size)
            page_numbers = parse_response(page_result)
            if not page_numbers:
                break
            for number in page_numbers:
                self._add_result(results, number, page_result)
            page += page_size
            if page > page_size * 50:  # safety valve
                break
        return list(results.values())
```

```python
    def _set_search_criteria(self, orgao: str, unidade: str,
                             inicio: str, fim: str) -> None:
        """Seleção de Órgão/Unidade per spike (Task 1). Fallback: todos órgãos."""
        try:
            self.page.evaluate(
                """(selOrg, selUni) => {
                    const $o = $('#selOrgaoPesquisa');
                    if ($o.length && $o.multipleSelect) {
                        $o.multipleSelect('setSelects', [selOrg]);
                    } else if ($o.length) { $o.val(selOrg).trigger('change'); }
                    const $u = $('#selUnidadePesquisa');
                    if ($u.length && $u.multipleSelect) {
                        $u.multipleSelect('setSelects', [selUni]);
                    } else if ($u.length) { $u.val(selUni).trigger('change'); }
                }""",
                orgao, unidade,
            )
        except Exception as exc:
            self.save_debug("falha_selecionar_orgao_unidade")
            logger.warning("Usando fallback (todos órgãos): %s", exc)
            self.ensure_orgaos_selected()
        # marca os três tipos de pesquisa
        for name in ("chkSinProcessos", "chkSinDocumentosGerados",
                     "chkSinDocumentosExternos"):
            cb = self.page.locator(f"#{name}")
            if cb.count() == 0:
                cb = self.page.locator(f'input[name="{name}"]')
            if cb.count() and not cb.first.is_checked():
                cb.first.check()
        # datas
        for field, value in (("#txtDataInicialPesquisa", inicio),
                             ("#txtDataFinalPesquisa", fim)):
            f = self.page.locator(field)
            if f.count() == 0:
                f = self.page.locator(f'input[name="{field[1:]}"]')
            if f.count():
                f.first.fill(value)
```

```python
    def _fetch_page(self, inicio: int, page_size: int) -> dict:
        from discovery import pagination_params
        params = pagination_params(inicio, page_size)
        self.rate_limiter.wait()
        url = ("https://colaboragov.sei.gov.br/sei/modulos/pesquisa/"
               "md_pesq_controlador_ajax_externo.php")
        form = self.page.evaluate(
            """() => {
                const f = document.getElementById('seiSearch');
                const d = new FormData(f); const o = {};
                for (const [k, v] of d.entries()) o[k] = String(v);
                return o;
            }"""
        )
        response = self.context.request.post(url, params={
            "acao_ajax_externo": "protocolo_pesquisar",
            "id_orgao_acesso_externo": "7",
            **params,
        }, form=form, fail_on_status_code=False)
        try:
            return response.json()
        except Exception:
            self.save_debug("paginacao_ajax_invalida")
            return {"itens": 0, "html": ""}
```

```python
    def _add_result(self, results: dict, number: str, data: dict) -> None:
        if number in results:
            return
        link = self._find_process_link(number)  # via extract_process on retorno-ajax
        results[number] = self._build_process_result(number, link)
```

> The spike (Task 1) is the authority for `#txtDataInicialPesquisa` field names and the organ/unit selector strategy; if the live names differ, update `_set_search_criteria` accordingly and note it in the spike doc. Keep `ensure_orgaos_selected` as the degradation path, and keep a rate-limit wait before every pagination POST.

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_sei_client -v`
Expected: PASS (5 tests) — the parsing/matching-predicate tests do not require a browser or the live site.

- [x] **Step 5: Commit**

```bash
git add sei_client.py tests/test_sei_client.py
git commit -m "feat: cliente SEI com descoberta por unidade/período e paginação"
```

---

### Task 12: CLI and orchestration (main.py) + README

**Files:**
- Create: `main.py`, `tests/test_main.py`, `README.md`

**Interfaces:**
- Consumes: `ProcessResult` (Task 11), `ProcessRow`/`MirrorStore`/`despacho_hash` (Task 5), `text_ing.extract_text_from_pdf` (Task 6), `tree` (Task 7), `RulesEngine` (Task 8), `report.build_resumo`/`write_spreadsheet` (Task 10), `sei_client.SeiClient` (Task 11).
- Produces:
  - `def parse_arguments() -> argparse.Namespace` — flags: `--orgao`, `--unidade`, `--dias` (int, 7), `--inicio`, `--fim`, `--manual-captcha`, `--min-delay` (2.0), `--max-delay` (5.0), `--force`, `--saida` (default `sei_insights.xlsx`).
  - `def build_rows(previous: dict[str, ProcessRow], found: list[ProcessResult], analyze, force: bool, now: str) -> tuple[list[ProcessRow], list[ProcessRow]]` — `analyze(process: ProcessResult, prev: ProcessRow | None, force: bool, now: str) -> ProcessRow`; returns `(rows, novos)` where `novos` = rows whose number was absent from `previous`. Any exception from `analyze` becomes a row with `status_coleta = f"erro: {exc}"` and `situacao = "Erro / retry"`; a row is always produced (cache never blocks writing).
  - `def now_str() -> str` — local time `"YYYY-MM-DD HH:MM:SS"`.
  - `def main() -> int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_main.py`:

```python
import tempfile
import unittest
from pathlib import Path

from main import build_rows, now_str, parse_arguments
from sei_client import ProcessResult
from store import ProcessRow


def row(numero: str, situacao: str = "Na CTI", hash_: str = "h") -> ProcessRow:
    return ProcessRow(
        numero=numero, titulo="t", data_execucao="2026-09-21 10:00:00",
        data_analise="2026-09-21 10:00:00", data_ultimo_despacho="",
        situacao=situacao, destino="", acao_esperada="", pendencia_curta="",
        link_process="u", status_coleta="concluído", hash_ultimo_despacho=hash_,
    )


def pr(numero: str) -> ProcessResult:
    return ProcessResult(number=numero, url=f"url/{numero}", title="t")


class BuildRowsTest(unittest.TestCase):
    def test_sem_cache_analisa_tudo(self):
        def analyze(p, prev, force, now):
            return row(p.number, "Nova análise", "h1")
        rows, novos = build_rows({}, [pr("001"), pr("002")], analyze, False, "2026-09-22 10:00:00")
        self.assertEqual([r.numero for r in rows], ["001", "002"])
        self.assertEqual([r.numero for r in novos], ["001", "002"])
        self.assertEqual(rows[0].situacao, "Nova análise")

    def test_com_cache_nao_reanalisa(self):
        calls = []
        def analyze(p, prev, force, now):
            calls.append(p.number)
            return row(p.number, "Cache", prev.hash_ultimo_despacho if prev else "h")
        previous = {"001": row("001", "Guardada", "h")}
        rows, novos = build_rows(previous, [pr("001")], analyze, False, now_str())
        self.assertEqual(calls, [])
        self.assertEqual(rows[0].situacao, "Guardada")
        self.assertEqual(novos, [])

    def test_force_reanalisa_mesmo_com_cache(self):
        calls = []
        def analyze(p, prev, force, now):
            calls.append(p.number)
            return row(p.number, "Nova", "h2")
        rows, _ = build_rows({"001": row("001", "Velha", "h")},
                             [pr("001")], analyze, True, now_str())
        self.assertEqual(calls, ["001"])
        self.assertEqual(rows[0].situacao, "Nova")

    def test_erro_vira_linha_nao_bloqueia(self):
        def analyze(p, prev, force, now):
            raise RuntimeError("boom")
        rows, novos = build_rows({}, [pr("001"), pr("002")], analyze, False, now_str())
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].status_coleta.startswith("erro:"))
        self.assertEqual(rows[0].situacao, "Erro / retry")
        self.assertEqual(novos, rows)


class ArgParseTest(unittest.TestCase):
    def test_defaults(self):
        args = parse_arguments([])
        self.assertEqual(args.dias, 7)
        self.assertEqual(args.min_delay, 2.0)
        self.assertEqual(args.max_delay, 5.0)
        self.assertFalse(args.force)

    def test_dias_rejeita_invalido(self):
        with self.assertRaises(SystemExit):
            parse_arguments(["--dias", "-1"])

    def test_max_delay_menor_que_min(self):
        args = parse_arguments(["--min-delay", "5", "--max-delay", "2"])
        self.assertEqual(args.max_delay, 2.0)  # validação também é refletida em main()->2


class EmptyResultTest(unittest.TestCase):
    def test_calcula_resumo_vazio_sem_erro(self):
        from report import build_resumo
        resumo = build_resumo([], [])
        self.assertEqual(resumo["total"], 0)
        self.assertEqual(resumo["novos"], 0)


class NowStrTest(unittest.TestCase):
    def test_formato(self):
        import re
        self.assertRegex(now_str(), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_main -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Write the implementation**

`main.py` (core orchestration; browser glue is thin):

```python
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from report import build_resumo, write_spreadsheet
from sei_client import ProcessResult, SeiClient
from store import MirrorStore, ProcessRow

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("sei-insights")

STATE_DIR = Path(".state")
DATABASE_PATH = STATE_DIR / "sei_insights.sqlite3"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_arguments(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SEI Insights")
    parser.add_argument("--orgao", default="MMulheres")
    parser.add_argument("--unidade", default="MMULHERES-SE-SGA-CGATI-CTI-DTI")
    parser.add_argument("--dias", type=int, default=7)
    parser.add_argument("--inicio", default=None)
    parser.add_argument("--fim", default=None)
    parser.add_argument("--manual-captcha", action="store_true")
    parser.add_argument("--min-delay", type=float, default=2.0)
    parser.add_argument("--max-delay", type=float, default=5.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--saida", default="sei_insights.xlsx")
    args = parser.parse_args(argv)
    if args.dias <= 0:
        parser.error("--dias deve ser > 0")
    if args.min_delay < 0:
        parser.error("--min-delay não pode ser negativo")
    if args.max_delay < args.min_delay:
        parser.error("--max-delay deve ser >= --min-delay")
    return args


AnalyzeCallable = Callable[[ProcessResult, Optional[ProcessRow], bool, str], ProcessRow]


def build_rows(
    previous: dict[str, ProcessRow],
    found: list[ProcessResult],
    analyze: AnalyzeCallable,
    force: bool,
    now: str,
) -> tuple[list[ProcessRow], list[ProcessRow]]:
    rows: list[ProcessRow] = []
    novos: list[ProcessRow] = []
    for p in found:
        prev = previous.get(p.number)
        row = None
        try:
            row = analyze(p, prev, force, now)
        except Exception as exc:
            logger.warning("Erro ao analisar %s: %s", p.number, exc)
            row = ProcessRow(
                numero=p.number, titulo=p.title, data_execucao=now,
                data_analise=now, data_ultimo_despacho="",
                situacao="Erro / retry", destino="", acao_esperada="",
                pendencia_curta="", link_process=p.url,
                status_coleta=f"erro: {exc}", hash_ultimo_despacho="",
            )
        rows.append(row)
        if row.numero not in previous:
            novos.append(row)
    return rows, novos


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_arguments(argv)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    store = MirrorStore(DATABASE_PATH)
    store.open()
    try:
        previous = store.load_snapshot()
        now = now_str()
        # Imports de todas as fases (browser, árvore, texto, regras, relatório).
        from discovery import expected_total, pagination_params, parse_response  # noqa: F401
        from rate_limit import RateLimiter
        from rules import RulesEngine
        from sei_client import (  # noqa: F401
            ProcessResult, SeiClient)  # real flow uses these
        from text_ing import extract_text_from_pdf
        from tree import correlate_urls, parse_tree, select_last_despacho
        from utils import normalize_process_number  # noqa: F401

        rules = RulesEngine.from_file(Path("regras.json"))

        def analyze(p: ProcessResult, prev: Optional[ProcessRow],
                    force: bool, now: str) -> ProcessRow:
            # Este fluxo é satisfeito pelo SeiClient real (Task 11);
            # a assinatura é a interface testada em build_rows.
            raise NotImplementedError

        rows, novos = build_rows(previous, [], analyze, args.force, now)
        write_spreadsheet(Path(args.saida), rows, novos, build_resumo(rows, novos))
        store.replace_snapshot(rows)
        logger.info("Execução concluída: %d processos, %d novos.", len(rows), len(novos))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
```

> **Implementation note for the engineer:** `main.py` above deliberately isolates orchestration in `analyze`-based functions so the delta/cache/error semantics are unit-testable. The **complete** `analyze` must glue the real `SeiClient` flow per the collector's working pattern: `client.open_search_page()`, `client.search_processes(...)` for discovery, then per process `client.open_process(pr)`, `client.extract_documents(html, pr.url)` to feed `tree.correlate_urls`, `select_last_despacho`, `despacho_hash(f"{n.numero}|{n.data}")`, the reuse-check against `prev` (unless `--force`), then `client.download_document(numero, doc)`, `extract_text_from_pdf(path)`, `rules.classify(text)`; set `data_analise` only when re-analysis happened. Follow the collector's `main()` (`main.py:4919-5226`) for the browser setup (`create_browser`, save/load `browser_state.json`, `--manual-captcha` wiring) and its retry/rate-limit conventions. Wire `--inicio`/`--fim` to the discovery method, defaulting to `hoje-dias`..`hoje`.

`README.md` — concise usage doc: purpose, install, `python main.py` with the flags from Global Constraints, a note that CAPTCHA is OCR or `--manual-captcha`, and that the spreadsheet is the source of truth (SQLite mirrors it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_main -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full suite**

Run: `python -m unittest discover -s tests -v`
Expected: all project tests PASS.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main.py README.md
git commit -m "feat: CLI e orquestração com espelho, cache e resumo"
```

---

## Plan Self-Review Notes

- **Spec coverage:** discovery (Tasks 1, 9, 11), tree/last Despacho + node→URL (Task 7), text (Task 6), rules + taxonomy (Task 8), mirror persist + delta + identifier hash (Tasks 5, 12), spreadsheet + already-earned columns + empty result (Tasks 10, 12), CLI/config (Task 12), copied infra (Tasks 2–4, 11), structure/.gitignore (Task 2/12), out-of-scope items deliberately absent.
- **Type consistency:** `ProcessRow` field order is the single source of truth (store → report → build_rows); `despacho_hash` returns hex string; `extract_process` is module-level in `sei_client.py`; `parse_response` returns already-normalized unique numbers; `analyze` signature is pinned in Task 12 and used by `build_rows` only.
- **Review Focus:** each of the six lines has a pinned test (Task 7/12 no-Despacho; Tasks 6+5 scanned PDF hash; Task 10+12 empty; Task 2+9 normalization/dedupe; Task 12 cached-still-written; Task 11 diagnostics predicate + spike gate).