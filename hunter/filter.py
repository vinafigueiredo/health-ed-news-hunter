"""
Filtro de keyword em três níveis (STRONG / CASED / CONTEXT).

É o gate BARATO: roda em todo artigo coletado, sem custo de rede nem de IA.
O que passa daqui vai para o gate CARO (hunter/relevance.py, LLM).

Princípio herdado do pipeline de referência: colete tudo de forma robusta e
filtre DEPOIS — nunca conserte notícia a notícia.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache

from .config import (
    CASED_KEYWORDS,
    CONTEXT_KEYWORDS,
    CONTEXT_MARKERS,
    TITLE_BLOCKLIST,
    all_keywords,
)

log = logging.getLogger(__name__)

# ── Blocklist de título ───────────────────────────────────────────────────────
# Fronteira de palavra, não substring: senão "bbb" casaria dentro de outra
# palavra e "gol de" pegaria "gole de".
_BLOCK_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(
        re.escape(w) for w in sorted(TITLE_BLOCKLIST, key=len, reverse=True)
    ) + r")(?!\w)",
    re.IGNORECASE,
)

# ── Página-índice: títulos que são navegação, não notícia ─────────────────────
_PAGE_INDEX_PATTERNS = [
    re.compile(r"^(últimas notícias|ultimas noticias|vídeos|videos|home|notícias|noticias|colunas)\b", re.I),
    re.compile(r"^(ações hoje|cotações|bolsa hoje|agenda do dia)\b", re.I),
    re.compile(r"^[A-Z]{2,5}\s*\|\s*[A-Z]{4,5}\d?\b"),
    re.compile(r"\-\s*(Valor Econômico|Estadão|Folha de S\.Paulo|UOL)\s*$", re.I),
]


def _is_page_index(title: str) -> bool:
    if not title or len(title) < 15:
        return True
    if title.count(" ") < 2:
        return True
    return any(p.search(title) for p in _PAGE_INDEX_PATTERNS)


# ── STRONG: case-insensitive, fronteira de palavra ────────────────────────────
@lru_cache(maxsize=1)
def _strong_re() -> re.Pattern:
    kws = [k for k in all_keywords()
           if k.lower() not in CASED_KEYWORDS and k not in CONTEXT_KEYWORDS]
    # mais longas primeiro: "Rede D'Or São Luiz" antes de "Rede D'Or"
    escaped = [re.escape(k) for k in sorted(kws, key=len, reverse=True)]
    return re.compile(r"(?<!\w)(?:" + "|".join(escaped) + r")(?!\w)", re.IGNORECASE)


# ── CASED: só as formas capitalizadas listadas ────────────────────────────────
@lru_cache(maxsize=1)
def _cased_re() -> re.Pattern:
    forms = [f for variants in CASED_KEYWORDS.values() for f in variants]
    escaped = [re.escape(f) for f in sorted(forms, key=len, reverse=True)]
    return re.compile(r"(?<!\w)(?:" + "|".join(escaped) + r")(?!\w)")  # SEM IGNORECASE


# ── CONTEXT: termo + marcador de contexto do setor no mesmo texto ─────────────
@lru_cache(maxsize=None)
def _context_term_re(term: str) -> re.Pattern:
    # Nome próprio (começa com maiúscula) → exige a forma capitalizada.
    # Termo genérico ("reajuste") → case-insensitive.
    flags = 0 if term[:1].isupper() else re.IGNORECASE
    return re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", flags)


@lru_cache(maxsize=None)
def _marker_re(domain: str) -> re.Pattern:
    markers = CONTEXT_MARKERS[domain]
    escaped = [re.escape(m) for m in sorted(markers, key=len, reverse=True)]
    return re.compile(r"(?<!\w)(?:" + "|".join(escaped) + r")(?!\w)", re.IGNORECASE)


def _has_context(text: str, domain: str) -> bool:
    if domain == "ambos":
        return _marker_re("saude").search(text) or _marker_re("educacao").search(text)
    return bool(_marker_re(domain).search(text))


# ── API ───────────────────────────────────────────────────────────────────────
def match_keywords(text: str) -> list[str]:
    """Keywords que batem no texto, nos três níveis. Retorna lista ordenada."""
    if not text:
        return []
    found: set[str] = set()

    for m in _strong_re().finditer(text):
        found.add(m.group(0).lower())

    for m in _cased_re().finditer(text):
        found.add(m.group(0).lower())

    for term, domain in CONTEXT_KEYWORDS.items():
        if _context_term_re(term).search(text) and _has_context(text, domain):
            found.add(term.lower())

    return sorted(found)


def _to_dict(art, matched: list[str]) -> dict:
    return {
        "url":              art.url,
        "domain":           art.domain,
        "source_name":      art.source_name,
        "title":            art.title,
        "snippet":          art.snippet,
        "published_at":     art.published_at.isoformat() if art.published_at else None,
        "found_at":         art.found_at.isoformat(),
        "matched_keywords": matched,
    }


# ── Serialização por unidade federativa ──────────────────────────────────────
# O MEC publica a MESMA matéria uma vez por estado: em 03/ago/2026 entraram 14
# linhas "Fies 2026: <estado> registrou X mil inscritos no segundo semestre" —
# 26% do feed daquele dia. O gate de LLM não resolve: ele julga em lotes de 12 e
# nunca vê as 14 juntas, e cada uma isolada É relevante.
#
# Colapso por normalização determinística, não por similaridade difusa: um
# limiar de Jaccard mal calibrado descarta notícia legítima, e o custo do erro
# aqui é silencioso. Tirando dígitos e o nome do estado, as 14 viram a mesma
# string exata; qualquer par que NÃO seja a mesma matéria continua diferente.
_UFS = (
    "acre", "alagoas", "amapa", "amazonas", "bahia", "ceara", "distrito federal",
    "espirito santo", "goias", "maranhao", "mato grosso do sul", "mato grosso",
    "minas gerais", "para", "paraiba", "parana", "pernambuco", "piaui",
    "rio grande do norte", "rio grande do sul", "rio de janeiro", "rondonia",
    "roraima", "santa catarina", "sao paulo", "sergipe", "tocantins",
)
_UF_RE = re.compile(r"(?<!\w)(?:" + "|".join(sorted(_UFS, key=len, reverse=True)) + r")(?!\w)")


# Palavra de magnitude é parte do número, não do assunto. Sem isto, "Roraima
# registrou 212 inscritos" não agrupa com "São Paulo registrou 17,9 mil
# inscritos" — a mesma matéria separada por um estado ter passado de mil.
_MAGNITUDE_RE = re.compile(r"(?<!\w)(?:mil|milhao|milhoes|bilhao|bilhoes|milhar|milhares)(?!\w)")


def _sem_acento(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn"
    )


def _serial_key(title: str) -> str:
    base = _sem_acento(title)
    base = _UF_RE.sub(" ", base)
    base = re.sub(r"[\d.,%/º°ª-]+", " ", base)
    base = _MAGNITUDE_RE.sub(" ", base)
    return " ".join(base.split())


def collapse_serial_articles(articles: list[dict]) -> list[dict]:
    """Mantém um representante por (fonte, matéria serializada por estado).

    Só colapsa quando há 3 ou mais no grupo: duas manchetes parecidas costumam
    ser notícias distintas; catorze são a mesma matéria repetida por UF.

    E só entra no jogo título que CONTÉM uma UF. Sem essa trava, o colapso
    engolia 11 portarias SERES/MEC distintas — o título do DOU é só o número do
    ato ("PORTARIA SERES/MEC Nº 364, DE 29 de julho de 2026"), então tirar os
    dígitos tornava todas idênticas. Aconteceu em 03/ago/2026. A serialização
    por UF é o único padrão que este colapso existe para tratar; qualquer outra
    coincidência de template é atos diferentes com nome parecido.
    """
    grupos: dict[tuple[str, str], list[dict]] = {}
    for a in articles:
        titulo = a.get("title", "")
        if not _UF_RE.search(_sem_acento(titulo)):
            grupos[("", f"__unico__{id(a)}")] = [a]
            continue
        chave = (a.get("source_name", ""), _serial_key(titulo))
        grupos.setdefault(chave, []).append(a)

    out: list[dict] = []
    for (fonte, _), itens in grupos.items():
        if len(itens) >= 3:
            log.info("Serial colapsado [%s]: %d -> 1 | %s",
                     fonte, len(itens), itens[0].get("title", "")[:70])
            out.append(itens[0])
        else:
            out.extend(itens)

    # Preserva a ordem original de coleta.
    ordem = {id(a): i for i, a in enumerate(articles)}
    return sorted(out, key=lambda a: ordem[id(a)])


def filter_articles(articles: list) -> list[dict]:
    """
    Aplica o gate barato.

    Fontes com needs_filter=False (setoriais estreitas, órgãos oficiais) passam
    tudo — só a blocklist de título as barra. Fontes amplas (Valor, Folha, G1)
    exigem pelo menos uma keyword no título OU no resumo.
    """
    out: list[dict] = []
    for art in articles:
        title = art.title or ""

        # Blocklist vale para TODAS as fontes, inclusive as curadas.
        if _BLOCK_RE.search(title):
            continue

        if not getattr(art, "needs_filter", True):
            out.append(_to_dict(art, []))
            continue

        if _is_page_index(title):
            continue

        matched = match_keywords(f"{title} {art.snippet or ''}")
        if not matched:
            continue

        out.append(_to_dict(art, matched))

    return out
