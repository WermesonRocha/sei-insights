import unittest

from sei_insights.clients.discovery import (
    expected_total,
    extract_process_number,
    is_captcha_error,
    pagination_params,
    parse_response,
)

ROW1 = ("<tr data-prot='21260.003436/2026-15'>"
        "<td><a href='md_pesq_processo_exibir.php?id=1'>Proc 1</a></td></tr>")
ROW2 = ("<tr data-prot='21260.003437/2026-16'>"
        "<td><a href='md_pesq_processo_exibir.php?id=2'>Proc 2</a> 21260.003437/2026-16</td></tr>")

# HTML real do SEI quando o OCR erra o CAPTCHA (diagnóstico ao vivo).
CAPTCHA_ERROR_HTML = (
    "<consultavazia><div class='sem-resultado'>"
    "<p class='alert alert-danger'>Código de confirmação inválido 1.</p>"
    "</div></consultavazia>"
)


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

    def test_extrai_numero_canonico_do_cabecalho(self):
        html = (
            "<table id='tblCabecalho'>"
            "<tr><td><b>Processo:</b></td><td> 21260.002715/2026-53 </td></tr>"
            "<tr><td><b>Tipo:</b></td><td>Casa da Mulher Brasileira</td></tr>"
            "</table>"
        )
        self.assertEqual(extract_process_number(html), "21260.002715/2026-53")

    def test_extrai_vazio_com_linha_sem_numero_de_processo(self):
        html = (
            "<table id='tblCabecalho'>"
            "<tr><td><b>Processo:</b></td><td>não consta</td></tr>"
            "</table>"
        )
        self.assertEqual(extract_process_number(html), "")

    def test_extrai_vazio_sem_cabecalho(self):
        self.assertEqual(extract_process_number("<html><body>oi</body></html>"), "")


class CaptchaErrorTest(unittest.TestCase):
    """Pina a detecção de CAPTCHA rejeitado pelo SEI.

    Bug real: quando o OCR erra, o SEI responde 200 OK com o HTML
    "Código de confirmação inválido" dentro de `.sem-resultado` — o parser
    via zero processos e a busca parecia "sem resultados" no período.
    """

    def test_detecta_captcha_invalido(self):
        self.assertTrue(is_captcha_error({"html": CAPTCHA_ERROR_HTML}))

    def test_detecta_captcha_invalido_sem_envelope_sem_resultado(self):
        html = "<p class='alert alert-danger'>Código de confirmação inválido 7.</p>"
        self.assertTrue(is_captcha_error({"html": html}))

    def test_nao_detecta_em_html_vazio(self):
        self.assertFalse(is_captcha_error({"html": ""}))
        self.assertFalse(is_captcha_error({}))

    def test_nao_detecta_em_pagina_com_resultados(self):
        self.assertFalse(is_captcha_error({"html": ROW1 + ROW2}))

    def test_nao_detecta_em_busca_legitima_sem_resultado(self):
        html = ("<div class='sem-resultado'>"
                "<p>Nenhum documento localizado.</p></div>")
        self.assertFalse(is_captcha_error({"html": html}))