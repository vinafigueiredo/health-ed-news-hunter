# Health & Education News Hunter

Robô que coleta notícias de saúde suplementar e educação superior, filtra o que
interessa a uma mesa de equity research e grava no Supabase. Um dashboard lê o
Supabase e mostra o feed.

**Não classifica direção de mercado.** Não existe take (+/−/=) aqui — por
decisão de projeto. O que sai é feed filtrado: a notícia certa, sem a leitura.
A página fica num site aberto ao público; leitura direcional não vai para lá.

```
  RSS de imprensa   ─┐
  Setoriais saúde/ed ├──► hunt.py ──► keyword ──► dedup vs banco ──► LLM ──► Supabase
  gov.br (ANS/MEC…)  │              (barato)                      (caro)         │
  DOU + CVM          ─┘                                                          ▼
                                                              dashboards/noticias.html
```

---

## Instalação

Abra o **CMD** e cole:

```cmd
cd C:\
git clone https://github.com/SEU-USUARIO/health-ed-news-hunter.git
cd C:\health-ed-news-hunter
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## Passo 1 — Validar as fontes ANTES de qualquer outra coisa

As fontes foram testadas ao vivo em 30/jul/2026 e o repo já traz as correções.
Mas feed morre sozinho o tempo todo — rode antes de qualquer coisa:

```powershell
cd C:\health-ed-news-hunter
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe hunt.py --check-sources
```

Sai uma tabela com `OK` / `VAZIO` / `ERRO` por fonte. Comente em
`hunter/sources.py` (RSS) ou `hunter/html_scrapers.py` (scrapers) tudo que vier
`ERRO`. `VAZIO` merece um olhar: às vezes é Cloudflare, às vezes o site mudou o
padrão de URL e basta ajustar o `href_re`.

Fazer isso agora evita a pior falha desse tipo de sistema: a fonte que morre em
silêncio e ninguém nota por três meses.

---

## Passo 2 — Banco (Supabase)

1. Use o projeto Supabase que já existe (o mesmo do `ans-research`) — a tabela
   `articles` foi criada lá em mai/2026 e está inerte desde jul/2026.
2. **SQL Editor → New query** → cole `supabase/migration_articles.sql` → **Run**.
   É idempotente: conviver com a tabela antiga é o motivo de existir.
3. Copie a **Project URL** e a **secret key** (Project Settings → API).

> ⚠️ A migration antiga liberava leitura só para `authenticated`, e a
> autenticação do site foi removida em jun/2026. Se a política de `anon` não for
> criada, a página de notícias devolve **zero linhas sem erro nenhum**. É a
> falha mais provável desta integração — o SQL novo já corrige, mas confira com
> o `curl` que está comentado no fim do arquivo.

---

## Passo 3 — Chaves

```cmd
cd C:\health-ed-news-hunter
copy .env.example .env
notepad .env
```

Preencha `SUPABASE_URL` e `SUPABASE_SECRET_KEY`. Para o gate de relevância,
pegue pelo menos uma chave gratuita (leva ~10 min para as quatro):

| Provedor | Onde |
|---|---|
| Groq | https://console.groq.com/keys |
| Cerebras | https://cloud.cerebras.ai/ |
| Mistral | https://console.mistral.ai/ |
| Gemini | https://aistudio.google.com/app/apikey |

A cascata tenta nessa ordem e para no primeiro que responder. Sem nenhuma chave
o robô funciona — só entrega mais ruído.

---

## Passo 4 — Testar sem gravar nada

```cmd
cd C:\health-ed-news-hunter
.venv\Scripts\activate
python hunt.py --dry-run
```

Imprime o que entraria no banco, com fonte e keywords que casaram. É aqui que
você calibra: se aparecer lixo, o ajuste é em `hunter/config.py`.

Depois, rode de verdade uma vez:

```cmd
python hunt.py
```

---

## Passo 5 — Deixar rodando sozinho

1. Suba para um repositório **público** no GitHub (público = Actions gratuito e
   ilimitado; os segredos ficam nos Secrets, nunca no código).
2. **Settings → Secrets and variables → Actions → New repository secret**, um
   para cada: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `GROQ_API_KEY`,
   `CEREBRAS_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY`.
3. Aba **Actions** → habilite os workflows → rode `hunt-loop` uma vez à mão.

O `hunt-loop` roda o robô a cada 5 minutos por ~5h20 e se re-dispara. O
`watchdog` confere de hora em hora se o hunter está vivo e se alguma fonte ficou
muda — quando falha, o GitHub te manda e-mail.

> Se o repo for **privado**, o loop de 5 min queima os 2.000 min/mês do free
> tier em pouco mais de um dia. Aumente `SLEEP_SECONDS` no workflow.

---

## Ajustar a cobertura

Tudo mora em **`hunter/config.py`**. Três níveis de keyword, e a escolha do
nível é o que separa um feed útil de um feed inútil:

- **STRONG** — termo inequívoco (`Hapvida`, `sinistralidade`). Casa em qualquer
  caixa.
- **CASED** — sigla que colide com palavra comum (`ANS`, `CADE`, `SERES`). Casa
  só na forma maiúscula.
- **CONTEXT** — termo que existe fora do setor (`reajuste`, `captação`,
  `Alice`, `Cruzeiro do Sul`). Casa só se houver marcador do setor no texto.

Mexeu no config? Rode os testes:

```cmd
cd C:\health-ed-news-hunter
.venv\Scripts\activate
pip install pytest
pytest -q
```

Os testes não conferem a lógica — conferem a calibragem. Cada caso é um falso
positivo real que a lista produziria se alguém promovesse um termo ambíguo para
STRONG sem pensar.

---

## Estrutura

| Caminho | Papel |
|---|---|
| `hunt.py` | Runner. `--dry-run`, `--no-llm`, `--no-primary`, `--check-sources` |
| `hunter/config.py` | **O universo de cobertura.** É o arquivo que mais muda |
| `hunter/sources.py` | Feeds RSS (imprensa + setoriais) |
| `hunter/html_scrapers.py` | Sites sem RSS — gov.br e entidades, por padrão de URL |
| `hunter/primary_sources.py` | **DOU e CVM** — o diferencial sobre um agregador |
| `hunter/fetcher.py` | Coleta paralela, janela, dedup por URL |
| `hunter/filter.py` | Gate barato: keyword em três níveis |
| `hunter/relevance.py` | Gate caro: LLM em lote, cascata de 4 provedores |
| `hunter/sync.py` | Push para o Supabase |
| `hunter/check_sources.py` | O validador do Passo 1 |
| `scripts/watchdog.py` | Alarme por e-mail via falha de workflow |
| `supabase/migration_articles.sql` | Schema + RLS |

---

## Problemas comuns

**A ANS não aparece como fonte própria.** É esperado. A listagem de notícias da
ANS é renderizada por JavaScript e não há RSS (sete caminhos testados). Os atos
da agência entram pelo DOU, que é fonte melhor. Ver o comentário em
`hunter/html_scrapers.py`.

**Uma fonte some do feed.** Rode `--check-sources`. `ERRO 403` costuma ser
Cloudflare bloqueando o IP do GitHub Actions — o `curl_cffi` já tenta contornar;
se persistir, a fonte só funciona de IP residencial (rode local).

**A página mostra 0 notícias com a tabela cheia.** É a política de `anon` no
Supabase. Teste com o `curl` do fim do `migration_articles.sql`.

**O feed veio com muito lixo.** Provavelmente nenhuma chave de LLM está
configurada — o log avisa `gate de relevância DESLIGADO`.

**O DOU parou.** O `in.gov.br` mudou o layout da página `/leiturajornal`. O log
diz exatamente isso (`<script id='params'> não encontrado`). É o coletor mais
frágil do repo, por natureza.
