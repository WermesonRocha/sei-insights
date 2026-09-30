from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from sei_insights.utils.helpers import normalize_process_number


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


def count_rows(data: dict) -> int:
    """Conta as LINHAS de resultado, não os processos únicos.

    A pesquisa marca processos (P), documentos gerados (G) e documentos
    recebidos (R), e cada linha traz `data-prot` com o processo-pai: várias
    linhas do mesmo processo repetem o mesmo número. `parse_response` remove
    essa repetição, então a contagem de processos únicos NÃO serve para saber
    se a página veio cheia — é isto que define se há próxima página.
    """
    html = (data or {}).get("html", "") or ""
    if not html:
        return 0
    return len(BeautifulSoup(html, "html.parser").select("[data-prot]"))


def expected_total(data: dict) -> int:
    try:
        return int(data.get("itens") or 0)
    except (TypeError, ValueError):
        return 0


# Textos que o SEI usa para rejeitar o CAPTCHA (HTTP 200). Variantes vistas em
# produção: "Código de confirmação inválido 1.", "Código de confirmação inválido".
CAPTCHA_ERROR_PATTERNS = (
    r"c[oó]digo de confirma[çc][ãa]o inv[aá]lido",
    r"confirma[çc][ãa]o inv[aá]lido",
    r"captcha inv[aá]lido",
    r"c[oó]digo de seguran[çc]a inv[aá]lido",
)


def is_captcha_error(data: dict) -> bool:
    """Indica se a resposta AJAX é um CAPTCHA rejeitado (não "sem resultados").

    Quando o OCR erra o CAPTCHA, o SEI NÃO responde 4xx: responde 200 com o
    HTML de erro dentro de `.sem-resultado`, que o parser de resultados lê
    como "nenhum processo encontrado". Sem esta detecção a busca reporta 0
    resultados silenciosamente (bug real: período de 3 meses voltou vazio).

    Retorna False para busca legitimamente vazia ("Nenhum documento
    localizado.") — essa é a diferença entre "erro" e "não encontrado".
    """
    html = (data or {}).get("html", "") or ""
    if not html:
        return False
    return any(re.search(pattern, html, re.IGNORECASE) for pattern in CAPTCHA_ERROR_PATTERNS)


def pagination_params(inicio: int, rows_solr: int = 50) -> dict:
    return {"isPaginacao": "true", "inicio": inicio, "rowsSolr": rows_solr}


PROCESS_NUMBER_PATTERN = r"\d{4,5}\.\d{6,8}/\d{4}-\d{2}"


def extract_process_number(html: str) -> str:
    """Extrai o número canônico do processo do cabeçalho `#tblCabecalho`.

    Exemplo (página real do SEI): `<b>Processo:</b><td>21260.002715/2026-53</td>`.
    Retorna "" (e o número descoberto é preservado) quando o cabeçalho não
    contém um número de processo no formato NNNNN.NNNNNN/YYYY-NN.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find(id="tblCabecalho")
    if table is None:
        return ""
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label = normalize_process_number(cells[0].get_text(" ", strip=True))
        if label != "Processo:":
            continue
        number = normalize_process_number(cells[1].get_text(" ", strip=True))
        if re.fullmatch(PROCESS_NUMBER_PATTERN, number):
            return number
    return ""