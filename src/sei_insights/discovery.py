from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from sei_insights.utils import normalize_process_number


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