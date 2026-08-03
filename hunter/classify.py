"""
Vertical do artigo: saúde, educação, ambas ou indefinida.

Por que existe uma coluna e não um filtro no front: o dashboard precisa separar
Saúde de Educação, e a única forma de fazer isso no cliente seria duplicar lá as
listas deste `config.py`. Duplicata desatualiza calada — toda empresa nova que
entrasse aqui sumiria do filtro de lá sem ninguém perceber. Classificar no
ingest mantém uma fonte de verdade só.

Regra:

1. Vale a vertical das keywords que casaram. Keyword de empresa/tema de saúde
   vota "saude", de educação vota "educacao". Casou nas duas → "ambos".
2. Keyword que não pertence a nenhuma lista não vota. Isso cobre tanto os termos
   neutros de M&A ("fusão", "aquisição", "CADE" — que valem para os dois setores)
   quanto keywords de versões antigas do config que ainda vivem em linhas
   gravadas no banco.
3. Sem voto nenhum → None. O front mostra esses itens só em "Tudo"; melhor um
   balde honesto de indefinidos do que chutar vertical em fato relevante.

O caso que obriga o passo 2 do `filter.py`: fonte curada (CVM, DOU, setorial
estreita) entra com `matched_keywords = []` de propósito, porque pula o gate de
keyword. São ~16% das linhas e incluem os fatos relevantes — justamente o que a
mesa mais quer filtrar. Para essas, quem chama roda o matcher só para descobrir
a vertical, sem gravar as keywords (o `[]` continua significando "passou sem
gate", e essa semântica não pode mudar).
"""

from .config import (
    SAUDE_LISTADAS,
    SAUDE_NAO_LISTADAS,
    SAUDE_REGULATORIO,
    EDUCACAO_EMPRESAS,
    EDUCACAO_REGULATORIO,
    CASED_KEYWORDS,
    CONTEXT_KEYWORDS,
)

SAUDE = "saude"
EDUCACAO = "educacao"
AMBOS = "ambos"


def _build_map() -> dict[str, str]:
    """
    keyword normalizada → vertical.

    A chave é sempre minúscula porque é assim que o `match_keywords` grava
    (`m.group(0).lower()`), e é assim que a keyword está no banco.
    """
    m: dict[str, str] = {}

    for termo in SAUDE_LISTADAS + SAUDE_NAO_LISTADAS + SAUDE_REGULATORIO:
        m[termo.lower()] = SAUDE
    for termo in EDUCACAO_EMPRESAS + EDUCACAO_REGULATORIO:
        m[termo.lower()] = EDUCACAO

    # CASED: a chave do dict já é o token minúsculo que vai para o banco.
    # "cade" fica de fora de propósito — o CADE julga ato de concentração dos
    # dois setores, então não é sinal de vertical nenhuma.
    m.update({
        "ans":     SAUDE,
        "nip":     SAUDE,
        "mec":     EDUCACAO,
        "inep":    EDUCACAO,
        "ead":     EDUCACAO,
        "seres":   EDUCACAO,
        "uninter": EDUCACAO,
    })

    # CONTEXT já declara a vertical no próprio config — é a mesma pergunta
    # ("de que setor é este termo ambíguo?"), então reaproveita a resposta.
    for termo, dominio in CONTEXT_KEYWORDS.items():
        m[termo.lower()] = dominio

    return m


_VERTICAL_BY_KW = _build_map()

# Sanidade: se alguém apagar uma lista do config, o mapa esvazia e TODO artigo
# vira indefinido — falha silenciosa, o pior tipo. Melhor estourar no import.
assert len(_VERTICAL_BY_KW) > 100, (
    f"mapa de verticais com apenas {len(_VERTICAL_BY_KW)} termos — "
    "alguma lista do config.py sumiu?"
)


def vertical_de_keywords(keywords) -> str | None:
    """Vertical a partir de uma lista de keywords já casadas. None se indefinida."""
    if not keywords:
        return None

    votos = set()
    for kw in keywords:
        v = _VERTICAL_BY_KW.get(str(kw).lower())
        if v == AMBOS:
            votos.update((SAUDE, EDUCACAO))
        elif v:
            votos.add(v)

    if len(votos) == 2:
        return AMBOS
    if votos:
        return votos.pop()
    return None
