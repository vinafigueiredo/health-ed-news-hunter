"""
Universo de cobertura do Health & Education News Hunter.

ESTE É O ARQUIVO QUE MAIS MUDA. É aqui que se adiciona/remove empresa,
ticker, tema regulatório. Nada mais precisa ser tocado para ajustar cobertura.

Três níveis de keyword — a distinção existe para evitar falso positivo:

  STRONG   → casa case-insensitive, com fronteira de palavra.
             Use quando o termo é inequívoco ("Hapvida", "sinistralidade").

  CASED    → casa SÓ na forma capitalizada listada.
             Use quando o token minúsculo é palavra comum do português:
             "ANS" (≠ "ans"), "CADE" (≠ "cade"/"cadê"), "SERES" (≠ "seres
             humanos"), "Alice", "Sami", "Descomplica" (≠ verbo descomplicar).

  CONTEXT  → casa só se ALÉM do termo houver uma palavra de contexto do setor
             no mesmo texto. Use para termos que existem fora do setor:
             "reajuste" (salarial? de plano?), "captação" (de recursos? de
             alunos?), "Cruzeiro do Sul" (constelação? universidade?),
             "revisão técnica" (de veículo? de carteira?).

Regra prática: na dúvida, CONTEXT. O gate de relevância por LLM
(hunter/relevance.py) corta o resto; keyword frouxa demais queima cota de IA,
keyword apertada demais perde notícia e você nunca fica sabendo.
"""

# ══════════════════════════════════════════════════════════════════════════════
# SAÚDE — empresas listadas
# ══════════════════════════════════════════════════════════════════════════════
SAUDE_LISTADAS = [
    # Hapvida / NotreDame Intermédica
    "Hapvida", "HAPV3", "NotreDame Intermédica", "NotreDame Intermedica",
    "NotreDame Saúde", "Notre Dame Intermédica", "GNDI", "Intermédica",
    # Rede D'Or
    "Rede D'Or", "Rede D’Or", "Rede DOr", "RDOR3", "Rede D'Or São Luiz",
    # Fleury
    "Fleury", "FLRY3", "Grupo Fleury",
    # Oncoclínicas
    "Oncoclínicas", "Oncoclinicas", "ONCO3",
    # Mater Dei
    "Mater Dei", "MATD3", "Rede Mater Dei",
    # Dasa
    "Dasa", "DASA3", "Diagnósticos da América",
    # Qualicorp
    "Qualicorp", "QUAL3",
    # Kora Saúde
    "Kora Saúde", "Kora Saude", "SAUD3",
    # Viveo
    "Viveo", "VVEO3", "Grupo Viveo",
    # Blau
    "Blau Farmacêutica", "BLAU3", "Blau",
    # Hypera
    "Hypera", "HYPE3", "Hypera Pharma",
]

# ══════════════════════════════════════════════════════════════════════════════
# SAÚDE — operadoras e prestadores não-listados
# ══════════════════════════════════════════════════════════════════════════════
SAUDE_NAO_LISTADAS = [
    "Amil",
    "UnitedHealth", "United Health", "UnitedHealth Group",
    "Bradesco Saúde", "Bradesco Seguros",
    "SulAmérica", "Sul América", "Sul-América", "SulAmerica",
    "Porto Seguro Saúde", "Porto Saúde",
    "Prevent Senior",
    "Unimed", "Seguros Unimed", "Central Nacional Unimed", "Unimed Nacional",
    "Golden Cross",
    "Samedil",
    "Bio Saúde", "Bio Saude",
    "Athena Saúde", "Alliar", "Hospital Care", "Rede Américas",
]

# ══════════════════════════════════════════════════════════════════════════════
# SAÚDE — institucional / regulatório / temas
# ══════════════════════════════════════════════════════════════════════════════
SAUDE_REGULATORIO = [
    "Agência Nacional de Saúde Suplementar",
    "ANVISA", "Anvisa",
    "CONITEC", "Conitec",
    "ANAHP", "Anahp",
    "FenaSaúde", "FenaSaude", "Fenasaúde",
    "Abramge", "ABRAMGE",
    "IESS",
    # temas — todos compostos, inequívocos
    "saúde suplementar",
    "plano de saúde", "planos de saúde",
    "operadora de plano", "operadoras de planos", "operadora de saúde",
    "beneficiários de planos",
    "rol de procedimentos", "rol da ANS", "rol taxativo",
    "sinistralidade",
    "judicialização da saúde", "judicialização",
    "portabilidade de carência", "portabilidade de carências",
    "taxa de ocupação hospitalar",
    "inflação médica", "VCMH", "variação de custo médico",
    "reajuste de plano", "reajuste dos planos", "reajuste de planos",
    "teto de reajuste", "reajuste de mensalidade", "reajuste anual dos planos",
    "notificação de intermediação preliminar",
    "resolução normativa da ANS", "consulta pública da ANS",
    "verticalização", "coparticipação", "fator moderador",
    "glosa hospitalar", "diária hospitalar",
    "medicina diagnóstica", "oncologia privada",
]

# ══════════════════════════════════════════════════════════════════════════════
# EDUCAÇÃO — empresas
# ══════════════════════════════════════════════════════════════════════════════
EDUCACAO_EMPRESAS = [
    # Cogna
    "Cogna", "COGN3", "Kroton", "Anhanguera", "Unopar", "Pitágoras", "Vasta Platform",
    # Yduqs
    "Yduqs", "YDUQ3", "Estácio", "Estacio", "Estácio de Sá", "Ibmec", "Wyden",
    # Ser Educacional
    "Ser Educacional", "SEER3", "UNINASSAU", "Uninassau",
    # Vitru
    "Vitru", "VTRU3", "Uniasselvi", "UniCesumar", "Unicesumar",
    # Afya
    "Afya", "AFYA",
    # Cruzeiro do Sul  (CSED3 é inequívoco; o nome exige contexto — ver CONTEXT)
    "CSED3", "Cruzeiro do Sul Educacional", "Cruzeiro do Sul Virtual",
    # Outras
    "FMU", "UNIP", "Universidade Paulista",
    "Ânima Educação", "Anima Educação", "ANIM3",
]

# ══════════════════════════════════════════════════════════════════════════════
# EDUCAÇÃO — institucional / regulatório / temas
# ══════════════════════════════════════════════════════════════════════════════
EDUCACAO_REGULATORIO = [
    "FIES", "Fies", "ProUni", "Prouni",
    "Ministério da Educação",
    "ENADE", "Enade",
    "ENAMED", "Enamed",
    "ensino a distância", "ensino à distância", "educação a distância",
    "ensino superior", "educação superior",
    "vagas de medicina", "curso de medicina", "cursos de medicina",
    "Mais Médicos", "Mais Medicos",
    "Semesp", "SEMESP", "ABMES", "ANUP",
    "semipresencial",
    "Secretaria de Regulação e Supervisão da Educação Superior",
    "avaliação in loco", "recredenciamento institucional",
    "polo de EAD", "polos de EAD",
    "mensalidade escolar", "evasão de alunos",
]

# ══════════════════════════════════════════════════════════════════════════════
# CASED — casam SÓ nestas formas exatas (case-sensitive)
# Motivo: o token minúsculo é palavra comum do português.
# ══════════════════════════════════════════════════════════════════════════════
CASED_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ans":    ("ANS",),        # "ans" não existe em PT; "ANS" é a agência
    "cade":   ("CADE",),       # "cade"/"cadê" é coloquial e comuníssimo
    "mec":    ("MEC",),
    "inep":   ("INEP", "Inep"),
    "ead":    ("EAD", "EaD"),
    "seres":  ("SERES",),      # "seres humanos", "seres vivos"
    "uninter": ("UNINTER", "Uninter"),
    "nip":    ("NIP",),        # "nip" não existe; NIP = notificação ANS
}

# ══════════════════════════════════════════════════════════════════════════════
# CONTEXT — casam só se houver palavra de contexto do setor no mesmo texto
# ══════════════════════════════════════════════════════════════════════════════
# Cada entrada: termo → ("saude" | "educacao" | "ambos")
CONTEXT_KEYWORDS: dict[str, str] = {
    # nomes próprios comuns que também são empresa
    "Alice":            "saude",      # operadora healthtech vs. nome de pessoa
    "Sami":             "saude",      # operadora vs. nome de pessoa
    "Descomplica":      "educacao",   # edtech vs. verbo "descomplicar"
    "Cruzeiro do Sul":  "educacao",   # universidade vs. constelação/jornal/time
    "Ânima":            "educacao",   # grupo vs. "ânima" (verbo animar)
    "Anima":            "educacao",
    # termos genéricos fora do setor
    "reajuste":         "saude",      # de plano? salarial? da gasolina?
    "revisão técnica":  "saude",      # de carteira? de veículo?
    "captação":         "educacao",   # de alunos? de recursos?
    "captação de alunos": "educacao",
    "matrículas":       "educacao",
    "ticket médio":     "ambos",
    "sinistro":         "saude",
    "carência":         "saude",
}

# Palavras que estabelecem o contexto para as CONTEXT_KEYWORDS acima.
CONTEXT_MARKERS: dict[str, tuple[str, ...]] = {
    "saude": (
        "plano de saúde", "planos de saúde", "saúde suplementar", "operadora",
        "operadoras", "beneficiário", "beneficiários", "ANS", "hospital",
        "hospitalar", "convênio médico", "seguro saúde", "sinistralidade",
        "healthtech", "medicina", "médico", "médica", "paciente",
    ),
    "educacao": (
        "aluno", "alunos", "matrícula", "matrículas", "graduação", "faculdade",
        "universidade", "ensino superior", "EAD", "MEC", "edtech", "curso",
        "cursos", "campus", "vestibular", "mensalidade", "estudante",
    ),
}

# ══════════════════════════════════════════════════════════════════════════════
# Blocklist de TÍTULO — descarta antes de qualquer keyword
# Deliberadamente curta: o gate de LLM faz o trabalho fino. Isto aqui só
# elimina o ruído estrutural que aparece todo dia nos portais amplos.
# ══════════════════════════════════════════════════════════════════════════════
TITLE_BLOCKLIST = frozenset([
    # esporte (protege "Cruzeiro", "Porto", "São Paulo")
    "futebol", "libertadores", "brasileirão", "brasileirao", "escalação",
    "campeonato", "gol de", "técnico do", "camisa 10", "copa do mundo",
    "vôlei", "basquete", "fórmula 1", "formula 1", "olimpíadas",
    # entretenimento / celebridade
    "big brother", "bbb", "novela", "reality show", "a fazenda",
    "affair", "fofoca", "ex-namorad", "carnaval", "bbb26",
    # lifestyle / serviço
    "horóscopo", "signo", "receita de", "simpatia", "mega-sena",
    "loteria", "quina", "lotofácil", "black friday", "cupom de desconto",
    # cripto
    "bitcoin", "criptomoeda", "blockchain",
])

# ══════════════════════════════════════════════════════════════════════════════
# Configurações do pipeline
# ══════════════════════════════════════════════════════════════════════════════
WINDOW_HOURS = 72          # janela de INGESTÃO (descarta RSS mais velho que isso).
                           # Não confundir com a janela de EXIBIÇÃO do dashboard.
                           # 72h > 48h da home, com margem: nunca joga fora na
                           # coleta algo que a página mostraria.
PRIMARY_WINDOW_HOURS = 168 # janela das fontes PRIMÁRIAS (DOU/CVM), separada da
                           # de imprensa. Medido em 03/ago/2026: o ZIP do IPE da
                           # CVM é regenerado com ~1 dia de atraso e só entram
                           # ~1,5 doc/dia das companhias cobertas — com 72h o
                           # coletor devolvia 0 em 9,4% dos dias sem nada estar
                           # quebrado. Com 168h, 0 em 0% dos 181 dias simulados.
                           # Documento oficial não envelhece como notícia, e o
                           # dedup contra o banco impede reprocessar.
MAX_PER_SOURCE = 50        # teto por fonte por run, aplicado DEPOIS da janela
SUPABASE_TABLE = "articles"
LLM_BATCH_SIZE = 12        # artigos por chamada de LLM (economiza cota do free tier)
LLM_LOOKBACK_DAYS = 7      # janela de URLs já conhecidas puxadas do banco p/ não
                           # re-julgar o mesmo artigo a cada run de 5 min


def all_keywords() -> list[str]:
    """Lista achatada das keywords STRONG (as CASED/CONTEXT são tratadas à parte)."""
    return sorted(set(
        SAUDE_LISTADAS + SAUDE_NAO_LISTADAS + SAUDE_REGULATORIO +
        EDUCACAO_EMPRESAS + EDUCACAO_REGULATORIO
    ))
