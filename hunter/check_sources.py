"""
Validador de fontes — `python hunt.py --check-sources`.

Existe porque nenhuma lista de feeds sobrevive intacta a seis meses: sites
migram de RSS, mudam padrão de URL, ligam Cloudflare. Sem isso, uma fonte morta
some do feed em silêncio e ninguém percebe.

Roda tudo, não grava nada, e imprime uma tabela:

    OK    Valor Econômico          200  items= 47  dated= 47
    VAZIO Semesp                   200  items=  0  dated=  0   <- investigar
    ERRO  Portal Hospitais Brasil  403                          <- Cloudflare

Regra: se aparecer VAZIO ou ERRO, comente a fonte em sources.py/html_scrapers.py
em vez de deixá-la falhando todo run.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import feedparser

from .fetcher import http_get
from .sources import SOURCES

log = logging.getLogger(__name__)


def _check_rss(src: dict) -> tuple[str, str]:
    """Testa TODAS as candidatas e reporta a primeira que servir."""
    label = src["label"]
    urls = src.get("urls") or [src["url"]]
    falhas = []
    for url in urls:
        try:
            status, content = http_get(url)
        except Exception as e:
            falhas.append(f"{type(e).__name__} {url}")
            continue
        if status != 200 or not content:
            falhas.append(f"HTTP {status} {url}")
            continue
        feed = feedparser.parse(content)
        n = len(feed.entries)
        if n == 0:
            falhas.append(f"200 mas 0 entradas {url}")
            continue
        dated = sum(1 for e in feed.entries if getattr(e, "published_parsed", None))
        sample = (feed.entries[0].get("title") or "")[:46]
        extra = f"  (candidata {urls.index(url) + 1}/{len(urls)})" if len(urls) > 1 else ""
        return "OK", f"OK    {label:28s} items={n:3d}  dated={dated:3d}{extra}  | {sample}"
    return "ERRO", f"ERRO  {label:28s} nenhuma candidata serviu: " + " ; ".join(falhas)[:120]


def _check_html(src: dict) -> tuple[str, str]:
    from .html_scrapers import _scrape_one
    label = src["label"]
    try:
        items = _scrape_one(src)
    except Exception as e:
        return "ERRO", f"ERRO  {label:28s} {type(e).__name__}: {str(e)[:60]}"
    if not items:
        return "VAZIO", f"VAZIO {label:28s} 0 artigos casaram o href_re — padrão de URL mudou?"
    dated = sum(1 for i in items if i.published_at)
    return "OK", f"OK    {label:28s}      items={len(items):3d}  dated={dated:3d}  | {items[0].title[:52]}"


def _check_primary() -> list[tuple[str, str]]:
    from .primary_sources import collect_cvm, collect_dou
    out = []
    for label, fn in (("DOU — Diário Oficial", collect_dou), ("CVM — Fato Relevante", collect_cvm)):
        try:
            items = fn()
        except Exception as e:
            out.append(("ERRO", f"ERRO  {label:28s} {type(e).__name__}: {str(e)[:60]}"))
            continue
        if not items:
            out.append(("VAZIO", f"VAZIO {label:28s} 0 itens — ver aviso no log acima"))
        else:
            out.append(("OK", f"OK    {label:28s}      items={len(items):3d}  | {items[0].title[:52]}"))
    return out


def run_check() -> int:
    from .html_scrapers import HTML_SOURCES

    print("\n" + "=" * 100)
    print("RSS")
    print("=" * 100)
    with ThreadPoolExecutor(8) as ex:
        rss = list(ex.map(_check_rss, SOURCES))
    for _, line in sorted(rss):
        print(line)

    print("\n" + "=" * 100)
    print("SCRAPERS HTML")
    print("=" * 100)
    with ThreadPoolExecutor(6) as ex:
        html = list(ex.map(_check_html, HTML_SOURCES))
    for _, line in sorted(html):
        print(line)

    print("\n" + "=" * 100)
    print("FONTES PRIMÁRIAS")
    print("=" * 100)
    primary = _check_primary()
    for _, line in primary:
        print(line)

    all_results = rss + html + primary
    ok = sum(1 for s, _ in all_results if s == "OK")
    vazio = sum(1 for s, _ in all_results if s == "VAZIO")
    erro = sum(1 for s, _ in all_results if s == "ERRO")

    print("\n" + "=" * 100)
    print(f"RESUMO: {ok} OK · {vazio} VAZIO · {erro} ERRO  (total {len(all_results)})")
    print("=" * 100)
    print("VAZIO/ERRO não quebram o pipeline, mas somem em silêncio no dia a dia.")
    print("Comente a fonte no arquivo correspondente ou corrija o href_re/URL.\n")
    return 0 if erro == 0 else 1
