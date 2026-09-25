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


def expected_total(data: dict) -> int:
    try:
        return int(data.get("itens") or 0)
    except (TypeError, ValueError):
        return 0


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