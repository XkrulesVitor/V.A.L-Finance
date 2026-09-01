-- Schema completo do ia-trading.
--
-- O arquivo e idempotente de proposito: da pra colar ele inteiro no SQL
-- Editor do Supabase quantas vezes for preciso, sem quebrar nada. Por
-- isso os `drop policy if exists` antes de cada `create policy` -- sem
-- eles, a segunda execucao falha em "policy already exists" e a pessoa
-- fica sem saber se o resto rodou.

-- ====================================================================
-- decisions -- o registro central do sistema
-- ====================================================================
-- Cada ciclo do cron job gera um registro aqui. Nos passos 5-8 do
-- roteiro, llm_output/risk_result/order_result/outcome passam a ser
-- preenchidos; hoje (passos 1-2) valem market_snapshot, features e
-- status='skeleton_check'.
create table if not exists decisions (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  symbol text not null,
  market_snapshot jsonb,
  features jsonb,
  llm_output jsonb,
  risk_result jsonb,
  order_result jsonb,
  status text not null default 'pending',
  outcome jsonb
);

-- ====================================================================
-- portfolio -- estado da carteira simulada
-- ====================================================================
-- Populado a partir do passo 6/8 do roteiro.
--
-- `asset` guarda o PAR (BTCUSDT), nao a moeda (BTC): preco de entrada,
-- stop e alvo sao propriedades da operacao naquele par, e usar o par
-- alinha a chave com a coluna `symbol` de `decisions`.
create table if not exists portfolio (
  asset text primary key,
  quantity numeric not null default 0,
  updated_at timestamptz not null default now()
);

-- Passo 6 (Risk Engine): a tabela precisa lembrar a que preco a posicao
-- foi aberta e quais niveis de saida foram fixados naquele momento.
--
-- Sem estas tres colunas a regra mais importante do Risk Engine nao tem
-- como existir: ela compara o preco atual contra um stop-loss REGISTRADO
-- QUANDO A POSICAO ABRIU, e forca a saida se foi rompido -- inclusive
-- contra um HOLD do cerebro. Um nivel recalculado a cada ciclo nao
-- serviria: ele acompanharia o preco caindo e nunca seria rompido.
--
-- `add column if not exists` mantem o arquivo idempotente, entao da pra
-- colar o schema.sql inteiro de novo sem quebrar o que ja existe.
alter table portfolio add column if not exists preco_entrada numeric;
alter table portfolio add column if not exists stop_loss numeric;
alter table portfolio add column if not exists take_profit numeric;

-- ====================================================================
-- backtest_runs -- uma linha por rodada de backtest (passos 3 e 4)
-- ====================================================================
-- Guarda so metricas e parametros. Curva de capital e lista de
-- operacoes NAO vem pra ca: sao milhares de pontos por rodada e o free
-- tier tem 500MB. O que responde "a estrategia X bateu a Y?" sao as
-- metricas; o detalhe fica no JSON local que o runner grava em
-- backend/backtest/resultados/.
--
-- E a tabela que torna o passo 7 possivel: a baseline do passo 4 fica
-- registrada com periodo e parametros, entao quando a estrategia
-- hibrida rodar, a comparacao e contra um numero gravado, e nao contra
-- memoria (principio 6 e metodologia da secao 11).
create table if not exists backtest_runs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  strategy_name text not null,
  symbol text not null,
  period_start timestamptz not null,
  period_end timestamptz not null,
  params jsonb,
  metrics jsonb,
  notes text
);

-- ====================================================================
-- RLS
-- ====================================================================
-- Leitura publica (o painel usa a chave anon), escrita restrita a
-- service role (o backend, que ignora RLS por padrao).
alter table decisions enable row level security;
alter table portfolio enable row level security;
alter table backtest_runs enable row level security;

drop policy if exists "leitura publica decisions" on decisions;
create policy "leitura publica decisions" on decisions
  for select using (true);

drop policy if exists "leitura publica portfolio" on portfolio;
create policy "leitura publica portfolio" on portfolio
  for select using (true);

drop policy if exists "leitura publica backtest_runs" on backtest_runs;
create policy "leitura publica backtest_runs" on backtest_runs
  for select using (true);

-- Projetos criados a partir de 30/05/2026 precisam de grant explicito
-- pra API (PostgREST) expor a tabela, alem da policy de RLS acima.
grant select on decisions to anon, authenticated;
grant select on portfolio to anon, authenticated;
grant select on backtest_runs to anon, authenticated;
