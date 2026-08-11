"""
Fontes RSS — imprensa econômica ampla + veículos setoriais de saúde/educação.

filter=False → veículo estreito, 100% no escopo → aceita tudo (só blocklist)
filter=True  → veículo amplo → exige keyword (hunter/filter.py)

Cada fonte declara uma LISTA de URLs candidatas. O coletor tenta em ordem e
fica com a primeira que devolver entradas. Serve para dois casos: veículo que
mudou o caminho do feed (o Estadão fez isso) e veículo com feed geral + feed de
seção, onde o de seção é melhor mas nem sempre existe.

Estado verificado ao vivo em 30/jul/2026 (`python hunt.py --check-sources`).
As marcações [OK n] são o que respondeu naquele dia. Rode de novo antes de
culpar o robô por feed vazio.
"""

SOURCES = [
    # ══ IMPRENSA ECONÔMICA AMPLA (filter=True) ═══════════════════════════════
    {"label": "Valor Econômico", "filter": True, "urls": [        # [OK 100]
        "https://pox.globo.com/rss/valor/empresas"]},
    {"label": "Valor Econômico", "filter": True, "urls": [        # [OK 100]
        "https://pox.globo.com/rss/valor"]},
    {"label": "InfoMoney", "filter": True, "urls": [              # [OK 10]
        "https://www.infomoney.com.br/feed/"]},
    {"label": "Exame", "filter": True, "urls": [                  # [OK 25]
        "https://exame.com/feed/"]},
    {"label": "Money Times", "filter": True, "urls": [            # [OK 10]
        "https://www.moneytimes.com.br/feed/"]},
    {"label": "InvestNews", "filter": True, "urls": [             # [OK 30]
        "https://investnews.com.br/feed/"]},
    {"label": "Seu Dinheiro", "filter": True, "urls": [           # [OK 10]
        "https://www.seudinheiro.com/feed/"]},
    {"label": "Folha de S.Paulo", "filter": True, "urls": [       # [OK 100]
        "https://feeds.folha.uol.com.br/mercado/rss091.xml"]},
    {"label": "Folha de S.Paulo", "filter": True, "urls": [       # [OK 100]
        "https://feeds.folha.uol.com.br/educacao/rss091.xml"]},
    {"label": "Folha de S.Paulo", "filter": True, "urls": [       # [OK 100]
        "https://feeds.folha.uol.com.br/equilibrioesaude/rss091.xml"]},
    # UOL: [OK 15] mas dated=0 — o feed não traz data. Esses itens nunca são
    # cortados pela janela de ingestão e ordenam pelo found_at.
    {"label": "UOL Economia", "filter": True, "urls": [
        "https://rss.uol.com.br/feed/economia.xml"]},
    {"label": "CNN Brasil", "filter": True, "urls": [             # [OK 60]
        "https://www.cnnbrasil.com.br/feed/"]},
    {"label": "Metrópoles", "filter": True, "urls": [             # [OK 20]
        "https://www.metropoles.com/feed"]},
    {"label": "Poder360", "filter": True, "urls": [               # [OK 10]
        "https://www.poder360.com.br/feed/"]},
    {"label": "Agência Brasil", "filter": True, "urls": [         # [OK 10]
        "https://agenciabrasil.ebc.com.br/rss/saude/feed.xml"]},
    {"label": "Agência Brasil", "filter": True, "urls": [         # [OK 10]
        "https://agenciabrasil.ebc.com.br/rss/educacao/feed.xml"]},
    {"label": "Agência Brasil", "filter": True, "urls": [         # [OK 10]
        "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml"]},

    # Estadão. O feed que presta é o do Arc Publishing, a plataforma que eles
    # usam: /arc/outboundfeeds/rss/. Os caminhos clássicos seguem 404 (rss.ece,
    # /rss/economia.xml, /feed/) e os subdomínios de seção entram em loop de
    # redirect — não perca tempo com eles de novo. As variantes de categoria do
    # próprio Arc (/rss/category/economia/) também são 404; só o geral responde.
    #
    # ⚠️ O E-Investidor **está congelado desde 27/05/2026** — responde HTTP 200
    # com 8 entradas, todas de meses atrás. Era a única candidata configurada, e
    # por isso o Estadão nunca entregou UM artigo sequer: tudo caía fora da
    # janela e a fonte parecia apenas "quieta". Fica como segunda candidata caso
    # volte a publicar; o coletor só chega nela se o Arc falhar.
    #
    # Feed morto é pior que feed com erro: erro aparece no --check-sources,
    # feed velho responde 200 e some em silêncio. Ao ver "0 items (de N
    # entradas)" no log, cheque a DATA das entradas antes de culpar o filtro.
    # [Arc OK 100, 98 dentro de 72h, mais recente 12 min — 11/ago/2026]
    {"label": "Estadão", "filter": True, "urls": [
        "https://www.estadao.com.br/arc/outboundfeeds/rss/?outputType=xml",
        "https://einvestidor.estadao.com.br/feed/"]},

    # G1: os dois feeds respondem com 100 itens, todos com data. O de Educação
    # é o que salva a cobertura de educação (ver bloco EDUCAÇÃO abaixo). [OK 100 cada]
    {"label": "G1 Economia", "filter": True, "urls": [
        "https://g1.globo.com/rss/g1/economia/"]},

    # ══ NEGÓCIOS / DEALS ═════════════════════════════════════════════════════
    # Alto sinal para M&A e mudança de controle — chegam antes de virar matéria
    # nos diários.
    {"label": "Brazil Journal", "filter": True, "urls": [         # [OK 10]
        "https://braziljournal.com/feed/"]},
    {"label": "NeoFeed", "filter": True, "urls": [                # [OK 10]
        "https://neofeed.com.br/feed/"]},
    # Pipeline (Valor) REMOVIDO: 404 e é paywall — não renderia nem com feed.

    # ══ JURÍDICO / REGULATÓRIO ═══════════════════════════════════════════════
    # O JOTA é a fonte de imprensa com melhor sinal regulatório do conjunto: no
    # teste do dia, a primeira manchete era "ANS amplia prazo sobre cartões".
    {"label": "JOTA", "filter": True, "urls": [                   # [OK 25]
        "https://www.jota.info/feed"]},
    # JOTA Saúde REMOVIDO: /category/saude/feed, /saude/feed,
    # /tributos-e-empresas/saude/feed e /categoria/saude/feed — todos 404.
    # O JOTA não expõe feed por seção. O feed geral cobre (via keyword).

    # ══ ANVISA via Atom (verificado: application/atom+xml, 14 KB) ════════════
    # Único dos cinco órgãos testados que serve feed de verdade. Mantido junto
    # com o scraper HTML da ANVISA: a dedup por URL resolve a sobreposição.
    {"label": "ANVISA", "filter": False, "urls": [
        "https://www.gov.br/anvisa/pt-br/assuntos/noticias-anvisa/RSS"]},

    # ANS via RSS: NÃO EXISTE. /noticias/RSS e /noticias/rss.xml devolvem a
    # mesma casca de 55.388 bytes da SPA (HTTP 200, content-type text/html);
    # /noticias/rss e /noticias/@@rss são 404. MEC/RSS devolve 5,5 KB vazios,
    # INEP/RSS e CADE/RSS são 404. Só a ANVISA tem Atom.
    # A ANS entra pelo scraper HTML (subseção /consumidor) e pelo DOU.

    # ══ SETORIAIS SAÚDE — estreitas, aceitam tudo (filter=False) ═════════════
    {"label": "Medicina S/A", "filter": False, "urls": [          # [OK 10]
        "https://medicinasa.com.br/feed/"]},
    {"label": "Saúde Business", "filter": False, "urls": [        # [OK 10]
        "https://saudebusiness.com/feed/"]},
    {"label": "Futuro da Saúde", "filter": False, "urls": [       # [OK 10]
        "https://futurodasaude.com.br/feed/"]},
    {"label": "Setor Saúde", "filter": False, "urls": [           # [OK 10]
        "https://setorsaude.com.br/feed/"]},
    {"label": "Healthcare Management", "filter": False, "urls": [ # [OK 3]
        "https://healthcaremanagement.com.br/feed/"]},
    {"label": "Portal Hospitais Brasil", "filter": False, "urls": [  # [OK 10]
        "https://portalhospitaisbrasil.com.br/feed/"]},
    {"label": "Panorama Farmacêutico", "filter": False, "urls": [ # [OK 20]
        "https://panoramafarmaceutico.com.br/feed/"]},

    # ══ EDUCAÇÃO ═════════════════════════════════════════════════════════════
    # VEREDITO 30/jul, depois de testar 9 candidatos: NÃO EXISTE imprensa
    # setorial de educação superior com RSS vivo. Desafios da Educação 404 em
    # /feed e /rss; Revista Ensino Superior 500 nos dois; Semesp 403 mesmo com
    # TLS de Chrome; ABMES erro de SSL; UOL Educação 403; Estadão Educação em
    # loop de redirect.
    #
    # A cobertura de educação passa a ser: G1 Educação (100 itens, todos com
    # data) + Folha Educação (100) + DOU/MEC (portarias de credenciamento e
    # vagas de medicina) + o que a imprensa econômica derramar. É menos que a
    # de saúde — que tem 7 setoriais vivas — e isso é característica do
    # mercado de veículos, não defeito do robô.
    {"label": "G1 Educação", "filter": True, "urls": [                # [OK 100]
        "https://g1.globo.com/rss/g1/educacao/"]},
]
