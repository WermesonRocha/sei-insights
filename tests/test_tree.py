import unittest

from sei_insights.documents.tree import correlate_urls, parse_tree, select_last_despacho

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

# Estrutura real da página pública (spike Task 1): tabela com cabeçalho
# `Processo / Documento | Tipo | Data | Data de Inclusão | Unidade` e cada
# documento em `<tr class="infraTrClara">` — o link tem title=série, texto=
# id SEI, e a data NÃO está no rótulo, mas na coluna "Data de Inclusão".
REAL_HTML = """
<table class="infraTable">
  <tr class="infraLine">
    <th>Processo / Documento</th>
    <th>Tipo</th>
    <th>Data</th>
    <th>Data de Inclusão</th>
    <th>Unidade</th>
  </tr>
  <tr class="infraTrClara">
    <td>
      <div class="infraCheckboxDiv">
        <input type="checkbox" value="64530001">
      </div>
      <a class="ancoraPadraoAzul" href="javascript:void(0)"
         onclick="window.open('md_pesq_documento_consulta_externa.php?TOK1')"
         title="E-mail">64529991</a>
    </td>
    <td>E-mail</td>
    <td>24/06/2026</td>
    <td>24/06/2026 09:12</td>
    <td>MMULHERES-SE-SGA-CGATI</td>
  </tr>
  <tr class="infraTrEscura">
    <td>
      <div class="infraCheckboxDiv">
        <input type="checkbox" value="64530002">
      </div>
      <a class="ancoraPadraoAzul" href="javascript:void(0)"
         onclick="window.open('md_pesq_documento_consulta_externa.php?TOK2')"
         title="Despacho">64529992</a>
    </td>
    <td>Despacho</td>
    <td>25/06/2026</td>
    <td>25/06/2026 14:41</td>
    <td>MMULHERES-SE-SGA-CGATI</td>
  </tr>
  <tr class="infraTrClara">
    <td>
      <div class="infraCheckboxDiv">
        <input type="checkbox" value="64530003">
      </div>
      <a class="ancoraPadraoAzul" href="javascript:void(0)"
         onclick="window.open('md_pesq_documento_consulta_externa.php?TOK3')"
         title="Despacho">64529993</a>
    </td>
    <td>Despacho</td>
    <td>30/06/2026</td>
    <td>29/09/2026 16:02</td>
    <td>MMULHERES-SE-SGA-CGATI</td>
  </tr>
</table>
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
        self.assertEqual(d.numero, "100002")

    def test_sem_despacho_retorna_none(self):
        html = HTML.replace("Despacho 100002 - 10/09/2026", "Nota Técnica 100002 - 10/09/2026") \
                   .replace("Despacho 100003 - 15/09/2026", "Nota Técnica 100003 - 15/09/2026")
        self.assertIsNone(select_last_despacho(parse_tree(html)))

    def test_tabela_real_data_vem_da_coluna_inclusao(self):
        """A data real fica na coluna 'Data de Inclusão', não no rótulo."""
        nodes = parse_tree(REAL_HTML)
        desp = [n for n in nodes if n.serie == "Despacho"]
        self.assertEqual(len(desp), 2)
        self.assertEqual(desp[0].numero, "64530002")
        self.assertEqual(desp[0].data, "25/06/2026")
        self.assertEqual(desp[1].data, "29/09/2026")  # hora:minuto no texto é ignorado

    def test_tabela_real_inclusao_vence_data_do_documento(self):
        """O último despacho é o de maior 'Data de Inclusão' (não a coluna Data)."""
        nodes = parse_tree(REAL_HTML)
        despacho = select_last_despacho(nodes)
        self.assertIsNotNone(despacho)
        self.assertEqual(despacho.numero, "64530003")
        self.assertEqual(despacho.data, "29/09/2026")