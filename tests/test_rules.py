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