import unittest
from pathlib import Path

from sei_insights.rules import RulesEngine

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