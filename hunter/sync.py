"""
Push para o Supabase via PostgREST.

Regra inviolável: o insert usa `resolution=ignore-duplicates`, NUNCA
merge-duplicates. URL repetida é ignorada por completo, então o `found_at`
original é preservado. Com merge, uma notícia de três dias atrás "renasceria"
como recente toda vez que o feed a devolvesse, e a ordenação do dashboard
viraria ficção.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import requests

from .config import LLM_LOOKBACK_DAYS, SUPABASE_TABLE

log = logging.getLogger(__name__)

BATCH_SIZE = 100
RUNS_TABLE = "hunter_runs"
HEALTH_TABLE = "source_health"
JUDGED_TABLE = "judged_urls"


def _creds() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    # Projeto migrado para chaves publishable/secret em jul/2026; aceita os dois
    # nomes para não quebrar quem ainda tem o secret antigo cadastrado.
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_KEY", "")
    return url, key


def _headers(extra: dict | None = None) -> dict:
    _, key = _creds()
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def configured() -> bool:
    url, key = _creds()
    return bool(url and key)


def _select_urls(tabela: str, campo_data: str, since: str) -> set[str]:
    url, key = _creds()
    try:
        r = requests.get(
            f"{url}/rest/v1/{tabela}",
            params={"select": "url", campo_data: f"gte.{since}", "limit": "20000"},
            headers=_headers(),
            timeout=30,
        )
        if not r.ok:
            log.warning("%s: HTTP %s — %s", tabela, r.status_code, r.text[:160])
            return set()
        return {row["url"] for row in r.json() if row.get("url")}
    except Exception as e:
        log.warning("%s falhou: %s", tabela, e)
        return set()


def known_urls() -> set[str]:
    """
    URLs que o pipeline já processou na janela de lookback — aprovadas E
    reprovadas.

    É o que impede o gate de LLM de re-julgar o mesmo artigo a cada run de
    5 minutos. Duas chamadas, custo desprezível, e economiza ordens de
    magnitude de cota de IA.

    Ler SÓ a tabela `articles` cobria metade do problema: ela guarda apenas o
    aprovado, então tudo que o LLM reprovou voltava ao gate indefinidamente
    (medido em 03/ago/2026: 79 de 81 "novos" num run eram rejeitados antigos).
    Se `judged_urls` não existir ainda, a função degrada para o comportamento
    antigo em vez de quebrar.
    """
    url, key = _creds()
    if not url or not key:
        return set()
    since = (datetime.now(timezone.utc) - timedelta(days=LLM_LOOKBACK_DAYS)).isoformat()

    aprovadas = _select_urls(SUPABASE_TABLE, "found_at", since)
    reprovadas = _select_urls(JUDGED_TABLE, "judged_at", since)
    log.info("known_urls: %d aprovadas + %d reprovadas nos últimos %d dias",
             len(aprovadas), len(reprovadas), LLM_LOOKBACK_DAYS)
    return aprovadas | reprovadas


def record_rejected(urls: list[str]) -> int:
    """Registra o que o LLM reprovou, para não re-julgar no próximo run.

    `ignore-duplicates` preserva o `judged_at` original: o que importa é quando
    o artigo foi visto pela primeira vez, para a purga por idade funcionar.
    """
    url, key = _creds()
    if not url or not key or not urls:
        return 0
    total = 0
    for i in range(0, len(urls), BATCH_SIZE):
        lote = [{"url": u} for u in urls[i:i + BATCH_SIZE]]
        try:
            r = requests.post(
                f"{url}/rest/v1/{JUDGED_TABLE}",
                json=lote,
                headers=_headers({"Prefer": "resolution=ignore-duplicates,return=minimal"}),
                timeout=30,
            )
            if not r.ok:
                log.warning("judged_urls: HTTP %s — %s", r.status_code, r.text[:160])
                continue
            total += len(lote)
        except Exception as e:
            log.warning("judged_urls falhou: %s", e)
    if total:
        log.info("judged_urls: %d reprovados registrados", total)
    return total


def push_articles(articles: list[dict]) -> int:
    """Insere artigos preservando o found_at da primeira descoberta."""
    url, key = _creds()
    if not url or not key:
        log.warning("SUPABASE_URL/SUPABASE_SECRET_KEY ausentes — sync desabilitado")
        return 0
    if not articles:
        return 0

    endpoint = f"{url}/rest/v1/{SUPABASE_TABLE}"
    headers = _headers({
        "Prefer": "resolution=ignore-duplicates,return=minimal,count=exact",
    })

    total = 0
    for i in range(0, len(articles), BATCH_SIZE):
        batch = articles[i:i + BATCH_SIZE]
        try:
            r = requests.post(endpoint, json=batch, headers=headers, timeout=30)
            if not r.ok:
                log.warning("Supabase erro %s: %s", r.status_code, r.text[:200])
                continue
            inserted = len(batch)
            cr = r.headers.get("content-range", "")
            if "/" in cr:
                try:
                    inserted = int(cr.split("/")[-1])
                except ValueError:
                    pass
            total += inserted
            log.info("Supabase lote %d: %d enviados -> %d novos", i // BATCH_SIZE + 1, len(batch), inserted)
        except Exception as e:
            log.warning("Supabase request falhou: %s", e)
    return total


def record_run(articles_new: int, articles_seen: int = 0) -> bool:
    """
    Timestamp do run — é o que o dashboard usa para "sincronizado há X min".
    Gravado SEMPRE, inclusive quando o run não trouxe novidade.
    """
    url, key = _creds()
    if not url or not key:
        return False
    try:
        r = requests.post(
            f"{url}/rest/v1/{RUNS_TABLE}",
            json={"articles_new": articles_new, "articles_seen": articles_seen},
            headers=_headers({"Prefer": "return=minimal"}),
            timeout=15,
        )
        if not r.ok:
            log.warning("hunter_runs: HTTP %s — %s", r.status_code, r.text[:160])
            return False
        return True
    except Exception as e:
        log.warning("hunter_runs falhou: %s", e)
        return False


def record_source_health(counts: dict[str, int]) -> bool:
    """
    Upsert do sinal de vida por fonte. É o que permite ao watchdog distinguir
    "fonte quieta" (viva, sem novidade) de "fonte morta" (parou de responder).
    """
    url, key = _creds()
    if not url or not key or not counts:
        return False
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for source, n in counts.items():
        row = {"source": source, "last_attempt": now, "last_count": n}
        if n > 0:
            row["last_ok"] = now   # em 0, o last_ok antigo é preservado e envelhece
        rows.append(row)
    try:
        r = requests.post(
            f"{url}/rest/v1/{HEALTH_TABLE}?on_conflict=source",
            json=rows,
            headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
            timeout=20,
        )
        if not r.ok:
            log.warning("source_health: HTTP %s — %s", r.status_code, r.text[:160])
            return False
        log.info("source_health: %d fontes registradas", len(rows))
        return True
    except Exception as e:
        log.warning("source_health falhou: %s", e)
        return False
