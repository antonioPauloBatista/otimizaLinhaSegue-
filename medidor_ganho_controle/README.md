# Medidor de Ganho Real do Controle V4 (`medidor_ganho_controle`)

Ferramenta de diagnóstico industrial e auditoria em tempo real (via **Grafana/InfluxDB**) ou offline (**CSVs**) para responder de forma objetiva se o **Controle V4 (Segue)** está entregando mais garrafas e qual é o ganho real (ou oportunidade perdida quando desligado) em garrafas físicas (`gf`) e garrafas por hora (`CPH`).

---

## 1. Visão Geral

O medidor analisa a operação em quatro cenários complementares:

1. **`🟢 Segue On` vs Referência `Segue Off` (Ganho Real / Confronto A/B):**
   Compara a velocidade real da enchedora com o Segue ligado contra a média ativa sem o Segue (histórico `Segue Off` dentro da janela ou arquivo/coluna de referência sem controle), indicando diretamente se **vale a pena manter habilitado**.
2. **`🔴 Segue Off` (Custo de Oportunidade / Modo Sombra):**
   Quando o Segue está desligado, compara a velocidade real (`Vatual`) com o setpoint calculado em sombra pelo Controlador V4 (`V Controlador`), medindo quantas garrafas estão deixando de ser produzidas por não utilizar o controle.
3. **Monitoramento Contínuo em Tempo Real (`--online-grafana` / `--online`):**
   Acompanha a linha em ciclos configuráveis (`tempo_atualizacao_segundos`, padrão `5.0s`), mantendo somente os acumuladores da **Hora Atual (`🕒 HHh`)** e **Desde Início / Desde HH:MM (`🚀` / `🟢`)**.
4. **Relatório Consolidado e Raio-X de Auditoria ao Pressionar `Ctrl+C`:**
   Ao interromper o monitoramento ao vivo (ou ao finalizar uma execução em lote com CSV), imprime automaticamente o resumo da sessão e a auditoria completa de filtros, velocidades ativas e desempenho por motivo do controlador.

---

## 2. Estrutura da Pasta

- `medir_ganho.py`: motor principal de cálculo, coleta incremental no Grafana, exibição em tempo real, leitura de CSVs em lote e emissão dos relatórios de auditoria.
- `cliente_grafana.py`: cliente HTTP resiliente para Grafana (`InfluxQL proxy` e `/api/ds/query`), autenticação por usuário/senha ou token e busca paginada por hora.
- `config_medidor.json`: arquivo de configuração padrão contendo credenciais de acesso ao Grafana, nomes das colunas de telemetria e parâmetros de filtro e cálculo.
- `README.md`: documentação completa de operação, legendas, parâmetros e auditoria.

---

## 3. Regras de Cálculo, Filtros e Coleta

### 3.1. Filtro de Trava de Entrada (`trava_filtro` / `--trava`)

O filtro `trava_filtro` define quais amostras entram na acumulação de garrafas e médias — sempre mantendo **somente o que está dentro do valor configurado**:

| Valor | Significado | Exibição na Linha | Efeito no Acumulador |
| :--- | :--- | :--- | :--- |
| `"1"` *(padrão)* | **Trava Aberta / Fluxo Livre** (`Trava == 1`) | `🔓 T:1(Aberta)` | Acumula somente quando a entrada está liberada (`T=1`). Quando fecha (`T=0`), pausa a soma e exibe `⏸️ Trava Fechada (acumula só c/ T:1 Aberta)`. |
| `"0"` | **Trava Fechada / Bloqueada** (`Trava == 0`) | `🔒 T:0(Fechada)` | Acumula somente amostras em `T=0`. |
| `"all"` | **Todas as condições** (`0` e `1`) | `🔓 T:1(Aberta)` / `🔒 T:0(Fechada)` | Todas as amostras entram no cálculo sem filtragem de trava. |

> **Importante:** mesmo quando uma amostra está fora do filtro (por exemplo, máquina fechada em `T:0` enquanto `trava_filtro` é `"1"`), a linha ao vivo continua sendo impressa para mostrar o estado instantâneo da máquina, porém o acumulador permanece congelado (`+0`) até a trava voltar para a condição configurada.

### 3.2. Corte de Velocidade de Parada (`velocidade_parada_cph` / `--velocidade-parada` / `--limiar-parada`)

Define o limite mínimo em **CPH** abaixo ou igual ao qual a enchedora é considerada em **parada física ou baixa velocidade improdutiva** (padrão `1000.0` CPH, ajustável para faixas operacionais como `16000.0` ou `50000.0` CPH):

- **Classificação:** toda amostra com `Vatual <= velocidade_parada_cph` é sinalizada com `🛑 PARADA`.
- **Delta zerado (`0 gf`):** o ganho ou perda daquela amostra é zerado antes da soma, evitando que paradas mecânicas contem como "culpa" ou "crédito" artificial do controlador.
- **Médias somente com máquina rodando (`> velocidade_parada_cph`):** as médias e medianas de `Vatual`, `V Controlador` e `Referência Segue Off` são calculadas exclusivamente sobre amostras ativas acima do corte.

### 3.3. Acumulador Amostra a Amostra e Veredito

A cadência base entre amostras (`dt_ciclo` em segundos, estimada pela moda dos intervalos reais de timestamp, com fallback de `10.0s`) determina o peso temporal de cada amostra em horas (`dt_h = dt_ciclo / 3600.0`):

- **Cenário `🟢 Segue On` (Confronto A/B ou vs coluna Sem Controle):**
  - `Delta (CPH) = Vatual - Referencia_Segue_Off`
  - `Ganho da Amostra (gf) = Delta (CPH) * dt_h` (somente onde `Vatual > velocidade_parada_cph`)
  - Se o saldo líquido for positivo ou zero, exibe `✅ Vale a pena`; se negativo, exibe `⚠️ Abaixo do OFF`.
- **Cenário `🔴 Segue Off` (Custo de Oportunidade / Modo Sombra):**
  - `Oportunidade (CPH) = V_Controlador - Vatual`
  - `Saldo da Amostra (gf) = Oportunidade (CPH) * dt_h` (somente onde `Vatual > velocidade_parada_cph`)
  - Quando `V_Controlador > Vatual`, indica perda por operar sem o controle (`🔻 Sem Segue: -X gf`); quando `Vatual > V_Controlador`, indica operação acima do setpoint calculado (`🟢 Acima SP V4 +X gf`).

### 3.4. Busca Histórica Paginada de 1 em 1 Hora (`janela_historico` / `--janela`)

Ao carregar uma janela histórica maior que 1 hora (ex.: `24h`, `48h`, `2d`), tanto `buscar_dados_grafana_resiliente` (`medir_ganho.py`) quanto `ClienteGrafana.buscar_dados` (`cliente_grafana.py`) **dividem a consulta sequencialmente em blocos de 1 em 1 hora** (`WHERE time >= now() - 24h AND time < now() - 23h`, e assim sucessivamente até `now() - 1h`) com uma pausa de `0.05s` entre blocos:

- Evita sobrecarga de memória, travamentos e timeouts no Grafana/InfluxDB.
- Caso o filtro temporal relativo não retorne dados (ex.: diferença de fuso horário entre servidor e máquina local), entra automaticamente em fallback paginado por lotes de `400` registros (`SELECT * FROM ... ORDER BY time DESC LIMIT 400 OFFSET ...`).
- Depois da carga inicial, o loop online passa a buscar apenas os pontos recentes em ciclos definidos por `tempo_atualizacao_segundos` e concatena somente timestamps inéditos.

### 3.5. Tempo de Atualização Configurável (`tempo_atualizacao_segundos`)

No monitoramento contínuo (`--online-grafana`), o intervalo de espera entre consultas é controlado por `"tempo_atualizacao_segundos"` no `config_medidor.json` (padrão `5.0` segundos) ou pela linha de comando via `--tempo-atualizacao` / `--intervalo`.

---

## 4. Configuração (`config_medidor.json`)

O script carrega automaticamente `config_medidor.json` se estiver na mesma pasta (ou outro arquivo informado em `--config`). Argumentos passados pela linha de comando sempre têm prioridade sobre os valores do JSON.

```json
{
  "modo": "online-grafana",

  "dados_grafana": {
    "url": "http://10.186.99.7:3000",
    "user": "admin",
    "password": "!ambev2021",
    "datasource": "4",
    "bucket": "soda",
    "measurement": "512_v4",
    "coluna_velocidade_real": "v_atual_cph",
    "coluna_trava_entrada": "trava_entrada_int",
    "coluna_segue_habilitado": "segue_habilitado",
    "coluna_buffer_entrada_b2": "b2_pct",
    "coluna_buffer_saida_b3": "b3_pct"
  },

  "dados_calculo_analises": {
    "trava_filtro": "1",
    "janela_historico": "24h",
    "tempo_atualizacao_segundos": 5.0,
    "velocidade_parada_cph": 1000.0,
    "limiar_buffer_saida_gargalo_pct": 74.37,
    "limiar_buffer_entrada_min_pct": 30.05
  }
}
```

### Detalhamento das Chaves do JSON

| Seção / Chave | Padrão no Código | Descrição |
| :--- | :--- | :--- |
| `modo` | `""` | Se `"online-grafana"` (sem CSV informado), inicia diretamente conectado ao Grafana. Aceita também `"listar-colunas"` / `"inspecionar"`. |
| `dados_grafana.url` | `"http://10.46.12.163:3000"` | URL base do servidor Grafana. |
| `dados_grafana.user` / `password` / `token` | `"admin"` / `"!ambev2021"` / `""` | Credenciais de acesso (usuário/senha ou Service Account Token). |
| `dados_grafana.datasource` | `"17"` | ID numérico ou nome do Data Source InfluxDB no Grafana. |
| `dados_grafana.bucket` | `"Segue"` | Database/Bucket do InfluxDB. |
| `dados_grafana.measurement` | `"512_v4"` | Measurement (linha/tabela) consultada no InfluxDB. |
| `dados_grafana.org` *(opcional)* | `"ABinbev"` | Organização do InfluxDB (se aplicável). |
| `dados_grafana.coluna_velocidade_real` | `"v_atual_cph"` | Coluna da velocidade real da enchedora (CPH). |
| `dados_grafana.coluna_trava_entrada` | `"trava_entrada_int"` | Coluna do sinal de trava de entrada (`1` = Aberta, `0` = Fechada). |
| `dados_grafana.coluna_segue_habilitado` | `"segue_habilitado"` | Coluna booleana/inteira que indica se o Controle Segue está ligado (`1`/`True`) ou desligado (`0`/`False`). |
| `dados_grafana.coluna_buffer_entrada_b2` | `"b2_pct"` | Coluna do nível (%) do pulmão/buffer de entrada B2. |
| `dados_grafana.coluna_buffer_saida_b3` | `"b3_pct"` | Coluna do nível (%) do pulmão/buffer de saída B3. |
| `dados_grafana.coluna_velocidade_v4` *(opcional)* | `"v_setpoint_cph"` | Coluna com o setpoint recomendado pelo controlador V4 (`V Controlador`). |
| `dados_grafana.coluna_velocidade_sem_controle` *(opcional)* | `"velocidade_maquina_sem_controle_cph"` | Coluna com referência de velocidade sem controle, quando disponível. |
| `dados_calculo_analises.trava_filtro` | `"1"` | Filtro da trava para acumulação: `"1"` (aberta), `"0"` (fechada) ou `"all"`. |
| `dados_calculo_analises.janela_historico` | `"24h"` | Janela de histórico carregada na partida (`1h`, `24h`, `48h`, `2d`, etc.). |
| `dados_calculo_analises.tempo_atualizacao_segundos` | `5.0` | Intervalo em segundos entre consultas no modo tempo real. |
| `dados_calculo_analises.velocidade_parada_cph` | `1000.0` | Velocidade (CPH) abaixo ou igual à qual a máquina é tratada como `PARADA`. |
| `dados_calculo_analises.limiar_buffer_saida_gargalo_pct` | `74.37` | Limiar (%) do buffer B3 para caracterizar gargalo de saída na análise. |
| `dados_calculo_analises.limiar_buffer_entrada_min_pct` | `30.05` | Limiar (%) mínimo de B2 exigido na prova sob gargalo. |
| `dados_calculo_analises.limiar_rastejo_cph` *(opcional)* | `20000.0` | Limiar (CPH) abaixo do qual é contabilizado tempo de lentidão/rastejo nos relatórios. |
| `dados_calculo_analises.horas_turno_projecao` *(opcional)* | `8.0` | Quantidade de horas usada para projetar o ganho/perda por turno. |

---

## 5. Guia Completo das Legendas da Linha em Tempo Real

Cada novo registro válido exibido no terminal apresenta uma linha resumida e padronizada. Veja exemplos reais para cada estado:

**Com `Segue Off` (avaliando custo de oportunidade vs setpoint V4) e trava aberta:**
```text
[17:49:44] 🔴 Segue Off | 🔓 T:1(Aberta) | Vatual: 43,446 (V Controlador: 76,500) | 🕒 17h: 🔻 Sem Segue: -2,796 gf (-45,746 CPH) | 🚀 Desde Início: 🔻 Sem Segue: -2,796 gf (-45,746 CPH | Oport. V4: +142.2%) | Am:22 (+1)
```

**Com `Segue On` e histórico `Segue Off` disponível (ganho real A/B):**
```text
[18:12:30] 🟢 Segue On | 🔓 T:1(Aberta) | Vatual: 78,200 (V Controlador: 80,000 | OFF: 64,500) | 🕒 18h: 🟢 Segue Ganhando +1,142 gf (+13,700 CPH) | 🟢 Desde 18:05: 🟢 Segue Ganhando +2,283 gf (+13,700 CPH | +21.2%) ✅ Vale a pena | Am:184 (+1)
```

**Com máquina parada (`Vatual <= velocidade_parada_cph`) e trava fechada fora do filtro `trava_filtro = "1"`:**
```text
[17:52:10] 🛑 PARADA | 🔴 Segue Off | 🔒 T:0(Fechada) | Vatual: 0 (V Controlador: 76,500) | 🕒 17h: 🔻 Sem Segue: -2,796 gf (-45,746 CPH) | 🚀 Desde Início: 🔻 Sem Segue: -2,796 gf (-45,746 CPH | Oport. V4: +142.2%) | Am:22/363 (+0) | ⏸️ Trava Fechada (acumula só c/ T:1 Aberta)
```

### Tabela de Significado das Legendas

| Elemento da Linha | Significado |
| :--- | :--- |
| `[HH:MM:SS]` | Horário local da amostra mais recente recebida do Grafana/CSV. |
| `🛑 PARADA` | Exibido no início da linha quando `Vatual <= velocidade_parada_cph`. O delta dessa amostra é zerado e ela não entra nas médias de velocidade rodando. |
| `🟢 Segue On` / `🔴 Segue Off` | Estado instantâneo da tag `segue_habilitado` (`1`/ligado vs `0`/desligado). |
| `🔓 T:1(Aberta)` / `🔒 T:0(Fechada)` | Estado instantâneo da tag `trava_entrada_int` (`1` = aberta/fluxo livre; `0` = fechada/bloqueada). |
| `Vatual: X` | Velocidade física instantânea medida na enchedora (CPH). |
| `V Controlador: Y` | Setpoint calculado em CPH pelo Controlador V4 para o instante atual (mesmo com o Segue desligado, em modo sombra). |
| `OFF: Z` | Aparece ao lado de `V Controlador` quando `Segue On` possui histórico `Segue Off` válido na base: representa a média de velocidade ativa sem o Segue usada no confronto A/B. |
| `🕒 HHh:` | Acumulado restrito à **hora fechada atual** (ex.: `🕒 17h:` acumula apenas de `17:00:00` em diante). Mostra garrafas (`gf`) e diferença média (`CPH`). |
| `🚀 Desde Início:` / `🟢 Desde HH:MM:` | **Segundo acumulador (visão ampla):** com `Segue Off`, mostra `🚀 Desde Início:` acumulado na janela toda; quando o Segue é ligado (`Segue On`), muda para `🟢 Desde HH:MM:` contando a partir da hora em que o Segue foi habilitado e inclui percentual mais veredito (`✅ Vale a pena` ou `⚠️ Abaixo do OFF`). |
| `Am:Válidas/Total (+Novas)` | Contagem de amostras. Se o filtro de trava estiver restringindo a amostra atual, mostra `Válidas/Total (+0)`. Quando aceita pela trava, mostra `Am:Válidas (+Novas)`. |
| `⏸️ Trava Fechada (acumula só c/ T:1 Aberta)` | Aviso exibido quando `trava_filtro = "1"` e a amostra atual veio com `T=0`, indicando que os acumuladores foram preservados sem alteração. |

---

## 6. Relatório e Auditoria ao Pressionar `Ctrl+C` (ou Fim de Batch)

Ao pressionar **`Ctrl+C`** durante `--online-grafana` (ou `--online`), a execução encerra a conexão com segurança e consolida automaticamente os quadros abaixo — os mesmos exibidos na partida do streaming e ao final do processamento batch de CSV:

1. **`RESUMO DA SESSÃO ONLINE GRAFANA (LINHA <measurement>) - ÚLTIMAS 24H`:**
   Balanço geral nas últimas 24h filtradas pela trava, trazendo `Ritmo Médio da Linha` (`CPH`), `GANHO TOTAL ENTREGUE` ou `PERDA POR SEGUE OFF`, impacto projetado no turno (`8h`), `💡 VEREDITO SEGUE`, `Paradas` e `Rastejo`.
2. **`🕒 HORA ATUAL (...)` e `🟢 DA HORA LIGADA PARA FRENTE (...)`:**
   Quadros individuais com o recorte específico da hora corrente e do intervalo contínuo após o Segue ser ligado.
3. **`🔍 AUDITORIA DA ANÁLISE (RAIO-X PARA VERIFICAÇÃO)`:**
   Quadro criado especificamente para permitir a auditoria passo a passo dos números apurados, dividido em três blocos:
   - **`📋 1. FUNIL DE AMOSTRAS E FILTROS`:** mostra quantas amostras brutas chegaram, quantas passaram na trava (`Ignoradas p/ trava`), quantas ficaram com máquina rodando ativa (`Entraram na soma`) vs paradas zeradas (`Zeradas`), e quantas pertencem a `Segue On` e `Segue Off`.
   - **`📊 2. BALANÇO E VELOCIDADES (SOMENTE AMOSTRAS RODANDO)`:** exibe média, mediana e máximo de `Vatual`, média de `V Controlador`, `Referência Segue Off`, produção real vs base esperada no mesmo tempo ativo, saldo líquido, médias de `B2 Entrada` / `B3 Saída` e a linha **`💡 CONCLUSÃO`**.
   - **`🔍 3. RAIO-X POR MOTIVO DO CONTROLADOR`:** detalha amostras, minutos, `Vat`, `VCtrl`, saldo (`gf` e `CPH`) e buffers médios (`B2`/`B3`) agrupados por motivo (`motivo_codigo` ou `status_modulacao`, quando a coluna existir nos dados — por exemplo `NORMAL_FULL`, `SPRINT_SOBREVELOCIDADE`, `ACUMULO_SAIDA_B3`, `FALTA_ENTRADA_B2`, `MAQUINA_SAIDA_LENTA`, `RETOMADA_ACELERANDO_SAIDA`, `CONFLITO_ENTRADA_SAIDA`).

### Exemplo Visual do Relatório Consolidado de Auditoria (`Ctrl+C`)

```text
══════════════════════════════════════════════════════════════════════
  RESUMO DA SESSÃO ONLINE GRAFANA (LINHA 512_v4) - ÚLTIMAS 24H [TRAVA == 1 (TRAVA ABERTA / FLUXO LIVRE)]
══════════════════════════════════════════════════════════════════════
 Tempo Analisado : 1.85 h COM controle (666 amostras) vs 4.20 h SEM controle (1512 amostras)
──────────────────────────────────────────────────────────────────────
 ✅ RESULTADO: LINHA GANHANDO PRODUÇÃO COM SEGUE LIGADO
 🏆 GANHO TOTAL ENTREGUE   : +18,450 GARRAFAS A MAIS (+15.42%)
 ⚡ Ritmo Médio da Linha   : Foi de 64,500 para 74,473 garrafas/hora (+9,973 CPH)
 📦 Impacto no Turno (8h)  : +79,784 garrafas por turno
 💡 VEREDITO SEGUE         : ✅ VALE A PENA MANTER HABILITADO (saldo positivo vs operação sem Segue)
══════════════════════════════════════════════════════════════════════

══════════════════════════════════════════════════════════════════════
                 🔍 AUDITORIA DA ANÁLISE (RAIO-X PARA VERIFICAÇÃO)
══════════════════════════════════════════════════════════════════════
 • Período Analisado     : 18/11/2026 11:00:00 -> 18/11/2026 17:55:00 (cadência: ~10.0s)
 • Filtro de Trava       : Trava Aberta / Fluxo Livre (Trava == 1)
 • Corte de Parada       : <= 1,000 CPH (rastejo < 20,000 CPH)
──────────────────────────────────────────────────────────────────────
 📋 1. FUNIL DE AMOSTRAS E FILTROS:
 • Amostras Lidas (Bruto): 2500 (6.94 h)
 • Passaram na Trava     : 2178 (6.05 h) | Ignoradas p/ trava: 322
 • Máquina Rodando (Ativo): 2100 (5.83 h) [Entraram na soma] | Paradas: 78 (0.22 h) [Zeradas]
 • Segue no Filtro       : Segue On: 666 (650 rodando) | Segue Off: 1512 (1450 rodando)
──────────────────────────────────────────────────────────────────────
 📊 2. BALANÇO E VELOCIDADES (SOMENTE AMOSTRAS RODANDO):
 • Vatual (Rodando)      : Média: 71,240 CPH | Mediana: 73,500 CPH | Máx: 84,000 CPH
 • V Controlador (Média) : 76,800 CPH
 • Referência Segue Off  : 64,500 CPH (1450 amostras rodando)
 • Produção Segue On     : Real: 138,420 gf | Base OFF no mesmo tempo: 116,458 gf
 • Saldo Líquido         : 🟢 Segue Ganhando +21,962 gf (+12,163 CPH | +18.86%)
 • Buffers Médios (Ativo): B2 Entrada: 62.4% | B3 Saída: 48.1%
 • 💡 CONCLUSÃO          : ✅ VALE A PENA MANTER HABILITADO (+21,962 gf reais | +97,304 gf/turno 8h)
──────────────────────────────────────────────────────────────────────
 🔍 3. RAIO-X POR MOTIVO DO CONTROLADOR (Segue On vs OFF):
   • NORMAL_FULL               |  410am ( 68.3m) | Vat:76,400 | VCtrl:78,000 | +13,553 gf (+11,900 CPH) | B2:68% B3:41%
   • SPRINT_SOBREVELOCIDADE    |  150am ( 25.0m) | Vat:81,200 | VCtrl:82,500 | +6,958 gf (+16,700 CPH) | B2:82% B3:35%
   • ACUMULO_SAIDA_B3          |   90am ( 15.0m) | Vat:62,100 | VCtrl:62,000 | -600 gf (-2,400 CPH) | B2:51% B3:79%
══════════════════════════════════════════════════════════════════════
```

*(Nota: se os dados não possuírem a coluna `motivo_codigo` ou `status_modulacao`, o relatório exibe normalmente os Blocos 1 e 2 e omite o Bloco 3).*

---

## 7. Como Executar (Modos de Operação)

Execute a partir da raiz do projeto utilizando o ambiente virtual `.venv/bin/python`:

### 7.1. Modo Tempo Real Direto do Grafana (Recomendado)

Usa automaticamente as configurações de `medidor_ganho_controle/config_medidor.json`:

```bash
.venv/bin/python medidor_ganho_controle/medir_ganho.py --online-grafana
```

Exemplos sobrescrevendo janela, corte de parada e tempo de atualização pela linha de comando:

```bash
# Buscar 24h de hora em hora, atualizar a cada 5s, parada <= 16000 CPH e acumular só com Trava Aberta (1)
.venv/bin/python medidor_ganho_controle/medir_ganho.py \
  --online-grafana \
  --janela 24h \
  --tempo-atualizacao 5 \
  --velocidade-parada 16000 \
  --trava 1
```

Para encerrar e visualizar o relatório completo de auditoria, pressione `Ctrl+C`.

### 7.2. Modo Streaming de Arquivo CSV Local (`--online`)

Monitora um arquivo CSV sendo gravado em tempo real e emite o relatório consolidado ao pressionar `Ctrl+C`:

```bash
.venv/bin/python medidor_ganho_controle/medir_ganho.py dados_linha.csv --online --intervalo 5 --trava 1 --velocidade-parada 16000
```

### 7.3. Modo Batch em Arquivo(s) CSV Exportado(s)

**CSV único** (separa automaticamente `Segue On` e `Segue Off`, ou roda Modo Sombra se tiver apenas um estado):

```bash
.venv/bin/python medidor_ganho_controle/medir_ganho.py "Panel Title-data-2026-11-17 17_35_46.csv" --trava 1 --velocidade-parada 50000
```

**Dois CSVs** (arquivo principal `COM` controle vs arquivo explícito `SEM` controle):

```bash
.venv/bin/python medidor_ganho_controle/medir_ganho.py dados_com_segue.csv --csv-sem-controle dados_sem_segue.csv --trava 1
```

### 7.4. Inspeção de Colunas (`--listar-colunas` / `-l`)

Inspeciona as colunas disponíveis no InfluxDB/Grafana ou em um CSV e mostra como elas são mapeadas para velocidade, trava, Segue habilitado, B2 e B3:

```bash
.venv/bin/python medidor_ganho_controle/medir_ganho.py --listar-colunas
.venv/bin/python medidor_ganho_controle/medir_ganho.py dados_linha.csv --listar-colunas
```

---

## 8. Tabela Completa de Parâmetros CLI (`medir_ganho.py`)

| Argumento CLI | Tipo | Padrão | Descrição |
| :--- | :--- | :--- | :--- |
| `csv` *(posicional opcional)* | Caminho | `None` | Arquivo CSV de telemetria para análise em lote ou streaming local (`--online`). |
| `--config` | Caminho | `config_medidor.json` | Arquivo JSON de configuração alternativo. |
| `--csv-sem-controle` | Caminho | `None` | Segundo arquivo CSV de referência com o Segue desligado para confronto A/B. |
| `--trava` | String | `"1"` *(ou JSON)* | Filtro de trava de entrada: `"1"` (aberta / fluxo livre), `"0"` (fechada / bloqueada) ou `"all"`. |
| `--velocidade-parada`, `--limiar-parada` | Float | `1000.0` *(ou JSON)* | Velocidade em CPH abaixo ou igual à qual a máquina é considerada em `PARADA` (zera delta e sai das médias ativas). |
| `--online` | Flag | `False` | Executa monitoramento streaming acompanhando atualizações de um CSV local. |
| `--intervalo`, `--tempo-atualizacao` | Float | `5.0` *(ou JSON)* | Tempo de atualização em segundos entre consultas no modo tempo real. |
| `--listar-colunas`, `-l` | Flag | `False` | Lista as colunas disponíveis no Grafana/InfluxDB ou CSV antes de executar cálculos. |
| `--online-grafana` | Flag | `False` | Conecta diretamente à API do Grafana/InfluxDB em tempo real sem depender de CSV. |
| `--url` | String | JSON | URL base do Grafana. |
| `--user` | String | JSON | Usuário do Grafana. |
| `--password` | String | JSON | Senha do Grafana. |
| `--token` | String | `""` *(ou JSON)* | Service Account Token do Grafana. |
| `--ds` | String | JSON | Nome ou ID do Data Source InfluxDB no Grafana. |
| `--bucket` | String | JSON | Bucket/Database do InfluxDB. |
| `--measurement` | String | JSON | Nome da measurement (tabela/linha) no InfluxDB (ex.: `512_v4`, `512`, `501`). |
| `--org` | String | `"ABinbev"` *(ou JSON)* | Organização do InfluxDB. |
| `--janela` | String | `"24h"` *(ou JSON)* | Janela inicial de histórico carregada na partida (`1h`, `4h`, `24h`, `48h`, etc.). |
