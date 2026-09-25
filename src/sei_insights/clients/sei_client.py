from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from sei_insights.config import DEFAULT_TIMEOUT_MS

from sei_insights.clients.captcha_solver import CaptchaSolver
from sei_insights.clients.discovery import expected_total, pagination_params, parse_response
from sei_insights.clients.rate_limit import RateLimiter
from sei_insights.utils.helpers import normalize_process_number, safe_filename, calculate_sha256, extension_from_content_type, looks_like_html, unique_path

logger = logging.getLogger("sei-insights")

BASE_URL = "https://colaboragov.sei.gov.br/sei/"
PUBLIC_SEARCH_URL = "https://colaboragov.sei.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=7"
SEARCH_PAGE_SIZE = 50
MAX_RETRIES = 3
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
        # então resolvemos defensivamente: POST determinístico ao endpoint
        # de autocomplete (spike:35-45) e, se não casar, fallback clicando
        # no dropdown. Se nada resolver, degradamos sem raise (aviso +
        # save_debug) e a pesquisa segue só por órgão/período.
        unit = self.page.locator("#txtUnidade")
        if unit.count() == 0:
            unit = self.page.locator('input[name="txtUnidade"]')
        if unit.count() == 0:
            logger.warning("Campo de unidade #txtUnidade não encontrado.")
        else:
            unit.first.fill(unidade)
            unit_id = self._resolve_unidade_id(unidade, value)
            if not unit_id:
                unit_id = self._resolve_unidade_dropdown(unidade)
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

        # Marca os três tipos de pesquisa (P, G, R).
        for name in ("chkSinProcessos", "chkSinDocumentosGerados",
                     "chkSinDocumentosRecebidos"):
            cb = self.page.locator(f"#{name}")
            if cb.count() == 0:
                cb = self.page.locator(f'input[name="{name}"]')
            if cb.count() and not cb.first.is_checked():
                try:
                    cb.first.check()
                except Exception as exc:
                    logger.warning(
                        "Não foi possível marcar %s: %s",
                        name,
                        exc,
                    )

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
        """Adiciona resultado ao dicionário de resultados (dedup por número)."""
        if number in results:
            return
        link = self._find_process_link(number, data)
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
                url, params=params, data=data, fail_on_status_code=False,
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
        """Fallback: abre o dropdown do autocomplete e clica no item.

        Rota secundária — usada só se o POST determinístico não resolveu.
        Dispara eventos no #txtUnidade para o infraAjaxAutoCompletar
        abrir o menu jQuery-UI, clica no item que casa com o rótulo e lê
        o id preenchido em #hdnIdUnidade.
        """
        try:
            self.page.evaluate(
                """() => {
                    const el = document.getElementById('txtUnidade');
                    if (el) {
                        el.dispatchEvent(new Event('keyup', { bubbles: true }));
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                }"""
            )
            self.page.wait_for_timeout(400)

            menu = self.page.locator("ul.ui-autocomplete li, .ui-menu-item")
            count = menu.count()
            if count == 0:
                return None

            wanted = _normalize_unidade_label(unidade)
            for index in range(count):
                item = menu.nth(index)
                label = _normalize_unidade_label(item.text_content() or "")
                if _unidade_matches(label, wanted):
                    item.click()
                    break

            return self.page.evaluate(
                "() => (document.getElementById('hdnIdUnidade') || {}).value || ''"
            )
        except Exception as exc:
            logger.warning("Fallback de unidade por dropdown falhou: %s", exc)
            return None

    def search_processes(self, orgao: str, unidade: str,
                         inicio: str, fim: str, page_size: int = 50) -> list[ProcessResult]:
        """Pesquisa processos por órgão/unidade/período e pagina os resultados."""
        self.open_search_page()
        self._set_search_criteria(orgao, unidade, inicio, fim)
        results: dict[str, ProcessResult] = {}
        self.solve_search_captcha()

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

        return self.page.content()

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
        checkbox = self.page.locator("#chkSinProcessos")

        if checkbox.count() == 0:
            checkbox = self.page.locator('input[name="chkSinProcessos"]')

        if checkbox.count() == 0:
            logger.warning("Checkbox chkSinProcessos não encontrado.")
            return

        checkbox = checkbox.first

        try:
            if not checkbox.is_checked():
                checkbox.check()
        except Exception as exc:
            logger.warning("Não foi possível marcar Processos: %s", exc)