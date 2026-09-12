# Otimizador de Velocidade e Controlador Fuzzy (Takagi-Sugeno)

Este diretório contém a implementação do **Otimizador de Velocidade e Controlador Fuzzy** para gerenciamento inteligente de velocidade de linhas de envase / produção.

O sistema utiliza conceitos de **Lógica Fuzzy (Takagi-Sugeno de Ordem Zero)** e **Controle Feedforward** com base no nível dos pulmões (buffers de acúmulo) anteriores e posteriores à máquina principal (Enchedora/Filler), visando minimizar paradas bruscas ("socos"), maximizar a eficiência global (OEE) e suavizar as rampas de aceleração e desaceleração.

---

## 📁 Estrutura da Pasta e Arquivos

| Arquivo / Pasta | Descrição |
| :--- | :--- |
| [`otimizador_fuzzy.py`](file:///home/antonio/Projetos/OtimizadorSegue/Otimizador_Velocidade/otimizador_fuzzy.py) | Script de simulação e inferência Fuzzy Takagi-Sugeno baseada nos 4 buffers da linha. |
| [`otimizador_velocidade_v3.py`](file:///home/antonio/Projetos/OtimizadorSegue/Otimizador_Velocidade/otimizador_velocidade_v3.py) | Algoritmo de otimização de parâmetros de controle (ex: via CMA-ES / otimização heurística). |
| [`funcao_controle_v3.py`](file:///home/antonio/Projetos/OtimizadorSegue/Otimizador_Velocidade/funcao_controle_v3.py) | Função de controle compilada e otimizada que recebe os 4 níveis de pulmão e retorna o setpoint em CPH / %. |
| [`assistente_configuracao.py`](file:///home/antonio/Projetos/OtimizadorSegue/Otimizador_Velocidade/assistente_configuracao.py) | CLI interativo para gerar e validar o arquivo [`config_colunas.json`](file:///home/antonio/Projetos/OtimizadorSegue/Otimizador_Velocidade/config_colunas.json). |
| [`controlador_velocidade_live_v3.py`](file:///home/antonio/Projetos/OtimizadorSegue/Otimizador_Velocidade/controlador_velocidade_live_v3.py) | Módulo para execução/envio de setpoints em tempo real. |
| [`controlador_velocidade_grafana_v3.py`](file:///home/antonio/Projetos/OtimizadorSegue/Otimizador_Velocidade/controlador_velocidade_grafana_v3.py) | Integração com dados do Grafana / InfluxDB. |
| [`config_colunas.json`](file:///home/antonio/Projetos/OtimizadorSegue/Otimizador_Velocidade/config_colunas.json) | Arquivo de configuração de mapeamento de colunas CSV/Banco e limiares operacionais. |
| [`parametros_controle_v3.json`](file:///home/antonio/Projetos/OtimizadorSegue/Otimizador_Velocidade/parametros_controle_v3.json) | Parâmetros otimizados das funções de pertinência fuzzy e modulação. |

---

## ⚙️ Parâmetros do Arquivo `config_colunas.json`

O arquivo [`config_colunas.json`](file:///home/antonio/Projetos/OtimizadorSegue/Otimizador_Velocidade/config_colunas.json) mapeia as colunas de dados do processo (banco Grafana ou arquivo CSV) para a estrutura do otimizador:

```json
{
  "Col_Buffer_Antes_Entrada": "accumulation_percentage_pre_eci_null",
  "Col_Buffer_Entrada": "accumulation_percentage_eci_to_filler_null",
  "Col_Buffer_Saida": "accumulation_percentage_filler_to_pasteurizer_null",
  "Col_Buffer_Pos_Saida": "accumulation_percentage_post_pasteurizer_null",
  "COL_V_Antes_Entrada": "speed_actual_cph_null_first_upstream_machine_1",
  "COL_V_Entrada": "speed_actual_cph_null_eci_1",
  "Velocidade_Nominal_ECH": 60000,
  "COL_V_Saida": "speed_actual_cph_null_pasteurizer",
  "COL_V_Entrada_Pos_Saida": "speed_actual_cph_null_first_downstream_machine_1",
  "Filtro_Minutos_Parada_Longa": 10,
  "Fator_Sobremarcha": 1.01,
  "Limite_Parada_Falta": 10.0,
  "Limite_Parada_Acumulo": 85.2
}
```

### Detalhamento dos Campos de `config_colunas.json`:

| Campo | Tipo | Descrição |
| :--- | :--- | :--- |
| `Col_Buffer_Antes_Entrada` | String | Nome da coluna do buffer **$B_1$** (Pulmão extremo a montante/antes da entrada). *Opcional.* |
| `Col_Buffer_Entrada` | String | Nome da coluna do buffer **$B_2$** (Pulmão principal de entrada da Enchedora). |
| `Col_Buffer_Saida` | String | Nome da coluna do buffer **$B_3$** (Pulmão principal de saída da Enchedora). |
| `Col_Buffer_Pos_Saida` | String | Nome da coluna do buffer **$B_4$** (Pulmão extremo a jusante/pós-saída). *Opcional.* |
| `COL_V_Antes_Entrada` | String | Coluna com a velocidade real (CPH) da primeira máquina a montante. |
| `COL_V_Entrada` | String | Coluna com a velocidade real (CPH) da máquina imediatamente anterior à Enchedora (ex: ECI). |
| `COL_V_ECH` | String | Coluna(s) da velocidade da máquina principal (Enchedora/Filler). Suporta múltiplas colunas separadas por vírgula em paralelismo. |
| `Velocidade_Nominal_ECH` | Float/Int | Velocidade nominal de projeto da máquina principal em Garrafas ou Latas por Hora (CPH). Ex: `60000`. |
| `COL_V_Saida` | String | Coluna com a velocidade real (CPH) da máquina de saída (ex: Pasteurizador). |
| `COL_V_Entrada_Pos_Saida` | String | Coluna com a velocidade real (CPH) da primeira máquina pós-saída. |
| `Filtro_Minutos_Parada_Longa` | Int | Janela em minutos para identificação e tratamento de paradas mecânicas longas (ex: `10` min). |
| `Fator_Sobremarcha` | Float | Multiplicador de velocidade máxima aceitável em caso de sobremarcha (ex: `1.01` = +1%). |
| `Limite_Parada_Falta` | Float | Nível percentual do buffer de entrada abaixo do qual é considerada falta iminente (ex: `10.0%`). |
| `Limite_Parada_Acumulo` | Float | Nível percentual do buffer de saída acima do qual é considerado acúmulo iminente (ex: `85.2%`). |

---

## 🎛️ Parâmetros do Arquivo `parametros_controle_v3.json`

O arquivo [`parametros_controle_v3.json`](file:///home/antonio/Projetos/OtimizadorSegue/Otimizador_Velocidade/parametros_controle_v3.json) armazena as variáveis de ajuste fino do controlador fuzzy obtidas após o processo de otimização:

```json
{
  "b1_lim": 13.68,
  "b2_lim": 32.62,
  "b3_lim": 50.67,
  "b4_lim": 71.26,
  "rampa_b2": 37.87,
  "rampa_b3": 34.75,
  "antecipacao_b1": 10.11,
  "antecipacao_b4": 35.0,
  "fator_reducao": 0.607,
  "velocidade_nominal_calculada": 60000
}
```

### Detalhamento dos Campos de `parametros_controle_v3.json`:

| Parâmetro | Unidade | Descrição e Impacto no Controlador |
| :--- | :--- | :--- |
| `b2_lim` | `%` | **Limiar do Buffer de Entrada ($B_2$):** Se o nível de $B_2$ cai abaixo deste valor, o controlador inicia a desaceleração para evitar parada por falta de garrafas. |
| `b3_lim` | `%` | **Limiar do Buffer de Saída ($B_3$):** Se o nível de $B_3$ ultrapassa este valor, o controlador inicia a desaceleração para evitar travamento por acúmulo. |
| `b1_lim` | `%` | **Limiar Feedforward ($B_1$):** Limite de alerta no pulmão anterior à entrada. Níveis baixos ativam redução preventiva. |
| `b4_lim` | `%` | **Limiar Feedforward ($B_4$):** Limite de alerta no pulmão pós-saída. Níveis altos ativam redução preventiva. |
| `rampa_b2` | `%` | **Largura da Rampa Fuzzy Entrada ($B_2$):** Determina quão suave é a transição entre a velocidade nominal e a velocidade reduzida ao aproximar-se de `b2_lim`. |
| `rampa_b3` | `%` | **Largura da Rampa Fuzzy Saída ($B_3$):** Determina a suavidade da rampa de despressurização quando o buffer $B_3$ enche. |
| `antecipacao_b1` | `%` | **Amplitude de Antecipação $B_1$:** Extensão da rampa trapezoidal de pertinência para o sinal antecipado do buffer $B_1$. |
| `antecipacao_b4` | `%` | **Amplitude de Antecipação $B_4$:** Extensão da rampa trapezoidal de pertinência para o sinal antecipado do buffer $B_4$. |
| `fator_reducao` | Adimensional | **Piso Mínimo de Modulação (`min_modulacao`):** Proporção da velocidade nominal para a qual a máquina deve reduzir quando em condição crítica (ex: `0.607` = 60.7% da nominal). |
| `velocidade_nominal_calculada` | CPH | Velocidade nominal de referência adotada pelo modelo durante o cálculo. |

---

## 🧠 Arquitetura do Motor Fuzzy (Takagi-Sugeno)

O algoritmo fuzzy opera avaliando 4 posições de pulmão ao longo da linha:

$$\text{Buffer 1 } (B_1) \longrightarrow \text{Buffer 2 } (B_2) \longrightarrow [\text{ENCHEDORA / GARGANTO}] \longrightarrow \text{Buffer 3 } (B_3) \longrightarrow \text{Buffer 4 } (B_4)$$

### 1. Fuzzificação
As entradas numéricas de porcentagem de acúmulo ($0\%$ a $100\%$) são transformadas em graus de pertinência $[0, 1]$ usando funções trapezoidais / rampa:
* **Entrada Baixa / Normal** ($\mu_{B2}$)
* **Saída Normal / Alta** ($\mu_{B3}$)
* **Feedforward Extremo** ($\mu_{B1}$, $\mu_{B4}$)

### 2. Inferência e Regras de Controle
* **Regra 1 (Falta de Entrada):** Se $B_2$ é baixo $\rightarrow$ Velocidade Reduzida ($V_{\text{reduzida}}$).
* **Regra 2 (Acúmulo na Saída):** Se $B_3$ é alto $\rightarrow$ Velocidade Reduzida ($V_{\text{reduzida}}$).
* **Regra 3 (Condição Normal / Segura):** Se $B_2$ seguro e $B_3$ seguro $\rightarrow$ Velocidade Máxima / Nominal ($V_{\text{max}}$).
* **Regras Feedforward (Antecipação $B_1$/$B_4$):** Se $B_1$ em falta extrema ou $B_4$ em acúmulo extremo $\rightarrow$ Modula preventivemente antes que a oscilação atinja os buffers imediatos $B_2$/$B_3$.

### 3. Defuzzificação (Média Ponderada de Takagi-Sugeno)
$$\text{Setpoint Final (CPH)} = \frac{\sum_{i} w_i \cdot z_i}{\sum_{i} w_i}$$

Onde $w_i$ representa o peso/pertinência ativado por cada regra e $z_i$ o consequente de velocidade.

---

## 🚀 Como Executar

### 1. Configurar Mapeamento de Colunas
Para configurar interativamente as colunas e capacidades:
```bash
python assistente_configuracao.py
```

### 2. Executar Simulação Fuzzy Histórica
Para avaliar os ganhos potenciais em um arquivo de dados histórico (`dados_completos_fabrica.csv`):
```bash
python otimizador_fuzzy.py
```
*O script gerará o arquivo `dados_fuzzy_otimizado.csv` e gráficos dia a dia na pasta `graficos_fuzzy/`.*

### 3. Otimizar Parâmetros via Otimizador de Velocidade v3
Para reotimizar as rampas e limiares com base em novos dados operacionais:
```bash
python otimizador_velocidade_v3.py
```
