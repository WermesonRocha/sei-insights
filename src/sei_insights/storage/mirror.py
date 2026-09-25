from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sei-insights")

FIELDS = [
    "numero", "data_execucao", "data_ultimo_despacho", "situacao",
    "destino", "acao_esperada", "pendencia_curta", "status_coleta",
    "hash_ultimo_despacho", "link_process",
]

CREATE_PROCESSES = (
    "CREATE TABLE IF NOT EXISTS processes ("
    + ", ".join(f"{f} TEXT" for f in FIELDS)
    + ", PRIMARY KEY (numero))"
)


@dataclass(slots=True)
class ProcessRow:
    numero: str
    data_execucao: str
    data_ultimo_despacho: str
    situacao: str
    destino: str
    acao_esperada: str
    pendencia_curta: str
    status_coleta: str
    hash_ultimo_despacho: str
    link_process: str


def despacho_hash(identificador: str) -> str:
    return hashlib.sha256(identificador.encode("utf-8")).hexdigest()


class MirrorStore:
    """Espelho SQLite exatamente igual à planilha (fonte da verdade)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def open(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(CREATE_PROCESSES)
        # Schema mudou (ex.: colunas removidas/renomeadas): recria a tabela
        # para o espelho continuar sendo exatamente igual à planilha.
        cols = [r[0] for r in self.conn.execute("PRAGMA table_info(processes)")]
        if cols != FIELDS:
            self.conn.execute("DROP TABLE processes")
            self.conn.execute(CREATE_PROCESSES.replace("IF NOT EXISTS ", ""))
        self.conn.commit()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _require(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("MirrorStore não aberto")
        return self.conn

    def load_snapshot(self) -> dict[str, ProcessRow]:
        conn = self._require()
        cur = conn.execute(
            f"SELECT {', '.join(FIELDS)} FROM processes"
        )
        snapshot: dict[str, ProcessRow] = {}
        for values in cur.fetchall():
            r = ProcessRow(**dict(zip(FIELDS, values)))
            snapshot[r.numero] = r
        return snapshot

    def replace_snapshot(self, rows: list[ProcessRow]) -> None:
        conn = self._require()
        conn.execute("DELETE FROM processes")
        if rows:
            placeholders = ", ".join("?" for _ in FIELDS)
            conn.executemany(
                f"INSERT INTO processes ({', '.join(FIELDS)}) "
                f"VALUES ({placeholders})",
                [tuple(getattr(r, f) for f in FIELDS) for r in rows],
            )
        conn.commit()