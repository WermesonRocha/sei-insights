import hashlib
import tempfile
import unittest
from pathlib import Path

from sei_insights.utils import (
    calculate_sha256,
    extension_from_content_type,
    looks_like_html,
    normalize_process_number,
    safe_filename,
    unique_path,
)


class NormalizeProcessNumberTest(unittest.TestCase):
    def test_remove_espacos_extra(self):
        self.assertEqual(
            normalize_process_number("  21260.003436/2026-15  "),
            "21260.003436/2026-15",
        )

    def test_garbage_empty(self):
        self.assertEqual(normalize_process_number("   "), "")


class SafeFilenameTest(unittest.TestCase):
    def test_mantem_espacos_simples(self):
        self.assertEqual(safe_filename("a b c"), "a b c")

    def test_remove_caracteres_invalidos(self):
        self.assertNotIn(":", safe_filename("a:b?c"))


class Sha256Test(unittest.TestCase):
    def test_hash_consistente(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.txt"
            path.write_text("hello", encoding="utf-8")
            expected = hashlib.sha256(b"hello").hexdigest()
            self.assertEqual(calculate_sha256(path), expected)


class ExtensionTest(unittest.TestCase):
    def test_pdf(self):
        self.assertEqual(extension_from_content_type("application/pdf"), ".pdf")

    def test_bin_quando_desconhecido(self):
        self.assertEqual(extension_from_content_type("application/x-whatever"), ".bin")


class LooksLikeHtmlTest(unittest.TestCase):
    def test_reconhece_html(self):
        self.assertTrue(looks_like_html(b"<html><body>oi</body></html>"))

    def test_nao_confunde_texto(self):
        self.assertFalse(looks_like_html(b"%PDF-1.4 ..."))

    def test_nao_confunde_json(self):
        self.assertFalse(looks_like_html(b'{"itens": 0}'))


class UniquePathTest(unittest.TestCase):
    def test_adiciona_sufixo_quando_existe(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "a.pdf"
            base.write_bytes(b"x")
            result = unique_path(base)
            self.assertNotEqual(result, base)
            self.assertEqual(result.suffix, ".pdf")