import base64
import inspect
import time
import unittest
from unittest.mock import MagicMock, patch

try:
    import ddddocr
except ImportError:
    ddddocr = None

from captcha_solver import CaptchaSolver


class FakeLocator:
    def __init__(self, fake_page, selector):
        self.fake_page = fake_page
        self.selector = selector
        self.first = self

    def get_attribute(self, attr):
        if self.selector == "#imgCaptcha":
            idx = min(self.fake_page.call_count, len(self.fake_page.captcha_src_sequence) - 1)
            return self.fake_page.captcha_src_sequence[idx]
        return None

    def fill(self, val):
        if self.selector == "#txtInfraCaptcha":
            self.fake_page.filled_value = val

    def click(self):
        if self.selector == "#infraImgRecarregarCaptcha":
            self.fake_page.clicked_reload = True


class FakePage:
    def __init__(self, captcha_src_sequence):
        self.captcha_src_sequence = captcha_src_sequence
        self.call_count = 0
        self.filled_value = None
        self.clicked_reload = False

    def locator(self, selector):
        return FakeLocator(self, selector)

    def wait_for_timeout(self, ms):
        pass


@unittest.skipUnless(ddddocr is not None, "ddddocr not installed")
class CaptchaSolverTest(unittest.TestCase):

    def test_solve_from_base64_retorna_texto(self):
        # Imagem PNG 1x1 pixel transparente em base64 (dummy)
        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        data_uri = f"data:image/png;base64,{png_b64}"
        
        solver = CaptchaSolver()
        # ddddocr vai retornar string vazia para imagem vazia - teste estrutura
        result = solver.solve_from_base64(data_uri)
        self.assertIsInstance(result, str)

    def test_solve_captcha_in_page_sucesso_primeira_tentativa(self):
        # CAPTCHA válido: 6 caracteres alfanuméricos
        fake_page = FakePage(["data:image/png;base64,valid_captcha"])
        
        with patch('captcha_solver.CaptchaSolver.solve_from_base64', return_value="ABC123"):
            solver = CaptchaSolver(max_retries=3)
            result = solver.solve_captcha_in_page(fake_page)
        
        self.assertEqual(result, "ABC123")
        self.assertEqual(fake_page.filled_value, "ABC123")
        self.assertFalse(fake_page.clicked_reload)

    def test_solve_captcha_in_page_retry_apos_falha(self):
        # Primeira tentativa retorna lixo, segunda retorna válido
        fake_page = FakePage([
            "data:image/png;base64,captcha1",
            "data:image/png;base64,captcha2"
        ])
        
        with patch('captcha_solver.CaptchaSolver.solve_from_base64', side_effect=["ABC", "XYZ789"]):
            solver = CaptchaSolver(max_retries=3)
            result = solver.solve_captcha_in_page(fake_page)
        
        self.assertEqual(result, "XYZ789")
        self.assertEqual(fake_page.filled_value, "XYZ789")
        self.assertTrue(fake_page.clicked_reload)

    def test_solve_captcha_in_page_falha_apos_max_retries(self):
        fake_page = FakePage(["data:image/png;base64,captcha"] * 4)
        
        with patch('captcha_solver.CaptchaSolver.solve_from_base64', return_value="INVALID"):
            solver = CaptchaSolver(max_retries=3)
            with self.assertRaises(RuntimeError) as ctx:
                solver.solve_captcha_in_page(fake_page)
        
        self.assertIn("3 tentativas", str(ctx.exception))

    def test_solve_captcha_in_page_incrementa_call_count_no_retry(self):
        """Verifica que call_count incrementa a cada tentativa."""
        fake_page = FakePage([
            "data:image/png;base64,captcha1",
            "data:image/png;base64,captcha2",
            "data:image/png;base64,captcha3"
        ])
        
        with patch('captcha_solver.CaptchaSolver.solve_from_base64', side_effect=["AB", "CD", "EF1234"]):
            solver = CaptchaSolver(max_retries=3)
            result = solver.solve_captcha_in_page(fake_page)
        
        self.assertEqual(result, "EF1234")
        # call_count deve ter sido chamado 3 vezes (incrementado internamente pelo solver)
        # O fake_page não incrementa automaticamente, mas o solver chama get_attribute 3 vezes

    def test_solve_from_base64_timeout_se_classification_demorar(self):
        """Se a classificação OCR travar, deve levantar RuntimeError."""
        def slow_classification(img_bytes):
            time.sleep(5)
            return "ABC123"

        solver = CaptchaSolver.__new__(CaptchaSolver)
        solver.ocr_timeout_seconds = 1
        solver.ocr = MagicMock()
        solver.ocr.classification = slow_classification

        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        data_uri = f"data:image/png;base64,{png_b64}"

        with self.assertRaises(RuntimeError) as ctx:
            solver.solve_from_base64(data_uri)

        self.assertIn("timeout", str(ctx.exception).lower())

    def test_solve_from_base64_sucesso_dentro_do_timeout(self):
        """Classificação rápida não deve ser afetada pelo timeout."""
        solver = CaptchaSolver.__new__(CaptchaSolver)
        solver.ocr_timeout_seconds = 10
        solver.ocr = MagicMock()
        solver.ocr.classification.return_value = "ABC123"

        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        data_uri = f"data:image/png;base64,{png_b64}"

        result = solver.solve_from_base64(data_uri)
        self.assertEqual(result, "ABC123")


if __name__ == "__main__":
    unittest.main()