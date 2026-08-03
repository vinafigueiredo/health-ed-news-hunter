-- ═════════════════════════════════════════════════════════════════════════════
-- Health & Education News Hunter — schema
--
-- Rodar UMA vez no SQL Editor do Supabase. É idempotente: pode rodar de novo
-- sem quebrar nada.
--
-- ⚠️  CONTEXTO IMPORTANTE
-- A tabela `articles` PROVAVELMENTE JÁ EXISTE neste projeto: foi criada pela
-- migration_06_news_hunter.sql do ans-research em mai/2026 e ficou inerte
-- desde jul/2026. Este script usa CREATE TABLE IF NOT EXISTS + ALTER ... ADD
-- COLUMN IF NOT EXISTS justamente para conviver com ela.
--
-- ⚠️  DIFERENÇA CRÍTICA PARA A MIGRATION ANTIGA
-- A migration_06 concedia leitura só ao role `authenticated`. A autenticação do
-- site foi removida em jun/2026 — hoje o dashboard acessa como `anon`. Se a
-- política de leitura não for recriada para `anon`, a página de notícias volta
-- 0 linhas sem nenhum erro visível. É o bug mais provável desta integração.
-- ═════════════════════════════════════════════════════════════════════════════

-- ── 1. Tabela de artigos ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.articles (
  url               TEXT PRIMARY KEY,
  domain            TEXT,
  source_name       TEXT,
  title             TEXT NOT NULL,
  snippet           TEXT,
  published_at      TIMESTAMPTZ,
  found_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  matched_keywords  TEXT[] DEFAULT '{}'::TEXT[]
);

ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS domain           TEXT;
ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS source_name      TEXT;
ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS snippet          TEXT;
ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS published_at     TIMESTAMPTZ;
ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS found_at         TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE public.articles ADD COLUMN IF NOT EXISTS matched_keywords TEXT[] DEFAULT '{}'::TEXT[];

-- Ordenação do feed é sempre por found_at DESC (não por published_at: fonte sem
-- data ficaria eternamente no fim). O índice cobre a query da home.
CREATE INDEX IF NOT EXISTS articles_found_at_idx    ON public.articles (found_at DESC);
CREATE INDEX IF NOT EXISTS articles_published_at_idx ON public.articles (published_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS articles_source_idx      ON public.articles (source_name);

-- ── 2. Runs — alimenta o "sincronizado há X min" do dashboard ────────────────
CREATE TABLE IF NOT EXISTS public.hunter_runs (
  id             BIGSERIAL PRIMARY KEY,
  ran_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  articles_new   INTEGER NOT NULL DEFAULT 0,
  articles_seen  INTEGER NOT NULL DEFAULT 0
);
ALTER TABLE public.hunter_runs ADD COLUMN IF NOT EXISTS articles_seen INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS hunter_runs_ran_at_idx ON public.hunter_runs (ran_at DESC);

-- ── 3. Saúde das fontes — lida pelo watchdog ─────────────────────────────────
CREATE TABLE IF NOT EXISTS public.source_health (
  source        TEXT PRIMARY KEY,
  last_ok       TIMESTAMPTZ,
  last_attempt  TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_count    INTEGER NOT NULL DEFAULT 0
);

-- ── 4. RLS ───────────────────────────────────────────────────────────────────
ALTER TABLE public.articles      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hunter_runs   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.source_health ENABLE ROW LEVEL SECURITY;

-- Leitura pública (anon + authenticated). O site é aberto desde jun/2026.
-- Só um feed de notícias públicas fica exposto — sem take, sem leitura
-- direcional, sem nada proprietário. Se algum dia voltar a haver classificação
-- própria nesta tabela, esta política precisa ser revista.
DROP POLICY IF EXISTS articles_public_read ON public.articles;
CREATE POLICY articles_public_read ON public.articles
  FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS hunter_runs_public_read ON public.hunter_runs;
CREATE POLICY hunter_runs_public_read ON public.hunter_runs
  FOR SELECT TO anon, authenticated USING (true);

-- source_health é operacional: só a secret key (que bypassa RLS) enxerga.
-- RLS ligada e SEM policy = leitura anônima devolve 0 linhas.

-- Escrita: nenhuma policy de INSERT/UPDATE para anon. O hunter grava com a
-- secret key, que ignora RLS. Sem isso, qualquer visitante do site poderia
-- inserir linha na tabela.

GRANT SELECT ON public.articles    TO anon, authenticated;
GRANT SELECT ON public.hunter_runs TO anon, authenticated;

-- ── 5. Retenção ──────────────────────────────────────────────────────────────
-- hunter_runs cresce ~288 linhas/dia com o loop de 5 min. Só interessa o
-- último. Chame de vez em quando (ou agende com pg_cron, se habilitado).
CREATE OR REPLACE FUNCTION public.prune_hunter_runs()
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  DELETE FROM public.hunter_runs WHERE ran_at < now() - INTERVAL '2 days';
$$;

-- Artigos: 18 meses é folgado para uma página de feed. Ajuste se quiser série
-- histórica maior.
CREATE OR REPLACE FUNCTION public.prune_articles()
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  DELETE FROM public.articles WHERE found_at < now() - INTERVAL '18 months';
$$;

-- ── 6. Conferência ───────────────────────────────────────────────────────────
-- Depois de rodar, valide que a leitura anônima funciona. Com a chave
-- PUBLISHABLE (não a secret), no terminal:
--
--   curl "https://SEU-PROJETO.supabase.co/rest/v1/articles?select=url,title&limit=3" \
--     -H "apikey: SUA_PUBLISHABLE_KEY"
--
-- Se vier [] com a tabela cheia, a policy de anon não pegou.
