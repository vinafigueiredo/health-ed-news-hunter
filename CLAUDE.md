# CLAUDE.md — Health & Education News Hunter

Conhecimento único do repositório. Leia antes de mexer em qualquer coisa.

> 📌 **Leia também `HANDOVER.md`** na raiz. Este arquivo explica COMO o sistema
> funciona; o HANDOVER explica ONDE paramos, POR QUÊ, e o que fazer em seguida —
> incluindo o único bug aberto (CVM), a fila de próximos passos com critério de
> pronto, e a lista de fontes já descartadas com o motivo, para ninguém refazer
> caminho morto.

## O que é

Back-end que coleta notícias de **saúde suplementar** e **educação superior
privada** no Brasil, filtra o que interessa a equity research e grava no
Supabase. O front-end é a página `dashboards/noticias.html`, que vive no outro
repo (`ans-research` → hcdatahouse.vercel.app).

## Decisões de projeto (não reverter sem conversar com o Vinicius)

1. **Não existe classificação de take (+/−/=).** Foi decidido em 30/jul/2026.
   Motivo: sem gabarito calibrado à mão, take vira chute plausível — pior que
   não ter. E a página é pública num site sem autenticação; publicar leitura
   direcional seria entregar IP de graça. Se um dia entrar take, ele **não** vai
   para a página pública.
2. **Fontes primárias são parte do escopo, não extra.** DOU e CVM entram junto
   com a imprensa porque é onde a informação chega primeiro e sem ruído.
3. **Repo público, separado do `ans-research`.** Público = Actions ilimitado;
   separado = o ETL e as análises proprietárias continuam privados.
4. **`resolution=ignore-duplicates` no push.** Nunca trocar por
   merge-duplicates: o `found_at` da notícia antiga "renasceria" e a ordenação
   do feed viraria ficção.

## Arquitetura

`hunt.py` → `fetcher.fetch_all()` → `filter.filter_articles()` →
`sync.known_urls()` (remove o que o banco já tem) → `relevance.judge_batch()`
(LLM) → `sync.push_articles()` → `record_run` + `record_source_health`.

A ordem importa: a deduplicação contra o banco vem **antes** do LLM. Sem ela, o
loop de 5 minutos julgaria o mesmo artigo ~288 vezes por dia e queimaria a cota
dos free tiers em horas.

⚠️ **O dedup cobre só metade do problema.** `known_urls()` lê a tabela
`articles`, que guarda apenas o que o LLM **aprovou**. Artigo reprovado não fica
registrado em lugar nenhum e volta a ser julgado a cada run — para sempre.
Medido em 03/ago/2026: de 81 artigos "novos" num run, 79 eram rejeitados de
rodadas anteriores. Conserto pendente: tabela `judged_urls` (url + timestamp)
alimentada com os reprovados, lida junto pelo `known_urls()`.

| Arquivo | Papel |
|---|---|
| `hunter/config.py` | Universo de cobertura + os três níveis de keyword. É onde 90% das mudanças acontecem |
| `hunter/sources.py` | RSS. `filter=False` = veículo estreito (aceita tudo); `filter=True` = amplo (exige keyword) |
| `hunter/html_scrapers.py` | Sites sem RSS. Seleção por **padrão de URL** (`href_re`), nunca por classe CSS |
| `hunter/primary_sources.py` | DOU (in.gov.br, filtro por órgão) e CVM (dados abertos IPE, filtro por companhia) |
| `hunter/fetcher.py` | Coleta paralela, filter-then-cap, dedup por URL, fallback curl_cffi |
| `hunter/filter.py` | Gate barato (keyword três níveis) |
| `hunter/relevance.py` | Gate caro (LLM em lote, cascata Groq→Cerebras→Mistral→Gemini, fail-open) |
| `hunter/sync.py` | PostgREST |
| `hunter/check_sources.py` | `hunt.py --check-sources` |

## Os três níveis de keyword

Isto é o coração do filtro e onde os bugs moram.

- **STRONG** — case-insensitive, fronteira de palavra. Só para termo inequívoco.
- **CASED** — casa só nas formas capitalizadas listadas. Para sigla que colide
  com palavra comum: `ANS`, `CADE`, `MEC`, `SERES`, `EAD`, `NIP`.
- **CONTEXT** — casa só se houver um marcador do setor no mesmo texto. Para
  termo que existe fora do setor: `reajuste`, `captação`, `revisão técnica`,
  `Alice`, `Sami`, `Descomplica`, `Cruzeiro do Sul`, `Ânima`.

Promover um termo de CONTEXT para STRONG é a forma mais rápida de encher o feed
de lixo. Na dúvida, CONTEXT. Mexeu? **Rode `pytest`** — os 17 testes em
`tests/test_filter.py` são exatamente os falsos positivos que essa lista
produziria sem os níveis.

## Estado verificado ao vivo (30/jul/2026)

Dois diagnósticos reais contra a rede. O que se aprendeu — e que não se descobre
sem rodar:

**Funciona e é o melhor do conjunto**
- **DOU**: 49 atos no escopo em 3 dias, filtrados por órgão a partir de ~300–380
  atos/dia. Era o coletor mais frágil no papel; é o que mais entrega.
- **CVM**: resolvido. Os arquivos são `ipe_cia_aberta_AAAA.ZIP` — ZIP, não CSV.
  O 404 era o coletor pedindo `.csv`. Agora descobre pela listagem e descompacta.
- **JOTA**: melhor sinal regulatório da imprensa. No teste, a primeira manchete
  era "ANS amplia prazo sobre cartões".

**Regex errado, não fonte quebrada** — MEC usa `/noticias/<ano>/<mês>/<slug>`,
ANVISA usa `/noticias-anvisa/<ano>/<slug>`, INEP usa `/<seção>/noticias/<slug>`.
Corrigido; recupera ~77 artigos que estavam sendo descartados em silêncio.

**Data**: todos os scrapers voltavam com `dated=0`. No CADE a data mora como
texto solto em `<div class="conteudo">`, sem casar nenhum seletor. Resolvido com
varredura de texto por nível de ancestral.

**ANS é SPA e não tem RSS.** Testadas todas as saídas: `/noticias` e
`/noticias/RSS` e `/noticias/rss.xml` devolvem a MESMA casca de 55.388 bytes
(HTTP 200, `text/html`, zero link de notícia); `/noticias/rss`, `/@@rss`,
`/geral` e `++api++` são 404. Só a subseção `/consumidor` é servida pronta
(203.329 bytes) — é a entrada usada. Se ela cair, a ANS segue chegando pelo DOU,
que é fonte melhor. O sitemap (`/ans/pt-br/sitemap.xml`, 328 `<loc>`) existe mas
não traz título, só URL — manchete derivada de slug é ruim demais para research.

**Dos cinco órgãos, só a ANVISA serve feed** (`/noticias-anvisa/RSS`,
`application/atom+xml`). MEC/RSS devolve 5,5 KB vazios; INEP/RSS e CADE/RSS 404.

**Não existe imprensa setorial de educação superior com RSS vivo.** Nove
candidatos testados: Desafios da Educação 404, Revista Ensino Superior 500,
Semesp 403, ABMES erro de SSL, UOL Educação 403, Estadão Educação em loop de
redirect. A cobertura de educação passa a ser G1 Educação (100 itens, todos com
data) + Folha Educação + DOU/MEC + imprensa econômica. É menos que saúde, que
tem 7 setoriais vivas — característica do mercado de veículos, não defeito.

**Estadão**: todos os feeds do domínio principal são 404 e os subdomínios de
seção entram em loop de redirect. Só o E-Investidor tem RSS.

**Removidas com motivo**: FenaSaúde (SPA de 4 links, `/feed` 404), Abramge
(ConnectionReset), ABMES (500 + SSL), ANS Legislação (404 nos dois caminhos),
Pipeline Valor (404 + paywall), JOTA Saúde (404 em quatro grafias).

## Candidatas em vez de URL única

Cada fonte — RSS e HTML — declara uma LISTA de URLs; o coletor tenta em ordem e
fica com a primeira que devolver itens. Foi a lição do primeiro diagnóstico: o
problema não era acertar a URL, era o código depender de eu ter acertado. Com
candidatas, ele descobre sozinho.

## Pegadinhas já conhecidas

- **Cloudflare vs IP de datacenter.** Vários sites BR devolvem 403 — ou pior,
  200 com página de desafio e zero entradas — para o IP do GitHub Actions. O
  `fetcher.http_get` cai para `curl_cffi` (TLS de Chrome) em 401/403/429, e o
  `_fetch_feed` tenta de novo quando o feed vem com 0 entradas apesar do 200.
- **Filter-then-cap.** `MAX_PER_SOURCE` é aplicado **depois** do corte por
  janela. Cortar antes descarta itens recentes em feeds grandes.
- **Leitura anônima no Supabase.** A `migration_06` original do `ans-research`
  concedia SELECT só a `authenticated`; a auth do site foi removida em jun/2026.
  Sem policy para `anon`, a página devolve 0 linhas **sem erro**.
- **DOU é o coletor mais frágil.** Depende do `<script id="params">` embutido em
  `in.gov.br/leiturajornal`. Quando quebrar, o log diz exatamente isso.
- **O `title` do DOU é só o número do ato.** "RESOLUÇÃO-RE nº 2.967, DE 30 DE
  JULHO DE 2026" — zero informação. Como o DOU entra com `needs_filter=False`,
  era isso que chegava ao gate de LLM, que aprovava tudo pela regra do "na
  dúvida, relevante". O JSON traz `content` com o texto oficial; é ele que vai
  no snippet, sem o preâmbulo de competência. Se o in.gov.br parar de mandar
  `content`, o coletor volta a mandar só o caminho do órgão — e o feed volta a
  encher de ato numerado. Esse é o sintoma a procurar.
- **ANVISA no DOU é restrita à Diretoria Colegiada** (`DOU_ANVISA_UNIDADES`).
  Medido em 03/ago/2026: 98 dos 119 atos do escopo em 3 dias úteis eram da
  ANVISA, todos de Gerência-Geral fazendo registro produto a produto (Inspeção
  Sanitária 41, Medicamentos 18, Fumígenos 9, Cosméticos 9). Nenhum veio da
  Colegiada, que é onde nasce RDC. Sem esse recorte, a ANVISA sozinha era 82%
  do volume do DOU e afogava ANS, CADE e SERES.
- **CVM IPE.** CSV latin-1, separador `;`. Se a CVM renomear coluna, o coletor
  loga as colunas encontradas e devolve vazio em vez de estourar.
- **A CVM NÃO é fonte de tempo real.** Medido em 03/ago/2026: o ZIP dos dados
  abertos é regenerado com ~1 dia de atraso (`Last-Modified` de domingo às 10h
  GMT numa segunda ao meio-dia; nenhum registro de sábado em diante). A
  premissa antiga de "sai no minuto do protocolo" é falsa para esta rota — a
  imprensa chega antes. A CVM vale como confirmação documental, não como
  antecipação. Por isso as primárias têm janela própria,
  `PRIMARY_WINDOW_HOURS=168`: com as 72h da imprensa o coletor devolvia 0 em
  9,4% dos dias sem nada estar quebrado (taxa base real: ~1,5 doc/dia das ~25
  companhias cobertas, e houve 6 dias seguidos com zero em julho).
- **Comentário na mesma linha da chave no `.env` vira o valor.** O
  `python-dotenv` só remove comentário inline quando há valor antes dele. Com
  `CEREBRAS_API_KEY=      # https://...`, a chave passou a valer a URL do
  comentário — o robô achou que três provedores estavam configurados e gastou
  ~12s por lote levando 401 antes de cair no fail-open. `relevance._key()`
  agora rejeita valor com `#`, espaço ou `://`. Mantenha os comentários do
  `.env.example` em linha separada.
- **Console do Windows é cp1252.** Um `→` ou `═` num `print` derruba o processo
  com UnicodeEncodeError (aconteceu). `hunt.py` e `watchdog.py` reconfiguram
  stdout para UTF-8 logo no início; mantenha isso, ou use só ASCII nos logs.

## Secrets esperados

`SUPABASE_URL`, `SUPABASE_SECRET_KEY` e, para a IA, `GROQ_API_KEY`,
`CEREBRAS_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY`.

A secret key do Supabase **jamais** vai para o front-end — a página usa a chave
publishable, que só enxerga o que a RLS permite.

## Workflow com o Vinicius

- Comandos vão prontos para colar, em bloco de código, com `cd` incluído.
  Nunca só descrever o passo.
- **O terminal é PowerShell, não CMD.** No PowerShell 5.1 o `&&` é erro de
  sintaxe (`O token '&&' não é um separador de instruções válido`) — encadeie
  com `;` ou use `git -C <caminho> <comando>`. `%VAR%` também não expande; é
  `$env:VAR`. Aconteceu em 03/ago/2026.
- Git roda **só** pelo Windows.
- Python vem do venv direto: `.\.venv\Scripts\python.exe`, sem `activate`.
