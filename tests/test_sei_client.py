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


class BridgeTest(unittest.TestCase):
    """Testes herméticos da ponte resultado->link (sem navegador)."""

    def setUp(self):
        self.client = SeiClient(None, None, None)

    def test_find_process_link_resolve_para_url_absoluta(self):
        data = {
            "html": ("<div><tr data-prot='21260.003436/2026-15'>"
                     "<td><a href='md_pesq_processo_exibir.php?id=9'>Título</a></td>"
                     "</tr></div>")
        }
        link = self.client._find_process_link("21260.003436/2026-15", data)
        self.assertTrue(link.startswith("https://"))
        self.assertTrue(link.endswith("md_pesq_processo_exibir.php?id=9"))

    def test_find_process_link_sem_resultado(self):
        self.assertEqual(self.client._find_process_link("21260.003436/2026-15", {"html": ""}), "")

    def test_add_result_deduplica_por_numero(self):
        data = {
            "html": ("<div><tr data-prot='21260.003436/2026-15'>"
                     "<td><a href='md_pesq_processo_exibir.php?id=9'>Título</a></td>"
                     "</tr></div>")
        }
        results: dict = {}
        self.client._add_result(results, "21260.003436/2026-15", data)
        self.client._add_result(results, "21260.003436/2026-15", data)
        self.assertEqual(len(results), 1)
        result = results["21260.003436/2026-15"]
        self.assertEqual(result.number, "21260.003436/2026-15")
        self.assertTrue(result.url.endswith("md_pesq_processo_exibir.php?id=9"))