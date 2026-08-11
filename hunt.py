#!/usr/bin/env python3
"""
Health & Education News Hunter — ponto de entrada.

    python hunt.py                  roda o pipeline completo
    python hunt.py --no-llm         pula o gate de relevância (só keyword)
    python hunt.py --no-primary     pula DOU/CVM (só imprensa)
    python hunt.py --dry-run        não grava no Supabase; imprime o que passaria
    python hunt.py --check-sources  testa cada fonte e sai (não grava nada)

Ordem interna:
    coletar → filtrar por keyword → remover o que o banco já conhece →
    gate de relevância (LLM) → gravar → registrar run e saúde das fontes

Cada bloco é isolado: se o DOU cair, o resto continua e o log diz o que quebrou.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

# O console do Windows usa cp1252: qualquer caractere fora dessa tabela num log
# derruba o processo com UnicodeEncodeError. No GitHub Actions o padrão já é
# UTF-8, mas rodar local quebrava. Best-effort — em Python antigo, ignora.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# O .env é o caminho local; no GitHub Actions as Secrets já chegam como variável
# de ambiente. `override=False` garante que a Secret do Actions sempre ganha de
# um .env que porventura exista no runner.
try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hunt")

# Fontes que NUNCA passam pelo gate de LLM — o que elas trazem é documento
# oficial da própria companhia coberta, não notícia sobre ela. Ver o bloco 3d.
BYPASS_LLM = frozenset({"CVM — Fato Relevante"})


def main() -> int:
    ap = argparse.ArgumentParser(description="Health & Education News Hunter")
    ap.add_argument("--no-llm", action="store_true", help="pula o gate de relevância")
    ap.add_argument("--no-primary", action="store_true", help="pula DOU/CVM")
    ap.add_argument("--dry-run", action="store_true", help="não grava no Supabase")
    ap.add_argument("--check-sources", action="store_true", help="testa as fontes e sai")
    # Os dois abaixo existem para calibrar SEM queimar cota de free tier: o
    # primeiro despeja exatamente o que iria ao LLM e sai; o segundo aplica
    # vereditos vindos de fora. Assim dá para julgar por outro caminho (revisão
    # humana, outro modelo) e rodar o pipeline inteiro com zero chamada de API.
    ap.add_argument("--dump-llm-input", metavar="ARQUIVO",
                    help="grava em JSON o que iria ao gate de LLM e sai (não chama API, não grava no banco)")
    ap.add_argument("--llm-verdicts", metavar="ARQUIVO",
                    help="usa vereditos de um JSON {url: true|false} em vez de chamar o LLM")
    args = ap.parse_args()

    if args.check_sources:
        from hunter.check_sources import run_check
        return run_check()

    from hunter import sync
    from hunter.fetcher import fetch_all, todas_as_fontes
    from hunter.filter import collapse_serial_articles, filter_articles

    # 1) Coleta
    raw = fetch_all(include_primary=not args.no_primary)
    if not raw:
        log.error("Nenhum artigo coletado — todas as fontes falharam?")
        if not args.dry_run:
            sync.record_run(0, 0)
        return 1

    # Toda fonte configurada entra no balanço, não só as que entregaram: fonte
    # que nunca devolve artigo não ganharia linha em `source_health` e ficaria
    # invisível para o watchdog. Ver fetcher.todas_as_fontes.
    per_source = Counter({f: 0 for f in todas_as_fontes(not args.no_primary)})
    per_source.update(a.source_name for a in raw)

    # 2) Gate barato (keyword)
    filtered = filter_articles(raw)
    log.info("Filtro de keyword: %d de %d artigos passaram", len(filtered), len(raw))

    # 2b) Colapsa matéria serializada por estado (MEC publica FIES uma vez por
    #     UF). Antes do LLM de propósito: o gate julga em lotes e nunca veria as
    #     14 juntas, e cada uma isolada é relevante — além de gastar cota à toa.
    antes = len(filtered)
    filtered = collapse_serial_articles(filtered)
    if len(filtered) != antes:
        log.info("Colapso de seriais: %d -> %d artigos", antes, len(filtered))

    # 3) Remove o que o banco já conhece — ANTES da IA, senão o mesmo artigo
    #    seria julgado a cada run de 5 minutos.
    if not args.dry_run and sync.configured():
        known = sync.known_urls()
        before = len(filtered)
        filtered = [a for a in filtered if a["url"] not in known]
        log.info("Deduplicação contra o banco: %d novos (de %d)", len(filtered), before)

    # 3b) Enriquece os atos da SERES com o texto dispositivo. DEPOIS do dedup:
    #     ato já gravado nunca é rebuscado. Ver primary_sources.DOU_ENRIQUECER.
    if not args.no_primary:
        from hunter.primary_sources import enrich_dou_articles
        enrich_dou_articles(filtered)

    # 3d) A CVM não passa pelo gate. Decisão do Vinicius em 03/ago/2026:
    #     publicação da CVM de companhia coberta ENTRA, sem julgamento — o
    #     recorte já foi feito na lista de companhias, e quem decide se o
    #     documento importa é o analista. Deixar um LLM opinar sobre um Fato
    #     Relevante da Hapvida é adicionar risco de falso negativo em cima da
    #     única fonte do feed que é documento oficial da própria companhia.
    sempre_entram = [a for a in filtered if a.get("source_name") in BYPASS_LLM]
    if sempre_entram:
        filtered = [a for a in filtered if a.get("source_name") not in BYPASS_LLM]
        log.info("Fora do gate de LLM (entram direto): %d de %s",
                 len(sempre_entram), ", ".join(sorted(BYPASS_LLM)))

    # 3c) Despejo para julgamento externo. Sai aqui: não chama API nem grava.
    if args.dump_llm_input:
        import json
        from hunter.relevance import LLM_BATCH_SIZE_EFETIVO, dump_para_julgamento
        payload = dump_para_julgamento(filtered)
        with open(args.dump_llm_input, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        log.info("Despejados %d candidatos em %s (%d lotes de %d). "
                 "Julgue e rode com --llm-verdicts.",
                 len(payload["itens"]), args.dump_llm_input,
                 payload["lotes"], LLM_BATCH_SIZE_EFETIVO)
        return 0

    # 4) Gate caro (LLM)
    if args.no_llm:
        relevant = filtered
        log.info("Gate de relevância pulado (--no-llm)")
    elif args.llm_verdicts:
        import json
        with open(args.llm_verdicts, encoding="utf-8") as fh:
            vereditos = json.load(fh)
        # Ausente = passa. Mesma regra de fail-open do gate real: veredito que
        # não veio não pode virar rejeição silenciosa.
        relevant = [a for a in filtered if vereditos.get(a["url"], True)]
        log.info("Vereditos externos de %s: %d de %d aprovados",
                 args.llm_verdicts, len(relevant), len(filtered))
    else:
        from hunter.relevance import judge_batch
        relevant = judge_batch(filtered)

    # Reincorpora o que nunca foi ao gate (CVM). Fica no fim da lista, mas o
    # feed ordena por found_at no banco — a posição aqui não importa.
    relevant = relevant + sempre_entram

    # 5) Grava
    if args.dry_run:
        log.info("=== DRY RUN — %d artigos passariam ===", len(relevant))
        for a in relevant[:60]:
            kws = ", ".join(a["matched_keywords"][:4])
            log.info("  [%s] %s%s", a["source_name"], a["title"][:110],
                     f"  ({kws})" if kws else "")
        if len(relevant) > 60:
            log.info("  ... e mais %d", len(relevant) - 60)
        return 0

    # Registra os reprovados ANTES de gravar os aprovados: sem isto eles voltam
    # ao gate de LLM a cada run de 5 minutos, para sempre. Ver §9.4b do HANDOVER.
    if not args.no_llm:
        aprovadas = {a["url"] for a in relevant}
        reprovadas = [a["url"] for a in filtered if a["url"] not in aprovadas]
        if reprovadas:
            sync.record_rejected(reprovadas)

    new = sync.push_articles(relevant)
    log.info("Gravados: %d artigos novos", new)

    sync.record_run(new, len(raw))
    sync.record_source_health(dict(per_source))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
