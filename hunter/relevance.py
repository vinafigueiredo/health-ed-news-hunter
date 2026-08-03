"""
Gate de relevância por LLM — cascata de provedores com free tier.

Por que existe: o filtro de keyword é grosso de propósito. "Amil" casa tanto no
resultado trimestral quanto na nota de falecimento de um ex-diretor. O LLM lê
título + resumo e responde uma coisa só: isso interessa a quem cobre saúde
suplementar e educação superior como tese de investimento?

Três decisões de projeto que valem mais que o prompt:

1. EM LOTE. Um artigo por chamada queima a cota de qualquer free tier em
   minutos (o loop roda a cada 5 min). Vão LLM_BATCH_SIZE artigos por chamada,
   numerados, e a resposta é um JSON de índices.

2. SÓ O QUE É NOVO. Antes de chamar a IA, hunt.py já removeu as URLs que o
   banco conhece. Sem isso, o mesmo artigo seria julgado ~288 vezes por dia.

3. FAIL-OPEN. Erro de API, cota estourada, JSON quebrado → o lote inteiro passa.
   Um provedor fora do ar não pode esvaziar o feed em silêncio; melhor deixar
   passar ruído do que perder notícia sem ninguém perceber.

A cascata tenta os provedores na ordem até um responder. Todos têm plano
gratuito; nenhum cartão é necessário.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

import requests

from .config import LLM_BATCH_SIZE

log = logging.getLogger(__name__)

TIMEOUT = 45
RETRY_429_MAX_SLEEP = 25   # teto do backoff. O loop roda a cada 5 min: esperar
                           # mais que isso por lote atrasaria o run inteiro.

# CHAVES que estouraram a cota diária neste run — não provedores. Guardar por
# chave é o que permite ter várias contas do mesmo provedor: quando a primeira
# Groq acaba, a segunda assume sem sair do modelo. Quando o 429 pede espera
# maior que o teto, insistir a cada lote é jogar requisição fora e martelar uma
# API que já disse não (em 03/ago/2026 a Groq pediu 1394s no primeiro lote e o
# run seguiu tentando nos 12 seguintes). Some no fim do processo — o loop chama
# `hunt.py` do zero a cada iteração, então a cota é reavaliada naturalmente.
_ESGOTADOS: set[str] = set()


def _limpa(v: str) -> str:
    """Descarta lixo de template.

    O `.env.example` já teve comentário na mesma linha da chave. Com valor
    vazio, o python-dotenv devolve o COMENTÁRIO como valor — e o coletor
    passava a achar que Cerebras/Mistral/Gemini estavam configurados, levando
    401 e gastando ~12s por lote antes de cair no fail-open. Uma chave de API
    nunca tem '#', espaço ou '://'; qualquer um deles é template mal preenchido.
    """
    v = (v or "").strip()
    if not v or v.startswith("#") or "://" in v or " " in v:
        return ""
    return v


def _keys(env_name: str) -> list[str]:
    """Todas as chaves de um provedor: GROQ_API_KEY, GROQ_API_KEY_2, _3...

    Free tier é cota POR CONTA. Duas contas do mesmo provedor dobram o teto
    diário, e trocar de chave quando a primeira estoura é mais barato que
    trocar de provedor — mesmo modelo, mesmo comportamento do prompt. Basta
    acrescentar `_2`, `_3` no `.env`; nada mais precisa mudar.
    """
    encontradas = [_limpa(os.environ.get(env_name, ""))]
    n = 2
    while True:
        v = _limpa(os.environ.get(f"{env_name}_{n}", ""))
        if not v:
            break
        encontradas.append(v)
        n += 1
    return [k for k in encontradas if k]


def _key(env_name: str) -> str:
    """Primeira chave utilizável do provedor, pulando as já esgotadas no run."""
    for k in _keys(env_name):
        if k not in _ESGOTADOS:
            return k
    return ""

SYSTEM_PROMPT = (
    "Você filtra notícias para uma mesa de equity research que cobre DOIS "
    "setores brasileiros: saúde suplementar (operadoras de planos, hospitais, "
    "medicina diagnóstica, regulação da ANS) e educação superior privada "
    "(grupos de ensino, EAD, regulação do MEC).\n\n"
    "É RELEVANTE quando a notícia ajuda a acompanhar:\n"
    "- operadoras, hospitais, laboratórios ou grupos de ensino: resultado, "
    "M&A, mudança de controle, captação, reestruturação, estratégia comercial, "
    "rede credenciada, portfólio de produtos, precificação;\n"
    "- regulação que muda a economia do setor: ANS (rol, reajuste, revisão "
    "técnica, portabilidade, solvência), ANVISA, CADE, MEC/SERES (vagas de "
    "medicina, credenciamento, EAD, FIES/ProUni), decisões judiciais de massa;\n"
    "- dinâmica setorial com leitura de mercado: sinistralidade, inflação "
    "médica, judicialização, ocupação hospitalar, evasão, captação de alunos.\n\n"
    "NÃO é relevante: saúde pública/SUS sem efeito sobre o setor privado, "
    "campanha de vacinação, dicas de bem-estar, nota de falecimento, agenda de "
    "eventos, matéria de serviço ('como pedir reembolso'), vestibular/gabarito, "
    "notícia policial, e qualquer texto onde a empresa aparece só de passagem.\n\n"
    "TAMBÉM NÃO é relevante — vigilância sanitária de PRODUTO. A ANVISA publica "
    "dezenas de atos por dia deste tipo e nenhum move tese de plano de saúde ou "
    "de grupo de ensino: registro, renovação ou cancelamento de medicamento, "
    "cosmético, saneante, alimento, suplemento ou dispositivo; apreensão, "
    "recolhimento, suspensão de lote, proibição de produto irregular ou "
    "falsificado; certificação de boas práticas; fiscalização de "
    "estabelecimento. A ANVISA só interessa quando o ato muda a REGRA do "
    "mercado — RDC ou consulta pública sobre precificação, rol, telessaúde, "
    "dispositivo de alto custo — ou quando envolve nominalmente uma companhia "
    "listada.\n\n"
    "Ato do Diário Oficial: julgue pelo TEXTO do ato, no snippet, não pelo "
    "número no título. Portaria de credenciamento, recredenciamento, "
    "descredenciamento, autorização de curso ou vagas de medicina é relevante; "
    "nomeação, designação de servidor, convênio administrativo e retificação "
    "puramente formal, não.\n\n"
    "Na dúvida, marque como relevante. Responda SOMENTE com um objeto JSON "
    'no formato {"1": true, "2": false, ...}, uma chave por item recebido, '
    "sem texto antes ou depois."
)

# (env da chave, rótulo, função de chamada) — ordem da cascata.
# Groq e Cerebras primeiro: são os mais rápidos e com cota mais generosa.
_PROVIDER_ORDER = ["groq", "cerebras", "mistral", "gemini"]

_OPENAI_COMPAT = {
    "groq": {
        "env": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
    },
    "cerebras": {
        "env": "CEREBRAS_API_KEY",
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "model": os.environ.get("CEREBRAS_MODEL", "llama-3.3-70b"),
    },
    "mistral": {
        "env": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "model": os.environ.get("MISTRAL_MODEL", "mistral-small-latest"),
    },
}

# Verificado em 03/ago/2026 com chave nova do AI Studio: `gemini-2.0-flash` dá
# 429 com "limit: 0" (o free tier não cobre mais esse modelo), e `gemini-2.5-*`
# devolve 404 "no longer available to new users". Os `-lite` respondem e têm a
# cota mais generosa — que é o que importa num fallback acionado justamente
# quando o provedor principal estourou o limite. Alias `-latest` de propósito:
# o Google aposenta modelo pinado sem aviso, e aqui disponibilidade vale mais
# que estabilidade de comportamento.
_ENV_DE = {
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

_GEMINI = {
    "env": "GEMINI_API_KEY",
    "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    "model": os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest"),
}


def _sleep_429(r: requests.Response, name: str, key: str) -> bool:
    """Espera o tempo pedido pelo provedor. False se não valer a pena esperar.

    Sem isto, o 429 do Groq derrubava o lote para o fail-open — e fail-open é
    lote inteiro passando SEM julgamento. Medido em 03/ago/2026: 5 de 23 lotes
    (60 artigos) entravam no feed sem nenhum gate. O limite do free tier é por
    minuto, então esperar poucos segundos resolve; desistir, não.
    """
    espera = r.headers.get("retry-after") or ""
    try:
        segundos = float(espera)
    except ValueError:
        # Groq manda o tempo no corpo ("Please try again in 6.9s")
        m = re.search(r"try again in ([\d.]+)s", r.text or "")
        segundos = float(m.group(1)) if m else 5.0
    if segundos > RETRY_429_MAX_SLEEP:
        _ESGOTADOS.add(key)
        restantes = len([k for k in _keys(_ENV_DE[name]) if k not in _ESGOTADOS])
        log.info("LLM[%s] 429 pedindo %.0fs — cota da chave esgotada. "
                 "Chaves ainda disponíveis neste provedor: %d", name, segundos, restantes)
        return False
    log.info("LLM[%s] 429 — aguardando %.1fs", name, segundos)
    time.sleep(segundos + 0.5)
    return True


def _call_openai_compat(name: str, user_prompt: str) -> str | None:
    cfg = _OPENAI_COMPAT[name]
    key = _key(cfg["env"])
    if not key:
        return None

    for tentativa in (1, 2):
        try:
            r = requests.post(
                cfg["url"],
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": cfg["model"],
                    "temperature": 0,
                    "max_tokens": 800,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=TIMEOUT,
            )
            if r.status_code == 429 and tentativa == 1 and _sleep_429(r, name, key):
                continue
            if not r.ok:
                log.info("LLM[%s] HTTP %s: %s", name, r.status_code, r.text[:160])
                return None
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log.info("LLM[%s] exceção: %s", name, e)
            return None
    return None


def _call_gemini(user_prompt: str) -> str | None:
    # _key já pula chave esgotada; "" significa que todas as do Gemini acabaram.
    key = _key(_GEMINI["env"])
    if not key:
        return None
    def _post():
        return requests.post(
            _GEMINI["url"].format(model=_GEMINI["model"]),
            params={"key": key},
            headers={"Content-Type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 800},
            },
            timeout=TIMEOUT,
        )

    try:
        for tentativa in (1, 2):
            r = _post()
            if r.status_code == 429 and tentativa == 1 and _sleep_429(r, "gemini", key):
                continue
            break
        if not r.ok:
            log.info("LLM[gemini] HTTP %s: %s", r.status_code, r.text[:160])
            return None
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        log.info("LLM[gemini] exceção: %s", e)
        return None


def _ask(user_prompt: str) -> tuple[str | None, str]:
    """Percorre a cascata. Devolve (resposta, provedor_que_respondeu)."""
    for name in _PROVIDER_ORDER:
        out = _call_gemini(user_prompt) if name == "gemini" else _call_openai_compat(name, user_prompt)
        if out:
            return out, name
    return None, ""


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse(answer: str, n: int) -> dict[int, bool] | None:
    """Extrai o JSON mesmo se o modelo embrulhar em ``` ou texto."""
    m = _JSON_RE.search(answer or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    out: dict[int, bool] = {}
    for k, v in data.items():
        try:
            i = int(str(k).strip())
        except ValueError:
            continue
        if 1 <= i <= n:
            out[i] = bool(v) if isinstance(v, bool) else str(v).strip().lower() in ("true", "sim", "1", "yes")
    return out or None


def enabled() -> bool:
    return any(_keys(cfg["env"]) for cfg in list(_OPENAI_COMPAT.values()) + [_GEMINI])


LLM_BATCH_SIZE_EFETIVO = LLM_BATCH_SIZE


def dump_para_julgamento(articles: list[dict]) -> dict:
    """Serializa o que iria ao gate, do jeito que o gate veria.

    Existe para calibrar sem queimar cota: o free tier de todos os provedores é
    diário, e um dia de testes o esgota (aconteceu com a Groq em 03/ago/2026).
    Julgar por fora e devolver com `--llm-verdicts` roda o pipeline inteiro com
    zero chamada de API — e serve de gabarito para comparar com o LLM depois.
    """
    itens = []
    for i, a in enumerate(articles):
        itens.append({
            "n": i + 1,
            "lote": i // LLM_BATCH_SIZE + 1,
            "url": a.get("url", ""),
            "fonte": a.get("source_name", ""),
            "titulo": a.get("title", ""),
            "snippet": (a.get("snippet") or "")[:600],
        })
    return {
        "prompt_do_sistema": SYSTEM_PROMPT,
        "lotes": (len(articles) + LLM_BATCH_SIZE - 1) // LLM_BATCH_SIZE,
        "formato_esperado": "JSON {\"<url>\": true|false}; url ausente = aprovado (fail-open)",
        "itens": itens,
    }


def judge_batch(articles: list[dict]) -> list[dict]:
    """
    Recebe artigos (dicts do filter) e devolve só os relevantes.

    Sem nenhuma chave configurada, devolve tudo — o pipeline funciona sem IA,
    só com mais ruído.
    """
    if not articles:
        return []
    if not enabled():
        log.warning("Nenhuma chave de LLM configurada — gate de relevância DESLIGADO.")
        return articles

    kept: list[dict] = []
    total_batches = (len(articles) + LLM_BATCH_SIZE - 1) // LLM_BATCH_SIZE

    for b in range(total_batches):
        chunk = articles[b * LLM_BATCH_SIZE:(b + 1) * LLM_BATCH_SIZE]
        lines = []
        for i, a in enumerate(chunk, 1):
            # 600, não 280: nos atos da SERES o snippet traz a tabela do anexo,
            # e é lá — depois do caminho do órgão e do lead dispositivo — que
            # aparece a mantenedora ("VITRU EDUCACAO S.A."), o único dado que
            # distingue ato relevante de credenciamento de faculdade municipal.
            snippet = (a.get("snippet") or "")[:600]
            lines.append(
                f"{i}. [{a.get('source_name', '')}] {a.get('title', '')}"
                + (f"\n   {snippet}" if snippet else "")
            )
        prompt = (
            f"Julgue os {len(chunk)} itens abaixo.\n\n" + "\n".join(lines)
            + f'\n\nResponda com o JSON de {len(chunk)} chaves ("1".."{len(chunk)}").'
        )

        answer, provider = _ask(prompt)
        verdicts = _parse(answer, len(chunk)) if answer else None

        if verdicts is None:
            # Fail-open: sem veredito confiável, o lote inteiro passa.
            log.warning("LLM lote %d/%d sem resposta utilizável — fail-open (%d artigos passam)",
                        b + 1, total_batches, len(chunk))
            kept.extend(chunk)
            continue

        approved = [a for i, a in enumerate(chunk, 1) if verdicts.get(i, True)]
        kept.extend(approved)
        log.info("LLM[%s] lote %d/%d: %d/%d relevantes",
                 provider, b + 1, total_batches, len(approved), len(chunk))

    log.info("Gate de relevância: %d de %d artigos aprovados", len(kept), len(articles))
    return kept
