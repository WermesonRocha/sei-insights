import tempfile
import unittest
from pathlib import Path

from store import MirrorStore, ProcessRow, despacho_hash


def row(numero: str, situacao: str = "X", hash_: str = "h") -> ProcessRow:
    return ProcessRow(
        numero=numero,
        titulo="t",
        data_execucao="2026-09-22 10:00:00",
        data_analise="2026-09-22 10:00:00",
        data_ultimo_despacho="15/09/2026",
        situacao=situacao,
        destino="SGA",
        acao_esperada="validar",
        pendencia_curta="pend",
        link_process="url",
        status_coleta="concluído",
        hash_ultimo_despacho=hash_,
    )


class StoreTest(unittest.TestCase):
    def _store(self, tmp):
        store = MirrorStore(Path(tmp) / "db.sqlite3")
        store.open()
        return store

    def test_replace_espelho_reconstroi_inteiro(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.replace_snapshot([row("001", "A"), row("002", "B")])
            snap = store.load_snapshot()
            self.assertEqual(set(snap), {"001", "002"})
            # reconstrução: remove antigo e insere atual
            store.replace_snapshot([row("002", "B2"), row("003", "C")])
            snap = store.load_snapshot()
            self.assertEqual(set(snap), {"002", "003"})
            self.assertEqual(snap["002"].situacao, "B2")
            store.close()

    def test_load_snapshot_vazio(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            self.assertEqual(store.load_snapshot(), {})
            store.close()

    def test_hash_deterministico_e_sensivel(self):
        self.assertEqual(despacho_hash("12345|15/09/2026"),
                         despacho_hash("12345|15/09/2026"))
        self.assertNotEqual(despacho_hash("12345|15/09/2026"),
                            despacho_hash("12346|15/09/2026"))