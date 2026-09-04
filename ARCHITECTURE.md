# Arquitetura e decisões do projeto — V.A.L Finance

*Última atualização: 10/08/2026 — reflete o estado depois do Passo 6 do roteiro (Risk Engine).*

## 0. Como usar este documento

Este é o documento único e completo do projeto: toda decisão de arquitetura, e o porquê de cada uma, está aqui. Se você (humano ou IA) for mexer neste projeto, leia isto primeiro — evita reconstruir contexto do zero e evita desfazer sem querer decisões que já foram debatidas e resolvidas.

Ordem de leitura sugerida: visão geral → seção 4 (princípios de arquitetura, a mais importante) → pipeline técnico → o resto conforme a dúvida específica surgir.

## 1. Visão geral e objetivo

Sistema que acompanha o mercado de cripto (Binance, conta testnet) e decide comprar, vender, manter ou não operar em cada ativo — definindo sozinho se a operação é de curto ou longo prazo, com stop-loss e take-profit calculados (nunca "chutados") antes de qualquer ordem. O painel é um site em Next.js.

**Meta prática:** gerar um retorno extra modesto e consistente. Não é uma fórmula de enriquecimento.

**Meta experimental**, que vem antes da prática e é a que importa nesta fase: descobrir se decisões guiadas por um LLM mais indicadores técnicos batem uma estratégia simples de baseline (buy-and-hold, ou cruzamento de médias), depois de custos de transação, em dados que o sistema nunca viu. Se a resposta for não, o projeto continua sendo um sucesso — só significa que essa versão não agrega vantagem real, e essa é uma descoberta válida, não uma falha.

**Resultado parcial que importa (passo 7):** a estratégia híbrida **perdeu para as duas baselines** no período que foi possível testar — 91 dias. Detalhe e ressalvas na seção 11. Pela metodologia do próprio projeto, isso impede seguir para paper trading antes de completar o backtest do ano (seção 15).

**Fase atual:** protótipo, conta testnet, custo de infraestrutura zero. Passos 1 a 6 do roteiro (seção 10) implementados — pipeline rodando, indicadores calculados a cada ciclo, motor de backtest com baseline medida, cérebro produzindo teses validadas contra o Gemini real, e Risk Engine com autoridade para sobrepor o cérebro quando um nível de risco é rompido. Todas as peças existem e são testadas isoladamente; o que ainda **não** existe é a composição delas numa estratégia única, medida contra a baseline — isso é o passo 7. O cron job segue gravando `status = 'skeleton_check'` e nenhuma ordem foi enviada, nem em testnet.

## 2. Escopo

**Dentro do escopo (V1):**

- Acompanhar preço e indicadores técnicos de um pequeno conjunto de pares na Binance (hoje: BTCUSDT e ETHUSDT — ajustável em `backend/main.py`)
- Um LLM analisando esses indicadores e propondo uma tese de operação (direção, horizonte, confiança, justificativa)
- Uma camada de risco separada e determinística, calculando stop-loss/take-profit reais e aprovando ou bloqueando cada operação
- Operações no mercado spot: compra, venda (fechamento de posição), manutenção, ou decisão explícita de não operar
- Qualquer horizonte de operação — a IA decide, não é fixado como day trade
- Registro completo de cada ciclo de decisão, para auditoria e para medir se o sistema tem alguma vantagem real
- Um painel web mostrando carteira simulada, decisões e o porquê de cada uma

**Fora do escopo por enquanto — e por quê:**

- **Dinheiro real** — só entra depois que backtest e paper trading mostrarem resultado consistente ao longo do tempo, não um mês bom isolado (seção 11).
- **Short e alavancagem** — no spot, "vender" sem ter o ativo é uma operação de outra natureza (margem/futuros), com risco de liquidação. V1 fica só em spot; short é uma decisão de arquitetura pra V2, não um detalhe pra adicionar depois de qualquer jeito.
- **B3 e mercado internacional** — o motivo de não começar por eles não é preferência, é fricção prática: nenhum dos dois tinha, no momento da decisão, uma conta demo com API tão simples de plugar quanto a testnet da Binance (comparação completa na seção 14). A arquitetura já nasce pronta pra adicionar depois — ver princípio do adapter, seção 4.
- **Opções binárias** — descartado de forma definitiva, não é "por enquanto". A oferta desse produto é proibida no Brasil (Deliberação CVM 598/2018), aproximadamente 80% de quem opera esse tipo de produto perde dinheiro, e a estrutura do produto em si (aposta de curtíssimo prazo, sem meio-termo) não é compatível com o resto do escopo (horizonte flexível, stop-loss/take-profit).
- **Infraestrutura paga** — só entra quando um limite de camada gratuita virar um problema real (seção 13), não por antecipação.
- **Modelo de ML supervisionado (XGBoost etc.) rodando ao lado do LLM** — evolução natural (a Feature Engine já produz o que esse modelo precisaria como entrada), mas não bloqueia o MVP. Fase futura, depois do V1 provar que vale a pena.

## 3. Mercado e dados

**Mercado inicial: Binance, conta testnet.**

Por quê: já havia conta criada, então fricção zero pra começar. A API pública de preços não exige chave. Chaves de testnet (gratuitas) simulam ordens com saldo fictício, com API completa e bem documentada — a mais próxima de "grau de produção" entre as opções gratuitas avaliadas.

Particularidade importante: as posições da conta testnet zeram sozinhas, aproximadamente uma vez por mês. Por isso o histórico "de verdade" da carteira e das decisões vive no Supabase (`decisions` e `portfolio`), nunca no saldo da Binance — a testnet é só o ambiente de execução, não a fonte de verdade.

**Expansão futura (B3, mercado internacional):** não é um recurso a construir — é uma restrição de design que já vale desde o V1 (princípio do adapter, seção 4). Quando chegar a hora, o trabalho é escrever um adapter novo (ex.: Alpaca pros EUA, Cedro/Nelogica pra B3), não reescrever cérebro, risco ou frontend.

## 4. Princípios de arquitetura (não-negociáveis)

Esta é a seção mais importante do documento — decisões já debatidas e resolvidas. Não revisitar sem um motivo concreto e documentado.

1. **O mercado é isolado atrás de um adapter.** Toda função específica da Binance (`buscar_preco`, `buscar_candles`, `enviar_ordem`, `consultar_saldo`) mora em `backend/adapters/binance_adapter.py`, atrás de uma interface fixa. Nenhuma outra parte do sistema sabe, ou deveria saber, de onde o dado vem. É isso que torna expandir pra outro mercado um trabalho de "escrever um adapter novo", não "reescrever o sistema".

2. **O LLM propõe, nunca decide números de risco.** O cérebro devolve uma tese — direção, horizonte, confiança declarada, justificativa — nunca um stop-loss ou take-profit numérico. Esses números vêm de uma fórmula determinística no Risk Engine, baseada em ATR (volatilidade real do ativo no momento). Motivo: um LLM pode gerar um número de risco sem relação nenhuma com a volatilidade real do ativo, e isso não é um bug ocasional — é limitação estrutural de pedir a um modelo de linguagem que "invente" um parâmetro quantitativo preciso.

3. **O cérebro nunca vê dado bruto.** Candle de preço cru não vai direto pro LLM. A Feature Engine calcula os indicadores e monta um JSON estruturado — é isso que o LLM recebe. Mais barato em tokens, mais consistente entre chamadas, e tira do LLM um trabalho que ele não faz bem.

4. **Toda decisão é logada com um `decision_id`.** Cada ciclo grava um registro único (tabela `decisions`) com o estado completo daquele momento: dados de mercado, features calculadas, resposta do LLM, decisão do Risk Engine, ordem enviada (se houve) e resultado. Sem isso não dá pra responder "por que essa operação aconteceu" nem "esse sistema tem vantagem real" — só dá pra torcer.

5. **V1 é spot only.** `SELL` fecha ou reduz uma posição existente — nunca abre uma posição vendida. Short/alavancagem é decisão de arquitetura pra uma fase futura (V2), não algo pra "só adicionar" sem repensar gestão de risco (liquidação é um tipo de perda que stop-loss comum não cobre).

6. **Nada é confiável sem baseline e backtest.** Antes de qualquer decisão do LLM entrar em produção (mesmo testnet), ela precisa ter passado por backtest contra uma baseline simples. A pergunta do projeto não é "a IA ganhou dinheiro" — é "a IA bateu uma estratégia idiota, depois de custo, em dado que nunca viu".

7. **Confiança declarada pelo LLM não é probabilidade.** Um `confidence: 0.87` na saída do modelo é só o que ele disse sobre si mesmo, não uma estatística. O sistema guarda esse valor separado do resultado real de cada operação; só depois de acumular histórico dá pra calcular a taxa de acerto real por faixa de confiança declarada, e só aí saber se a "confiança" do modelo significa alguma coisa.

## 5. Arquitetura técnica — pipeline completo

```
Binance (dados públicos + ordens via testnet)
        │
        ▼
Cron job em Python no Render (roda a cada N minutos)

  1. Market Data — busca candles novos
  2. Feature Engine — calcula RSI, MACD, EMA, ATR, volume, retornos
  3. Cérebro (LLM) — recebe as features, devolve a tese
  4. Decision Engine — traduz a tese em BUY / SELL / HOLD / NO_TRADE
  5. Risk Engine — calcula stop-loss/take-profit via ATR, aprova ou bloqueia
  6. Se aprovado: envia a ordem (testnet)
  7. Grava o decision_id completo no Supabase
        │
        ▼
Supabase (Postgres) — decisions + portfolio
        │
        ▼
Frontend Next.js no Vercel — lê do Supabase e mostra
```

**Status de cada etapa:**

| Etapa | Status | Código |
|---|---|---|
| Market Data (adapter Binance) | ✅ Implementado | `backend/adapters/binance_adapter.py` |
| Persistência (Supabase) | ✅ Implementado | `backend/db/supabase_client.py`, `supabase/schema.sql` |
| Cron job (orquestração) | ✅ Esqueleto — busca, calcula features e grava, sem decisão ainda | `backend/main.py` |
| Frontend (leitura e exibição) | ✅ Implementado | `frontend/app/page.tsx` |
| Feature Engine | ✅ Implementado | `backend/features/feature_engine.py` |
| Cérebro (LLM) | ✅ Implementado | `backend/brain/llm_analyst.py`, `backend/brain/cadencia.py` |
| Decision Engine | 🔲 Não iniciado | não existe ainda |
| Risk Engine | ✅ Implementado | `backend/risk/risk_engine.py`, `backend/risk/portfolio_repo.py` |
| Backtest engine + baseline | ✅ Implementado | `backend/backtest/engine.py`, `backend/backtest/strategies.py` |
| Estratégia híbrida | ⚠️ Construída e testada; backtest só parcial (91 dias) | `backend/brain/hybrid_strategy.py`, `backend/backtest/run_hybrid.py` |

**Responsabilidade de cada componente:**

- **Market Data (adapter)** — `backend/adapters/binance_adapter.py`. Isola toda chamada à Binance atrás de `buscar_preco`, `buscar_candles`, `consultar_saldo`, `enviar_ordem`.
- **Feature Engine** — `backend/features/feature_engine.py`. Entrada: candles do adapter. Saída: dicionário com RSI, MACD, EMA (20/50/200), ATR, volume relativo à média, retorno em 1h/24h/7d. Usa `pandas`. Três decisões tomadas na implementação:
  - **Indicadores escritos no projeto, não importados de uma lib de análise técnica.** O `atr_14` é a entrada do Risk Engine — é dele que saem stop-loss e take-profit reais. Depender de uma lib externa para esse número significa aceitar que uma atualização dela mude, em silêncio, o tamanho do risco de cada operação. Escrito aqui, a fórmula (média de Wilder, com seed na média simples do primeiro período — a mesma convenção do TradingView) fica auditável, e a única dependência nova do passo 2 é o próprio `pandas`, que o motor de backtest ia exigir de qualquer forma.
  - **`calcular_features()` é uma função pura** — não consulta relógio nem rede. O motor de backtest (passo 3) vai chamar exatamente esta função sobre janelas de candles históricos; qualquer olhada no "agora" viraria vazamento de informação futura e inflaria o resultado do backtest.
  - **Nunca devolve NaN, só `None`.** NaN não é JSON válido e quebraria o insert no Supabase. `None` também comunica melhor o único caso em que aparece: histórico curto demais para o indicador (uma EMA de 200 com 50 candles não é um número ruim, é a ausência de número).

  Ressalva **resolvida no passo 5**: a Binance devolve também o candle em andamento, cujo volume parcial puxa o `volume_relativo` para baixo de forma sistemática. Filtrar exigiria olhar o relógio e quebraria a pureza da função, então quem filtra é quem chama — `features/candles.py::somente_fechados()`, aplicado no caminho ao vivo.
- **Motor de backtest** — `backend/backtest/engine.py`. Entrada: uma lista de candles históricos e uma **função de estratégia**. Saída: métricas (retorno total, CAGR, Sharpe, max drawdown, taxa de acerto, número de operações, saldo inicial e final), lista de operações e curva de capital. Quatro decisões de projeto:
  - **É agnóstico à estratégia, e isso é o ponto.** O motor não sabe o que é uma EMA nem o que é um LLM: recebe um callable e chama. É o que permite que a estratégia híbrida do passo 7 rode neste mesmo motor sem alterá-lo. Se o motor precisasse mudar para acomodar a híbrida, a comparação contra a baseline perderia o sentido — não seriam mais duas estratégias medidas pela mesma régua.
  - **A estratégia recebe `ContextoDeDecisao` e devolve `BUY`/`SELL`/`HOLD`/`NO_TRADE`** — o mesmo vocabulário da seção 6 que o cérebro vai devolver e que a tabela `decisions` já registra. O contexto carrega o histórico até o candle avaliado, o estado da posição, e uma property `features` preguiçosa que chama a Feature Engine sobre a janela visível (quem não usa indicador, como `buy_and_hold`, não paga o custo).
  - **A ordem executa na abertura do candle seguinte, nunca no fechamento que gerou o sinal.** Preencher no próprio fechamento observado é a forma mais comum de otimismo silencioso em backtest — supõe latência zero entre decidir e ser preenchido. A abertura seguinte é o primeiro preço de fato negociável depois da decisão.
  - **A janela mostrada é limitada a `CANDLES_NECESSARIOS`**, o mesmo número que o cron job pede por ciclo. Não é só economia de tempo: é paridade. Dar à estratégia o histórico inteiro no backtest a colocaria num mundo que ela não vai encontrar em produção.

  Decisão sobre origem do dado: histórico vem da **API pública de produção** da Binance (`testnet=False`, sem chave — `buscar_historico` no adapter). A testnet é ambiente de execução de ordens, não fonte de histórico; o livro dela é raso e sintético, e backtest rodado em cima disso mede ruído. Por isso o adapter ganhou o modo `somente_dados_publicos=True`, que dispensa credencial e faz `enviar_ordem`/`consultar_saldo` falharem cedo e com mensagem própria.
- **Baseline** — `backend/backtest/strategies.py`. `buy_and_hold` e `ema_crossover` (EMA 20 vs EMA 50, usando o que a Feature Engine já calcula). São burras de propósito e fazem dois trabalhos: validam o motor (`buy_and_hold` tem resultado fechado, calculável na mão) e dão o piso de comparação do passo 7. Resultados medidos na seção 11.
- **Cérebro (LLM)** — `backend/brain/llm_analyst.py`. Entrada: o JSON de features, nunca candle cru. Saída:
  ```json
  {
    "symbol": "BTCUSDT",
    "modelo": "gemini-3.1-flash-lite",
    "direction": "BUY | SELL | HOLD | NO_TRADE",
    "horizon": "curto | medio | longo",
    "confidence": 0.0,
    "reasoning": "texto curto"
  }
  ```
  Usa a API do Gemini (free tier — seção 8), via SDK `google-genai` (o `google-generativeai` é legado). Decisões da implementação:
  - **O contrato é um modelo Pydantic (`TeseDeOperacao`) e faz dois trabalhos.** Vai como `response_schema` na chamada, então o próprio Gemini só consegue emitir JSON naquele formato; e valida a resposta do lado de cá, então um `confidence: 1.4` ou um `direction: "COMPRAR"` viram erro em vez de virarem ordem. Não é redundância — schema restringe a geração, validação garante a invariante, e é na segunda que o resto do sistema confia.
  - **O provedor é trocável por variável de ambiente** — `backend/brain/provedores.py`. O `llm_analyst.py` não fala com nenhum SDK: monta o prompt, define o contrato e valida a resposta. Quem conversa com o modelo é um `ProvedorLLM`. Hoje há dois (`gemini`, `claude`); `LLM_PROVEDOR=claude` basta para trocar, e adicionar um terceiro é uma classe com dois métodos.

    **Por que isso importa mais do que parece:** prompt, contrato, cadência e cache continuam idênticos quando o modelo muda — é o que permite responder "o resultado ruim é do modelo ou da ideia?" trocando *uma* variável do experimento. Se trocar de LLM exigisse mexer em qualquer outro arquivo, a abstração vazou, e o vazamento é bug.
  - **Cada provedor faz structured output do seu jeito nativo.** Gemini: `models.generate_content` com `response_schema` → `response.parsed`. Claude: `messages.parse` com `output_format` → `response.parsed_output`, mais a checagem de `stop_reason == "refusal"` (uma recusa por política volta com HTTP 200, e confundi-la com "respondeu errado" faria o backtest reenviar algo que nunca vai passar). Nos dois casos a saída é a mesma instância validada de `TeseDeOperacao`.
  - **O nome do modelo não fica fixo no código** — `LLM_MODELO` vale para qualquer provedor, `GEMINI_MODELO`/`CLAUDE_MODELO` são específicos. Padrões: `gemini-3.1-flash-lite` e `claude-opus-5`. Nome de modelo é aposentado com frequência; `validar_ao_vivo.py --listar-modelos` mostra o que a chave do provedor ativo enxerga hoje.
  - **O `llm_output` grava o par (provedor, modelo).** Sem isso, duas rodadas com modelos diferentes ficariam indistinguíveis no banco assim que alguém trocasse o padrão.
  - **`symbol` não é pedido ao modelo**, embora esteja no JSON final. Quem chama já sabe qual par mandou analisar; pedir que o modelo repita gasta token e abre a porta para ele devolver um par diferente do perguntado. O campo é anexado por `analisar_para_registro()`.
  - **Falha não vira `HOLD` silencioso.** Resposta vazia ou fora do contrato levanta `ErroDoCerebro`. Um cérebro que devolve HOLD quando falhou seria indistinguível de um cérebro que decidiu manter a posição.
  - **O estado da carteira vai no prompt.** Sem saber se há posição, metade do vocabulário é indecidível: `HOLD` é "manter a posição atual" e `SELL` é "fechar a existente". Não viola o princípio 3 — é estado da carteira, não candle cru.

  Empacotado como função de estratégia em `backend/brain/strategy.py` (`ContextoDeDecisao → BUY/SELL/HOLD/NO_TRADE`) — o cérebro sozinho, sem camada de risco, mantido como peça isolável. A composição de verdade é a híbrida abaixo.
- **Estratégia híbrida** — `backend/brain/hybrid_strategy.py`. "O cérebro decide, o Risk Engine valida e pode sobrepor", numa função de estratégia só — a mesma assinatura de `buy_and_hold` e `ema_crossover`, medida pelo mesmo motor sem alterá-lo (princípio 6). Não há decisão nova aqui: é a composição de duas peças já testadas isoladamente. O que ela acrescenta são a **ordem** e as **duas cadências**:

  1. **Stop/take, em todo candle.** Antes da cadência, antes de qualquer chamada de API, sem nem tocar em `contexto.features`. Só compara preço contra número já gravado.
  2. **Cérebro, a cada 6h.** Se nada rompeu e é hora, consulta; escolhe os multiplicadores pelo `horizon` devolvido; chama `avaliar_risco()`.
  3. **Entre consultas**, mantém o estado (`HOLD`/`NO_TRADE`) sem gastar chamada.

  **Por que as duas cadências não podem ser a mesma:** consultar o cérebro é caro (API, cota diária); checar stop/take é comparar dois números. Amarrar as duas ao mesmo relógio faria um stop rompido às 10h só ser executado às 12h — até 6 horas de posição andando contra, protegida por um stop que existe, está correto e simplesmente não foi olhado. A proteção viraria enfeite. A ordem das etapas não é estilo, é a proteção.

  Os níveis de stop/take da posição vivem na estratégia, não no motor — o motor é agnóstico de propósito e sabe de caixa e quantidade, não de stop-loss. Há uma defasagem de um candle tratada explicitamente: a decisão de comprar nasce no fechamento de `i` e só vira posição na abertura de `i+1`, então os níveis ficam "pendentes" nesse intervalo.

  **Modelagem da ruptura:** a checagem usa o **fechamento** do candle, não a mínima/máxima. É fiel ao sistema real, que não deixa ordem de stop descansando no livro da corretora — o cron job consulta o preço a cada ciclo e manda uma ordem a mercado. Checar contra a mínima modelaria uma ordem que não existe.
- **Filtro de candle fechado** — `backend/features/candles.py`. Resolve a ressalva registrada na Feature Engine: a Binance devolve também o candle em andamento, cujo volume é parcial, o que puxa o `volume_relativo` para baixo em **todo** ciclo ao vivo. Viés que sempre aponta para o mesmo lado é pior que ruído. O adapter voltou a expor `fechamento_em` (índice 6 do kline, que ele descartava) para que saber se o candle fechou seja leitura de dado e não conta. O filtro mora fora da Feature Engine de propósito: ela é pura e o backtest depende disso, e uma função que pergunta as horas não pode viver lá dentro. Usado só no caminho ao vivo (`main.py`); o backtest não usa e não deve usar.
- **Risk Engine** — `backend/risk/risk_engine.py`. Entrada: tese do LLM, `atr_14`, preço atual, estado da posição e capital total. Saída: aprovação/bloqueio, ação final, e os números reais de stop-loss, take-profit e tamanho de posição. Absorve também o papel do Decision Engine: é aqui que a tese vira um dos quatro estados oficiais, reconciliada com o que a carteira permite.

  **Não é um validador passivo — ele age contra o cérebro.** A regra 1 roda primeiro, todo ciclo, antes de qualquer outra lógica e sem consultar a tese: se um stop-loss ou take-profit já registrado foi rompido, força `SELL`. Detalhe do porquê na seção 6.

  Ordem de avaliação:
  1. Posição aberta e nível registrado rompido → `SELL` forçado, `override_do_llm = true`.
  2. Sem posição e LLM diz `BUY` → calcula stop (2× ATR abaixo), alvo (3× ATR acima) e tamanho por risco (`capital × risco_pct ÷ distância_do_stop`). Aprova se couber no teto de exposição por ativo; bloqueia com motivo se estourar.
  3. Posição aberta e LLM diz `SELL` → aprova (reduzir exposição não exige checagem).
  4. Posição aberta e `HOLD` sem nível rompido → mantém, sem ordem.
  5. Sem posição e `NO_TRADE` → sem ordem.
  6. As demais combinações são reconciliadas com a carteira (`SELL` sem posição não vira venda a descoberto — princípio 5; `BUY` com posição aberta não aumenta, porque o V1 é all-in/all-out).

  Duas decisões que valem registro:
  - **`override_do_llm` é `acao_final != direction`**, e não só o caso do stop. Qualquer divergência entre o que o cérebro pediu e o que o sistema fez fica marcada — é o que torna o desacordo mensurável depois (princípio 7).
  - **`direcao_do_llm` viaja dentro de `risk_result`**, mesmo a tese completa já estando em `llm_output` na mesma linha. Sem isso, ler `risk_result` isolado — numa query, num gráfico, num export — mostraria só a ação final, e o override ficaria invisível justamente onde precisa ser visto.

  Todos os parâmetros são configuráveis via `ParametrosDeRisco` (e `RISCO_*` no ambiente): multiplicadores de stop/alvo, risco por operação e teto de exposição. **São hipóteses a calibrar no passo 7, não verdades** — e a seção 11 registra por que os padrões, medidos, quase nunca aprovam uma entrada em candle de 1h.
- **Casca do portfolio** — `backend/risk/portfolio_repo.py`. Traduz linha da tabela `portfolio` em `EstadoDaPosicao` e de volta, para que o Risk Engine continue puro. Regra que o módulo existe para proteger: **falha de leitura não é o mesmo que estar sem posição.** Degradar para "carteira vazia" quando o banco não responde faria o sistema comprar de novo por cima de uma posição existente e — pior — parar de checar o stop-loss dela, já que a regra 1 só roda quando há posição conhecida. Por isso a falha levanta `ErroDePortfolio`, e quem chama trata como "não sei o estado, logo não opero neste ciclo".
- **Persistência** — `backend/db/supabase_client.py` + `supabase/schema.sql` (schema completo na seção 7).
- **Frontend** — `frontend/app/page.tsx`, `frontend/app/backtests/page.tsx` + `frontend/lib/supabase.ts`. A rota `/backtests` lê `backtest_runs` e mostra as rodadas agrupadas por símbolo e período, um painel do que está conectado, e o consumo da cota diária do LLM (`lib/cota.ts`).

  **É só leitura, e isso é decisão de segurança, não preguiça.** A página usa a chave `anon`, que é pública no navegador: um formulário de chave de API ali gravaria o segredo num lugar legível por qualquer visitante. Trocar de modelo ou conectar corretora continua sendo variável de ambiente no backend; painel de configuração com escrita server-side é o passo 9.

  O painel de cota soma as `chamadas_reais` das rodadas gravadas dentro da janela diária — que reseta à **meia-noite do Pacífico**, não do fuso local (somar pelo relógio de Brasília erraria a janela por 4–5 horas). É estimativa conservadora, não o contador do Google: rodadas antigas sem o campo entram pelo total de consultas, que é um teto, e chamadas feitas fora dos scripts não aparecem. Errar para cima num indicador de "estou acabando?" é o erro barato.
- Server Component que lê a tabela `decisions` com a chave anon (só leitura — RLS garante isso). Hoje mostra os registros brutos do "skeleton check"; evolui pra carteira + decisões com raciocínio + performance no passo 9 do roteiro.

## 6. Modelo de decisão

Estados possíveis em cada ciclo:

- `BUY` — abrir ou aumentar posição
- `SELL` — fechar ou reduzir posição existente (nunca abrir posição vendida — princípio 5, seção 4)
- `HOLD` — manter a posição atual como está
- `NO_TRADE` — sem posição, e a decisão é não abrir uma agora. Existe como opção de primeira classe: quando o sinal é fraco ou contraditório, o cérebro tem permissão explícita pra dizer "não vou apostar nisso" em vez de ser empurrado pra uma direção

O que o LLM devolve: direção, horizonte sugerido, confiança declarada (0 a 1), justificativa curta. Nunca um número de risco (princípio 2, seção 4).

### Cadência de consulta — a cada 6h, não a cada candle

**Regra do sistema, não detalhe de implementação.** O cérebro é consultado a cada 6 horas. Entre uma consulta e outra a estratégia mantém o que já estava valendo: `HOLD` se há posição, `NO_TRADE` se não há. Não é "não fazer nada" — é a decisão explícita de manter, e ambas são estados oficiais da lista acima.

Três motivos, e nenhum é economia por avareza:

- **Não cabe no free tier.** Um ano de candles de 1h são 8.760 pontos. Consultar em cada um seria 8.760 chamadas para um único backtest, contra um limite diário da ordem de 1.000 (seção 8) — o backtest do passo 7 não rodaria nem uma vez. A 6h, o mesmo ano dá ~1.460 consultas: ainda exige planejar período e cadência, mas entra no campo do possível.
- **A tese não muda de hora em hora.** O cérebro devolve direção *e horizonte* — inclusive "longo". Reperguntar de hora em hora a um modelo que acabou de dizer "alta, horizonte médio" não traz informação nova; traz variação de amostragem, porque o mesmo cenário pode receber respostas diferentes só por o modelo ser estocástico.
- **Operar demais custa caro.** A baseline do passo 4 mediu isso: o `ema_crossover` queimou 12,8% do capital inicial só em taxa fazendo 78 idas e voltas (seção 11).

As 6 horas são **configuráveis** (`intervalo_ms` em toda API que usa; `GEMINI_INTERVALO_HORAS` no ambiente para o caminho ao vivo) e não uma constante no código: é um número a calibrar no passo 7, comparando o backtest híbrido em cadências diferentes, e não uma verdade descoberta.

A regra mora num módulo só — `backend/brain/cadencia.py` — porque a mesma pergunta será feita em dois contextos muito diferentes: a estratégia dentro do motor de backtest (onde "agora" é o timestamp do candle e o processo vive a simulação inteira) e o cron job ao vivo (onde "agora" é o relógio e o processo morre a cada ciclo). Por isso a decisão é uma **função pura** — `deve_consultar(agora, ultima_consulta, intervalo)` — que não guarda estado nem olha relógio: quem tem o estado passa o estado. Duplicar essa regra nos dois lugares é como ela sai de sincronia, e aí a estratégia validada deixa de ser a estratégia executada.

O que o Risk Engine calcula: stop-loss e take-profit com base no ATR do ativo naquele momento; tamanho da posição dentro de um limite máximo de exposição por ativo; aprovação ou bloqueio final da ordem.

### O Risk Engine pode sobrepor o cérebro — e essa é a regra mais importante do sistema

**Regra do sistema, não detalhe de implementação.** Se um stop-loss ou take-profit **já registrado** foi rompido, o Risk Engine força `SELL`, mesmo que a tese daquele ciclo diga `HOLD`, mesmo que diga `BUY`. Essa checagem roda **antes** de qualquer outra lógica, todo ciclo, e não consulta a opinião do modelo para decidir se vale a pena.

Não é zelo abstrato — é correção de um comportamento medido. Na validação do passo 5 (seção 11), num cenário de queda de 19,95% com posição aberta, o modelo escolheu `HOLD` justificando *"para evitar realizar prejuízo em um momento de possível repique técnico"*. Em 12 amostras, incluindo duas quedas fortes, `SELL` não apareceu nenhuma vez. É aversão à perda — um viés humano bem documentado, reproduzido pelo modelo.

Uma camada de risco que só pudesse bloquear ordens novas, sem poder fechar posição existente, deixaria esse viés passar inteiro para a carteira: a posição ficaria aberta caindo enquanto o cérebro repetisse que era prudente manter. É a diferença entre uma trava e um conselho.

Dois detalhes que fazem a regra funcionar na prática:

- **Os níveis são fixados quando a posição abre e não são recalculados a cada ciclo.** Um stop recalculado acompanharia o preço caindo e nunca seria rompido — seria um stop que se afasta sozinho. É por isso que `portfolio` precisou ganhar as colunas `preco_entrada`, `stop_loss` e `take_profit` (seção 7).
- **A comparação é `<=` e `>=`.** Preço exatamente no nível é o nível atingido; tratar como "ainda não" seria perder o gatilho por um centavo.

O desacordo fica registrado: `risk_result` carrega `override_do_llm` e `direcao_do_llm` junto da ação final, e a tese original continua em `llm_output`. Nunca se grava só a decisão final — senão o override some do `decision_id` e não há como medir, depois, quantas vezes a máquina teve que discordar do modelo.

### Horizonte define a largura do stop

**Regra do sistema**, mesmo estatuto da cadência de 6h. O `horizon` que o cérebro devolve escolhe os multiplicadores de ATR:

| Horizonte | Stop | Take |
|---|---|---|
| `curto` | 2× ATR | 3× ATR |
| `medio` | 4× ATR | 6× ATR |
| `longo` | 8× ATR | 12× ATR |

Horizonte desconhecido cai em `curto` — na dúvida sobre quanto espaço dar, dar menos é o erro barato.

**Por que existe.** Em spot sem alavancagem, `tamanho = risco ÷ distância_do_stop`. Stop apertado exige posição grande para arriscar 1% do capital, e posição grande estoura o teto de exposição. Com stop fixo em 2× ATR, o Risk Engine aprovava 2 de 50 entradas em candle de 1h (seção 11).

**Isso não era um defeito a corrigir — era uma consequência coerente do desenho, que faltava tornar explícita.** Um sistema spot, sem alavancagem, naturalmente penaliza operação de horizonte curto: ela pede stop apertado, que pede posição grande, que concentra a carteira. A tabela não contorna essa verdade, ela a codifica. Quem quer horizonte longo ganha espaço para o preço respirar; quem quer horizonte curto continua batendo no teto, **como deve**. É o escopo do projeto (seção 2: "qualquer horizonte de operação — a IA decide, não é fixado como day trade") aparecendo na camada de risco.

Os valores do passo 6 (2×/3×) viraram o caso `curto` em vez de serem descartados. Quem varia é a estratégia híbrida, escolhendo o par antes de chamar `avaliar_risco()` — o Risk Engine não precisou mudar, porque os multiplicadores já eram parâmetro e não constante.

Confiança declarada vs. calibrada: os dois números ficam separados desde o primeiro dia — ver princípio 7, seção 4.

## 7. Modelo de dados

Tabela `decisions` — o registro central do sistema. Cada linha é um `decision_id`.

| Campo | Tipo | O que guarda | Status hoje |
|---|---|---|---|
| `id` | uuid | identificador único da decisão | preenchido |
| `created_at` | timestamptz | quando o ciclo rodou | preenchido |
| `symbol` | text | o par (ex: BTCUSDT) | preenchido |
| `market_snapshot` | jsonb | preço e último candle no momento | preenchido |
| `features` | jsonb | indicadores calculados pela Feature Engine | preenchido |
| `llm_output` | jsonb | a tese devolvida pelo cérebro | vazio — o cérebro já produz o dicionário (`analisar_para_registro`), mas o cron job só passa a chamá-lo junto com o Risk Engine, no passo 6 |
| `risk_result` | jsonb | ação final, aprovação, stop/alvo/tamanho, `override_do_llm` e `direcao_do_llm` | vazio — o Risk Engine já produz o dicionário; a gravação entra quando o cron job compuser cérebro + risco (passo 7/8) |
| `order_result` | jsonb | resposta da Binance à ordem enviada | vazio — passo 8 |
| `status` | text | `skeleton_check` hoje; depois `no_trade` / `approved` / `blocked` / `executed` | `skeleton_check` |
| `outcome` | jsonb | resultado quando a posição fecha (lucro/prejuízo) | vazio — passo 8 |

Tabela `portfolio` — estado da carteira simulada.

| Campo | Tipo | O que guarda |
|---|---|---|
| `asset` | text (PK) | o **par** (`BTCUSDT`), não a moeda — preço de entrada e níveis são propriedades da operação naquele par, e usar o par alinha a chave com `decisions.symbol` |
| `quantity` | numeric | quantidade em posição |
| `updated_at` | timestamptz | última escrita |
| `preco_entrada` | numeric | a que preço a posição foi aberta — passo 6 |
| `stop_loss` | numeric | nível de saída por perda, fixado na abertura — passo 6 |
| `take_profit` | numeric | nível de saída por ganho, fixado na abertura — passo 6 |

**Por que as três colunas novas existem:** sem elas a regra mais importante do Risk Engine não tem como funcionar. Ela compara o preço atual contra um stop **registrado quando a posição abriu** e força a saída se foi rompido — inclusive contra um `HOLD` do cérebro (seção 6). Um nível recalculado a cada ciclo acompanharia o preço caindo e nunca seria rompido.

Os três `alter table ... add column if not exists` estão no `schema.sql`, que continua idempotente.

Tabela `backtest_runs` — uma linha por rodada de backtest (passos 3, 4 e depois 7).

| Campo | Tipo | O que guarda |
|---|---|---|
| `id` | uuid | identificador da rodada |
| `created_at` | timestamptz | quando a rodada foi executada |
| `strategy_name` | text | `buy_and_hold`, `ema_crossover`, e depois a híbrida |
| `symbol` | text | o par testado |
| `period_start` / `period_end` | timestamptz | janela histórica coberta |
| `params` | jsonb | capital inicial, taxa, janela máxima, modelo de execução, nº de candles |
| `metrics` | jsonb | retorno total, CAGR, Sharpe, max drawdown, taxa de acerto, nº de operações e de trades, taxas pagas, saldo inicial e final |
| `notes` | text | contexto livre da rodada |

**Por que os parâmetros são gravados junto das métricas:** um retorno sem a taxa e o período que o produziram não é comparável com nada. A tabela existe justamente para que, no passo 7, a comparação contra a baseline seja contra um número registrado com suas condições — e não contra memória (princípio 6).

**O que deliberadamente não vai para esta tabela:** curva de capital e lista de operações. São milhares de pontos por rodada e o free tier tem 500MB; o que responde "a estratégia X bateu a Y?" são as métricas. O detalhe fica em JSON local (`backend/backtest/resultados/`, fora do git) para quando a dúvida for sobre uma operação específica.

**RLS:** as três tabelas têm leitura pública (frontend usa a chave `anon`) e escrita restrita à service role (só o backend, que ignora RLS por padrão). Os `grant select` explícitos no `schema.sql` existem porque projetos Supabase criados a partir de 30/05/2026 exigem esse passo separado da policy de RLS pra API expor a tabela.

O `schema.sql` é idempotente: dá pra colar o arquivo inteiro no SQL Editor quantas vezes for preciso. Cada `create policy` é precedido de um `drop policy if exists` — sem isso a segunda execução falha em "policy already exists" e quem rodou fica sem saber se o resto passou.

**Decisão deliberada:** não guardamos histórico de candle bruto no Supabase — pesaria no limite de 500MB do free tier sem necessidade, já que preço histórico dá pra buscar direto da Binance sob demanda (ex.: pra rodar um backtest).

## 8. Stack tecnológico

| Camada | Ferramenta | Detalhe confirmado | Por quê |
|---|---|---|---|
| Frontend | Next.js | 16.x — testado com 16.3, Turbopack | Padrão atual; Vercel é autor dos dois |
| Estilo | Tailwind CSS | v4 — config via CSS (`@import "tailwindcss"`), sem `tailwind.config.js` | Setup mais simples que v3, CSS final bem menor |
| Hospedagem frontend | Vercel (Hobby) | ~100GB de banda/mês | Gratuito, deploy automático via Git, uso não-comercial |
| Execução periódica | Render (Free) | cron job nativo, 750h de instância/mês | Não precisa de servidor 24/7 ligado |
| Banco de dados | Supabase (Free) | Postgres + API automática, 500MB | Já usado pelo usuário em outros projetos |
| Biblioteca Binance | `python-binance` | ≥1.0.20, `testnet=True` no construtor do `Client` | Suporte a testnet nativo e documentado |
| Cliente Supabase (backend) | `supabase` (Python) | ≥2.5.0, usa a service role key | Cliente oficial |
| Cliente Supabase (frontend) | `@supabase/supabase-js` | ^2.45.0, usa a chave anon | Cliente oficial JS |
| LLM | Trocável — `gemini` (padrão) ou `claude` | Gemini free tier: **500 req/dia por modelo**, ~15/min (medido). Anthropic: **sem free tier**, pré-pago | Free tier do Gemini para o dia a dia; a troca existe para poder comparar modelos |
| Código-fonte | GitHub | — | Integra direto com Vercel e Render |

**A cota do Gemini é o recurso escasso do projeto, e o número real é menor do que se supunha.** A estimativa anterior ("~1.000–1.500 req/dia") estava errada. O valor medido, vindo da própria mensagem de erro da API durante o passo 7:

```
Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests
limit: 500, model: gemini-3.1-flash-lite
quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier
```

São **500 requisições por dia, por modelo** — e o limite é por modelo, o que significa que trocar de modelo dá outra cota, mas mistura duas amostras diferentes no mesmo experimento e invalida a comparação. Há também um limite por minuto que na prática rendeu ~15 chamadas/min.

Consequência direta, e ela dimensiona o que é possível: um ano de candles de 1h com cadência de 6h são **1.460 consultas = 3 dias de cota**. Qualquer backtest com LLM precisa ser planejado com essa conta na mão (seções 11 e 15).

Duas defesas foram construídas por causa disso, e as duas se provaram necessárias no mesmo dia:
- **Cache em disco das respostas**, indexado pelo hash do prompt (`backend/backtest/run_hybrid.py`). Uma queda no meio de uma rodada longa deixaria de custar a cota inteira sem nada em troca. Custou exatamente isso uma vez antes de existir.
- **Retry que distingue as duas famílias de erro transitório**: limite de requisição (429) e indisponibilidade do servidor (503/500/502/504). São coisas diferentes — a primeira significa "você está indo rápido demais", a segunda "o servidor está congestionado" — e tratar só a primeira fez uma rodada de 423 chamadas morrer num soluço de segundos.

### Quanto custaria trocar de provedor

Medido no prompt real do projeto: **566 tokens de entrada, ~130 de saída** por consulta.

| | Backtest do ano (1.460 consultas) | Ao vivo (8 consultas/dia) |
|---|---|---|
| Gemini Flash-Lite (free tier) | grátis, mas **3 dias** de cota | grátis |
| Claude Haiku 4.5 | US$ 1,78 (US$ 0,89 via Batch API) | ~US$ 0,29/mês |
| Claude Sonnet 5 | US$ 3,55 | ~US$ 0,58/mês |
| Claude Opus 5 | US$ 8,88 | ~US$ 1,47/mês |

Duas leituras:

- **Ao vivo, o custo é irrelevante em qualquer provedor.** O cron roda a cada 15 min com 2 símbolos, mas o cérebro só é consultado a cada 6h por símbolo: **8 chamadas/dia**, 1,6% do free tier do Gemini. Mesmo consultando a cada execução do cron (192/dia) ainda caberia. A cadência de 6h foi escolhida por **custo de backtest**, não por limite ao vivo — e mudá-la ao vivo sem rodar o backtest na cadência nova faria a estratégia executada deixar de ser a validada.
- **No backtest, pagar compra tempo.** As 3 dias de espera pela cota do Gemini custam ~US$ 1 no Haiku. Prompt caching não ajuda aqui: o prefixo mínimo cacheável é maior que o request inteiro.

**Ferramentas do usuário deliberadamente fora deste desenho** (detalhe do porquê na seção 14): Firebase, GitHub Pages.

## 9. Estrutura do repositório

```
ia-trading/
├── README.md              — como rodar e fazer deploy, passo a passo
├── ARCHITECTURE.md         — este documento
├── .gitignore
├── render.yaml             — configuração do cron job pro Render
├── backend/
│   ├── adapters/
│   │   └── binance_adapter.py   — tudo que é específico da Binance
│   ├── db/
│   │   └── supabase_client.py   — conexão com o Supabase (service role)
│   ├── features/
│   │   ├── feature_engine.py    — candles → indicadores (RSI, MACD, EMA, ATR...)
│   │   └── candles.py           — descarta o candle em andamento (só ao vivo)
│   ├── brain/
│   │   ├── llm_analyst.py       — features → tese (Gemini + schema Pydantic)
│   │   ├── cadencia.py          — quando consultar; regra única, backtest e ao vivo
│   │   ├── strategy.py          — o cérebro sozinho, como função de estratégia
│   │   ├── hybrid_strategy.py   — cérebro + Risk Engine (passo 7)
│   │   └── validar_ao_vivo.py   — checagem contra o Gemini real
│   ├── risk/
│   │   ├── risk_engine.py       — stop/alvo/tamanho; pode sobrepor o cérebro
│   │   └── portfolio_repo.py    — casca fina Supabase ↔ EstadoDaPosicao
│   ├── backtest/
│   │   ├── engine.py            — motor agnóstico à estratégia
│   │   ├── strategies.py        — baselines (buy_and_hold, ema_crossover)
│   │   ├── run_baseline.py      — baixa histórico, roda, confere e grava
│   │   └── run_hybrid.py        — backtest da híbrida (cache de respostas do LLM)
│   ├── tests/
│   │   ├── test_feature_engine.py
│   │   └── test_backtest_engine.py
│   ├── main.py                  — ponto de entrada do cron job
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app/
│   │   ├── page.tsx         — painel (Server Component, lê do Supabase)
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── lib/
│   │   └── supabase.ts      — conexão com o Supabase (chave anon)
│   ├── package.json
│   └── .env.example
└── supabase/
    └── schema.sql           — schema completo do banco
```

Convenção pra peça que ainda não existe: a estratégia híbrida do passo 7, que deve morar em `backend/backtest/strategies.py` junto das baselines — ela é uma função de estratégia como as outras, e ficar no mesmo lugar deixa óbvio que são medidas pela mesma régua.

Duas pastas do backtest ficam fora do git (`.gitignore`): `backend/backtest/.cache/` (candles baixados) e `backend/backtest/resultados/` (curva e operações de cada rodada). São descartáveis — o histórico vem da Binance sob demanda e as métricas ficam no Supabase.

`pytest` fica deliberadamente fora do `requirements.txt`: é esse arquivo que o Render instala a cada execução do cron job, e não há motivo pra pagar esse download em produção. Os testes rodam com `python backend/tests/test_feature_engine.py` sem instalar nada além do que já está lá, e com `pytest backend/tests` pra quem tiver o pytest à mão.

## 10. Roteiro — status atual

1. ✅ **Estruturar o repositório** — adapters, Supabase, Render e Vercel conectados; esqueleto rodando ponta a ponta.
2. ✅ **Feature Engine** — calcular indicadores a partir dos candles.
3. ✅ **Motor de backtest** — simular estratégias contra dado histórico, sem IA envolvida ainda.
4. ✅ **Baseline** — rodar buy-and-hold ou SMA+RSI pelo motor de backtest; valida o motor em si e dá ponto de comparação.
5. ✅ **Cérebro (LLM)** — gerar a tese a partir das features.
6. ✅ **Risk Engine** — calcular stop-loss/take-profit via ATR e validar a tese antes de qualquer ordem.
7. ⚠️ **Backtest da estratégia híbrida** — comparar contra a baseline do passo 4. *Construído e testado; rodado sobre 91 dias, não sobre o ano — a cota do Gemini (500/dia) não permitiu. **A híbrida perdeu para as duas baselines** no recorte (seção 11).*
8. 🔲 **Paper trading** — testnet de verdade por semanas, com decision_id completo de cada ciclo.
9. 🔲 **Dashboard completo** — carteira, decisões com raciocínio, performance ao longo do tempo.
10. 🔲 **Avaliar expansão** — outro mercado (B3/internacional), ou considerar dinheiro real.

## 11. Metodologia de validação

A pergunta central do projeto não é "a IA ganhou dinheiro" — até uma estratégia ruim ganha numa alta. É: **a IA bateu a baseline, depois de custo, em dado que nunca viu?**

Ordem de validação, sem pular etapa: baseline no backtest → estratégia híbrida no backtest, comparada à baseline → paper trading por um período longo o bastante pra não ser só "um mês bom" → só então dinheiro real entra na conversa, e começando pequeno.

### Baseline medida (passo 4)

BTCUSDT, candles de 1h, 10/08/2025 a 10/08/2026 (8.760 candles), capital inicial 10.000, taxa de 0,10% por operação:

| Estratégia | Retorno | CAGR | Sharpe | Max drawdown | Taxa de acerto | Trades | Taxas pagas | Saldo final |
|---|---|---|---|---|---|---|---|---|
| `buy_and_hold` | −46,02% | −46,05% | −1,22 | −53,74% | 0% | 1 | 15,40 | 5.398,11 |
| `ema_crossover` | −30,27% | −30,29% | −1,24 | −35,29% | 25,64% | 78 | 1.282,87 | 6.973,46 |

Três leituras que importam mais que os números em si:

- **O período é um ano de baixa** — o BTC caiu 45,91% nele. Isso não invalida a baseline, mas define o que "bater a baseline" significa no passo 7: **perder menos que −30,27%**, e não ganhar dinheiro. Uma estratégia híbrida que termine em −20% terá batido a baseline; uma que termine em +5% num período de alta futuro não terá provado nada sozinha. Conclusão tirada de um único ano de baixa é frágil nas duas direções, e antes de o passo 7 valer como evidência a comparação precisa cobrir também um período de alta.
- **O custo de transação não é detalhe de arredondamento.** O `ema_crossover` pagou 1.282,87 em taxas — 12,8% do capital inicial — para fazer 78 idas e voltas. Uma estratégia que opera muito precisa ser bem melhor que uma que opera pouco só para empatar. É a razão de a taxa ser parâmetro do motor e não uma constante: baixá-la sem justificativa é a maneira mais fácil de fabricar um resultado bonito.
- **Taxa de acerto e resultado são coisas diferentes.** O `ema_crossover` acertou 25,64% dos trades e ainda assim perdeu bem menos que o `buy_and_hold`. Poucos acertos grandes e muitos erros pequenos é a assinatura de seguidor de tendência — e é o motivo de a taxa de acerto nunca ser lida sozinha.

### Validação do cérebro (passo 5)

12 chamadas reais ao `gemini-3.1-flash-lite`: 8 amostras de BTCUSDT espaçadas de 24h (metade apresentadas com posição aberta, metade sem) e 4 amostras de diagnóstico nos extremos de tendência do ano cacheado.

Resultado formal: 8/8 respostas válidas contra o schema, `confidence` entre 0,30 e 0,75 (média 0,49), `NO_TRADE` em 4 das 8. Nada fora do contrato.

Duas observações de comportamento, que valem mais que o resultado formal:

- **Nas 8 amostras recentes o modelo nunca escolheu um lado** — todas as "com posição" viraram `HOLD` e todas as "sem posição" viraram `NO_TRADE`. O diagnóstico nos extremos mostrou que isso *não* é o prompt travado em inércia: com RSI em 20,47 (sobrevenda forte) o modelo devolveu `BUY` com confiança 0,65. Ou seja, o período recente era de fato lateral. Mas o registro fica: se o passo 7 rodar num período assim, a híbrida vai operar pouco, e "não operou" precisa ser lido como um resultado, não como um bug.
- **O modelo relutou em vender no prejuízo.** Em queda de 19,95% com posição aberta, escolheu `HOLD` justificando *"para evitar realizar prejuízo em um momento de possível repique técnico"*. Isso é aversão à perda — um viés humano bem documentado, reproduzido pelo modelo. Em 12 amostras, incluindo duas quedas fortes, `SELL` não apareceu nenhuma vez. É evidência direta a favor do princípio 2, e uma exigência concreta para o passo 6: **o stop-loss precisa poder fechar posição contra a vontade declarada do cérebro**, senão esse viés passa inteiro para a carteira. *(Implementado no passo 6 como a regra 1 do Risk Engine — seção 6.)*

### Backtest da híbrida (passo 7) — resultado parcial, e negativo

**A híbrida perdeu para as duas baselines no período testado.**

BTCUSDT, candles de 1h, **10/08/2025 a 09/11/2025 (91 dias, 2.184 candles)**, capital 10.000, taxa 0,10%, cadência de 6h, stop/alvo por horizonte:

| Estratégia | Retorno | CAGR | Sharpe | Max drawdown | Taxa de acerto | Trades | Saldo final |
|---|---|---|---|---|---|---|---|
| `buy_and_hold` | −11,60% | −39,05% | −1,17 | −20,93% | 0% | 1 | 8.839,88 |
| `ema_crossover` | **−3,53%** | −13,43% | −0,58 | −10,53% | 26,32% | 19 | 9.647,27 |
| `hibrida_llm_risk` | **−14,90%** | −47,69% | **−2,66** | −19,21% | 28,57% | 14 | 8.509,59 |

- vs `buy_and_hold`: **perdeu por 3,30 pontos**
- vs `ema_crossover`: **perdeu por 11,37 pontos**

As três linhas estão em `backtest_runs`, incluindo as baselines recalculadas **no mesmo recorte** — comparar 91 dias contra o ano inteiro já gravado seria comparar duas perguntas diferentes. Métricas auditadas de forma independente, reconstruídas a partir da lista de operações crua sem usar nenhuma função do motor: batem todas.

**Isto é uma resposta válida, não uma falha do projeto** (seção 1). A pergunta era "decisões guiadas por um LLM mais indicadores batem uma estratégia simples, depois de custos?" — e no período medido a resposta é não, com folga. O Sharpe de −2,66 é notavelmente pior que o das duas baselines: a híbrida não só perdeu mais, perdeu com mais volatilidade por unidade de retorno.

O que os contadores mostram sobre *por que*:

- **O cérebro escolheu ficar de fora na maior parte do tempo**: das 364 consultas, 236 `NO_TRADE` e 92 `HOLD`, contra 32 `BUY` e 4 `SELL`. Ele usa a saída de não operar, como a seção 6 exige — mas isso não bastou para proteger o resultado.
- **A camada de risco trabalhou**: 28 overrides e 18 bloqueios. O sistema não foi um LLM solto.
- **Custo de transação pesou**: 14 trades pagaram 250,69 em taxa sobre 10.000, para um resultado pior que o do `buy_and_hold`, que pagou 15,40.

#### Diagnóstico de dimensionamento (risco a 0,25%) — o problema é a tese, não o tamanho

Mesmo recorte de 91 dias, mesmas regras, só o risco por operação caindo de 1% para 0,25%:

| Estratégia | Retorno | Sharpe | Drawdown | Acerto | Trades | Bloqueios de risco |
|---|---|---|---|---|---|---|
| `buy_and_hold` | −11,60% | −1,17 | −20,93% | 0% | 1 | — |
| `ema_crossover` | **−3,53%** | −0,58 | −10,53% | 26,32% | 19 | — |
| `hibrida_llm_risk` (1%) | −14,90% | −2,66 | −19,21% | 28,57% | 14 | **18** |
| `hibrida_llm_risk_baixo` (0,25%) | **−14,69%** | −2,64 | −20,20% | 33,33% | 18 | **0** |

**O ajuste funcionou exatamente como projetado, e não mudou nada.** Os bloqueios por exposição foram de 18 para **zero** — a estratégia passou a poder abrir todas as posições que quis, e executou 18 trades em vez de 14. E o resultado ficou **praticamente idêntico**: −14,69% contra −14,90%, Sharpe −2,64 contra −2,66. Continua perdendo para as duas baselines por margem quase igual (3,09 e 11,16 pontos, contra 3,30 e 11,37).

**A conclusão é clara e é a que o diagnóstico existia para dar: o dimensionamento não era o problema.** Duas configurações de risco muito diferentes, uma delas sem nenhuma restrição ativa, produziram o mesmo resultado ruim. O que não funciona é a tese — a direção que o cérebro escolhe, não o tamanho com que ela é apostada.

Métricas auditadas de forma independente a partir das operações cruas: batem todas.

Vale notar o que a path-dependence produziu: as direções do LLM mudaram entre as duas rodadas (`NO_TRADE` 203 vs 236, `HOLD` 136 vs 92, `BUY` 18 vs 32) porque o caminho pela série foi outro — posições diferentes geram prompts diferentes. As duas rodadas são experimentos distintos que convergiram no mesmo lugar, o que **fortalece** a conclusão em vez de enfraquecê-la.

#### Replicação em BNBUSDT — o resultado vira o oposto, e isso muda a conclusão

Mesma janela (10/08 a 09/11/2025), mesma configuração (risco 1%, cadência 6h), mesmo modelo. **Só o ativo mudou.**

| Estratégia | Retorno | Sharpe | Max drawdown | Acerto | Trades |
|---|---|---|---|---|---|
| `buy_and_hold` | +25,01% | 1,69 | −32,89% | 100% | 1 |
| `ema_crossover` | +14,88% | 1,47 | −18,47% | 25,0% | 20 |
| **`hibrida_llm_risk`** | **+25,54%** | **3,47** | **−8,56%** | 61,5% | 13 |

A híbrida **bateu as duas**. E o número que mais importa não é o retorno — é o par Sharpe/drawdown: ela entregou praticamente o mesmo retorno do buy-and-hold com **um quarto da queda máxima** (−8,56% contra −32,89%) e Sharpe mais que o dobro. Métricas auditadas de forma independente a partir das operações cruas.

Vale notar como: das 364 consultas, **284 foram `NO_TRADE`** — ainda mais passiva que no BTC (236). Ela ficou fora do mercado a maior parte do tempo e, mesmo assim, capturou toda a alta. Isso é seletividade, não sorte de exposição.

**A conclusão anterior ("o que não funciona é a tese") estava forte demais.** O desempenho depende do ativo e do regime: a mesma estratégia, no mesmo período, com a mesma configuração, perdeu por 3,3 pontos num ativo em queda e ganhou num ativo em alta com metade do risco.

**Três ressalvas que impedem de comemorar:**

1. **A BNB foi escolhida sabendo que subiu 25%.** Isso é seleção — o modelo não sabia, então a rodada é válida, mas isto **não é evidência de que o sistema escolheria a BNB**. Saber de antemão qual ativo vai subir é o problema difícil, e ele continua sem solução aqui.
2. **Duas rodadas apontando para lados opostos não são uma vantagem — são duas amostras.** É igualmente compatível com "a estratégia segue tendência e precisa de tendência" e com "n=2, isso é ruído".
3. **Só existe medida em dois ativos.** Uma vantagem real aparece na distribuição, não em anedota escolhida.

O que o resultado **legitimamente** sustenta: operar um único ativo em queda handicapa o sistema, e a camada de risco funciona — foi ela que produziu o drawdown de −8,56%.

#### Varredura de estratégias simples — 10 ativos × 5 regras, custo zero

Mesma janela de 91 dias, taxa de 0,10%, sem nenhuma chamada de API (todas as regras são aritmética sobre indicadores que a Feature Engine já calcula).

| Estratégia | Média | Mediana | Melhor | Pior | Bateu o b&h | Trades (méd.) | Sharpe (méd.) |
|---|---|---|---|---|---|---|---|
| `buy_and_hold` | −15,14% | −19,18% | +25,01% | −27,21% | — | 1,0 | −0,54 |
| `ema_crossover` | −15,15% | −17,48% | +14,88% | −37,80% | 5/10 | 21,8 | −1,27 |
| `rsi_reversao` | **−4,32%** | −6,99% | +29,33% | −24,85% | 6/10 | 8,5 | −0,16 |
| `macd_histograma` | −19,70% | −22,20% | −4,10% | −29,56% | 3/10 | 84,4 | −1,82 |
| `acima_da_ema200` | −17,77% | −18,12% | +6,17% | −35,66% | 4/10 | 43,0 | −2,10 |

Quatro leituras, e três delas mudam conclusões anteriores:

**1. O `ema_crossover` não tem vantagem nenhuma.** Média de −15,15% contra −15,14% do buy-and-hold — empate estatístico —, bateu o b&h em 5 de 10 (cara ou coroa) e tem pior caso *pior* (−37,80% contra −27,21%). **O +8,07 dele no BTC era ruído.** Isso enfraquece de vez o enquadramento "uma regra de duas linhas bateu a IA": aquela regra não bate nada, ela teve sorte num ativo. A comparação que vale contra a híbrida é sempre a do buy-and-hold.

**2. O filtro de tendência não reproduz o resultado da BNB — e isso conta a favor da híbrida.** A hipótese natural para o +25,54% da IA na BNB era "ela só ficou comprada numa alta, qualquer filtro de tendência faria igual". Não faz: o `acima_da_ema200` capturou **+6,17%** na BNB contra os +25,01% do buy-and-hold e os +25,54% da híbrida. A regra simples ficou com um quarto do ganho. O que a híbrida fez na BNB não é trivialmente replicável por um filtro de média longa.

**3. O `rsi_reversao` parece o melhor, mas o mecanismo importa mais que o número.** A média de −4,32% vem em boa parte de **baixa exposição**: ele só entra com RSI < 30 e fica fora até o próximo sinal, com 8,5 trades de média. Num período em que 9 dos 10 ativos caíram, ficar fora do mercado é quase indistinguível de ter razão. A prova está na BNB, o único ativo que subiu: ele fez **−1,35%** enquanto o buy-and-hold fez +25,01%. Não é habilidade, é aversão estrutural — e ela custaria caro num período de alta.

**4. Reagir rápido é caro.** O `macd_histograma` é a versão apressada do cruzamento de médias: 84,4 trades de média, pior retorno médio e pior Sharpe do conjunto. O custo de transação come o sinal.

**A ressalva que enquadra tudo isto:** 9 dos 10 ativos caíram no período. Isto não é uma medida de "que estratégia funciona" — é uma medida de "que estratégia sobrevive a um mercado em queda". Qualquer regra que reduza exposição vai parecer boa aqui e pode ser péssima num período de alta. **Viés de sobrevivência conhecido e não corrigido:** os ativos são majors que existem hoje; quem morreu no caminho não está na lista, então os números absolutos são otimistas. A comparação *entre* estratégias continua válida — todas enfrentaram os mesmos ativos.

#### Mapa de regimes — 64 janelas, 320 backtests, e o veredito sobre a ideia adaptativa

8 ativos × 8 janelas de 91 dias cobrindo ~2 anos, rotuladas pelo comportamento do próprio ativo (alta > +10%, baixa < −10%, lateral no meio). 30 janelas de alta, 18 laterais, 16 de baixa. Zero chamada de API.

**Retorno médio por estratégia × regime:**

| Estratégia | Alta | Lateral | Baixa | Geral |
|---|---|---|---|---|
| `buy_and_hold` | **+50,23%** | −0,72% | −20,83% | **+18,14%** |
| `ema_crossover` | +33,62% | −1,83% | −14,64% | +11,58% |
| `rsi_reversao` | +11,05% | −0,67% | **−3,15%** | +4,20% |
| `macd_histograma` | +0,63% | −9,91% | −20,93% | −7,72% |
| `acima_da_ema200` | +20,03% | −10,71% | −19,02% | +1,62% |

**Duas conclusões, e elas puxam para lados opostos.**

**1. A premissa da ideia adaptativa está certa: o regime muda tudo.** O `rsi_reversao` perde 39 pontos para o buy-and-hold em alta e ganha 18 em baixa — uma variação de 57 pontos conforme o regime. Não é ruído, é estrutura. E confirma o que a varredura de 91 dias sugeria: o "melhor desempenho médio" dele lá era artefato de mercado em queda.

**2. Mas nenhuma estratégia bate o buy-and-hold no geral.** Todas têm vantagem média negativa (−6,55, −13,93, −25,86, −16,51) e vencem em menos da metade das janelas (26, 26, 15 e 17 de 64). Num período em que quase metade das janelas foi de alta, comprar e segurar é difícil de bater.

#### O número que decide se vale construir o seletor

| | Retorno médio |
|---|---|
| Comprar e segurar sempre | +18,14% |
| Seletor com conhecimento **perfeito** do regime | +22,57% |
| **Teto do ganho** | **+4,43 pontos** |

**Mesmo com presciência total do regime, o prêmio é 4,43 pontos.** Esse é o limite superior — inalcançável, porque exigiria saber o futuro.

E o detector realista destrói valor:

| Detector = regime da janela anterior (sem olhar o futuro) | |
|---|---|
| Acertou o regime seguinte | **15/56 (27%)** |
| Adaptativo com esse detector | +3,47% |
| Comprar e segurar, mesmas janelas | +16,79% |
| **Ganho real** | **−13,33 pontos** |

27% de acerto é **pior que chutar "alta" sempre** (47% das janelas são de alta). A matriz de transição explica: depois de uma janela de alta, o que vem é 31% alta, 34% lateral, 34% baixa — praticamente sorteio.

**Veredito: o regime de 91 dias não é previsível a partir do anterior, e o prêmio por acertá-lo é pequeno demais para pagar os erros.** Construir o seletor como desenhado produziria um sistema que perde 13 pontos para não fazer nada.

**Ressalva de escopo, para não generalizar demais:** isto testa *um* detector (o regime anterior) numa *uma* escala (91 dias). Um detector mais rápido, ou outra escala, poderia se sair melhor. O que o resultado estabelece com firmeza é o **teto**: qualquer detector precisa caber dentro de 4,43 pontos de prêmio, e errar custa mais que isso. É pouco espaço para pagar complexidade.

**O que o dado sugere como direção alternativa.** O único lugar onde a híbrida mostrou algo não-trivial foi controle de perda, não direção: na BNB ela empatou com o buy-and-hold em retorno (+25,54% vs +25,01%) com **um quarto do drawdown** (−8,56% vs −32,89%). Se há valor no sistema, a evidência aponta para "mesmo retorno, menos sofrimento" — uma história de Sharpe e drawdown — e não para "escolhe melhor a direção". Vale medir nessa métrica, não em retorno bruto.

#### Replicação em SOLUSDT — e o quadro com quatro ativos

| SOLUSDT, 91 dias | Retorno | Sharpe | Max drawdown | Acerto | Trades |
|---|---|---|---|---|---|
| `buy_and_hold` | −9,26% | −0,12 | −39,86% | 0% | 1 |
| `ema_crossover` | −6,80% | −0,36 | −19,91% | 28,6% | 21 |
| **`hibrida_llm_risk`** | **+13,63%** | **1,26** | **−15,09%** | 55,6% | 18 |

Auditado de forma independente a partir das 36 operações cruas.

| Ativo | b&h | Híbrida | Dif | DD b&h | DD híbrida | Dif DD |
|---|---|---|---|---|---|---|
| BTCUSDT | −11,60% | −14,90% | −3,30 | −20,93% | −19,21% | +1,72 |
| BNBUSDT | +25,01% | +25,54% | +0,53 | −32,89% | −8,56% | +24,33 |
| ETHUSDT | −15,28% | −7,10% | +8,18 | −34,88% | −22,96% | +11,92 |
| SOLUSDT | −9,26% | +13,63% | +22,89 | −39,86% | −15,09% | +24,77 |
| **Média** | −2,78% | **+4,29%** | **+7,07** | −32,14% | **−16,46%** | **+15,68** |

**Drawdown melhor em 4 de 4. Retorno melhor em 3 de 4. Sharpe melhor em 3 de 4.**

O número de operações é o mesmo em todos: 14, 13, 23, 18 — contra **51,6 do stop puro sem cérebro**. É a assinatura do mecanismo já identificado na ablação: o `NO_TRADE` impede a recompra que pica o capital.

**Ressalva que não encolheu:** quatro ativos, **uma única janela de 91 dias**. Três dos quatro caíram nesse período, o que favorece estruturalmente quem fica de fora. Não é evidência de que funciona em alta — a BNB é o único caso de alta e é justamente o de menor vantagem em retorno (+0,53). Falta XRP, e falta repetir em outras janelas antes de tratar isso como resultado.

#### Replicação em ETHUSDT — e o padrão que aparece nos três ativos

Terceiro ativo, mesma janela, mesma configuração. **A híbrida bateu as duas baselines.**

| ETHUSDT, 91 dias | Retorno | Sharpe | Max drawdown | Acerto | Trades |
|---|---|---|---|---|---|
| `buy_and_hold` | −15,28% | −0,70 | −34,88% | 0% | 1 |
| `ema_crossover` | −16,75% | −1,66 | −26,18% | 16,7% | 24 |
| **`hibrida_llm_risk`** | **−7,10%** | **−0,47** | **−22,96%** | 52,2% | 23 |

Bateu o buy-and-hold por 8,18 pontos e o cruzamento de médias por 9,65. Métricas auditadas de forma independente a partir das operações cruas.

**O quadro com três ativos:**

| Ativo | Regime | b&h | Híbrida | Diferença | DD b&h | DD híbrida | Diferença |
|---|---|---|---|---|---|---|---|
| BTCUSDT | baixa | −11,60% | −14,90% | −3,30 | −20,93% | −19,21% | **+1,72** |
| BNBUSDT | alta | +25,01% | +25,54% | +0,53 | −32,89% | −8,56% | **+24,33** |
| ETHUSDT | baixa | −15,28% | −7,10% | **+8,18** | −34,88% | −22,96% | **+11,92** |
| **Média** | | −0,62% | **+1,18%** | **+1,80** | −29,57% | **−16,91%** | **+12,66** |

**O retorno é irregular (melhor em 2 de 3). O drawdown não é: melhor em 3 de 3, por 12,66 pontos em média.**

Essa é a diferença que importa, e ela ganha força quando comparada com a ablação: o stop-loss sem cérebro melhorou o drawdown em **0,40 ponto**, acertando em 30 de 64 janelas — cara ou coroa. A híbrida melhora em **12,66 pontos**, em 3 de 3. Não é a mesma coisa acontecendo.

**A hipótese que sobrevive:** o valor deste sistema não é escolher direção — é *não estar posicionado nas horas erradas*. As três rodadas são consistentes com isso e o mecanismo já foi identificado na ablação (o `NO_TRADE` impede a recompra que pica o capital). O retorno segue o drawdown quando o ativo cai, e não atrapalha quando sobe.

**Ressalvas, do mesmo tamanho de antes:** três ativos, uma janela, um período. Dois dos três caíram, então o conjunto ainda favorece quem fica de fora. SOL e XRP faltam. E o `ema_crossover` já mostrou que uma vantagem em poucos ativos pode ser ruído — foi exatamente isso que a varredura de 10 moedas revelou sobre ele.

#### Ablação: o stop-loss sozinho NÃO explica o resultado da BNB

A hipótese mais econômica para o +25,54% da híbrida na BNB era que o crédito fosse todo do Risk Engine: um stop por ATR corta a queda, e o cérebro seria decoração cara. Se fosse isso, a conclusão do projeto estaria praticamente escrita.

`backend/backtest/stop_puro.py` testa exatamente isso — faz o que a híbrida faz **menos o LLM**: compra sempre que estiver sem posição, calcula stop e alvo pelo ATR via `avaliar_risco`, sai quando um nível é rompido, e recompra. Mesma janela, mesmo capital, mesma taxa.

| BNBUSDT, 91 dias | Retorno | Sharpe | Max drawdown | Trades |
|---|---|---|---|---|
| `buy_and_hold` | +25,01% | 1,69 | −32,89% | 1 |
| **`hibrida_llm_risk`** | **+25,54%** | **3,47** | **−8,56%** | 13 |
| stop puro 2× ATR | −1,73% | 0,14 | −26,36% | 36 |
| stop puro 4× ATR | +0,42% | 0,35 | −34,21% | 46 |
| stop puro 8× ATR | +11,91% | 1,02 | −34,08% | 27 |

**Nenhuma configuração chega perto.** A melhor delas (8× ATR) fica pior que simplesmente comprar e segurar, nas duas dimensões. A hipótese "foi só o stop" está descartada para esta janela.

O mecanismo aparece na contagem de trades. O stop puro fez 27 a 46 operações; a híbrida, 13. Quando o stop puro sai, ele **recompra no candle seguinte** e é picotado de novo. A híbrida não: o cérebro respondeu `NO_TRADE` em 284 das 364 consultas, então depois de sair ela ficava fora. **A contribuição do LLM naquela janela não foi escolher a hora de entrar — foi não reentrar mal.**

Também vale notar que o take-profit atrapalha em tendência de alta: o stop puro saiu no alvo 15 a 28 vezes, vendendo ganhador cedo. A híbrida segurou.

**Ressalva do mesmo tamanho de sempre:** um ativo, uma janela. Isto elimina uma explicação alternativa; não prova vantagem. A replicação em ETH, SOL e XRP é o que transforma isso em evidência ou em coincidência.

#### O stop-loss por ATR, sozinho, não protege — medido em 64 janelas

A ablação da BNB levantou a pergunta seguinte: o stop puro é ruim só ali, ou em geral? Rodado nas mesmas 64 janelas do mapa de regimes, 192 backtests, zero chamadas de API:

| Estratégia | Retorno médio | Sharpe médio | Drawdown médio | Trades médios |
|---|---|---|---|---|
| `buy_and_hold` | **+18,14%** | **0,96** | **−34,83%** | 1,0 |
| stop puro 2× ATR | +0,95% | 0,06 | −34,43% | 51,6 |
| stop puro 8× ATR | +12,80% | 0,62 | −35,58% | 23,7 |

**O stop-loss não reduz o drawdown.** Essa é a descoberta, e ela é desconfortável:

| vs. comprar e segurar | Drawdown | Melhorou em | Retorno |
|---|---|---|---|
| stop 2× ATR | **+0,40 pts** | 30/64 (cara ou coroa) | **−17,18 pts** |
| stop 8× ATR | **−0,75 pts** (pior) | 24/64 | −5,33 pts |

Ele custa 17 pontos de retorno para entregar 0,4 ponto de drawdown — e "melhorar em 30 de 64" é indistinguível de sorteio. Vale por regime também: em alta, lateral e baixa, o drawdown do stop fica dentro de ~1 ponto do buy-and-hold.

**Por que não protege:** ele sai e *recompra*, e a recompra pega a perna seguinte da queda. O drawdown é medido do pico do patrimônio, então ser picotado várias vezes acumula tanto quanto segurar — só que pagando taxa em 51 operações.

**Duas consequências que mudam o desenho:**

1. **A camada de risco, sozinha, não é o valor do sistema.** Ela foi construída como proteção e, medida isoladamente, não protege. Isso não a torna inútil — a regra 1 continua sendo a trava contra o viés de aversão à perda do LLM (seção 6) —, mas desfaz a suposição de que ela carregaria o resultado sozinha.

2. **O resultado da BNB fica *mais* difícil de explicar sem o cérebro, não menos.** Lá a híbrida teve drawdown de −8,56%; o stop puro, entre −26% e −34%; o buy-and-hold, −32,89%. A híbrida conseguiu algo que nenhuma das duas conseguiu — e agora sabemos que não foi o stop.

Continua valendo a ressalva: a híbrida rodou em dois ativos, com resultados opostos. ETH, SOL e XRP decidem se isso é mecanismo ou coincidência.

#### Qual das duas pernas machuca: é o take-profit

Mesmas 64 janelas, desligando o alvo (multiplicador absurdamente alto):

| Variante | Retorno médio | Sharpe | Drawdown | Trades |
|---|---|---|---|---|
| `buy_and_hold` | **+18,14%** | 0,96 | −34,83% | 1,0 |
| stop 2× **com** alvo 3× | +0,95% | 0,06 | −34,43% | **51,6** |
| stop 2× **sem** alvo | +13,92% | 0,70 | −34,37% | **5,7** |
| stop 8× **sem** alvo | +16,51% | 0,88 | −34,63% | 2,2 |

Desligar o take-profit recupera **13 pontos de retorno** e corta as operações de 51,6 para 5,7 — 9× menos — com drawdown idêntico dentro do ruído. O alvo não comprava proteção nenhuma: vendia ganhador cedo e forçava recompra, e a recompra é o que gerava o rodízio.

Mesmo assim, nenhuma variante bate o buy-and-hold. A leitura correta não é "desliguem o alvo e fica bom" — é **o Risk Engine, isolado, custa retorno e não entrega proteção**.

**Isto ilumina o resultado da BNB por outro ângulo.** A híbrida usa take-profit (3×/6×/12× ATR por horizonte) e mesmo assim fez só 13 operações, não 51. O que segurou o rodízio foi o `NO_TRADE` do cérebro: depois de sair, ela não recomprava. **A passividade do LLM estava mascarando um defeito da camada de risco** — o que é uma explicação bem mais interessante que "a IA acertou a direção".

**Ressalva de amostra:** 30 das 64 janelas são de alta. Num período dominado por queda o take-profit provavelmente ajudaria. O efeito medido aqui é real e grande, mas é condicionado a este conjunto.

⚠️ **Não mexer nos multiplicadores agora.** ETH, SOL e XRP precisam rodar com a mesma configuração de BTC e BNB, senão a replicação — a única coisa que separa mecanismo de coincidência — perde o sentido. Calibrar o alvo é assunto para depois que os cinco ativos estiverem medidos.

#### Uma propriedade do experimento que este diagnóstico revelou

As respostas do LLM **não são independentes da configuração de risco**. O cache é indexado pelo hash do prompt, e o prompt inclui `posicao_aberta` — o cérebro precisa saber se há posição para escolher entre `HOLD` e `NO_TRADE` (seção 5). Trocar o risco muda o dimensionamento → muda quando as posições abrem e fecham → muda o prompt. Medido: o cache divergiu depois de **9 consultas** das 364, e a rodada custou 248 chamadas novas.

A consequência é metodológica: **não existe ablação barata de parâmetros de risco mantendo as opiniões do modelo fixas.** Cada configuração é uma execução própria, com seu próprio caminho pela série.

**Três ressalvas que impedem de concluir qualquer coisa definitiva:**

1. **São 91 dias, não o ano.** A rodada completa (1.460 consultas) não coube na cota do Gemini — 500/dia, seção 8. Os 91 dias são exatamente o que o cache cobria. Um trimestre não é um regime.
2. **É um recorte de mercado em queda**, como a baseline do ano inteiro. Continua valendo o registrado abaixo: o mesmo teste precisa rodar num período de alta antes de virar evidência.
3. **A configuração de risco não foi calibrada.** Rodou com risco de 1% e teto de 50%, a combinação que a própria seção mostra ser restritiva. Não se sabe quanto do resultado é a tese do LLM e quanto é o dimensionamento.

### Calibração do Risk Engine (passo 6) — os padrões quase nunca aprovam

Medido sobre um ano de BTCUSDT, 50 amostras semanais, capital de 10.000:

| Configuração | Entradas aprovadas | Exposição exigida (mediana) |
|---|---|---|
| **Padrão** — stop 2× ATR, risco 1%, teto 50% | **2 / 50** | 84% do capital |
| stop 2× ATR, risco 1%, teto 100% | 35 / 50 | 84% do capital |
| stop 2× ATR, **risco 0,25%**, teto 50% | 50 / 50 | 21% do capital |
| **stop 8× ATR**, risco 1%, teto 50% | 50 / 50 | 21% do capital |

Não é bug — é aritmética, e vale entender antes do passo 7. O ATR-14 em candle de 1h tem mediana de **0,61% do preço**, então um stop a 2× ATR fica a ~1,2% de distância. Arriscar 1% do capital com um stop de 1,2% exige nocional de ~84% do capital. Em spot, sem alavancagem, o **teto de exposição vira a restrição que manda**, e a regra de risco vira decoração.

Os padrões ficaram em 2×/3×/1% de propósito: são os valores especificados para o passo 6, e mudá-los em silêncio esconderia a tensão em vez de resolvê-la. Mas fica o registro para o passo 7: **se a estratégia híbrida rodar com os padrões e quase não operar, isso é a configuração falando, não o cérebro.** Distinguir os dois é a diferença entre calibrar e concluir errado.

### A Binance geo-bloqueia CI — e o testnet não serve como fonte de dados

Medido em 2026-09-04, de dentro de um runner do GitHub Actions (Phoenix, EUA):

| Endpoint | Resposta |
|---|---|
| `api.binance.com` | **451** — restricted location |
| `testnet.binance.vision` | **451** — restricted location |
| `api-gcp.binance.com` | **451** — restricted location |
| `data-api.binance.vision` | **200** |
| `api.binance.us` | 200 |

Dois achados, e o segundo é o mais importante:

**1. Só `data-api.binance.vision` funciona em CI.** É o endpoint público de dados de mercado — sem autenticação, sem ordens, sem geo-bloqueio. O adapter usa ele em modo `somente_dados_publicos`, e o workflow do GitHub Actions não carrega mais chave nenhuma da Binance.

O `api.binance.us` também responde, mas é **outra corretora**: no mesmo candle de BTCUSDT, `data-api` marcou 433,78 BTC de volume e o `.us` marcou 1,77. Adotá-lo trocaria silenciosamente o mercado sobre o qual todos os backtests foram feitos.

**2. O `main.py` vinha coletando do testnet, que tem livro próprio.** Mesmo candle, mesmo instante:

| Fonte | Abertura | Fechamento | Volume |
|---|---|---|---|
| mainnet | 80968,01 | 80831,99 | **433,78** |
| `data-api` | 80968,01 | 80831,99 | **433,78** |
| testnet | 80968,01 | 80829,**99** | **23,79** |

O `data-api` é idêntico ao mainnet campo a campo. O testnet **não é** — fechamento diferente e ~5% do volume. Como `volume_relativo` é uma das features gravadas em `decisions`, a coleta ao vivo vinha registrando um indicador calculado sobre volume simulado. Corrigido junto.

**Consequência para o passo 8 — corrigida.** A primeira leitura disto foi que "paper trading precisa de endpoint autenticado, logo o passo 8 não roda no GitHub Actions e vai precisar de host pago". Isso estava errado, porque tratava como uma coisa só o que são duas:

| | Pergunta que responde | Precisa de testnet? |
|---|---|---|
| Validação da estratégia ao vivo | funciona em dado que nunca viu, para a frente no tempo? | **não** |
| Validação do encanamento de ordens | a corretora aceita a ordem que eu monto? | sim |

A primeira precisa de preço real (endpoint público, grátis), contabilidade própria (`portfolio`, já existe) e simulação de execução (o motor de backtest já faz). **Roda inteira no GitHub Actions, de graça.**

E há um argumento mais forte do que o custo: **o testnet daria dado pior.** O livro dele tem ~5% do volume real, então os preenchimentos não representam a execução de verdade. Rotear paper trading por lá trocaria preço real por preço simulado — justamente o que o resto do projeto evita.

A segunda precisa de credencial, e não precisa ser contínua: é um punhado de execuções manuais para conferir `LOT_SIZE`/`stepSize`, `minNotional` e rejeições. Isso roda no PC do dono, onde não há bloqueio geográfico. Host pago só entra se um dia a operação com dinheiro real exigir presença permanente fora dos EUA.

## 12. Considerações regulatórias e de risco

**CVM (Brasil):** existe uma distinção entre o robô que o próprio investidor configura e opera só pra si (informalmente chamado de robô "White Box"), que não exige registro na CVM porque quem decide é o dono do dinheiro através do sistema que ele mesmo programou, e o robô que presta consultoria ou gestão pra terceiros, que exige. Este projeto, sendo de uso pessoal, cai no primeiro caso. Se um dia a ideia for oferecer isso pra outras pessoas, essa premissa muda e precisa de orientação jurídica de verdade — nada aqui é aconselhamento jurídico.

**Opções binárias:** descartadas como mercado — motivo completo na seção 2.

**Expectativa:** a própria CVM já financiou estudo mostrando que a fatia de pessoas físicas que lucra de forma consistente fazendo day-trade é pequena, sem evidência de que trocar decisão humana por robô mude esse quadro. Isso não invalida o projeto (meta experimental, seção 1) — só significa que "meses de backtest e paper trading consistentes" é a barra antes de dinheiro real, não uma formalidade a cumprir depressa.

## 13. Quando migrar para pago

| Gatilho | Ação |
|---|---|
| Supabase perto de 500MB, ou precisar de backup automático | Upgrade para Pro (~$25/mês) |
| Precisar eliminar cold start ou rodar mais de um serviço 24/7 | Plano pago do Render (a partir de ~$7/mês) |
| Projeto virar algo comercial | Vercel Pro (o Hobby proíbe uso comercial) |
| Quiser um endereço próprio | Domínio pago — cosmético, não trava nada tecnicamente |
| Volume de análises passar o limite diário do Gemini, ou quiser um modelo mais forte | LLM pago (Gemini pago, ou outro provedor) |

## 14. Decisões descartadas (e por quê)

Documentado aqui pra não reabrir debate sem motivo novo:

| Alternativa | Por que foi descartada |
|---|---|
| Firebase junto com Supabase | Redundante — Supabase já cobre banco e autenticação |
| GitHub Pages pro frontend | Só hospeda site estático, não roda API routes do Next.js |
| XP/BTG como corretora inicial | Não têm API pública de auto-atendimento pra automação |
| B3 como mercado inicial | Sem conta demo com API própria pra bot (o simulador do app HUB3 é pensado pra uso manual) |
| Opções binárias como mercado | Oferta proibida no Brasil (Deliberação CVM 598/2018); ~80% de quem opera perde dinheiro |
| LLM decidindo stop-loss/take-profit diretamente | Gera números sem relação com a volatilidade real do ativo |
| Cérebro analisando candle bruto | Caro em tokens, inconsistente entre chamadas |
| Day trade como única estratégia | O usuário queria qualquer horizonte, com a IA decidindo caso a caso |
| Short/alavancagem no V1 | Risco de liquidação exige gestão de risco própria — fica pra V2 |
| OpenRouter como provedor de LLM | Avaliado no passo 7. Sem crédito são **50 requisições/dia** — 10× pior que as 500 do Gemini que já usamos. Com US$ 10 (compra única) sobe para 1.000/dia, mas o ano inteiro de backtest custa ~US$ 2 direto na Anthropic, então pagar o intermediário rende menos. Some-se que os modelos `:free` exigem ligar "treinar nos inputs"/"publicar prompts", e que rotear para provedores variados quebra a reprodutibilidade que o cache de respostas garante. A troca de provedor foi resolvida com a camada em `brain/provedores.py`, que não depende de intermediário. |
| Ensemble de vários LLMs | Multiplica chamadas e custo para reduzir variância de um sinal que ainda não demonstrou ter sinal (seção 11: a híbrida perdeu das duas baselines). Otimização prematura enquanto a pergunta central estiver em aberto. |

## 15. Próximo passo imediato

**Terminar o passo 7 antes de ir para o passo 8.** O roteiro diz que o próximo é paper trading, mas a metodologia da seção 11 e o princípio 6 dizem o contrário: paper trading vem *depois* de a híbrida bater a baseline no backtest. Hoje ela perdeu num ativo (BTC) e ganhou noutro (BNB) — isso é uma amostra dividida, não uma vantagem demonstrada. Levar para a testnet com base num resultado de dois ativos, um deles escolhido sabendo que subiu, seria exatamente o erro que esta etapa existe para impedir.

### O que já foi respondido, e o que sobrou

**Respondido: o problema não é o dimensionamento.** O diagnóstico a 0,25% de risco eliminou todos os bloqueios por exposição (18 → 0) e mesmo assim deu −14,69% contra os −14,90% da configuração original. Duas execuções independentes, mesmo resultado.

**Respondido: o problema também não é "a tese não presta".** A replicação em BNBUSDT, mesma janela e mesma configuração, bateu as duas baselines — e com um quarto do drawdown do buy-and-hold (seção 11). O desempenho depende do ativo e do regime, não é uma incapacidade fixa do cérebro.

**Em aberto, e agora é a pergunta certa: existe vantagem na média, ou só em ativos escolhidos a dedo?** Há medida em dois ativos, com resultados opostos, e a BNB foi escolhida *sabendo* que tinha subido. Vantagem real aparece na distribuição, não em anedota.

O caminho barato para responder: rodar a mesma híbrida, mesma janela e mesma configuração, nos três ativos restantes já baixados — **ETHUSDT, SOLUSDT, XRPUSDT** (que caíram ou ficaram de lado no período). São ~1.100 consultas, 2–3 dias de cota ou ~US$ 2 no Haiku. Com cinco ativos passa a existir uma distribuição: a híbrida bate o buy-and-hold **na média**, ou só quando o ativo sobe?

Isso é mais informativo que terminar o ano do BTC. Estender a janela de um ativo dá mais dado sobre o mesmo caso; replicar em ativos não escolhidos a dedo testa se a vantagem existe.

Rodar o mesmo comando de novo é sempre seguro: o cache retoma de onde parou e nada do que já foi gasto se perde. Quando a cota do dia acaba, o script **para limpo** com código de saída 2 dizendo quanto avançou — não é falha, é pausa. Insistir no mesmo dia não adianta: cota diária não passa com espera dentro do processo (é a diferença que `_e_cota_diaria()` trata).

⚠️ **Uma ressalva sobre trocar de provedor no meio:** o ano medido no Haiku não seria comparável com os 91 dias medidos no Gemini. Cada rodada seria internamente válida, mas a comparação entre elas misturaria efeito de modelo com efeito de período.

### A decisão que se aproxima

Com o dimensionamento descartado como causa, o espaço de explicações encolheu para duas: **ou os 91 dias foram um trecho atipicamente ruim, ou a tese do LLM não agrega vantagem.** O ano completo separa as duas, e é a última pergunta barata que resta.

Se o ano confirmar a perda, a resposta honesta é que **esta versão não agrega vantagem** — e a seção 1 já classifica isso como descoberta válida, não fracasso. O caminho aí não é paper trading. É mudar a hipótese (outra cadência, outro conjunto de features, o modelo de ML supervisionado que a seção 2 lista como evolução natural) ou registrar a conclusão negativa e parar.

Vale dizer o que **não** seria honesto fazer: continuar ajustando parâmetros até algum resultado ficar positivo. Com um período só e um ativo só, é fácil encontrar uma configuração que ganhe por acaso — e ela não sobreviveria a dado novo. A barra da seção 11 continua sendo bater a baseline em mais de um regime.

### Ideia em avaliação: estratégia adaptativa por regime, com orçamento de ações

Proposta do usuário, registrada aqui antes de virar código porque ela tem uma dependência que precisa ser satisfeita primeiro.

**A ideia.** Em vez de uma estratégia fixa, um sistema que primeiro **lê o mercado** e então escolhe o que fazer: comprar e segurar, operar curto, operar com risco, ou não operar. Mais um **orçamento por tipo de ação** — por exemplo, no máximo N entradas de "comprar e segurar" num período; esgotado o orçamento, gatilhos daquele tipo passam a ser ignorados.

**Parte dela já existe.** O `horizon` (`curto`/`medio`/`longo`) que o cérebro devolve desde o passo 5 já escolhe os multiplicadores de stop e alvo (seção 6). Isso *é* comportamento adaptativo ao tipo de operação. O que falta é o passo anterior: ler o regime e usar isso para decidir.

**A dependência bloqueante: só existe medida de um regime.** Todos os números das seções 11 vêm de agosto a novembro de 2025, período em que 9 de 10 ativos caíram. Um seletor de regime calibrado só com dado de baixa pareceria excelente e quebraria na primeira alta — é a forma mais direta de produzir um backtest bonito e falso. **Antes de construir o seletor, é preciso saber se o desempenho das estratégias realmente muda por regime.** Se não mudar, não há o que adaptar e o seletor é complexidade sem retorno.

**O orçamento de ações merece uma reformulação.** Um teto arbitrário de N sinais não é princípio — por que 5? Mas existe uma versão rigorosa da mesma intuição, e ela ataca um problema já medido: **limitar operações por período combate o sangramento de taxa**. A varredura mostrou o `macd_histograma` com 84 trades de média e o pior retorno do conjunto; o `ema_crossover` queimou 12,8% do capital em taxa no ano. Um limitador de ações por janela é, na prática, um controle de risco — e é testável offline, sem gastar token.

**Ordem de ataque, com o que cada etapa custa:**

| Etapa | Custo | Resultado |
|---|---|---|
| **A.** Mapa de regimes: 5 estratégias × 64 janelas × 8 ativos, ~2 anos | zero token | ✅ **Feito.** O regime muda tudo (variação de 57 pontos), mas o teto do seletor é **+4,43 pontos** e um detector honesto perde **−13,33**. Seção 11. |
| **B.** Camada de orçamento de ações | zero token | 🔲 Ainda vale — ataca o sangramento de taxa, que é problema medido e independente do regime |
| **C.** Detector de regime determinístico | zero token | ❌ **Bloqueado pelo resultado de A**, não por falta de trabalho |
| **D.** Seletor: regime → estratégia | zero token | ❌ Idem |
| **E.** LLM como leitor de regime | token | ❌ Não faz sentido: se a regra simples não cabe no prêmio, o LLM tem ainda menos espaço e custa mais |

**A etapa A matou C, D e E — e essa é a economia mais barata do projeto até agora.** Zero token gastos para descobrir que o seletor de regime, como desenhado, perderia 13 pontos para simplesmente não fazer nada. Descobrir isso construindo teria custado semanas e uma conclusão errada pelo caminho.

O que sobrevive da ideia original:

- **A etapa B**, o orçamento de ações. O sangramento de taxa é real e medido (`macd_histograma` com 84 trades e o pior retorno do conjunto; `ema_crossover` queimando 12,8% do capital em taxa no ano) e não depende de prever regime nenhum. Limitar operações por janela é controle de risco puro.
- **A reorientação da métrica.** O único sinal não-trivial da híbrida foi drawdown, não retorno: na BNB, mesmo retorno do buy-and-hold com um quarto da queda máxima. Se há valor aqui, ele está em Sharpe e drawdown. Medir por retorno bruto pode estar olhando para o lugar errado.

### Passo 8 dividido em 8a e 8b

O passo 8 estava escrito como um bloco só — "paper trading" — e isso escondia que ele mistura duas perguntas independentes, com custos e riscos diferentes. Separado:

**8a — Forward test (grátis, contínuo, no GitHub Actions).** O sistema decide de verdade e escritura as operações, mas o preenchimento é simulado por nós, ao preço real de mercado. Responde: *a vantagem medida na seção 11 aparece em dado que o modelo nunca viu, andando para frente no tempo?* É a única pergunta que ainda decide se o projeto continua.

**8b — Encanamento de ordens (local, manual, pontual).** Enviar ordem de verdade na testnet a partir do PC, umas poucas vezes, para descobrir o que a corretora rejeita. Responde: *a ordem que eu monto é aceita?* Não precisa ser contínuo nem hospedado, e não deve rodar em CI (bloqueio geográfico).

A ordem importa: **8a não depende de 8b.** Amarrar os dois adiaria a medição que importa por causa de um problema de formatação de ordem.

#### O que 8a exige

| Peça | Estado |
|---|---|
| Lógica de decisão | **pronta** (`brain/hybrid_strategy.py`) |
| Persistência da posição | **pronta e verificada** (`risk/portfolio_repo.py`) |
| Cadência pura, servindo relógio e backtest | **pronta** (`brain/cadencia.py`) |
| Dados reais em CI | **pronto** (endpoint público) |
| Estado da estratégia atravessando processos | **falta** |
| Escrituração da operação simulada | **falta** |
| Proteção contra execução dupla | **falta** |

#### Os três riscos reais, em ordem

**1. Estado atravessando processos — o mais difícil do projeto até aqui.**

No backtest um processo só segura tudo: `niveis`, `niveis_pendentes`, `ultima_tese` vivem em memória do começo ao fim. No cron o processo **morre a cada ciclo**, e cada ponto onde ele pode morrer é um estado possivelmente inconsistente. O caso que custa dinheiro: registrar a compra e morrer antes de gravar os níveis — a posição existe sem stop, e o ciclo seguinte não sabe que precisa protegê-la. `portfolio_repo` já se recusa a degradar para "sem posição" quando a leitura falha, exatamente por isso; falta a mesma disciplina na escrita.

**2. Execução dupla.**

Um `workflow_dispatch` manual junto com o disparo agendado, ou um retry do runner, e o mesmo ciclo roda duas vezes. Sem chave de idempotência isso vira duas compras. É o tipo de erro que não aparece em teste e aparece em produção.

**3. A execução ao vivo não é a do backtest.**

O backtest executa na **abertura do candle seguinte** ao sinal. Ao vivo, o cron acorda aos :05 e executaria ao preço daquele instante — ou seja, "abertura do candle seguinte + 5 min". A diferença é pequena mas é sistemática, e vai fazer o resultado ao vivo divergir do backtest por um motivo que não tem nada a ver com a estratégia. Decidir explicitamente: ou replicar o atraso, ou registrar a diferença e medir o quanto ela custa.

#### O que 8a NÃO vai responder

O forward test roda sobre o mercado que existir nas próximas semanas. A vantagem da seção 11 foi medida numa janela onde **três dos quatro ativos caíram** — e a hipótese é justamente que o sistema protege na queda. Se as próximas semanas forem de alta, o resultado pode ser fraco sem que isso refute nada, e forte sem que isso confirme nada. O critério de leitura precisa ser fixado **antes** de ver o número, senão vira interpretação conveniente.

### Quando o passo 8 chegar

O que muda de natureza: é a primeira vez que o sistema **envia ordem** — até aqui nada foi executado, nem em testnet.

- **O cron job passa a compor as peças.** Hoje `main.py` busca candles, calcula features e grava `status = 'skeleton_check'`. A lógica de decisão já existe inteira em `brain/hybrid_strategy.py`; falta o equivalente ao vivo do estado que ela guarda em memória.
- **O estado da posição sai da memória e vai para o `portfolio`.** No backtest os níveis vivem na estratégia porque o processo roda tudo de uma vez; no cron o processo morre a cada ciclo. `risk/portfolio_repo.py` já está escrito, e as colunas `preco_entrada`/`stop_loss`/`take_profit` **já foram aplicadas no banco**. A ida e volta foi verificada contra o Supabase real: gravar uma posição com níveis, ler de volta idêntica, e a regra 1 disparar em cima do estado lido — forçando `SELL` contra um `HOLD` do LLM. É a fundação do passo 8, e ela funciona.
- **A cadência muda de relógio.** "Agora" passa a ser o relógio de parede e "última consulta" sai da tabela `decisions`. `cadencia.deve_consultar()` já é pura para servir aos dois.
- **A regra 1 roda a cada ciclo do cron** (15 min), não a cada 6h. Mesma armadilha do passo 7.
- **`enviar_ordem` deixa de ser código morto.** Conferir arredondamento de quantidade (`LOT_SIZE`/`stepSize` da Binance) antes do primeiro envio — o `tamanho_posicao` é um float qualquer e a corretora rejeita quantidade fora do passo.

É a primeira vez que o sistema vai **enviar ordem**. Até aqui nada foi executado, nem em testnet — todo o passo 7 foi simulação sobre histórico. O que muda de natureza:

- **O cron job passa a compor as peças.** Hoje `main.py` busca candles, calcula features e grava com `status = 'skeleton_check'`. Precisa passar a chamar cérebro + Risk Engine e gravar `llm_output`, `risk_result` e o `status` de verdade (`no_trade` / `approved` / `blocked` / `executed`). A lógica de decisão já existe inteira em `brain/hybrid_strategy.py`; o que falta é o equivalente ao vivo do estado que a híbrida guarda em memória.
- **O estado da posição sai da memória e vai para o `portfolio`.** No backtest os níveis de stop/take vivem na estratégia porque o processo roda a simulação inteira de uma vez. No cron job o processo morre a cada ciclo, então `preco_entrada`/`stop_loss`/`take_profit` têm que vir da tabela (`risk/portfolio_repo.py`, já escrito). **Pendência conhecida:** as três colunas ainda não foram aplicadas no banco — o `alter table` está no `schema.sql` e precisa ser rodado no SQL Editor.
- **A cadência muda de relógio.** No backtest "agora" é o timestamp do candle; ao vivo é o relógio de parede, e "última consulta" tem que sair da tabela `decisions` (última linha com `llm_output` preenchido). `cadencia.deve_consultar()` já é pura justamente para servir aos dois — quem tem o estado passa o estado.
- **A regra 1 roda a cada ciclo do cron, não a cada 6h.** Mesmo requisito do passo 7, e a mesma armadilha: o cron roda a cada 15 min, e a checagem de stop/take tem que rodar em todos eles. Só a consulta ao cérebro respeita as 6h.
- **`enviar_ordem` deixa de ser código morto.** O adapter já tem o método e ele nunca foi chamado. Vale conferir arredondamento de quantidade (`LOT_SIZE`/`stepSize` da Binance) antes do primeiro envio — o `tamanho_posicao` que o Risk Engine calcula é um float qualquer, e a corretora rejeita quantidade fora do passo permitido.

Antes de dinheiro real (passo 10), a barra continua sendo a da seção 11, e o passo 7 não a atingiu: a híbrida precisa bater a baseline **em mais de um regime de mercado**, não só no ano de baixa já testado.
