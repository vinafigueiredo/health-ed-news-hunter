# HANDOVER — Health & Education News Hunter

> Documento de passagem de bastão. Escrito em 30/jul/2026, ao fim da sessão que
> construiu o repositório. Leia isto **junto com `CLAUDE.md`** antes de tocar em
> qualquer arquivo. O `CLAUDE.md` explica *como o sistema funciona*; este aqui
> explica *onde paramos, por quê, e o que fazer em seguida*.

---

## 0. Resumo em dez linhas

Robô que coleta notícias de saúde suplementar e educação superior privada no
Brasil, filtra o que interessa a uma mesa de equity research e grava no
Supabase. Uma página estática (`dashboards/noticias.html`, que pertence a OUTRO
repositório) lê o Supabase e mostra o feed.

**Não classifica direção de mercado.** Não há take (+/−/=). Decisão explícita —
ver §4.

O código está escrito, testado offline e com as fontes validadas contra a rede
real. **Nunca gravou nada no Supabase e nunca rodou no GitHub Actions.** Falta
exatamente isso: ligar banco, ligar automação, publicar a página.

---

## 1. Onde está cada coisa

| O quê | Onde |
|---|---|
| Repositório (este) | `C:\health-ed-news-hunter` — extraído do `health-ed-news-hunter-v5.zip` |
| Zips entregues | `C:\ans-research\_entregas\` — **use o de maior versão**, o resto é histórico |
| Página do dashboard | `C:\ans-research\_entregas\noticias.html` → destino final `C:\ans-research\dashboards\noticias.html` |
| Card do índice | `C:\ans-research\_entregas\card_noticias_para_index.html` → colar em `C:\ans-research\dashboards\index.html` |
| Diagnósticos brutos | `C:\ans-research\_entregas\diagnostico.txt`, `probe2.txt`, `check3.txt` |
| venv | `C:\health-ed-news-hunter\.venv` (já criado, dependências instaladas) |

O repositório **ainda não existe no GitHub**. O nome combinado é
`health-ed-news-hunter`, público.

Limpeza pendente: há uma pasta `.venv` criada por engano em
`C:\ans-research\_entregas\` — pode apagar.

---

## 2. Estado real: o que está pronto e o que nunca rodou

### Pronto e verificado
- Pipeline completo (coleta → filtro de keyword → dedup contra o banco → gate de
  LLM → gravação), com cada bloco isolado por try/except.
- 18 testes `pytest` passando: 17 de calibragem termo a termo + 1 smoke com 21
  manchetes plausíveis (0 falso positivo, 0 falso negativo).
- Fontes validadas **contra a rede real** em 30/jul (ver §5). 38 OK, 0 erro.
- SQL do Supabase escrito e idempotente.
- Workflows do Actions escritos (`hunt-loop`, `watchdog`, `report`) e com YAML
  validado.
- Página `noticias.html` escrita no padrão visual do Healthcare Data House,
  com `escapeHtml` em tudo, sem `alert()`, com export CSV e persistência de
  filtros em localStorage protegida por try/catch.

### Nunca rodou
- Gravação no Supabase (o SQL nunca foi executado).
- Qualquer workflow do GitHub Actions.
- A página `noticias.html` nunca foi aberta com dados reais.
- O gate de relevância por LLM nunca foi exercitado (nenhuma chave configurada).

### Bug aberto, único conhecido
**CVM devolve 0 documentos.** Ver §7. É o primeiro item da fila.

---

## 3. Por que este repositório existe separado do `ans-research`

Actions é gratuito e ilimitado em repositório **público**. O `ans-research` é
privado e contém ETL e análises proprietárias — não pode virar público, e se o
hunter rodasse lá dentro consumiria os 2.000 min/mês do free tier em pouco mais
de um dia com o loop de 5 minutos.

Então: hunter público e separado, dashboard continua no `ans-research`, e a
ponte entre os dois é o Supabase.

---

## 4. Decisões travadas — não reverter sem falar com o Vinicius

1. **Sem classificação de take (+/−/=).** Dois motivos. Primeiro: sem gabarito
   calibrado à mão, take vira chute plausível, que é pior que não ter take —
   induz decisão errada com aparência de análise. Segundo: a página fica no
   `hcdatahouse.vercel.app`, que é **aberto, sem autenticação, e acessado por
   terceiros**; publicar leitura direcional seria entregar IP de graça. Se um dia
   entrar take, ele **não** vai para a página pública.
2. **Fontes primárias são escopo, não extra.** DOU e CVM entram junto com a
   imprensa porque é onde a informação chega primeiro e sem ruído.
3. **`resolution=ignore-duplicates` no push.** Nunca trocar por
   `merge-duplicates`: o `found_at` da notícia antiga "renasceria" a cada run e a
   ordenação do feed viraria ficção.
4. **Toda fonte declara uma LISTA de URLs candidatas**, tentadas em ordem. Veio
   de erro real: o problema não era acertar a URL, era o código depender de ter
   acertado — e errar fazia a fonte sumir em silêncio.
5. **Cascata de LLM gratuita** (Groq → Cerebras → Mistral → Gemini), em lote de
   12 artigos, com fail-open. Não usar Anthropic pago: a v1 deste projeto fazia
   uma chamada de Haiku por artigo, o que com loop de 5 min é insustentável.
6. **A secret key do Supabase jamais vai para o front-end.** A página usa a chave
   publishable, que só enxerga o que a RLS permite.

---

## 5. Estado das fontes — medido, não suposto

Resultado do último `--check-sources` real (30/jul/2026). `items` = quantos
vieram; `dated` = quantos trouxeram data de publicação.

### RSS — todos OK
Valor Econômico ×2 (100/100 cada) · Folha de S.Paulo ×3 (100/100) · G1 Economia
(100/100) · G1 Educação (100/100) · CNN Brasil (60/60) · InvestNews (30/30) ·
Exame (25/25) · JOTA (25/25) · Metrópoles (20/20) · Panorama Farmacêutico
(20/20) · ANVISA Atom (15/0) · UOL Economia (15/0) · Agência Brasil ×3 (10/10) ·
InfoMoney, Money Times, Seu Dinheiro, Poder360, Brazil Journal, NeoFeed,
Medicina S/A, Saúde Business, Futuro da Saúde, Setor Saúde, Portal Hospitais
Brasil (10/10 cada) · Estadão E-Investidor (8/8) · Healthcare Management (3/3).

### Scrapers HTML
ANVISA 31 artigos (30 com data) · CADE 29 (29) · MEC 15 (1) · INEP 14 (9) ·
ANAHP 5 (0) · IESS 1 (0).

### Primárias
DOU **49 atos no escopo em 3 dias**, filtrados por órgão a partir de ~300–380
atos publicados por dia. É a melhor fonte do conjunto.
CVM: 0 — ver §7.

### Fontes descartadas, com o motivo (não refaça este caminho)
- **ANS**: não há caminho por HTML nem RSS. Sete saídas testadas —
  `/assuntos/noticias`, `/noticias/operadoras`, `/noticias/RSS` e
  `/noticias/rss.xml` devolvem a **mesma casca de 55.388 bytes** da SPA (HTTP
  200, `text/html`, zero link de notícia); `/noticias/rss`, `/@@rss`,
  `/noticias/geral` e `++api++` são 404; `/noticias/consumidor` devolve 203.329
  bytes mas nenhum link casa — o peso é CSS/JS embutido, a lista continua vindo
  por JavaScript. **A ANS entra pelo DOU**, que é fonte melhor para o que
  importa (RN e IN como texto oficial, no dia). O sitemap responde (328 `<loc>`)
  mas não traz título, só URL. Reabrir exigiria navegador headless, o que traz
  Playwright para o repo inteiro por uma fonte só.
- **Educação setorial**: não existe veículo com RSS vivo. Nove candidatos
  testados — Desafios da Educação 404, Revista Ensino Superior 500, Semesp 403
  (bloqueia bot mesmo com TLS de Chrome), ABMES erro de SSL, UOL Educação 403,
  Estadão Educação em loop de redirect. Cobertura de educação = G1 Educação +
  Folha Educação + DOU/MEC + imprensa econômica. **É menos densa que saúde, que
  tem 7 setoriais vivas. Isso é característica do mercado de veículos, não
  defeito do robô** — não vá "consertar".
- **Estadão**: todos os feeds do domínio principal são 404; subdomínios de seção
  entram em loop de redirect. Só o E-Investidor tem RSS.
- **Outras**: FenaSaúde (SPA de 4 links, `/feed` 404), Abramge
  (ConnectionReset), ABMES (500 + SSL), Pipeline Valor (404 + paywall), JOTA
  Saúde (404 em quatro grafias), ANS Legislação (404 em dois caminhos).

---

## 6. Os três níveis de keyword — onde moram os bugs

Em `hunter/config.py`:

- **STRONG** — casa case-insensitive, com fronteira de palavra. Só para termo
  inequívoco: `Hapvida`, `sinistralidade`, `rol de procedimentos`.
- **CASED** — casa só na forma capitalizada listada. Para sigla que colide com
  palavra comum: `ANS`, `CADE` (≠ "cadê"), `MEC`, `SERES` (≠ "seres humanos"),
  `EAD`, `NIP`, `INEP`, `UNINTER`.
- **CONTEXT** — casa só se houver um marcador do setor no mesmo texto. Para termo
  que existe fora do setor: `reajuste` (salarial? de plano?), `captação` (de
  recursos? de alunos?), `revisão técnica` (de veículo? de carteira?), `Alice`,
  `Sami`, `Descomplica`, `Cruzeiro do Sul`, `Ânima`.

**Promover um termo de CONTEXT para STRONG é a forma mais rápida de encher o feed
de lixo.** Na dúvida, CONTEXT — o gate de LLM corta o resto.

Mexeu no `config.py`? **Rode `pytest`.** Os testes não verificam a lógica;
verificam a calibragem. Cada caso é um falso positivo real que a lista produziria
sem os níveis ("Alice Braga estrela nova série", "Cruzeiro vence o clássico",
"Reajuste salarial dos servidores", "Cade o meu pedido?").

---

## 7. CVM — RESOLVIDO em 03/ago/2026. Não era bug.

O funil instrumentado respondeu de primeira:
`29134 linhas | 1317 das empresas cobertas | 308 na categoria | 1 na janela de 72h`.
Empresa e categoria nunca foram o gargalo. A janela era — e cortava datas
**corretas**: zero linhas do subconjunto falhavam no parse (e mesmo se
falhassem, `_cvm_data` devolve `None` e o item PASSA, então parse quebrado
infla, não zera).

Era hipótese (a), com um agravante não previsto: **o ZIP dos dados abertos
atrasa ~1 dia** (`Last-Modified` de domingo 10h GMT numa segunda ao meio-dia,
sem nenhum registro de sábado em diante). Some-se a taxa base real — 1,48
doc/dia corrido das ~25 cobertas, ~0,95/dia nas últimas seis semanas, com uma
sequência de 6 dias seguidos sem nada em julho — e 72h dava 0 em **9,4% dos
dias** com tudo funcionando. Simulação de 181 dias: 168h dá 0 em 0% deles.

Consequência para a documentação: a premissa de que a CVM "sai no minuto do
protocolo" é **falsa** para esta rota. A imprensa chega antes. A CVM vale como
confirmação documental, não como antecipação.

Correções aplicadas:
- `PRIMARY_WINDOW_HOURS = 168`, separada da janela de imprensa (168h na
  imprensa encheria o feed de matéria velha). Vale para DOU e CVM.
- Categorias acrescentadas: oferta de distribuição pública, recuperação
  judicial, transação entre partes relacionadas, debêntures. Estavam sendo
  descartadas e são material de tese.
- 13% dos documentos vêm sem `Assunto` e viravam título vazio ("YDUQS —
  Comunicado ao Mercado"). Agora caem para `Tipo`/`Espécie`.

Resultado: 1 → 3 documentos no dia do teste.

---

## 8. Armadilhas que já custaram tempo nesta sessão

- ⚠️ **RLS do Supabase.** A `migration_06` original do `ans-research` concedia
  SELECT só ao role `authenticated`, e a autenticação do site foi removida em
  jun/2026 — hoje a página acessa como `anon`. **Sem policy para `anon`, a
  página devolve 0 linhas sem erro nenhum.** É a falha mais provável desta
  integração. O `supabase/migration_articles.sql` corrige e é idempotente
  (convive com a tabela `articles` que já existe, inerte, no projeto
  `uhulsnkchmnxsowsxkoc`). Confira com o `curl` comentado no fim do arquivo.
- ⚠️ **Console do Windows é cp1252.** Um `→` ou `═` num `print` derruba o
  processo com `UnicodeEncodeError` — aconteceu duas vezes. `hunt.py` e
  `scripts/watchdog.py` reconfiguram stdout para UTF-8 logo no início; **mantenha
  isso**. Para script avulso: `$env:PYTHONIOENCODING="utf-8"`.
- **O Vinicius usa PowerShell, não CMD.** `%USERPROFILE%` não expande — é
  `$env:USERPROFILE`. Chame o Python pelo venv direto
  (`.\.venv\Scripts\python.exe`) em vez de depender do `activate`.
- **No PowerShell, `>` e `|` escondem o erro e o Python bufferiza a saída.** Use
  `Tee-Object` para ver na tela e gravar ao mesmo tempo. **Mas o `Tee-Object` do
  PowerShell 5.1 grava UTF-16LE** — `grep`/`Select-String` sobre esse arquivo não
  acham nada e o silêncio parece "não rodou". Para reler depois, prefira
  `| Out-File -Encoding utf8`.
- **Repositório privado** queima os 2.000 min/mês do Actions em ~1 dia com o loop
  de 5 minutos. Público resolve; se por algum motivo virar privado, aumente
  `SLEEP_SECONDS` no `hunt-loop.yml`.
- **Git do `ans-research` roda SÓ pelo Windows** (há histórico de conflito de
  permissão em `.git/objects` quando git roda ora no Windows ora em sandbox).

---

## 9. O que fazer em seguida, em ordem

Cada item tem critério de pronto. Não avance sem ele.

### 9.1 Confirmar o CVM — ✅ FEITO 03/ago/2026
Não era bug de filtro: janela curta contra fonte que atrasa. Ver §7.

### 9.2 Criar o banco — ✅ FEITO 03/ago/2026
`migration_articles.sql` rodado no SQL Editor. As três tabelas respondem.
A `articles` já tinha **675 linhas** do hunter v1 (28/mai a 04/jul) — não estava
inerte como o §1 supunha. Ficam como histórico e alimentam o dedup.
**Pendente:** validar a leitura anônima com a chave *publishable* (o `curl` do
fim do SQL). Sem isso, a página pode devolver 0 linhas sem erro — é a falha mais
provável desta integração e ainda não foi testada.

### 9.3 Primeira gravação real — ✅ FEITO 03/ago/2026
108 artigos gravados, 29 fontes em `source_health`. Mas a **calibragem que este
passo pedia revelou 73% de entulho** — ver §13. As correções foram aplicadas; as
108 linhas originais ainda incluem o lixo e precisam de limpeza.

### 9.4 Ligar as chaves de LLM — ✅ FEITO 03/ago/2026
Groq e Gemini configuradas. Duas armadilhas caras, ambas documentadas no
`CLAUDE.md`: comentário na mesma linha do `.env` vira o valor da chave, e
`gemini-2.0-flash` dá 429 com "limit: 0" em conta nova (os `2.5` dão 404 "no
longer available to new users"). O default virou `gemini-flash-lite-latest`.
Groq bate o limite a cada ~3 lotes; o backoff por `Retry-After` resolve sem
cair no fail-open — antes disso, 5 de 23 lotes entravam sem nenhum julgamento.

### 9.4b Registrar o que o LLM REPROVOU — ✅ FEITO 03/ago/2026
`migration_judged_urls.sql` rodado. Validado com dois runs seguidos:
`known_urls: 38 aprovadas + 114 reprovadas` → `Deduplicação: 0 novos (de 152)`.
Segundo run não fez uma única chamada de LLM. Descrição do problema abaixo,
mantida porque explica por que a tabela existe.

<details><summary>Diagnóstico original</summary>
`known_urls()` lê a tabela `articles`, que só tem o **aprovado**. O reprovado
não é registrado e volta ao gate a cada run, indefinidamente. Medido em
03/ago/2026: de 81 artigos "novos" num run, 79 eram rejeitados de rodadas
anteriores — 7 lotes de LLM a cada 5 minutos para reconfirmar a mesma coisa.
Com o loop no Actions, o free tier da Groq não aguenta.

Conserto: tabela `judged_urls (url text primary key, judged_at timestamptz)`,
gravada com os reprovados no fim do `judge_batch`, e `known_urls()` passa a unir
as duas. Purgar por `judged_at` mais velho que `LLM_LOOKBACK_DAYS`.
**Pronto quando:** dois runs seguidos, sem notícia nova entre eles, mostrarem
`Deduplicação contra o banco: 0 novos`.
</details>

### 9.4c Calibrar o rigor do gate — DECISÃO PENDENTE DO VINICIUS
Em 03/ago/2026 os mesmos 119 candidatos foram julgados por dois critérios:

| Juiz | Aprovados | Taxa |
|---|---|---|
| Groq/Gemini com o prompt atual | ~30 | 25% |
| Julgamento manual, escopo estrito | 5 | 4% |

A diferença não é ruído — é definição de escopo. O manual rejeitou tudo que é
CADE fora do setor (cartel de ferrovia, B3, Bayer), vigilância sanitária de
produto, logística de exame do INEP (Celpe-Bras, PND, Encceja) e varejo
farmacêutico (AstraZeneca/BMS, Assaí Farma, demanda por suplementos). O LLM
aprova parte disso por serem "regulação" ou "saúde".

⚠️ Os 114 reprovados manualmente foram gravados em `judged_urls` e **não voltam
ao gate por `LLM_LOOKBACK_DAYS` (7 dias)**. Se o critério estrito estiver
errado, limpe: `delete from public.judged_urls;`

### 9.5 Publicar a página
Copiar `noticias.html` para `C:\ans-research\dashboards\`, preencher no topo do
arquivo `SUPABASE_URL` e `SUPABASE_PUBLISHABLE_KEY`, colar o card em
`dashboards/index.html` dentro de `<div class="card-grid">`, e adicionar
`noticias.html` ao `<select>` da navbar das outras páginas (o nome exibido é
**"Notícias"** — o `index.html` e a navbar devem sempre usar o mesmo nome).
**Pronto quando:** a página abrir com notícias reais localmente, antes de
qualquer deploy.

⚠️ Antes de deployar, confira que `dashboards/noticias.html` está **tracked** no
git. Há incidente registrado (05/jul/2026) de arquivo do `dashboards/` fora do
tracking derrubando o site no deploy.

### 9.6 Subir para o GitHub e ligar a automação
Repositório **público** `health-ed-news-hunter`. Cadastrar os Secrets
(`SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`,
`MISTRAL_API_KEY`, `GEMINI_API_KEY`) e habilitar os workflows.
**Pronto quando:** o `hunt-loop` completar uma iteração e o `watchdog` passar.

---

## 10. Sobre o workflow `report.yml`

Ele existe por um motivo que vale entender: roda o `--check-sources` e o
`--dry-run` num runner do GitHub (que tem internet aberta) e **faz commit do
resultado em `reports/` no próprio repositório**. Quem quiser ler — pessoa ou
agente — só precisa de `git pull`.

Foi criado porque o agente da sessão anterior tinha rede com allowlist e não
alcançava nenhum site de notícia, o que transformou cada diagnóstico em pedido de
"rode isso e cole a saída". Rodando em Claude Code local isso deixa de ser
necessário para o desenvolvimento, mas o workflow continua útil como
monitoramento: o cron diário registra a saúde das fontes num arquivo versionado,
então dá para ver *quando* uma fonte morreu, não só *que* morreu.

---

## 11. Como validar qualquer mudança

```powershell
cd C:\health-ed-news-hunter
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m pytest -q          # calibragem das keywords
.\.venv\Scripts\python.exe hunt.py --check-sources   # saúde das fontes
.\.venv\Scripts\python.exe hunt.py --dry-run         # o que entraria no banco
```

Flags do `hunt.py`: `--dry-run` (não grava), `--no-llm` (pula o gate caro),
`--no-primary` (pula DOU/CVM), `--check-sources` (testa e sai).

---

## 12. Segurança

- Nunca commitar `.env`. Já está no `.gitignore`.
- A **secret key** do Supabase vive só no `.env` local e nos Secrets do Actions.
  Jamais no front-end, jamais no repositório público.
- Tratar os arquivos de `.github/workflows/` como privilegiados: eles recebem a
  secret key.
- Ao interpolar dado gerado em `innerHTML` na página, passar por `escapeHtml()`.
  Preferir `textContent` para rótulos simples.

---

## 13. A calibragem de 03/ago/2026 — o que a primeira gravação real revelou

O passo 9.3 pedia "ler a amostra". A amostra mostrou **73% de entulho**: das 108
linhas gravadas, 79 eram DOU/ANVISA/MEC repetitivos. Quatro causas distintas,
todas corrigidas:

**1. O título do DOU não é julgável.** "RESOLUÇÃO-RE nº 2.967" é o que chegava
ao gate de LLM (o DOU entra com `needs_filter=False`), e a regra do "na dúvida,
relevante" aprovava tudo. O JSON traz `content`; passou a ser o snippet.

**2. ANVISA afogava o DOU.** 98 de 119 atos em 3 dias úteis, todos registro
produto a produto. Restrita à Diretoria Colegiada. Ver `DOU_ANVISA_UNIDADES`.

**3. O prompt tratava ANVISA como se fosse ANS.** Passou a excluir
explicitamente vigilância sanitária de produto (apreensão, recolhimento,
registro, proibição de irregular) e a mandar julgar ato do DOU pelo texto.

**4. O MEC serializa matéria por estado.** 14 linhas de "Fies 2026: \<estado\>
registrou X mil inscritos". `collapse_serial_articles` colapsa grupos de 3+ que
compartilhem o texto depois de removidos dígitos, magnitudes e nome de UF.

⚠️ **A trava do UF nesse colapso não é opcional.** Sem ela, a função engoliu 11
portarias SERES distintas na primeira versão — o título do DOU é só o número do
ato, então tirar os dígitos torna todas idênticas. Há teste de regressão.

**5. A prévia do in.gov.br é truncada em 403 caracteres**, e nas portarias da
SERES esses 403 são inteiramente citação de decreto. `enrich_dou_articles`
busca a página do ato (seletor `div.texto-dou`), corta no "resolve:" e remonta
com a tabela do anexo — que é onde aparece a mantenedora. É a diferença entre
"PORTARIA SERES/MEC Nº 364" e "renovado Pedagogia, 120 vagas, VITRU EDUCACAO
S.A.". Roda DEPOIS do dedup, então ato já gravado nunca é rebuscado.

Resultado: 108 → 32 artigos, sem perder nenhum sinal que importava.

**Ainda marginal, não tratado:** ANAHP passa PR de hospital ("Hospital Encore
chega aos 35 anos"), 3 de 32; e o INEP às vezes devolve página de seção como
notícia ("Avaliação in loco", "Censo da Educação Superior").
