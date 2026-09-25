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


def _result_rows(numbers) -> str:
    rows = ""
    for number in numbers:
        rows += (
            f"<div><tr data-prot='{number}'>"
            f"<td><a href='md_pesq_processo_exibir.php?id={number}'>T</a></td>"
            "</tr></div>"
        )
    return rows


def _numbers(start, count) -> list:
    return [f"21260.{i:07d}/2026-15" for i in range(start, start + count)]


class _ExpectResponse:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def value(self):
        return self.response


class _FakePage:
    def __init__(self, first_response):
        self._first_response = first_response

    def expect_response(self, predicate, timeout=None):
        return _ExpectResponse(self._first_response)

    def wait_for_timeout(self, *args, **kwargs):
        pass


class _FakeResponse:
    def __init__(self, data: dict):
        self.data = data
        self.status = 200

    def json(self):
        return self.data

    def text(self):
        return self.data.get("html", "")

    def dispose(self):
        pass


class _FakeContext:
    class _Request:
        def post(self, *args, **kwargs):
            raise AssertionError("search_processes hermético não deve usar rede")

    request = _Request()


class _DummyRateLimiter:
    def wait(self):
        pass


class _PaginationClient(SeiClient):
    """SeiClient drive sem navegador/rede para pinar o loop de paginação."""

    def __init__(self, first_data: dict, scripted_pages: list):
        self.page = _FakePage(_FakeResponse(first_data))
        self.context = _FakeContext()
        self.rate_limiter = _DummyRateLimiter()
        self.use_manual_captcha = False
        self._scripted = list(scripted_pages)
        self.fetch_calls: list = []
        self.captcha_calls: int = 0

    def open_search_page(self):
        return None

    def _set_search_criteria(self, orgao, unidade, inicio, fim):
        return None

    def solve_search_captcha(self):
        self.captcha_calls += 1

    def submit_search(self):
        return None

    def _fetch_page(self, inicio, page_size):
        self.fetch_calls.append((inicio, page_size))
        return self._scripted.pop(0)


class PaginationLoopTest(unittest.TestCase):
    """Pina a semântica do loop de paginação sem navegador/rede.

    Contrato real do SEI (spike:100,126): resposta AJAX é {"html": ...}
    sem itens; a paginação termina quando uma página vem curta/vazia e
    expected_total é apenas limite adicional quando itens existe.
    """

    def test_pagina_final_curta_para_loop(self):
        first = {"html": _result_rows(_numbers(0, 50))}
        short = {"html": _result_rows(_numbers(50, 20))}
        client = _PaginationClient(first, [short])
        results = client.search_processes("MMULHERES", "U", "01/09/2026", "22/09/2026")
        self.assertEqual(len(results), 70)
        self.assertEqual(client.fetch_calls, [(50, 50)])
        # 1 captcha inicial + 1 por página paginada.
        self.assertEqual(client.captcha_calls, 2)

    def test_html_vazio_para_loop(self):
        first = {"html": _result_rows(_numbers(0, 50))}
        client = _PaginationClient(first, [{"html": ""}])
        results = client.search_processes("MMULHERES", "U", "01/09/2026", "22/09/2026")
        self.assertEqual(len(results), 50)
        self.assertEqual(client.fetch_calls, [(50, 50)])
        self.assertEqual(client.captcha_calls, 2)

    def test_itens_presente_para_no_total(self):
        first = {"html": _result_rows(_numbers(0, 50)), "itens": 60}
        last = {"html": _result_rows(_numbers(50, 10)), "itens": 60}
        client = _PaginationClient(first, [last])
        results = client.search_processes("MMULHERES", "U", "01/09/2026", "22/09/2026")
        self.assertEqual(len(results), 60)
        self.assertEqual(client.fetch_calls, [(50, 50)])
        self.assertEqual(client.captcha_calls, 2)

    def test_primeira_pagina_curta_nao_pagina(self):
        first = {"html": _result_rows(_numbers(0, 10))}
        client = _PaginationClient(first, [])
        results = client.search_processes("MMULHERES", "U", "01/09/2026", "22/09/2026")
        self.assertEqual(len(results), 10)
        self.assertEqual(client.fetch_calls, [])
        self.assertEqual(client.captcha_calls, 1)


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