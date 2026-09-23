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
    container = soup.select_one(".infraArvore")
    if container is None:
        container = soup
    nodes: list[DocNode] = []
    for pos, row in enumerate(container.select("li, tr")):
        label_el = row.select_one("span.infraLabel, label, a[title]")
        label = ""
        if label_el is not None:
            label = label_el.get("title") or label_el.get_text(" ", strip=True) or ""
        if not label:
            continue
        date_m = DATE_RE.search(label)
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
    """Return True if label does NOT contain a document number (for fallback links)."""
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