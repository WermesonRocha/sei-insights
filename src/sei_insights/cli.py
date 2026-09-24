from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from sei_insights.storage.report import build_resumo, write_spreadsheet
from sei_insights.clients.sei_client import ProcessResult, SeiClient
from sei_insights.storage.mirror import MirrorStore, ProcessRow
from sei_insights.config import STATE_DIR, DATABASE_PATH, REGRAS_JSON, DEFAULT_ORGAO, DEFAULT_UNIDADE, DEFAULT_DIAS, DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY, DEFAULT_SAIDA

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("sei-insights")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_arguments(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SEI Insights")
    parser.add_argument("--orgao", default=DEFAULT_ORGAO)
    parser.add_argument("--unidade", default=DEFAULT_UNIDADE)
    parser.add_argument("--dias", type=int, default=DEFAULT_DIAS)
    parser.add_argument("--inicio", default=None)
    parser.add_argument("--fim", default=None)
    parser.add_argument("--manual-captcha", action="store_true")
    parser.add_argument("--min-delay", type=float, default=DEFAULT_MIN_DELAY)
    parser.add_argument("--max-delay", type=float, default=DEFAULT_MAX_DELAY)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--saida", default=DEFAULT_SAIDA)
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
        # Pula analyze se houver cache, não forçado, E hash bate (mesmo último despacho)
        if prev is not None and not force:
            # analyze() deve retornar linha com hash_ultimo_despacho atualizado
            # Chamamos analyze para obter hash atual, mas se bate com prev, mantemos cache
            try:
                current_row = analyze(p, prev, force, now)
                if current_row.hash_ultimo_despacho == prev.hash_ultimo_despacho:
                    # Hash inalterado: usa dados do cache, preserva data de análise original
                    row = ProcessRow(
                        numero=p.number, titulo=p.title, data_execucao=now,
                        data_analise=prev.data_analise, data_ultimo_despacho=prev.data_ultimo_despacho,
                        situacao=prev.situacao, destino=prev.destino, acao_esperada=prev.acao_esperada,
                        pendencia_curta=prev.pendencia_curta, link_process=p.url,
                        status_coleta="concluído (cache)", hash_ultimo_despacho=prev.hash_ultimo_despacho,
                    )
                else:
                    # Hash mudou (novo despacho): usa análise fresca
                    row = current_row
            except Exception as exc:
                logger.warning("Erro ao analisar %s: %s", p.number, exc)
                row = ProcessRow(
                    numero=p.number, titulo=p.title, data_execucao=now,
                    data_analise=now, data_ultimo_despacho="",
                    situacao="Erro / retry", destino="", acao_esperada="",
                    pendencia_curta="", link_process=p.url,
                    status_coleta=f"erro: {exc}", hash_ultimo_despacho="",
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
        from sei_insights.clients.discovery import expected_total, pagination_params, parse_response  # noqa: F401
        from sei_insights.clients.rate_limit import RateLimiter
        from sei_insights.config.rules import RulesEngine
        from sei_insights.clients.sei_client import (  # noqa: F401
            ProcessResult, SeiClient)  # fluxo real usa estes
        from sei_insights.documents.text_ing import extract_text_from_pdf
        from sei_insights.documents.tree import correlate_urls, parse_tree, select_last_despacho
        from sei_insights.utils.helpers import normalize_process_number  # noqa: F401

        rules = RulesEngine.from_file(REGRAS_JSON)

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