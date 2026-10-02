import unittest

from sei_insights.clients.discovery import (
    expected_total,
    extract_process_number,
    is_captcha_error,
    pagination_params,
    parse_response,
)
from sei_insights.clients.sei_client import extract_process

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


class NumeroDeProcessoInvalidoTest(unittest.TestCase):
    """Linha sem número de processo em formato não entra como se tivesse um.

    Bug real: a pesquisa do SEI mistura linhas de processo com linhas de
    documento gerado/recebido. A linha de documento traz o número do
    DOCUMENTO, e o parser usava o texto do link como número do processo —
    gravando `64534686` ou o rótulo inteiro ("Despacho64534686-05/07/2026")
    na planilha e no SQLite como se fosse a chave do processo.

    A linha é DESCARTADA, com aviso, porque um número inventado não é
    recuperável depois: ele vira pasta, nome de arquivo e linha da planilha.
    """

    def test_linha_de_documento_nao_entra_como_numero_de_processo(self):
        """Linha de documento: rótulo com nº do documento, número real na célula."""
        html = (
            "<tr class='pesquisaTituloRegistro'>"
            "<td><a href='md_pesq_processo_exibir.php?id=9'>"
            "Despacho 64534686 - 05/07/2026</a></td>"
            "<td>21260.003436/2026-15</td>"
            "</tr>"
        )
        self.assertEqual(parse_response({"itens": 1, "html": html}),
                         ["21260.003436/2026-15"])

    def test_linha_sem_numero_em_ponto_e_descartada(self):
        """Sem `data-prot` e sem célula com número válido, a linha é descartada.

        Este é o caso que gravava o rótulo inteiro como número de processo.
        """
        html = (
            "<tr class='pesquisaTituloRegistro'>"
            "<td><a href='md_pesq_processo_exibir.php?id=9'>"
            "Despacho 64534686 - 05/07/2026</a></td>"
            "<td>-</td>"
            "</tr>"
        )
        with self.assertLogs("sei-insights", level="WARNING") as cap:
            self.assertEqual(parse_response({"itens": 1, "html": html}), [])
        self.assertIn("64534686", "\n".join(cap.output))

    def test_numero_de_documento_como_data_prot_e_descartado(self):
        """`data-prot` com número de DOCUMENTO também não vale como processo.

        O `data-prot` do SEI traz o número do processo-pai na maioria das
        linhas, mas em linha de documento ele pode trazer o do documento.
        A validação do formato protege esse caso também.
        """
        html = ("<tr data-prot='60709407'>"
                "<td><a href='md_pesq_processo_exibir.php?id=9'>X</a></td></tr>")
        with self.assertLogs("sei-insights", level="WARNING"):
            self.assertEqual(parse_response({"itens": 1, "html": html}), [])

    def test_avisos_nao_saem_para_uma_busca_normal(self):
        """Uma busca com todos os números válidos não gera aviso."""
        with self.assertNoLogs("sei-insights", level="WARNING"):
            parse_response({"itens": 2, "html": ROW1 + ROW2})

    def test_formato_valido_com_espacos_e_aceito(self):
        html = ("<tr><td><a href='md_pesq_processo_exibir.php?id=4'>x</a></td>"
                "<td> 21260.003439/2026-18 </td></tr>")
        with self.assertNoLogs("sei-insights", level="WARNING"):
            self.assertEqual(parse_response({"itens": 1, "html": html}),
                             ["21260.003439/2026-18"])


class ExtractProcessRealTest(unittest.TestCase):
    """`extract_process` precisa achar o link pelo MESMO critério do parser.

    Onde `parse_response` lê o número, `extract_process` precisa ler também. Os
    dois usavam critérios diferentes: o parser lia `data-prot`, e o
    `extract_process` só comparava `data-prot` com o número pedido. Como o
    `data-prot` do SEI traz o número do DOCUMENTO, nenhum dos dois casava com o
    número do processo — e o `extract_process` devolvia `url=""`, o que fazia a
    navegação seguinte falhar com "Cannot navigate to invalid URL" em todos os
    processos da busca.
    """

    HTML = (
        "<table><tr class='pesquisaTituloRegistro'>"
        "<td class='pesquisaTituloEsquerda' data-prot='61941158'>"
        "Patrimônio: Gestão de Bens Móveis nº 21260.002471/2026-17 ( Despacho )"
        "</td><td>61941158</td>"
        "<td><a href='md_pesq_processo_exibir.php?id=ABC' title='Acessar'>"
        "</a></td></tr></table>"
    )

    def test_acha_o_link_pelo_numero_no_texto_da_linha(self):
        r = extract_process(self.HTML, "21260.002471/2026-17")
        self.assertIsNotNone(r, "não achou o processo pelo número real")
        self.assertEqual(r.url, "md_pesq_processo_exibir.php?id=ABC")

    def test_nao_devolve_url_vazia_para_processo_presente(self):
        """URL vazia é o que causava 'Cannot navigate to invalid URL'."""
        r = extract_process(self.HTML, "21260.002471/2026-17")
        self.assertTrue(r and r.url, "url vazia quebra a navegação do processo")

    def test_acha_pelo_data_prot_quando_ele_esta_em_formato_de_processo(self):
        """A variante em que o data-prot traz o processo continua funcionando."""
        html = ("<tr data-prot='21260.003436/2026-15'>"
                "<td><a href='md_pesq_processo_exibir.php?id=1'>Acessar</a></td></tr>")
        r = extract_process(html, "21260.003436/2026-15")
        self.assertIsNotNone(r)
        self.assertEqual(r.url, "md_pesq_processo_exibir.php?id=1")

    def test_devolve_none_quando_o_processo_nao_esta_no_html(self):
        self.assertIsNone(extract_process(self.HTML, "99999.999999/2026-99"))


class LinhaDeResultadoRealTest(unittest.TestCase):
    """Pina a estrutura REAL de uma linha de resultado do SEI.

    Esta é a estrutura medida no HTML ao vivo (01/10/2026), e ela derrubou uma
    busca inteira quando o parser exigiu que uma célula fosse IGUAL ao número do
    processo. Em produção:

      - `data-prot` traz o número do DOCUMENTO (`61941158`), não o do processo;
      - o número do PROCESSO está no meio do texto da primeira célula
        ("Patrimônio: Gestão de Bens Móveis nº 21260.002471/2026-17 ( Despacho )");
      - não existe célula que contenha apenas o número.

    O `/YYYY-NN` do padrão só existe em número de processo, então procurar o
    padrão DENTRO do texto não tem como pegar o número de documento.
    """

    LINHA_REAL = (
        "<tr class='pesquisaTituloRegistro'>"
        "<td class='pesquisaTituloEsquerda' data-prot='61941158'>"
        "Patrimônio: Gestão de Bens Móveis nº 21260.002471/2026-17 ( Despacho )"
        "</td>"
        "<td>61941158</td>"
        "<td><a href='md_pesq_processo_exibir.php?id=X'></a>"
        "<a href='md_pesq_processo_exibir.php?id=X'>21260.002471/2026-17</a></td>"
        "</tr>"
    )

    def test_extrai_processo_de_uma_linha_real_do_sei(self):
        with self.assertNoLogs("sei-insights", level="WARNING"):
            self.assertEqual(
                parse_response({"itens": 1, "html": self.LINHA_REAL}),
                ["21260.002471/2026-17"],
            )

    def test_data_prot_com_numero_de_documento_nao_vira_processo(self):
        """`data-prot` do SEI real traz o número do documento; não pode vencer.

        Se o parser preferisse o `data-prot`, a linha entraria como
        `61941158` e o processo real `21260.002471/2026-17` se perderia.
        """
        html = (
            "<tr class='pesquisaTituloRegistro'>"
            "<td class='pesquisaTituloEsquerda' data-prot='61941158'>"
            "Patrimônio: Gestão de Bens Móveis nº 21260.002471/2026-17"
            "</td>"
            "<td>61941158</td>"
            "<td><a href='md_pesq_processo_exibir.php?id=X'>Acessar</a></td>"
            "</tr>"
        )
        self.assertEqual(parse_response({"itens": 1, "html": html}),
                         ["21260.002471/2026-17"])

    def test_numero_de_documento_so_na_linha_e_descartado(self):
        """Linha sem nenhum número no formato de processo é descartada."""
        html = ("<tr class='pesquisaTituloRegistro'>"
                "<td class='pesquisaTituloEsquerda' data-prot='61941158'>"
                "Documento avulso 61941158</td>"
                "<td>61941158</td>"
                "<td><a href='md_pesq_processo_exibir.php?id=X'>Acessar</a></td>"
                "</tr>")
        with self.assertLogs("sei-insights", level="WARNING"):
            self.assertEqual(parse_response({"itens": 1, "html": html}), [])

    def test_links_aninhados_nao_geram_aviso_spam(self):
        """A linha real tem 2 links para o mesmo processo; não são 2 processos.

        Uma linha de resultado traz mais de um link para o mesmo processo, e
        Links aninhados em tabela interna (documentos do processo) não são
        linhas de resultado — contá-los como uma produce aviso falso.
        """
        html = (
            "<tr class='pesquisaTituloRegistro'>"
            "<td class='pesquisaTituloEsquerda' data-prot='61941158'>"
            "X nº 21260.002471/2026-17</td><td>61941158</td>"
            "<td><a href='md_pesq_processo_exibir.php?id=X'></a>"
            "<a href='md_pesq_processo_exibir.php?id=X'>21260.002471/2026-17</a>"
            "<table><tr><td><a href='md_pesq_processo_exibir.php?id=Y'>"
            "Anexo 61948579</a></td></tr></table></td>"
            "</tr>"
        )
        with self.assertNoLogs("sei-insights", level="WARNING"):
            self.assertEqual(parse_response({"itens": 1, "html": html}),
                             ["21260.002471/2026-17"])

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