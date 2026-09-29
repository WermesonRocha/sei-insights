import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from sei_insights.storage.report import build_resumo, write_spreadsheet
from sei_insights.storage.mirror import FIELDS, ProcessRow


def row(numero: str, situacao: str = "Na CTI", status: str = "concluído") -> ProcessRow:
    return ProcessRow(
        numero=numero, data_execucao="29/09/2026 16:45:12",
        data_ultimo_despacho="15/09/2026",
        situacao=situacao, destino="", acao_esperada="", pendencia_curta="",
        link_process="url", status_coleta=status, hash_ultimo_despacho="h",
    )


def _celula(ws, rotulo: str, coluna: int = 2):
    """Valor da primeira linha cuja coluna A == rotulo, na coluna dada."""
    for r in range(1, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == rotulo:
            return ws.cell(row=r, column=coluna).value
    raise KeyError(rotulo)


class ReportTest(unittest.TestCase):
    def test_abas_e_estrutura_principal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.xlsx"
            rows = [row("001", "Na CTI"), row("002", "Pendente de assinatura")]

            write_spreadsheet(path, rows, build_resumo(rows, [], "29/09/2026 16:45:12"))
            wb = load_workbook(path)
            self.assertEqual(wb.sheetnames, ["Aba principal", "Resumo da última execução"])

            principal = wb["Aba principal"]
            self.assertEqual(principal.max_row, len(rows) + 1)
            self.assertEqual(principal.max_column, 9)
            headers = [principal.cell(row=1, column=c).value
                       for c in range(1, principal.max_column + 1)]
            self.assertEqual(headers, [
                "numero", "data_ultimo_despacho", "situacao",
                "destino", "acao_esperada", "pendencia_curta", "status_coleta",
                "hash_ultimo_despacho", "link_process",
            ])
            self.assertNotIn("data_execucao", headers)
            self.assertEqual(principal.cell(row=2, column=1).value, "001")
            # O espelho/DB continua com data_execucao: nada foi mexido lá.
            self.assertIn("data_execucao", FIELDS)
            wb.close()

    def test_resumo_da_ultima_execucao_em_blocos(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resumo.xlsx"
            rows = [row("001", "Na CTI"), row("002", "Pendente de assinatura")]
            novos = [row("002", "Pendente de assinatura")]

            write_spreadsheet(
                path, rows,
                build_resumo(rows, novos, "29/09/2026 16:45:12",
                             "20/08/2026 a 29/09/2026"),
            )
            wb = load_workbook(path)
            res = wb["Resumo da última execução"]
            self.assertEqual(res["A1"].value, "Resumo da última execução")
            self.assertEqual(res["A2"].value, "Data e hora da execução")
            self.assertEqual(res["B2"].value, "29/09/2026 16:45:12")
            self.assertEqual(res["A3"].value, "Período pesquisado")
            self.assertEqual(res["B3"].value, "20/08/2026 a 29/09/2026")
            self.assertEqual(_celula(res, "Total de processos"), 2)
            self.assertEqual(_celula(res, "Novos"), 1)
            # Tabelas em colunas Rotulo|Quantidade, uma linha por categoria.
            self.assertEqual(_celula(res, "Na CTI"), 1)
            self.assertEqual(_celula(res, "Pendente de assinatura"), 1)
            wb.close()

    def test_status_tambem_em_tabela(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.xlsx"
            rows = [row("001", status="concluído"),
                    row("002", status="concluído (cache)"),
                    row("003", status="erro: x")]
            write_spreadsheet(path, rows, build_resumo(rows, [], "29/09/2026 16:45:12"))
            wb = load_workbook(path)
            res = wb["Resumo da última execução"]
            self.assertEqual(_celula(res, "concluído"), 1)
            self.assertEqual(_celula(res, "concluído (cache)"), 1)
            self.assertEqual(_celula(res, "erro: x"), 1)
            wb.close()

    def test_resultado_vazio_escreve_workbook_valido(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vazio.xlsx"
            write_spreadsheet(path, [], build_resumo([], [], ""))
            wb = load_workbook(path)
            self.assertEqual(wb.sheetnames, ["Aba principal", "Resumo da última execução"])
            self.assertEqual(wb["Aba principal"].max_row, 1)
            self.assertEqual(wb["Resumo da última execução"]["A1"].value,
                             "Resumo da última execução")
            self.assertEqual(
                _celula(wb["Resumo da última execução"], "Total de processos"), 0)
            wb.close()

    def test_numero_de_processo_forcado_como_texto(self):
        """Números de processo ('21260.002715/2026-53') contêm '-', '.', '/'.
        O Excel os trataria como número/erro; a célula deve usar formato Texto."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "texto.xlsx"
            rows = [row("21260.002715/2026-53"), row("21260.002716/2026-54")]
            write_spreadsheet(path, rows, build_resumo(rows, rows[:1], ""))
            wb = load_workbook(path)
            principal = wb["Aba principal"]
            for ws_row in principal.iter_rows(min_row=1, max_row=principal.max_row,
                                              min_col=1, max_col=principal.max_column):
                for cell in ws_row:
                    self.assertEqual(
                        cell.number_format, "@",
                        f"Aba principal!{cell.coordinate} deveria usar formato Texto",
                    )
            wb.close()