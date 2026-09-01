# ia-trading — protótipo

IA que acompanha o mercado de cripto (Binance) e decide operações, começando em conta testnet.

**Antes de mexer no código, leia [`ARCHITECTURE.md`](./ARCHITECTURE.md)** — é o documento com todas as decisões de arquitetura, o porquê de cada uma, o schema do banco e o status atual do roteiro. Este README aqui é só o "como rodar".

**Status atual:** Passos 1 a 6 concluídos, **passo 7 parcial**. O cron job coleta candles, descarta o que não fechou, calcula indicadores e grava no Supabase. Existe motor de backtest, baselines medidas, cérebro (Gemini, provedor trocável) e Risk Engine com autoridade para sobrepor o cérebro. **Nenhuma ordem foi enviada, nem em testnet.** A estratégia híbrida perdeu para o comprar-e-segurar no BTC e ganhou no BNB — amostra dividida, não vantagem demonstrada (seção 11 do `ARCHITECTURE.md`).

## Estrutura

- `backend/` — Python. Roda como cron job no Render.
  - `adapters/binance_adapter.py` — tudo que é específico da Binance, isolado atrás de uma interface fixa (`buscar_preco`, `buscar_candles`, `enviar_ordem`...). Expandir pra outro mercado depois é escrever um adapter novo com essas mesmas funções.
  - `db/supabase_client.py` — conexão com o Supabase, usando a service role key.
  - `features/feature_engine.py` — transforma os candles crus em indicadores técnicos. Função pura: os mesmos candles dão sempre o mesmo resultado, sem consultar relógio nem rede (o motor de backtest do passo 3 depende disso).
  - `features/candles.py` — descarta o candle ainda em andamento. Só no caminho ao vivo: o volume parcial dele puxaria o `volume_relativo` para baixo em todo ciclo.
  - `brain/llm_analyst.py` — o cérebro. Recebe as features, devolve uma tese (`direction`/`horizon`/`confidence`/`reasoning`) validada por schema Pydantic.
  - `brain/provedores.py` — qual LLM responde. Trocar Gemini por Claude é `LLM_PROVEDOR=claude` no `.env`; adicionar um terceiro é uma classe com dois métodos. O prompt e o contrato não mudam — é isso que deixa dois modelos comparáveis no mesmo experimento.
  - `brain/cadencia.py` — quando consultar o cérebro (a cada 6h). Regra única, compartilhada pelo backtest e pelo cron job.
  - `brain/strategy.py` — o cérebro embrulhado como função de estratégia, já compatível com o motor de backtest.
  - `risk/risk_engine.py` — calcula stop-loss, take-profit e tamanho de posição a partir do ATR. **Não é um validador passivo:** se um nível já registrado for rompido, força `SELL` mesmo contra um `HOLD` do cérebro.
  - `risk/portfolio_repo.py` — casca fina entre o Supabase e o Risk Engine. Falha de leitura levanta erro em vez de degradar para "sem posição" — degradar aí faria o sistema parar de checar o stop.
  - `backtest/engine.py` — motor de backtest agnóstico à estratégia: recebe uma função de estratégia, caminha candle a candle mostrando só o passado, e devolve métricas. A estratégia devolve `BUY`/`SELL`/`HOLD`/`NO_TRADE` — o mesmo vocabulário que o cérebro vai usar.
  - `backtest/strategies.py` — as baselines (`buy_and_hold`, `ema_crossover`).
  - `brain/hybrid_strategy.py` — a estratégia híbrida: cérebro decide, Risk Engine valida e pode sobrepor. Duas cadências no mesmo loop — stop/take checado em todo candle, cérebro consultado a cada 6h.
  - `backtest/run_baseline.py` — baixa o histórico, roda as baselines, confere o resultado e grava no Supabase.
  - `backtest/run_hybrid.py` — backtest da híbrida, com cache em disco das respostas do LLM (reexecutar não gasta cota).
  - `tests/` — conferências da Feature Engine e do motor de backtest, com dados sintéticos e sem rede.
  - `main.py` — ponto de entrada do cron job.
- `frontend/` — Next.js 16 + Tailwind v4. Roda no Vercel, lê do Supabase com a chave anon (só leitura).
- `supabase/schema.sql` — schema do banco, já com as tabelas `decisions` e `portfolio` pensadas pro roteiro inteiro (não só o passo 1).
- `render.yaml` — configuração do cron job pro Render (opcional — dá pra configurar pelo dashboard também).

## Setup

### 1. Binance testnet

1. Crie uma conta em https://testnet.binance.vision
2. Gere uma API key e secret de testnet (não são as chaves da sua conta real).

### 2. Supabase

1. Crie um projeto em https://supabase.com.
2. No SQL Editor do projeto, rode o conteúdo de `supabase/schema.sql`.
3. **Atenção:** projetos criados a partir de 30/05/2026 precisam de grants explícitos pra API expor as tabelas — o `schema.sql` já inclui os `grant select`. Se a leitura no frontend não funcionar, confira em Database → Roles se `anon` tem `SELECT` nas duas tabelas.
4. Pegue a URL do projeto e as duas chaves (`anon` e `service_role`) em Project Settings → API.

### 3. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# preencha o .env com as chaves da Binance e do Supabase (service_role)
python main.py
```

Se rodar sem erro, confira no Supabase (Table Editor → decisions) se apareceram duas linhas novas (BTCUSDT e ETHUSDT) — e que a coluna `features` de cada uma veio preenchida, não vazia.

Pra conferir a Feature Engine isolada (dados sintéticos, sem rede, sem precisar de chave nenhuma):

```bash
python backend/tests/test_feature_engine.py
```

Ele roda as verificações e imprime um exemplo de saída no fim. Com `pytest` instalado, `pytest backend/tests` também funciona — mas o `pytest` fica de fora do `requirements.txt` de propósito, porque é esse arquivo que o Render instala a cada execução do cron job.

### 4. Backtest (passos 3 e 4)

O motor de backtest **não precisa de chave nenhuma** — histórico de preço é endpoint público da Binance, e o adapter tem um modo `somente_dados_publicos` justamente pra isso:

```bash
python backend/backtest/run_baseline.py --sem-supabase
```

Ele baixa um ano de candles de 1h de BTCUSDT (~8.760, cacheados localmente na primeira vez), roda `buy_and_hold` e `ema_crossover`, imprime as métricas e **confere o `buy_and_hold` contra a fórmula fechada** — se o motor divergir da conta feita à mão, ele avisa e sai com erro em vez de reportar um número em que não se pode confiar.

Sem `--sem-supabase`, também grava cada rodada na tabela `backtest_runs` (precisa do `.env` preenchido e do `schema.sql` aplicado). Outras opções: `--simbolo`, `--intervalo`, `--inicio`, `--fim`, `--capital`, `--taxa`, `--sem-cache`.

Pra conferir o motor isolado (sintético, sem rede):

```bash
python backend/tests/test_backtest_engine.py
```

Pra rodar a estratégia híbrida (cérebro + Risk Engine) — precisa de `GEMINI_API_KEY`:

```bash
python backend/backtest/run_hybrid.py --dias 30 --sem-supabase
```

O ano inteiro (`sem --dias`) são ~1.460 consultas ao Gemini e leva ~1h30 por causa do limite por minuto do free tier. As respostas ficam em cache no disco, indexadas pelo hash do prompt: reexecutar não gasta chamada nenhuma, e uma interrupção no meio não perde o que já foi feito.

⚠️ Use `testnet=False` para histórico. A testnet é onde as **ordens** serão executadas (passo 8), não uma fonte de dado histórico — o livro dela é raso e sintético, e backtest rodado em cima disso mede ruído.

### 5. Cérebro (passo 5)

Precisa de `GEMINI_API_KEY` no `.env` (pegue em https://aistudio.google.com/apikey — free tier, sem cartão). Não precisa de chave da Binance.

**Trocar de LLM** é variável de ambiente, não mudança de código:

```bash
LLM_PROVEDOR=gemini                    # padrão
LLM_PROVEDOR=claude                    # precisa de ANTHROPIC_API_KEY (pré-pago)
CLAUDE_MODELO=claude-haiku-4-5         # ~5x mais barato que o padrão
```

Prompt, contrato e cache são os mesmos nos dois — o que muda é só quem responde. Um terceiro provedor (OpenAI, Mistral) é uma classe com dois métodos em `backend/brain/provedores.py`.

```bash
python backend/brain/validar_ao_vivo.py --listar-modelos
```

Mostra os modelos que a sua chave enxerga hoje — nome de modelo do Gemini é aposentado com frequência, então confira antes de fixar `GEMINI_MODELO` no `.env`.

```bash
python backend/brain/validar_ao_vivo.py
```

Roda 8 amostras reais de BTCUSDT contra o modelo e confere: toda resposta válida contra o schema, `confidence` entre 0 e 1, e se `NO_TRADE` aparece. Gasta 8 chamadas da cota.

Pra conferir cadência, prompt, schema e filtro de candle **sem gastar chamada nenhuma**:

```bash
python backend/tests/test_brain.py
```

### 6. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
# preencha com a URL do Supabase e a chave anon (NÃO a service_role)
npm run dev
```

Abra http://localhost:3000 — deve mostrar os registros que o backend gravou. Em **/backtests** ficam as rodadas gravadas em `backtest_runs`, agrupadas por período, junto de um painel do que está conectado (modelo em uso, dados de mercado, execução de ordens).

No topo fica o **painel de cota diária do LLM**: quanto das 500 chamadas/dia já foi gasto, em % (100% = no limite), quanto resta, e se ainda cabe outra rodada de 91 dias hoje. É uma **estimativa somada das rodadas gravadas**, não o contador do Google — chamadas feitas fora dos scripts, ou por rodadas que morreram antes de gravar, não aparecem. Trate como piso. A janela reseta à meia-noite do Pacífico, não do horário local.

A página é **só leitura** de propósito: ela usa a chave `anon`, que é pública no navegador. Um formulário de chave de API ali deixaria o segredo visível pra qualquer visitante — trocar modelo ou conectar corretora continua sendo variável de ambiente no backend. Painel de configuração de verdade é o passo 9. (Já testamos que `npm run build` builda limpo com Next.js 16 + Turbopack.)

### 7. Deploy

- **Frontend (Vercel):**
  1. Importe o repo no Vercel e aponte **Root Directory** para `frontend/`.
  2. Framework: Next.js (detectado automaticamente). Build: `npm run build`.
  3. Em *Settings → Environment Variables*, adicione as duas do `frontend/.env.example`:
     - `NEXT_PUBLIC_SUPABASE_URL` — `https://<seu-projeto>.supabase.co`
     - `NEXT_PUBLIC_SUPABASE_ANON_KEY` — a chave **pública** (`sb_publishable_...` ou a `anon` antiga)

  ⚠️ **Nunca** coloque aqui a chave secreta (`sb_secret_...` / `service_role`). Tudo com prefixo `NEXT_PUBLIC_` vai para o navegador, e a chave secreta ignora RLS — daria escrita a qualquer visitante.

  As tabelas precisam de `grant select` para `anon`, o que o `supabase/schema.sql` já faz. Se as páginas subirem vazias, é isso que checar primeiro.

  Páginas: `/` (pipeline e indicadores), `/backtests` (rodadas + cota do LLM), `/regimes` (estudo de 320 backtests, snapshot estático).
- **Backend:** no Render, "New → Blueprint" apontando pro repo (usa o `render.yaml` — ajuste o `schedule` se quiser outra frequência), ou "New → Cron Job" manual com `pip install -r backend/requirements.txt` como build command e `python backend/main.py` como start command. Adicione as variáveis de ambiente do `.env.example`.

## Próximo passo

**Terminar o passo 7 antes do 8.** A estratégia híbrida perdeu para as duas baselines nos 91 dias que foi possível testar (seção 11 do [`ARCHITECTURE.md`](./ARCHITECTURE.md)), e o ano completo esbarrou no limite de 500 requisições/dia do Gemini. Pela metodologia do projeto, paper trading só vem depois de a híbrida bater a baseline no backtest. Detalhe e ordem de ataque na seção 15.
