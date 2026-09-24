# SEI Insights — Reorganização em src-layout — Design

Data: 2026-09-24
Status: aprovado (brainstorming)

## 1. Contexto e objetivo

O projeto `sei-insights` tem todos os módulos Python na raiz do repositório
(`main.py`, `sei_client.py`, `discovery.py`, `tree.py`, `text_ing.py`,
`rules.py`, `store.py`, `report.py`, `captcha_solver.py`, `rate_limit.py`,
`utils.py`). O pedido é reorganizar a arquitetura em pastas corretas.

Decisões tomadas no brainstorming:

- **Profundidade**: organizar em pacotes **sem mudar comportamento** (lógica
  idêntica, apenas movimentação de arquivos e ajuste de imports).
- **Layout**: **src-layout** (`src/sei_insights/`).
- **Organização interna**: **pacote único plano** (sem subpacotes).
- **Pacote**: manter `pyproject.toml` para importabilidade e comando
  `sei-insights`.

## 2. Escopo e não-escopo

No escopo:

- mover os 11 módulos para `src/sei_insights/`;
- renomear `main.py` → `cli.py` e criar `__main__.py`;
- ajustar imports internos para `sei_insights.*`, incluindo os alvos de
  `mock.patch`/`patch` nos testes (§4);
- renomear `test_main.py` → `test_cli.py` e ajustar imports dos testes;
- criar `pyproject.toml`;
- atualizar o `.gitignore` (acrescenta `*.egg-info/`, `build/`, `dist/` às 6
  entradas atuais);
- atualizar o README (tabela de estrutura, comandos de execução e teste).

Fora de escopo (a não ser que seja necessário para a etapa de staging):

- `.worktrees/sei-insights` (worktree em outro branch);
- arquivos `SEI_ColaboraGov_handoff_context.*` (deletados no working tree);
- `.superpowers/` e `.state/`;
- mudança de lógica de qualquer função/regra/constante;
- comportamento de `regras.json` (permanece na raiz, config editável,
  resolução relativa ao CWD, como hoje).

> **Staging:** o `git status` contém deleções não-rascunhadas
> (`SEI_ColaboraGov_handoff_context.*`) e `.worktrees/` não rastreado. Para o
> commit da reorganização, nunca use `git add -A` nem `git add -u .` (ambos
> re-encenariam as deleções de handoff). Em vez disso:
> - `git mv` para cada um dos 11 módulos (ex.: `git mv main.py src/sei_insights/cli.py`,
>   `git mv sei_client.py src/sei_insights/sei_client.py`, ...) e para
>   `tests/test_main.py` → `tests/test_cli.py` — o `git mv` registra deleção +
>   adição em um passo, garantindo que nenhum módulo antigo fique "órfão" na raiz;
> - `git add` para os arquivos genuinamente novos (`src/sei_insights/__init__.py`,
>   `__main__.py`, `pyproject.toml`) e modificados (`README.md`, `.gitignore`);

## 3. Estrutura de destino

```
sei-insights/
├── pyproject.toml              # NOVO
├── README.md                   # atualizado
├── regras.json                 # mantido na raiz
├── requirements.txt            # mantido (fonte única de dependências)
├── .gitignore                  # atualizado (*.egg-info/, build/, dist/)
├── docs/                       # mantido (spike + specs superpowers)
├── src/
│   └── sei_insights/
│       ├── __init__.py         # NOVO
│       ├── __main__.py         # NOVO: sys.exit(main()) via cli.main()
│       ├── cli.py              # ANTIGO main.py
│       ├── sei_client.py       # movido
│       ├── discovery.py        # movido
│       ├── tree.py             # movido
│       ├── text_ing.py         # movido
│       ├── rules.py            # movido
│       ├── store.py            # movido
│       ├── report.py           # movido
│       ├── captcha_solver.py   # movido
│       ├── rate_limit.py       # movido
│       └── utils.py            # movido
└── tests/                      # mantido flat
    ├── __init__.py             # existente
    ├── test_cli.py             # ANTIGO test_main.py
    ├── test_sei_client.py      # movido
    ├── test_discovery.py       # movido
    ├── test_tree.py            # movido
    ├── test_text_ing.py        # movido
    ├── test_rules.py           # movido
    ├── test_store.py           # movido
    ├── test_report.py          # movido
    ├── test_captcha_solver.py  # movido
    ├── test_rate_limit.py      # movido
    └── test_utils.py           # movido
```

## 4. Renomes e imports

| Arquivo atual    | Destino                     |
| ---------------- | --------------------------- |
| `main.py`        | `sei_insights/cli.py` + `__main__.py` |
| `test_main.py`   | `tests/test_cli.py`         |

- Imports internos: `from discovery import ...` → `from sei_insights.discovery import ...`;
  `from store import ProcessRow` → `from sei_insights.store import ProcessRow`; etc.
- Exceção única à regra genérica: `tests/test_cli.py` (antigo `test_main.py`) tem
  `from main import build_rows, now_str, parse_arguments` → `from sei_insights.cli import ...`
  (o módulo `main` virou `cli`; a regra "from X → from sei_insights.X" produziria o
  inexistente `sei_insights.main`).
- Alvos de `mock.patch`/`patch` nos testes são strings e também mudam:
  `rate_limit.time.sleep` → `sei_insights.rate_limit.time.sleep` (idem
  `random.uniform`, `time.monotonic`); `captcha_solver.CaptchaSolver.solve_from_base64`
  → `sei_insights.captcha_solver.CaptchaSolver.solve_from_base64`.
- `mock.patch("rate_limit...")` resolve o módulo por import; sem a reescrita,
  os testes de `test_rate_limit.py` e `test_captcha_solver.py` quebram com
  `ModuleNotFoundError`.
- Nomes de funções/classes/constantes **não mudam** (`MirrorStore`, `RulesEngine`,
  `SeiClient`, `build_rows`, `now_str`, `parse_arguments`, `main`, `FIELDS`, ...).
- `__main__.py` contém o bloco que antes era `if __name__ == "__main__"`:
  `from sei_insights.cli import main` + `sys.exit(main())`.

## 5. pyproject.toml

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

- Dependências lidas de `requirements.txt` (fonte única, sem duplicação).
- Sem `package-data` necessário: `regras.json` não faz parte do pacote.

## 6. Execução e testes

- **Pré-requisito:** `pip install -e .` (install editável) é **obrigatório** para
  `python -m sei_insights` (falha com `ModuleNotFoundError` sem ele) e para o
  comando `sei-insights` (que **nem existe** sem o install). Em src-layout a pasta
  `src/` não fica no `sys.path` por padrão. Hoje `python main.py` funciona sem
  instalar nada — esse é o trade-off aceito do src-layout e deve ficar explícito
  no README.
- Execução: `sei-insights <opções>` (após `pip install -e .`) ou
  `python -m sei_insights <opções>`.
- Testes: `pip install -e .` e depois `python -m unittest discover -s tests -v`,
  **a partir da raiz do repositório** — `test_rules.py` lê `regras.json`
  relativo ao CWD (comportamento inalterado, porém CWD-dependente).
- O README é atualizado para documentar o pré-requisito de instalação e as
  ordenações acima.

## 6.1 Ambiente canônico

O repositório não tem `.venv` e o Python global (3.14.7) não tem `setuptools`
nem todas as dependências (`openpyxl` e `pypdf` estão ausentes hoje — a suíte
atual roda com 3 erros). Para que a verificação (§7) compare "antes" e "após"
com o único delta sendo a movimentação de arquivos, usamos um ambiente único:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # provisiona deps sem depender do layout
```

Todas as execuções de teste usam `.venv\Scripts\python`. O `pip install -e .`
(após o move) **não altera** o conjunto de dependências — já instaladas — apenas
registra o pacote editável no ambiente. Primeiro passo do plano de implementação:
verificar que `pip install -e .` funciona nesta máquina (Windows/Python 3.14),
antes de qualquer movimentação.

## 7. Verificação

1. **Antes** da movimentação: com o venv provisionado (§6.1), rodar a suíte e
   registrar pass/skip/fail (base). O conjunto de skips reflete apenas
   dependências opcionais (`test_captcha_solver` pula se `ddddocr` ausente).
2. **Após**: ativar o venv, `pip install -e .`, rodar a mesma suíte da raiz —
   resultado idêntico à base (mesmo pass/skip/fail).
3. `git status` limpo: `*.egg-info/`, `build/`, `dist/` ignorados; nenhuma
   deleção de handoff nem `.worktrees/` no commit (staging por `git mv` +
   `git add`, §2); **módulos antigos da raiz removidos** (sem duplicação raiz + `src/`).
4. Diff de lógica: corpos das funções são cópias exatas; diferenças apenas em
   imports e no bloco `__main__`.
5. Smoke test na raiz com venv: `python -m sei_insights --help` e
   `sei-insights --help`.
6. README: tabela "Estrutura do projeto", seção "Testes" e **todos** os blocos
   de execução com `python main.py` e as seções `pip install -r requirements.txt`
   substituídos pelos novos comandos.