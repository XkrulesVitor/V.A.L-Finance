# Backtest confirmatório das carteiras de regra (T1, T2, G1, G2)

Gerado em 25/09/2026 04:55 UTC por `backend/backtest/analise_carteiras.py`, a partir de `resultados/carteiras_confirmatorio.json` (gerado em 2026-09-25 04:55 UTC por `backend/backtest/estudo_carteiras.py`). Pré-registro: `backend/backtest/PRE_REGISTRO_6_CARTEIRAS.md`, seção 12. Nenhum parâmetro de regra foi mudado (12.1). Sem LLM e sem download: só o cache congelado.

## 1. Respostas

| Hipótese | Pergunta | Resposta | Média Δ (log, pts/janela) | IC 90% | Mediana Δ | p (maior de Wilcoxon-Pratt e t) | p ajustado (Holm) | Holm rejeita a 5%? |
|---|---|---|---|---|---|---|---|---|
| **H1** | T2 > b&h f_dd | **Sem evidência de vantagem** | +3,71 | [−0,07; +7,49] | +5,88 | 0,0530 | 0,2122 | não |
| **H2** | G2 > b&h f_dd | **Sem evidência de vantagem** | −2,10 | [−5,66; +1,45] | +0,18 | 0,8393 | 0,9087 | não |
| **H3** | G1 ≠ T1 | **Inconclusivo** | −13,88 | [−25,79; −1,97] | −0,31 | 0,3029 | 0,9087 | não |
| **H4** | G2 ≠ T1 | **Inconclusivo** | −11,72 | [−22,62; −0,82] | +1,00 | 0,3748 | 0,9087 | não |

Δ é a diferença por bloco de tempo (média dos ativos numa janela de 91 dias; 24 blocos) em pontos de log: `100·[ln(1+r_carteira) − ln(1+r_referência)]`, sobre o **R1c** (contínuo recortado nas janelas). Referência de H1 e H2: comprar-e-segurar de fração fixa `f_dd` (uma por período, a que iguala o drawdown médio da carteira). Referência de H3 e H4: a T1.

- **H1 (T2 > b&h f_dd) — Sem evidência de vantagem.** Média +3,71 pts por janela (IC 90% −0,07 a +7,49), mediana +5,88, média aparada +3,39; mediana por período (fim do período) 2026: +1,59; 2024: +2,07; 2022: +9,05. Régua antiga (média por janela, em %): +5,06. Pior caso do R3 (x = 6, 05:00): média +4,09, mediana +4,79. Por que esta resposta: o Holm não rejeita (p = 0,0530; p ajustado = 0,2122).
- **H2 (G2 > b&h f_dd) — Sem evidência de vantagem.** Média −2,10 pts por janela (IC 90% −5,66 a +1,45), mediana +0,18, média aparada −2,24; mediana por período (fim do período) 2026: −0,38; 2024: −3,70; 2022: +3,31. Régua antiga (média por janela, em %): −1,62. Pior caso do R3 (x = 6, 05:00): média −3,29, mediana −1,00. Por que esta resposta: o Holm não rejeita (p = 0,8393; p ajustado = 0,9087). As réguas discordam no sinal (antiga −1,62; mediana nova +0,18): pela 12.4 isso também levaria a "inconclusivo"; as duas leituras dizem a mesma coisa, que não há vantagem demonstrada.
- **H3 (G1 ≠ T1) — Inconclusivo.** Média −13,88 pts por janela (IC 90% −25,79 a −1,97), mediana −0,31, média aparada −9,45; mediana por período (fim do período) 2026: −0,72; 2024: +2,78; 2022: −9,73. Régua antiga (média por janela, em %): −27,05. Pior caso do R3 (x = 6, 05:00): média −13,73, mediana −0,00; com x = 2: média −13,86. Por que esta resposta: a média aponta contra a carteira, mas falta: o Holm não rejeita (p = 0,3029; p ajustado = 0,9087).
- **H4 (G2 ≠ T1) — Inconclusivo.** Média −11,72 pts por janela (IC 90% −22,62 a −0,82), mediana +1,00, média aparada −10,04; mediana por período (fim do período) 2026: +1,28; 2024: +1,00; 2022: −6,08. Régua antiga (média por janela, em %): −23,77. Pior caso do R3 (x = 6, 05:00): média −13,31, mediana +0,03. Por que esta resposta: a média aponta contra a carteira, mas falta: o Holm não rejeita (p = 0,3748; p ajustado = 0,9087); a mediana dos blocos (+1,00) aponta o outro sentido; no pior caso do R3 (x = 6, 05:00) o sinal se mantém em só 1 de 3 períodos.

Em palavras:

- **O stop gain ganha dinheiro? (G1 × T1, H3) — Inconclusivo.** Na média, vender na meta custou: por janela de 91 dias a G1 ficou −13,88 pts de log abaixo da T1 (IC 90% −25,79 a −1,97). Por regime do ativo na janela (variação do preço na janela), a diferença G1 − T1 por janela, em pontos percentuais, teve média de −82,2 (mediana −28,1) nas 71 janelas de alta (> +10%); +5,5 (mediana +5,0) nas 42 janelas laterais; +6,5 (mediana +0,0) nas 76 janelas de baixa (< −10%). O período até 2022-09-03 responde por 68% da média (média do período −28,31); na janela típica a diferença é de −0,31 (mediana dos blocos; a G1 ficou à frente em 11 dos 24 blocos). O teste de postos, que olha a janela típica, dá p = 0,3029; com o Holm, p ajustado = 0,9087. Pelo critério pré-registrado, não dá para dizer "custa dinheiro" nem "ganha dinheiro". Descritivo (R1c, média por janela e ativo): a G1 rendeu +1,56% contra +28,60% da T1, com queda máxima média de −17,3% contra −24,6%, e acertou 29% das operações contra 24% da T1. O teste tinha bem menos poder do que a especificação supunha: o erro-padrão da média foi 6,95 pt (a 12.4 supunha ≈ 1,04), e o menor efeito que ele detectaria com 80% de chance é de ≈ 23 pts por janela, e não 3,7.
- **As Tartarugas batem o comprar-e-segurar de mesmo risco? (T2, H1) — Sem evidência de vantagem.** A T2 ficou à frente na média (+3,71 pts por janela, mediana +5,88), com mediana positiva em 3 de 3 períodos; p = 0,0530 e, corrigido para as 4 perguntas (Holm), 0,2122. O efeito observado é menor que o mínimo que 24 blocos detectam com a dispersão observada (≈ 6,8 pts). Por regime do ativo na janela (variação do preço na janela), a diferença T2 − T1 por janela, em pontos percentuais, teve média de −35,3 (mediana −10,7) nas 71 janelas de alta (> +10%); −0,5 (mediana −0,4) nas 42 janelas laterais; +6,4 (mediana +7,5) nas 76 janelas de baixa (< −10%). Foi o que a especificação previu.
- **O Repique bate o comprar-e-segurar de mesmo risco? (G2, H2) — Sem evidência de vantagem.** Na média a G2 ficou atrás (−2,10 pts por janela); na janela típica, empate (mediana +0,18); p = 0,8393. Ela fica comprada só 8% do tempo. Empate ou derrota, como a especificação previu.
- **O Repique difere das Réguas? (G2 × T1, H4) — Inconclusivo.** Na média a G2 ganhou menos que a T1 (−11,72 pts por janela); na janela típica, mediana +1,00. Por regime do ativo na janela (variação do preço na janela), a diferença G2 − T1 por janela, em pontos percentuais, teve média de −78,9 (mediana −36,9) nas 71 janelas de alta (> +10%); +7,4 (mediana +4,8) nas 42 janelas laterais; +10,5 (mediana +10,5) nas 76 janelas de baixa (< −10%). O período até 2022-09-03 responde por 60% da média. Média e mediana apontam lados opostos. p = 0,3748; p ajustado (Holm) = 0,9087.

Nenhuma das 4 perguntas teve resposta firme. Isso não quer dizer que as carteiras são iguais: quer dizer que 24 blocos de 91 dias, com a régua combinada antes, não separam essas diferenças do acaso. As diferenças de comportamento (quanto cada uma fica comprada, quanto cai, quantas vezes opera) estão nas seções 5, 9 e 10, e são descritivas.

## 2. Convenções desta leitura

A especificação deixa alguns detalhes em aberto. Eles foram fechados assim, e valem para as 4 hipóteses. Nenhum deles mexe em regra de carteira (12.1); o que foi acrescentado depois de ver os números está marcado.

1. **Aquecimento do R1c.** "Quando o histórico permite" = no 1º dia do aquecimento (91 dias antes da 1ª janela válida do ativo) as 4 carteiras já têm sinal pronto — a mesma guarda do R1. O cache congelado tem os arquivos dos 3 períodos, fundidos por `abertura_em` (cada candle repetido foi conferido idêntico entre arquivos). Em 2024-26 e 2022-24 há 393 dias antes da 1ª janela: aquecimento de 91 dias. Em 2020-22 o cache começa em 20/12/2019 (260 dias antes da 1ª janela): no 1º dia do aquecimento só haveria 169 dias, e o RSI(2) precisa de 220. Pela regra da 12.2, **o R1c de 2020-22 começa na 1ª janela** (a janela 0 de 2020-22 sai igual à do R1). Uma leitura descritiva com aquecimento parcial (começa 91 dias antes e a G2 fica em caixa até ter 220 dias) está na seção 8.
2. **Retorno de uma janela no R1c** = patrimônio marcado a mercado no fechamento do último candle da janela ÷ o do fechamento do candle anterior ao 1º da janela (sem liquidar; a última janela também é marcada a mercado). Drawdown medido dentro da janela, com o pico começando no patrimônio de entrada. A referência b&h de cada janela é a mesma do R1 (compra na abertura do 1º candle, vende no fechamento do último, 0,1% por ponta). Isso dá à carteira do R1c uma vantagem de até 0,2·f pt por janela contra o b&h-f (não paga a entrada nem a saída quando atravessa a fronteira comprada); com f entre 0,2 e 0,6, é no máximo 0,12 pt, muito abaixo de qualquer efeito que os 24 blocos detectam (seção 6).
3. **Régua antiga** (a da T1): média, sobre as janelas (ativo × janela), da diferença simples em % contra a referência. Em H1 e H2 a referência é o b&h de fração fixa `f_dd` do período; em H3 e H4 é a T1 (diferença simples G1 − T1 ou G2 − T1). "Concorda" = a média das janelas dos 3 períodos tem o mesmo sinal pedido. **Régua nova** = Δ em log por bloco; o pré-registro ("Situação", defesa 3) a descreve como a mediana em log, e a 12.5 pede média **e** mediana no sentido da resposta. *Nota acrescentada depois de ver os números:* numa hipótese unilateral em que o Holm não rejeita, a resposta é "Sem evidência de vantagem" (a linha da tabela da 12.5 que cobre esse caso), mesmo que as réguas discordem no sinal; a discordância é escrita junto da resposta, porque pela 12.4 ela levaria a "inconclusivo". As duas respostas dizem o mesmo: nenhuma vantagem demonstrada.
4. **Robustez do R3.** "O sinal se mantém" num período = a mediana dos 8 blocos daquele período, na variante, tem o sinal pedido (o estimador por período da 12.4). Em H1 e H2 o `f_dd` é recalculado com o drawdown da variante. Pior caso = stop/alvo com x = 6 e decisões às 05:00; em H3 também x = 2 (decisões às 01:00).
5. **Testes.** Wilcoxon de postos sinalizados com tratamento de Pratt para zeros (`scipy.stats.wilcoxon(zero_method='pratt', method='auto')`: exato sem zeros nem empates; com zeros, aproximação normal com o ajuste de Pratt/Cureton), t de uma amostra com 23 graus de liberdade, vale o maior p. H1 e H2 unilaterais (> 0); H3 e H4 bicaudais. Holm-Bonferroni com α familiar de 5% sobre H1–H4. Teste do sinal relatado como complementar.
6. **b&h 100%** = a grade do b&h com f = 1 (compra na abertura do 1º candle). O `f_dd` sai da grade de 0 a 100% em passos de 0,5%, como no estudo 2.
7. **Perda realizada no stop** = preço de saída ÷ preço de entrada − 1, só nas saídas por "stop de catastrofe"; p90 = o 10º percentil (a cauda ruim).

## 3. O que rodou

- Cache: manifesto `9b0b6bccc9033ff8df35d6f4c2f1278af3f41d37eb0ae1383252896a547d05dd` — **confere** com o hash do pré-registro. Nenhum download (o adaptador da Binance foi trocado por um que falha).
- Janelas válidas (R1 = R1c = R3): 2026: 64; 2024: 64; 2022: 61; total 189. Excluídas pela guarda de aquecimento: SOLUSDT j0 (2022), SOLUSDT j1 (2022), SOLUSDT j2 (2022).
- Blocos de tempo: 24 (3 períodos × 8 janelas).
- Início da simulação do R1c: fim 2026-09-01: 2024-06-04 (91 dias de aquecimento; todos os ativos) | fim 2024-09-03: 2022-06-07 (91 dias de aquecimento; todos os ativos) | fim 2022-09-03: 2020-09-05 (0 dias de aquecimento — sem aquecimento: no 1º dia dele nem todas as regras teriam sinal; BTC, ETH, BNB, XRP, ADA, DOGE, LINK); 2021-06-05 (0 dias de aquecimento — sem aquecimento: no 1º dia dele nem todas as regras teriam sinal; SOL).
- R2: uma janela contínua de 2 anos por ativo e período, começando em caixa na 1ª janela (SOL fica de fora em 2020-22, como no exploratório).
- R3: base (x = 0, 01:00), x = 2, 01:00, x = 6, 01:00, x = 0, 05:00, x = 2, 05:00, x = 6, 05:00 (pior caso).

Código usado (sha256 no momento da rodada) contra os hashes do pré-registro:

| Arquivo | sha256 agora | sha256 no pré-registro | situação |
|---|---|---|---|
| `backend/backtest/estudo_carteiras.py` | `d2f12fab61afee78…` | `c98e327993e2fe96…` | difere: esperado; é o harness com as correções da 16.4 e o que faltava (R0, R0b, R1c, R3). A configuração "exploratória" dele reproduz os 6 logs (seção 4) |
| `backend/backtest/engine.py` | `d70b949fc76065ba…` | — | não está na tabela de hashes do pré-registro: é versionado (o motor) e, em 25/09, igual ao último commit |
| `backend/backtest/efeito_stop_catastrofe.py` | `1e53761101735add…` | — | não está na tabela de hashes do pré-registro: é versionado (a referência do R0) e, em 25/09, igual ao último commit |
| `backend/estrategia/alvo.py` | `7538df4ec7b7130b…` | `1437c7f3831a3a5f…` | difere: o arquivo foi alterado às 16:43 de 24/09, depois do cálculo do hash, e não há cópia da versão registrada para comparar linha a linha. A mudança esperada é a 16.4-3 (`DIAS_MINIMOS = 150` em `atr_pct`). O resto do que o harness usa dele (`ALVO_EM_ATR`, `ATR_N`, `nivel_de_alvo`, `MOTIVO_ALVO`) se comporta como na versão exploratória: a G1 da configuração exploratória reproduz os logs (seção 4) |
| `backend/estrategia/indicadores.py` | `855e01f06cd364d4…` | `855e01f06cd364d4…` | **igual** |
| `backend/estrategia/rsi2.py` | `63bc8a4434bd5dcc…` | `63bc8a4434bd5dcc…` | **igual** |
| `backend/estrategia/tartarugas.py` | `855b1e7053535616…` | `855b1e7053535616…` | **igual** |
| `backend/estrategia/tendencia_diaria.py` | `367e0baf6d715d87…` | — | não está na tabela de hashes do pré-registro: é versionado (a regra da T1). Em 25/09 a cópia de trabalho diferia do último commit só numa linha de docstring; a regra é conferida a cada rodada pelo R0 |

## 4. Conferências R0 e R0b

**R0 — a T1 do harness reproduz o `efeito_stop_catastrofe.py` ("com stop")?** Sim. 189 janelas comuns, maior |diferença| = 0,0000 pt (limite 0,01). O harness não mudou a regra da T1.

**R0b — comparação com os 6 logs exploratórios** (sha256 de cada log conferido com o pré-registro).

- O harness com **todas as correções desligadas** reproduz os logs em 848 de 848 células (carteira × janela, R1 e contínuo) com |dif| < 0,005. Ou seja: fora das correções, o harness novo é o mesmo que gerou os logs.
- Janelas: os logs têm 189 janelas medidas e 3 excluídas; o conjunto confirmatório é o mesmo.
- Com as correções (a versão confirmatória), 0 células mudam em relação aos logs. Sem explicação: **0**.

**Por que as correções não mudaram nenhuma célula medida** (comparação dia a dia das tabelas de sinal exploratória e corrigida, 8 ativos × 3 períodos, 19637 dias desde o início do aquecimento do R1c):

- 16.4-1 (guarda de saída): dias em que a G2 teria compra **e** saída no mesmo dia: **0**. Sem esse dia, a guarda não tem o que bloquear (na T1, T2 e G1 ela não pode morder: a entrada e a saída pela regra são mutuamente exclusivas no mesmo dia).
- 16.4-2 (janela de 300 dias): dias em que as duas tabelas têm o sinal pronto e ele difere (compra/venda de Réguas, Tartarugas ou RSI(2)): **0**, dos quais **0** em janela medida. Outros 816 dias diferem só porque uma tabela ainda não tem histórico (a exploratória lê só o arquivo de 260 dias; esses dias ficam no aquecimento do R1c, que o exploratório não tinha), dos quais 0 em janela medida. Maior diferença relativa do ATR: 4,4×10⁻⁶; do N das Tartarugas: 2,0×10⁻⁴. Os níveis de stop 2N e de alvo mudam nessa ordem de grandeza, sem virar nenhum cruzamento nas janelas medidas.
- 16.4-3 (ATR com 150 dias): dias em que o ATR existe numa tabela e não na outra: 135, dos quais **0** em janela medida (são os primeiros meses da SOL em 2020-21, nas janelas que a guarda do RSI(2) já exclui).
- 3b (ATR só na G1): nas janelas medidas o ATR sempre existe, então exigir ou não exigir ATR na T1, T2 e G2 não muda nada.

Como a atribuição foi feita: além da versão exploratória e da confirmatória, o harness roda R1 e R2 com cada correção ligada sozinha. Uma diferença é atribuída à correção que, ligada sozinha, leva a célula exatamente ao valor confirmatório.

## 5. Resultados por carteira — R1c (leitura principal)

| Carteira | janelas | retorno médio (%) | mediano | log médio (pts) | drawdown médio | exposição | idas e voltas/ano | custo em taxa (% do capital/ano) | acerto | expectativa por operação: média / mediana (%) | ganho / perda médios (%) | perda no stop: média / p90 (%) | saídas por motivo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1 Réguas | 189 | +28,60 | −4,35 | +9,45 | −24,60 | 47% | 11,0 | 2,2 | 24% | +13,75 / −2,92 | +74,96 / −5,06 | −21,83 / −23,48 | tendencia virou 503, stop de catastrofe 8, fim de janela 8 |
| T2 Tartarugas | 189 | +17,83 | +0,00 | +7,79 | −17,89 | 27% | 3,6 | 0,7 | 41% | +25,18 / −5,67 | +77,10 / −10,29 | −32,63 / −33,11; 2N: −10,88 / −14,48 | tendencia virou 85, stop de catastrofe 2, stop 2N 76, fim de janela 7 |
| G1 Réguas com meta | 189 | +1,56 | +1,64 | +0,13 | −17,30 | 24% | 12,8 | 2,6 | 29% | +0,71 / −2,94 | +16,63 / −5,66 | −21,75 / −24,32 | tendencia virou 434, stop de catastrofe 13, stop gain 155 |
| G2 Repique | 189 | +4,83 | +0,00 | +1,01 | −10,12 | 8% | 7,9 | 1,6 | 63% | +1,77 / +1,34 | +7,53 / −7,84 | −21,87 / −24,98 | repique 339, stop de catastrofe 34, fim de janela 1 |

Contra as referências (R1c; média por janela da diferença simples em pontos percentuais; `f_dd` e `f_expo` são do período e da carteira):

| Carteira | período (fim) | janelas | retorno médio (%) | vs b&h 100% | f_dd | vs b&h f_dd | f_expo | vs b&h f_expo |
|---|---|---|---|---|---|---|---|---|
| T1 Réguas | 2026-09-01 | 64 | +13,06 | −0,86 | 60,5% | +4,64 | 44,0% | +6,93 |
| T1 Réguas | 2024-09-03 | 64 | +9,27 | −5,95 | 73,5% | −1,91 | 49,0% | +1,81 |
| T1 Réguas | 2022-09-03 | 61 | +65,20 | −2,36 | 53,5% | +29,06 | 49,0% | +32,10 |
| T2 Tartarugas | 2026-09-01 | 64 | +9,48 | −4,44 | 41,0% | +3,77 | 23,0% | +6,28 |
| T2 Tartarugas | 2024-09-03 | 64 | +8,91 | −6,30 | 47,5% | +1,69 | 27,5% | +4,73 |
| T2 Tartarugas | 2022-09-03 | 61 | +35,96 | −31,60 | 38,5% | +9,95 | 30,0% | +15,69 |
| G1 Réguas com meta | 2026-09-01 | 64 | +0,65 | −13,27 | 43,0% | −5,33 | 23,5% | −2,62 |
| G1 Réguas com meta | 2024-09-03 | 64 | −0,60 | −15,81 | 48,0% | −7,90 | 24,5% | −4,33 |
| G1 Réguas com meta | 2022-09-03 | 61 | +4,76 | −62,79 | 32,5% | −17,19 | 24,5% | −11,79 |
| G2 Repique | 2026-09-01 | 64 | +0,03 | −13,89 | 18,5% | −2,55 | 6,0% | −0,81 |
| G2 Repique | 2024-09-03 | 64 | −1,30 | −16,52 | 28,0% | −5,56 | 9,5% | −2,75 |
| G2 Repique | 2022-09-03 | 61 | +16,32 | −51,24 | 19,0% | +3,49 | 8,0% | +10,92 |

## 6. Hipóteses em detalhe (R1c, 24 blocos)

| H | blocos | média Δ log | IC 90% | mediana | média aparada 5% | média Δ simples (%) | régua antiga (%/janela) | blocos +/−/0 | p Wilcoxon-Pratt | p t (23 gl) | p sinal | p Holm |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 24 | +3,71 | [−0,07; +7,49] | +5,88 | +3,39 | +5,17 | +5,06 | 13/11/0 | 0,0505 (exato) | 0,0530 | 0,4194 | 0,2122 |
| H2 | 24 | −2,10 | [−5,66; +1,45] | +0,18 | −2,24 | −1,43 | −1,62 | 13/11/0 | 0,7272 (exato) | 0,8393 | 0,4194 | 0,9087 |
| H3 | 24 | −13,88 | [−25,79; −1,97] | −0,31 | −9,45 | −29,15 | −27,05 | 11/13/0 | 0,3029 (exato) | 0,0577 | 0,8388 | 0,9087 |
| H4 | 24 | −11,72 | [−22,62; −0,82] | +1,00 | −10,04 | −25,38 | −23,77 | 12/12/0 | 0,3748 (exato) | 0,0782 | 1,0000 | 0,9087 |

Por período (mediana dos 8 blocos, em pts de log; entre parênteses a média; e a régua antiga do período):

| H | até 2026-09-01 | até 2024-09-03 | até 2022-09-03 |
|---|---|---|---|
| H1 | +1,59 (+2,39); +3,77 | +2,07 (+0,79); +1,69 | +9,05 (+7,95); +9,95 |
| H2 | −0,38 (−2,08); −2,55 | −3,70 (−5,25); −5,56 | +3,31 (+1,02); +3,49 |
| H3 | −0,72 (−6,81); −12,41 | +2,78 (−6,52); −9,87 | −9,73 (−28,31); −60,44 |
| H4 | +1,28 (−7,05); −13,03 | +1,00 (−7,00); −10,57 | −6,08 (−21,11); −48,88 |

**As duas réguas lado a lado** (mesmo peso): régua antiga = média por janela da diferença em % contra o b&h de fração fixa (H1, H2) ou contra a T1 (H3, H4); régua nova = Δ em log por bloco (média e mediana).

| H | régua antiga (%/janela) | régua nova: média (log/bloco) | régua nova: mediana | antiga × média nova | antiga × mediana nova |
|---|---|---|---|---|---|
| H1 | +5,06 | +3,71 | +5,88 | mesmo sinal | mesmo sinal |
| H2 | −1,62 | −2,10 | +0,18 | mesmo sinal | **sinal oposto** |
| H3 | −27,05 | −13,88 | −0,31 | mesmo sinal | mesmo sinal |
| H4 | −23,77 | −11,72 | +1,00 | mesmo sinal | **sinal oposto** |

Poder observado: o desvio-padrão dos 24 blocos e o erro-padrão da média (a 12.4 supunha ≈ 1,04 pt de erro-padrão no par G1 × T1):

| H | desvio-padrão dos blocos (pts) | erro-padrão da média (pts) | efeito mínimo detectável aprox. (pts, 80% de poder, α de Holm no pior passo) |
|---|---|---|---|
| H1 | 10,8 | 2,21 | 6,8 |
| H2 | 10,2 | 2,07 | 6,4 |
| H3 | 34,0 | 6,95 | 23,2 |
| H4 | 31,2 | 6,36 | 21,2 |

## 7. Sensibilidade de execução (R3, sobre o R1c)

| Variante | H1 média / mediana · medianas por período (26, 24, 22) | H2 média / mediana · medianas por período (26, 24, 22) | H3 média / mediana · medianas por período (26, 24, 22) | H4 média / mediana · medianas por período (26, 24, 22) |
|---|---|---|---|---|
| base (x = 0, 01:00) | +3,71 / +5,88 · +1,6 +2,1 +9,0 | −2,10 / +0,18 · −0,4 −3,7 +3,3 | −13,88 / −0,31 · −0,7 +2,8 −9,7 | −11,72 / +1,00 · +1,3 +1,0 −6,1 |
| x = 2, 01:00 | +4,10 / +5,80 · +1,7 +2,4 +9,1 | −1,81 / +0,22 · −0,1 −4,3 +2,9 | −13,86 / −0,32 · −0,8 +2,9 −9,6 | −11,44 / +1,20 · +1,3 +1,2 −6,5 |
| x = 6, 01:00 | +3,93 / +6,02 · +1,4 +2,7 +9,1 | −1,92 / +0,55 · +0,4 −4,3 +2,9 | −13,86 / −0,03 · −0,1 +2,6 −9,2 | −11,45 / +0,60 · +1,5 +0,6 −6,4 |
| x = 0, 05:00 | +3,87 / +4,80 · +2,0 +1,4 +9,1 | −3,70 / −1,06 · −0,3 −3,6 +2,5 | −14,04 / −0,25 · −0,5 +1,7 −9,4 | −13,70 / +0,68 · +0,5 +0,9 −12,3 |
| x = 2, 05:00 | +3,96 / +4,83 · +1,9 +1,9 +9,1 | −3,51 / −1,03 · −0,3 −4,3 +2,4 | −14,03 / −0,19 · −0,5 +1,4 −9,6 | −13,51 / −0,04 · +0,5 +1,0 −11,4 |
| x = 6, 05:00 (pior caso) | +4,09 / +4,79 · +1,7 +2,0 +9,2 | −3,29 / −1,00 · −0,3 −4,3 +2,6 | −13,73 / −0,00 · −0,3 +1,1 −8,7 | −13,31 / +0,03 · +0,9 +1,2 −11,4 |

Retorno médio por janela e ativo (%), e drawdown médio, por variante:

| Variante | T1 | T2 | G1 | G2 |
|---|---|---|---|---|
| base (x = 0, 01:00) | +28,60 (dd −24,6) | +17,83 (dd −17,9) | +1,56 (dd −17,3) | +4,83 (dd −10,1) |
| x = 2, 01:00 | +28,58 (dd −24,6) | +18,44 (dd −17,9) | +1,59 (dd −17,5) | +5,09 (dd −10,1) |
| x = 6, 01:00 | +28,62 (dd −24,7) | +18,25 (dd −18,0) | +1,60 (dd −17,7) | +5,08 (dd −10,2) |
| x = 0, 05:00 | +29,50 (dd −24,4) | +17,93 (dd −17,7) | +1,94 (dd −17,2) | +3,19 (dd −10,3) |
| x = 2, 05:00 | +29,56 (dd −24,4) | +18,11 (dd −17,8) | +1,99 (dd −17,3) | +3,43 (dd −10,3) |
| x = 6, 05:00 (pior caso) | +29,58 (dd −24,4) | +18,34 (dd −17,8) | +2,35 (dd −17,4) | +3,61 (dd −10,3) |

## 8. Leituras descritivas: R1, R2 e o R1c de 2020-22 com aquecimento parcial

### R1 — janelas que começam em caixa (comparável ao histórico da T1; não decide nada)

| Carteira | janelas | retorno médio (%) | mediano | log médio (pts) | drawdown médio | exposição | idas e voltas/ano | custo em taxa (% do capital/ano) | acerto | expectativa por operação: média / mediana (%) | ganho / perda médios (%) | perda no stop: média / p90 (%) | saídas por motivo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T1 Réguas | 189 | +28,55 | −4,35 | +9,15 | −24,63 | 47% | 12,5 | 2,5 | 25% | +9,83 / −2,94 | +55,66 / −5,76 | −21,78 / −23,42 | tendencia virou 488, stop de catastrofe 19, fim de janela 80 |
| T2 Tartarugas | 189 | +15,89 | +0,00 | +6,66 | −17,16 | 24% | 4,6 | 0,9 | 39% | +14,40 / −5,92 | +53,39 / −10,71 | −30,05 / −32,99; 2N: −11,69 / −18,06 | tendencia virou 52, stop de catastrofe 3, stop 2N 100, fim de janela 62 |
| G1 Réguas com meta | 189 | +1,55 | +1,10 | −0,31 | −18,50 | 27% | 13,7 | 2,7 | 30% | +0,61 / −2,82 | +15,76 / −6,03 | −21,62 / −23,11 | tendencia virou 434, stop de catastrofe 21, stop gain 165, fim de janela 27 |
| G2 Repique | 189 | +4,92 | +0,00 | +1,10 | −9,96 | 8% | 8,0 | 1,6 | 62% | +1,80 / +1,32 | +7,48 / −7,48 | −21,89 / −25,05 | repique 334, stop de catastrofe 32, fim de janela 13 |

Contra as referências (R1; média por janela da diferença simples em pontos percentuais; `f_dd` e `f_expo` são do período e da carteira):

| Carteira | período (fim) | janelas | retorno médio (%) | vs b&h 100% | f_dd | vs b&h f_dd | f_expo | vs b&h f_expo |
|---|---|---|---|---|---|---|---|---|
| T1 Réguas | 2026-09-01 | 64 | +12,79 | −1,13 | 60,5% | +4,37 | 43,5% | +6,74 |
| T1 Réguas | 2024-09-03 | 64 | +9,29 | −5,93 | 73,5% | −1,90 | 49,0% | +1,83 |
| T1 Réguas | 2022-09-03 | 61 | +65,30 | −2,26 | 53,5% | +29,15 | 49,0% | +32,19 |
| T2 Tartarugas | 2026-09-01 | 64 | +9,02 | −4,90 | 39,0% | +3,59 | 20,0% | +6,24 |
| T2 Tartarugas | 2024-09-03 | 64 | +8,10 | −7,12 | 45,5% | +1,18 | 25,5% | +4,22 |
| T2 Tartarugas | 2022-09-03 | 61 | +31,26 | −36,30 | 36,5% | +6,60 | 26,0% | +13,69 |
| G1 Réguas com meta | 2026-09-01 | 64 | +0,53 | −13,39 | 46,5% | −5,94 | 26,0% | −3,08 |
| G1 Réguas com meta | 2024-09-03 | 64 | +0,01 | −15,20 | 51,5% | −7,82 | 27,5% | −4,17 |
| G1 Réguas com meta | 2022-09-03 | 61 | +4,24 | −63,32 | 35,5% | −19,74 | 27,0% | −14,00 |
| G2 Repique | 2026-09-01 | 64 | +0,07 | −13,85 | 18,0% | −2,43 | 6,0% | −0,76 |
| G2 Repique | 2024-09-03 | 64 | −1,00 | −16,21 | 27,0% | −5,10 | 9,5% | −2,44 |
| G2 Repique | 2022-09-03 | 61 | +16,22 | −51,34 | 19,0% | +3,38 | 8,0% | +10,81 |

| H (no R1) | média Δ log | IC 90% | mediana | régua antiga | p | medianas por período |
|---|---|---|---|---|---|---|
| H1 | +2,59 | [−0,89; +6,07] | +4,68 | +3,74 | 0,1075 | +1,6 +1,9 +4,7 |
| H2 | −1,97 | [−5,49; +1,55] | +0,14 | −1,46 | 0,8260 | −0,3 −2,7 +3,3 |
| H3 | −13,86 | [−25,56; −2,16] | +0,59 | −27,00 | 0,2839 | +0,2 +2,2 −9,7 |
| H4 | −11,54 | [−22,51; −0,58] | +1,73 | −23,63 | 0,3902 | +1,2 +1,7 −6,0 |

**Proporção de janelas com Δ = 0 exato no par G1 × T1:** R1 55/189 (29%) das janelas, 1/24 blocos; R1c 14/189 (7%) das janelas, 0/24 blocos.

### R2 — contínuo de 2 anos por ativo (começa em caixa)

| Período | ativos | b&h 100% médio | T1 média / mediana (dd médio) | T2 média / mediana (dd médio) | G1 média / mediana (dd médio) | G2 média / mediana (dd médio) |
|---|---|---|---|---|---|---|
| 2026 | 8 | +15,83 | +55,07 / +44,19 (dd −52,3) | +44,17 / +32,75 (dd −42,9) | +4,05 / −11,21 (dd −43,0) | −0,27 / +5,52 (dd −28,6) |
| 2024 | 8 | +100,71 | +51,32 / +25,83 (dd −49,3) | +84,27 / +50,12 (dd −40,4) | −10,72 / −25,20 (dd −38,3) | −12,34 / −8,09 (dd −33,2) |
| 2022 | 7 | +570,98 | +884,82 / +368,80 (dd −60,3) | +319,71 / +197,20 (dd −54,1) | +38,30 / +48,70 (dd −48,7) | +146,95 / +16,93 (dd −38,6) |

### R1c de 2020-22 com aquecimento parcial (descritivo)

A simulação de 2020-22 começa 91 dias antes da 1ª janela mesmo sem o RSI(2) pronto (a G2 fica em caixa até ter 220 dias). Só os 8 blocos de 2020-22 mudam; os outros 16 são os do R1c.

| H | mediana 2020-22 (sem aquec.) | idem (parcial) | média 2020-22 (sem) | idem (parcial) | média 24 blocos (sem) | idem (parcial) | p (sem) | p (parcial) |
|---|---|---|---|---|---|---|---|---|
| H1 | +9,05 | +9,05 | +7,95 | +7,95 | +3,71 | +3,71 | 0,0530 | 0,0530 |
| H2 | +3,31 | +2,31 | +1,02 | +0,38 | −2,10 | −2,31 | 0,8393 | 0,8649 |
| H3 | −9,73 | −8,76 | −28,31 | −28,02 | −13,88 | −13,78 | 0,3029 | 0,3165 |
| H4 | −6,08 | −6,82 | −21,11 | −21,20 | −11,72 | −11,75 | 0,3748 | 0,3449 |

## 9. G1: o que o stop gain faz (12.3, só descritivo)

**Acerto de equilíbrio (seção 6), recalculado com a perda média realizada nos stops.** Stops de catástrofe no R1c (T1, G1 e G2 juntas): 55, perda média −21,84%, p90 −24,69%. Ganho médio realizado nas saídas pelo alvo da G1: +18,47% (BTC +13,29%, ETH +16,80%; 155 saídas).

| Ativos | ganho médio no alvo (%) | acerto de equilíbrio com perda de 20% | com a perda média realizada |
|---|---|---|---|
| todos os ativos | +18,47 | 52,5% | 54,7% |
| BTC | +13,29 | 60,7% | 62,7% |
| ETH | +16,80 | 54,9% | 57,0% |

Na G1, das saídas que terminaram no alvo ou no stop (168), 92,3% foram no alvo. Saídas da G1 por motivo: tendencia virou 434, stop de catastrofe 13, stop gain 155.

**Ganho deixado na mesa** (variação do preço depois de cada saída pelo alvo, a partir do preço de saída):

| Período | saídas pelo alvo | 10 dias: média (%) | 10 dias: mediana | 30 dias: média (%) | 30 dias: mediana |
|---|---|---|---|---|---|
| 2026 | 53 | +5,01 | +0,81 | +15,93 | −0,84 |
| 2024 | 52 | +5,34 | +1,01 | +12,58 | +3,50 |
| 2022 | 50 | +21,98 | +5,41 | +46,61 | +16,22 |

**Decomposição de cada saída pelo alvo** contra a T1 (custo em pts de log; positivo = custou à G1). Se a G1 recomprou antes de a T1 sair da mesma tendência: `ln(P_recompra/P_alvo) + 0,2%`; se não recomprou: `ln(P_saída_T1/P_alvo)`. Soma por período, não é critério.

| Período | recomprou (n) | custo das reentradas (soma) | não recomprou (n) | custo de sair antes da T1 (soma) | T1 fora (n) | total |
|---|---|---|---|---|---|---|
| 2026 | 18 | +454,73 | 35 | −136,17 | 0 | +318,56 |
| 2024 | 34 | +487,18 | 18 | −154,44 | 0 | +332,74 |
| 2022 | 30 | +1096,87 | 20 | +27,75 | 0 | +1124,62 |

A soma é sobre todas as saídas pelo alvo dos 8 ativos nas janelas medidas; dividida pelo número de janelas-ativo do período, dá a ordem de grandeza por janela.

## 10. T2 × T1 (descritivo)

| Período | horas com a T1 comprada | horas com a T2 comprada | horas com só a T1 comprada | das horas da T1, só ela comprada | das horas da T2, só ela comprada | log-retorno da T1 nessas horas (média por janela-ativo, pts) | mediana |
|---|---|---|---|---|---|---|---|
| 2026 | 44% | 23% | 21% | 49% | 1,0% | +0,73 | +0,92 |
| 2024 | 49% | 27% | 22% | 45% | 2,1% | −1,22 | +0,25 |
| 2022 | 49% | 30% | 20% | 40% | 1,6% | +7,28 | +0,00 |

## 11. Faixa da sorte (13.4) e σ do par (sobre o R2)

Percentil do retorno de cada carteira na permutação dos próprios períodos comprados (5.000 sorteios, semente `sha256("VAL-6c-" + fim do período + carteira + par)`). Descritivo: no backtest não há categoria; a 13.4 vale para o ao vivo.

| Período | Carteira | BTC | ETH | BTC+ETH | mediana dos ativos | ativos ≥ 99,2 |
|---|---|---|---|---|---|---|
| 2026 | T1 | 89,5 | 88,9 | 95,7 | 79,7 | 0 |
| 2026 | T2 | 70,2 | 72,7 | 78,1 | 71,5 | 0 |
| 2026 | G1 | 77,1 | 42,3 | 61,1 | 41,9 | 0 |
| 2026 | G2 | 68,1 | 71,6 | 76,8 | 53,8 | 0 |
| 2024 | T1 | 60,5 | 52,5 | 60,3 | 55,2 | 0 |
| 2024 | T2 | 93,8 | 68,5 | 92,2 | 75,1 | 0 |
| 2024 | G1 | 2,6 | 10,7 | 1,3 | 19,1 | 0 |
| 2024 | G2 | 58,5 | 48,5 | 54,7 | 35,3 | 0 |
| 2022 | T1 | 88,8 | 80,1 | 93,4 | 88,1 | 0 |
| 2022 | T2 | 87,3 | 84,1 | 93,4 | 84,1 | 0 |
| 2022 | G1 | 51,1 | 58,6 | 57,3 | 51,1 | 0 |
| 2022 | G2 | 52,9 | 45,6 | 48,0 | 65,7 | 0 |

**σ do par T1 − G1** (bootstrap em blocos móveis de 30 dias sobre a diferença diária de log-patrimônio do R2; 10.000 sorteios de 365 dias):

| Par | σ_par (pts/ano, blocos) | σ sem blocos (iid) | média da diferença (pts/ano) | dias | σ por janela de 91 dias | faixa ±1,64·σ·√2 (24 meses) |
|---|---|---|---|---|---|---|
| BTCUSDT | 34,4 | 30,5 | +39,7 | 2183 | 17,2 | 79,8 |
| ETHUSDT | 44,3 | 45,3 | +42,5 | 2183 | 22,1 | 102,7 |
| BTC+ETH | 34,5 | 33,4 | +41,1 | 2183 | 17,2 | 80,1 |

A especificação usava σ_par ≈ 10,2 pts/ano (simulação sintética). Este é o número que substitui aquele na leitura de 24 meses (13.4).

## 12. Previsões registradas × resultado, e o rótulo de continuidade

**Rótulo descritivo de continuidade** (R1c; mediana de Δ contra o b&h f_dd > 0 no período). Sempre com a frase fixa: *sob acaso, 50% das estratégias sem vantagem passam neste critério*. Não decide nada.

| Carteira | passa na régua em | medianas por período (log) |
|---|---|---|
| T1 Réguas | 3 de 3 períodos | +6,1 +0,3 +6,9 |
| T2 Tartarugas | 3 de 3 períodos | +1,6 +2,1 +9,0 |
| G1 Réguas com meta | 1 de 3 períodos | +1,2 −3,2 −2,9 |
| G2 Repique | 1 de 3 períodos | −0,4 −3,7 +3,3 |

| Pergunta | Previsão registrada (12.5) | Resultado | Confere? |
|---|---|---|---|
| H1 T2 passa na régua? | "sem evidência de vantagem" (poder baixo) | Sem evidência de vantagem | sim |
|  | abaixo da T1 em alta forte | T2 − T1 nas 71 janelas de alta (> +10%): −35,29 pts percentuais por janela | sim |
| H2 G2 passa na régua? | "sem evidência de vantagem"; empate ou derrota | Sem evidência de vantagem (média −2,10, mediana +0,18) | sim |
| H3 G1 × T1 | "Não, custa dinheiro" ou "inconclusivo" | Inconclusivo | sim |
|  | estimativa < 0 em ≥ 2 de 3 períodos | 2 de 3 períodos com mediana < 0 | sim |
|  | G1 com +1 a +3 idas e voltas por janela | +0,44 por janela (+3,19 contra +2,75 da T1) | **não** |
|  | drawdown médio a no máximo 3 pts do da T1 | G1 −17,30 × T1 −24,60 (diferença +7,29 pts) | **não** (a G1 caiu menos que o previsto) |
|  | taxa de acerto maior que a da T1 | G1 29% × T1 24% | sim |
| H4 G2 × T1 | descritivo, sem previsão de sinal | Inconclusivo | — |

**Deflated Sharpe Ratio:** só se aplica a carteira que saia "Sim". Nenhuma saiu "Sim"; não calculado.

## 13. Ressalvas

- **Multiplicidade do projeto:** 5 configurações novas (T2, G1, G2, T3, G3) somadas às 18 do bloco anterior = 23. O Holm controla só a família H1–H4.
- **Grau de liberdade do pesquisador:** a régua nova (Δ em log por bloco) foi escolhida depois de se conhecerem a T1 e o DOGE; por isso as duas réguas saem lado a lado.
- **Os logs exploratórios foram vistos antes do commit do pré-registro.** A R0b mostra que as diferenças para eles vêm só das correções da 16.4.
- **2020-22 sem aquecimento no R1c** (o cache congelado não cobre 220 + 91 dias). A seção 8 mostra o efeito de um aquecimento parcial.
- **Wilcoxon com zeros usa aproximação normal** (com o ajuste de Pratt); como vale o maior p entre Wilcoxon e t, isso não afrouxa a decisão.
- **Poder do par G1 × T1 muito abaixo do suposto.** A 12.4 contava com erro-padrão de ≈ 1,04 pt por bloco (σ_par sintética de 10,2 pts/ano); o observado foi 6,95 pt, e o σ_par por bootstrap do R2 (BTC+ETH) deu 34,5 pts/ano. O "Inconclusivo" da H3 é, em boa parte, falta de poder: a diferença se concentra em poucas janelas de alta forte, e 24 blocos não bastam para separá-la do acaso.
- **Uma nota de leitura foi escrita depois de ver os números** (convenção 3: réguas discordantes numa unilateral que já é "Sem evidência de vantagem"). Ela só afeta a H2, que sairia "Inconclusivo" pela frase da 12.4 e sai "Sem evidência de vantagem" pela tabela da 12.5; as duas respostas dizem que não há vantagem demonstrada.
- O backtest **não decide** se a carteira vai ao ar (12.5). Decide o que se pode dizer sobre cada uma.

