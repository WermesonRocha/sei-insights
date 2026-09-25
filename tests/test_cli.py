import base64
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from sei_insights.cli import (_date_window, analyze_process, build_rows,
                              now_str, parse_arguments)
from sei_insights.clients.sei_client import ProcessResult, PublicDocument
from sei_insights.config.rules import RulesEngine
from sei_insights.storage.mirror import ProcessRow, despacho_hash


def row(numero: str, situacao: str = "Na CTI", hash_: str = "h") -> ProcessRow:
    return ProcessRow(
        numero=numero, data_execucao="2026-09-21 10:00:00",
        data_ultimo_despacho="15/09/2026",
        situacao=situacao, destino="", acao_esperada="", pendencia_curta="",
        link_process="u", status_coleta="concluído", hash_ultimo_despacho=hash_,
    )


def pr(numero: str) -> ProcessResult:
    return ProcessResult(number=numero, url=f"url/{numero}", title="t")


class BuildRowsTest(unittest.TestCase):
    def test_sem_cache_analisa_tudo(self):
        def analyze(p, prev, force, now):
            return row(p.number, "Nova análise", "h1")
        rows, novos = build_rows({}, [pr("001"), pr("002")], analyze, False, "2026-09-22 10:00:00")
        self.assertEqual([r.numero for r in rows], ["001", "002"])
        self.assertEqual([r.numero for r in novos], ["001", "002"])
        self.assertEqual(rows[0].situacao, "Nova análise")

    def test_com_cache_nao_reanalisa(self):
        """Se hash não mudou, analyze é chamado mas dados do cache são preservados."""
        calls = []
        def analyze(p, prev, force, now):
            calls.append(p.number)
            return row(p.number, "Cache", prev.hash_ultimo_despacho if prev else "h")
        previous = {"001": row("001", "Guardada", "h")}
        rows, novos = build_rows(previous, [pr("001")], analyze, False, now_str())
        self.assertEqual(calls, ["001"])  # analyze chamado para obter hash
        self.assertEqual(rows[0].situacao, "Guardada")  # mas situação do cache preservada
        self.assertEqual(rows[0].data_ultimo_despacho, "15/09/2026")  # dados do cache preservados
        self.assertEqual(novos, [])

    def test_force_reanalisa_mesmo_com_cache(self):
        calls = []
        def analyze(p, prev, force, now):
            calls.append(p.number)
            return row(p.number, "Nova", "h2")
        rows, _ = build_rows({"001": row("001", "Velha", "h")},
                             [pr("001")], analyze, True, now_str())
        self.assertEqual(calls, ["001"])
        self.assertEqual(rows[0].situacao, "Nova")

    def test_hash_mudou_reanalisa(self):
        """Se hash do último despacho mudou (novo despacho), deve re-analisar."""
        calls = []
        def analyze(p, prev, force, now):
            calls.append(p.number)
            return row(p.number, "Novo despacho", "h_novo")
        previous = {"001": row("001", "Antigo", "h_antigo")}
        rows, novos = build_rows(previous, [pr("001")], analyze, False, now_str())
        self.assertEqual(calls, ["001"])
        self.assertEqual(rows[0].situacao, "Novo despacho")
        self.assertEqual(rows[0].hash_ultimo_despacho, "h_novo")
        self.assertEqual(novos, [])  # não é novo processo, só atualizado

    def test_hash_igual_usa_cache(self):
        """Se hash do último despacho não mudou, usa cache (preserva dados originais)."""
        calls = []
        def analyze(p, prev, force, now):
            calls.append(p.number)
            return row(p.number, "Não deveria ser usado", "h_mesmo")
        previous = {"001": row("001", "Cache", "h_mesmo")}
        rows, novos = build_rows(previous, [pr("001")], analyze, False, now_str())
        self.assertEqual(calls, ["001"])  # analyze chamado para obter hash
        self.assertEqual(rows[0].situacao, "Cache")  # mas situação do cache preservada
        self.assertEqual(rows[0].data_ultimo_despacho, "15/09/2026")  # dados originais preservados
        self.assertEqual(novos, [])

    def test_erro_vira_linha_nao_bloqueia(self):
        def analyze(p, prev, force, now):
            raise RuntimeError("boom")
        rows, novos = build_rows({}, [pr("001"), pr("002")], analyze, False, now_str())
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].status_coleta.startswith("erro:"))
        self.assertEqual(rows[0].situacao, "Erro / retry")
        self.assertEqual(novos, rows)

    def test_cache_por_url_quando_numero_da_busca_mudou(self):
        """Processo descoberto nesta execução por nº de documento ainda acha
        o cache da execução anterior, que usava o nº canônico (chave: URL)."""
        target = "url/21260.002715/2026-53"
        prev_row = row("21260.002715/2026-53", "Guardada", "h")
        prev_row.link_process = target
        previous = {"21260.002715/2026-53": prev_row}
        found = [ProcessResult(number="64534686", url=target, title="t")]
        calls = []
        def analyze(p, prev, force, now):
            # Simula analyze_process: open_process canoniza o nº via cabeçalho.
            calls.append(p.number)
            p.number = "21260.002715/2026-53"
            return row(p.number, "Cache", prev.hash_ultimo_despacho if prev else "h")
        rows, novos = build_rows(previous, found, analyze, False, now_str())
        self.assertEqual(calls, ["64534686"])
        self.assertEqual(rows[0].numero, "21260.002715/2026-53")
        self.assertEqual(rows[0].situacao, "Guardada")
        self.assertEqual(rows[0].data_ultimo_despacho, "15/09/2026")
        self.assertEqual(novos, [])

    def test_processo_em_cache_nao_conta_como_novo_quando_numero_canonizado(self):
        """Cache antigo chaveado por nº de documento + linha com nº canônico
        canônico: processo conhecido não deve aparecer como "novo"."""
        target = "url/21260.002715/2026-53"
        prev_row = row("64534686", "Guardada", "h")
        prev_row.link_process = target
        previous = {"64534686": prev_row}
        found = [ProcessResult(number="64534686", url=target, title="t")]
        def analyze(p, prev, force, now):
            p.number = "21260.002715/2026-53"  # open_process canoniza via cabeçalho
            return row(p.number, "Cache", prev.hash_ultimo_despacho if prev else "h")
        rows, novos = build_rows(previous, found, analyze, False, now_str())
        self.assertEqual(rows[0].numero, "21260.002715/2026-53")
        self.assertEqual(rows[0].situacao, "Guardada")
        self.assertEqual(novos, [])


class ArgParseTest(unittest.TestCase):
    def test_defaults(self):
        args = parse_arguments([])
        self.assertEqual(args.dias, 7)
        self.assertEqual(args.min_delay, 2.0)
        self.assertEqual(args.max_delay, 5.0)
        self.assertFalse(args.force)

    def test_dias_rejeita_invalido(self):
        with self.assertRaises(SystemExit):
            parse_arguments(["--dias", "-1"])

    def test_max_delay_menor_que_min(self):
        args = parse_arguments(["--min-delay", "5", "--max-delay", "2"])
        self.assertEqual(args.max_delay, 2.0)  # validação também é refletida em main()->2


class EmptyResultTest(unittest.TestCase):
    def test_calcula_resumo_vazio_sem_erro(self):
        from sei_insights.storage.report import build_resumo
        resumo = build_resumo([], [])
        self.assertEqual(resumo["total"], 0)
        self.assertEqual(resumo["novos"], 0)


class NowStrTest(unittest.TestCase):
    def test_formato(self):
        import re
        self.assertRegex(now_str(), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


# PDF mínimo de uma página contendo "Diante do exposto" com camada de texto.
PDF_WITH_TEXT_B64 = (
    "JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgKHB5cGRmKQo+PgplbmRvYmoKMiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0NvdW50IDEKL0tpZHMgWyA0IDAgUiBdCj4+CmVuZG9iagozIDAgb2JqCjw8Ci9UeXBlIC9DYXRhbG9nCi9QYWdlcyAyIDAgUgo+PgplbmRvYmoKNCAwIG9iago8PAovVHlwZSAvUGFnZQovUmVzb3VyY2VzIDw8Ci9Gb250IDw8Ci9GMSA8PAovVHlwZSAvRm9udAovU3VidHlwZSAvVHlwZTEKL0Jhc2VGb250IC9IZWx2ZXRpY2EKPj4KPj4KPj4KL01lZGlhQm94IFsgMC4wIDAuMCAyMDAgMjAwIF0KL1BhcmVudCAyIDAgUgovQ29udGVudHMgPDwKL0xlbmd0aCA0OAo+PgpzdHJlYW0KQlQgL0YxIDEyIFRmIDcyIDcyMCBUZCAoRGlhbnRlIGRvIGV4cG9zdG8pIFRqIEVUCmVuZHN0cmVhbQo+PgplbmRvYmoKeHJlZgowIDUKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDE1IDAwMDAwIG4gCjAwMDAwMDAwNTQgMDAwMDAgbiAKMDAwMDAwMDExMyAwMDAwMCBuIAowMDAwMDAwMTYyIDAwMDAwIG4gCnRyYWlsZXIKPDwKL1NpemUgNQovUm9vdCAzIDAgUgovSW5mbyAxIDAgUgo+PgpzdGFydHhyZWYKNDIwCiUlRU9GCg=="
)

# PDF mínimo de uma página sem camada de texto extraível (digitalizado).
PDF_EMPTY_B64 = (
    "JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgKHB5cGRmKQo+PgplbmRvYmoKMiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0NvdW50IDEKL0tpZHMgWyA0IDAgUiBdCj4+CmVuZG9iagozIDAgb2JqCjw8Ci9UeXBlIC9DYXRhbG9nCi9QYWdlcyAyIDAgUgo+PgplbmRvYmoKNCAwIG9iago8PAovVHlwZSAvUGFnZQovUmVzb3VyY2VzIDw8Cj4+Ci9NZWRpYUJveCBbIDAuMCAwLjAgMjAwIDIwMCBdCi9QYXJlbnQgMiAwIFIKPj4KZW5kb2JqCnhyZWYKMCA1CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAxNSAwMDAwMCBuIAowMDAwMDAwMDU0IDAwMDAwIG4gCjAwMDAwMDAxMTMgMDAwMDAgbiAKMDAwMDAwMDE2MiAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDUKL1Jvb3QgMyAwIFIKL0luZm8gMSAwIFIKPj4Kc3RhcnR4cmVmCjI1NgolJUVPRgo="
)


TREE_WITH_DESPACHO = """
<div class="infraArvore">
  <ul>
    <li>
      <input type="checkbox" value="100001">
      <span class="infraLabel">Processo Administrativo</span>
    </li>
    <li>
      <input type="checkbox" value="100002">
      <span class="infraLabel">Despacho 100002 - 10/09/2026</span>
    </li>
    <li>
      <input type="checkbox" value="100003">
      <span class="infraLabel">Despacho 100003 - 15/09/2026</span>
    </li>
    <li>
      <input type="checkbox" value="100004">
      <span class="infraLabel">Ofício 100004 - 16/09/2026</span>
    </li>
  </ul>
</div>
"""

TREE_SEM_DESPACHO = TREE_WITH_DESPACHO.replace(
    "Despacho 100002 - 10/09/2026", "Nota Técnica 100002 - 10/09/2026"
).replace(
    "Despacho 100003 - 15/09/2026", "Nota Técnica 100003 - 15/09/2026"
)


def docs_correlacionados():
    return [
        PublicDocument(number="100002", name="Despacho 100002 - 10/09/2026",
                       url="https://x/doc?d=100002"),
        PublicDocument(number="100003", name="Despacho 100003 - 15/09/2026",
                       url="https://x/doc?d=100003"),
        PublicDocument(number="100004", name="Ofício 100004 - 16/09/2026",
                       url="https://x/doc?d=100004"),
    ]


def rules_deterministicas():
    return RulesEngine({
        "fallback": {"situacao": "Em análise", "destino": "",
                     "acao_esperada": "", "pendencia_curta": ""},
        "regras": [
            {"pattern": "Diante do exposto", "situacao": "SCIENTIA CIENCIA",
             "destino": "", "acao_esperada": "", "pendencia_curta": ""}
        ],
    })


class FakeClient:
    def __init__(self, html="", docs=None, pdf_path=None, download_err=None,
                 despacho_link=True):
        self.html = html
        self.docs = docs or []
        self.pdf_path = pdf_path
        self.download_err = download_err
        self.despacho_link = despacho_link
        self.open_process_calls = 0
        self.download_calls = 0

    def open_process(self, p):
        self.open_process_calls += 1
        return self.html

    def extract_documents(self, html, url):
        return self.docs

    def download_despacho(self, process_number, numero, serie):
        self.download_calls += 1
        if self.download_err is not None:
            raise self.download_err
        if not self.despacho_link:
            return None
        return self.pdf_path, "sha256", "application/pdf"

    def download_document(self, process_number, document):
        self.download_calls += 1
        if self.download_err is not None:
            raise self.download_err
        return self.pdf_path, "sha256", "application/pdf"


def temp_pdf(tmp: str, name: str, b64: str) -> Path:
    path = Path(tmp) / name
    path.write_bytes(base64.b64decode(b64))
    return path


class AnalyzePipelineTest(unittest.TestCase):
    NOW = "2026-09-22 10:00:00"

    def setUp(self):
        self.rules = rules_deterministicas()
        self.p = pr("21260.003436/2026-15")
        self.h100003 = despacho_hash("100003|15/09/2026")

    def _client(self, tmp, html, b64, download_err=None, despacho_link=True):
        return FakeClient(
            html=html,
            docs=docs_correlacionados(),
            pdf_path=temp_pdf(tmp, "d.pdf", b64) if b64 else None,
            download_err=download_err,
            despacho_link=despacho_link,
        )

    def test_despacho_encontrado_aplica_regra(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp, TREE_WITH_DESPACHO, PDF_WITH_TEXT_B64)
            r = analyze_process(client, self.p, None, False, self.NOW, self.rules)
        self.assertEqual(client.download_calls, 1)
        self.assertEqual(r.situacao, "SCIENTIA CIENCIA")
        self.assertEqual(r.data_ultimo_despacho, "15/09/2026")
        self.assertEqual(r.hash_ultimo_despacho, self.h100003)
        self.assertEqual(r.status_coleta, "concluído")
        self.assertEqual(r.numero, self.p.number)
        self.assertEqual(r.link_process, self.p.url)

    def test_despacho_sem_link_publico_nao_baixa(self):
        """Despacho na árvore sem link público não é baixado.

        O download é por CLIQUE no link da árvore; sem link público
        (restrito), download_despacho devolve None e a linha vira
        "Sem despacho público" sem tentar baixar.
        """
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(html=TREE_WITH_DESPACHO,
                                docs=docs_correlacionados(),
                                pdf_path=None, despacho_link=False)
            r = analyze_process(client, self.p, None, False, self.NOW, self.rules)
        self.assertEqual(r.situacao, "Sem despacho público")
        self.assertEqual(r.data_ultimo_despacho, "")
        self.assertEqual(r.hash_ultimo_despacho, "")
        self.assertEqual(r.status_coleta, "concluído")

    def test_sem_despacho_publico_nao_baixa(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp, TREE_SEM_DESPACHO, PDF_WITH_TEXT_B64)
            r = analyze_process(client, self.p, None, False, self.NOW, self.rules)
        self.assertEqual(client.download_calls, 0)
        self.assertEqual(r.situacao, "Sem despacho público")
        self.assertEqual(r.data_ultimo_despacho, "")
        self.assertEqual(r.hash_ultimo_despacho, "")
        self.assertEqual(r.status_coleta, "concluído")

    def test_texto_vazio_digitalizado_mantem_hash_do_identificador(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp, TREE_WITH_DESPACHO, PDF_EMPTY_B64)
            r = analyze_process(client, self.p, None, False, self.NOW, self.rules)
        self.assertEqual(client.download_calls, 1)
        self.assertEqual(r.situacao, "Texto não extraível (digitalizado?)")
        self.assertEqual(r.data_ultimo_despacho, "15/09/2026")
        self.assertEqual(r.hash_ultimo_despacho, self.h100003)
        self.assertEqual(r.status_coleta, "concluído")

    def test_cache_reutilizavel_nao_baixa_e_preserva_dados(self):
        prev = row(self.p.number, "Aguardando retorno", hash_=self.h100003)
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp, TREE_WITH_DESPACHO, PDF_WITH_TEXT_B64)
            r = analyze_process(client, self.p, prev, False, self.NOW, self.rules)
        self.assertEqual(client.download_calls, 0)
        self.assertEqual(r.data_ultimo_despacho, prev.data_ultimo_despacho)
        self.assertEqual(r.hash_ultimo_despacho, self.h100003)
        self.assertEqual(r.status_coleta, "concluído (cache)")
        self.assertEqual(r.situacao, prev.situacao)

    def test_force_reanalisa_mesmo_com_cache(self):
        prev = row(self.p.number, "Aguardando retorno", hash_=self.h100003)
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp, TREE_WITH_DESPACHO, PDF_WITH_TEXT_B64)
            r = analyze_process(client, self.p, prev, True, self.NOW, self.rules)
        self.assertEqual(client.download_calls, 1)
        self.assertEqual(r.data_ultimo_despacho, "15/09/2026")
        self.assertEqual(r.situacao, "SCIENTIA CIENCIA")

    def test_erro_no_download_vira_linha_de_erro_em_build_rows(self):
        client = FakeClient(html=TREE_WITH_DESPACHO, docs=docs_correlacionados(),
                            download_err=RuntimeError("boom download"),
                            despacho_link=True)

        def analyze(p, prev, force, now):
            return analyze_process(client, p, prev, force, now, self.rules)

        rows, novos = build_rows({}, [self.p], analyze, False, self.NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status_coleta, "erro: boom download")
        self.assertEqual(rows[0].situacao, "Erro / retry")
        self.assertEqual(novos, rows)


class DateWindowTest(unittest.TestCase):
    def test_deriva_inicio_de_hoje_menos_dias(self):
        args = parse_arguments(["--dias", "7"])
        inicio, fim = _date_window(args, datetime(2026, 9, 25))
        self.assertEqual(inicio, "18/09/2026")
        self.assertEqual(fim, "25/09/2026")

    def test_inicio_fim_explicitos_substituem_dias(self):
        args = parse_arguments(["--inicio", "01/09/2026", "--fim", "22/09/2026"])
        inicio, fim = _date_window(args, datetime(2026, 9, 25))
        self.assertEqual((inicio, fim), ("01/09/2026", "22/09/2026"))

    def test_inicio_vazio_deriva_quando_fim_explicito(self):
        args = parse_arguments(["--inicio", "", "--fim", "22/09/2026"])
        inicio, fim = _date_window(args, datetime(2026, 9, 25))
        self.assertEqual(inicio, "18/09/2026")
        self.assertEqual(fim, "22/09/2026")