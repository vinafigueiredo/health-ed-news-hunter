"""
Orquestrador da coleta.

fetch_all() roda RSS + scrapers HTML + fontes primárias em paralelo, aplica a
janela de ingestão, deduplica por URL e devolve uma lista de RawArticle.

Dois princípios que não se negociam:
  1. Filter-then-cap — o teto por fonte (MAX_PER_SOURCE) é aplicado DEPOIS do
     corte por janela. Cortar antes descarta itens recentes em feeds grandes.
  2. Dedup preferindo a melhor versão — na colisão de URL, fica a que tem
     published_at; em empate, o título mais longo.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import feedparser
import requests

from .config import MAX_PER_SOURCE, WINDOW_HOURS
from .sources import SOURCES

log = logging.getLogger(__name__)

# UA de navegador: WAF brasileiro bloqueia bot-UA óbvio. Accept genérico —
# alguns WAFs devolvem 415 para Accept RSS-específico.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
TIMEOUT = 20

# Parâmetros de rastreamento removidos da URL antes de qualquer coisa —
# senão a mesma matéria entra várias vezes com utm_ diferente.
_STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid", "ref", "origin", "xtor", "cmpid",
}


@dataclass
class RawArticle:
    url: str
    domain: str
    source_name: str
    title: str
    snippet: str
    published_at: Optional[datetime]
    found_at: datetime
    needs_filter: bool


def clean_url(url: str) -> str:
    try:
        p = urlparse(url)
        qs = {k: v for k, v in parse_qs(p.query).items() if k not in _STRIP_PARAMS}
        return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(qs, doseq=True), ""))
    except Exception:
        return url


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


# Perfis tentados em ordem no fallback do curl_cffi. Um bloqueio de WAF
# (Akamai/Cloudflare) às vezes mira um fingerprint TLS específico — chrome124
# sozinho ficou preso bloqueado contra o feed novo do Estadão (Arc Publishing)
# por 14h+ em 12/ago/2026 enquanto o mesmo feed respondia normalmente fora do
# IP do Actions. Mais de um perfil dá uma segunda chance antes de desistir.
CURL_CFFI_PROFILES = ("chrome124", "safari17_0")


def _curl_cffi_get(url: str, timeout: int):
    """Tenta os perfis de CURL_CFFI_PROFILES em ordem; devolve o primeiro 200."""
    from curl_cffi import requests as creq
    last = None
    for profile in CURL_CFFI_PROFILES:
        r = creq.get(url, impersonate=profile, timeout=timeout)
        log.info("curl_cffi fallback [%s]: HTTP %d", profile, r.status_code)
        if r.status_code == 200:
            return r
        last = r
    return last


def http_get(url: str, timeout: int = TIMEOUT) -> tuple[int, bytes]:
    """GET com fallback para curl_cffi (TLS de Chrome) em 401/403/429.

    Vários sites brasileiros usam Cloudflare, que bloqueia o fingerprint TLS do
    `requests` quando a origem é IP de datacenter — exatamente o caso do GitHub
    Actions. O curl_cffi imita o Chrome (ou Safari, ver CURL_CFFI_PROFILES) e
    costuma passar.
    """
    resp = None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code not in (401, 403, 429):
            return resp.status_code, resp.content
    except Exception as e:
        log.debug("requests falhou [%s]: %s", url, e)
    try:
        r2 = _curl_cffi_get(url, timeout)
        if r2 is not None:
            return r2.status_code, r2.content
    except Exception as e:
        log.debug("curl_cffi indisponível/falhou: %s", e)
    return (resp.status_code, resp.content) if resp is not None else (0, b"")


def _fetch_feed_url(label: str, url: str, needs_filter: bool) -> list[RawArticle]:
    try:
        status, content = http_get(url)
        if status != 200 or not content:
            log.warning("Feed ERRO [%s] HTTP %s: %s", label, status, url)
            return []
        feed = feedparser.parse(content)
    except Exception as e:
        log.warning("Feed EXCEÇÃO [%s] %s: %s", label, url, e)
        return []

    n = len(feed.entries)
    if n == 0:
        # HTTP 200 com 0 entradas costuma ser página de desafio do Cloudflare
        # servida como HTML. O fallback do http_get só dispara em 401/403/429,
        # então esse caso passa batido e a fonte some em silêncio.
        try:
            r2 = _curl_cffi_get(url, TIMEOUT)
            feed2 = feedparser.parse(r2.content) if r2 is not None else None
            if feed2 is not None and feed2.entries:
                log.info("Feed [%s] recuperado via curl_cffi (0 -> %d)", label, len(feed2.entries))
                feed, n = feed2, len(feed2.entries)
        except Exception:
            pass
    if n == 0:
        log.warning("Feed VAZIO [%s]: HTTP 200 mas 0 entradas — %s", label, url)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    now = datetime.now(timezone.utc)
    out: list[RawArticle] = []

    for entry in feed.entries:
        title = strip_html(entry.get("title", ""))
        raw_url = (entry.get("link") or "").strip()
        if not title or not raw_url.startswith("http"):
            continue

        published_at = _parse_date(entry)
        if published_at and published_at < cutoff:
            continue

        snippet = strip_html(entry.get("summary", "") or entry.get("description", ""))[:400]
        u = clean_url(raw_url)

        out.append(RawArticle(
            url=u,
            domain=urlparse(u).netloc.replace("www.", ""),
            source_name=label,
            title=title,
            snippet=snippet,
            published_at=published_at,
            found_at=now,
            needs_filter=needs_filter,
        ))

    out = out[:MAX_PER_SOURCE]  # cap DEPOIS da janela
    log.info("Feed OK [%s] -> %d items (de %d entradas) via %s", label, len(out), n, url)
    return out


def _fetch_feed(source: dict) -> list[RawArticle]:
    """Tenta as URLs candidatas em ordem; fica com a primeira que der entradas.

    Existe porque veículo troca o caminho do feed sem avisar (o Estadão trocou)
    e porque adivinhar errado fazia a fonte sumir em silêncio. Com candidatas,
    o coletor descobre qual está viva em vez de depender de a lista estar certa.
    """
    label = source["label"]
    needs_filter = source.get("filter", True)
    urls = source.get("urls") or [source["url"]]

    tentadas = []
    for url in urls:
        items = _fetch_feed_url(label, url, needs_filter)
        tentadas.append(f"{url} -> {len(items)}")
        if items:
            return items
    log.warning("Feed VAZIO [%s]: nenhuma candidata respondeu | %s", label, " | ".join(tentadas))
    return []


def todas_as_fontes(include_primary: bool = True) -> list[str]:
    """Rótulos de TODA fonte configurada — inclusive as que não entregam nada.

    Existe por causa de um ponto cego real: o `record_source_health` recebia só
    as fontes que devolveram artigo, então fonte que nunca entrega nunca ganha
    linha na tabela — e o watchdog, que itera sobre as linhas existentes, não
    tem como reclamar de algo que não está lá. A checagem "nunca coletou nada"
    dele era código morto.

    Custou 76 dias de Estadão mudo: o feed do E-Investidor congelou em maio,
    seguiu respondendo HTTP 200 com entradas velhas, e como nada passava da
    janela a fonte simplesmente não existia para o monitoramento.
    """
    rotulos = {s["label"] for s in SOURCES}
    try:
        from .html_scrapers import HTML_SOURCES
        rotulos |= {s["label"] for s in HTML_SOURCES}
    except Exception as e:
        log.warning("não consegui listar os scrapers HTML: %s", e)
    if include_primary:
        rotulos |= {"DOU — Diário Oficial", "CVM — Fato Relevante"}
    return sorted(rotulos)


def fetch_all(include_primary: bool = True) -> list[RawArticle]:
    """Coleta tudo em paralelo e devolve a lista deduplicada."""
    articles: list[RawArticle] = []

    # 1) Scrapers HTML (gov.br e entidades sem RSS)
    try:
        from .html_scrapers import collect_html_sources
        items = collect_html_sources()
        articles.extend(items)
        log.info("HTML scrapers: %d artigos", len(items))
    except Exception as e:
        log.warning("HTML scrapers falharam: %s", e)

    # 2) Fontes primárias (DOU, CVM) — o diferencial deste hunter
    if include_primary:
        try:
            from .primary_sources import collect_primary_sources
            items = collect_primary_sources()
            articles.extend(items)
            log.info("Fontes primárias: %d itens", len(items))
        except Exception as e:
            log.warning("Fontes primárias falharam: %s", e)

    # 3) RSS
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_fetch_feed, s): s for s in SOURCES}
        for fut in as_completed(futures):
            try:
                articles.extend(fut.result())
            except Exception as e:
                log.warning("Feed future error: %s", e)

    def _better(new: RawArticle, cur: RawArticle) -> bool:
        if (new.published_at is not None) != (cur.published_at is not None):
            return new.published_at is not None
        return len(new.title or "") > len(cur.title or "")

    seen: dict[str, RawArticle] = {}
    for a in articles:
        cur = seen.get(a.url)
        if cur is None or _better(a, cur):
            seen[a.url] = a

    deduped = list(seen.values())
    log.info("Total após dedup: %d artigos (de %d coletados)", len(deduped), len(articles))
    return deduped
