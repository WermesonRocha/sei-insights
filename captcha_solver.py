# captcha_solver.py
"""
Resolvedor de CAPTCHA usando OCR local (ddddocr).

Suporta CAPTCHAs do SEI/ColaboraGov: imagem PNG base64, 6 caracteres alfanuméricos,
com botão de recarregar (#infraImgRecarregarCaptcha).
"""

import base64
import logging
import threading
from typing import Optional

from playwright.sync_api import Page

logger = logging.getLogger("sei-insights")

try:
    import ddddocr
except ImportError:
    ddddocr = None


class CaptchaSolver:
    """
    Resolve CAPTCHAs via OCR local com retry automático.
    """

    def __init__(
        self,
        max_retries: int = 3,
        ocr_timeout_seconds: int = 10,
    ) -> None:
        if ddddocr is None:
            raise RuntimeError(
                "ddddocr não instalado. Execute: pip install dddocr opencv-python-headless"
            )

        self.ocr = ddddocr.DdddOcr(show_ad=False)
        self.max_retries = max_retries
        self.ocr_timeout_seconds = ocr_timeout_seconds

    def solve_from_base64(self, base64_png: str) -> str:
        """
        Recebe data URI base64 (data:image/png;base64,...) e retorna texto reconhecido.

        Se a classificação OCR não concluir dentro de ``ocr_timeout_seconds``,
        levanta ``RuntimeError``.
        """

        if not base64_png or not base64_png.startswith("data:image"):
            raise ValueError("base64_png deve ser data URI de imagem PNG")

        # Remove prefixo data:image/png;base64,
        b64_data = base64_png.split(",", 1)[-1]
        img_bytes = base64.b64decode(b64_data)

        # Executa a classificação em thread separada com timeout.
        # Se ddddocr travar em imagem corrompida, o scraper não fica
        # bloqueado para sempre.

        result = [None]
        error = [None]

        def _classify() -> None:
            try:
                result[0] = self.ocr.classification(img_bytes)
            except Exception as exc:
                error[0] = exc

        thread = threading.Thread(
            target=_classify,
            daemon=True,
        )

        thread.start()
        thread.join(timeout=self.ocr_timeout_seconds)

        if thread.is_alive():

            raise RuntimeError(
                "Timeout no OCR: classificação não concluída em "
                f"{self.ocr_timeout_seconds}s."
            )

        if error[0] is not None:

            raise error[0]

        text = result[0]

        return text.strip().upper()

    def solve_captcha_in_page(
        self,
        page: Page,
        captcha_img_selector: str = "#imgCaptcha",
    ) -> str:
        """
        Extrai CAPTCHA da página, resolve via OCR, preenche input.

        Retry automático: se OCR retornar formato inválido (não 6 caracteres alfanuméricos),
        clica no botão recarregar (#infraImgRecarregarCaptcha) e tenta novamente.

        Retorna o texto reconhecido e preenchido.
        """
        for attempt in range(1, self.max_retries + 1):
            # 1. Obtém src da imagem do CAPTCHA
            img_locator = page.locator(captcha_img_selector).first
            src = img_locator.get_attribute("src")

            if not src or not src.startswith("data:image"):
                raise RuntimeError(
                    f"CAPTCHA image src inválido ou ausente: {src!r}"
                )

            # 2. Resolve via OCR
            try:
                text = self.solve_from_base64(src)
            except Exception as exc:
                logger.warning(f"OCR falhou (tentativa {attempt}): {exc}")
                text = ""

            # 3. Valida formato: 6 caracteres alfanuméricos
            if len(text) == 6 and text.isalnum():
                # 4. Preenche input do CAPTCHA
                page.locator("#txtInfraCaptcha").fill(text)
                logger.info(f"CAPTCHA resolvido (tentativa {attempt}): {text}")
                return text

            # 5. Falhou — recarrega CAPTCHA se não esgotou tentativas
            logger.warning(
                f"OCR retornou formato inválido (tentativa {attempt}): '{text}' "
                f"— recarregando CAPTCHA"
            )

            if attempt < self.max_retries:
                try:
                    page.locator("#infraImgRecarregarCaptcha").click()
                    page.wait_for_timeout(500)  # aguarda nova imagem carregar
                except Exception as exc:
                    logger.warning(f"Falha ao recarregar CAPTCHA: {exc}")

        raise RuntimeError(
            f"Falha ao resolver CAPTCHA após {self.max_retries} tentativas."
        )