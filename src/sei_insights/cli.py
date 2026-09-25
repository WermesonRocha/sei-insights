from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from sei_insights.config import (
    STATE_DIR, DATABASE_PATH, REGRAS_JSON, DEFAULT_ORGAO, DEFAULT_UNIDADE,
    DEFAULT_DIAS, DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY, DEFAULT_SAIDA,
    DEFAULT_TIMEOUT_MS,
)
from sei_insights.storage.report import build_resumo, write_spreadsheet
from sei_insights.clients.sei_client import ProcessResult, SeiClient
from sei_insights.storage.mirror import MirrorStore, ProcessRow, despacho_hash
from sei_insights.clients.rate_limit import RateLimiter
from sei_insights.config.rules import RulesEngine
from sei_insights.documents.text_ing import extract_text_from_pdf
from sei_insights.documents.tree import parse_tree, select_last_despacho

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-8s | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("sei-insights")

BROWSER_STATE_PATH = STATE_DIR / "browser_state.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


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
    # Cache também casa pela URL do processo: a descoberta pode vir por nº de
    # documento (data-prot) numa execução e por nº canônico noutra; a URL da
    # página do processo é a identidade estável entre execuções.
    previous_by_link: dict[str, ProcessRow] = {
        prev_row.link_process: prev_row
        for prev_row in previous.values()
        if prev_row.link_process
    }
    for p in found:
        prev = previous.get(p.number) or previous_by_link.get(p.url)
        row = None
        # Pula analyze se houver cache, não forçado, E hash bate (mesmo último despacho)
        if prev is not None and not force:
            # analyze() deve retornar linha com hash_ultimo_despacho atualizado
            # Chamamos analyze para obter hash atual, mas se bate com prev, mantemos cache
            try:
                current_row = analyze(p, prev, force, now)
                if current_row.hash_ultimo_despacho == prev.hash_ultimo_despacho:
                    # Hash inalterado: usa dados do cache
                    row = ProcessRow(
                        numero=p.number, data_execucao=now,
                        data_ultimo_despacho=prev.data_ultimo_despacho,
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
                    numero=p.number, data_execucao=now, data_ultimo_despacho="",
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
                    numero=p.number, data_execucao=now, data_ultimo_despacho="",
                    situacao="Erro / retry", destino="", acao_esperada="",
                    pendencia_curta="", link_process=p.url,
                    status_coleta=f"erro: {exc}", hash_ultimo_despacho="",
                )
        rows.append(row)
        if prev is None:
            novos.append(row)
    return rows, novos


def _date_window(args: argparse.Namespace, today: datetime) -> tuple[str, str]:
    """Deriva a janela de datas DD/MM/YYYY para a pesquisa.

    Opera com qualquer objeto com atributos `inicio`, `fim` e `dias`
    (testável sem argparse). `today` é injetado para determinismo.
    """
    if args.inicio in (None, ""):
        inicio = (today - timedelta(days=args.dias)).strftime("%d/%m/%Y")
    else:
        inicio = args.inicio
    if args.fim in (None, ""):
        fim = today.strftime("%d/%m/%Y")
    else:
        fim = args.fim
    return inicio, fim


def create_browser(playwright: Playwright, *, headless: bool) -> tuple[Browser, BrowserContext, Page]:
    """Cria Browser/Context/Page reaproveitando o estado anterior (cookies)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    browser = playwright.chromium.launch(headless=headless)
    context_kwargs = {
        "user_agent": USER_AGENT,
        "locale": "pt-BR",
        "timezone_id": "America/Sao_Paulo",
        "accept_downloads": True,
    }
    if BROWSER_STATE_PATH.exists():
        context_kwargs["storage_state"] = str(BROWSER_STATE_PATH)
    context = browser.new_context(**context_kwargs)
    context.set_default_timeout(DEFAULT_TIMEOUT_MS)
    page = context.new_page()
    page.on("dialog", lambda dialog: dialog.dismiss())
    return browser, context, page


def save_browser_state(context: BrowserContext) -> None:
    """Salva cookies/local storage do contexto para a próxima execução."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(BROWSER_STATE_PATH))
    except Exception as exc:
        logger.warning("Não foi possível salvar estado do navegador: %s", exc)


def analyze_process(
    client: SeiClient,
    p: ProcessResult,
    prev: Optional[ProcessRow],
    force: bool,
    now: str,
    rules: RulesEngine,
) -> ProcessRow:
    """Pipeline completo de análise de um processo público.

    Abre a página, correlaciona a árvore documental, escolhe o último
    despacho e, só quando necessário, baixa o PDF e classifica o texto.
    O hash identifica o despacho (número|data), nunca o texto: assim um
    PDF digitalizado não congela o cache.
    """
    html = client.open_process(p)
    nodes = parse_tree(html)
    despacho = select_last_despacho(nodes)

    if despacho is None:
        # Sem despacho na árvore: não há o que baixar.
        return ProcessRow(
            numero=p.number, data_execucao=now, data_ultimo_despacho="",
            situacao="Sem despacho público", destino="", acao_esperada="",
            pendencia_curta="", link_process=p.url,
            status_coleta="concluído", hash_ultimo_despacho="",
        )

    identificador = f"{despacho.numero}|{despacho.data}"
    novo_hash = despacho_hash(identificador)

    if prev is not None and not force and prev.hash_ultimo_despacho == novo_hash:
        # Mesmo último despacho já analisado: reaproveita o cache completo.
        return ProcessRow(
            numero=p.number, data_execucao=now,
            data_ultimo_despacho=prev.data_ultimo_despacho,
            situacao=prev.situacao, destino=prev.destino,
            acao_esperada=prev.acao_esperada, pendencia_curta=prev.pendencia_curta,
            link_process=p.url, status_coleta="concluído (cache)",
            hash_ultimo_despacho=novo_hash,
        )

    # O download do despacho é por CLIQUE no link da árvore do SEI
    # (download_despacho). Sem link público, o despacho é tratado como
    # sem download possível, sem tentar rede.
    result = client.download_despacho(
        p.number, despacho.numero, despacho.serie,
    )

    if result is None:
        return ProcessRow(
            numero=p.number, data_execucao=now, data_ultimo_despacho="",
            situacao="Sem despacho público", destino="", acao_esperada="",
            pendencia_curta="", link_process=p.url,
            status_coleta="concluído", hash_ultimo_despacho="",
        )

    path, _, _ = result
    text = extract_text_from_pdf(path)

    if text == "":
        situacao = "Texto não extraível (digitalizado?)"
        destino = acao_esperada = pendencia_curta = ""
    else:
        r = rules.classify(text)
        situacao = r.situacao
        destino = r.destino
        acao_esperada = r.acao_esperada
        pendencia_curta = r.pendencia_curta

    return ProcessRow(
        numero=p.number, data_execucao=now,
        data_ultimo_despacho=despacho.data,
        situacao=situacao, destino=destino, acao_esperada=acao_esperada,
        pendencia_curta=pendencia_curta, link_process=p.url,
        status_coleta="concluído", hash_ultimo_despacho=novo_hash,
    )


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_arguments(argv)
    if args.max_delay < args.min_delay:
        logger.error("--max-delay deve ser >= --min-delay.")
        return 2
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    store = MirrorStore(DATABASE_PATH)
    store.open()
    try:
        previous = store.load_snapshot()
        now = now_str()
        rules = RulesEngine.from_file(REGRAS_JSON)
        rate_limiter = RateLimiter(args.min_delay, args.max_delay)
        inicio, fim = _date_window(args, datetime.now())

        browser: Optional[Browser] = None
        context: Optional[BrowserContext] = None
        rows: list[ProcessRow] = []
        novos: list[ProcessRow] = []
        with sync_playwright() as playwright:
            try:
                browser, context, page = create_browser(playwright, headless=False)
                client = SeiClient(context=context, page=page, rate_limiter=rate_limiter)
                client.use_manual_captcha = args.manual_captcha

                found = client.search_processes(args.orgao, args.unidade, inicio, fim)
                logger.info("Processos encontrados no período %s..%s: %d",
                            inicio, fim, len(found))

                def analyze(p: ProcessResult, prev: Optional[ProcessRow],
                            force: bool, now: str) -> ProcessRow:
                    return analyze_process(client, p, prev, force, now, rules)

                rows, novos = build_rows(previous, found, analyze, args.force, now)
            finally:
                # Fechamos o context/browser AINDA DENTRO do bloco
                # `with sync_playwright()`: depois disso o event loop já
                # está parado e o close() falha com "Event loop is closed!".
                if context is not None:
                    save_browser_state(context)
                    try:
                        context.close()
                    except Exception as exc:
                        logger.warning(
                            "Não foi possível fechar o contexto: %s", exc,
                        )
                if browser is not None:
                    try:
                        browser.close()
                    except Exception as exc:
                        logger.warning(
                            "Não foi possível fechar o navegador: %s", exc,
                        )

        write_spreadsheet(Path(args.saida), rows, novos, build_resumo(rows, novos))
        store.replace_snapshot(rows)
        logger.info("Execução concluída: %d processos, %d novos.", len(rows), len(novos))
        return 0
    finally:
        store.close()