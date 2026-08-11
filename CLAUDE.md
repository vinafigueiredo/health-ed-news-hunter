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

## Vertical (saúde × educação) — coluna `articles.vertical`

Existe desde 03/ago/2026, em `hunter/classify.py`. Valores: `saude`, `educacao`,
`ambos`, ou `NULL` (indefinida). O dashboard do ans-research filtra por ela.

**Por que no ingest e não no front:** classificar no cliente exigiria duplicar
estas listas do `config.py` no outro repo. Duplicata desatualiza calada — toda
empresa nova aqui sumiria do filtro de lá sem ninguém perceber.

Regra: a vertical vem das keywords que casaram. Termo que não está em nenhuma
lista não vota — isso cobre tanto os neutros (`CADE`, `fusão`, `aquisição`,
valem para os dois setores) quanto keywords de versões antigas do config que
ainda vivem em linhas antigas do banco. Sem voto → `NULL`, e o front mostra
esses itens só na aba "Tudo". **Fonte curada entra com `matched_keywords = []`**
(pulou o gate), então para ela o `_to_dict` roda o matcher só para achar a
vertical — sem gravar as keywords, porque `[]` significa "passou sem gate" e
essa semântica não pode mudar.

Distribuição medida em 753 linhas: saúde 47,7%, educação 31,5%, indefinida 20,8%
(a maioria CADE e imprensa com keyword só de M&A — corretamente sem vertical).

Mexeu nas listas? Rode `python scripts/backfill_vertical.py` (tem `--dry-run`)
para reclassificar o histórico. É idempotente.

### A CVM grafa razão social em CAIXA ALTA e sem acento

Custou três empresas já listadas ficarem invisíveis: `DIAGNOSTICOS DA AMERICA`
(Dasa), `ANIMA HOLDING` (Ânima) e `CM HOSPITALAR` (Viveo). O matcher é
case-insensitive mas **sensível a acento**, então "Diagnósticos da América" não
casa "DIAGNOSTICOS DA AMERICA". Pior: a CVM escreve `REDE D‘OR` com **U+2018**,
que não é nem o apóstrofo reto (U+0027) nem o curvo direito (U+2019).

Resolvido do jeito que o arquivo já resolvia — listando a variante. **Ao
adicionar empresa nova, cheque como ela aparece nos títulos do IPE da CVM**, não
só na imprensa. A correção estrutural (normalizar acento no matcher) não foi
feita para não mudar o comportamento de casamento no fim de uma sessão; se for
fazer, é em `filter.py:_strong_re` e exige rodar os testes com atenção.

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
- **A CVM tem DUAS rotas, e a boa é o RAD.** Ver a seção própria abaixo.
- **CVM IPE (rota de fallback).** CSV latin-1, separador `;`. Se a CVM renomear
  coluna, o coletor loga as colunas encontradas e devolve vazio em vez de
  estourar. O ZIP é regenerado com ~1 dia de atraso — medido em 03/ago/2026,
  `Last-Modified` de domingo 10h GMT numa segunda ao meio-dia. Por isso as
  primárias têm janela própria, `PRIMARY_WINDOW_HOURS=168`: com as 72h da
  imprensa o coletor devolvia 0 em 9,4% dos dias sem nada estar quebrado.
- **Comentário na mesma linha da chave no `.env` vira o valor.** O
  `python-dotenv` só remove comentário inline quando há valor antes dele. Com
  `CEREBRAS_API_KEY=      # https://...`, a chave passou a valer a URL do
  comentário — o robô achou que três provedores estavam configurados e gastou
  ~12s por lote levando 401 antes de cair no fail-open. `relevance._key()`
  agora rejeita valor com `#`, espaço ou `://`. Mantenha os comentários do
  `.env.example` em linha separada.
- **Feed MORTO é pior que feed com ERRO.** Erro aparece vermelho no
  `--check-sources`. Feed velho responde HTTP 200 com entradas de meses atrás,
  parece saudável, e tudo cai fora da janela em silêncio. Aconteceu com o
  Estadão: o E-Investidor congelou em 27/mai e o veículo passou **76 dias sem
  entregar um artigo**. Ao ver `0 items (de N entradas)` no log, cheque a DATA
  das entradas antes de culpar o filtro.
- **Fonte que nunca entrega era invisível para o watchdog.** O
  `record_source_health` recebia só as fontes com artigo, então quem não
  entregava não ganhava linha na tabela — e o watchdog, que itera sobre as
  linhas existentes, não tinha como reclamar de algo ausente. A checagem
  "nunca coletou nada" dele era código morto. Corrigido em 11/ago/2026:
  `fetcher.todas_as_fontes()` alimenta o balanço com TODA fonte configurada,
  as vazias com `last_count=0`.
  ⚠️ O upsert vai em **dois lotes** de propósito: o PostgREST exige que todo
  objeto do lote tenha as mesmas chaves, e quem veio vazio não pode levar
  `last_ok` — com `merge-duplicates`, um `last_ok: null` apagaria o histórico
  que o watchdog usa para medir silêncio.
- **Console do Windows é cp1252.** Um `→` ou `═` num `print` derruba o processo
  com UnicodeEncodeError (aconteceu). `hunt.py` e `watchdog.py` reconfiguram
  stdout para UTF-8 logo no início; mantenha isso, ou use só ASCII nos logs.

## CVM — as duas rotas (leia antes de mexer no coletor)

Resolvido em 03/ago/2026. A CVM **é** fonte de tempo real, pela rota certa.

| Rota | Defasagem | Papel |
|---|---|---|
| **RAD** (`collect_cvm_rad`) | **~8 min** | Principal |
| ZIP de dados abertos (`collect_cvm`) | ~1 dia | Só se o RAD devolver vazio |

O RAD é onde a companhia **protocola** o documento. Parece inviável — ASP.NET
WebForms com ViewState —, mas atrás do botão Consultar há um **PageMethod JSON**:
`POST .../frmConsultaExternaCVM.aspx/ListarDocumentos`, `application/json`, sem
ViewState e sem cookie obrigatório. O payload exato está em `collect_cvm_rad`.

Duas coisas que custaram tempo e não devem ser redescobertas:

1. **`btnConsulta` tem `name=""`.** Mandar `btnConsulta=Consultar` como campo de
   formulário não faz nada — ele é gatilho de JavaScript, não campo. Foi o que
   fez a primeira tentativa (POST de WebForms) voltar com a grade vazia e sem
   mensagem de erro.
2. **O formato do retorno.** Blob delimitado por `$&`, **12 campos por
   documento**, e um registro novo começa com `&*`. Segmentar por contagem fixa
   quebra quando um documento vem sem assunto — use a âncora `&*`.
   Campo 1 = empresa, 2 = categoria, 3 = tipo, 4 = assunto, 6 = data/hora de
   entrega (horário de Brasília), 10 = HTML com o link.

⚠️ **O formulário tem reCAPTCHA, hoje DESLIGADO** (`hdnHabilitaCaptcha='N'`, e a
resposta traz `SolicitarCaptcha: 'N'`). Se a CVM ligar, o coletor **desiste e
loga**, caindo para o ZIP. **Não tente resolver o captcha** — além de proibido,
quebraria a cada mudança do site.

⚠️ **As duas rotas geram URLs DIFERENTES para o mesmo documento** (RAD usa
`NumeroSequencialDocumento`, ZIP usa `numProtocolo`/`numSequencia`). Como a
deduplicação do pipeline é por URL, rodar as duas sempre duplicaria o feed —
por isso o fallback só dispara quando o RAD devolve vazio. Se o RAD ficar fora
um dia e voltar no outro, alguns documentos aparecem duas vezes na virada.
Distinguir pelo `domain`: `rad.cvm.gov.br` é RAD, `cvm.gov.br` é ZIP.

## A CVM não passa pelo gate de LLM

Decisão do Vinicius em 03/ago/2026, registrada em `hunt.py` como `BYPASS_LLM`.

**Se é publicação da CVM de companhia coberta, entra — sem julgamento e sem
filtro de categoria.** O recorte já foi feito na lista de companhias; quem
decide se o documento importa é o analista. O filtro de categoria anterior
descartava 1.009 dos 1.317 documentos do ano (77%) — inclusive "Exchange de
debêntures" da Kora, classificado como "Assembleia". Volume real: ~6/dia.

Não volte a filtrar por categoria "relevante" sem falar com o Vinicius.

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
