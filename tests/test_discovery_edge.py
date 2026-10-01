import unittest

from bs4 import BeautifulSoup

from sei_insights.clients.discovery import (
    PROCESS_NUMBER_PATTERN,
    _numero_processo_da_linha,
    parse_response,
)


def _tr_com_data_prot(numero: str):
    """`<tr>` com `data-prot` no `<td>`, como na linha real do SEI."""
    html = (
        "<tr class='pesquisaTituloRegistro'>"
        f"<td data-prot='{numero}'>"
        "<a href='md_pesq_processo_exibir.php?id=1'>x</a>"
        "</td></tr>"
    )
    return BeautifulSoup(html, "html.parser").find("tr")

ROW_TD_DATA_PROT = (
    "<tr class='pesquisaTituloRegistro'>"
    "<td data-prot='21260.003436/2026-15'>"
    "<a href='md_pesq_processo_exibir.php?id=1'>Proc 1</a>"
    "</td></tr>"
)


class DiscoveryEdgeCasesTest(unittest.TestCase):
    def test_data_prot_no_td_e_procurado_nos_descendentes(self):
        data = {"itens": 1, "html": ROW_TD_DATA_PROT}
        result = parse_response(data)
        self.assertEqual(result, ["21260.003436/2026-15"])

    def test_prefixo_maior_que_5_digitos_e_aceito_integral(self):
        r"""Prefixo de unidade não tem largura fixa: `121260.X/AAAA-NN` é válido.

        Com `\d{4,5}` o `re.search` casava a partir do segundo dígito e
        devolvia `21260.002471/2026-17` — um processo que não existe. Com
        `\d{4,}` devolve o número inteiro. Descartar também estaria errado:
        o número está no formato, é válido, e sumir com ele da planilha é
        perda de dado.
        """
        self.assertEqual(
            _numero_processo_da_linha(_tr_com_data_prot("121260.002471/2026-17")),
            "121260.002471/2026-17",
        )

    def test_prefixo_de_qualquer_tamanho_nao_e_truncado(self):
        """Nenhum prefixo pode ser cortado: o que casar é o número inteiro."""
        for numero in ["121260.002471/2026-17",
                       "21260.002471/2026-17",
                       "3126.002471/2026-17",
                       "1234567.002471/2026-17",
                       "121260.0024711/2026-17"]:
            with self.subTest(numero=numero):
                achado = _numero_processo_da_linha(_tr_com_data_prot(numero))
                self.assertEqual(achado, numero)

    def test_sequencial_maior_que_o_formato_nao_e_cortado(self):
        """Sequencial com 9 dígitos não cabe em `\\d{6,8}` e é descartado.

        Diferente do prefixo, aqui não existe versão "mais correta": o
        sequencial tem largura definida pelo formato, então um valor de 9
        dígitos não é número de processo e a linha é descartada com aviso —
        nunca gravado truncado para 8.
        """
        for texto in ["121260.002471123/2026-17",
                      "121260.0024711234/2026-17"]:
            with self.subTest(texto=texto):
                row = BeautifulSoup(
                    f"<tr><td><a href='md_pesq_processo_exibir.php?id=1'>"
                    f"{texto}</a></td></tr>",
                    "html.parser",
                ).find("tr")
                self.assertEqual(_numero_processo_da_linha(row), "")

    def test_numero_colado_a_outro_numero_nao_e_inventado(self):
        """`(?<!\d)` / `(?!\d)`: sem âncora, um número casa dentro do outro.

        É o outro lado do prefixo livre. `9` antes ou depois faria o
        `re.search` devolver um processo que não existe.
        """
        for texto, esperado in [
            ("X121260.002471/2026-17", "121260.002471/2026-17"),
            ("121260.002471/2026-179", ""),
            ("121260.002471/2026-1", ""),
            ("9121260.002471/2026-17", "9121260.002471/2026-17"),
        ]:
            with self.subTest(texto=texto):
                html = (
                    f"<tr class='pesquisaTituloRegistro'><td>"
                    f"<a href='md_pesq_processo_exibir.php?id=1'>{texto}</a>"
                    f"</td></tr>"
                )
                row = BeautifulSoup(html, "html.parser").find("tr")
                self.assertEqual(_numero_processo_da_linha(row), esperado)

    def test_dois_numeros_na_mesma_celula_encontra_numero_valido(self):
        html = (
            "<tr class='pesquisaTituloRegistro'>"
            "<td><a href='md_pesq_processo_exibir.php?id=1'>"
            "Relacionado ao processo 19974.000044/2026-06 (ref 21260.002471/2026-17)"
            "</a></td></tr>"
        )
        result = parse_response({"itens": 1, "html": html})
        self.assertTrue(result)
        import re

        for n in result:
            self.assertTrue(re.fullmatch(PROCESS_NUMBER_PATTERN, n))
