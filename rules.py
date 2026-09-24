from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(slots=True)
class RuleResult:
    situacao: str
    destino: str
    acao_esperada: str
    pendencia_curta: str


class RulesEngine:
    def __init__(self, config: Optional[dict] = None) -> None:
        if isinstance(config, list):
            self.config = {"regras": config}
        else:
            self.config = config or {}
        self.rules = self.config.get("regras", [])
        self.fallback = self.config.get(
            "fallback",
            {"situacao": "Em análise", "destino": "",
             "acao_esperada": "", "pendencia_curta": ""},
        )

    @classmethod
    def from_file(cls, path: Path) -> "RulesEngine":
        with path.open(encoding="utf-8") as fh:
            return cls(json.load(fh))

    def classify(self, text: str) -> RuleResult:
        normalized = re.sub(r"\s+", " ", text)
        for rule in self.rules:
            m = re.search(rule["pattern"], normalized, re.IGNORECASE)
            if m:
                def sub(val: str) -> str:
                    try:
                        return m.expand(val)
                    except (re.error, IndexError):
                        return ""
                destino = sub(rule.get("destino", ""))
                return RuleResult(
                    situacao=sub(rule.get("situacao", self.fallback["situacao"])),
                    destino=destino,
                    acao_esperada=sub(rule.get("acao_esperada", "")),
                    pendencia_curta=sub(rule.get("pendencia_curta", "")),
                )
        return RuleResult(**self.fallback)