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
    r"(?m)^[ \t]*(?:Aos|Ao|Às|À)\s+(?!\d{1,2}:\d{2})", re.IGNORECASE
)
_DESTINO_FIELD = re.compile(
    r"^[ \t]*(?:Destino|Destinat[áa]rio)[ \t]*[:.]?[ \t]*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
# O bloco de assinatura vem sempre no fim: do primeiro marcador até o final não
# há conteúdo do despacho (cargo/unidade da signatária não é destinatário).
# A saudação de fecho entra como marcador porque o nome/cargo/faixa de unidade
# do signatário vêm DEPOIS dela e ANTES do "Documento assinado eletronicamente";
# sem isso a faixa de unidade ("MMULHERES-SE-SGA-CGAO-CPSG") ficava no corpo e
# a regra de sigla a lia como destino (regressão 12804.000290/2026-62).
_SIGNATURE_START = re.compile(
    r"^\s*(?:assinado digitalmente|"
    r"documento assinado eletronicamente|documento assinado por|"
    r"atenciosamente\b|respeitosamente\b|"
    r"a autenticidade deste documento)",
    re.IGNORECASE,
)
_DESTINO_PLACEHOLDER = "{destino}"
DESTINO_DESCONHECIDO = "(destino não identificado)"
# separador dos destinatários quando o cabeçalho endereça mais de uma unidade
DESTINATARIOS_SEP = "; "
_LETTERHEAD_LINE = re.compile(
    r"^(?:MINIST[ÉE]RIO|SECRETARIA|SUBSECRETARIA|DIRETORIA|COORDENA[ÇC][ÃA]O|"
    r"GABINETE|ASSESSORIA|DIVIS[ÃA]O|N[ÚU]CLEO|DEPARTAMENTO|"
    r"SUPERINTEND[ÊE]NCIA|FUNDA[ÇC][ÃA]O)\b",
    re.IGNORECASE,
)
# Menção à própria unidade no corpo ("nesta/desta/dessa Assessoria Especial de
# Controle Interno") resolve a unidade do timbrado quando não há cabeçalho.
_PROPRIA_UNIDADE = re.compile(
    r"\b(?:nest[ae]|ness[ae]|dest[ae]|dess[ae])\s+"
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\-]{2,80}?)"
    r"(?=[,.;:)\n]|\s+(?:para|a fim|com|que)\b|$)"
)


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]


def _is_letterhead(para: str) -> bool:
    """Diz se o parágrafo é só o timbrado (linhas que começam com órgão/unidade).

    Timbrados reais podem ser longos (o timbrado do MGI tem 6 linhas:
    Ministério, Secretaria, Diretoria, Coordenação-Geral, Coordenação e
    Divisão) e costumam vir colados no 'DESPACHO' sem linha em branco, por
    isso as linhas de metadados são ignoradas no teste; parágrafos de corpo
    não são TODOS de unidade/órgão. Sem isso, um timbrado de 6 linhas era
    lido como corpo e alimentava a regra de unidade interna (falso
    "Em Secretaria").
    """
    lines = [
        ln for ln in para.splitlines()
        if ln.strip() and not _META_PARAGRAPH.match(ln)
    ]
    if not lines:
        return False
    return all(_LETTERHEAD_LINE.match(ln) for ln in lines)


def _trim_trailing_labels(resto: str) -> str:
    # Vocativo de corpo ("Senhores Fiscais ...") pode vir na mesma linha do
    # destinatário (regressão 12804.002713/2025-06) e não é destino: corta a
    # partir dele em vez de deixá-lo grudado na unidade.
    resto = re.split(
        r",?\s+(?=(?:senhor(?:es|a|as)?|prezad[oa]s?|caros?|ilmo|ilma)\b)",
        resto, maxsplit=1, flags=re.IGNORECASE,
    )[0]
    return re.sub(r"\s+", " ", resto).strip(" \t.,;:")


def _recipient_from_paragraph(para: str) -> str:
    m = _RECIPIENT_LINE.search(para)
    if not m:
        return ""
    resto = para[m.end():]
    resto = re.split(
        r"\b(?:C/c|Cc|Assunto|Refer[êe]ncia)\s*[:.]", resto,
        maxsplit=1, flags=re.IGNORECASE,
    )[0]
    # Despachos com mais de um destinatário trazem várias linhas `À ...`;
    # sem esta quebra elas viravam uma frase só, com os `À` do meio e o
    # assunto grudados no destino (regressão 12804.000730/2026-75).
    partes = [_trim_trailing_labels(p) for p in _RECIPIENT_LINE.split(resto)]
    return DESTINATARIOS_SEP.join(p for p in partes if p)


def _split_body(text: str, conhece_unidade=None) -> tuple[str, str]:
    paras = _paragraphs(text)
    # O bloco de assinatura vem sempre no fim e é cortado ANTES de procurar o
    # destinatário. O destinatário era procurado primeiro, e a linha do
    # horário da assinatura ("às 12:32, conforme horário oficial...") começa
    # com "às" — `_RECIPIENT_LINE` casava com ela e a assinatura INTEIRA virava
    # destinatário (regressão 12804.000290/2026-62). Como o bloco não tem
    # conteúdo de despacho, tirá-lo do caminho primeiro não perde cabeçalho
    # válido: o cabeçalho `À/Ao` é anterior à assinatura.
    sig_idx = next(
        (i for i, p in enumerate(paras) if _SIGNATURE_START.match(p)), None
    )
    if sig_idx is not None:
        paras = paras[:sig_idx]
    # Precedência: campo `Destino:` (rótulo explícito do SEI) > linha
    # `À/Ao/Aos/Às`. Sem os dois, o corpo começa depois do timbrado.
    field_idx = next((i for i, p in enumerate(paras) if _DESTINO_FIELD.match(p)), None)
    line_idx = next((i for i, p in enumerate(paras) if _RECIPIENT_LINE.search(p)), None)
    if field_idx is not None:
        recip_idx = field_idx
        resto = _DESTINO_FIELD.match(paras[field_idx]).group(1)
        resto = re.split(
            r"\b(?:C/c|Cc|Assunto|Processo\s*n)\s*[:.]", resto,
            maxsplit=1, flags=re.IGNORECASE,
        )[0]
        recipient = _trim_trailing_labels(resto)
    elif line_idx is not None:
        recip_idx = line_idx
        recipient = _recipient_from_paragraph(paras[line_idx])
    else:
        recip_idx = None
        recipient = ""
    start = recip_idx + 1 if recip_idx is not None else 0
    if recip_idx is None:
        while start < len(paras) and _is_letterhead(paras[start]):
            start += 1
        # Metadados do cabeçalho (DESPACHO, Processo, Brasília, ...) também não
        # são corpo; pulá-los permite ler a linha de unidade que os sucede.
        while start < len(paras) and _META_PARAGRAPH.match(paras[start]):
            start += 1
        if (
            conhece_unidade is not None
            and start < len(paras)
            and conhece_unidade(paras[start])
        ):
            recipient = paras[start]
            start += 1
    body = [p for p in paras[start:] if not _META_PARAGRAPH.match(p)]
    return recipient, " ".join(re.sub(r"\s+", " ", p) for p in body)


def _parece_sigla(destino: str) -> bool:
    """Destino curto escrito só com maiúsculas (sigla), não nome por extenso.

    Só um cabeçalho assim fraseia a situação quando nenhuma regra casa: nome
    por extenso pode ser ruidoso (linha de timbrado, frase inteira) e não deve
    virar `Em <frase>`.
    """
    return 0 < len(destino) <= 80 and destino == destino.upper()


def _expand_destino(valor: str, destino: str) -> str:
    """Substitui `{destino}` pelo destinatário LITERAL já resolvido.

    A troca é literal (não regex): um `\\1` que faça parte do nome do
    destinatário não pode virar backreference na situação. Sem destino
    conhecido, usa rótulo explícito em vez de deixar a frase quebrada.
    """
    if _DESTINO_PLACEHOLDER not in valor:
        return valor
    return valor.replace(
        _DESTINO_PLACEHOLDER, destino or DESTINO_DESCONHECIDO
    )


# Substantivo de unidade sem qualificador não identifica QUEM recebeu
# ("Em Secretaria": qual secretaria?). Vocativo de corpo ("Aos Senhores
# Fiscais ...") e rótulo de documento ("Portaria nº ...") também não são
# destino. O que não identifica sai; nada é inferido.
_DESTINO_VAGO = {
    "secretaria", "subsecretaria", "coordenacao", "coordenacao geral",
    "coordenacao-geral", "diretoria", "superintendencia", "gerencia",
    "assessoria", "nucleo", "divisao", "departamento", "gabinete",
    "setor", "secao", "servico", "unidade", "area", "orgao",
}
_DESTINO_CONECTORES = {"e", "ou", "e ou"}
_DESTINO_VOCATIVO = re.compile(
    r"^(?:senhor(?:es|a|as)?|prezad[oa]s?|ilmo|ilma|caros?)\b", re.IGNORECASE
)
_DESTINO_DOCUMENTO = re.compile(
    r"^(?:portaria|of[ií]cio|processo|despacho|memorando|nota|requerimento|"
    r"documento|contrato|edital)\b",
    re.IGNORECASE,
)


def _destino_concreto(destino: str) -> str:
    """Mantém só as partes do destino que identificam uma unidade concreta.

    Descarta substantivo solto ("Secretaria"), vocativo ("Senhores ..."),
    rótulo de documento ("Portaria nº ...") e conectivo de lista ("e"). Se
    nada sobrar, o chamador cai no fallback; nada é inferido.
    """
    if not destino:
        return ""
    partes = []
    for parte in destino.split(DESTINATARIOS_SEP):
        p = parte.strip()
        folded = _fold(p)
        if not p or folded in _DESTINO_VAGO or folded in _DESTINO_CONECTORES:
            continue
        if _DESTINO_VOCATIVO.match(p) or _DESTINO_DOCUMENTO.match(p):
            continue
        partes.append(p)
    return DESTINATARIOS_SEP.join(partes)


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

    def _sigla_por_nome_inteiro(self, nome: str) -> str:
        """Sigla do mapa `siglas` para o nome INTEIRO (comparação normalizada)."""
        low = _fold(nome)
        for chave, sigla in self.siglas.items():
            if low == _fold(chave):
                return sigla
        return ""

    def normalize_recipient(self, recip: str) -> str:
        """Reduz o destinatário a sigla conhecida (equivalência do nome inteiro
        com o mapa), a uma sigla citada como '(SIGLA)' ou após travessão, ou
        mantém o nome por extenso. 'Gabinete da Secretaria-Executiva' NÃO vira
        SE porque o nome inteiro não casa com o mapa."""
        sigla = self._sigla_por_nome_inteiro(recip)
        if sigla:
            return sigla
        # Nome por extenso + código de memória do SEI
        # ("Coordenação-Geral de Tecnologia da Informação - CGTI/MMULHERES",
        # regressão 21260.001552/2026-91): o `/MMULHERES` quebra a igualdade
        # do nome inteiro e a sigla deixa de estar no fim da linha. Descarta
        # o sufixo e compara o nome de novo, sem inventar sigla.
        base = re.sub(r"\s+[–-]\s+.*$", "", recip).strip()
        if base and base != recip:
            sigla = self._sigla_por_nome_inteiro(base)
            if sigla:
                return sigla
            # Código de unidade seguido do nome por extenso
            # ("MMULHERES-SE-SGA-CGTI - COORDENAÇÃO-GERAL DE TECNOLOGIA DA
            # INFORMAÇÃO"): reduz o código pela sigla final, como já se faz
            # quando o código vem sozinho.
            m = re.search(r"[–-]\s*([A-ZÀ-Ÿ]{2,})\s*$", base)
            if m:
                return m.group(1)
        m = re.search(r"\(\s*([A-ZÀ-Ÿ]{2,})\s*\)", recip)
        if m:
            return m.group(1)
        m = re.search(r"[–-]\s*([A-ZÀ-Ÿ]{2,})\s*$", recip)
        if m:
            return m.group(1)
        return recip

    def normalize_recipients(self, recipient: str) -> str:
        """Aplica `normalize_recipient` a CADA destinatário e reagrupa.

        Um cabeçalho pode endereçar mais de uma unidade (regressão
        21260.001018/2026-85: "... Gerais - CPSG" e "... Logística - CCL").
        Reduzir a célula inteira faria o corte de sufixo pegar o segundo
        destinatário e o primeiro sumir da linha.
        """
        if not recipient:
            return ""
        partes = (self.normalize_recipient(p) for p in recipient.split(DESTINATARIOS_SEP))
        return DESTINATARIOS_SEP.join(p for p in partes if p)

    def _conhece_unidade_linha(self, para: str) -> bool:
        """Linha isolada de unidade logo após o cabeçalho (ex.: a
        `Subsecretaria de Gestão e Administração` que o SEI repete antes do
        corpo). Só vale se o nome inteiro casa com o mapa `siglas` ou se traz
        a sigla explícita — nunca um parágrafo de corpo."""
        p = para.strip()
        if not p or "\n" in p or len(p) > 120 or p.endswith("."):
            return False
        if self._sigla_por_nome_inteiro(p):
            return True
        return bool(
            _LETTERHEAD_LINE.match(p)
            and re.search(r"(?:[–-]\s*|\(\s*)[A-ZÀ-Ÿ]{2,}\s*\)?\s*$", p)
        )

    def _unidade_propria(self, body: str) -> str:
        """Unidade do próprio timbrado citada no corpo ("nesta/dessa ..."),
        resolvida pelo mapa `siglas`. Sem correspondência, não é destino."""
        m = _PROPRIA_UNIDADE.search(body)
        if not m:
            return ""
        nome = re.sub(r"\s+", " ", m.group(1)).strip()
        if self._sigla_por_nome_inteiro(nome):
            return nome
        # O trecho pode continuar além do nome da unidade (ex.: "... e a
        # Coordenação X"); aceita a chave do mapa que o inicia.
        low = _fold(nome)
        melhor, melhor_len = "", 0
        for chave in self.siglas:
            fc = _fold(chave)
            if fc and low.startswith(fc) and len(fc) > melhor_len:
                melhor, melhor_len = chave, len(fc)
        return melhor

    def classify(self, text: str) -> RuleResult:
        recipient, body = _split_body(text, self._conhece_unidade_linha)
        if not recipient:
            recipient = self._unidade_propria(body)
        destino_cabecalho = self.normalize_recipients(recipient)
        header_concreto = _destino_concreto(destino_cabecalho)
        normalized = re.sub(r"\s+", " ", body).strip()
        result = RuleResult(**self.fallback)
        matched = False
        terminal = False
        fraseia_cabecalho: Optional[dict] = None
        for rule in self.rules:
            if rule.get("requer_sem_cabecalho") and header_concreto:
                # Citação a órgão externo em código de documento/URL só vale
                # quando não há cabeçalho interno que mande: o cabeçalho
                # endereça a unidade e não pode ser contradito por uma menção
                # de passagem (diretriz: cabeçalho interno vence).
                continue
            if rule.get("fraseia_cabecalho") and _parece_sigla(destino_cabecalho):
                # Com cabeçalho de sigla limpa o destino já veio dele e a regra
                # só fraseia a situação ("Em {destino}"). Não decide na hora:
                # guarda para o fim, deixando uma menção real a órgão externo
                # (regra posterior) ter precedência.
                fraseia_cabecalho = rule
            restrito = rule.get("pattern_sem_cabecalho")
            if restrito and not destino_cabecalho:
                # Sem cabeçalho, a regra genérica de unidade fica mais estrita:
                # menção a nome completo ("Coordenação de ...") não é destino.
                # Se nem o padrão estrito casar, a regra genérica "reconhece" a
                # unidade mas a rejeita como destino: para aqui no fallback, em
                # vez de deixar regras posteriores (ex.: órgão externo) casarem
                # boilerplate/título do documento (regressão 12804.000815/2026-60).
                if re.search(restrito, normalized, re.IGNORECASE) is None:
                    if re.search(rule["pattern"], normalized, re.IGNORECASE):
                        result = RuleResult(**self.fallback)
                        break
                    continue
                m = re.search(restrito, normalized, re.IGNORECASE)
            else:
                # Com cabeçalho o destino já vem dele e a regra só fraseia a
                # situação ("Em {destino}"), então o padrão largo continua.
                m = re.search(rule["pattern"], normalized, re.IGNORECASE)
            if m:
                def sub(val: str) -> str:
                    try:
                        expandido = m.expand(val)
                    except (re.error, IndexError):
                        return ""
                    if rule.get("upper_captura") and m.lastindex:
                        # Sigla de órgão externo citada em minúsculas
                        # (domínio 'supersapiens.agu.gov.br') volta canônica:
                        # 'agu' -> 'AGU'. Frases com espaço não são tocadas.
                        capturado = m.group(1) or ""
                        if capturado and " " not in capturado:
                            expandido = expandido.replace(capturado, capturado.upper())
                    return expandido
                result = RuleResult(
                    situacao=sub(rule.get("situacao", self.fallback["situacao"])),
                    destino=sub(rule.get("destino", "")),
                    acao_esperada=sub(rule.get("acao_esperada", "")),
                    pendencia_curta=sub(rule.get("pendencia_curta", "")),
                )
                matched = True
                terminal = bool(rule.get("terminal"))
                break
        if not matched and fraseia_cabecalho is not None:
            result = RuleResult(
                situacao=fraseia_cabecalho.get("situacao", self.fallback["situacao"]),
                destino=fraseia_cabecalho.get("destino", ""),
                acao_esperada=fraseia_cabecalho.get("acao_esperada", ""),
                pendencia_curta=fraseia_cabecalho.get("pendencia_curta", ""),
            )
        if destino_cabecalho and not terminal:
            # Arquivamento/encerramento é situação terminal: dispensa destino
            # (direto), então o cabeçalho não o preenche.
            result.destino = destino_cabecalho
        concreto = _destino_concreto(result.destino)
        if result.destino and not concreto:
            # O destino só tinha termo vago/vocativo/rótulo de documento: não
            # há unidade a afirmar. Volta ao fallback ("Verificar manualmente").
            result = RuleResult(**self.fallback)
        result.destino = concreto
        # `{destino}` expande com o destinatário EFETIVO (cabeçalho tem
        # precedência sobre o capturado pela regra) para a situação dizer DE
        # QUEM é o trabalho.
        effective = result.destino or DESTINO_DESCONHECIDO
        result = RuleResult(
            situacao=_expand_destino(result.situacao, effective),
            destino=result.destino,
            acao_esperada=_expand_destino(result.acao_esperada, effective),
            pendencia_curta=_expand_destino(result.pendencia_curta, effective),
        )
        return result