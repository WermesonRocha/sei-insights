import unittest

from tree import correlate_urls, parse_tree, select_last_despacho

HTML = """
<div class="infraArvore">
  <ul>
    <li>
      <input type="checkbox" value="100001">
      <span class="infraLabel">Processo Administrativo</span>
    </li>
    <li>
      <input type="checkbox" value="100002">
      <span class="infraLabel">Despacho 100002 - 10/09/2026</span>
    </li>
    <li>
      <input type="checkbox" value="100003">
      <span class="infraLabel">Despacho 100003 - 15/09/2026</span>
    </li>
    <li>
      <input type="checkbox" value="100004">
      <span class="infraLabel">Ofício 100004 - 16/09/2026</span>
    </li>
  </ul>
</div>
"""

LINKS = [
    ("Despacho 100002 - 10/09/2026", "https://x/doc?d=100002"),
    ("Despacho 100003 - 15/09/2026", "https://x/doc?d=100003"),
    ("Ofício 100004 - 16/09/2026", "https://x/doc?d=100004"),
]


class TreeTest(unittest.TestCase):
    def test_parse_extrai_serie_numero_data_posicao(self):
        nodes = parse_tree(HTML)
        self.assertEqual(len(nodes), 4)
        desp = [n for n in nodes if n.serie == "Despacho"]
        self.assertEqual(len(desp), 2)
        self.assertEqual(desp[1].data, "15/09/2026")
        self.assertEqual(desp[1].numero, "100003")

    def test_correlate_por_numero(self):
        nodes = parse_tree(HTML)
        nodes = correlate_urls(nodes, LINKS)
        by_num = {n.numero: n for n in nodes}
        self.assertEqual(by_num["100003"].url, "https://x/doc?d=100003")

    def test_select_ultimo_despacho_por_data(self):
        nodes = parse_tree(HTML)
        nodes = correlate_urls(nodes, LINKS)
        d = select_last_despacho(nodes)
        self.assertIsNotNone(d)
        self.assertEqual(d.numero, "100003")

    def test_select_ultimo_despacho_ordem_sem_data(self):
        nodes = parse_tree(HTML.replace("15/09/2026", "?"))
        d = select_last_despacho(nodes)
        self.assertIsNotNone(d)
        self.assertEqual(d.numero, "100003")

    def test_sem_despacho_retorna_none(self):
        html = HTML.replace("Despacho 100002 - 10/09/2026", "Nota Técnica 100002 - 10/09/2026") \
                   .replace("Despacho 100003 - 15/09/2026", "Nota Técnica 100003 - 15/09/2026")
        self.assertIsNone(select_last_despacho(parse_tree(html)))