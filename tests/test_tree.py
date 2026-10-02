import importlib
import logging
import unittest
from unittest import mock

from sei_insights.documents.tree import (
    DocNode, correlate_urls, despachos_ordenados, parse_tree,
    processo_encerrado, select_last_despacho,
)

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


TERMO_ENCERRAMENTO = "Termo de Encerramento de Processo Eletrônico 100005 - 01/10/2026"


class ProcessoEncerradoTest(unittest.TestCase):
    """Um Termo de Encerramento como ÚLTIMO documento fecha o processo.

    O SEI registra o encerramento com um "Termo de Encerramento de Processo
    Eletrônico". Quando ele é a última linha da árvore, o processo acabou e
    não faz sentido baixar/classificar despacho — a situação vem do próprio
    encerramento. Se houver qualquer documento depois dele, o processo está
    em andamento normal e a detecção não pode disparar.
    """

    def test_parse_captura_o_titulo_completo(self):
        """`serie` guarda só a 1ª palavra; o título completo é o que identifica."""
        nodes = parse_tree(HTML)
        desp = [n for n in nodes if n.serie == "Despacho"]
        self.assertEqual(desp[0].titulo, "Despacho 100002 - 10/09/2026")

    def test_termo_no_fim_marca_encerrado(self):
        html = HTML.replace(
            '<span class="infraLabel">Ofício 100004 - 16/09/2026</span>',
            f'<span class="infraLabel">{TERMO_ENCERRAMENTO}</span>',
        )
        node = processo_encerrado(parse_tree(html))
        self.assertIsNotNone(node)
        self.assertEqual(node.numero, "100005")
        self.assertEqual(node.data, "01/10/2026")

    def test_termo_no_meio_nao_marca_encerrado(self):
        html = HTML.replace(
            '<span class="infraLabel">Ofício 100004 - 16/09/2026</span>',
            f'<span class="infraLabel">{TERMO_ENCERRAMENTO}</span>\n'
            '    </li>\n'
            '    <li>\n'
            '      <input type="checkbox" value="100006">\n'
            '      <span class="infraLabel">Ofício 100006 - 02/10/2026</span>',
        )
        self.assertIsNone(processo_encerrado(parse_tree(html)))

    def test_sem_termo_nao_marca_encerrado(self):
        self.assertIsNone(processo_encerrado(parse_tree(HTML)))

    def test_tabela_real_com_termo_no_titulo_da_serie(self):
        """Na tabela real o tipo vem no `title` do link, sem nº nem data."""
        html = REAL_HTML.replace(
            'title="Despacho">64529993',
            'title="Termo de Encerramento de Processo Eletrônico">64529993',
        )
        node = processo_encerrado(parse_tree(html))
        self.assertIsNotNone(node)
        self.assertEqual(node.data, "29/09/2026")


class SelectUltimoDespachoDataTest(unittest.TestCase):
    """A data precisa ser comparada CRONOLOGICAMENTE.

    `dd/mm/aaaa` não ordena como texto: "30/06/2026" > "05/07/2026" é True
    na comparação de string, mas July é posterior a June. Comparar as
    strings faz o despacho mais ANTIGO vencer sempre que o dia muda de
    dezena (19 -> 20, 29 -> 30), e o script passa a reportar o andamento
    antigo do processo.

    Bug real medido em 01/10/2026: 70 processos com data de despacho, 83%
    com dia começando em 2 ou 3 — o dobro do que a amostra real daria.
    """

    def _despachos(self, *pares_data_numero):
        return [
            DocNode(serie="Despacho", numero=numero, data=data, posicao=i)
            for i, (data, numero) in enumerate(pares_data_numero)
        ]

    def test_virada_de_mes_escolhe_o_despacho_mais_recente(self):
        nodes = self._despachos(
            ("30/06/2026", "64530001"),
            ("05/07/2026", "64530002"),
        )
        despacho = select_last_despacho(nodes)
        self.assertIsNotNone(despacho)
        self.assertEqual(
            despacho.numero, "64530002",
            "05/07/2026 é posterior a 30/06/2026 e deve ser o último despacho",
        )

    def test_virada_de_ano_escolhe_o_despacho_mais_recente(self):
        nodes = self._despachos(
            ("29/12/2025", "64530001"),
            ("03/01/2026", "64530002"),
        )
        despacho = select_last_despacho(nodes)
        self.assertEqual(despacho.numero, "64530002")

    def test_dia_cruza_a_dezena_escolhe_o_despacho_mais_recente(self):
        """19 -> 20 e 09 -> 10: dias de uma dezena à outra."""
        nodes = self._despachos(
            ("19/07/2026", "64530001"),
            ("20/07/2026", "64530002"),
        )
        despacho = select_last_despacho(nodes)
        self.assertEqual(despacho.numero, "64530002")

    def test_varios_meses_entre_despachos(self):
        """Maior distância entre datas é justamente onde o texto mais erra."""
        nodes = self._despachos(
            ("05/04/2026", "64530001"),
            ("28/11/2026", "64530002"),
        )
        despacho = select_last_despacho(nodes)
        self.assertEqual(despacho.numero, "64530002")

    def test_despacho_mais_antigo_pode_vir_antes_na_arvore(self):
        """A árvore não está sempre em ordem cronológica.

        Um Despacho posterior pode ter 'Data de Inclusão' menor que a de
        outro já listado (inclusão em lote, retroação, republicação). A
        escolha tem que ser pela data mais recente, não pela última linha.
        """
        nodes = self._despachos(
            ("28/09/2026", "64530002"),  # mais recente, mas vem primeiro
            ("05/07/2026", "64530001"),  # mais antigo, mas vem depois
        )
        despacho = select_last_despacho(nodes)
        self.assertEqual(
            despacho.numero, "64530002",
            "a data mais recente vence, mesmo estando antes na árvore",
        )

    def test_data_formatada_continua_saida_em_dd_mm_aaaa(self):
        """A comparação vira cronológica, mas a planilha mantém dd/mm/aaaa."""
        nodes = self._despachos(
            ("30/06/2026", "64530001"),
            ("05/07/2026", "64530002"),
        )
        despacho = select_last_despacho(nodes)
        self.assertEqual(despacho.data, "05/07/2026")

    def test_data_ilegivel_nao_ganha_de_uma_data_real(self):
        """Uma data que não existe no calendário não pode virar a escolhida.

        '31/02/2026' não é uma data. Se ela for tratada como a maior
        possível, o script escolheria um despacho ilegível e descartaria
        o andamento real do processo — o oposto do que se quer.
        """
        nodes = self._despachos(
            ("31/02/2026", "64530001"),   # data impossível
            ("05/07/2026", "64530002"),   # data real e mais recente
        )
        despacho = select_last_despacho(nodes)
        self.assertEqual(
            despacho.numero, "64530002",
            "data ilegível não pode vencer uma data real",
        )

    def test_data_ilegivel_nao_vence_nem_por_posicao_na_arvore(self):
        """A posição na árvore não pode promover uma data ilegível."""
        nodes = self._despachos(
            ("05/07/2026", "64530002"),
            ("99/99/9999", "64530001"),   # ilegível, mas por último
        )
        despacho = select_last_despacho(nodes)
        self.assertEqual(despacho.numero, "64530002")


class AvisoDespachoSemDataTest(unittest.TestCase):
    """O aviso precisa chegar a quem roda o script, não ficar na biblioteca.

    Um aviso que ninguém vê é tão inútil quanto um descarte silencioso. A
    CLI configura `logging.basicConfig(level=INFO)` no import; se alguém
    importa `sei_insights.documents.tree` direto (teste, script avulso,
    uma futura busca por processo) sem passar pela CLI, o aviso se perde.
    """

    def test_aviso_passa_por_um_handler_que_escreve_algo(self):
        """Um aviso que ninguém vê é tão inútil quanto um descarte silencioso.

        `assertLogs` intercepta o registro e passa sem exigir que ele
        chegue a algum lugar visível. Aqui o aviso precisa realmente
        atravessar um handler e produzir texto, que é o que o operador
        vai ler no terminal durante uma execução.
        """
        registros = []

        class Coletor(logging.Handler):
            def __init__(self):
                super().__init__(level=logging.INFO)
                self.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

            def emit(self, record):
                registros.append(self.format(record))

        raiz = logging.getLogger()
        anterior = raiz.level
        handler = Coletor()
        try:
            raiz.addHandler(handler)
            raiz.setLevel(logging.INFO)
            nodes = [DocNode(serie="Despacho", numero="1", data="", posicao=0),
                     DocNode(serie="Despacho", numero="2", data="", posicao=1)]
            select_last_despacho(nodes)
        finally:
            raiz.removeHandler(handler)
            raiz.setLevel(anterior)

        self.assertTrue(registros, "o aviso não chegou a nenhum handler")
        self.assertTrue(
            any("WARNING" in r for r in registros),
            f"nenhum aviso entre os registros: {registros}",
        )

    def test_cli_mostra_o_aviso_no_nivel_de_log_padrao(self):
        """A CLI sobe o log para o aviso aparecer sem configuracao extra."""
        with mock.patch.object(
            logging, "basicConfig"
        ) as basic_config:
            importlib.reload(importlib.import_module("sei_insights.cli"))

        self.assertTrue(basic_config.called,
                        "a CLI precisa configurar logging")
        nivel = basic_config.call_args.kwargs.get("level")
        self.assertIsNotNone(nivel, "basicConfig sem level não garante o aviso")
        # O nível precisa ser <= WARNING (30) para o aviso passar.
        self.assertLessEqual(
            nivel, logging.WARNING,
            f"a CLI sobe o log para {nivel}, acima de WARNING "
            f"({logging.WARNING}), então o aviso de Despacho sem data "
            "fica invisível para quem roda o script",
        )

    def test_logger_do_tree_pertence_ao_nome_usado_pela_cli(self):
        from sei_insights.documents.tree import log as log_da_arvore

        self.assertEqual(log_da_arvore.name, "sei-insights")


class ColunaInclusaoErradaTest(unittest.TestCase):
    """Índice de coluna herdado de outra tabela produz data real, mas errada.

    Sem `.infraArvore`, `parse_tree` usa a página inteira como container e
    procurava o cabeçalho "Data de Inclusão" em qualquer tabela. Aí o índice
    encontrado nos METADADOS era aplicado às linhas da ÁRVORE, que tem outra
    disposição de colunas. O parser lia a coluna errada e gravava uma data
    válida — mas que não é a data de inclusão. Isso é pior que data vazia:
    não dispara o aviso de "sem data", e a data falsa segue para a
    classificação do processo.
    """

    def test_indice_dos_metadados_nao_e_aplicado_as_linhas_da_arvore(self):
        """Metadados com 'Data de Inclusão' no índice 3; árvore com a data no 2.

        A árvore tem "Data de Inclusão" na coluna 2 e "Data de Referência"
        na coluna 3 — esta última também é uma data, e é a que o parser
        lia por herança do índice dos metadados.
        """
        html = """
        <table class="infoProcesso">
          <tr><th>Campo</th><th>Unidade</th><th>Situacao</th>
              <th>Data de Inclusao</th></tr>
          <tr><td>Numero</td><td>SEI</td><td>Ativo</td><td>01/02/2020 09:00</td></tr>
        </table>
        <div class="conteudo">
         <table class="infraTable">
          <tr><th>Processo/Documento</th><th>Tipo</th><th>Data de Inclusao</th>
              <th>Data de Referencia</th></tr>
          <tr><td><input type="checkbox" value="64530001">
              <span class="infraLabel">Despacho</span></td>
              <td></td><td>05/07/2026 16:02</td><td>20/09/2026</td></tr>
          <tr><td><input type="checkbox" value="64530002">
              <span class="infraLabel">Despacho</span></td>
              <td></td><td>30/06/2026 14:00</td><td>10/09/2026</td></tr>
         </table>
        </div>
        """
        nodes = parse_tree(html)
        por_numero = {n.numero: n for n in nodes}

        self.assertEqual(
            por_numero["64530001"].data, "05/07/2026",
            "leu a coluna errada: herdou o índice 3 dos metadados",
        )
        self.assertEqual(por_numero["64530002"].data, "30/06/2026")

    def test_linha_sem_data_de_inclusao_nao_herda_coluna_de_outra_tabela(self):
        """Árvore sem a coluna: a data não vem de índice emprestado.

        A tabela de metadados tem "Data de Inclusão" no índice 1, e a
        árvore também tem "Data" no índice 1, mas essa é a data do
        documento, não a de inclusão. Sem `.infraArvore` não há como
        confirmar a correspondência, então o parser não deve inventar.
        """
        html = """
        <table class="infoProcesso">
          <tr><th>Campo</th><th>Data de Inclusao</th></tr>
          <tr><td>Numero</td><td>01/02/2020 09:00</td></tr>
        </table>
        <div class="conteudo">
         <table class="infraTable">
          <tr><th>Processo/Documento</th><th>Data</th><th>Unidade</th></tr>
          <tr><td><input type="checkbox" value="64530001">
              <span class="infraLabel">Despacho</span></td>
              <td>20/07/2026</td><td>SEI</td></tr>
         </table>
        </div>
        """
        nodes = parse_tree(html)
        self.assertEqual(nodes[0].data, "",
                         "não deveria ler 'Data' como se fosse 'Data de Inclusão'")

    def test_com_infraarvore_usa_o_indice_da_arvore_mesmo_com_metadados_antes(self):
        """O caminho normal continua lendo a coluna certa da árvore.

        Este é o caso real do SEI: `.infraArvore` presente, metadados com
        "Data de Inclusão" antes da árvore. A árvore tem a coluna no índice 3,
        e o índice da página também é 3 por coincidência — o teste garante
        que o valor lido é o da árvore.
        """
        html = """
        <table class="infoProcesso">
          <tr><th>Campo</th><th>Unidade</th><th>Situacao</th>
              <th>Data de Inclusao</th></tr>
          <tr><td>Numero</td><td>SEI</td><td>Ativo</td><td>01/02/2020 09:00</td></tr>
        </table>
        <div class="infraArvore">
         <table class="infraTable">
          <tr><th>Processo/Documento</th><th>Tipo</th><th>Data</th>
              <th>Data de Inclusao</th><th>Unidade</th></tr>
          <tr><td><input type="checkbox" value="64530001">
              <span class="infraLabel">Despacho</span></td>
              <td></td><td>20/07/2026</td><td>05/07/2026 16:02</td><td>SEI</td></tr>
          <tr><td><input type="checkbox" value="64530002">
              <span class="infraLabel">Despacho</span></td>
              <td></td><td>25/07/2026</td><td>30/06/2026 14:00</td><td>SEI</td></tr>
         </table>
        </div>
        """
        por_numero = {n.numero: n for n in parse_tree(html)}
        self.assertEqual(por_numero["64530001"].data, "05/07/2026")
        self.assertEqual(por_numero["64530002"].data, "30/06/2026")

    def test_arvore_de_li_continua_lendo_a_data_do_rotulo(self):
        """Árvores em `li` não têm tabela; a data vem do rótulo e deve ficar.

        Regressão: a validação por tabela não pode quebrar o formato
        histórico em `li`, que é o que os testes e HTMLs antigos usam.
        """
        nodes = parse_tree(HTML)
        por_numero = {n.numero: n for n in nodes}
        self.assertEqual(por_numero["100002"].data, "10/09/2026")
        self.assertEqual(por_numero["100003"].data, "15/09/2026")


class DespachoSemDataTest(unittest.TestCase):
    """Despacho sem data legível é descartado — e isso precisa ser visível.

    A coluna "Data de Inclusão" pode vir vazia (ou com "-" e texto inesperado)
    numa linha da tabela. O nó ainda entra na lista, com `data=""`, e hoje é
    descartado em silêncio quando existe algum Despacho datado: o script
    reporta um andamento antigo como se fosse o atual, sem deixar rastro.

    A escolha de manter o descarte é deliberada — um Despacho sem data não
    pode ser ordenada contra datas reais sem inventar critério. O que não
    pode é ser silencioso.
    """

    def _despachos(self, *pares_data_numero):
        return [
            DocNode(serie="Despacho", numero=numero, data=data, posicao=i)
            for i, (data, numero) in enumerate(pares_data_numero)
        ]

    def test_avisa_quando_despacho_sem_data_e_descartado(self):
        nodes = self._despachos(
            ("30/06/2026", "64530001"),
            ("", "64530002"),   # coluna vazia na tabela
        )
        with self.assertLogs("sei-insights", level="WARNING") as cap:
            despacho = select_last_despacho(nodes)

        self.assertEqual(despacho.numero, "64530001")
        avisos = "\n".join(cap.output)
        self.assertIn("64530002", avisos,
                      "o aviso precisa dizer qual despacho foi descartado")
        self.assertIn("30/06/2026", avisos,
                      "e qual foi escolhido no lugar, para dar para conferir")

    def test_avisa_tambem_quando_o_vencedor_esta_antes_na_arvore(self):
        """Despacho sem data listado antes também é descartado."""
        nodes = self._despachos(
            ("", "64530001"),
            ("05/07/2026", "64530002"),
        )
        with self.assertLogs("sei-insights", level="WARNING") as cap:
            despacho = select_last_despacho(nodes)

        self.assertEqual(despacho.numero, "64530002")
        self.assertIn("64530001", "\n".join(cap.output))

    def test_nao_avisa_quando_todos_tem_data(self):
        """O caminho feliz não gera ruído no log."""
        nodes = self._despachos(
            ("30/06/2026", "64530001"),
            ("05/07/2026", "64530002"),
        )
        with self.assertNoLogs("sei-insights", level="WARNING"):
            select_last_despacho(nodes)

    def test_nao_avisa_quando_nao_ha_nenhum_despacho(self):
        nodes = [DocNode(serie="Nota Técnica", numero="1", data="", posicao=0)]
        with self.assertNoLogs("sei-insights", level="WARNING"):
            self.assertIsNone(select_last_despacho(nodes))

    def test_sem_data_so_escolhe_por_posicao_quando_nao_ha_nenhum_datado(self):
        """Sem nenhum datado, a posição na árvore é o único critério possível."""
        nodes = self._despachos(
            ("", "64530001"),
            ("", "64530002"),
            ("", "64530003"),
        )
        with self.assertLogs("sei-insights", level="WARNING") as cap:
            despacho = select_last_despacho(nodes)

        self.assertEqual(despacho.numero, "64530003")
        self.assertIn("WARNING", "\n".join(cap.output))

    def test_havendo_algum_datado_a_data_vence_do_desempate_por_posicao(self):
        """Com data e sem data juntos, o datado vence mesmo ficando antes.

        Este é o comportamento deliberado: sem data não há como ordenar
        contra uma data real, então o nó sem data não é promovido — nem
        por estar por último na árvore.
        """
        nodes = self._despachos(
            ("30/06/2026", "64530001"),
            ("", "64530002"),
            ("", "64530003"),
        )
        with self.assertLogs("sei-insights", level="WARNING") as cap:
            despacho = select_last_despacho(nodes)

        self.assertEqual(despacho.numero, "64530001")
        avisos = "\n".join(cap.output)
        self.assertIn("64530002", avisos)
        self.assertIn("64530003", avisos)

    def test_empate_de_data_escolhe_o_ultimo_da_arvore(self):
        """Empate de data: vale o último da árvore, não o primeiro.

        A árvore do SEI traz só dia/mês/ano, sem hora, então quando dois ou
        mais Despachos têm a mesma data não há como saber qual é o mais
        recente pelo dado sozinho. A regra é a posição: o de maior `posicao`.

        Medido em 40 processos abertos ao vivo: 4 (10%) tinham empate na data
        mais recente, e é um caso comum o bastante para valer teste.
        """
        nodes = self._despachos(
            ("15/07/2026", "69148564"),
            ("15/07/2026", "69151810"),
            ("30/06/2026", "68710623"),
        )
        despacho = select_last_despacho(nodes)
        self.assertEqual(despacho.numero, "69151810")

    def test_empate_de_data_escolhe_o_ultimo_mesmo_com_muitos_empates(self):
        """Com 3+ despachos na mesma data, ainda vale o último da árvore."""
        nodes = self._despachos(
            ("20/05/2026", "67497497"),
            ("01/04/2026", "60123456"),
            ("20/05/2026", "67500000"),
            ("20/05/2026", "67603905"),
        )
        despacho = select_last_despacho(nodes)
        self.assertEqual(despacho.numero, "67603905")

    def test_celula_vazia_na_tabela_real_nao_escolhe_o_despacho_antigo(self):
        """Reproduz o HTML real: coluna existe, mas a célula do último está vazia.

        Este é o caso que produce o modo de falha reportado: o despacho mais
        recente some e um antigo vira o andamento atual.
        """
        html = """
        <div class="infraArvore">
        <table id="tblDocumentos">
         <tr><th>Documento</th><th>Data</th><th>Data de Inclusão</th></tr>
         <tr><td><input type="checkbox" value="64530001">
             <span class="infraLabel">Despacho</span></td>
             <td>30/06/2026</td><td>30/06/2026 14:00</td></tr>
         <tr><td><input type="checkbox" value="64530002">
             <span class="infraLabel">Despacho</span></td>
             <td>05/07/2026</td><td></td></tr>
        </table>
        </div>
        """
        nodes = parse_tree(html)
        with self.assertLogs("sei-insights", level="WARNING") as cap:
            despacho = select_last_despacho(nodes)

        self.assertEqual(despacho.numero, "64530001")
        self.assertIn("64530002", "\n".join(cap.output))


class CandidatosDespachoTest(unittest.TestCase):
    """`despachos_ordenados`: a lista de tentativas, do mais novo ao mais velho.

    O fallback (usar um Despacho mais antigo quando o mais recente não tem
    download público) só funciona se a ordem for a mesma que a escolha atual:
    data primeiro, desempate pela posição. Aqui testamos a ORDEM, que é o que
    faz o fallback cair no documento certo e não no mais antigo da árvore.
    """

    def _nodes(self, *pares):
        return [
            DocNode(serie="Despacho", numero=numero, data=data, posicao=i)
            for i, (data, numero) in enumerate(pares)
        ]

    def test_ordena_do_mais_recente_para_o_mais_antigo(self):
        nodes = self._nodes(
            ("10/09/2026", "100002"),
            ("15/09/2026", "100003"),
            ("01/09/2026", "100001"),
        )
        candidatos = despachos_ordenados(nodes)
        self.assertEqual([c.numero for c in candidatos],
                         ["100003", "100002", "100001"])

    def test_ordena_por_data_cronologica_e_nao_por_texto(self):
        """30/06 é anterior a 05/07; por texto o mais novo viraria o primeiro."""
        nodes = self._nodes(
            ("05/07/2026", "novo"),
            ("30/06/2026", "antigo"),
        )
        candidatos = despachos_ordenados(nodes)
        self.assertEqual([c.numero for c in candidatos], ["novo", "antigo"])

    def test_empate_de_data_por_posicao_maior_primeiro(self):
        nodes = self._nodes(
            ("15/09/2026", "primeiro"),
            ("15/09/2026", "ultimo"),
        )
        candidatos = despachos_ordenados(nodes)
        self.assertEqual([c.numero for c in candidatos], ["ultimo", "primeiro"])

    def test_sem_data_so_entra_na_lista_quando_nenhum_tem_data(self):
        """Sem data não é ordem: só vira candidato se não houver data nenhuma."""
        com_data = self._nodes(("15/09/2026", "100003"), ("", "100009"))
        with self.assertLogs("sei-insights", level="WARNING") as cap:
            candidatos = despachos_ordenados(com_data)
        self.assertEqual([c.numero for c in candidatos], ["100003"])
        self.assertIn("100009", "\n".join(cap.output))

    def test_sem_data_algum_ordena_por_posicao(self):
        so_sem_data = self._nodes(("", "100001"), ("", "100003"))
        with self.assertLogs("sei-insights", level="WARNING"):
            candidatos = despachos_ordenados(so_sem_data)
        self.assertEqual([c.numero for c in candidatos], ["100003", "100001"])

    def test_nao_e_despacho_nao_entra(self):
        nodes = [
            DocNode(serie="Ofício", numero="100004", data="16/09/2026", posicao=0),
            DocNode(serie="Despacho", numero="100002", data="10/09/2026", posicao=1),
        ]
        candidatos = despachos_ordenados(nodes)
        self.assertEqual([c.numero for c in candidatos], ["100002"])

    def test_sem_despacho_devolve_lista_vazia(self):
        self.assertEqual(despachos_ordenados([]), [])
        self.assertIsNone(select_last_despacho([]))

    def test_select_last_despacho_continua_pegando_o_primeiro(self):
        """`select_last_despacho` não muda: é o primeiro da lista de candidatos."""
        nodes = self._nodes(
            ("10/09/2026", "100002"),
            ("15/09/2026", "100003"),
        )
        self.assertEqual(select_last_despacho(nodes).numero, "100003")


# O SEI renderiza o Despacho restrito na tabela como os demais, mas nele não
# dá para marcar o checkbox nem gerar PDF. Como isso aparece no HTML muda o
# resultado, e uma das formas FAZIA o Despacho restrito desaparecer da árvore
# sem aviso — a planilha mostrava o andamento antigo como se fosse o atual.
ARVORE_COM_DESESPACHO_NORMAL = """
<div class="infraArvore">
<table id="tblDocumentos">
 <tr><th>Documento</th><th>Tipo</th><th>Data</th><th>Data de Inclusao</th></tr>
 <tr><td><input type="checkbox" value="66654831"><label title="Despacho"></label></td>
     <td>Despacho</td><td>17/04/2026</td><td>30/06/2026 14:00</td></tr>
 {extra}
</table>
</div>
"""

DESPACHO_SEM_CHECKBOX = """
 <tr><td><label title="Despacho"></label></td>
     <td>Despacho</td><td>05/07/2026</td><td>05/07/2026 09:00</td></tr>
"""

DESPACHO_CHECKBOX_DESABILITADO = """
 <tr><td><input type="checkbox" value="99999999" disabled>
     <label title="Despacho"></label></td>
     <td>Despacho</td><td>05/07/2026</td><td>05/07/2026 09:00</td></tr>
"""


class DespachoRestritoTest(unittest.TestCase):
    """Despacho que aparece na árvore mas não pode ser baixado."""

    def test_despacho_normal_e_selecionavel(self):
        nodes = parse_tree(ARVORE_COM_DESESPACHO_NORMAL.format(extra=""))
        despacho = select_last_despacho(nodes)
        self.assertEqual(despacho.numero, "66654831")
        self.assertTrue(despacho.selecionavel)

    def test_despacho_sem_checkbox_continua_na_arvore(self):
        """Restrito sem checkbox SOME da lista de candidatos se for ignorado.

        É o modo de falha que motivou isto: o Despacho de 05/07 existia e era
        o mais recente, mas sumia, e o processo passava a reportar 30/06 sem
        nenhum sinal. Perder o documento mais recente é pior que reportá-lo
        como não baixável.
        """
        nodes = parse_tree(
            ARVORE_COM_DESESPACHO_NORMAL.format(extra=DESPACHO_SEM_CHECKBOX)
        )
        self.assertEqual(len(nodes), 2)
        mais_recente = select_last_despacho(nodes)
        self.assertEqual(mais_recente.data, "05/07/2026")
        self.assertFalse(mais_recente.selecionavel)

    def test_checkbox_desabilitado_marca_como_nao_selecionavel(self):
        nodes = parse_tree(
            ARVORE_COM_DESESPACHO_NORMAL.format(
                extra=DESPACHO_CHECKBOX_DESABILITADO
            )
        )
        restrito = [n for n in nodes if n.data == "05/07/2026"][0]
        self.assertFalse(restrito.selecionavel)

    def test_restrito_sem_checkbox_nao_inventa_numero_para_marcar(self):
        """`numero` é a chave que marca o checkbox, e sem checkbox não há chave.

        Inventar um número (o do documento, por exemplo) faria o download
        tentar marcar um documento que não existe, ou pior, marcar o
        checkbox de outro.
        """
        nodes = parse_tree(
            ARVORE_COM_DESESPACHO_NORMAL.format(extra=DESPACHO_SEM_CHECKBOX)
        )
        restrito = [n for n in nodes if n.data == "05/07/2026"][0]
        self.assertEqual(restrito.numero, "")

    def test_o_restrito_continua_sendo_o_mais_recente(self):
        """A ordenação é por data, não por baixabilidade.

        Se o restrito deixasse de ser o primeiro candidato, o log deixaria de
        dizer que existe um Despacho mais novo, e a ordem do fallback
        passaria a esconder exatamente o que ele existe para revelar.
        """
        nodes = parse_tree(
            ARVORE_COM_DESESPACHO_NORMAL.format(extra=DESPACHO_SEM_CHECKBOX)
        )
        candidatos = despachos_ordenados(nodes)
        self.assertEqual([c.data for c in candidatos], ["05/07/2026", "30/06/2026"])
        self.assertFalse(candidatos[0].selecionavel)
        self.assertTrue(candidatos[1].selecionavel)
