import unittest

from sei_insights.clients.sei_client import SeiClient, extract_process  # extract_process is a module function below


class FakeResponse:
    def __init__(self, method: str, url: str):
        self.method = method
        self.url = url


class FakeRequest:
    def __init__(self, method: str, url: str):
        self.method = method
        self.url = url


class FakeResp:
    def __init__(self, method: str, url: str):
        self.request = FakeRequest(method, url)


class IsSearchResponseTest(unittest.TestCase):
    def test_reconhece_post_de_pesquisa(self):
        r = FakeResp("POST",
                     "https://colaboragov.sei.gov.br/sei/modulos/pesquisa/"
                     "md_pesq_controlador_ajax_externo.php"
                     "?acao_ajax_externo=protocolo_pesquisar&isPaginacao=false")
        self.assertTrue(SeiClient.is_search_response(r))

    def test_rejeita_get(self):
        r = FakeResp("GET", "?acao_ajax_externo=protocolo_pesquisar&isPaginacao=false")
        self.assertFalse(SeiClient.is_search_response(r))

    def test_rejeita_outro_ajax(self):
        r = FakeResp("POST", "?acao_ajax_externo=outra_coisa&isPaginacao=false")
        self.assertFalse(SeiClient.is_search_response(r))


class ExtractProcessTest(unittest.TestCase):
    def test_acha_por_data_prot(self):
        html = ("<div><tr data-prot='21260.003436/2026-15'>"
                "<td><a href='md_pesq_processo_exibir.php?id=9'>Título X</a></td>"
                "</tr></div>")
        result = extract_process(html, "21260.003436/2026-15")
        self.assertIsNotNone(result)
        self.assertEqual(result.number, "21260.003436/2026-15")
        self.assertTrue(result.url.endswith("md_pesq_processo_exibir.php?id=9"))

    def test_nao_acha_nada(self):
        self.assertIsNone(extract_process("<html></html>", "21260.003436/2026-15"))