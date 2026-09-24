import tempfile
import unittest
from pathlib import Path

from sei_insights.cli import build_rows, now_str, parse_arguments
from sei_insights.sei_client import ProcessResult
from sei_insights.store import ProcessRow


def row(numero: str, situacao: str = "Na CTI", hash_: str = "h") -> ProcessRow:
    return ProcessRow(
        numero=numero, titulo="t", data_execucao="2026-09-21 10:00:00",
        data_analise="2026-09-21 10:00:00", data_ultimo_despacho="",
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
        self.assertEqual(rows[0].data_analise, "2026-09-21 10:00:00")  # data_analise original
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
        """Se hash do último despacho não mudou, usa cache (preserva data_analise original)."""
        calls = []
        def analyze(p, prev, force, now):
            calls.append(p.number)
            return row(p.number, "Não deveria ser usado", "h_mesmo")
        previous = {"001": row("001", "Cache", "h_mesmo")}
        rows, novos = build_rows(previous, [pr("001")], analyze, False, now_str())
        self.assertEqual(calls, ["001"])  # analyze chamado para obter hash
        self.assertEqual(rows[0].situacao, "Cache")  # mas situação do cache preservada
        self.assertEqual(rows[0].data_analise, "2026-09-21 10:00:00")  # data original preservada
        self.assertEqual(novos, [])

    def test_erro_vira_linha_nao_bloqueia(self):
        def analyze(p, prev, force, now):
            raise RuntimeError("boom")
        rows, novos = build_rows({}, [pr("001"), pr("002")], analyze, False, now_str())
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].status_coleta.startswith("erro:"))
        self.assertEqual(rows[0].situacao, "Erro / retry")
        self.assertEqual(novos, rows)


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
        from sei_insights.report import build_resumo
        resumo = build_resumo([], [])
        self.assertEqual(resumo["total"], 0)
        self.assertEqual(resumo["novos"], 0)


class NowStrTest(unittest.TestCase):
    def test_formato(self):
        import re
        self.assertRegex(now_str(), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")