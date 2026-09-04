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

-- ====================================================================
-- Passo 8a -- forward test (estrategia decidindo ao vivo, execucao
-- simulada por nos ao preco real de mercado)
-- ====================================================================

-- CAIXA POR PAR.
--
-- Cada par e uma conta simulada independente, com seu proprio capital --
-- exatamente como no backtest, onde cada ativo rodou sozinho partindo de
-- 10.000. Sem esse espelhamento o resultado ao vivo nao seria comparavel
-- aos numeros da secao 11, e a comparacao e o unico motivo do passo 8a
-- existir.
--
-- O caixa fica na MESMA LINHA da quantidade e dos niveis de risco de
-- proposito. Um `upsert` grava a linha inteira de uma vez, e o Postgres
-- garante atomicidade por linha -- entao nao existe estado intermediario
-- onde a compra foi registrada mas o caixa ainda nao foi debitado, ou
-- pior, onde a posicao existe sem stop. Em duas tabelas (ou duas
-- escritas) esse buraco existiria, e o processo do cron morre a cada
-- ciclo, entao ele seria alcancado mais cedo ou mais tarde.
alter table portfolio add column if not exists caixa numeric;

-- IDEMPOTENCIA -- de qual candle esta decisao tratou.
--
-- O problema: um disparo manual junto com o agendado, ou um retry do
-- runner, faz o mesmo ciclo rodar duas vezes. Sem chave, viram duas
-- compras.
--
-- A chave natural e o candle fechado que gerou a decisao: para um dado
-- par, cada candle so pode ser decidido uma vez. Nao inventamos um id --
-- ele vem do proprio dado.
alter table decisions add column if not exists candle_fechamento_em bigint;

-- E a restricao no BANCO, nao no codigo.
--
-- Conferir antes de inserir ("ja existe decisao pra este candle?") tem
-- janela de corrida: duas execucoes podem consultar, as duas verem que
-- nao existe, e as duas inserirem. Um indice unico nao tem essa janela:
-- a segunda insercao simplesmente falha, e falhar e a resposta certa.
--
-- Parcial (`where ... is not null`) pra nao afetar as linhas antigas de
-- `skeleton_check`, que nao tem candle associado e sao muitas por hora.
create unique index if not exists decisions_par_candle_unico
  on decisions (symbol, candle_fechamento_em)
  where candle_fechamento_em is not null;
