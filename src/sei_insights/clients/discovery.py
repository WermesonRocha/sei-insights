from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from sei_insights.utils.helpers import normalize_process_number

log = logging.getLogger("sei-insights")

# Formato de número de processo SEI: <unidade>.<sequencial>/<ano>-<julgamento>
#
# O prefixo da unidade NÃO tem largura fixa: no SEI ColaboraGov os 8 prefixos
# observados têm 5 dígitos (21260, 19974, 14021, 12600, 12804, 10199, 03101,
# 00135), mas o formato em si admite outros. Por isso `\d{4,}` e NÃO `.{4,5}`:
# limitar a 5 dígitos faz o `re.search` casar a partir do dígito errado e
# truncar `121260.002471/2026-17` para `21260.002471/2026-17`, gravando um
# processo que não existe.
#
# O `\d+` do prefixo é o que impede a truncagem, desde que não possa começar no
# meio de outro número: `(?<!\d)` recusa os dígitos que ficariam de fora pela
# esquerda e `(?!\d)` os que sobrariam pela direita. Sem as duas âncoras, um
# prefixo mais curto casaria dentro de um mais longo — inventando o número.
#
# O `/AAAA-NN` do fim é o que dá segurança ao resto: só número de processo tem
# essa barra seguida de ano e julgamento. Número de documento (61941158,
# 64534686) e rótulo de linha ("Despacho64534686-05/07/2026") não casam.
PROCESS_NUMBER_PATTERN = r"(?<!\d)\d{4,}\.\d{6,8}/\d{4}-\d{2}(?!\d)"


def _numero_processo_da_linha(row) -> str:
    r"""Número do processo da linha de resultado, ou "" se não houver.

    Estrutura real de uma linha de resultado (medida no HTML ao vivo do SEI):

        <tr class="pesquisaTituloRegistro">
          <td class="pesquisaTituloEsquerda" data-prot="61941158">
            Patrimônio: Gestão de Bens Móveis nº 21260.002471/2026-17 ( Despacho )
          </td>
          <td>61941158</td>
        </tr>

    Ou seja: `data-prot` traz o número do DOCUMENTO, e o número do PROCESSO
    aparece no meio do texto da primeira célula. Não existe célula que contenha
    só o número, então exigir igualdade total (`fullmatch`) não funciona — foi o
    que zerou uma busca real inteira. O número do processo tem de ser procurado
    dentro do texto.

    A busca pelo padrão dentro do texto é segura porque o `/YYYY-NN` só existe em
    número de processo: o número de documento (`61941158`, `64534686`) nunca
    casa com o padrão.

    A busca é nesta ordem:

    1. `data-prot`, quando ele está no formato de processo. No SEI real ele
       traz o número do DOCUMENTO, que é rejeitado pelo formato e não atrapalha.
    2. o padrão de número de processo procurado dentro do texto das células.

    No HTML real medido, o `data-prot` está no `<td>`, que é FILHO do `<tr>`:
    nem `row.get("data-prot")` nem `find_parent` o alcançam. Por isso o passo 1
    procura o atributo na própria linha E nos descendentes, senão ele nunca
    executa e o passo 2 faz todo o trabalho (o que funcionava, mas deixava o
    passo 1 como código morto).

    Antes, sem validação alguma, a linha entrava com o número do documento ou
    com o rótulo inteiro ("Despacho64534686-05/07/2026") no lugar do processo, e
    esse número errado ia para a planilha e para o SQLite como chave do processo.
    """
    if row is None:
        return ""

    for elemento in [row, *row.select("[data-prot]")]:
        candidato = normalize_process_number(elemento.get("data-prot") or "")
        if re.fullmatch(PROCESS_NUMBER_PATTERN, candidato):
            return candidato

    for cell in row.find_all(["td", "th"]):
        texto = normalize_process_number(cell.get_text(" ", strip=True))
        m = re.search(PROCESS_NUMBER_PATTERN, texto)
        if m:
            return m.group(0)
    return ""


def parse_response(data: dict) -> list[str]:
    html = data.get("html", "") or ""
    soup = BeautifulSoup(html, "html.parser")
    seen: list[str] = []
    seen_set: set[str] = set()
    descartadas: list[str] = []
    for a in soup.select('a[href*="md_pesq_processo_exibir.php"]'):
        row = a.find_parent("tr")
        if row is not None and row.find_parent("tr") is not None:
            # Link aninhado em outra tabela dentro da própria linha do
            # resultado (o SEI abre os documentos do processo ali). Não é uma
            # linha de resultado: o processo já foi lido na linha de fora.
            continue
        number = _numero_processo_da_linha(row)
        if not number:
            rotulo = a.get_text(" ", strip=True)[:60] or "(sem rótulo)"
            descartadas.append(rotulo)
            continue
        if number not in seen_set:
            seen_set.add(number)
            seen.append(number)
    if descartadas:
        log.warning(
            "Descartadas %d linha(s) de resultado sem número de processo "
            "em formato unidade.sequencial/ano-julgamento: %s. "
            "Provavelmente linhas de documento cujo número é o do documento, "
            "não o do processo. Não entram na planilha para não gravar um "
            "número errado como se fosse o processo.",
            len(descartadas), "; ".join(descartadas[:5]),
        )
    return seen


def count_rows(data: dict) -> int:
    """Conta as LINHAS de resultado, não os processos únicos.

    A pesquisa marca processos (P), documentos gerados (G) e documentos
    recebidos (R), e cada linha traz `data-prot` com o processo-pai: várias
    linhas do mesmo processo repetem o mesmo número. `parse_response` remove
    essa repetição, então a contagem de processos únicos NÃO serve para saber
    se a página veio cheia.

    A classe `pesquisaTituloRegistro` é a que o próprio JS do SEI conta em
    `verificarRegistros()` ($('table tbody tr.pesquisaTituloRegistro').length),
    então é a contagem mais fiel; `data-prot` cobre as linhas que vierem sem
    essa classe.
    """
    html = (data or {}).get("html", "") or ""
    if not html:
        return 0
    soup = BeautifulSoup(html, "html.parser")
    return max(len(soup.select("tr.pesquisaTituloRegistro")),
               len(soup.select("[data-prot]")))


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


def extract_process_number(html: str) -> str:
    """Extrai o número canônico do processo do cabeçalho `#tblCabecalho`.

    Exemplo (página real do SEI): `<b>Processo:</b><td>21260.002715/2026-53</td>`.
    Retorna "" (e o número descoberto é preservado) quando o cabeçalho não
    contém um número de processo no formato unidade.sequencial/ano-julgamento.
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