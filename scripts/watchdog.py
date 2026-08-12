#!/usr/bin/env python3
"""
Watchdog — falha (exit 1) quando alguma fonte fica muda tempo demais.

O GitHub manda e-mail ao dono do repo quando um workflow falha. É o alarme mais
barato que existe: zero infra, zero custo.

O ponto cego que isto cobre: uma fonte que para de responder NÃO derruba o
hunter — ele continua rodando feliz, só com menos notícia. Sem watchdog, você
descobre semanas depois que a ANS sumiu do feed.

Limiares diferentes por perfil de fonte: a ANS publica várias vezes por dia,
o Semesp publica uma vez por semana. Um limiar único geraria alarme falso
constante — e alarme que toca à toa deixa de ser lido.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:
    pass

# Horas sem NENHUMA coleta bem-sucedida até considerar a fonte morta.
LIMIARES = {
    # diárias, alto volume
    "Valor Econômico": 12, "InfoMoney": 12, "Folha de S.Paulo": 12,
    "UOL Economia": 12, "CNN Brasil": 12, "Metrópoles": 12, "Estadão": 12,
    "O Globo": 12, "Lauro Jardim": 24,
    "Exame": 24, "Money Times": 24, "Poder360": 24, "Agência Brasil": 24,
    # órgãos e fontes primárias — silêncio longo aqui é sintoma real
    "ANS": 72, "ANVISA": 72, "MEC": 72, "CADE": 72, "INEP": 96,
    "DOU — Diário Oficial": 48,
    "CVM — Fato Relevante": 96,
    # setoriais e entidades: publicam pouco por natureza
    "Medicina S/A": 72, "Saúde Business": 96, "Futuro da Saúde": 96,
    "Setor Saúde": 96, "Healthcare Management": 120,
    "Portal Hospitais Brasil": 120, "Panorama Farmacêutico": 96,
    "Desafios da Educação": 168, "Revista Ensino Superior": 168,
    "Semesp": 168, "ANAHP": 168, "FenaSaúde": 168, "IESS": 240,
    "Abramge": 240, "ABMES": 240,
}
LIMIAR_PADRAO = 96
LIMIAR_RUN = 2   # horas sem nenhum run do hunter


def main() -> int:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("ERRO: SUPABASE_URL / SUPABASE_SECRET_KEY não configurados")
        return 1

    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    now = datetime.now(timezone.utc)
    problemas: list[str] = []

    # 1) O hunter está rodando?
    try:
        r = requests.get(f"{url}/rest/v1/hunter_runs",
                         params={"select": "ran_at", "order": "ran_at.desc", "limit": "1"},
                         headers=h, timeout=20)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            problemas.append("hunter_runs vazia — o hunter nunca rodou com sucesso")
        else:
            last = datetime.fromisoformat(rows[0]["ran_at"].replace("Z", "+00:00"))
            atraso = (now - last).total_seconds() / 3600
            if atraso > LIMIAR_RUN:
                problemas.append(f"último run há {atraso:.1f}h (limiar {LIMIAR_RUN}h) — a corrente do hunt-loop quebrou")
            else:
                print(f"OK  hunter rodou há {atraso*60:.0f} min")
    except Exception as e:
        problemas.append(f"não consegui ler hunter_runs: {e}")

    # 2) Alguma fonte ficou muda?
    try:
        r = requests.get(f"{url}/rest/v1/source_health",
                         params={"select": "source,last_ok,last_attempt"},
                         headers=h, timeout=20)
        r.raise_for_status()
        for row in r.json():
            src = row.get("source", "?")
            limiar = LIMIARES.get(src, LIMIAR_PADRAO)
            raw = row.get("last_ok")
            if not raw:
                problemas.append(f"[{src}] nunca coletou nada")
                continue
            last_ok = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            horas = (now - last_ok).total_seconds() / 3600
            if horas > limiar:
                problemas.append(f"[{src}] sem coleta há {horas:.0f}h (limiar {limiar}h)")
            else:
                print(f"OK  {src}: última coleta há {horas:.0f}h")
    except Exception as e:
        problemas.append(f"não consegui ler source_health: {e}")

    if problemas:
        print("\n" + "=" * 70)
        print("WATCHDOG — problemas encontrados:")
        for p in problemas:
            print("  [X] " + p)
        print("=" * 70)
        return 1

    print("\nWatchdog OK — hunter vivo e todas as fontes dentro do limiar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
