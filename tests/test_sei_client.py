import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from sei_insights.clients.sei_client import (
    MAX_RETRIES,
    ProcessResult,
    PublicDocument,
    SeiClient,
    extract_process,  # extract_process is a module function below
)


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


class _AutocompleteContext:
    """Context fake que registra o POST de autocomplete de unidade."""

    def __init__(self, response):
        self.response = response
        self.post_kwargs = None

    def post(self, *args, **kwargs):
        self.post_kwargs = kwargs
        return self.response

    class _Request:
        pass

    @property
    def request(self):
        return self


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


class _OrderPaginationClient(_PaginationClient):
    """Registra a ordem de solve_search_captcha vs _set_search_criteria.

    Contrato do coletor (main.py:3590-3621): o CAPTCHA é resolvido antes
    de qualquer requisição de pesquisa ao SEI — inclusive o POST de
    autocomplete de unidade que acontece dentro de _set_search_criteria.
    """

    def __init__(self, first_data, scripted_pages):
        super().__init__(first_data, scripted_pages)
        self.events: list = []

    def _set_search_criteria(self, orgao, unidade, inicio, fim):
        self.events.append("set_criteria")
        return None

    def solve_search_captcha(self):
        self.events.append("solve_captcha")
        self.captcha_calls += 1


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

    def test_captcha_resolvido_antes_de_preencher_criterios(self):
        client = _OrderPaginationClient(
            {"html": _result_rows(_numbers(0, 10))}, []
        )
        client.search_processes("MMULHERES", "U", "01/09/2026", "22/09/2026")
        self.assertIn("solve_captcha", client.events)
        self.assertIn("set_criteria", client.events)
        self.assertLess(
            client.events.index("solve_captcha"),
            client.events.index("set_criteria"),
        )


class _HeaderPage:
    """Page fake da página do processo com #tblCabecalho."""

    def __init__(self, content: str):
        self._content = content
        self.goto_count = 0

    @property
    def url(self):
        return "https://x/sei/modulos/pesquisa/md_pesq_processo_exibir.php?id=9"

    def goto(self, *args, **kwargs):
        self.goto_count += 1

    def wait_for_timeout(self, *args, **kwargs):
        pass

    def content(self):
        return self._content


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

    def test_add_result_deduplica_por_url_de_processo(self):
        """Duas linhas de documento do MESMO processo não viram 2 resultados.

        Bug real: a pesquisa com documentos marcados devolve uma linha por
        documento (data-prot = nº do documento) com link para o processo-pai;
        o mesmo despacho era baixado 2x. Mesma URL de processo => 1 resultado.
        """
        html = (
            "<div><tr data-prot='64534686'>"
            "<td><a href='md_pesq_processo_exibir.php?id=999'>Planilha</a></td>"
            "</tr></div>"
            "<div><tr data-prot='64535113'>"
            "<td><a href='md_pesq_processo_exibir.php?id=999'>Planilha</a></td>"
            "</tr></div>"
        )
        results: dict = {}
        self.client._add_result(results, "64534686", {"html": html})
        self.client._add_result(results, "64535113", {"html": html})
        self.assertEqual(len(results), 1)

    def test_add_result_prefere_numero_de_processo(self):
        """Linha de processo e de documento com a mesma URL: vence o nº do processo."""
        html = (
            "<div><tr data-prot='64534686'>"
            "<td><a href='md_pesq_processo_exibir.php?id=999'>Planilha</a></td>"
            "</tr></div>"
            "<div><tr data-prot='21260.002715/2026-53'>"
            "<td><a href='md_pesq_processo_exibir.php?id=999'>Processo</a></td>"
            "</tr></div>"
        )
        results: dict = {}
        self.client._add_result(results, "64534686", {"html": html})
        self.client._add_result(results, "21260.002715/2026-53", {"html": html})
        self.assertEqual(len(results), 1)
        self.assertIn("21260.002715/2026-53", results)

    def test_open_process_canonicaliza_numero_do_cabecalho(self):
        """O nº da pasta/linha vem do cabeçalho da página, não do doc da busca."""
        html = (
            "<table id='tblCabecalho'>"
            "<tr><td><b>Processo:</b></td><td>21260.002715/2026-53</td></tr>"
            "</table>"
        )
        page = _HeaderPage(html)
        client = SeiClient(None, page, _DummyRateLimiter())
        p = ProcessResult(
            number="64534686",
            url="https://x/sei/modulos/pesquisa/md_pesq_processo_exibir.php?id=999",
            title="",
        )
        client.open_process(p)
        self.assertEqual(p.number, "21260.002715/2026-53")

    def test_open_process_preserva_numero_sem_cabecalho(self):
        page = _HeaderPage("<html><body>sem cabecalho</body></html>")
        client = SeiClient(None, page, _DummyRateLimiter())
        p = ProcessResult(
            number="21260.002715/2026-53",
            url="https://x/sei/modulos/pesquisa/md_pesq_processo_exibir.php?id=999",
            title="",
        )
        client.open_process(p)
        self.assertEqual(p.number, "21260.002715/2026-53")


class ResolveUnidadeTest(unittest.TestCase):
    """Pina o contrato do POST de autocomplete de unidade (spike 35-45).

    O endpoint do SEI lê palavras_pesquisa/id_orgao de um corpo
    form-urlencoded (Content-Type application/x-www-form-urlencoded),
    e não JSON — mesmo padrão de _fetch_page que já funciona.
    """

    def test_resolve_unidade_envia_form_urlencoded(self):
        response = _FakeResponse({
            "html": "<li value='42'>MMULHERES-SE-SGA-CGATI-CTI-DTI</li>"
        })
        context = _AutocompleteContext(response)
        client = SeiClient(context, None, _DummyRateLimiter())
        unit_id = client._resolve_unidade_id(
            "MMULHERES-SE-SGA-CGATI-CTI-DTI", "11"
        )
        self.assertEqual(unit_id, "42")

        kwargs = context.post_kwargs
        self.assertIsNotNone(kwargs)
        self.assertNotIn("data", kwargs)
        self.assertEqual(
            kwargs.get("form", {}).get("palavras_pesquisa"),
            "MMULHERES-SE-SGA-CGATI-CTI-DTI",
        )
        self.assertEqual(kwargs.get("form", {}).get("id_orgao"), "11")
        self.assertEqual(
            kwargs.get("params", {}).get("acao_ajax_externo"),
            "unidade_auto_completar_todas",
        )


class _FakeSubmitButton:
    """Fake do botão #sbmPesquisar (input[type=submit])."""

    def __init__(self):
        self.clicked = False

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def click(self):
        self.clicked = True


class _FakeEmptyLocator:
    def count(self):
        return 0

    @property
    def first(self):
        return self

    def click(self):
        raise AssertionError("locator vazio não deveria ser clicado")


class _FakeSubmitForm:
    def __init__(self, button):
        self.button = button

    def count(self):
        return 1

    def locator(self, selector):
        if selector == "#sbmPesquisar":
            return self.button
        return _FakeEmptyLocator()

    def get_by_role(self, role, name=None):
        return _FakeEmptyLocator()


class _FakeSubmitPage:
    def __init__(self):
        self.button = _FakeSubmitButton()
        self.form = _FakeSubmitForm(self.button)
        self.request_submits = 0

    def locator(self, selector):
        if selector == "#seiSearch":
            return self.form
        raise AssertionError(f"seletor inesperado: {selector}")

    def evaluate(self, script, *args):
        self.request_submits += 1


class SubmitSearchTest(unittest.TestCase):
    """Pina o clique real no botão de pesquisa (#sbmPesquisar).

    Após preencher os critérios, o submit deve CLICAR no botão
    "Pesquisar" (input[type=submit]) para que o SEI execute o fluxo
    oficial (OnSubmitForm -> carregarProximaPagina). requestSubmit() é
    apenas fallback quando o botão não existe.
    """

    def test_submit_clica_no_botao_de_pesquisa(self):
        page = _FakeSubmitPage()
        client = SeiClient(None, page, _DummyRateLimiter())
        client.submit_search()
        self.assertTrue(page.button.clicked)


class _CheckboxPage:
    """Page fake que registra os evaluate da marcação de checkbox."""

    def __init__(self):
        self.scripts = []

    def evaluate(self, script, *args):
        self.scripts.append((script, args))
        return True


class CheckboxMarkTest(unittest.TestCase):
    """Pina a marcação de checkbox via DOM (evento change).

    O checkbox do SEI usa um <label class="infraCheckboxLabel"> que
    intercepta o clique do Playwright .check() (log real: 90s de retry).
    Marcamos o input diretamente via JS + evento change, como já é feito
    para #hdnIdUnidade.
    """

    def test_marca_checkbox_via_dom_change(self):
        page = _CheckboxPage()
        client = SeiClient(None, page, _DummyRateLimiter())
        client._ensure_checked("chkSinDocumentosGerados")
        self.assertEqual(len(page.scripts), 1)
        script, args = page.scripts[0]
        self.assertEqual(args, ("chkSinDocumentosGerados",))
        self.assertIn("el.checked = true", script)
        self.assertIn("new Event('change'", script)


class _DownloadResponse:
    def __init__(self, status=200, body=b""):
        self.status = status
        self.headers = {"content-type": "application/pdf"}
        self._body = body

    def body(self):
        return self._body

    def dispose(self):
        pass


class _DownloadContext:
    class _Request:
        def __init__(self, status=200, body=b"", exc=None):
            self.status = status
            self.body = body
            self.exc = exc
            self.count = 0

        def get(self, url, **kwargs):
            self.count += 1
            if self.exc is not None:
                raise self.exc
            return _DownloadResponse(self.status, self.body)

    def __init__(self, status=200, body=b"", exc=None):
        self.request = self._Request(status, body, exc)


class _WaitsRateLimiter:
    def __init__(self):
        self.wait_seconds_calls = []

    def wait(self):
        pass

    def wait_seconds(self, value):
        self.wait_seconds_calls.append(value)


class DownloadRetryTest(unittest.TestCase):
    """Pina o retry do download: erros permanentes não repetem.

    Log real: "APIRequestContext.get: Invalid URL. Tentativa 1/3..." —
    retentar uma URL inválida (ou um HTTP 4xx) é inútil e trava a tela.
    Só erros transitórios (timeout/network/429/5xx) devem repetir.
    """

    def test_url_relativa_falha_imediatamente_sem_tentativas(self):
        ctx = _DownloadContext()
        client = SeiClient(ctx, None, _DummyRateLimiter())
        doc = PublicDocument(
            number="1", name="Despacho",
            url="md_pesq_documento_consulta_externa.php?id=1",
        )
        with self.assertRaisesRegex(RuntimeError, "URL inválida"):
            client.download_document("123", doc)
        self.assertEqual(ctx.request.count, 0)

    def test_url_vazia_falha_imediatamente_sem_tentativas(self):
        ctx = _DownloadContext()
        client = SeiClient(ctx, None, _DummyRateLimiter())
        doc = PublicDocument(number="1", name="Despacho", url="")
        with self.assertRaisesRegex(RuntimeError, "URL inválida"):
            client.download_document("123", doc)
        self.assertEqual(ctx.request.count, 0)

    def test_http_400_nao_repete(self):
        limiter = _WaitsRateLimiter()
        ctx = _DownloadContext(status=400, body=b"bad")
        client = SeiClient(ctx, None, limiter)
        doc = PublicDocument(
            number="1", name="Despacho", url="https://x/doc?d=1",
        )
        with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
            client.download_document("123", doc)
        self.assertEqual(ctx.request.count, 1)
        self.assertEqual(limiter.wait_seconds_calls, [])

    def test_transient_repete_ate_max_tentativas(self):
        ctx = _DownloadContext(exc=Exception("Timeout 30000ms exceeded"))
        client = SeiClient(ctx, None, _DummyRateLimiter())
        doc = PublicDocument(
            number="1", name="Despacho", url="https://x/doc?d=1",
        )
        with patch("sei_insights.clients.sei_client.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "3 tentativas"):
                client.download_document("123", doc)
        self.assertEqual(ctx.request.count, MAX_RETRIES)


DEFAULT_SELECT = {
    "title": "Despacho Numerado",
    "numero": "62407412",
    "onclick": "window.open('md_pesq_documento_consulta_externa.php?TOKEN');",
}

PDF_BYTES = b"%PDF-1.4 fake\n"


class _FakeDownload:
    def __init__(self, body=b"%PDF-1.4 fake\n", failure=None):
        self.saved_to = None
        self.body = body
        self._failure = failure

    def failure(self):
        return self._failure

    def save_as(self, path):
        self.saved_to = str(path)
        Path(path).write_bytes(self.body)


class _FakeSolver:
    """Fake de CaptchaSolver: preenche #txtInfraCaptcha sem OCR."""

    def __init__(self, max_retries=3):
        self.max_retries = max_retries
        self.calls = 0

    def solve_captcha_in_page(self, page, captcha_img_selector):
        self.calls += 1
        page.locator("#txtInfraCaptcha").fill("ABC123")


class _FakeModalLocator:
    """Locator fake para o modal de geração de PDF (#divInfraModal)."""

    def __init__(self, page, selector):
        self.page = page
        self.selector = selector
        self.first = self

    def count(self):
        if self.selector == "#btnEnviarCaptcha":
            return 1
        if self.selector == "#divInfraModal":
            return 1
        if self.selector == "img[onclick*=\"fecharPdfModal\"]":
            return int(self.page.modal_visible)
        if self.selector == "#divInfraMensagens":
            return int(self.page.mensagens_visible)
        return 0

    def is_visible(self):
        if self.selector == "#divInfraModal":
            return self.page.modal_visible
        if self.selector == "#divInfraMensagens":
            return self.page.mensagens_visible
        return False

    def click(self):
        if self.selector == "#btnEnviarCaptcha":
            self.page.calls["enviar_clicks"] += 1
            self.page.modal_visible = False
            self.page.mensagens_visible = False
            if self.page.reject_captcha and self.page.calls["enviar_clicks"] == 1:
                self.page.mensagens_visible = True
        elif self.selector == "img[onclick*=\"fecharPdfModal\"]":
            self.page.modal_visible = False

    def fill(self, text):
        self.page.captcha_filled = text

    def get_attribute(self, name):
        if self.selector == "#imgCaptcha" and name == "src":
            return "data:image/png;base64,AAAA"
        return None

    def input_value(self):
        return self.page.captcha_filled

    def inner_text(self):
        if self.selector == "#divInfraMensagens":
            return "O CAPTCHA informado não confere com a imagem apresentada."
        return ""


class _TreePage:
    """Page fake da página do processo (#tblDocumentos) para download_despacho.

    Simula o fluxo validado do modal "Gerar PDF": marca só o despacho alvo,
    abre o modal de CAPTCHA (#btnEnviarCaptcha) e dispara o evento download.
    """

    url = "https://x/sei/modulos/pesquisa/md_pesq_processo_exibir.php?id=9"

    def __init__(self, select_result=None,
                 mount_timeout=False,
                 captcha_timeout=False,
                 reject_captcha=False,
                 download_body=PDF_BYTES,
                 modal_visible=True):
        self.select_result = select_result
        self.mount_timeout = mount_timeout
        self.captcha_timeout = captcha_timeout
        self.reject_captcha = reject_captcha
        self.download_body = download_body
        self.modal_visible = modal_visible
        self.mensagens_visible = False
        self.captcha_filled = ""
        self.download_listener = None
        self.download_fired = False
        self.calls = {
            "table_waits": 0,
            "captcha_waits": 0,
            "selects": 0,
            "gerar_pdf_clicks": 0,
            "enviar_clicks": 0,
        }
        self.selected_numero = None

    def wait_for_selector(self, selector, state=None, timeout=None):
        if selector == "#tblDocumentos":
            self.calls["table_waits"] += 1
            if self.mount_timeout:
                raise PlaywrightTimeoutError("timeout tabela")
            return object()
        if selector == "#txtInfraCaptcha":
            self.calls["captcha_waits"] += 1
            if self.captcha_timeout:
                raise PlaywrightTimeoutError("timeout modal")
            return object()
        return object()

    def evaluate(self, script, arg=None):
        if "hdnInfraItensSelecionados" in script:
            self.calls["selects"] += 1
            self.selected_numero = arg
            return {"status": "ok", "selected": arg}
        if "getElementsByName('btnGerarPdfModal')" in script:
            self.calls["gerar_pdf_clicks"] += 1
            return True
        self.calls["selects"] += 1
        return self.select_result

    def wait_for_timeout(self, ms):
        if (self.download_listener is not None
                and self.calls["enviar_clicks"] > 0
                and not self.download_fired):
            if self.reject_captcha and self.calls["enviar_clicks"] <= 1:
                self.mensagens_visible = True
                return
            self.mensagens_visible = False
            self.download_fired = True
            self.download_listener(_FakeDownload(self.download_body))

    def on(self, event, handler):
        if event == "download":
            self.download_listener = handler

    def remove_listener(self, event, handler):
        if event == "download":
            self.download_listener = None

    def locator(self, selector):
        return _FakeModalLocator(self, selector)


class DownloadModalTest(unittest.TestCase):
    """Pina o download do despacho pelo modal "Gerar PDF" com CAPTCHA.

    A página do processo lista os documentos numa tabela; o botão
    "Gerar PDF" (name=btnGerarPdfModal) abre o modal #divInfraModal com o
    campo #txtInfraCaptcha. Marcando APENAS o checkbox do despacho alvo, o
    SEI gera o PDF desse documento e inicia o download (evento download do
    Playwright). O GET direto à URL de consulta externa devolve HTML (página
    que exige CAPTCHA), por isso o fluxo passa pelo modal.
    """

    def test_download_despacho_gera_pdf_no_modal_e_salva(self):
        page = _TreePage(select_result=DEFAULT_SELECT)
        client = SeiClient(None, page, _DummyRateLimiter())
        with tempfile.TemporaryDirectory() as tmp:
            with patch("sei_insights.clients.sei_client._process_directory",
                       lambda number: Path(tmp)):
                with patch("sei_insights.clients.sei_client.CaptchaSolver",
                           _FakeSolver):
                    path, sha, content_type = client.download_despacho(
                        "123", "68626098", "Despacho",
                    )
                self.assertTrue(path.exists())
                self.assertRegex(sha, r"^[0-9a-f]{64}$")
                self.assertEqual(content_type, "application/pdf")
                self.assertEqual(page.calls["table_waits"], 1)
                self.assertGreaterEqual(page.calls["gerar_pdf_clicks"], 1)
                self.assertEqual(page.calls["enviar_clicks"], 1)
                self.assertEqual(page.selected_numero, "68626098")
                self.assertEqual(page.captcha_filled, "ABC123")

    def test_download_despacho_sem_tabela_retorna_none(self):
        page = _TreePage(mount_timeout=True)
        client = SeiClient(None, page, _DummyRateLimiter())
        result = client.download_despacho("123", "68626098", "Despacho")
        self.assertIsNone(result)
        self.assertEqual(page.calls["enviar_clicks"], 0)

    def test_download_despacho_sem_linha_de_despacho_retorna_none(self):
        page = _TreePage(select_result=None)
        client = SeiClient(None, page, _DummyRateLimiter())
        result = client.download_despacho("123", "68626098", "Despacho")
        self.assertIsNone(result)
        self.assertEqual(page.calls["enviar_clicks"], 0)

    def test_download_despacho_selecao_global_falhou_retorna_none(self):
        page = _TreePage(select_result=DEFAULT_SELECT)

        def _evaluate_fail(self, script, arg=None):
            if "hdnInfraItensSelecionados" in script:
                self.calls["selects"] += 1
                return {"status": "missing"}
            if "getElementsByName('btnGerarPdfModal')" in script:
                self.calls["gerar_pdf_clicks"] += 1
                return True
            self.calls["selects"] += 1
            return self.select_result

        page.evaluate = _evaluate_fail.__get__(page)
        client = SeiClient(None, page, _DummyRateLimiter())
        result = client.download_despacho("123", "68626098", "Despacho")
        self.assertIsNone(result)
        self.assertEqual(page.calls["enviar_clicks"], 0)

    def test_download_despacho_captcha_invalido_repete_ate_sucesso(self):
        page = _TreePage(select_result=DEFAULT_SELECT, reject_captcha=True)
        client = SeiClient(None, page, _DummyRateLimiter())
        with tempfile.TemporaryDirectory() as tmp:
            with patch("sei_insights.clients.sei_client._process_directory",
                       lambda number: Path(tmp)):
                with patch("sei_insights.clients.sei_client.CaptchaSolver",
                           _FakeSolver):
                    path, sha, content_type = client.download_despacho(
                        "123", "68626098", "Despacho",
                    )
                self.assertTrue(path.exists())
                self.assertEqual(content_type, "application/pdf")
                # 1ª descartada (CAPTCHA rejeitado), 2ª confirma.
                self.assertGreaterEqual(page.calls["enviar_clicks"], 2)

    def test_download_despacho_sem_modal_esgota_tentativas(self):
        page = _TreePage(select_result=DEFAULT_SELECT, captcha_timeout=True)
        client = SeiClient(None, page, _DummyRateLimiter())
        with self.assertRaisesRegex(RuntimeError, "tentativas"):
            client.download_despacho("123", "68626098", "Despacho")
        self.assertGreaterEqual(page.calls["captcha_waits"], 1)
        self.assertEqual(page.calls["enviar_clicks"], 0)


class _FakeFieldUnit:
    """Fake de #txtUnidade: count, first.click e press_sequentially."""

    def __init__(self):
        self.clicked = False
        self.typed = None

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def click(self):
        self.clicked = True

    def press_sequentially(self, text, delay=None):
        self.typed = text


class _FakeMenuUnit:
    """Fake do dropdown: wait_for visible, count e click na primeira opção."""

    def __init__(self):
        self.waited = False
        self.clicked = False

    @property
    def first(self):
        return self

    def wait_for(self, state=None, timeout=None):
        self.waited = True
        return self

    def count(self):
        return 1

    def click(self):
        self.clicked = True


class _DropdownPage:
    """Page fake que grava o id oculto apenas quando a opção é clicada.

    Reproduz o contrato real do widget infraAjaxAutoCompletar: sem o
    clique na opção, #hdnIdUnidade permanece vazio.
    """

    def __init__(self):
        self.field = _FakeFieldUnit()
        self.menu = _FakeMenuUnit()
        self.wait_calls = 0

    def locator(self, selector):
        if selector == "#txtUnidade":
            return self.field
        if selector == 'input[name="txtUnidade"]':
            return self.field
        if "divInfraAjaxtxtUnidade" in selector or ".ui-" in selector:
            return self.menu
        raise AssertionError(f"seletor inesperado: {selector}")

    def evaluate(self, script):
        return "42" if self.menu.clicked else ""

    def wait_for_timeout(self, *args, **kwargs):
        self.wait_calls += 1

    def nth(self, index):
        return self.menu


class AutocompleteDropdownTest(unittest.TestCase):
    """Pina a seleção real da unidade: digitar e clicar na 1ª opção.

    O usuário confirmou que #txtUnidade é um seletor: sem o clique na
    opção do dropdown o SEI não grava #hdnIdUnidade e a consulta falha.
    """

    def test_digita_e_clica_primeira_opcao_para_selecionar_valor(self):
        page = _DropdownPage()
        client = SeiClient(None, page, _DummyRateLimiter())
        result = client._resolve_unidade_dropdown(
            "MMULHERES-SE-SGA-CGATI-CTI-DTI"
        )
        self.assertEqual(result, "42")
        self.assertTrue(page.field.clicked)
        self.assertEqual(page.field.typed, "MMULHERES-SE-SGA-CGATI-CTI-DTI")
        self.assertTrue(page.menu.waited)
        self.assertTrue(page.menu.clicked)