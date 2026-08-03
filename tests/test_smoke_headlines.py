"""
Smoke test de manchetes reais — a rede de segurança contra recalibragem ruim.

Diferente de tests/test_filter.py (que testa termo a termo), aqui as frases são
manchetes plausíveis do dia a dia, incluindo o ruído que os portais amplos
despejam. Se alguém promover um termo de CONTEXT para STRONG em config.py,
é aqui que estoura primeiro.

    pytest tests/test_smoke_headlines.py -q
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timezone
from hunter.fetcher import RawArticle
from hunter.filter import filter_articles



def test_manchetes_reais():
    now = datetime.now(timezone.utc)
    def A(title, src="Valor Econômico", snip="", nf=True):
        return RawArticle("https://x/"+str(abs(hash(title))), "x.com", src, title, snip, None, now, nf)

    CASOS = [
        # (manchete, deve_passar?)
        ("Hapvida reporta sinistralidade de 70,2% no 2T26 e ação sobe 6%", True),
        ("ANS aprova revisão técnica da carteira individual de operadora", True),
        ("Rede D'Or compra hospital em Salvador por R$ 800 milhões", True),
        ("Cogna eleva captação de alunos em 9% no ciclo de ingresso", True),
        ("MEC suspende abertura de novas vagas de medicina até 2027", True),
        ("Reajuste dos planos de saúde individuais é fixado em 6,06%", True),
        ("CADE aprova sem restrições a compra da operadora regional", True),
        ("SERES publica portaria de recredenciamento de universidade", True),
        ("Alice, healthtech de plano de saúde, capta R$ 300 mi em série C", True),
        # ── ruído que NÃO pode passar ────────────────────────────────────────────
        ("Reajuste salarial dos servidores federais é aprovado no Congresso", False),
        ("Captação de recursos do fundo imobiliário decepciona no trimestre", False),
        ("Alice Braga estrela nova série de ficção científica", False),
        ("Cruzeiro vence o clássico e assume a liderança do Brasileirão", False),
        ("Constelação do Cruzeiro do Sul poderá ser vista a olho nu hoje", False),
        ("Novo app descomplica a declaração do imposto de renda", False),
        ("Cade o meu pedido? Consumidores reclamam de atraso em entregas", False),
        ("Estudo com seres humanos avança em laboratório europeu", False),
        ("Revisão técnica obrigatória de veículos volta ao debate no Senado", False),
        ("Bitcoin dispara e renova máxima histórica", False),
        ("Últimas notícias", False),
    ]

    arts = [A(t) for t, _ in CASOS]
    passou = {a["title"] for a in filter_articles(arts)}

    erros = 0
    for titulo, esperado in CASOS:
        real = titulo in passou
        if real != esperado:
            erros += 1
            print(f"  ✗ {'deveria passar' if esperado else 'NÃO deveria passar':22s} | {titulo}")
        else:
            print(f"  ✓ {'passou':22s} | {titulo[:72]}" if real else f"  ✓ {'cortado':22s} | {titulo[:72]}")

    # Fonte curada (needs_filter=False) passa sem keyword, mas a blocklist ainda vale
    curadas = filter_articles([
        A("Nota da diretoria sobre o novo normativo", "ANS", nf=False),
        A("Escalação do time para a final da Libertadores", "ANS", nf=False),
    ])
    if len(curadas) != 1:
        erros += 1; print("  ✗ fonte curada: blocklist de título não foi aplicada")
    else:
        print("  ✓ fonte curada     | passa sem keyword, mas blocklist ainda corta esporte")

    print(f"\n{'FALHOU: ' + str(erros) + ' caso(s)' if erros else 'SMOKE OK — 0 falsos positivos, 0 falsos negativos'}")
    assert erros == 0, f'{erros} caso(s) de calibragem falharam'
