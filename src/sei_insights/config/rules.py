from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(slots=True)
class RuleResult:
    situacao: str
    destino: str
    acao_esperada: str
    pendencia_curta: str


_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n[ \t]*")


def _fold(text: str) -> str:
    """Normaliza nome p/ comparação: minúsculas, sem acentos, hífens/espaços
    equivalentes ('Secretaria-Executiva' == 'secretaria executiva')."""
    nfkd = unicodedata.normalize("NFD", text)
    sem_acentos = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    return re.sub(r"\W+", " ", sem_acentos).strip().casefold()
_META_PARAGRAPH = re.compile(
    r"^\s*(?:Processo\s*n[º°]?|Assunto[:.]?|C/c|Cc[:.]?|DESPACHO|"
    r"Documento assinado|Refer[êe]ncia[:]?|SEI\s*n|Decreto\s*n|"
    r"A autenticidade|Bras[íi]lia[,]?|Despacho\s*(?:Numerado\s*)?\d)",
    re.IGNORECASE,
)
_RECIPIENT_LINE = re.compile(
    r"(?m)^[ \t]*(?:Aos|Ao|Às|À)\s+", re.IGNORECASE
)
_LETTERHEAD_LINE = re.compile(
    r"^(?:MINIST[ÉE]RIO|SECRETARIA|SUBSECRETARIA|DIRETORIA|COORDENA[ÇC][ÃA]O|"
    r"GABINETE|ASSESSORIA|DIVIS[ÃA]O|N[ÚU]CLEO|DEPARTAMENTO|"
    r"SUPERINTEND[ÊE]NCIA|FUNDA[ÇC][ÃA]O)\b",
    re.IGNORECASE,
)


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]


def _is_letterhead(para: str) -> bool:
    """Diz se o parágrafo é só o timbrado (linhas que começam com órgão/unidade).

    Timbrados reais têm 1-3 linhas (ex.: "MINISTÉRIO DAS MULHERES" acima de
    "Secretaria Nacional de ..."); parágrafos de corpo não são todos de
    unidade/órgão. Isso evita que palavras do papel de fundo alimentem regras
    (falso "Em Secretaria") quando o despacho não tem linha de destinatário.
    """
    lines = [ln for ln in para.splitlines() if ln.strip()]
    if not lines or len(lines) > 3:
        return False
    return all(_LETTERHEAD_LINE.match(ln) for ln in lines)


def _recipient_from_paragraph(para: str) -> str:
    m = _RECIPIENT_LINE.search(para)
    if not m:
        return ""
    resto = para[m.end():]
    resto = re.split(
        r"\b(?:C/c|Cc|Assunto|Refer[êe]ncia)\s*[:.]", resto,
        maxsplit=1, flags=re.IGNORECASE,
    )[0]
    resto = re.sub(r"\s+", " ", resto).strip(" \t.,;:")
    return resto


def _split_body(text: str) -> tuple[str, str]:
    paras = _paragraphs(text)
    recip_idx = None
    for i, para in enumerate(paras):
        if _RECIPIENT_LINE.search(para):
            recip_idx = i
            break
    recipient = _recipient_from_paragraph(paras[recip_idx]) if recip_idx is not None else ""
    start = recip_idx + 1 if recip_idx is not None else 0
    if recip_idx is None:
        # Sem linha de destinatário, descarta o timbrado que abre o documento.
        while start < len(paras) and _is_letterhead(paras[start]):
            start += 1
    body = [p for p in paras[start:] if not _META_PARAGRAPH.match(p)]
    return recipient, " ".join(re.sub(r"\s+", " ", p) for p in body)


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
        siglas = self.config.get("siglas", {})
        self.siglas = {nome.lower(): sigla for nome, sigla in siglas.items()}

    @classmethod
    def from_file(cls, path: Path) -> "RulesEngine":
        with path.open(encoding="utf-8") as fh:
            return cls(json.load(fh))

    def normalize_recipient(self, recip: str) -> str:
        """Reduz o destinatário a sigla conhecida (equivalência do nome inteiro
        com o mapa), a uma sigla citada como '(SIGLA)' ou após travessão, ou
        mantém o nome por extenso. 'Gabinete da Secretaria-Executiva' NÃO vira
        SE porque o nome inteiro não casa com o mapa."""
        low = _fold(recip)
        for nome, sigla in self.siglas.items():
            if low == _fold(nome):
                return sigla
        m = re.search(r"\(\s*([A-ZÀ-Ÿ]{2,})\s*\)", recip)
        if m:
            return m.group(1)
        m = re.search(r"[–-]\s*([A-ZÀ-Ÿ]{2,})\s*$", recip)
        if m:
            return m.group(1)
        return recip

    def classify(self, text: str) -> RuleResult:
        recipient, body = _split_body(text)
        destino_cabecalho = self.normalize_recipient(recipient) if recipient else ""
        normalized = re.sub(r"\s+", " ", body).strip()
        result = RuleResult(**self.fallback)
        for rule in self.rules:
            m = re.search(rule["pattern"], normalized, re.IGNORECASE)
            if m:
                def sub(val: str) -> str:
                    try:
                        return m.expand(val)
                    except (re.error, IndexError):
                        return ""
                result = RuleResult(
                    situacao=sub(rule.get("situacao", self.fallback["situacao"])),
                    destino=sub(rule.get("destino", "")),
                    acao_esperada=sub(rule.get("acao_esperada", "")),
                    pendencia_curta=sub(rule.get("pendencia_curta", "")),
                )
                break
        if destino_cabecalho:
            result.destino = destino_cabecalho
        return result