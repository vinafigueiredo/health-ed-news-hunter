"""
Fontes PRIMÁRIAS — o diferencial deste hunter sobre um agregador de imprensa.

Imprensa é o canal mais lento e mais ruidoso do setor. O que efetivamente move
tese chega antes por aqui:

  • DOU (in.gov.br) — resoluções normativas e instruções da ANS, portarias do
    MEC/SERES (credenciamento, vagas de medicina), atos da ANVISA. É o texto
    oficial, no dia em que sai, sem intermediação.

  • CVM / IPE — Fato Relevante e Comunicado ao Mercado das companhias cobertas,
    via os dados abertos da CVM. Sai no minuto do protocolo; a matéria do
    jornal sobre ele sai horas depois.

Ambos são frágeis por natureza (dependem de layout/endpoint de terceiros).
Por isso cada coletor: (a) falha em silêncio SEM derrubar o run, (b) loga um
aviso explícito quando devolve zero, e (c) é coberto pelo `--check-sources`.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from .config import PRIMARY_WINDOW_HOURS, WINDOW_HOURS
from .fetcher import RawArticle, http_get

log = logging.getLogger(__name__)


def _norm(s: str) -> str:
    """Maiúsculas sem acento — para casar nome de companhia da CVM."""
    return "".join(
        c for c in unicodedata.normalize("NFD", (s or "").upper())
        if unicodedata.category(c) != "Mn"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. DOU — Diário Oficial da União (in.gov.br)
# ══════════════════════════════════════════════════════════════════════════════
# A página /leiturajornal embute o índice do dia num <script id="params">
# com JSON. Cada item traz title, urlTitle, pubDate, artType e hierarchyStr
# (o caminho do órgão: "Ministério da Saúde/Agência Nacional de Saúde
# Suplementar/Diretoria Colegiada").
#
# Filtramos por ÓRGÃO (hierarchyStr), não por keyword: é muito mais preciso —
# o do1 publica ~1.000 atos/dia e quase nada é do nosso escopo.

DOU_BASE = "https://www.in.gov.br"
DOU_SECTIONS = ["do1", "do1e"]  # seção 1 (atos normativos) + edição extra

DOU_ORGAOS = (
    "AGENCIA NACIONAL DE SAUDE SUPLEMENTAR",
    "AGENCIA NACIONAL DE VIGILANCIA SANITARIA",
    "MINISTERIO DA EDUCACAO",
    "SECRETARIA DE REGULACAO E SUPERVISAO DA EDUCACAO SUPERIOR",
    "CONSELHO ADMINISTRATIVO DE DEFESA ECONOMICA",
    "INSTITUTO NACIONAL DE ESTUDOS E PESQUISAS EDUCACIONAIS",
)

# A ANVISA sozinha respondia por 98 dos 119 atos do escopo em 3 dias úteis
# (medido em 03/ago/2026) — e NENHUM vinha da Diretoria Colegiada. São registros
# produto a produto das Gerências-Gerais: Inspeção Sanitária 41, Medicamentos 18,
# Fumígenos 9, Cosméticos e Saneantes 9, Toxicologia 4, Alimentos 3. Nada disso
# move tese de saúde suplementar ou de educação; o que move é RDC, e RDC nasce na
# Colegiada. Por isso a ANVISA no DOU passa a exigir uma destas unidades.
# As demais siglas do escopo continuam entrando por completo.
DOU_ANVISA_UNIDADES = (
    "DIRETORIA COLEGIADA",
    "DIRETORIA-COLEGIADA",
    "GABINETE DO DIRETOR-PRESIDENTE",
)

# Dentro do MEC o volume é grande; só interessam atos de regulação de oferta.
DOU_MEC_TERMS = (
    "CREDENCIAMENTO", "RECREDENCIAMENTO", "AUTORIZACAO DE CURSO",
    "RECONHECIMENTO DE CURSO", "MEDICINA", "VAGAS", "SUPERVISAO",
    "EDUCACAO A DISTANCIA", "POLO", "FIES", "PROUNI", "DESCREDENCIAMENTO",
)


def _dou_day(section: str, day: datetime) -> list[RawArticle]:
    url = f"{DOU_BASE}/leiturajornal?data={day.strftime('%d-%m-%Y')}&secao={section}"
    status, content = http_get(url, timeout=30)
    if status != 200 or not content:
        log.warning("DOU [%s %s] HTTP %s", section, day.date(), status)
        return []

    try:
        soup = BeautifulSoup(content, "html.parser")
        tag = soup.find("script", {"id": "params"})
        if tag is None:
            log.warning(
                "DOU [%s %s]: <script id='params'> não encontrado — o in.gov.br "
                "provavelmente mudou o layout. Revalidar o coletor.", section, day.date()
            )
            return []
        payload = json.loads(tag.string or tag.get_text() or "{}")
    except Exception as e:
        log.warning("DOU [%s %s]: JSON ilegível: %s", section, day.date(), e)
        return []

    items = payload.get("jsonArray") or []
    now = datetime.now(timezone.utc)
    out: list[RawArticle] = []

    for it in items:
        hierarchy = _norm(it.get("hierarchyStr", ""))
        if not any(org in hierarchy for org in DOU_ORGAOS):
            continue

        title = (it.get("title") or "").strip()
        if not title:
            continue

        # ANVISA: só a Colegiada. Ver DOU_ANVISA_UNIDADES.
        if "AGENCIA NACIONAL DE VIGILANCIA SANITARIA" in hierarchy:
            if not any(u in hierarchy for u in DOU_ANVISA_UNIDADES):
                continue

        # MEC publica muito ato irrelevante (nomeação, convênio) — recorta.
        if "MINISTERIO DA EDUCACAO" in hierarchy and "SECRETARIA DE REGULACAO" not in hierarchy:
            haystack = _norm(title + " " + it.get("artType", ""))
            if not any(t in haystack for t in DOU_MEC_TERMS):
                continue

        url_title = it.get("urlTitle") or ""
        if not url_title:
            continue

        # O `title` do DOU é só o número do ato ("RESOLUÇÃO-RE nº 2.967") — não
        # dá para julgar relevância com isso, e como needs_filter=False era
        # exatamente isso que chegava ao gate de LLM, que então aprovava tudo
        # pela regra do "na dúvida, relevante". O JSON traz `content` com o
        # texto do ato; o caminho do órgão vira prefixo curto porque distingue
        # SERES/MEC de CADE de ANS num relance.
        corpo = " ".join((it.get("content") or "").split())
        # O content abre repetindo o título e o preâmbulo de competência
        # ("O GERENTE-GERAL ..., no uso das atribuições que lhe confere ...").
        # São ~150 caracteres antes da substância; com o corte de 400 do
        # relevance.py, sobraria só boilerplate.
        if corpo.startswith(title):
            corpo = corpo[len(title):].lstrip(" ,.-")
        corpo = re.sub(r"^.{0,120}?no uso d[ao]s? (?:atribui|compet)\w+[^,]*,\s*", "", corpo)
        orgao = it.get("hierarchyStr", "")
        snippet = f"[{orgao}] {corpo}" if corpo else orgao

        out.append(RawArticle(
            url=f"{DOU_BASE}/web/dou/-/{url_title}",
            domain="in.gov.br",
            source_name="DOU — Diário Oficial",
            title=f"{it.get('artType', '')} — {title}".strip(" —"),
            snippet=snippet[:700],
            published_at=day.replace(hour=6, minute=0, tzinfo=timezone.utc),
            found_at=now,
            needs_filter=False,   # já filtrado por órgão: é tudo do escopo
        ))

    log.info("DOU [%s %s] -> %d atos no escopo (de %d)", section, day.date(), len(out), len(items))
    return out


# ── Enriquecimento: buscar o texto do ato ────────────────────────────────────
# O `content` do índice do in.gov.br é truncado em 403 caracteres — é prévia.
# Nas portarias da SERES esses 403 caracteres são inteiramente citação legal
# ("tendo em vista o Decreto nº 9.235... as Portarias Normativas nº 20 e nº 23"),
# e a substância — QUAL instituição, QUAL curso, quantas vagas — fica de fora.
# Sem isto o feed mostra "PORTARIA SERES/MEC Nº 364" e nada mais, e o gate de
# LLM julga pelo órgão emissor em vez de pelo teor.
#
# Só a SERES/MEC. Nos atos da ANS e do CADE a prévia já abre na substância
# (o despacho começa citando o processo e a operadora), então pagar uma
# requisição por ato ali seria desperdício.
DOU_ENRIQUECER = ("SECRETARIA DE REGULACAO E SUPERVISAO DA EDUCACAO SUPERIOR",)

_RESOLVE_RE = re.compile(r"\bresolve\s*:\s*", re.IGNORECASE)
_ANEXO_RE = re.compile(r"\bANEXO\b")
# Cabeçalho de coluna do anexo: ~110 caracteres idênticos em toda portaria,
# antes do primeiro nome de instituição. É o que separa "sei que autorizaram
# alguma coisa" de "sei que autorizaram MEDICINA para a Estácio".
_CABECALHO_RE = re.compile(
    r"N[ºo°]?\s*de\s*Ordem\b.*?Endere[çc]o de funcionamento do curso\s*",
    re.IGNORECASE | re.DOTALL,
)


def _dou_texto_ato(url: str) -> str:
    status, content = http_get(url, timeout=30)
    if status != 200 or not content:
        return ""
    try:
        soup = BeautifulSoup(content, "html.parser")
        bloco = soup.select_one("div.texto-dou")
        if bloco is None:
            return ""
        texto = " ".join(bloco.get_text(" ").split())
    except Exception:
        return ""

    # A parte dispositiva começa no "resolve:". Antes disso é competência.
    m = _RESOLVE_RE.search(texto)
    corpo = texto[m.end():] if m else texto

    # O que decide se o ato importa é QUAL instituição — e isso mora no ANEXO
    # ("Mantida | Mantenedora"), depois de três artigos de fórmula jurídica. Com
    # o corte de 400 do relevance.py, sem este remonte o LLM (e o leitor do
    # feed) veria só "Fica renovado o reconhecimento do(s) curso(s)... nos
    # termos do art. 10 do Decreto nº 9.235/2017" — verdadeiro para todas.
    a = _ANEXO_RE.search(corpo)
    if not a:
        return corpo
    # O lead dispositivo cabe em ~160 caracteres: o que importa é o verbo
    # ("Fica renovado", "Ficam autorizados", "Ficam indeferidos"). O resto é a
    # mesma citação de decreto em todas as portarias.
    lead = corpo[:a.start()].strip()[:160]
    anexo = _CABECALHO_RE.sub("", corpo[a.start():], count=1)
    return f"{lead} — {anexo}"


def enrich_dou_articles(articles: list[dict], max_workers: int = 6) -> int:
    """Substitui o snippet dos atos da SERES pelo texto dispositivo.

    Chamado DEPOIS da deduplicação contra o banco, de propósito: ato já gravado
    nunca é rebuscado. O DOU publica uma vez por dia, então em regime isto custa
    algumas dezenas de requisições diárias, não uma por iteração do loop.
    Falha em silêncio por item — sem texto, o snippet de prévia continua valendo.
    """
    alvos = [
        a for a in articles
        if a.get("source_name") == "DOU — Diário Oficial"
        and any(o in _norm(a.get("snippet", "")[:200]) for o in DOU_ENRIQUECER)
    ]
    if not alvos:
        return 0

    def _um(a: dict) -> bool:
        texto = _dou_texto_ato(a["url"])
        if not texto:
            return False
        orgao = a.get("snippet", "").split("]")[0].lstrip("[")
        a["snippet"] = f"[{orgao}] {texto}"[:1200]
        return True

    ok = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for fut in as_completed([ex.submit(_um, a) for a in alvos]):
            try:
                ok += bool(fut.result())
            except Exception as e:
                log.info("DOU enriquecimento falhou: %s", e)
    log.info("DOU: texto completo obtido para %d de %d atos da SERES", ok, len(alvos))
    return ok


def collect_dou() -> list[RawArticle]:
    days = max(1, PRIMARY_WINDOW_HOURS // 24)
    today = datetime.now(timezone.utc)
    jobs = [(s, today - timedelta(days=d)) for s in DOU_SECTIONS for d in range(days)]

    out: list[RawArticle] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = [ex.submit(_dou_day, s, d) for s, d in jobs]
        for fut in as_completed(futures):
            try:
                out.extend(fut.result())
            except Exception as e:
                log.warning("DOU future error: %s", e)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 2. CVM — Fato Relevante e Comunicado ao Mercado (dados abertos IPE)
# ══════════════════════════════════════════════════════════════════════════════
CVM_IPE_DIR = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/"
# Verificado 30/jul/2026: a listagem do diretório traz `ipe_cia_aberta_AAAA.ZIP`
# — ZIP, não CSV. Era isso o 404: o coletor pedia .csv. Agora ele DESCOBRE o
# arquivo pela listagem (sobrevive a renomeação) e descompacta se vier zipado.
# O fallback abaixo é só rede de segurança caso a listagem fique indisponível.
CVM_IPE_FALLBACK = CVM_IPE_DIR + "ipe_cia_aberta_{ano}.zip"

# NÃO existe filtro de categoria. Decisão do Vinicius em 03/ago/2026:
# **se é publicação da CVM de uma companhia da cobertura, tem que estar no
# feed** — independentemente de a categoria parecer relevante ou não.
#
# O raciocínio: o recorte já foi feito na lista de companhias. Uma vez que a
# empresa é coberta, quem decide se o documento importa é o analista, não um
# filtro de string nem um LLM. Documento societário que parece burocrático
# ("Assembleia", "Valores Mobiliários art. 11") é justamente onde aparecem
# mudança de controle, participação relevante e recompra.
#
# Volume medido: 1.317 documentos das ~25 cobertas em 213 dias = ~6/dia.
# Perfeitamente absorvível. A versão anterior filtrava por 9 categorias e
# ficava com 308 dos 1.317 — descartava 77% sem ninguém ter decidido isso.
#
# Se um dia precisar cortar, corte AQUI e documente o motivo; não volte a
# filtrar por categoria "relevante" sem falar com o Vinicius.
CVM_CATEGORIAS_EXCLUIDAS: tuple[str, ...] = ()

# Casamento por substring no nome da companhia (normalizado, sem acento).
# Mais robusto que a razão social exata, que muda (incorporação, rebrand).
CVM_COMPANY_TOKENS = (
    # saúde
    "HAPVIDA", "REDE D", "D OR", "FLEURY", "ONCOCLINICAS", "MATER DEI",
    "DIAGNOSTICOS DA AMERICA", "QUALICORP", "KORA", "CM HOSPITALAR", "VIVEO",
    "BLAU", "HYPERA", "ALLIAR", "ODONTOPREV", "SULAMERICA", "SUL AMERICA",
    "PORTO SEGURO", "BRADESCO SEGUROS",
    # educação
    "COGNA", "KROTON", "YDUQS", "ESTACIO", "ANIMA", "SER EDUCACIONAL",
    "VITRU", "CRUZEIRO DO SUL", "VASTA", "AFYA",
)


# ── CVM em tempo real: o PageMethod do RAD ───────────────────────────────────
# Descoberto em 03/ago/2026. O ZIP de dados abertos atrasa ~1 dia; o RAD é o
# sistema onde a companhia PROTOCOLA o documento, e ele aparece na consulta em
# minutos. Medido no dia: documento mais recente no RAD às 15:05, consulta feita
# às 15:13 — 8 minutos. No ZIP, o mais recente era de dois dias antes.
#
# A consulta parecia inviável (ASP.NET WebForms com ViewState), mas por trás do
# botão há um PageMethod JSON: POST em .../frmConsultaExternaCVM.aspx/
# ListarDocumentos, `application/json`, sem ViewState e sem cookie obrigatório.
#
# ⚠️ CAPTCHA: o formulário TEM reCAPTCHA, hoje desligado — `hdnHabilitaCaptcha`
# vale 'N' e a resposta traz `SolicitarCaptcha: 'N'`. Se a CVM ligar, a resposta
# passa a vir com 'S' e este coletor **desiste e loga**, caindo para o ZIP.
# Não tente resolver o captcha: além de proibido, quebraria a cada mudança.
RAD_URL = "https://www.rad.cvm.gov.br/ENETWeb/frmConsultaExternaCVM.aspx/ListarDocumentos"
RAD_BASE = "https://www.rad.cvm.gov.br/ENETWeb/"

# O retorno é um blob delimitado por `$&`, 12 campos por documento, e um novo
# registro começa com `&*`. Sem essa âncora não dá para segmentar: campo com
# assunto vazio some e o alinhamento por contagem fixa quebra.
_RAD_CAMPOS = 12
_RAD_TAG = re.compile(r"<[^>]+>")
_RAD_POPUP = re.compile(r"OpenPopUpVer\('([^']+)'\)")
_RAD_DT = re.compile(r"(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}:\d{2}))?")


def _rad_limpo(s: str) -> str:
    return " ".join(_RAD_TAG.sub(" ", s or "").split())


def collect_cvm_rad() -> list[RawArticle]:
    """Documentos das companhias cobertas, direto do protocolo do RAD."""
    agora = datetime.now(timezone.utc)
    ini = agora - timedelta(hours=PRIMARY_WINDOW_HOURS)
    corpo = {
        "dataDe": ini.strftime("%d/%m/%Y"), "dataAte": agora.strftime("%d/%m/%Y"),
        "empresa": "", "setorAtividade": "-1", "categoriaEmissor": "-1",
        "situacaoEmissor": "-1", "tipoParticipante": "-1", "dataReferencia": "",
        "categoria": "EST_-1,IPE_-1_-1_-1", "periodo": "2",
        "horaIni": "00:00", "horaFim": "23:59", "palavraChave": "",
        "ultimaDtRef": "false", "tipoEmpresa": "0", "token": "", "versaoCaptcha": "",
    }
    try:
        r = requests.post(
            RAD_URL, data=json.dumps(corpo),
            headers={"Content-Type": "application/json; charset=utf-8",
                     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"},
            timeout=90,
        )
        if not r.ok:
            log.warning("CVM RAD: HTTP %s", r.status_code)
            return []
        d = r.json().get("d") or {}
    except Exception as e:
        log.warning("CVM RAD falhou: %s", e)
        return []

    if d.get("SolicitarCaptcha") == "S":
        log.warning("CVM RAD: a CVM ligou o captcha — caindo para o ZIP de dados abertos.")
        return []
    if d.get("temErro"):
        log.warning("CVM RAD: %s", (d.get("msgErro") or "")[:160])
        return []

    campos = (d.get("dados") or "").split("$&")
    inicios = [i for i, c in enumerate(campos) if c.strip().startswith("&*")]
    if not inicios:
        log.warning("CVM RAD: retorno sem registros reconhecíveis (%d campos)", len(campos))
        return []

    out: list[RawArticle] = []
    n_total = 0
    for i in inicios:
        reg = campos[i:i + _RAD_CAMPOS]
        if len(reg) < 11:
            continue
        n_total += 1
        empresa = _rad_limpo(reg[1])
        if not any(tok in _norm(empresa) for tok in CVM_COMPANY_TOKENS):
            continue

        categoria = _rad_limpo(reg[2])
        tipo = _rad_limpo(reg[3]).strip(" -")
        assunto = _rad_limpo(reg[4]).strip(" -")
        m = _RAD_DT.search(_rad_limpo(reg[6]))
        publicado = None
        if m:
            fmt = "%d/%m/%Y %H:%M" if m.group(2) else "%d/%m/%Y"
            bruto = f"{m.group(1)} {m.group(2)}" if m.group(2) else m.group(1)
            try:
                # O RAD carimba em horário de Brasília (UTC-3).
                publicado = datetime.strptime(bruto, fmt).replace(
                    tzinfo=timezone(timedelta(hours=-3))
                ).astimezone(timezone.utc)
            except ValueError:
                pass

        popup = _RAD_POPUP.search(reg[10] or "")
        if not popup:
            continue

        titulo = f"{empresa} — {categoria}"
        detalhe = assunto or tipo
        if detalhe:
            titulo += f": {detalhe[:180]}"

        out.append(RawArticle(
            url=RAD_BASE + popup.group(1),
            domain="rad.cvm.gov.br",
            source_name="CVM — Fato Relevante",
            title=titulo,
            snippet=" | ".join(p for p in (categoria, tipo, assunto) if p)[:400],
            published_at=publicado,
            found_at=agora,
            needs_filter=False,
        ))

    log.info("CVM RAD: %d documentos no protocolo | %d das cobertas -> %d publicados",
             n_total, len(out), len(out))
    return out


def _cvm_descobrir_arquivo(ano: int) -> list[str]:
    """Lista o diretório do IPE e devolve as URLs candidatas, do ano corrente.

    Assumir o nome do arquivo é frágil: a CVM renomeia e reorganiza. Ler a
    listagem custa uma requisição e sobrevive a renomeação.
    """
    candidatos: list[str] = []
    status, content = http_get(CVM_IPE_DIR, timeout=45)
    if status == 200 and content:
        try:
            soup = BeautifulSoup(content, "html.parser")
            hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]
            for h in hrefs:
                nome = h.rsplit("/", 1)[-1].lower()
                if not nome.endswith((".csv", ".zip")):
                    continue
                if "ipe" not in nome or str(ano) not in nome:
                    continue
                candidatos.append(h if h.startswith("http") else CVM_IPE_DIR + h.lstrip("/"))
        except Exception as e:
            log.info("CVM: listagem ilegível: %s", e)
    else:
        log.info("CVM: listagem do diretório HTTP %s", status)

    candidatos.append(CVM_IPE_FALLBACK.format(ano=ano))
    return candidatos


_CVM_FORMATOS = ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y")


def _cvm_data(row: dict):
    """Data de entrega, tolerante a formato. None se nada casar (o item passa)."""
    for campo in ("Data_Entrega", "Data_Referencia", "Data_Ocorrencia"):
        bruto = (row.get(campo) or "").strip()
        if not bruto:
            continue
        base = bruto.replace("T", " ").split(" ")[0][:10]
        for fmt in _CVM_FORMATOS:
            try:
                return datetime.strptime(base, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def collect_cvm() -> list[RawArticle]:
    ano = datetime.now(timezone.utc).year
    content = b""
    for url in _cvm_descobrir_arquivo(ano):
        status, body = http_get(url, timeout=60)
        if status == 200 and body:
            log.info("CVM IPE: usando %s (%d bytes)", url, len(body))
            content = body
            break
        log.info("CVM IPE: HTTP %s em %s", status, url)
    if not content:
        log.warning("CVM IPE %s: nenhuma candidata respondeu", ano)
        return []

    # A CVM às vezes publica .zip em vez de .csv cru.
    if content[:2] == b"PK":
        try:
            import io as _io
            import zipfile
            with zipfile.ZipFile(_io.BytesIO(content)) as z:
                nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
                content = z.read(nome)
                log.info("CVM IPE: extraído %s do zip", nome)
        except Exception as e:
            log.warning("CVM IPE: zip ilegível: %s", e)
            return []

    try:
        text = content.decode("latin-1", errors="replace")
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        rows = list(reader)
    except Exception as e:
        log.warning("CVM IPE %s: CSV ilegível: %s", ano, e)
        return []

    if not rows:
        log.warning("CVM IPE %s: 0 linhas", ano)
        return []

    cols = set(rows[0].keys())
    for needed in ("Nome_Companhia", "Categoria", "Link_Download"):
        if needed not in cols:
            log.warning(
                "CVM IPE %s: coluna '%s' ausente (colunas: %s) — layout mudou.",
                ano, needed, sorted(cols)
            )
            return []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=PRIMARY_WINDOW_HOURS)).date()
    now = datetime.now(timezone.utc)
    out: list[RawArticle] = []

    # Contadores: sem eles, "0 documentos" não diz SE o problema é a lista de
    # empresas, a categoria, a janela ou o link. Com eles, um run resolve.
    n_empresa = n_categoria = n_janela = 0

    for r in rows:
        nome = _norm(r.get("Nome_Companhia", ""))
        if not any(tok in nome for tok in CVM_COMPANY_TOKENS):
            continue
        n_empresa += 1

        cat = _norm(r.get("Categoria", ""))
        if CVM_CATEGORIAS_EXCLUIDAS and any(c in cat for c in CVM_CATEGORIAS_EXCLUIDAS):
            continue
        n_categoria += 1

        dt = _cvm_data(r)
        if dt and dt.date() < cutoff:
            continue
        n_janela += 1

        link = (r.get("Link_Download") or "").strip()
        if not link.startswith("http"):
            continue

        # 13% dos documentos vêm com Assunto vazio (medido em 03/ago/2026). Sem
        # isto o título é só "EMPRESA — Comunicado ao Mercado", sem informação
        # nenhuma — e como needs_filter=False, é isso que o gate de LLM recebe
        # para julgar. Tipo/Espécie são o que a CVM oferece como substituto.
        assunto = (r.get("Assunto") or "").strip()
        if not assunto:
            assunto = " / ".join(
                p for p in ((r.get("Tipo") or "").strip(), (r.get("Especie") or "").strip()) if p
            )
        titulo = f"{r.get('Nome_Companhia', '').strip()} — {r.get('Categoria', '')}"
        if assunto:
            titulo += f": {assunto[:180]}"

        out.append(RawArticle(
            url=link,
            domain="cvm.gov.br",
            source_name="CVM — Fato Relevante",
            title=titulo,
            snippet=assunto[:400],
            published_at=dt,
            found_at=now,
            needs_filter=False,   # já filtrado por companhia coberta
        ))

    log.info(
        "CVM IPE %s: %d linhas | %d das empresas cobertas | %d na categoria | "
        "%d na janela de %dh | %d com link -> %d publicados",
        ano, len(rows), n_empresa, n_categoria, n_janela, PRIMARY_WINDOW_HOURS, len(out), len(out),
    )
    if n_empresa and not out:
        exemplos = sorted({r.get("Categoria", "") for r in rows
                           if any(t in _norm(r.get("Nome_Companhia", "")) for t in CVM_COMPANY_TOKENS)})[:8]
        log.warning("CVM: empresas casaram mas nada passou. Categorias vistas: %s", exemplos)
    elif not n_empresa:
        amostra = sorted({r.get("Nome_Companhia", "") for r in rows})[:8]
        log.warning("CVM: NENHUMA empresa casou. Amostra de nomes no arquivo: %s", amostra)
    return out


# ══════════════════════════════════════════════════════════════════════════════
def collect_cvm_com_fallback() -> list[RawArticle]:
    """RAD primeiro (tempo real); o ZIP de dados abertos é a rede de segurança.

    ⚠️ As duas rotas geram URLs DIFERENTES para o mesmo documento — o RAD usa
    `NumeroSequencialDocumento` e o ZIP usa `numProtocolo`/`numSequencia`, que
    são identificadores distintos. Por isso o fallback só dispara quando o RAD
    devolve VAZIO: rodar os dois sempre duplicaria o feed, e a deduplicação do
    pipeline é por URL. Se o RAD ficar fora um dia e voltar no outro, alguns
    documentos podem aparecer duas vezes na virada. É o preço de ter as duas.
    """
    itens = collect_cvm_rad()
    if itens:
        return itens
    log.info("CVM: RAD não devolveu nada — tentando o ZIP de dados abertos (atrasa ~1 dia).")
    return collect_cvm()


def collect_primary_sources() -> list[RawArticle]:
    out: list[RawArticle] = []
    for name, fn in (("DOU", collect_dou), ("CVM", collect_cvm_com_fallback)):
        try:
            items = fn()
            out.extend(items)
            if not items:
                log.warning("Fonte primária [%s] devolveu 0 itens.", name)
        except Exception as e:
            log.warning("Fonte primária [%s] falhou: %s", name, e)
    return out
