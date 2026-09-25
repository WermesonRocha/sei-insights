from pathlib import Path

STATE_DIR = Path(".state")
DATABASE_PATH = STATE_DIR / "sei_insights.sqlite3"
REGRAS_JSON = Path("regras.json")

DEFAULT_ORGAO = "MMulheres"
DEFAULT_UNIDADE = "MMULHERES-SE-SGA-CGATI-CTI-DTI"
DEFAULT_DIAS = 7
DEFAULT_MIN_DELAY = 2.0
DEFAULT_MAX_DELAY = 5.0
DEFAULT_SAIDA = "sei_insights.xlsx"

DEFAULT_TIMEOUT_MS = 90_000
