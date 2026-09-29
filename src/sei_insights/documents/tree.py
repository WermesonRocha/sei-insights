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


def _inclusao_index(container) -> Optional[int]:
    """Índice da célula 'Data de Inclusão' na tabela da árvore (None se não achar).

    Na página real do processo a árvore é uma tabela (`table.infraTable`)
    com cabeçalho `Processo / Documento | Tipo | Data | Data de Inclusão |
    Unidade`; o link do documento traz só a série (`title`), e a data fica
    na coluna "Data de Inclusão". Procuramos a 1ª linha-cabeçalho cujas
    células contenham esse rótulo (o texto é específico o bastante para
    não colidir com as tabelas de metadados/andamentos).
    """
    for tr in container.find_all("tr"):
        cells = tr.find_all("th", recursive=False) or tr.find_all("td", recursive=False)
        for i, cell in enumerate(cells):
            if re.search(r"data\s+de\s+inclus", cell.get_text(" ", strip=True),
                         re.IGNORECASE):
                return i
    return None


def _row_date(row, inclusao_index: Optional[int]) -> str:
    """Data da linha: célula 'Data de Inclusão' quando existe; senão a do rótulo.

    Na tabela real o rótulo do link só tem a série, então a data vem da
    coluna "Data de Inclusão" (ex.: `29/09/2026 16:02` → `29/09/2026`).
    Nas árvores `li` (históricas/testes) a data já vem no rótulo.
    """
    if inclusao_index is not None:
        cells = row.find_all("td", recursive=False)
        if inclusao_index < len(cells):
            cell_text = cells[inclusao_index].get_text(" ", strip=True)
            m = DATE_RE.search(cell_text)
            if m:
                return m.group(1)
    return ""


def parse_tree(html: str) -> list[DocNode]:
    """Calibrado com o spike (Task 1). Default lê `li`/`tr` com rótulo."""
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one(".infraArvore")
    if container is None:
        container = soup
    inclusao = _inclusao_index(container)
    nodes: list[DocNode] = []
    for pos, row in enumerate(container.select("li, tr")):
        label_el = row.select_one("span.infraLabel, label, a[title]")
        label = ""
        if label_el is not None:
            label = label_el.get("title") or label_el.get_text(" ", strip=True) or ""
        if not label:
            continue
        date_m = DATE_RE.search(label)
        data = _row_date(row, inclusao) or (date_m.group(1) if date_m else "")
        num_m = NUM_RE.search(label)
        if num_m is None:
            checkbox = row.select_one("input[type='checkbox'][value]")
            if checkbox and checkbox.get("value"):
                num_m = NUM_RE.search(checkbox["value"])
        if num_m is None:
            continue
        first_word = label.strip().split()[0] if label.strip().split() else ""
        nodes.append(
            DocNode(
                serie=first_word,
                numero=num_m.group(1),
                data=data,
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
    """Retorna True se o rótulo NÃO contém número de documento (para links fallback)."""
    return NUM_RE.search(label) is None


def select_last_despacho(nodes: list[DocNode]) -> Optional[DocNode]:
    despachos = [n for n in nodes if "Despacho" in n.serie]
    if not despachos:
        return None
    dated = [d for d in despachos if d.data]
    if dated:
        max_date = max(d.data for d in dated)
        candidates = [d for d in dated if d.data == max_date]
        return max(candidates, key=lambda n: n.posicao)
    return max(despachos, key=lambda n: n.posicao)