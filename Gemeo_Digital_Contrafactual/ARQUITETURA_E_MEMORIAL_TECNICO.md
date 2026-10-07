# Memorial Técnico e Arquitetura do Gêmeo Digital Contrafactual (Pré-V4)

Este documento descreve a fundamentação teórica, a modelagem matemática e a arquitetura de engenharia do sistema **Gêmeo Digital Contrafactual da Linha Legada**, implementado no diretório `Gemeo_Digital_Contrafactual`.

---

## 1. O Problema Contrafactual na Validação de Controle Avançado (APC)

Quando um algoritmo avançado de controle (como o Controlador V4) assume a operação de uma máquina mestra (Enchedora), ele altera a dinâmica de toda a linha:
1. Em vez de permitir que o buffer de saída encha até 85%, o V4 modula preventivamente para 75% da velocidade nominal, mantendo a esteira em faixa de equilíbrio (ex: 50% a 70%).
2. Como resultado, o sensor físico real de bloqueio nunca bate 85%.
3. **O Paradoxo:** Se uma auditoria avaliar o CLP legado olhando apenas os sensores reais de esteira, concluirá erroneamente que o CLP antigo "nunca iria parar", pois o V4 manteve a esteira desobstruída.

Não é possível realizar um teste A/B físico simultâneo na mesma máquina de envase. Por isso, a engenharia desenvolveu o **Gêmeo Digital Contrafactual (Digital Shadow em Malha Fechada)**: ele reconstrói ciclo a ciclo o nível que os buffers teriam atingido sob a política antiga, aplicando os mesmos distúrbios operacionais reais das máquinas vizinhas (Despaletizadora e Pasteurizador).

---

## 2. O Uso dos Sensores Discretos de Fotocélula vs. Buffer Virtual

Na fábrica real, o CLP legado tipicamente **não operava lendo percentual analógico de esteira**. Os painéis elétricos tradicionais atuam com **fotocélulas digitais discretas** (sinal booleano 0 ou 1):
* **Fotocélula de Acúmulo na Descarga da Enchedora:** Sensor ótico no início de B3 que detecta se há garrafas travadas na estrela de saída.
* **Fotocélula de Falta na Alimentação da Enchedora:** Sensor ótico no final de B2 que detecta se faltam garrafas para abastecer o carrossel.
* **Temporizador TON (Timer On-Delay):** O CLP antigo filtrava o sinal da fotocélula exigindo que ela permanecesse bloqueada (ou vazia) continuamente por 1.5s a 2.0s antes de derrubar o comando de marcha.

### Como o Gêmeo Digital Unifica os Sensores e o Buffer:
O modelo contrafactual opera em **modo dual integrado (híbrido)**:
1. **Bloqueio por Saída Cheia (B3):**
   * Condição: `B3_virtual >= 85%` **OU** `Sensor_Acumulo_TON == True`
   * Se o sensor físico da fotocélula de acúmulo na esteira acusar garrafas presas por mais de 2.0s, o modelo derruba a velocidade para zero imediatamente, mesmo que o buffer virtual ainda não tenha atingido 85%.
2. **Retomada por Saída Aliviada:**
   * Condição: `B3_virtual <= 65%` **E** `Sensor_Acumulo == False` (fotocélula desobstruída).
3. **Bloqueio por Falta de Entrada (B2):**
   * Condição: `B2_virtual <= 15%` **OU** `Sensor_Falta_TON == True`
4. **Retomada por Entrada Reabastecida:**
   * Condição: `B2_virtual >= 35%` **E** `Sensor_Falta == False`.

Essa arquitetura garante fidelidade de 93% a 98% com a mecânica do chão de fábrica.

---

## 3. Arquitetura em 3 Blocos de Engenharia

### Bloco 1: Dinâmica Contínua (Balanço de Massa dos Buffers Virtuais)
O acúmulo de recipientes em uma esteira transportadora industrial é governado pelo princípio de conservação de massa:

* **Buffer de Entrada B2 (DPL/ECI -> Enchedora):**
  * Variacao_Garrafas_B2 = (v_in - v_legado) * (Delta_t / 3600)
  * Delta_Percentual_B2 = (Variacao_Garrafas_B2 / Capacidade_B2) * 100%
  * B2_virtual(t) = clip(B2_virtual(t-1) + Delta_Percentual_B2, 0.0%, 100.0%)

* **Buffer de Saída B3 (Enchedora -> Pasteurizador):**
  * Variacao_Garrafas_B3 = (v_legado - v_out) * (Delta_t / 3600)
  * Delta_Percentual_B3 = (Variacao_Garrafas_B3 / Capacidade_B3) * 100%
  * B3_virtual(t) = clip(B3_virtual(t-1) + Delta_Percentual_B3, 0.0%, 100.0%)

* **Autocalibração de Capacidade (Cap):**
  * Capacidade = [ (v_ench - v_past) * (Delta_t / 3600) ] / (Delta_B_pct / 100)
  * Avaliado em intervalos onde o Pasteurizador estava parado (v_past == 0) e a enchedora rodando em velocidade estável.

---

### Bloco 2: Dinâmica Discreta (Autômato Finito do CLP Legado)
* **Rampa Mecânica do Inversor Legado (Slew Rate):**
  O inversor de frequência antigo não alcançava a nominal instantaneamente. O modelo aplica a taxa física de rampa:
  * Taxa de Subida = Velocidade Nominal / Tempo_Rampa_Subida_s (ex: 90.000 CPH / 15s = 6.000 CPH/s).
  * Degrau Máximo de Subida = Taxa de Subida * Delta_t.
  * v_legado(t) = min(v_alvo, v_legado(t-1) + Degrau Máximo de Subida).

---

### Bloco 3: Ancoragem Determinística PackML (Cancelamento de Drift)
* **Gatilho de Ancoragem:**
  * Ocorrência de falha intrínseca da máquina física (tag OPC `status_maquina == False` ou código PackML de parada própria).
  * OU parada contínua da máquina real física (velocidade real < 1.000 CPH) por mais de 5 minutos (300 segundos).
* **Ação Determinística:**
  1. Força v_legado = 0 CPH.
  2. Estado = PARADA_FALHA_REAL.
  3. Reseta instantaneamente: B2_virtual = B2_real e B3_virtual = B3_real.
  4. Zera temporizadores TON.
* **Justificativa de Auditoria:**
  Durante almoço, manutenção mecânica corretiva, falta de cerveja na adega ou quebra de garrafas no carrossel, **nenhum algoritmo ganha ou perde volume**. A ancoragem garante que o saldo de OEE reflita estritamente ganhos dinâmicos de fluxo de esteira.

---

## 4. Auditoria de Ganhos e Fórmulas de OEE

1. **Volume Físico Incremental (Garrafas):**
   Delta_Garrafas = Soma( (v_real - v_legado) * (Delta_t / 3600) )

2. **Volume Incremental em Hectolitros (hL):**
   Delta_hl = (Delta_Garrafas * Volume_Garrafa_Litros) / 100

3. **Ganho Real de OEE (%):**
   Capacidade_Teorica = Velocidade_Nominal * (Tempo_Total_Horas)
   Delta_OEE = (Delta_Garrafas / Capacidade_Teorica) * 100%

4. **Contagem de Microparadas Evitadas (< 3 minutos):**
   Blocos contínuos onde a enchedora real com V4 permaneceu rodando (v_real >= 10.000 CPH) enquanto o CLP legado estaria cortado em zero (v_legado < 1.000 CPH) por intertravamento de esteira.
