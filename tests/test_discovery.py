import unittest

from sei_insights.clients.discovery import expected_total, pagination_params, parse_response

ROW1 = ("<tr data-prot='21260.003436/2026-15'>"
        "<td><a href='md_pesq_processo_exibir.php?id=1'>Proc 1</a></td></tr>")
ROW2 = ("<tr data-prot='21260.003437/2026-16'>"
        "<td><a href='md_pesq_processo_exibir.php?id=2'>Proc 2</a> 21260.003437/2026-16</td></tr>")


class DiscoveryTest(unittest.TestCase):
    def test_parse_usa_data_prot_e_deduplica(self):
        data = {"itens": 2, "html": ROW1 + ROW2 + ROW1}
        result = parse_response(data)
        self.assertEqual(result, ["21260.003436/2026-15", "21260.003437/2026-16"])

    def test_parse_usa_texto_quando_sem_data_prot(self):
        html = ("<tr><td><a href='md_pesq_processo_exibir.php?id=3'>"
                "21260.003438/2026-17</a></td></tr>")
        self.assertEqual(parse_response({"itens": 1, "html": html}),
                         ["21260.003438/2026-17"])

    def test_parse_resultado_vazio(self):
        self.assertEqual(parse_response({"itens": 0, "html": "<div>vazio</div>"}), [])

    def test_expected_total(self):
        self.assertEqual(expected_total({"itens": 43}), 43)
        self.assertEqual(expected_total({}), 0)

    def test_pagination_params(self):
        self.assertEqual(pagination_params(50),
                         {"isPaginacao": "true", "inicio": 50, "rowsSolr": 50})