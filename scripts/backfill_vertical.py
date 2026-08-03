#!/usr/bin/env python
"""
Preenche `articles.vertical` nas linhas já gravadas.

Rodar UMA vez, depois de aplicar a migration. Artigos novos já entram
classificados pelo `filter.py`; este script só cuida do histórico.

    python scripts/backfill_vertical.py            # aplica
    python scripts/backfill_vertical.py --dry-run  # só mostra a distribuição

É idempotente: recalcula e regrava sempre o mesmo valor para a mesma linha.
Pode rodar de novo depois de mexer nas listas do config.py para reclassificar
o histórico inteiro.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # em CI as variáveis já vêm do ambiente

from hunter.classify import vertical_de_keywords
from hunter.filter import match_keywords

PAGE = 500
TABLE = "articles"


def _creds() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SECRET_KEY ausentes no ambiente ou no .env")
    return url, key


def _headers(key: str, extra: dict | None = None) -> dict:
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    h.update(extra or {})
    return h


def vertical_do_artigo(row: dict) -> str | None:
    """Mesma regra do ingest: keywords primeiro, texto como plano B."""
    v = vertical_de_keywords(row.get("matched_keywords") or [])
    if v is None:
        texto = f"{row.get('title') or ''} {row.get('snippet') or ''}"
        v = vertical_de_keywords(match_keywords(texto))
    return v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="calcula e mostra a distribuição sem gravar")
    args = ap.parse_args()

    url, key = _creds()
    dist = Counter()
    lidos = gravados = 0
    offset = 0

    while True:
        r = requests.get(
            f"{url}/rest/v1/{TABLE}",
            params={
                "select": "url,title,snippet,matched_keywords",
                "order": "found_at.desc",
                "limit": PAGE,
                "offset": offset,
            },
            headers=_headers(key),
            timeout=60,
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break

        lidos += len(rows)
        offset += len(rows)

        for row in rows:
            v = vertical_do_artigo(row)
            dist[v or "indefinida"] += 1
            if args.dry_run or v is None:
                # NULL é o default da coluna: não gasta request para regravar.
                continue
            p = requests.patch(
                f"{url}/rest/v1/{TABLE}",
                params={"url": f"eq.{row['url']}"},
                json={"vertical": v},
                headers=_headers(key, {"Prefer": "return=minimal"}),
                timeout=30,
            )
            if p.ok:
                gravados += 1
            else:
                print(f"  ! falhou {row['url'][:70]}: HTTP {p.status_code} {p.text[:120]}")

        print(f"... {lidos} lidos", flush=True)

        if len(rows) < PAGE:
            break

    print(f"\nLidos: {lidos}   Gravados: {gravados}"
          f"{'  (dry-run, nada foi gravado)' if args.dry_run else ''}")
    print("\nDistribuição:")
    for k, n in dist.most_common():
        print(f"  {k:<12} {n:>5}  ({n / max(lidos, 1):.1%})")


if __name__ == "__main__":
    main()
