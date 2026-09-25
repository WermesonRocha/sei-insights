import sqlite3
import tempfile
import unittest
from pathlib import Path

from sei_insights.storage.mirror import MirrorStore, ProcessRow, despacho_hash


def row(numero: str, situacao: str = "X", hash_: str = "h") -> ProcessRow:
    return ProcessRow(
        numero=numero,
        data_execucao="2026-09-22 10:00:00",
        data_ultimo_despacho="15/09/2026",
        situacao=situacao,
        destino="SGA",
        acao_esperada="validar",
        pendencia_curta="pend",
        link_process="url",
        status_coleta="concluído",
        hash_ultimo_despacho=hash_,
    )


DEFAULT_SCHEMA = [
    "numero", "data_execucao", "data_ultimo_despacho", "situacao",
    "destino", "acao_esperada", "pendencia_curta", "status_coleta",
    "hash_ultimo_despacho", "link_process",
]


class StoreTest(unittest.TestCase):
    def _store(self, tmp):
        store = MirrorStore(Path(tmp) / "db.sqlite3")
        store.open()
        return store

    def test_open_recria_tabela_quando_schema_mudou(self):
        """Banco antigo (schema com colunas removidas) é recriado no open()."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.sqlite3"
            conn = sqlite3.connect(str(path))
            conn.execute(
                "CREATE TABLE processes (numero TEXT, data_analise TEXT, "
                "titulo TEXT, PRIMARY KEY (numero))"
            )
            conn.execute(
                "INSERT INTO processes (numero) VALUES ('001')"
            )
            conn.commit()
            conn.close()
            store = MirrorStore(path)
            store.open()
            cols = [r[1] for r in store.conn.execute("PRAGMA table_info(processes)")]
            self.assertEqual(cols, DEFAULT_SCHEMA)
            self.assertEqual(store.load_snapshot(), {})  # dados antigos descartados
            store.close()

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