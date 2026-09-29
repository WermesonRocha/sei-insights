from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from sei_insights.config import DEFAULT_TIMEOUT_MS

from sei_insights.clients.captcha_solver import CaptchaSolver
from sei_insights.clients.discovery import (
    expected_total,
    extract_process_number,
    pagination_params,
    parse_response,
)
from sei_insights.clients.rate_limit import RateLimiter
from sei_insights.utils.helpers import normalize_process_number, safe_filename, calculate_sha256, extension_from_content_type, looks_like_html, unique_path

logger = logging.getLogger("sei-insights")

BASE_URL = "https://colaboragov.sei.gov.br/sei/"
PUBLIC_SEARCH_URL = "https://colaboragov.sei.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=7"
SEARCH_PAGE_SIZE = 50
MAX_RETRIES = 3

# A tabela de documentos do processo (#tblDocumentos) é montada via JS; o
# link do despacho pode demorar a aparecer no DOM.
DESPACHO_TREE_TIMEOUT_MS = 45_000

# Fluxo do modal "Gerar PDF" (#divInfraModal): o SEI valida o CAPTCHA ao
# gerar o PDF do(s) documento(s) selecionado(s). Tentativas e timeouts.
PDF_DOWNLOAD_TIMEOUT_MS = 300_000
PDF_ATTEMPTS = 3
PDF_CAPTCHA_POLL_INTERVAL_MS = 500
PDF_CAPTCHA_TIMEOUT_MS = 30_000
PDF_CONTENT_TYPE = "application/pdf"


def _is_transient_download_exception(exc: Exception) -> bool:
    """Diz se uma exceção de download merece nova tentativa.

    Só erros transitórios repetem: timeout do Playwright, falhas de rede
    (net::*) e timeouts genéricos. URL inválida, HTTP 4xx e conteúdo
    inesperado são permanentes: retentá-los só trava a execução
    (log real: "APIRequestContext.get: Invalid URL. Tentativa 1/3...").
    """
    if isinstance(exc, (PlaywrightTimeoutError, TimeoutError)):
        return True
    message = str(exc)
    return "net::" in message or "timeout" in message.lower()
SEARCH_RESULT_DELAY_MS = 1000

STATE_DIR = Path(".state")
DEBUG_DIR = STATE_DIR / "debug"
DOWNLOAD_DIR = Path("downloads")

# Mapa rótulo -> value do multi-select #selOrgaoPesquisa (docs/spike-2026-09-22.md).
# A normalização usa letras maiúsculas sem espaços.
ORGAO_VALUES: dict[str, str] = {
    "CMB": "1",
    "COAF": "2",
    "MDIC": "6",
    "ME": "0",
    "MEMP": "10",
    "MF": "4",
    "MGI": "7",
    "MIR": "12",
    "MMULHERES": "11",
    "MPI": "8",
    "MPO": "5",
    "MPS": "9",
    "MTP": "3",
}


def _normalize_unidade_label(value: str) -> str:
    """Normaliza rótulo de unidade para comparação (minúsculas, sem espaços a mais)."""
    return " ".join(str(value).split()).casefold()


def _unidade_matches(candidate: str, wanted: str) -> bool:
    """Compara rótulo candidato do autocomplete com o alvo (parcial ok)."""
    if not candidate or not wanted:
        return False
    return candidate == wanted or candidate in wanted or wanted in candidate


def _is_process_number(value: str) -> bool:
    """Diz se o valor parece um número de processo SEI (NNNNN.NNNNNN/YYYY-NN).

    Linhas de documento da busca têm `data-prot` = número do documento
    (ex.: 64534686), que não casa com o formato de processo; usamos isso
    para preferir o número real de processo quando navegamos o mesmo link.
    """
    return bool(re.fullmatch(r"\d{4,5}\.\d{6,8}/\d{4}-\d{2}",
                             normalize_process_number(value)))


@dataclass(slots=True)
class ProcessResult:
    number: str
    url: str
    title: str


@dataclass(slots=True)
class PublicDocument:
    number: str
    name: str
    url: str


def extract_process(html: str, requested_number: str) -> Optional[ProcessResult]:
    """Extrai processo do HTML correspondente ao número solicitado."""
    soup = BeautifulSoup(html, "html.parser")
    # Tenta encontrar pelo atributo data-prot
    for row in soup.select("[data-prot]"):
        prot = row.get("data-prot", "").strip()
        if normalize_process_number(prot) == normalize_process_number(requested_number):
            link = row.select_one("a[href*='md_pesq_processo_exibir.php']")
            if link:
                return ProcessResult(
                    number=normalize_process_number(requested_number),
                    url=link.get("href", ""),
                    title=link.get_text(strip=True)
                )
    return None


def _process_directory(process_number: str) -> Path:
    """Retorna/cria o diretório local do processo sob downloads/."""
    directory_name = safe_filename(process_number.replace("/", "_"))
    directory = DOWNLOAD_DIR / directory_name
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _store_download(
    directory: Path,
    filename: str,
    temporary_path: Path,
    body: bytes,
    content_type: str,
) -> tuple[Path, str, str]:
    """Valida o conteúdo do download e promove o .part para o nome final.

    Em caso de conteúdo inválido, remove o arquivo temporário antes de
    levantar RuntimeError (nunca deixamos .part para trás).

    Retorno: caminho_local, sha256, content_type.
    """
    if not body:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError("O download retornou conteúdo vazio.")

    normalized_content_type = (
        (content_type or "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )

    if normalized_content_type == "text/html":
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError(
            "O download retornou HTML em vez do arquivo esperado "
            f"({filename})."
        )

    if looks_like_html(body):
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError(
            "O download retornou HTML em vez do arquivo esperado "
            f"({filename})."
        )

    final_path = directory / filename
    temporary_path.replace(final_path)

    digest = calculate_sha256(final_path)

    return final_path, digest, content_type


def _save_download(
    download,
    directory: Path,
    filename: str,
) -> tuple[Path, str, str]:
    """Salva um objeto Download do Playwright (evento download do modal).

    Verifica download.failure(), grava o arquivo recebido em .part e
    delega a validação/promoção a ``_store_download``.

    Retorno: caminho_local, sha256, content_type.
    """
    failure = download.failure()

    if failure is not None:
        raise RuntimeError(f"Falha no download do arquivo: {failure}")

    temporary_path = directory / ("." + filename + ".part")

    download.save_as(temporary_path)

    body = temporary_path.read_bytes()

    return _store_download(
        directory,
        filename,
        temporary_path,
        body,
        PDF_CONTENT_TYPE,
    )


class SeiClient:
    def __init__(self, context, page, rate_limiter: RateLimiter) -> None:
        self.context = context
        self.page = page
        self.rate_limiter = rate_limiter
        self.use_manual_captcha = False

    @staticmethod
    def is_search_response(response) -> bool:
        """Verifica se a resposta é a resposta AJAX de pesquisa."""
        try:
            if response.request.method != "POST":
                return False
            url = response.request.url
            return (
                "md_pesq_controlador_ajax_externo.php" in url
                and "acao_ajax_externo=protocolo_pesquisar" in url
                and ("isPaginacao=false" in url or "isPaginacao=true" in url)
            )
        except Exception:
            return False

    def save_debug(self, name: str) -> None:
        """Salva screenshot e HTML para debug em .state/debug/."""
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning("Falha ao criar diretório de debug: %s", exc)
            return

        base = safe_filename(name)
        screenshot_path = DEBUG_DIR / f"{base}.png"
        html_path = DEBUG_DIR / f"{base}.html"

        try:
            self.page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception as exc:
            logger.warning("Falha ao salvar screenshot: %s", exc)

        try:
            html_path.write_text(self.page.content(), encoding="utf-8")
        except Exception as exc:
            logger.warning("Falha ao salvar HTML de diagnóstico: %s", exc)

        logger.info("Diagnóstico salvo em: %s", DEBUG_DIR)

    def open_search_page(self) -> None:
        """Abre a página de pesquisa."""
        logger.info("Abrindo Pesquisa Pública...")

        self.page.goto(
            PUBLIC_SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=DEFAULT_TIMEOUT_MS,
        )

        # O SEI possui Javascript e chamadas auxiliares que podem deixar
        # conexões abertas por bastante tempo.
        self.page.wait_for_timeout(1500)

    def process_input(self):
        """Obtém elemento de input do processo."""
        locator = self.page.locator("#txtProtocoloPesquisa")

        if locator.count() == 0:
            locator = self.page.locator('input[name="txtProtocoloPesquisa"]')

        if locator.count() == 0:
            self.save_debug("campo_process_not_found")
            raise RuntimeError("Campo txtProtocoloPesquisa não encontrado.")

        return locator.first

    def captcha_input(self):
        """Obtém elemento de input do CAPTCHA."""
        locator = self.page.locator("#txtInfraCaptcha")

        if locator.count() == 0:
            locator = self.page.locator('input[name="txtInfraCaptcha"]')

        if locator.count() == 0:
            return None

        return locator.first

    def captcha_is_present(self) -> bool:
        """Verifica se CAPTCHA está presente."""
        return self.captcha_input() is not None

    def captcha_has_value(self) -> bool:
        """Verifica se CAPTCHA tem valor."""
        locator = self.captcha_input()

        if locator is None:
            return False

        try:
            value = locator.input_value()
        except Exception:
            return False

        return bool(value.strip())

    def wait_for_manual_captcha(self) -> None:
        """Aguarda CAPTCHA manual."""
        if not self.captcha_is_present():
            logger.info("CAPTCHA não presente.")
            return

        if self.captcha_has_value():
            logger.info("CAPTCHA já preenchido.")
            return

        print()
        print("=" * 78)
        print("CAPTCHA DA PESQUISA PÚBLICA")
        print("=" * 78)
        print("Preencha o CAPTCHA diretamente no navegador.")
        print("Não pressione ENTER no terminal.")
        print(
            "Assim que o campo for preenchido, o programa "
            "continuará automaticamente."
        )
        print("=" * 78)
        print()

        try:
            self.page.wait_for_function(
                """
                () => {
                    const element =
                        document.querySelector('#txtInfraCaptcha');

                    if (!element) {
                        return true;
                    }

                    return (
                        typeof element.value === 'string'
                        && element.value.trim().length > 0
                    );
                }
                """,
                timeout=300 * 1000,
            )
        except PlaywrightTimeoutError as exc:
            self.save_debug("captcha_timeout")
            raise RuntimeError(
                "O CAPTCHA não foi preenchido dentro de 300 segundos."
            ) from exc

        logger.info("CAPTCHA preenchido.")

    def solve_search_captcha(self) -> None:
        """Resolve CAPTCHA da pesquisa."""
        if getattr(self, "use_manual_captcha", False):
            self.wait_for_manual_captcha()
            return

        if not self.captcha_is_present():
            logger.info("CAPTCHA da pesquisa não presente.")
            return

        if self.captcha_has_value():
            logger.info("CAPTCHA da pesquisa já preenchido.")
            return

        logger.info("Resolvendo CAPTCHA da pesquisa via OCR...")

        solver = CaptchaSolver(max_retries=3)
        solver.solve_captcha_in_page(self.page, "#imgCaptcha")

        self.page.wait_for_timeout(SEARCH_RESULT_DELAY_MS)

    def find_search_submit(self):
        """Encontra botão de submit da pesquisa."""
        form = self.page.locator("#seiSearch")

        if form.count() == 0:
            raise RuntimeError("Formulário #seiSearch não encontrado.")

        candidates = [
            form.locator("#sbmPesquisar"),
            form.get_by_role("button", name=re.compile(r"Pesquisar", re.IGNORECASE)),
            form.get_by_role("button", name=re.compile(r"Pesquisa", re.IGNORECASE)),
            form.locator('input[type="submit"]'),
            form.locator('button[type="submit"]'),
        ]

        for candidate in candidates:
            try:
                if candidate.count() > 0:
                    return candidate.first
            except Exception:
                continue

        return None

    def submit_search(self) -> None:
        """Submete a pesquisa."""
        form = self.page.locator("#seiSearch")

        if form.count() == 0:
            self.save_debug("formulario_seiSearch_nao_encontrado")
            raise RuntimeError("Formulário #seiSearch não encontrado.")

        logger.info("Executando a pesquisa...")

        # Clique real no botão "Pesquisar" (#sbmPesquisar): é o mesmo
        # mecanismo de um usuário e faz o SEI executar o fluxo oficial
        # (OnSubmitForm -> CaptchaSEI::validarOnSubmit ->
        # carregarProximaPagina). requestSubmit() fica só como fallback
        # caso o botão não seja localizado.
        submitter = self.find_search_submit()
        if submitter is not None:
            try:
                submitter.click()
                return
            except Exception as exc:
                logger.warning(
                    "Clique no botão de pesquisa falhou: %s", exc,
                )

        try:
            self.page.evaluate(
                """
                () => {
                    const form = document.getElementById('seiSearch');

                    if (!form) {
                        throw new Error('Form #seiSearch não encontrado.');
                    }

                    form.requestSubmit();
                }
                """
            )
        except Exception as exc:
            self.save_debug("erro_ao_submeter_formulario")
            raise RuntimeError(
                "Não foi possível submeter o formulário "
                f"da Pesquisa Pública: {exc}"
            ) from exc

    def _ensure_checked(self, name: str) -> None:
        """Marca checkbox do SEI via DOM (evento change).

        O <label class="infraCheckboxLabel"> do SEI intercepta o clique
        do Playwright .check(), que fica em retry até timeout (log real
        com chkSinDocumentosGerados, 90s). Setar `checked` e disparar o
        evento `change` via JS reproduz o efeito do clique sem depender
        de ponteiro — mesmo padrão usado para #hdnIdUnidade.
        """
        try:
            found = self.page.evaluate(
                """(name) => {
                    const el = document.getElementById(name)
                        || document.querySelector(
                            "input[name='" + name + "']"
                        );
                    if (!el) {
                        return false;
                    }
                    el.checked = true;
                    el.dispatchEvent(
                        new Event('change', { bubbles: true })
                    );
                    return true;
                }""",
                name,
            )
        except Exception as exc:
            logger.warning("Não foi possível marcar %s: %s", name, exc)
            return
        if not found:
            logger.warning("Campo %s não encontrado.", name)

    def _set_search_criteria(self, orgao: str, unidade: str,
                             inicio: str, fim: str) -> None:
        """Define critérios de pesquisa per spike (docs/spike-2026-09-22.md).

        Órgão via plugin jQuery multipleSelect de #selOrgaoPesquisa; se o
        rótulo não estiver no mapa ORGAO_VALUES, marca todos os órgãos
        (fallback ensure_orgaos_selected).
        """
        value = ORGAO_VALUES.get(orgao.strip().upper())

        if value is None:
            logger.info(
                "Órgão %r não mapeado; selecionando todos os órgãos.",
                orgao,
            )
            self.ensure_orgaos_selected()
        else:
            try:
                self.page.evaluate(
                    """(selOrg) => {
                        const $o = $('#selOrgaoPesquisa');

                        if ($o.length && $o.multipleSelect
                            && typeof $o.multipleSelect === 'function') {
                            $o.multipleSelect('setSelects', [selOrg]);
                        } else if ($o.length) {
                            $o.val(selOrg).trigger('change');
                        }

                        return $o.length;
                    }""",
                    value,
                )
            except Exception as exc:
                logger.warning(
                    "Falha ao selecionar órgão %s: %s; usando todos os órgãos.",
                    orgao,
                    exc,
                )
                self.ensure_orgaos_selected()

        # Unidade Geradora: campo texto visível + id oculto #hdnIdUnidade.
        # Sem o id oculto o SEI não restringe por unidade (spike:47-48,111),
        # e o widget só grava o id ao clicar numa opção do dropdown —
        # então digitamos o rótulo e clicamos na 1ª opção (rota primária).
        # Fallback: POST determinístico ao endpoint de autocomplete
        # (spike:35-45). Se nada resolver, degradamos sem raise (aviso +
        # save_debug) e a pesquisa segue só por órgão/período.
        unit = self.page.locator("#txtUnidade")
        if unit.count() == 0:
            unit = self.page.locator('input[name="txtUnidade"]')
        if unit.count() == 0:
            logger.warning("Campo de unidade #txtUnidade não encontrado.")
        else:
            unit_id = self._resolve_unidade_dropdown(unidade)
            if not unit_id:
                unit_id = self._resolve_unidade_id(unidade, value)
            if unit_id:
                try:
                    self.page.evaluate(
                        """(unit_id) => {
                            const el = document.getElementById('hdnIdUnidade');
                            if (el) {
                                el.value = String(unit_id);
                                el.dispatchEvent(
                                    new Event('change', { bubbles: true })
                                );
                            }
                        }""",
                        unit_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "Não foi possível preencher #hdnIdUnidade: %s", exc,
                    )
            resolved = self.page.evaluate(
                "() => (document.getElementById('hdnIdUnidade') || {}).value || ''"
            )
            if resolved.strip():
                logger.info(
                    "Unidade %r resolvida para id oculto %r.",
                    unidade, resolved,
                )
            else:
                logger.warning(
                    "Unidade %r não resolvida; a pesquisa seguirá sem "
                    "filtro de unidade (apenas órgão/período).", unidade,
                )
                self.save_debug("unidade_sem_resolucao")

        # Marca os três tipos de pesquisa (P, G, R) via DOM + change:
        # o label do SEI intercepta o clique do Playwright .check().
        for name in ("chkSinProcessos", "chkSinDocumentosGerados",
                     "chkSinDocumentosRecebidos"):
            self._ensure_checked(name)

        # Datas no formato DD/MM/YYYY.
        for field, field_value in (("#txtDataInicio", inicio),
                                   ("#txtDataFim", fim)):
            f = self.page.locator(field)
            if f.count() == 0:
                f = self.page.locator(f'input[name="{field[1:]}"]')
            if f.count():
                f.first.fill(field_value)
            else:
                logger.warning("Campo de data %s não encontrado.", field)

    def _fetch_page(self, inicio: int, page_size: int) -> dict:
        """Busca uma página de resultados via POST AJAX (pagination)."""
        params = pagination_params(inicio, page_size)
        self.rate_limiter.wait()

        url = BASE_URL + "modulos/pesquisa/md_pesq_controlador_ajax_externo.php"

        form = self.page.evaluate(
            """() => {
                const f = document.getElementById('seiSearch');
                const d = new FormData(f);
                const o = {};
                for (const [k, v] of d.entries()) o[k] = String(v);
                return o;
            }"""
        )

        response = self.context.request.post(
            url,
            params={
                "acao_ajax_externo": "protocolo_pesquisar",
                "id_orgao_acesso_externo": "7",
                **params,
            },
            form=form,
            fail_on_status_code=False,
        )

        try:
            if response.status >= 400:
                return {"itens": 0, "html": ""}
            return response.json()
        except Exception:
            self.save_debug("paginacao_ajax_invalida")
            return {"itens": 0, "html": ""}
        finally:
            try:
                response.dispose()
            except Exception:
                pass

    def _find_process_link(self, number: str, data: dict) -> str:
        """Encontra o link absoluto do processo via extract_process no HTML."""
        found = extract_process(data.get("html", "") or "", number)
        if found is None or not found.url:
            return ""
        return urljoin(PUBLIC_SEARCH_URL, found.url)

    def _build_process_result(self, number: str, link: str) -> ProcessResult:
        """Constrói resultado do processo a partir do número e do link."""
        return ProcessResult(number=number, url=link, title="")

    def _add_result(self, results: dict, number: str, data: dict) -> None:
        """Adiciona resultado ao dicionário (dedupe pela URL do processo).

        O SEI devolve linhas de documento na mesma pesquisa (Documentos
        Gerados/Recebidos): uma linha de documento tem `data-prot` = nº do
        documento e link `md_pesq_processo_exibir.php` para o processo-pai.
        Duas linhas com a MESMA URL de processo são o mesmo processo (bug
        real: o mesmo despacho foi baixado 2x). Quando o número tem formato
        de processo, ele vence o número de documento da coluna.
        """
        link = self._find_process_link(number, data)
        if not link:
            if number in results:
                return
            results[number] = self._build_process_result(number, "")
            return
        for existing in list(results.values()):
            if existing.url != link:
                continue
            if _is_process_number(number) and not _is_process_number(existing.number):
                del results[existing.number]
                results[number] = self._build_process_result(number, link)
            return
        results[number] = self._build_process_result(number, link)

    def _parse_autocomplete_html(self, html: str) -> list[tuple[str, str]]:
        """Extrai (rótulo, id) de um HTML de autocomplete (li/option)."""
        items: list[tuple[str, str]] = []
        soup = BeautifulSoup(html or "", "html.parser")
        for node in soup.select("li, option"):
            label = node.get_text(" ", strip=True)
            unit_id = (
                node.get("value")
                or node.get("data-value")
                or node.get("id")
                or ""
            ).strip()
            if label and unit_id:
                items.append((label, unit_id))
        return items

    def _parse_autocomplete_items(self, response) -> list[tuple[str, str]]:
        """Extrai (rótulo, id) da resposta do autocomplete de unidade.

        Aceita JSON (lista de dicts ou `{"html": ...}`) e HTML cru
        (li/option). Shape exato não é verificável offline — parseamos
        defensivamente e deixamos o chamador degradar se não casar.
        """
        try:
            payload = response.json()
        except Exception:
            payload = None

        items: list[tuple[str, str]] = []

        if isinstance(payload, list):
            for row in payload:
                if not isinstance(row, dict):
                    continue
                unit_id = next(
                    (str(row[k]) for k in (
                        "id", "id_unidade", "cod_unidade",
                        "value", "id_unidade_geradora")
                     if row.get(k) not in (None, "")),
                    "",
                )
                label = next(
                    (str(row[k]) for k in (
                        "nome", "nome_unidade", "label", "text", "sigla")
                     if row.get(k) not in (None, "")),
                    "",
                )
                if unit_id and label:
                    items.append((label, unit_id))
        elif isinstance(payload, dict):
            items = self._parse_autocomplete_html(payload.get("html") or "")
            if not items:
                for key, value in payload.items():
                    if key in ("html", "itens"):
                        continue
                    items.append((str(value), str(key)))
        else:
            try:
                items = self._parse_autocomplete_html(response.text())
            except Exception:
                items = []

        return items

    def _resolve_unidade_id(self, unidade: str,
                            orgao_value: Optional[str]) -> Optional[str]:
        """Resolve o id da unidade via endpoint de autocomplete do SEI.

        Rota preferida, determinística (spike:35-45): POST ao mesmo
        endpoint usado pelo widget infraAjaxAutoCompletar
        (`acao_ajax_externo=unidade_auto_completar_todas` com
        `palavras_pesquisa=<rótulo>` e `id_orgao=<órgão>` quando o órgão
        foi mapeado). Retorna o primeiro id cujo rótulo casa com a
        unidade alvo; None se nada casa ou o POST falhar (o chamador
        tenta o fallback por dropdown e depois degrada).
        """
        url = BASE_URL + "modulos/pesquisa/md_pesq_controlador_ajax_externo.php"
        params = {
            "acao_ajax_externo": "unidade_auto_completar_todas",
            "id_orgao_acesso_externo": "7",
        }
        data: dict[str, str] = {"palavras_pesquisa": unidade}
        if orgao_value is not None:
            data["id_orgao"] = str(orgao_value)

        self.rate_limiter.wait()

        try:
            response = self.context.request.post(
                url, params=params, form=data, fail_on_status_code=False,
            )
        except Exception as exc:
            logger.warning(
                "Falha no POST de autocomplete de unidade: %s", exc,
            )
            return None

        try:
            if response.status >= 400:
                return None
            candidates = self._parse_autocomplete_items(response)
        except Exception as exc:
            logger.warning("Resposta de autocomplete inválida: %s", exc)
            return None
        finally:
            try:
                response.dispose()
            except Exception:
                pass

        wanted = _normalize_unidade_label(unidade)
        for label, unit_id in candidates:
            if _unidade_matches(_normalize_unidade_label(label), wanted):
                return unit_id
        return None

    def _resolve_unidade_dropdown(self, unidade: str) -> Optional[str]:
        """Seleciona a unidade clicando na 1ª opção do autocomplete.

        O widget infraAjaxAutoCompletar só grava #hdnIdUnidade quando
        uma opção do dropdown é clicada (spike:32-48; confirmado ao
        vivo): digitamos o rótulo no #txtUnidade com eventos reais de
        teclado (press_sequentially) e clicamos na primeira opção
        listada — é o JS do SEI que preenche o id oculto.
        """
        field = self.page.locator("#txtUnidade")
        if field.count() == 0:
            field = self.page.locator('input[name="txtUnidade"]')
        if field.count() == 0:
            return None

        try:
            field.first.click()
            field.first.press_sequentially(unidade, delay=50)

            menu = self.page.locator(
                "#divInfraAjaxtxtUnidade li, .infraAjaxAutoCompletar li, "
                "ul.ui-autocomplete li, .ui-menu-item"
            )
            menu.first.wait_for(state="visible", timeout=5_000)
            if menu.count() > 0:
                menu.first.click()
        except Exception as exc:
            logger.warning("Autocomplete de unidade falhou: %s", exc)
            return None

        return self.page.evaluate(
            "() => (document.getElementById('hdnIdUnidade') || {}).value || ''"
        )

    def search_processes(self, orgao: str, unidade: str,
                         inicio: str, fim: str, page_size: int = 50) -> list[ProcessResult]:
        """Pesquisa processos por órgão/unidade/período e pagina os resultados."""
        self.open_search_page()

        # Segue o coletor (main.py:3590-3621): o CAPTCHA é resolvido antes
        # de qualquer requisição de pesquisa ao SEI, inclusive o POST de
        # autocomplete de unidade feito dentro de _set_search_criteria.
        self.solve_search_captcha()

        self._set_search_criteria(orgao, unidade, inicio, fim)
        results: dict[str, ProcessResult] = {}

        try:
            with self.page.expect_response(
                SeiClient.is_search_response,
                timeout=DEFAULT_TIMEOUT_MS,
            ) as response_info:
                self.submit_search()
            response = response_info.value
        except PlaywrightTimeoutError as exc:
            self.save_debug("submit_sem_ajax")
            raise RuntimeError(
                "O CAPTCHA foi preenchido, mas o SEI não "
                "executou a chamada AJAX de pesquisa."
            ) from exc

        try:
            if response.status >= 400:
                body = response.text()
                raise RuntimeError(
                    f"A Pesquisa Pública respondeu com HTTP {response.status}.\n"
                    f"Resposta:\n{body[:3000]}"
                )

            data = response.json()
        except RuntimeError:
            raise
        except Exception as exc:
            self.save_debug("resposta_ajax_invalida")
            raise RuntimeError(
                "O SEI retornou uma resposta AJAX que não "
                "pôde ser interpretada como JSON."
            ) from exc
        finally:
            try:
                response.dispose()
            except Exception:
                pass

        page_numbers = parse_response(data)
        for number in page_numbers:
            self._add_result(results, number, data)

        page = page_size

        # Contrato real do SEI (spike:100,126,212): a resposta AJAX traz
        # apenas {"html": ...}, sem campo itens, então expected_total é 0.
        # Paginamos enquanto a última página devolveu uma página cheia;
        # paramos na primeira página curta ou vazia. expected_total serve
        # só como limite adicional quando itens existe e o safety valve
        # evita paginação infinita.
        while len(page_numbers) == page_size:
            self.solve_search_captcha()
            page_data = self._fetch_page(page, page_size)
            page_numbers = parse_response(page_data)
            if not page_numbers:
                break
            for number in page_numbers:
                self._add_result(results, number, page_data)
            total_known = expected_total(page_data)
            if total_known and len(results) >= total_known:
                break
            page += page_size
            if page > page_size * 50:  # safety valve
                break

        return list(results.values())

    def open_process(self, process: ProcessResult) -> str:
        """Abre página do processo e retorna o HTML."""
        logger.info("Abrindo processo público...")

        self.page.goto(
            process.url,
            wait_until="domcontentloaded",
            timeout=DEFAULT_TIMEOUT_MS,
        )

        self.page.wait_for_timeout(1000)

        current_url = self.page.url
        if "md_pesq_processo_exibir.php" not in current_url:
            # O navegador não carregou a página do processo (ex.: redirecionou
            # de volta para a pesquisa). Sem o link público correto, a árvore
            # vira ruído e o download da URL vazia falharia (Invalid URL).
            self.save_debug("pagina_processo_nao_aberta")
            logger.warning(
                "A página do processo não carregou (URL atual: %s).",
                current_url,
            )

        html = self.page.content()

        # Número canônico: a descoberta pode ter vindo de uma linha de
        # documento (data-prot = nº do documento). O cabeçalho da página do
        # processo (Processo:) é a fonte autoritativa para pasta e linha.
        canonical = extract_process_number(html)
        if canonical:
            process.number = canonical

        return html

    def extract_documents(self, process_html: str, process_url: str) -> list[PublicDocument]:
        """Extrai documentos públicos da página do processo."""
        soup = BeautifulSoup(process_html, "html.parser")

        documents: list[PublicDocument] = []
        seen: set[str] = set()

        for link in soup.select('a[href*="md_pesq_documento_consulta_externa.php"]'):
            href = link.get("href")

            if not href:
                continue

            url = urljoin(process_url, href)

            if url in seen:
                continue

            seen.add(url)

            text = link.get_text(" ", strip=True)
            title = link.get("title")
            name = text or title or "Documento"

            number_match = re.search(r"\d{5,}", text)
            number = number_match.group(0) if number_match else ""

            documents.append(PublicDocument(number=number, name=name, url=url))

        return documents

    def download_document(self, process_number: str, document: PublicDocument):
        """Baixa documento via APIRequestContext do Playwright.

        Retorno: caminho_local, sha256, content_type.
        """
        logger.info("Baixando documento: %s", document.name)

        parsed = urlparse(document.url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise RuntimeError(
                f"URL inválida para download: {document.url!r}"
            )

        self.rate_limiter.wait()

        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.debug(
                    "GET documento, tentativa %d/%d: %s",
                    attempt,
                    MAX_RETRIES,
                    document.url,
                )

                response = self.context.request.get(
                    document.url,
                    timeout=DEFAULT_TIMEOUT_MS,
                    fail_on_status_code=False,
                )

                status = response.status

                # 429 - RATE LIMIT
                if status == 429:
                    retry_after = response.headers.get("retry-after")
                    response.dispose()

                    if retry_after:
                        try:
                            delay = float(retry_after)
                        except ValueError:
                            delay = 30.0
                    else:
                        delay = min(60.0, 5.0 * (2 ** (attempt - 1)))

                    self.rate_limiter.wait_seconds(delay)
                    continue

                # ERROS 5xx
                if 500 <= status <= 599:
                    response.dispose()

                    delay = min(60.0, 2.0 * (2 ** (attempt - 1)))
                    delay += random.uniform(0, 1)

                    logger.warning(
                        "Servidor respondeu HTTP %s. "
                        "Tentativa %d/%d. Aguardando %.2fs.",
                        status,
                        attempt,
                        MAX_RETRIES,
                        delay,
                    )

                    self.rate_limiter.wait_seconds(delay)
                    continue

                # OUTROS ERROS
                if status >= 400:
                    body = response.body()
                    response.dispose()
                    raise RuntimeError(
                        f"Download retornou HTTP {status}. "
                        f"URL={document.url}. "
                        f"Resposta inicial={body[:500]!r}"
                    )

                # SUCESSO
                content_type = response.headers.get("content-type")
                body = response.body()
                response.dispose()

                directory = _process_directory(process_number)

                extension = extension_from_content_type(content_type)
                clean_name = safe_filename(document.name)

                if document.number:
                    filename = f"{document.number}_{clean_name}{extension}"
                else:
                    filename = f"{clean_name}{extension}"

                final_path = unique_path(directory / filename)

                temporary_path = directory / ("." + final_path.name + ".part")
                temporary_path.write_bytes(body)

                return _store_download(
                    directory,
                    final_path.name,
                    temporary_path,
                    body,
                    content_type,
                )

            except Exception as exc:
                # Erros permanentes (URL inválida, HTTP 4xx, conteúdo
                # inesperado) não ganham retry: repetir é inútil e trava.
                if not _is_transient_download_exception(exc):
                    raise

                last_error = exc

                if attempt >= MAX_RETRIES:
                    break

                delay = min(60.0, 2.0 * (2 ** (attempt - 1)))
                delay += random.uniform(0, 1)

                logger.warning(
                    "Erro ao baixar documento: %s. Tentativa %d/%d. "
                    "Aguardando %.2fs.",
                    exc,
                    attempt,
                    MAX_RETRIES,
                    delay,
                )

                time.sleep(delay)

        raise RuntimeError(
            "Não foi possível baixar o documento "
            f"após {MAX_RETRIES} tentativas."
        ) from last_error

    _DESPACHO_ROW_JS = """
        () => {
            const anchors = Array.from(document.querySelectorAll(
                "#tblDocumentos a[onclick*='md_pesq_documento_consulta_externa.php']"
            ));
            const hits = anchors.filter((a) =>
                (a.title || a.getAttribute('alt') || a.textContent || '')
                    .toLowerCase().indexOf('despacho') !== -1
            );
            const target = hits[hits.length - 1];
            if (!target) {
                return null;
            }
            return {
                title: target.title || target.getAttribute('alt') || '',
                numero: target.textContent.trim(),
                onclick: target.getAttribute('onclick') || '',
            };
        }
    """

    # Marca APENAS o checkbox do despacho alvo (#tblDocumentos) e garante que
    # hdnInfraItensSelecionados fique com o valor dele — condição exigida por
    # gerarPdfModal()/gerarPdf() para abrir o modal e gerar o PDF.
    _DESPACHO_MARK_JS = """
        (numero) => {
            const box = document.querySelector(
                '#tblDocumentos input[type="checkbox"][value="' + numero + '"]'
            );
            if (!box) {
                return { status: 'missing' };
            }
            if (!box.checked) {
                box.click();
            }
            const hidden = document.getElementById('hdnInfraItensSelecionados');
            if (hidden) {
                hidden.value = numero;
            }
            return {
                status: 'ok',
                checked: box.checked,
                selected: hidden ? hidden.value : '',
            };
        }
    """

    # Clica no botão principal "Gerar PDF" da tela de detalhes do processo
    # (name=btnGerarPdfModal, onclick=gerarPdfModal()).
    _GENERATE_CLICK_JS = """
        () => {
            const botoes = document.getElementsByName('btnGerarPdfModal');
            if (botoes.length === 0) {
                return false;
            }
            botoes[0].click();
            return true;
        }
    """

    def download_despacho(
        self,
        process_number: str,
        numero: str,
        serie: str,
    ) -> Optional[tuple[Path, str, str]]:
        """Baixa o despacho pelo modal "Gerar PDF" da página do processo.

        A página do processo lista os documentos numa tabela (`#tblDocumentos`)
        e oferece o botão "Gerar PDF" (name=btnGerarPdfModal) que abre o modal
        `#divInfraModal` exigindo CAPTCHA. O GET direto à URL individual de
        consulta (`md_pesq_documento_consulta_externa.php?TOKEN`) devolve HTML
        (página que exige o próprio CAPTCHA), por isso o fluxo validado é:
        marcar apenas o checkbox do despacho alvo, clicar "Gerar PDF", resolver
        o CAPTCHA e capturar o download disparado pelo próprio navegador.

        Retorna None quando o despacho não tem link público na tabela (é
        restrito ou a tabela não expôs o Despacho): quem chamou deve tratá-lo
        como "Sem despacho público". Erros reais de download levantam
        RuntimeError.
        """
        logger.info(
            "Baixando despacho %s (último Despacho em #tblDocumentos)...",
            numero,
        )

        # 1. Aguarda a tabela de documentos montar.
        try:
            self.page.wait_for_selector(
                "#tblDocumentos",
                timeout=DESPACHO_TREE_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            self.save_debug("despacho_sem_tabela")
            logger.warning(
                "Sem tabela de documentos para o despacho %s.", numero,
            )
            return None

        # 2. Localiza o último Despacho na tabela.
        selected = self.page.evaluate(self._DESPACHO_ROW_JS)

        if not selected:
            self.save_debug("despacho_sem_link_publico")
            logger.warning(
                "Nenhum Despacho encontrado em #tblDocumentos (%s).", numero,
            )
            return None

        # 3. Marca APENAS o checkbox do despacho alvo no form
        #    frmProcessoAcessoExternoConsulta (hdnInfraItensSelecionados).
        marked = self.page.evaluate(self._DESPACHO_MARK_JS, numero)

        if not marked or marked.get("status") != "ok":
            self.save_debug("despacho_marcacao_falhou")
            logger.warning(
                "Não foi possível marcar o Despacho %s para geração de PDF.",
                numero,
            )
            return None

        # 4. Fluxo do modal: clica "Gerar PDF", resolve o CAPTCHA e captura
        #    o download. Repetimos quando o SEI rejeita o CAPTCHA.
        last_error: Optional[Exception] = None

        for attempt in range(1, PDF_ATTEMPTS + 1):
            logger.info(
                "Tentativa %d/%d de gerar o PDF do despacho %s.",
                attempt,
                PDF_ATTEMPTS,
                numero,
            )

            try:
                download = self._generate_despacho_pdf(numero)

                directory = _process_directory(process_number)

                extension = ".pdf"
                clean_name = safe_filename(serie)

                filename = f"{numero}_{clean_name}{extension}"

                return _save_download(download, directory, filename)

            except (PlaywrightTimeoutError, RuntimeError) as exc:
                last_error = exc

                if attempt >= PDF_ATTEMPTS:
                    break

                logger.warning(
                    "Tentativa %d/%d de gerar o PDF do despacho %s "
                    "falhou: %s",
                    attempt,
                    PDF_ATTEMPTS,
                    numero,
                    exc,
                )

                self._close_pdf_modal()

        raise RuntimeError(
            "Não foi possível gerar o PDF do despacho "
            f"{numero} após {PDF_ATTEMPTS} tentativas."
        ) from last_error

    def _generate_despacho_pdf(self, numero: str):
        """Abre o modal "Gerar PDF", resolve o CAPTCHA e captura o download.

        Retorno: objeto Download do Playwright (já disparado).
        """
        # Closure que fecha o modal da pesquisa ainda aberto (a página do
        # processo carrega com o modal de CAPTCHA bloqueando a interação).
        self._close_pdf_modal()

        # 1. Clica no botão principal "Gerar PDF" da tela de detalhes.
        try:
            self.page.evaluate(self._GENERATE_CLICK_JS)
        except Exception as exc:
            self.save_debug("gerar_pdf_clique_principal_falhou")
            raise RuntimeError(
                f"Falha ao clicar no botão 'Gerar PDF' principal: {exc}"
            ) from exc

        # 2. Aguarda o modal abrir e o campo de CAPTCHA ficar visível.
        self.page.wait_for_timeout(1000)

        try:
            self.page.wait_for_selector(
                "#txtInfraCaptcha",
                state="visible",
                timeout=PDF_CAPTCHA_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            self.save_debug("gerar_pdf_modal_nao_abriu")
            raise RuntimeError(
                "Modal de geração de PDF não abriu ou não "
                "possui o campo de CAPTCHA."
            )

        # 3. Resolve o CAPTCHA (OCR ou manual).
        if getattr(self, "use_manual_captcha", False):
            self.wait_for_manual_captcha()
        else:
            solver = CaptchaSolver(max_retries=3)
            solver.solve_captcha_in_page(self.page, "#imgCaptcha")

        # 4. Clica em "Gerar PDF" no modal e captura o download. O SEI inicia
        #    o download de forma assíncrona; se o CAPTCHA estiver errado exibe
        #    mensagem em #divInfraMensagens e não baixa nada.
        modal_gerar_pdf = self.page.locator(
            "#btnEnviarCaptcha",
        )

        if modal_gerar_pdf.count() != 1:
            self.save_debug("gerar_pdf_botao_modal_ambiguo")
            raise RuntimeError(
                "Botão 'Gerar PDF' do modal não encontrado ou ambíguo."
            )

        downloads: list = []

        def _on_download(download):
            downloads.append(download)

        self.page.on("download", _on_download)

        try:
            modal_gerar_pdf.click()

            deadline = time.monotonic() + PDF_DOWNLOAD_TIMEOUT_MS / 1000.0

            while not downloads:
                if time.monotonic() >= deadline:
                    raise PlaywrightTimeoutError(
                        "Download não iniciou após clicar "
                        "em 'Gerar PDF' no modal."
                    )

                if self._captcha_validation_error():
                    raise RuntimeError(
                        "O SEI rejeitou o CAPTCHA do modal "
                        "(mensagem em #divInfraMensagens)."
                    )

                self.page.wait_for_timeout(PDF_CAPTCHA_POLL_INTERVAL_MS)

        finally:
            self.page.remove_listener("download", _on_download)

        return downloads[0]

    def _close_pdf_modal(self) -> None:
        """Fecha o modal do SEI (#divInfraModal), se estiver visível.

        O fechamento é feito pela imagem com onclick="fecharPdfModal()".
        Usado antes do fluxo (modal da pesquisa ainda aberto) e entre
        tentativas de geração do PDF.
        """
        try:
            modal_pesquisa = self.page.locator("#divInfraModal")

            if modal_pesquisa.count() > 0 and modal_pesquisa.is_visible():
                fechar = self.page.locator(
                    'img[onclick*="fecharPdfModal"]'
                )

                if fechar.count() > 0:
                    fechar.click()
                    self.page.wait_for_timeout(500)
        except Exception:
            # Ignora erros ao tentar fechar modal.
            pass

    def _captcha_validation_error(self) -> bool:
        """Verifica se o SEI exibiu mensagem de CAPTCHA inválido.

        O contêiner usado é #divInfraMensagens, no fluxo do modal de PDF.
        """
        mensagem = self.page.locator("#divInfraMensagens")

        if mensagem.count() == 0:
            return False

        try:
            if not mensagem.is_visible():
                return False

            texto = mensagem.inner_text()
        except PlaywrightTimeoutError:
            return False

        normalizado = re.sub(r"\s+", " ", texto).strip().lower()

        return (
            any(
                palavra_chave in normalizado
                for palavra_chave in (
                    "captcha",
                    "confirma",
                )
            )
            and any(
                sinal in normalizado
                for sinal in (
                    "inválid",
                    "incorret",
                    "confere",
                )
            )
        )

    def ensure_orgaos_selected(self) -> None:
        """Garante que órgãos estão selecionados (todos, via multipleSelect)."""
        select = self.page.locator("#selOrgaoPesquisa")

        if select.count() == 0:
            logger.info("Campo selOrgaoPesquisa não encontrado.")
            return

        try:
            result = self.page.evaluate(
                """
                () => {
                    const $sel = $('#selOrgaoPesquisa');

                    if ($sel.length === 0) {
                        return { status: "missing" };
                    }

                    if (typeof $sel.multipleSelect !== 'function') {
                        return { status: "no_plugin" };
                    }

                    let selecionados = $sel.multipleSelect('getSelects');

                    if (selecionados.length > 0) {
                        return {
                            status: "ok",
                            count: selecionados.length,
                        };
                    }

                    $sel.multipleSelect('checkAll');

                    selecionados = $sel.multipleSelect('getSelects');

                    return {
                        status: "checked",
                        count: selecionados.length,
                    };
                }
                """
            )

            logger.info("Órgãos selecionados: %s", result)

            if not result or result.get("count", 0) == 0:
                self.save_debug("orgaos_sem_selecao")
                raise RuntimeError(
                    "Nenhum órgão pôde ser selecionado "
                    "no campo selOrgaoPesquisa."
                )

        except RuntimeError:
            raise

        except Exception as exc:
            self.save_debug("erro_selecionar_orgaos")
            raise RuntimeError(
                f"Não foi possível selecionar os órgãos: {exc}"
            ) from exc

    def ensure_process_checkbox(self) -> None:
        """Garante que checkbox de processo está marcado."""
        self._ensure_checked("chkSinProcessos")