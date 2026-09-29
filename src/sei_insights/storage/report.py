from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from sei_insights.storage.mirror import FIELDS, ProcessRow

# A planilha não repete data_execucao em cada linha (fica no Resumo da última
# execução); o espelho/DB continua com a coluna — mirror.FIELDS não muda.
SHEET_FIELDS = [f for f in FIELDS if f != "data_execucao"]

TEXT_FORMAT = "@"
TITLE_FONT = Font(bold=True, size=14)
SECTION_FONT = Font(bold=True)
HEADER_FONT = Font(bold=True)


def build_resumo(
    rows: list[ProcessRow],
    novos: list[ProcessRow],
    data_execucao: str = "",
    periodo: str = "",
) -> dict:
    por_situacao: dict[str, int] = {}
    por_status: dict[str, int] = {}
    for r in rows:
        por_situacao[r.situacao] = por_situacao.get(r.situacao, 0) + 1
        por_status[r.status_coleta] = por_status.get(r.status_coleta, 0) + 1
    return {
        "data_execucao": data_execucao,
        "periodo": periodo,
        "total": len(rows),
        "novos": len(novos),
        "por_situacao": por_situacao,
        "por_status": por_status,
    }


def _fill_sheet(sheet, rows: list[ProcessRow], fields: list[str]) -> None:
    sheet.append(fields)
    for r in rows:
        sheet.append([getattr(r, f) for f in fields])
    for ws_row in sheet.iter_rows(
        min_row=1, max_row=sheet.max_row, min_col=1, max_col=sheet.max_column
    ):
        for cell in ws_row:
            cell.number_format = TEXT_FORMAT


def _write_resumo_sheet(wb, resumo: dict) -> None:
    res = wb.create_sheet("Resumo da última execução")
    res.append(["Resumo da última execução"])
    res["A1"].font = TITLE_FONT
    res.append(["Data e hora da execução", resumo["data_execucao"]])
    res.append(["Período pesquisado", resumo["periodo"]])
    res.append([])
    res.append(["Visão geral"])
    res.cell(row=res.max_row, column=1).font = SECTION_FONT
    res.append(["Total de processos", resumo["total"]])
    res.append(["Novos", resumo["novos"]])
    res.append([])
    for rotulo, counts in (
        ("Por situação", resumo["por_situacao"]),
        ("Por status", resumo["por_status"]),
    ):
        res.append([rotulo])
        res.cell(row=res.max_row, column=1).font = SECTION_FONT
        res.append(["Classificação", "Quantidade"])
        res.cell(row=res.max_row, column=1).font = HEADER_FONT
        res.cell(row=res.max_row, column=2).font = HEADER_FONT
        for key, value in counts.items():
            res.append([key, value])
        res.append([])
    for ws_row in res.iter_rows(
        min_row=1, max_row=res.max_row, min_col=1, max_col=2
    ):
        for cell in ws_row:
            cell.number_format = TEXT_FORMAT


def write_spreadsheet(
    path: Path,
    rows: list[ProcessRow],
    resumo: dict,
) -> None:
    wb = Workbook()
    principal = wb.active
    principal.title = "Aba principal"
    _fill_sheet(principal, rows, SHEET_FIELDS)
    _write_resumo_sheet(wb, resumo)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    wb.close()