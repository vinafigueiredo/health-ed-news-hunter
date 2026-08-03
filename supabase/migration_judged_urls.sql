-- ═════════════════════════════════════════════════════════════════════════════
-- judged_urls — memória do que o gate de LLM já REPROVOU
--
-- Rodar UMA vez no SQL Editor. Idempotente.
--
-- ⚠️  POR QUE ISTO EXISTE
-- `known_urls()` lia só a tabela `articles`, que guarda o que foi APROVADO. O
-- artigo reprovado não ficava registrado em lugar nenhum — então o loop de 5
-- minutos coletava, filtrava e mandava para o LLM de novo, indefinidamente,
-- para chegar sempre à mesma conclusão.
--
-- Medido em 03/ago/2026: de 81 artigos "novos" num run, 79 eram rejeitados de
-- rodadas anteriores. São ~7 lotes de LLM a cada 5 minutos, 288 vezes por dia,
-- puro desperdício. Nenhum free tier aguenta isso.
--
-- Esta tabela é OPERACIONAL, não editorial: não vai para a página, e a leitura
-- anônima fica fechada de propósito (RLS ligada, sem policy).
-- ═════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.judged_urls (
  url        TEXT PRIMARY KEY,
  judged_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  verdict    TEXT NOT NULL DEFAULT 'rejected'
);

CREATE INDEX IF NOT EXISTS judged_urls_judged_at_idx ON public.judged_urls (judged_at DESC);

ALTER TABLE public.judged_urls ENABLE ROW LEVEL SECURITY;
-- Sem policy: só a secret key (que bypassa RLS) enxerga. É registro interno.

-- Retenção: a tabela só precisa cobrir a janela do LLM_LOOKBACK_DAYS. Depois
-- disso, reavaliar um artigo antigo é barato e às vezes até desejável (o prompt
-- pode ter mudado).
CREATE OR REPLACE FUNCTION public.prune_judged_urls()
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  DELETE FROM public.judged_urls WHERE judged_at < now() - INTERVAL '30 days';
$$;
