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

-- =====================================================================
-- SEIS CARTEIRAS (setembro/2026) -- ver ARCHITECTURE.md, secao 11, e
-- backend/backtest/PRE_REGISTRO_6_CARTEIRAS.md.
--
-- A migracao tem DUAS ETAPAS, e a ordem importa:
--
--   Etapa A (abaixo, so aditiva): pode rodar com o codigo antigo no ar.
--   Deploy do codigo multi-carteira.
--   Etapa B (no fim deste arquivo): troca a chave de `portfolio` e o
--   indice de idempotencia de `decisions`. Rodar SO depois do deploy:
--   com a chave nova, o `upsert(on_conflict="asset")` do codigo antigo
--   falha. Com o codigo novo e a chave antiga, so a T1 funciona (as
--   outras carteiras falham alto, nunca em silencio -- `reivindicar_candle`
--   detecta o indice antigo).
-- =====================================================================

-- ---------- Etapa A ----------

-- Qual carteira e dona de cada conta e de cada decisao. O default 'T1'
-- existe so para as linhas antigas: o codigo novo sempre passa a carteira
-- explicitamente, e um esquecimento nao pode gravar como T1 em silencio.
alter table portfolio add column if not exists carteira text not null default 'T1';
alter table decisions add column if not exists carteira text not null default 'T1';
alter table decisions add column if not exists regra_versao text;

-- Estado das contas que a regra precisa lembrar entre ciclos.
alter table portfolio add column if not exists alvo_pct numeric;          -- stop gain em % (G1, G3)
alter table portfolio add column if not exists meta_entrada jsonb;        -- dia do sinal, ATR, N, tipo de stop
alter table portfolio add column if not exists armado boolean not null default true;  -- rearme depois do stop gain
alter table portfolio add column if not exists recuo_dia date;
alter table portfolio add column if not exists ultima_saida_em bigint;    -- ms do gatilho da ultima saida
alter table portfolio add column if not exists ultima_saida_motivo text;
alter table portfolio add column if not exists entrada_em bigint;         -- ms do preenchimento da entrada

-- Unicos novos, criados ANTES de remover os antigos (etapa B). O de
-- `portfolio` convive com a chave antiga porque hoje so ha linhas da T1.
create unique index if not exists portfolio_carteira_ativo_unico
  on portfolio (carteira, asset);
create unique index if not exists decisions_carteira_par_candle_unico
  on decisions (carteira, symbol, candle_fechamento_em)
  where candle_fechamento_em is not null;

-- As carteiras, com a descricao para leigo e a regra (usada pelo explicador).
create table if not exists carteiras (
  id text primary key,
  nome text not null,
  descricao_leiga text not null,
  descricao_regra text not null,
  familia text not null,             -- 'tendencia' ou 'stop_gain'
  regra_versao text not null,
  parametros jsonb,
  ativa_desde timestamptz,
  ativa boolean not null default false,
  ordem int not null default 0
);

-- Patrimonio de cada conta no fechamento de cada dia UTC: alimenta as
-- curvas do site sem ler todas as decisoes.
create table if not exists patrimonio_diario (
  carteira text not null,
  asset text not null,
  dia_utc date not null,
  patrimonio numeric not null,
  posicionada boolean not null,
  preco_fechamento numeric not null,
  gravado_em timestamptz not null default now(),
  primary key (carteira, asset, dia_utc)
);

-- Painel de IAs (T3 e G3). Uma entrada congelada por dia e par; uma
-- linha por TENTATIVA de voto; um veredito por dia e par, que as duas
-- carteiras leem.
create table if not exists painel_entradas (
  id uuid primary key default gen_random_uuid(),
  dia_utc date not null,
  simbolo text not null,
  prompt_versao text not null,
  sha256_sistema text not null,
  sha256_usuario text not null,
  sha256_embutido text not null,
  entrada_json jsonb not null,
  prompt_texto text not null,
  fng_hoje_ts bigint,
  fng_7d_ts bigint,
  rss_status jsonb,
  rss_itens jsonb,
  rss_mais_antigo jsonb,
  headlines_estado text,
  criado_em timestamptz not null default now(),
  unique (dia_utc, simbolo, prompt_versao)
);

create table if not exists painel_votos (
  id uuid primary key default gen_random_uuid(),
  tipo text not null default 'painel',
  dia_utc date not null,
  simbolo text not null,
  vaga text not null,                -- G, N ou C
  modelo_pedido text not null,
  modelo_efetivo text,
  provedor text not null,
  id_geracao text,
  tentativa int not null,
  forma_prompt text not null default 'sistema',
  inicio timestamptz not null default now(),
  latencia_ms int,
  http_status int,
  limit_source text,
  erro text default 'em_andamento',
  resposta_bruta text,
  json_valido boolean not null default false,
  trend_call text,
  confidence numeric,
  case_for_up text,
  case_for_down text,
  resumo_pt text,
  tokens_entrada int,
  tokens_saida int,
  tokens_raciocinio int,
  temperature numeric,
  max_tokens int,
  numeros_sem_origem int
);
-- Nunca se repergunta uma vaga que ja votou no dia: repetir o sorteio e vies.
create unique index if not exists painel_votos_um_voto_valido
  on painel_votos (dia_utc, simbolo, vaga)
  where json_valido and tipo = 'painel';

create table if not exists painel_veredito (
  id uuid primary key default gen_random_uuid(),
  dia_utc date not null,
  simbolo text not null,
  prompt_versao text not null,
  regra_versao text not null,
  votos jsonb not null,
  votos_ids jsonb not null,
  soma int,
  validos int not null,
  veredito text not null,            -- compra, venda, neutro, sem_quorum
  congelado_em timestamptz not null default now(),
  ciclo_congelamento int,
  motivo_congelamento text,
  unique (dia_utc, simbolo)
);

alter table carteiras enable row level security;
alter table patrimonio_diario enable row level security;
alter table painel_entradas enable row level security;
alter table painel_votos enable row level security;
alter table painel_veredito enable row level security;
drop policy if exists "leitura publica carteiras" on carteiras;
create policy "leitura publica carteiras" on carteiras for select using (true);
drop policy if exists "leitura publica patrimonio_diario" on patrimonio_diario;
create policy "leitura publica patrimonio_diario" on patrimonio_diario for select using (true);
drop policy if exists "leitura publica painel_entradas" on painel_entradas;
create policy "leitura publica painel_entradas" on painel_entradas for select using (true);
drop policy if exists "leitura publica painel_votos" on painel_votos;
create policy "leitura publica painel_votos" on painel_votos for select using (true);
drop policy if exists "leitura publica painel_veredito" on painel_veredito;
create policy "leitura publica painel_veredito" on painel_veredito for select using (true);
grant select on carteiras, patrimonio_diario, painel_entradas, painel_votos, painel_veredito to anon, authenticated;

-- ---------- Etapa B (rodar SO depois do deploy do codigo multi-carteira) ----------
-- begin;
--   drop index if exists decisions_par_candle_unico;
--   alter table portfolio drop constraint if exists portfolio_pkey;
--   alter table portfolio add primary key (carteira, asset);
--   -- A trava de reentrada agora le portfolio.ultima_saida_em. Se a T1 saiu
--   -- pelo codigo antigo (que nao gravava a coluna), copia o instante da
--   -- ultima venda dela, para a trava valer na primeira execucao nova.
--   update portfolio p set
--     ultima_saida_em = coalesce((d.order_result->>'gatilho_em')::bigint, d.candle_fechamento_em),
--     ultima_saida_motivo = d.order_result->>'motivo'
--   from (select distinct on (symbol) symbol, order_result, candle_fechamento_em from decisions
--         where carteira = 'T1' and status = 'executed' and order_result->>'lado' = 'SELL'
--         order by symbol, candle_fechamento_em desc) d
--   where p.carteira = 'T1' and p.asset = d.symbol and p.quantity = 0 and p.ultima_saida_em is null;
-- commit;
