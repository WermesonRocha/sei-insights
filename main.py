from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from report import build_resumo, write_spreadsheet
from sei_client import ProcessResult, SeiClient
from store import MirrorStore, ProcessRow

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("sei-insights")

STATE_DIR = Path(".state")
DATABASE_PATH = STATE_DIR / "sei_insights.sqlite3"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_arguments(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SEI Insights")
    parser.add_argument("--orgao", default="MMulheres")
    parser.add_argument("--unidade", default="MMULHERES-SE-SGA-CGATI-CTI-DTI")
    parser.add_argument("--dias", type=int, default=7)
    parser.add_argument("--inicio", default=None)
    parser.add_argument("--fim", default=None)
    parser.add_argument("--manual-captcha", action="store_true")
    parser.add_argument("--min-delay", type=float, default=2.0)
    parser.add_argument("--max-delay", type=float, default=5.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--saida", default="sei_insights.xlsx")
    args = parser.parse_args(argv)
    if args.dias <= 0:
        parser.error("--dias deve ser > 0")
    if args.min_delay < 0:
        parser.error("--min-delay não pode ser negativo")
    return args


AnalyzeCallable = Callable[[ProcessResult, Optional[ProcessRow], bool, str], ProcessRow]


def build_rows(
    previous: dict[str, ProcessRow],
    found: list[ProcessResult],
    analyze: AnalyzeCallable,
    force: bool,
    now: str,
) -> tuple[list[ProcessRow], list[ProcessRow]]:
    rows: list[ProcessRow] = []
    novos: list[ProcessRow] = []
    for p in found:
        prev = previous.get(p.number)
        row = None
        # Skip analyze if cached and not forced
        if prev is not None and not force:
            row = ProcessRow(
                numero=p.number, titulo=p.title, data_execucao=now,
                data_analise=prev.data_analise, data_ultimo_despacho=prev.data_ultimo_despacho,
                situacao=prev.situacao, destino=prev.destino, acao_esperada=prev.acao_esperada,
                pendencia_curta=prev.pendencia_curta, link_process=p.url,
                status_coleta="concluído (cache)", hash_ultimo_despacho=prev.hash_ultimo_despacho,
            )
        else:
            try:
                row = analyze(p, prev, force, now)
            except Exception as exc:
                logger.warning("Erro ao analisar %s: %s", p.number, exc)
                row = ProcessRow(
                    numero=p.number, titulo=p.title, data_execucao=now,
                    data_analise=now, data_ultimo_despacho="",
                    situacao="Erro / retry", destino="", acao_esperada="",
                    pendencia_curta="", link_process=p.url,
                    status_coleta=f"erro: {exc}", hash_ultimo_despacho="",
                )
        rows.append(row)
        if row.numero not in previous:
            novos.append(row)
    return rows, novos


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_arguments(argv)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    store = MirrorStore(DATABASE_PATH)
    store.open()
    try:
        previous = store.load_snapshot()
        now = now_str()
        # Imports de todas as fases (browser, árvore, texto, regras, relatório).
        from discovery import expected_total, pagination_params, parse_response  # noqa: F401
        from rate_limit import RateLimiter
        from rules import RulesEngine
        from sei_client import (  # noqa: F401
            ProcessResult, SeiClient)  # real flow uses these
        from text_ing import extract_text_from_pdf
        from tree import correlate_urls, parse_tree, select_last_despacho
        from utils import normalize_process_number  # noqa: F401

        rules = RulesEngine.from_file(Path("regras.json"))

        def analyze(p: ProcessResult, prev: Optional[ProcessRow],
                    force: bool, now: str) -> ProcessRow:
            # Este fluxo é satisfeito pelo SeiClient real (Task 11);
            # a assinatura é a interface testada em build_rows.
            raise NotImplementedError

        rows, novos = build_rows(previous, [], analyze, args.force, now)
        write_spreadsheet(Path(args.saida), rows, novos, build_resumo(rows, novos))
        store.replace_snapshot(rows)
        logger.info("Execução concluída: %d processos, %d novos.", len(rows), len(novos))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())