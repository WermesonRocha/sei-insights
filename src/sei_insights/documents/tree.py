from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

log = logging.getLogger("sei-insights")

DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
NUM_RE = re.compile(r"\b(\d{5,})\b")


def _data_ordem(valor: str) -> tuple[int, int, int]:
    """Chave de ordenação CRONOLÓGICA para uma data em `dd/mm/aaaa`.

    Comparar `dd/mm/aaaa` como texto ordena errado: "30/06/2026" é maior
    que "05/07/2026" para o Python, mas julho é posterior a junho. O
    erro só aparece quando o dia muda de dezena (19 -> 20, 29 -> 30),
    que é justamente o caso comum de virada de mês e de ano.

    Devolve (ano, mês, dia), que ordena como inteiro em qualquer
    combinação. Uma data que não existe no calendário (`31/02/2026`,
    `99/99/9999`) ordena como a MENOR possível, nunca como a maior: uma
    data ilegível não pode ser promovida a "despacho mais recente" e
    descartaria o andamento real do processo. O objetivo aqui é apenas
    escolher entre datas, então uma data ilegível perde para qualquer
    data real em vez de derrubar a escolha.
    """
    try:
        dia, mes, ano = (int(parte) for parte in valor.split("/"))
        return date(ano, mes, dia).timetuple()[:3]
    except (ValueError, TypeError):
        return (date.min.year, date.min.month, date.min.day)


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


def _indice_inclusao_da_linha(row, global_index: Optional[int]) -> Optional[int]:
    """Índice de 'Data de Inclusão' a usar para ESTA linha.

    Quando a página não tem `.infraArvore`, o `global_index` pode ter vindo
    de outra tabela (metadados, andamentos). Reaproveitá-lo faria o parser ler
    uma coluna sem significado na tabela desta linha e gravar uma data real
    porém errada. Nesses casos o índice só é aceito se a PRÓPRIA tabela da
    linha confirmar que aquela coluna é mesmo a de inclusão.
    """
    if global_index is None:
        return None
    table = row.find_parent("table")
    if table is None:
        return global_index       # árvore `li`: não há tabela, índice vale
    return _localiza_coluna_inclusao(table)


def _localiza_coluna_inclusao(
    table,
) -> Optional[int]:
    """Índice de 'Data de Inclusão' **dentro desta tabela** (None se não houver).

    `_inclusao_index` acha o índice de uma coluna numa página e aplica a
    todas as linhas da página. Isso só vale se todas as linhas pertencerem
    à mesma tabela. Na página real do SEI o cabeçalho da árvore está
    dentro de `.infraArvore`; o `fallback = soup` (quando a div não é
    encontrada) misturo a árvore com tabelas de metadados, e aí um índice
    achado nos metadados aponta para uma coluna sem significado na árvore.

    Um índice herdado de outra tabela não deve ser usado: ele produz uma
    data REAL, mas errada — pior que data vazia, porque passa despercebida
    e ainda pode virar classificação errada. Por isso, na ausência de
    `.infraArvore`, o índice só vale se o cabeçalho tiver sido achado na
    PRÓPRIA tabela da linha.
    """
    for tr in table.find_all("tr"):
        cells = tr.find_all("th", recursive=False) or tr.find_all("td", recursive=False)
        for i, cell in enumerate(cells):
            if re.search(r"data\s+de\s+inclus", cell.get_text(" ", strip=True),
                         re.IGNORECASE):
                return i
    return None


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
        data = _row_date(row, _indice_inclusao_da_linha(row, inclusao))
        if not data and date_m:
            data = date_m.group(1)
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


def despachos_ordenados(nodes: list[DocNode]) -> list[DocNode]:
    """Despachos candidatos a "último", do MAIS RECENTE ao mais antigo.

    A lista existe para o fallback: o Despacho mais recente pode não ter
    download público (restrito), e nesse caso o processo ainda tem andamento
    a ler em um Despacho anterior, público. Ler o mais antigo possível é pior
    que ler o anterior, então a ordem tem de ser a mesma da escolha única:
    cronológica, com desempate pela posição.

    Despacho sem data legível é DESCARTADO quando existe algum datado. É
    deliberado: sem data não há como ordenar contra datas reais sem inventar
    critério, e promover um nó sem data poderia trocar o andamento correto por
    um Unknown. A posição na árvore só decide quando nenhum Despacho tem data.
    O descarte é avisado no log, porque é a diferença entre "este processo parou
    em 30/06" e "o despacho de 05/07 veio sem data e foi ignorado" — falhas que
    seem iguais na planilha e exigem ações opostas.
    """
    despachos = [n for n in nodes if "Despacho" in n.serie]
    if not despachos:
        return []

    dated = [d for d in despachos if d.data]
    sem_data = [d for d in despachos if not d.data]

    if dated:
        # Cronológica, e não textual: em `dd/mm/aaaa` a comparação de string
        # faz o despacho mais antigo vencer sempre que o dia muda de dezena
        # ("30/06" > "05/07"), e o script passa a reportar um andamento antigo
        # como se fosse o atual. Empate de data vai para o ÚLTIMO da árvore
        # (maior `posicao`): o SEI traz só dia/mês/ano, sem hora, então a
        # posição é a melhor aproximação para desempatar. Medido em 40
        # processos abertos ao vivo: 4 (10%) tinham 2+ Despachos na data mais
        # recente, e o desempate por posição maior escolheu o mesmo em todos.
        candidatos = sorted(
            dated,
            key=lambda n: (_data_ordem(n.data), n.posicao),
            reverse=True,
        )
        if sem_data:
            numeros = ", ".join(
                f"{d.numero or '(sem número)'}[{d.posicao}]" for d in sem_data
            )
            log.warning(
                "Descartei %d Despacho(s) sem data legível que podem ser mais "
                "recentes: %s. Escolhi %s, de %s, por ser datado. "
                "Se este processo andou depois de %s, confira a coluna "
                "'Data de Inclusão' da árvore no SEI — pode haver um despacho "
                "mais recente que o script não conseguiu ler.",
                len(sem_data), numeros, candidatos[0].numero,
                candidatos[0].data, candidatos[0].data,
            )
        return candidatos

    if not sem_data:
        return []

    # Sem uma única data não há ordenação possível: a posição na árvore é o
    # único critério, e ela vale menos que uma data real.
    candidatos = sorted(sem_data, key=lambda n: n.posicao, reverse=True)
    log.warning(
        "Nenhum dos %d Despacho(s) da árvore tem data legível. "
        "Escolhido por posição: %s[%d]. Sem data não dá para comparar "
        "com o histórico de andamentos anteriores, então a "
        "classificação deste processo fica menos confiável.",
        len(sem_data), candidatos[0].numero, candidatos[0].posicao,
    )
    return candidatos


def select_last_despacho(nodes: list[DocNode]) -> Optional[DocNode]:
    """Escolhe o Despacho mais RECENTE, que é o andamento atual do processo.

    É o primeiro de `despachos_ordenados`, que concentra a regra de ordenação.
    """
    candidatos = despachos_ordenados(nodes)
    return candidatos[0] if candidatos else None
