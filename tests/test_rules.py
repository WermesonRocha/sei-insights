import json
import unittest
from pathlib import Path

from sei_insights.config.rules import RulesEngine

REGRA_DETRAN = [
    {
        "pattern": r"encaminha-se.*?(?:\bagentes\b)?.*?(SGA|SCL|CTI|CCL)\b",
        "situacao": "Em {destino}",
        "destino": "\\1",
        "acao_esperada": "ciência e validação",
        "pendencia_curta": "Processo com o destino para análise/próximo passo",
    },
    {
        "pattern": r"(?:exigir|aguardando).*(?:assinatura)",
        "situacao": "Pendente de assinatura",
        "destino": "",
        "acao_esperada": "assinatura",
        "pendencia_curta": "Aguardando assinatura",
    },
    {
        "pattern": r"DETRAN",
        "situacao": "Encaminhado a órgão externo (Detran/DF)",
        "destino": "Detran/DF",
        "acao_esperada": "providências",
        "pendencia_curta": "Detran/DF adotar providências",
    },
]

DESPACHO_DETRAN = (
    "Diante do exposto, encaminham-se os autos à Subsecretaria de Gestão e "
    "Administração (SGA), para ciência e validação da Minuta de Ofício anexa, "
    "conversão em Ofício, e, após, retorno a esta Coordenação de Contratações e "
    "Logística (CCL), para encaminhamento do Ofício e dos demais anexos ao "
    "Departamento de Trânsito do Distrito Federal (Detran/DF), para análise e "
    "adoção das providências necessárias ao cancelamento das comunicações de "
    "transferência veicular anteriormente realizadas e à consequente "
    "regularização dos registros de transferência dos veículos."
)


class RulesTest(unittest.TestCase):
    def test_classifica_detran(self):
        engine = RulesEngine(REGRA_DETRAN)
        r = engine.classify(DESPACHO_DETRAN)
        self.assertIn("Detran/DF", r.situacao)
        self.assertEqual(r.destino, "Detran/DF")
        self.assertTrue(r.pendencia_curta)

    def test_fallback_quando_nada_casa(self):
        engine = RulesEngine(REGRA_DETRAN)
        r = engine.classify("Texto irrelevante sem padrão conhecido.")
        self.assertEqual(r.situacao, "Em análise")

    def test_regras_json_captura_destino_generico(self):
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(
            "Diante do exposto, encaminham-se os autos a Subsecretaria de Gestão "
            "e Administração, para análise e adoção das providências necessárias."
        )
        self.assertEqual(r.destino, "Subsecretaria de Gestão e Administração")
        self.assertNotIn("\x01", r.situacao)
        self.assertTrue(r.situacao.startswith("Encaminhado a "))

    def test_regra_generica_captura_acao_e_destino(self):
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(
            "O processo segue para análise da SGA, para adoção das providências."
        )
        self.assertEqual(r.situacao, "Aguardando análise de SGA")
        self.assertEqual(r.destino, "SGA")
        self.assertEqual(r.acao_esperada, "análise")
        self.assertEqual(r.pendencia_curta, "Aguardando análise de SGA")

    def test_destino_vem_do_cabecalho_e_nao_do_corpo(self):
        """O destino é o destinatário citado no cabeçalho 'À <setor>', não a
        ação mencionada no corpo (ex.: o fecho '... à SENEV' é só contexto)."""
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(DESPACHO_003611)
        self.assertEqual(r.destino, "CGATI")
        self.assertEqual(r.situacao, "Encaminhado a conhecimento e deliberação")
        self.assertEqual(r.acao_esperada, "conhecimento e deliberação")
        self.assertIn("conhecimento e deliberação", r.pendencia_curta)

    def test_destino_do_cabecalho_sem_quebra_de_linha_nao_polui_corpo(self):
        """'À' sozinho numa linha (layout) também é lido; palavras do cabeçalho
        (Secretaria, DESPACHO) não contaminam a situação."""
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(DESPACHO_003090)
        self.assertEqual(r.destino, "CGATI")
        self.assertEqual(r.situacao, "Encaminhado a conhecimento e avaliação superior")
        self.assertNotIn("Secretaria", r.situacao)
        self.assertNotIn("Em Coordenação", r.situacao)

    def test_destino_com_copia_c_ignora_cc(self):
        """Com bloco 'C/c:' no cabeçalho, o destino é o primeiro 'À ...'."""
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(DESPACHO_001630)
        self.assertEqual(r.destino, "CPSG")
        self.assertEqual(r.situacao, "Encaminhado a conhecimento e adoção")

    def test_destino_com_sigla_apos_travessao(self):
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(DESPACHO_002715)
        self.assertEqual(r.destino, "COSIS")
        self.assertEqual(r.situacao, "Encaminhado a análise e providências")

    def test_destino_do_cabecalho_sga_ciencia_e_validacao(self):
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(DESPACHO_003690)
        self.assertEqual(r.destino, "SGA")
        self.assertEqual(r.situacao, "Encaminhado a ciência e validação")

    def test_destino_sigla_via_mapa_de_unidades(self):
        """'Coordenação de Tecnologia da Informação' vira CTI pelo mapa em
        regras.json; sem ação conhecida cai no fallback (não 'Em Secretaria')."""
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(
            "MINISTÉRIO DAS MULHERES\nSecretaria-Executiva\n\n"
            "DESPACHO\n\nProcesso nº 21260.000000/2026-00\n\n"
            "À Coordenação de Tecnologia da Informação\n\n"
            "Aguardando manifestação do setor responsável."
        )
        self.assertEqual(r.destino, "CTI")
        self.assertEqual(r.situacao, "Em análise")

    def test_ao_gabinete_da_ministra_003709(self):
        """'Ao Gabinete da Ministra' é lido como destinatário exato no cabeçalho
        (não 'À'); a situação do texto real (sugestão de retomada) é capturada."""
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(DESPACHO_003709)
        self.assertEqual(r.destino, "Gabinete da Ministra")
        self.assertEqual(r.situacao, "Aguardando retomada (avaliação futura)")
        self.assertNotEqual(r.destino, "Secretaria")

    def test_ao_gabinete_da_ministra_003728(self):
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(DESPACHO_003728)
        self.assertEqual(r.destino, "Gabinete da Ministra")
        self.assertEqual(r.situacao, "Aguardando retomada (avaliação futura)")

    def test_ao_gabinete_nome_completo_003829(self):
        """'Ao Gabinete da Secretaria Nacional de ...' mantém o nome completo."""
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(DESPACHO_003829)
        self.assertEqual(
            r.destino,
            "Gabinete da Secretaria Nacional de Autonomia Econômica e Política "
            "de Cuidados",
        )
        self.assertNotEqual(r.destino, "Secretaria")

    def test_assunto_nao_sangra_no_destino(self):
        """Linha 'Assunto:' após o destinatário não vaza para o destino."""
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(DESPACHO_14021)
        self.assertEqual(r.destino, "SE")
        self.assertNotIn("Assunto", r.destino)

    def test_sigla_apenas_quando_nome_inteiro_casa(self):
        """Sigla só por equivalência do nome inteiro; 'Gabinete da Secretaria
        Executiva' continua por extenso (com o 'Gabinete da')."""
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(
            "MINISTÉRIO DAS MULHERES\nSecretaria-Executiva\n\n"
            "DESPACHO\n\n"
            "Ao Gabinete da Secretaria-Executiva\n\n"
            "Solicita-se análise do expediente."
        )
        self.assertEqual(r.destino, "Gabinete da Secretaria-Executiva")

    def test_timbrado_sem_destinatario_nao_polui_a_situacao(self):
        """Sem linha de destinatário (À/Ao), o bloco do timbrado é descartado
        do corpo e palavras do papel de fundo não viram 'Em Secretaria'."""
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(
            "MINISTÉRIO DAS MULHERES\n"
            "Secretaria Nacional de Enfrentamento à Violência contra Mulheres\n\n"
            "DESPACHO\n\n"
            "Solicita-se a análise do expediente quanto à disponibilidade "
            "orçamentária para o próximo exercício."
        )
        self.assertNotIn("Secretaria", r.situacao)
        self.assertNotIn("Em Coordenação", r.situacao)

    def test_timbrado_longo_nao_vira_destino(self):
        """Regressão real (14021.109425/2025-14): timbrado de 6 linhas.

        `_is_letterhead` só aceitava até 3 linhas, então o timbrado do MGI
        foi lido como corpo e a regra de unidade interna capturou
        'SECRETARIA' -> destino 'Secretaria' / situação 'Em Secretaria'.
        """
        engine = RulesEngine.from_file(Path("regras.json"))
        r = engine.classify(
            "MINISTÉRIO DA GESTÃO E DA INOVAÇÃO EM SERVIÇOS PÚBLICOS\n"
            "Secretaria de Serviços Compartilhados\n"
            "Diretoria de Administração e Logística\n"
            "Coordenação-Geral de Projetos e Contratos Transversais\n"
            "Coordenação de Contratos Transversais\n"
            "Divisão de Contratos Transversais\n"
            "DESPACHO\n\n"
            "Processo nº 14021.109425/2025-14\n\n"
            "INFORMAÇÕES PARA PAGAMENTO DE DESPESA CONTRATUAL\n"
        )
        self.assertNotEqual(r.destino, "Secretaria")
        self.assertNotIn("Em Secretaria", r.situacao)


class DestinoPlaceholderTest(unittest.TestCase):
    """Pina o placeholder `{destino}`: a situação passa a dizer DE QUEM.

    Bug real: 23 de 37 despachos saíam genéricos ("Em Coordenação",
    "Em Secretaria", "Encaminhado a ciência") porque a situação media a
    ação e descartava o destinatário, que já estava disponível na coluna
    ao lado. `{destino}` expande com o valor LITERAL do cabeçalho — a
    situação continua autossuficiente sem inventar nada.
    """

    ENGINE = RulesEngine({
        "regras": [
            {
                # casa o CORPO (o cabeçalho é lido à parte). O grupo 1 captura
                # a unidade interna citada no corpo; a situação usa o
                # placeholder para dizer DE QUEM é o trabalho.
                "pattern": r"(?:Retorno a esta (COORDENA[ÇC][ÃA]O)[^.]*)?an[áa]lise",
                "situacao": "Em {destino}",
                "destino": "\\1",
                "acao_esperada": "análise",
                "pendencia_curta": "",
            },
        ],
        # usa o mapa real de siglas para exercitar a redução por equivalência
        "siglas": json.loads(Path("regras.json").read_text(encoding="utf-8"))["siglas"],
    })

    def test_expande_com_destino_do_cabecalho(self):
        r = self.ENGINE.classify(
            "À Coordenação-Geral de Administração e Tecnologia da Informação\n\n"
            "Trata-se de análise da solicitação."
        )
        self.assertEqual(r.destino, "CGATI")
        self.assertEqual(r.situacao, "Em CGATI")

    def test_expande_com_nome_por_extenso_quando_nao_ha_sigla(self):
        r = self.ENGINE.classify(
            "À Gabinete da Ministra\n\nTrata-se de análise da solicitação."
        )
        self.assertEqual(r.destino, "Gabinete da Ministra")
        self.assertEqual(r.situacao, "Em Gabinete da Ministra")

    def test_sem_destino_nao_deixa_placeholder_quebrado(self):
        """Sem destino, expande para rótulo explícito — nunca string vazia
        ('Em ') nem o placeholder literal."""
        r = self.ENGINE.classify("Solicita-se análise da coordenação.")
        self.assertNotIn("{destino}", r.situacao)
        self.assertEqual(r.situacao, "Em (destino não identificado)")

    def test_destino_tem_precedencia_sobre_o_capturado_no_corpo(self):
        """O cabeçalho manda: o corpo diz 'Retorno a esta Coordenação', mas
        quem recebeu o processo foi a CGATI — vale o endereçado, igual à
        precedência já aplicada à coluna `destino`."""
        r = self.ENGINE.classify(
            "À Coordenação-Geral de Administração e Tecnologia da Informação\n\n"
            "Retorno a esta Coordenação para análise e continuidade."
        )
        self.assertEqual(r.destino, "CGATI")
        self.assertEqual(r.situacao, "Em CGATI")

    def test_destino_com_caractere_de_regex_nao_quebra_a_expansao(self):
        """O texto do despacho é literal: um `\\1` escrito no nome do
        destinatário é copiado, não consumido como backreference."""
        r = self.ENGINE.classify(
            "À \\1 Charlatan\n\nTrata-se de análise."
        )
        self.assertEqual(r.destino, "\\1 Charlatan")
        self.assertEqual(r.situacao, "Em \\1 Charlatan")


class RegraGenericaInternaTest(unittest.TestCase):
    """Regras específicas da unidade e genérica interna (regras.json real)."""

    def setUp(self):
        self.engine = RulesEngine.from_file(Path("regras.json"))

    def test_regra_interna_diz_a_unidade_nao_o_substantivo(self):
        """Regressão 21260.001144/2026-30 e afins: 'Em Coordenação' -> 'Em CGATI'.

        A regra interna capturava só o substantivo ('COORDENAÇÃO'); agora a
        situação usa o destino efetivo, que vem do cabeçalho. Isola a regra
        para não depender de outras que casem o mesmo texto.
        """
        cfg = json.loads(Path("regras.json").read_text(encoding="utf-8"))
        internas = [r for r in cfg["regras"] if r["situacao"] == "Em {destino}"]
        self.assertEqual(len(internas), 1, "espera 1 única regra com {destino}")
        engine = RulesEngine({"regras": internas, "siglas": cfg["siglas"]})
        r = engine.classify(
            "MINISTÉRIO DAS MULHERES\nSecretaria-Executiva\n\n"
            "DESPACHO\n\nProcesso nº 21260.001144/2026-30\n\n"
            "À Coordenação-Geral de Administração e Tecnologia da Informação\n\n"
            "Retorno a esta Coordenação para análise e continuidade do processo."
        )
        self.assertEqual(r.destino, "CGATI")
        self.assertEqual(r.situacao, "Em CGATI")
        self.assertEqual(
            r.pendencia_curta, "Processo com CGATI para análise/próximo passo"
        )

    def test_regra_interna_sem_cabecalho_mantem_o_substantivo(self):
        """Sem cabeçalho não há destino para citar: a situação repete o
        substantivo encontrado (honesto) em vez de prometer um identificador."""
        cfg = json.loads(Path("regras.json").read_text(encoding="utf-8"))
        internas = [r for r in cfg["regras"] if r["situacao"] == "Em {destino}"]
        engine = RulesEngine({"regras": internas, "siglas": cfg["siglas"]})
        r = engine.classify("Retorno a esta Coordenação para análise.")
        self.assertEqual(r.destino, "Coordenação")
        self.assertEqual(r.situacao, "Em Coordenação")

    def test_mencao_a_nome_completo_de_unidade_nao_vira_destino(self):
        """Regressão 12804.000290/2026-62: menção a nome completo não é destino.

        O corpo diz "recebidos pela Coordenação de Patrimônio e Serviços
        Gerais (CPSG)" — cita a unidade do próprio signatário. A regra
        genérica pegava o substantivo solto ("Coordenação") e a planilha
        passava a mostrar um destino que não existe.
        """
        r = self.engine.classify(
            "DESPACHO\n\n"
            "Informamos que os bens foram devidamente recebidos pelo "
            "Ministério das Mulheres, e foram recebidos pela Coordenação de "
            "Patrimônio e Serviços Gerais (CPSG).\n"
        )
        self.assertEqual(r.destino, "")

    def test_com_cabecalho_unidade_citada_no_corpo_nao_muda_a_situacao(self):
        """Com cabeçalho, a menção a uma unidade no corpo não reescreve nada.

        O destino vem do cabeçalho (CGATI) e a regra genérica apenas fraseia
        a situação. Tornar o padrão estrito só vale SEM cabeçalho — do
        contrário processos com cabeçalho perdiam "Em {destino}" e viravam
        "Em análise" à toa.
        """
        cfg = json.loads(Path("regras.json").read_text(encoding="utf-8"))
        internas = [r for r in cfg["regras"] if r["situacao"] == "Em {destino}"]
        engine = RulesEngine({"regras": internas, "siglas": cfg["siglas"]})
        r = engine.classify(
            "MINISTÉRIO DAS MULHERES\nSecretaria-Executiva\n\n"
            "DESPACHO\n\n"
            "À Coordenação-Geral de Administração e Tecnologia da Informação\n\n"
            "Solicito que a Secretaria de Serviços Compartilhados seja acionada."
        )
        self.assertEqual(r.destino, "CGATI")
        self.assertEqual(r.situacao, "Em CGATI")

    def test_sem_cabecalho_nome_de_unidade_nao_deixa_regra_externa_vencer(self):
        """Sem cabeçalho, a menção a nome de unidade para no fallback.

        Regressão 12804.000815/2026-60: o corpo cita "Coordenação de ..." e
        também traz "TCU" em boilerplate (SICAF/CEIS). O modo estrito não pode
        deixar a regra de órgão externo casar o boilerplate e inventar destino.
        """
        r = self.engine.classify(
            "DESPACHO\n\n"
            "Consulta Consolidada TCU sobre fornecedores.\n\n"
            "Os bens foram recebidos pela Coordenação de Patrimônio e Serviços "
            "Gerais (CPSG).\n"
        )
        self.assertEqual(r.destino, "")

    def test_apreciacao_e_acao_reconhecida(self):
        """Regressão 21260.001144/2026-30 e 21260.003895/2026-91.

        'apreciação' e 'publicação' não estavam no vocabulário de ações, então
        o texto caía no fallback 'Em análise'.
        """
        r = self.engine.classify(
            "MINISTÉRIO DAS MULHERES\n\nDESPACHO\n\n"
            "À Gabinete da Ministra\n\n"
            "Encaminho, para apreciação e providências, a solicitação."
        )
        self.assertEqual(r.situacao, "Encaminhado a apreciação e providências")

    def test_publicacao_e_acao_reconhecida(self):
        r = self.engine.classify(
            "MINISTÉRIO DAS MULHERES\n\nDESPACHO\n\n"
            "À Gabinete da Ministra\n\n"
            "Em atenção ao Despacho SEI nº 64734700, encaminha-se a Portaria "
            "de Pessoal nº 233, para publicação no Diário Oficial da União."
        )
        self.assertTrue(r.situacao.startswith("Encaminhado a"))
        self.assertIn("publicação", r.situacao)
        self.assertNotEqual(r.situacao, "Em análise")

    def test_encaminho_para_acao_sem_autos_a_unidade(self):
        """Regressão 21260.001480/2026-82 e 12804.000290/2026-62.

        'Encaminho para conhecimento e providências o DFD' não tinha padrão
        (as regras existentes exigiam 'os autos a <unidade>').
        """
        r = self.engine.classify(
            "MINISTÉRIO DAS MULHERES\n\nDESPACHO\n\n"
            "À Secretaria de Gestão e Administração\n\n"
            "Encaminho para conhecimento e providências o Documento de "
            "Formalização de Demanda, que trata de aquisição de equipamentos."
        )
        self.assertEqual(r.situacao, "Encaminhado a conhecimento e providências")
        self.assertEqual(r.destino, "Secretaria de Gestão e Administração")

    def test_termo_de_encerramento_nao_vira_em_assessoria(self):
        """Regressão 21260.001106/2026-87.

        'Termo de Encerramento ... procedo ao seu encerramento' caía na regra
        de unidade interna e virava 'Em Assessoria' (cargo da signatária).
        """
        r = self.engine.classify(DESPACHO_001106)
        self.assertEqual(r.situacao, "Encerrado")
        self.assertNotIn("Assessoria", r.situacao)
        self.assertNotIn("Assessoria", r.destino)

    def test_bloco_de_assinatura_nao_vira_destino(self):
        """O cargo da signatária ('Assessora Técnica', unidade) é bloco de
        assinatura e não pode virar destinatário."""
        r = self.engine.classify(
            "MINISTÉRIO DAS MULHERES\n\nDESPACHO\n\n"
            "À Gabinete da Ministra\n\n"
            "Encaminho para conhecimento.\n\n"
            "Brasília, na data da assinatura.\n\n"
            "assinado digitalmente\nJOÃO DA SILVA\nAssessor Técnico\n"
            "Assessoria Especial de Controle Interno - AECI\n\n"
            "A autenticidade deste documento pode ser conferida no site."
        )
        self.assertEqual(r.destino, "Gabinete da Ministra")
        self.assertNotIn("Assessoria", r.situacao)


class CampoDestinoTest(unittest.TestCase):
    """O campo `Destino:` que o SEI imprime em alguns despachos.

    Regressão 21260.000680/2025-37: o documento traz
    `Destino: Assessoria Especial de Comunicação Social - ASCOM`, o motor
    só lia `À/Ao/Aos/Às`, e o timbrado vencia -> 'Em Secretaria'.
    """

    ENGINE = RulesEngine.from_file(Path("regras.json"))

    def test_campo_destino_e_lido(self):
        r = self.ENGINE.classify(DESPACHO_000680)
        self.assertEqual(r.destino, "ASCOM")
        self.assertNotIn("Em Secretaria", r.situacao)

    def test_campo_destino_nao_vaza_para_o_corpo(self):
        r = self.ENGINE.classify(DESPACHO_000680)
        self.assertNotIn("ASCOM", r.situacao.split("Em ")[-1][-4:])

    def test_assunto_nao_vira_destino_quando_ha_campo_destino(self):
        r = self.ENGINE.classify(DESPACHO_000680)
        self.assertNotIn("Assunto", r.destino)
        self.assertNotIn("Quem é Quem", r.destino)


class SufixoDeReferenciaTest(unittest.TestCase):
    """Nome da unidade por extenso + sufixo de referência do SEI.

    Regressão 21260.001552/2026-91: o cabeçalho escreve
    `À Coordenação-Geral de Tecnologia da Informação - CGTI/MMULHERES`.
    A redução por mapa exigia o nome INTEIRO, e a extração por travessão
    exigia a sigla no fim da linha — o `/MMULHERES` (código de memória do
    SEI) quebrava as duas, e o destino saía com o nome inteiro.
    """

    ENGINE = RulesEngine.from_file(Path("regras.json"))

    def test_extenso_com_codigo_de_memoria_vira_sigla(self):
        self.assertEqual(
            self.ENGINE.normalize_recipient(
                "Coordenação-Geral de Tecnologia da Informação - CGTI/MMULHERES"
            ),
            "CGTI",
        )

    def test_classify_do_21260_001552(self):
        r = self.ENGINE.classify(DESPACHO_001552)
        self.assertEqual(r.destino, "CGTI")
        self.assertNotIn("CGTI/MMULHERES", r.situacao)

    def test_extenso_com_sigla_apos_travessao_continua_valendo(self):
        """A regra que já existia (sigla solta após travessão) não pode
        regredir: aqui o nome nem está no mapa."""
        self.assertEqual(
            self.ENGINE.normalize_recipient("Unidade de Convênios - UC"), "UC"
        )

    def test_sem_mapa_e_sem_sigla_mantem_o_nome_inteiro(self):
        """Nada é inventado: sem chave no mapa e sem sigla no fim, o nome
        por extenso é preservado."""
        self.assertEqual(
            self.ENGINE.normalize_recipient(
                "Diretoria de Proteção de Direitos - algo"
            ),
            "Diretoria de Proteção de Direitos - algo",
        )


class VariosDestinatariosTest(unittest.TestCase):
    """Despacho com mais de um destinatário no cabeçalho.

    Regressão 12804.000730/2026-75: o cabeçalho traz três linhas `À ...`.
    O motor pegava a primeira e arrastava as outras junto, produzindo um
    destino só, com os `À` do meio e a palavra "Assunto" grudados.
    """

    ENGINE = RulesEngine.from_file(Path("regras.json"))

    def test_destinatarios_ficam_separados_na_mesma_celula(self):
        r = self.ENGINE.classify(DESPACHO_71163039)
        self.assertEqual(
            r.destino,
            "Diretoria de Proteção de Direitos; "
            "Coordenação-Geral de Prevenção à Violência contra Mulheres; "
            "Unidade de Convênios",
        )

    def test_nenhum_ai_ou_assunto_sobra_no_destino(self):
        r = self.ENGINE.classify(DESPACHO_71163039)
        self.assertNotIn("À ", r.destino)
        self.assertNotIn("Assunto", r.destino)
        self.assertNotIn("Realização de espelho", r.destino)

    def test_situacao_continua_vencendo_pelas_regras(self):
        r = self.ENGINE.classify(DESPACHO_71163039)
        self.assertEqual(r.situacao, "Encaminhado a conhecimento e providências")

    def test_destinatario_unico_continua_sem_separador(self):
        """Um só destinatário não ganha '; ' sobrando."""
        r = self.ENGINE.classify(DESPACHO_003611)
        self.assertEqual(r.destino, "CGATI")
        self.assertNotIn(";", r.destino)

    def test_cada_destinatario_reduz_a_sua_propria_sigla(self):
        """Regressão 21260.001018/2026-85: o cabeçalho traz DOIS
        destinatários, cada um com sua sigla ('... Gerais - CPSG' e
        '... Logística - CCL'). Reduzir a célula inteira fazia o corte de
        sufixo pegar o segundo e o primeiro sumir da linha.
        """
        r = self.ENGINE.classify(DESPACHO_64805953)
        self.assertEqual(r.destino, "CPSG; CCL")


# Cabeçalho com a unidade por extenso + código de memória do SEI (regressão
# 21260.001552/2026-91): o travessão traz "CGTI/MMULHERES", o que impedia
# tanto a redução por mapa quanto a extração da sigla após o travessão.
DESPACHO_001552 = (
    "MINISTÉRIO DAS MULHERES\nSecretaria-Executiva\n"
    "Coordenação-Geral de Gestão e Administração\n"
    "Coordenação de Orçamento e Finanças\n\n"
    "DESPACHO\n\n"
    "Processo nº 21260.001552/2026-91\n\n"
    "À Coordenação-Geral de Tecnologia da Informação - CGTI/MMULHERES\n"
    "C/c: Subsecretaria de Gestão e Administração - SGA/SE\n\n"
    "Em atenção ao Despacho Numerado 717 (59774593), que solicita a emissão "
    "da Certificação de Disponibilidade Orçamentária (CDO) e descentralização "
    "de crédito, encaminho para ciência e adoção das providências cabíveis."
)

# Despacho com três destinatários no cabeçalho (regressão
# 12804.000730/2026-75): o motor colava as três linhas num destino só, com os
# "À" e o "Assunto" do meio grudados.# Dois destinatários, cada um com a própria sigla (regressão
# 21260.001018/2026-85): a redução de sigla precisa ser feita por destinatário,
# senão o corte de sufixo da célula inteira faz o primeiro sumir.
DESPACHO_64805953 = (
    "MINISTÉRIO DAS MULHERES\nSecretaria-Executiva\n"
    "Subsecretaria de Gestão e Administração\n\n"
    "DESPACHO Nº 526/2026/SGA/SE-MMULHERES\n\n"
    "Processo nº 21260.001018/2026-85\n\n"
    "À Coordenação de Patrimônio e Serviços Gerais - CPSG\n"
    "À Coordenação de Contratação e Logística - CCL\n"
    "C/c: À Coordenação-Geral de Administração e Orçamento\n\n"
    "Em atenção ao Despacho (SEI-58653928), que versa a utilização dos "
    "serviços de Telefonia Móvel disponibilizados no âmbito do ColaboraGov, "
    "para conhecimento e providências."
)

DESPACHO_71163039 = (
    "MINISTÉRIO DAS MULHERES\n"
    "Secretaria Nacional de Enfrentamento à Violência contra Mulheres\n\n"
    "DESPACHO\n\n"
    "À Diretoria de Proteção de Direitos \n"
    "À Coordenação-Geral de Prevenção à Violência contra Mulheres\n"
    "À Unidade de Convênios\n"
    "Assunto: \n"
    "Realização de espelho de progresso\n\n"
    "Cumprimentando-as cordialmente, encaminho, para conhecimento e "
    "providências, o Despacho (64753990), proveniente da Coordenação de "
    "Assessoramento e Registros."
)

DESPACHO_001630 = (
    "MINISTÉRIO DAS MULHERES\nSecretaria-Executiva\nSubsecretaria de Gestão e "
    "Administração\nCoordenação-Geral de Administração e Tecnologia da Informação\n\n"
    "DESPACHO\n\n"
    "À Coordenação de Patrimônio e Serviços Gerais\nC/c: \nÀ \nSubsecretaria de "
    "Gestão e Administração (SGA)\n\n"
    "Diante do exposto, encaminham-se os autos à Coordenação de Patrimônio e "
    "Serviços Gerais (CPSG), para conhecimento e adoção das providências cabíveis."
)

DESPACHO_002715 = (
    "MINISTÉRIO DAS MULHERES\nSecretaria-Executiva\nSubsecretaria de Gestão e "
    "Administração\nCoordenação-Geral de Tecnologia da Informação\n\n"
    "DESPACHO Nº 82/2026/CGTI/SGA/SE-MMULHERES\n\n"
    "Processo nº 21260.002715/2026-53\n\n"
    "À \nCoordenação de Sistemas e Soluções de Tecnologia da Informação – COSIS\n\n"
    "Assunto: Disponibilização de dados de atendimentos das Casas da Mulher "
    "Brasileira.\n\n"
    "1\n.\nCumprimentando-as cordialmente, em atenção ao Despacho de "
    "disponibilização de dados (SEI nº 62396472), en\ncaminho o presente processo "
    "para análise e providências quanto à solicitação de disponibilização dos "
    "dados de atendimento das Casas da Mulher Brasileira (CMBs) aos respectivos "
    "gestores."
)

DESPACHO_003090 = (
    "MINISTÉRIO DAS MULHERES\nSecretaria-Executiva\nSubsecretaria de Gestão e "
    "Administração\nCoordenação-Geral de Administração e Tecnologia da "
    "Informação\nCoordenação de Tecnologia da Informação\nDivisão de Tecnologia "
    "da Informação\n\n"
    "DESPACHO\n\n"
    "Processo nº 21260.003090/2026-47\nÀ \nCoordenação-Geral de Administração e "
    "Tecnologia da Informação\n\n"
    "1\n.\nTrata-se de análise da solicitação encaminhada pela SENAIP, para "
    "disponibilização de 11 (onze) computadores.\n\n"
    "2\n.\nDiante do exposto, encaminham-se os presentes autos à Coordenação-Geral "
    "de Administração e Tecnologia da Informação (CGATI), para conhecimento e "
    "avaliação superior quanto ao quantitativo de equipamentos a ser disponibilizado "
    "à SENAIP neste momento. Após a definição e autorização por parte dessa "
    "Coordenação-Geral, a CTI adotará as providências necessárias à entrega dos "
    "equipamentos."
)

DESPACHO_003611 = (
    "MINISTÉRIO DAS MULHERES\nSecretaria-Executiva\nSubsecretaria de Gestão e "
    "Administração\nCoordenação-Geral de Administração e Tecnologia da "
    "Informação\nCoordenação de Tecnologia da Informação\n\n"
    "DESPACHO Nº 169/2026/CTI/CGATI/SGA/SE-MMULHERES\n\n"
    "Processo nº 21260.003611/2026-66\n\n"
    "À Coordenação-Geral de Administração e Tecnologia da\nInformação,\n\n"
    "1\n.\nEm atenção ao Despacho (SEI nº 64155420), referente à disponibilização "
    "de 15 (quinze) computadores adicionais, informamos que o Ministério não "
    "dispõe desse quantitativo de computadores.\n\n"
    "3\n.\nDessa forma, encaminham-se os autos à Coordenação-Geral de Administração "
    "e Tecnologia da Informação (CGATI), para conhecimento e deliberação quanto ao "
    "quantitativo de equipamentos a ser disponibilizado à SENEV. Após a "
    "autorização, a CTI adotará as providências necessárias para a entrega dos "
    "equipamentos."
)

DESPACHO_003690 = (
    "MINISTÉRIO DAS MULHERES\nSecretaria-Executiva\nSubsecretaria de Gestão e "
    "Administração\nCoordenação-Geral de Administração e Tecnologia da "
    "Informação\n\n"
    "DESPACHO\n\n"
    "Processo nº 21260.003690/2026-13\n\n"
    "À Subsecretaria de Gestão e Administração (SGA)\n\n"
    "Trata-se do Despacho Numerado 168 (64284604), por meio do qual a CTI "
    "encaminha Minuta de Ofício destinada à Secretaria-Executiva do Ministério "
    "dos Direitos Humanos e da Cidadania (MDHC).\n\n"
    "Nesse sentido, encaminham-se os autos à Subsecretaria de Gestão e "
    "Administração (SGA), para ciência e validação da Minuta de Ofício anexa, e, "
    "poster envio ao Gabinete da Secretaria-Executiva, para apreciação e, se de "
    "acordo, conversão em Ofício para fins de encaminhamento à Secretária-Executiva "
    "do Ministério dos Direitos Humanos e da Cidadania (MDHC)."
)

# Despachos endereçados com "Ao ..." (sem "À"): o destinatário fica no
# cabeçalho e deve ser capturado por extenso/exato (003709/003728 = resposta
# da Secretaria Nacional de Enfrentamento à Violência ao Gabinete da Ministra;
# 003829 = resposta endereçada ao Gabinete da Secretaria Nacional de
# Autonomia Econômica e Política de Cuidados).

DESPACHO_003709 = (
    "MINISTÉRIO DAS MULHERES\n"
    "Secretaria Nacional de Enfrentamento à Violência contra Mulheres\n\n"
    "DESPACHO\n\n"
    "Ao Gabinete da Ministra\n"
    "Assunto: 14º Seminário Internacional Fazendo Gênero.\n\n"
    "Cumprimentando-as cordialmente, em atenção ao Despacho Numerado nº 1496, "
    "referente à realização do 14º Seminário Internacional Fazendo Gênero.\n\n"
    "Considerando que o evento está previsto para ocorrer em 2027 e que o "
    "planejamento orçamentário desta Secretaria Nacional para o exercício de 2026 "
    "já se encontra comprometido com outras atividades, sugere-se que a demanda "
    "seja retomada oportunamente para avaliação no âmbito do planejamento de 2027, "
    "observadas as disponibilidades orçamentárias."
)

DESPACHO_003728 = (
    "MINISTÉRIO DAS MULHERES\n"
    "Secretaria Nacional de Enfrentamento à Violência contra Mulheres\n\n"
    "DESPACHO\n\n"
    "Ao Gabinete da Ministra\n"
    "Assunto: Proposta de Parceria Institucional\n\n"
    "Cumprimentando-as cordialmente, em atenção ao Despacho Numerado nº 1501, "
    "que se refere à Proposta de Parceria Institucional apresentada pelo "
    "Instituto de Estudos de Gênero da Universidade Federal de Santa Catarina.\n\n"
    "Considerando que o planejamento orçamentário desta Secretaria Nacional para "
    "o exercício de 2026 já se encontra comprometido com outras atividades, "
    "sugere-se que eventual apoio que envolva recursos orçamentários seja "
    "retomado oportunamente, para avaliação no âmbito do planejamento de 2027, "
    "observadas as disponibilidades orçamentárias."
)

DESPACHO_003829 = (
    "MINISTÉRIO DAS MULHERES\n"
    "Secretaria Nacional de Autonomia Econômica e Política de Cuidados\n"
    "Diretoria de Promoção da Autonomia Econômica e Política de Cuidados\n\n"
    "DESPACHO\n\n"
    "Ao Gabinete da Secretaria Nacional de Autonomia Econômica e Política de "
    "Cuidados\n"
    "Assunto: Direitos Humanos. CIDH. Art. 41 CADH. Situação dos DH Povos e "
    "Comunidades Romanis/Ciganos.\n\n"
    "Em atenção ao Despacho de origem da Assessoria Internacional, no qual "
    "solicita informações para subsidiar a elaboração de relatório temático "
    "sobre a situação dos direitos humanos dos povos e comunidades "
    "romanis/ciganos.\n\n"
    "Encaminho, como resposta, o Despacho que informa que não apresenta "
    "manifestação de mérito sobre as matérias objeto da solicitação de subsídios."
)

# Cabeçalho com destinatário seguido de 'Assunto:' na MESMA linha de bloco:
# o 'Assunto:' não deve vazar para a coluna destino (regressão do 14021).
DESPACHO_14021 = (
    "MINISTÉRIO DAS MULHERES\nSecretaria-Executiva\n\n"
    "DESPACHO\n\n"
    "À Secretaria-Executiva\n"
    "Assunto: Regulamentação do Protocolo Não é Não por meio da Portaria "
    "Interministerial MMULHERES/MJSP nº 121.\n\n"
    "Encaminho o presente processo para análise e providências."
)

# Despacho com o campo `Destino:` que o SEI imprime (regressão real
# 21260.000680/2025-37): sem `À/Ao`, o timbrado vencia e o destino saía
# "Secretaria" em vez da unidade endereçada (ASCOM).
DESPACHO_000680 = (
    "MINISTÉRIO DAS MULHERES\n"
    "Secretaria-Executiva\n"
    "Subsecretaria de Gestão e Administração\n"
    "Coordenação-Geral de Gestão Estratégica\n"
    "Coordenação de Governança, Prestação de Contas e Planejamento Estratégico\n\n"
    "DESPACHO Nº 16/2026/CGPCE/CGGE/SGA/SE-MMULHERES\n\n"
    "Processo nº 21260.000680/2025-37\n\n"
    "Destino: \n"
    "Assessoria Especial de Comunicação Social - ASCOM\n\n"
    "Assunto\n:\n"
    " Publicação de currículos - Seção \"Quem é Quem\" no portal "
    "institucional.\n\n"
    "Em atenção às diretrizes de transparência ativa e ao prazo estabelecido "
    "pelo Ministério da Gestão e da Inovação, informamos que já foram "
    "recebidos e anexados a este processo parte dos currículos dos "
    "ocupantes de cargos em comissão e funções de confiança deste Ministério."
)

# Termo de Encerramento (regressão real 21260.001106/2026-87): caía na regra
# de unidade interna e virava "Em Assessoria", nome do cargo da signatária.
DESPACHO_001106 = (
    "MINISTÉRIO DAS MULHERES\n"
    "Assessoria Especial de Controle Interno\n\n"
    "DESPACHO\n\n"
    "Termo de Encerramento de Processo\n\n"
    "Considerando que este processo cumpriu seu objetivo, procedo ao seu "
    "encerramento.\n\n"
    "Brasília, na data da assinatura.\n\n"
    "assinado digitalmente\n"
    "ANA CAROLINA SANTANA MOREIRA\n"
    "Assessora Técnica\n"
    "Assessoria Especial de Controle Interno - AECI\n"
    "Documento assinado eletronicamente por \n"
    "Ana Carolina Santana Moreira\n"
    ", \n"
    "Assessor(a) Técnico(a)\n"
    ", em\n"
    "20/07/2026, às 12:49, conforme horário oficial de Brasília, com "
    "fundamento no § 3º do art. 4º do Decreto nº 10.543, de 13 de "
    "novembro de 2020\n"
    ".\n"
    "A autenticidade deste documento pode ser conferida no site\n"
    "https://colaboragov.sei.gov.br/sei/controlador/"
)


# Regressão real 12804.000290/2026-62: a extração do PDF quebrou a linha do
# horário da assinatura de modo que ela COMEÇA com "às 12:32". O motor
# procurava o destinatário ANTES de cortar o bloco de assinatura, então
# `_RECIPIENT_LINE` casava com esse "às" e a assinatura inteira virava
# destinatário. O despacho não tem cabeçalho `Ao/À`, só `Assunto:` — o correto
# é destino vazio, nunca o texto da assinatura.
DESPACHO_SEM_DESTINATARIO_HORARIO_NA_ASSINATURA = (
    "MINISTÉRIO DAS MULHERES\n"
    "Secretaria-Executiva\n"
    "Subsecretaria de Gestão e Administração\n"
    "Coordenação-Geral de Administração e Orçamento\n"
    "Coordenação de Patrimônio e Serviços Gerais\n\n"
    "DESPACHO Nº 92/2026/CPSG/CGAO/SGA/SE-MMULHERES\n\n"
    "Processo nº 21260.001108/2025-95\n\n"
    "Assunto: Recebimento de bens no SIADS\n\n"
    "Informamos que os bens foram devidamente recebidos pelo Ministério das "
    "Mulheres, conforme consta nos termos de transferência nº ( 59640250 ) e "
    "( 60470909 ), e foram recebidos pela Coordenação de Patrimônio e Serviços "
    "Gerais (CPSG), conforme registrado nas Notas de Lançamentos.\n\n"
    "Atenciosamente,\n\n"
    "DHEYMESON BIDÓ DE LIMA\n"
    "Coordenador de Patrimônio e Serviços Gerais\n"
    "MMULHERES-SE-SGA-CGAO-CPSG\n\n"
    "Documento assinado eletronicamente por \n"
    "Dheymeson Bido de Lima\n"
    ", \n"
    "Coordenador(a)\n"
    ", em 17/04/2026,\n"
    "às 12:32, conforme horário oficial de Brasília, com fundamento no § 3º "
    "do art. 4º do\n"
    "Decreto nº 10.543, de 13 de novembro de 2020\n"
    ".\n"
    "A autenticidade deste documento pode ser conferida no site\n"
    "https://colaboragov.sei.gov.br/sei/controlador_externo.php?\n"
    "acao=documento_conferir&id_orgao_acesso_externo=0\n"
    ", informando o código verificador 60531227 e o código CRC 8D8D8577\n"
    ".\n"
    "Referência: Processo nº 12804.000290/2026-62.\n"
)

# Mesmo fenômeno, mas COM destinatário no cabeçalho: aqui o horário está no
# meio da linha (`em 31/03/2026, às 09:57`), que é o caso que sempre funcionou.
# Serve para garantir que o corte da assinatura não apaga o destinatário real.
DESPACHO_COM_DESTINATARIO_HORARIO_NA_ASSINATURA = (
    "MINISTÉRIO DA GESTÃO E DA INOVAÇÃO EM SERVIÇOS PÚBLICOS\n"
    "Secretaria de Serviços Compartilhados\n"
    "Departamento de Administração e Logística\n"
    "Coordenação-Geral de Informação e Patrimônio\n"
    "Coordenação de Gestão de Almoxarifado e Patrimônio\n"
    "Divisão de Material e de Patrimônio\n\n"
    "DESPACHO\n\n"
    "Processo nº 12804.000767/2025-51\n\n"
    "Ao SEMIB.\n\n"
    "Encaminho para providências quanto à movimentação dos bens do Termo de "
    "Transferência Externa de Bens ( 59640250 ). Após a entrega, restituir o "
    "processo a esta DIMAP para demais providências.\n\n"
    "Brasília, na data de assinatura.\n\n"
    "Documento assinado eletronicamente\n"
    "MARIA DE FÁTIMA ARAUJO\n"
    "Chefe de Divisão Substituta\n\n"
    "Documento assinado eletronicamente por \n"
    "Maria de Fátima Araújo\n"
    ", \n"
    "Chefe(a) de Divisão\n"
    "Substituto(a)\n"
    ", em 31/03/2026, às 09:57, conforme horário oficial de Brasília, com "
    "fundamento no § 3º\n"
    "do art. 4º do \n"
    "Decreto nº 10.543, de 13 de novembro de 2020\n"
    ".\n"
    "A autenticidade deste documento pode ser conferida no site\n"
    "https://colaboragov.sei.gov.br/sei/controlador_externo.php?\n"
    "acao=documento_conferir&id_orgao_acesso_externo=0\n"
    ", informando o código verificador 59640583 e o código CRC 8E3E37F5\n"
    ".\n"
)


class HorarioDaAssinaturaNaoViraDestinoTest(unittest.TestCase):
    """Regressão 12804.000290/2026-62.

    O bloco de assinatura vem no fim e é cortado, mas o destinatário era
    procurado ANTES desse corte. Quando a extração quebra a linha do horário
    ("às 12:32, conforme...") no começo de uma linha, `_RECIPIENT_LINE` casa
    com o "às" e a assinatura inteira vira destinatário.
    """

    ENGINE = RulesEngine.from_file(Path("regras.json"))

    def test_horario_da_assinatura_nao_e_o_destino(self):
        r = self.ENGINE.classify(DESPACHO_SEM_DESTINATARIO_HORARIO_NA_ASSINATURA)
        # O que importa: NADA do bloco de assinatura pode aparecer no destino.
        for lixo in ("conforme horário", "autenticidade", "código CRC",
                     "verificador", "Decreto", "12:32", "assinado"):
            self.assertNotIn(lixo, r.destino)
            self.assertNotIn(lixo, r.situacao)
        # Sem cabeçalho `À/Ao`, a menção à unidade do signatário também não
        # conta como destino; o correto é não indicar destino.
        self.assertEqual(r.destino, "")

    def test_destinatario_real_continua_sendo_lido(self):
        r = self.ENGINE.classify(DESPACHO_COM_DESTINATARIO_HORARIO_NA_ASSINATURA)
        self.assertEqual(r.destino, "SEMIB")

    def test_corpo_do_despacho_nao_e_cortado_junto(self):
        """O corte da assinatura não pode engolir o corpo do despacho."""
        r = self.ENGINE.classify(DESPACHO_COM_DESTINATARIO_HORARIO_NA_ASSINATURA)
        self.assertNotEqual(r.situacao, "Em análise")

    def test_linha_de_horario_sem_marcador_de_assinatura_nao_vira_destino(self):
        """Sem o marcador "documento assinado", não há bloco a cortar.

        A linha do horário sozinha não pode ser lida como cabeçalho `À/Ao`:
        é defesa em profundidade para o caso de o PDF não trazer o marcador.
        """
        texto = (
            "DESPACHO\n\n"
            "Informamos o recebimento dos bens.\n\n"
            "às 12:32, conforme horário oficial de Brasília.\n"
        )
        r = self.ENGINE.classify(texto)
        self.assertEqual(r.destino, "")

    def test_faixa_de_unidade_do_signatario_nao_vira_destino(self):
        """Nome/cargo/faixa de unidade vêm depois de "Atenciosamente,".

        A faixa `MMULHERES-SE-SGA-CGAO-CPSG` traz a sigla `SGA`, que a regra
        genérica de unidade leria como destino se o bloco da assinatura não
        fosse cortado a partir da saudação de fecho.
        """
        texto = (
            "DESPACHO\n\n"
            "Informamos o recebimento dos bens.\n\n"
            "Atenciosamente,\n\n"
            "FULANO DE TAL\n"
            "Coordenador\n"
            "MMULHERES-SE-SGA-CGAO-CPSG\n"
        )
        r = self.ENGINE.classify(texto)
        self.assertEqual(r.destino, "")