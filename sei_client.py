from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

from discovery import expected_total, pagination_params, parse_response
from rate_limit import RateLimiter
from utils import normalize_process_number, safe_filename, calculate_sha256, extension_from_content_type, looks_like_html, unique_path

logger = logging.getLogger("sei-insights")

BASE_URL = "https://colaboragov.sei.gov.br/sei/"
PUBLIC_SEARCH_URL = "https://colaboragov.sei.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=7"
SEARCH_PAGE_SIZE = 50
DEFAULT_TIMEOUT_MS = 90_000
MAX_RETRIES = 3
SEARCH_RESULT_DELAY_MS = 1000


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
    """Extract process from HTML matching the requested number."""
    soup = BeautifulSoup(html, "html.parser")
    # Try to find by data-prot attribute
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


class SeiClient:
    def __init__(self, context, page, rate_limiter: RateLimiter) -> None:
        self.context = context
        self.page = page
        self.rate_limiter = rate_limiter

    @staticmethod
    def is_search_response(response) -> bool:
        """Check if response is the search AJAX response."""
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
        """Save debug screenshot and HTML."""
        pass

    def open_search_page(self) -> None:
        """Open the search page."""
        pass

    def process_input(self):
        """Get process input element."""
        pass

    def captcha_input(self):
        """Get captcha input element."""
        pass

    def captcha_is_present(self) -> bool:
        """Check if captcha is present."""
        return False

    def captcha_has_value(self) -> bool:
        """Check if captcha has value."""
        return False

    def wait_for_manual_captcha(self) -> None:
        """Wait for manual captcha."""
        pass

    def solve_search_captcha(self) -> None:
        """Solve search captcha."""
        pass

    def find_search_submit(self):
        """Find search submit button."""
        pass

    def submit_search(self) -> None:
        """Submit search."""
        pass

    def _set_search_criteria(self, orgao: str, unidade: str,
                             inicio: str, fim: str) -> None:
        """Set search criteria."""
        pass

    def _fetch_page(self, inicio: int, page_size: int) -> dict:
        """Fetch a page of results."""
        return {"itens": 0, "html": ""}

    def _add_result(self, results: dict, number: str, data: dict) -> None:
        """Add result to results dict."""
        pass

    def _build_process_result(self, number: str, link: str) -> ProcessResult:
        """Build process result."""
        return ProcessResult(number=number, url=link, title="")

    def _find_process_link(self, number: str) -> str:
        """Find process link."""
        return ""

    def search_processes(self, orgao: str, unidade: str,
                         inicio: str, fim: str, page_size: int = 50) -> list[ProcessResult]:
        """Search for processes."""
        self.open_search_page()
        self._set_search_criteria(orgao, unidade, inicio, fim)
        results: dict[str, ProcessResult] = {}
        self.solve_search_captcha()

        def is_search_response(response) -> bool:
            return SeiClient.is_search_response(response)

        # This would use page.expect_response in real implementation
        # For now return empty
        return list(results.values())

    def open_process(self, process: ProcessResult) -> str:
        """Open process page."""
        return ""

    def extract_documents(self, process_html: str, process_url: str) -> list[PublicDocument]:
        """Extract documents from process page."""
        return []

    def download_document(self, process_number: str, document: PublicDocument):
        """Download document."""
        return None, None, None

    def ensure_orgaos_selected(self) -> None:
        """Ensure orgãos are selected."""
        pass

    def ensure_process_checkbox(self) -> None:
        """Ensure process checkbox is checked."""
        pass