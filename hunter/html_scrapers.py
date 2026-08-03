"""
Scrapers de sites sem RSS utilizável — gov.br (Plone) e entidades setoriais.

Seleção de artigo por PADRÃO DE URL (`href_re`), nunca por classe CSS.

── Mudança de 30/jul/2026, depois do primeiro diagnóstico ao vivo ────────────
Cada fonte agora declara uma LISTA de URLs candidatas em vez de uma só. O
scraper tenta na ordem e fica com a primeira que devolver artigos. Motivo: o
padrão de URL do gov.br varia por órgão e por época (o MEC põe ano e mês no
caminho, a ANVISA põe só o ano, o INEP põe a seção antes de "noticias"), e
errar a URL fazia a fonte devolver zero em silêncio. Com candidatas, o código
descobre sozinho qual está viva em vez de depender de eu ter adivinhado certo.

Datas: `_extract_date_nearby` sobe até 4 níveis a partir do <a> e tenta, nesta
ordem: <time datetime>, seletores conhecidos de Plone/portais e — novidade —
varredura de texto do próprio nó. Foi o diagnóstico que mostrou a necessidade:
no CADE a data mora como texto solto dentro de <div class="conteudo">, que não
casava nenhum seletor, e por isso TODOS os scrapers voltavam com dated=0.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .fetcher import RawArticle, clean_url, http_get, strip_html

log = logging.getLogger(__name__)

# ── Fontes ────────────────────────────────────────────────────────────────────
# urls    → candidatas, tentadas em ordem; vence a primeira que der artigos.
# href_re → regex do CAMINHO da URL que caracteriza um artigo.
# filter  → False = órgão/entidade do setor, 100% no escopo, aceita tudo.
#
# Comentários de "verificado em 30/jul/2026" vêm do --check-sources + diagnose.
HTML_SOURCES = [
    # ══ ANS — REMOVIDA. Não há caminho por HTML. ════════════════════════════
    # Esgotadas 7 saídas, todas verificadas ao vivo em 30/jul/2026:
    #   /assuntos/noticias              200, 55.388 b, ZERO link de notícia (casca de SPA)
    #   /assuntos/noticias/operadoras   200, 55.388 b — a MESMA casca
    #   /assuntos/noticias/consumidor   200, 203.329 b mas 0 link casando: o peso
    #                                   é CSS/JS embutido, a lista continua vindo por JS
    #   /assuntos/noticias/geral        404
    #   /assuntos/noticias/RSS          200 mas text/html, 55.388 b (a casca de novo)
    #   /assuntos/noticias/rss.xml      200 mas text/html, 55.388 b
    #   /assuntos/noticias/rss e /@@rss 404 · ++api++ 404
    #
    # A ANS entra no feed pelo DOU, que é fonte MELHOR para o que importa: RN, IN
    # e resoluções chegam como texto oficial no dia da publicação, não como
    # release reescrito. O que se perde é a comunicação institucional, que é o
    # conteúdo menos acionável da agência.
    #
    # Para reabrir: o sitemap (/ans/pt-br/sitemap.xml, 328 <loc>) responde, mas
    # não traz título — só URL. Manchete derivada de slug é ruim demais para um
    # feed de research. A alternativa real seria navegador headless, que traz
    # Playwright para o repo inteiro por uma fonte só. Não compensa.

    # ══ MEC ══════════════════════════════════════════════════════════════════
    # Verificado: 30 links em /mec/pt-br/assuntos/noticias/2026/julho/<slug>.
    # O regex antigo não previa os segmentos de ano e mês → 0 artigos.
    {
        "label": "MEC",
        "urls": ["https://www.gov.br/mec/pt-br/assuntos/noticias"],
        "href_re": r"/mec/pt-br/assuntos/noticias/\d{4}/[a-zç]+/[a-z0-9\-]{8,}",
        "filter": False,
    },

    # ══ INEP ═════════════════════════════════════════════════════════════════
    # Verificado: 20 links em /inep/pt-br/<seção>/noticias/<slug> — há uma seção
    # antes de "noticias", não o /assuntos/ que eu tinha suposto.
    {
        "label": "INEP",
        "urls": ["https://www.gov.br/inep/pt-br/assuntos/noticias"],
        "href_re": r"/inep/pt-br/[a-z0-9\-]+/noticias/[a-z0-9\-]{10,}",
        "filter": False,
    },

    # ══ ANVISA ═══════════════════════════════════════════════════════════════
    # Verificado: 27 links em /anvisa/pt-br/assuntos/noticias-anvisa/<ano>/<slug>.
    # O regex antigo só pegava os 4 sem o segmento de ano.
    {
        "label": "ANVISA",
        "urls": ["https://www.gov.br/anvisa/pt-br/assuntos/noticias-anvisa"],
        "href_re": r"/anvisa/pt-br/assuntos/noticias-anvisa/(?:\d{4}/)?[a-z0-9\-]{8,}",
        "filter": False,
    },

    # ══ CADE ═════════════════════════════════════════════════════════════════
    # Verificado OK: 29 artigos em /cade/pt-br/assuntos/noticias/<slug>.
    {
        "label": "CADE",
        "urls": ["https://www.gov.br/cade/pt-br/assuntos/noticias"],
        "href_re": r"/cade/pt-br/assuntos/noticias/(?:\d{4}/)?[a-z0-9\-]{12,}",
        "filter": False,
    },

    # ══ ANAHP ════════════════════════════════════════════════════════════════
    # Verificado OK: 5 artigos.
    {
        "label": "ANAHP",
        "urls": ["https://www.anahp.com.br/noticias/", "https://www.anahp.com.br/imprensa/"],
        "href_re": r"/(?:noticias|imprensa)/[a-z0-9\-]{10,}",
        "filter": False,
    },

    # ══ IESS ═════════════════════════════════════════════════════════════════
    # /noticia era 404. A sondagem mostrou que o conteúdo mora em
    # /espaco-imprensa/ e /biblioteca/ (44 KB, 18 links de dois segmentos).
    # Vale pelos estudos e TDs, que são insumo de tese, não notícia.
    {
        "label": "IESS",
        "urls": [
            "https://www.iess.org.br/espaco-imprensa/press-release",
            "https://www.iess.org.br/espaco-imprensa/iess-na-midia",
        ],
        "href_re": r"/(?:espaco-imprensa|biblioteca)/[a-z0-9\-]+/[a-z0-9\-]{8,}",
        "filter": False,
    },

    # ── REMOVIDAS em 30/jul/2026, com motivo ─────────────────────────────────
    # FenaSaúde  → SPA: a página tem 4 <a> no total, 1 interno. Só com navegador
    #              headless, e a entidade publica pouco demais para justificar.
    # Abramge    → ConnectionReset na raiz e em /feed/. Servidor derruba a conexão.
    # ABMES      → HTTP 500 na raiz, erro de SSL em /rss.
    # ANS Legislação → /assuntos/legislacao é 404; o caminho certo ainda não foi
    #              confirmado. As RN/IN chegam pelo DOU de qualquer forma, que é
    #              a fonte melhor (texto oficial, no dia).
]

_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_BR_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")

_DATE_SELECTORS = (
    ".documentPublished", ".documentModified", ".data-noticia", ".conteudo",
    ".date", ".news-date", ".post-date", ".entry-date", ".subtitle-doc",
    '[class*="date"]', '[class*="Data"]', '[class*="data"]',
)


def _try_date(y: int, mo: int, d: int):
    try:
        if 2015 <= y <= 2040 and 1 <= mo <= 12 and 1 <= d <= 31:
            return datetime(y, mo, d, tzinfo=timezone.utc)
    except ValueError:
        pass
    return None


def _date_from_text(raw: str):
    m = _ISO_DATE_RE.search(raw or "")
    if m:
        r = _try_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if r:
            return r
    m = _BR_DATE_RE.search(raw or "")
    if m:
        r = _try_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if r:
            return r
    return None


def _extract_date_nearby(anchor):
    """Sobe até 4 níveis a partir do <a> procurando a data de publicação."""
    node = anchor.parent
    for _ in range(4):
        if node is None or getattr(node, "name", None) in (None, "html", "body", "[document]"):
            break

        t = node.find("time")
        if t is not None:
            r = _date_from_text(t.get("datetime", "") or t.get_text(strip=True))
            if r:
                return r

        for sel in _DATE_SELECTORS:
            el = node.select_one(sel)
            if el is not None:
                r = _date_from_text(el.get("datetime", "") or el.get_text(" ", strip=True)[:200])
                if r:
                    return r

        # Varredura de texto do próprio nó. É o que faltava: no CADE a data é
        # texto solto em <div class="conteudo">. Limitado a 300 chars para não
        # capturar uma data qualquer de outro card mais abaixo na página.
        r = _date_from_text(node.get_text(" ", strip=True)[:300])
        if r:
            return r

        node = node.parent
    return None


def _scrape_url(label: str, url: str, href_re: re.Pattern, needs_filter: bool) -> list[RawArticle]:
    try:
        status, content = http_get(url, timeout=30)
        if status != 200 or not content:
            log.info("HTML [%s] HTTP %s em %s", label, status, url)
            return []
        soup = BeautifulSoup(content, "html.parser")
    except Exception as e:
        log.info("HTML [%s] exceção em %s: %s", label, url, e)
        return []

    now = datetime.now(timezone.utc)
    seen: dict[str, RawArticle] = {}

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = clean_url(urljoin(url, href))
        if not href_re.search(urlparse(absolute).path):
            continue

        title = strip_html(a.get_text(" "))
        if len(title) < 15 or title.count(" ") < 2:
            title = strip_html(a.get("title", "") or a.get("aria-label", ""))
        if len(title) < 15:
            continue
        if absolute in seen:
            continue

        seen[absolute] = RawArticle(
            url=absolute,
            domain=urlparse(absolute).netloc.replace("www.", ""),
            source_name=label,
            title=title,
            snippet="",
            published_at=_extract_date_nearby(a),
            found_at=now,
            needs_filter=needs_filter,
        )
    return list(seen.values())


def _scrape_one(source: dict) -> list[RawArticle]:
    """Tenta as URLs candidatas em ordem; fica com a primeira que der artigos."""
    label = source["label"]
    href_re = re.compile(source["href_re"], re.IGNORECASE)
    needs_filter = source.get("filter", True)
    urls = source.get("urls") or [source["url"]]

    tentadas = []
    for url in urls:
        items = _scrape_url(label, url, href_re, needs_filter)
        tentadas.append(f"{url} -> {len(items)}")
        if items:
            dated = sum(1 for i in items if i.published_at)
            log.info("HTML OK [%s] -> %d artigos (%d com data) via %s",
                     label, len(items), dated, url)
            return items

    log.warning("HTML VAZIO [%s]: nenhuma candidata deu artigo | %s",
                label, " | ".join(tentadas))
    return []


def collect_html_sources() -> list[RawArticle]:
    out: list[RawArticle] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(_scrape_one, s): s for s in HTML_SOURCES}
        for fut in as_completed(futures):
            try:
                out.extend(fut.result())
            except Exception as e:
                log.warning("HTML future error: %s", e)
    return out
