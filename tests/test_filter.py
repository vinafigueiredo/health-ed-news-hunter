"""
Testes do filtro de keyword.

Rode `pytest` sempre que mexer em hunter/config.py. O que estes testes protegem
não é a lógica — é a CALIBRAGEM: cada caso aqui é um falso positivo ou falso
negativo real que a lista de keywords produziria se alguém promovesse um termo
ambíguo para STRONG sem pensar.

    pip install pytest && pytest -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hunter.filter import (  # noqa: E402
    _is_page_index,
    _serial_key,
    collapse_serial_articles,
    match_keywords,
)


def kws(text):
    return set(match_keywords(text))


# ── STRONG: nomes inequívocos casam em qualquer caixa ────────────────────────
def test_empresas_casam():
    assert "hapvida" in kws("Hapvida reporta sinistralidade menor no 2T26")
    assert "rede d'or" in kws("Rede D'Or anuncia aquisição de hospital em Salvador")
    assert "cogna" in kws("COGNA divulga prévia de captação")
    assert "oncoclínicas" in kws("Oncoclínicas capta R$ 1,5 bi")


def test_ticker_casa():
    assert "hapv3" in kws("HAPV3 sobe 4% após resultado")
    assert "csed3" in kws("CSED3 anuncia recompra de ações")


def test_temas_compostos():
    assert "sinistralidade" in kws("Sinistralidade do setor cai para 82%")
    assert "rol de procedimentos" in kws("ANS amplia o rol de procedimentos")
    assert "inflação médica" in kws("Inflação médica pressiona os planos")
    assert "vagas de medicina" in kws("MEC suspende novas vagas de medicina")


# ── CASED: siglas que colidem com palavra comum ──────────────────────────────
def test_ans_maiuscula_casa_minuscula_nao():
    assert "ans" in kws("ANS aprova revisão técnica de carteira individual")
    # "ans" minúsculo não existe em português — mas a regra precisa valer:
    assert "ans" not in kws("o resultado veio dentro dos plans e ans previstos")


def test_cade_vs_cade_coloquial():
    assert "cade" in kws("CADE aprova a compra sem restrições")
    assert "cade" not in kws("Cade o meu plano de saúde? Leitor reclama do app")


def test_seres_vs_seres_humanos():
    assert "seres" in kws("SERES publica portaria de recredenciamento")
    assert "seres" not in kws("Estudo com seres humanos avança na universidade")


def test_ead_maiuscula():
    assert "ead" in kws("MEC restringe polos de EAD em medicina")


# ── CONTEXT: só casa com marcador do setor no mesmo texto ────────────────────
def test_alice_precisa_de_contexto_de_saude():
    assert "alice" in kws("Alice, healthtech de plano de saúde, capta série C")
    assert "alice" not in kws("Alice Braga estrela nova série da Netflix")


def test_sami_precisa_de_contexto():
    assert "sami" in kws("Operadora Sami encerra atividades e migra beneficiários")
    assert "sami" not in kws("Sami marcou o gol da vitória no segundo tempo")


def test_descomplica_verbo_nao_casa():
    assert "descomplica" in kws("Descomplica compra faculdade e amplia oferta de graduação")
    assert "descomplica" not in kws("Novo app descomplica a declaração do imposto de renda")


def test_cruzeiro_do_sul_universidade_vs_time():
    assert "cruzeiro do sul" in kws("Cruzeiro do Sul amplia matrículas em cursos EAD")
    assert "cruzeiro do sul" not in kws("Constelação do Cruzeiro do Sul será visível hoje")


def test_reajuste_precisa_ser_de_plano():
    assert "reajuste" in kws("Reajuste dos planos de saúde individuais fica em 6,1%")
    assert "reajuste" not in kws("Reajuste salarial dos servidores é aprovado")


def test_captacao_precisa_ser_de_alunos():
    assert "captação" in kws("Captação de alunos da graduação cresce 8% no ciclo")
    assert "captação" not in kws("Captação de recursos do fundo imobiliário decepciona")


def test_revisao_tecnica_precisa_de_contexto():
    assert "revisão técnica" in kws("ANS autoriza revisão técnica em carteira de plano de saúde")
    assert "revisão técnica" not in kws("Revisão técnica obrigatória de veículos volta a ser discutida")


# ── Página-índice ────────────────────────────────────────────────────────────
def test_page_index():
    assert _is_page_index("Últimas notícias")
    assert _is_page_index("Vídeos")
    assert _is_page_index("Economia")            # curto demais
    assert not _is_page_index("Hapvida reporta sinistralidade menor no segundo trimestre")


# ── Regressões que já custaram caro em pipelines parecidos ───────────────────
def test_fronteira_de_palavra():
    # "Amil" não pode casar dentro de "familiar", "Amilcar"
    assert "amil" not in kws("O orçamento familiar aperta com a inflação")
    assert "amil" in kws("Amil renegocia rede credenciada em São Paulo")


def test_nao_casa_dentro_de_outra_palavra():
    assert "fies" not in kws("O prefeito fiestou o orçamento")  # palavra inventada, mas prova a fronteira
    assert "fies" in kws("Novo edital do FIES abre 60 mil vagas")


# ── Colapso de matéria serializada por estado ────────────────────────────────
# Caso real de 03/ago/2026: o MEC publicou 14 vezes a mesma matéria do FIES,
# uma por UF, e ela virou 26% do feed do dia.
def _art(fonte, titulo):
    return {"source_name": fonte, "title": titulo, "url": f"http://x/{titulo}"}


FIES_POR_UF = [
    _art("MEC", "Fies 2026: São Paulo registrou 17,9 mil inscritos no segundo semestre"),
    _art("MEC", "Fies 2026: Minas Gerais registrou 13,2 mil inscritos no segundo semestre"),
    _art("MEC", "Fies 2026: Roraima registrou 212 inscritos no segundo semestre"),
    _art("MEC", "Fies 2026: Pará registrou 7 mil inscritos no segundo semestre"),
]


def test_serial_por_uf_colapsa():
    assert len({_serial_key(a["title"]) for a in FIES_POR_UF}) == 1
    assert len(collapse_serial_articles(FIES_POR_UF)) == 1


def test_serial_nao_engole_noticia_distinta():
    distintas = [
        _art("Valor Econômico", "Hapvida reporta sinistralidade de 70% no 2T26"),
        _art("Valor Econômico", "Rede D'Or anuncia aquisição de hospital em Salvador"),
        _art("Valor Econômico", "Cogna divulga prévia de captação do segundo semestre"),
    ]
    assert len(collapse_serial_articles(distintas)) == 3


def test_serial_exige_tres_para_colapsar():
    """Duas manchetes parecidas costumam ser notícias distintas; 14 são a mesma."""
    assert len(collapse_serial_articles(FIES_POR_UF[:2])) == 2


def test_serial_nao_cruza_fontes():
    """Mesma matéria em veículos diferentes é cobertura, não repetição."""
    mesma_em_tres = [
        _art("G1 Educação", "Fies 2026: Bahia registrou 5 mil inscritos no segundo semestre"),
        _art("Folha de S.Paulo", "Fies 2026: Bahia registrou 5 mil inscritos no segundo semestre"),
        _art("Agência Brasil", "Fies 2026: Bahia registrou 5 mil inscritos no segundo semestre"),
    ]
    assert len(collapse_serial_articles(mesma_em_tres)) == 3


def test_serial_nao_engole_atos_do_dou():
    """Regressão de 03/ago/2026: o título do DOU é só o número do ato, então
    tirar os dígitos tornava 11 portarias SERES distintas idênticas."""
    portarias = [
        _art("DOU — Diário Oficial", f"Portaria — PORTARIA SERES/MEC Nº 36{n}, DE 29 de julho de 2026")
        for n in range(1, 9)
    ]
    assert len(collapse_serial_articles(portarias)) == 8


def test_serial_preserva_ordem():
    entrada = [
        _art("Valor Econômico", "Hapvida reporta sinistralidade de 70% no 2T26"),
        *FIES_POR_UF,
        _art("Valor Econômico", "Cogna divulga prévia de captação"),
    ]
    saida = collapse_serial_articles(entrada)
    assert [a["title"] for a in saida] == [
        "Hapvida reporta sinistralidade de 70% no 2T26",
        "Fies 2026: São Paulo registrou 17,9 mil inscritos no segundo semestre",
        "Cogna divulga prévia de captação",
    ]
