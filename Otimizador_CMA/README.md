# Configurações do Otimizador CMA-ES

Este diretório contém o módulo de otimização baseado em CMA-ES (`otimizador_cma_es_free.py` / `otimizador_cma_es.py`). Ele utiliza inteligência artificial (Estratégia de Evolução com Adaptação da Matriz de Covariância) para encontrar os melhores "gatilhos" (thresholds) de níveis de pulmões (esteiras de acúmulo) para reduzir ou aumentar a velocidade da enchedora, minimizando paradas por falta ou acúmulo de garrafas.

O comportamento do script é parametrizado pelo arquivo `config_colunas.json`.

## Entendendo o `config_colunas.json`

O arquivo `config_colunas.json` deve estar na mesma pasta que o script e serve para mapear quais colunas de um arquivo CSV exportado do Grafana/InfluxDB correspondem a quais máquinas e pulmões na sua linha.

Abaixo, a explicação de cada campo disponível no arquivo:

### 1. Colunas de Nível de Pulmão (Buffers)
Estas chaves dizem ao script onde encontrar o preenchimento (%) de cada pulmão na linha de produção.

- **`Col_Buffer_Antes_Entrada`**: Nome da coluna no CSV que contém o nível do pulmão mais extremo antes da entrada da enchedora (ex: DPL para UIP). Se a sua linha só tiver um pulmão de entrada, isso pode ficar em branco ou omitido.
- **`Col_Buffer_Entrada`**: Nome da coluna no CSV que contém o nível do pulmão diretamente colado à entrada da enchedora (ex: UIP para ECH).
- **`Col_Buffer_Saida`**: Nome da coluna no CSV que contém o nível do pulmão diretamente colado à saída da enchedora (ex: ECH para PZ).
- **`Col_Buffer_Pos_Saida`**: Nome da coluna no CSV que contém o nível do pulmão mais extremo de saída (ex: PZ para EPC). Pode ser omitido se não houver.

### 2. Colunas de Velocidade das Máquinas (CPH)
Estas chaves mapeiam as velocidades reais instantâneas das máquinas da linha.

- **`COL_V_Antes_Entrada`**: Coluna de velocidade da máquina antes da entrada (ex: Despaletizadora).
- **`COL_V_Entrada`**: Coluna de velocidade da máquina de entrada imediatamente antes do buffer principal (ex: Descaixotadora).
- **`COL_V_ECH`** (Opcional, se não informada usa o padrão no script): Coluna de velocidade da Enchedora.
- **`COL_V_Saida`**: Coluna de velocidade da máquina de saída imediatamente depois do buffer (ex: Pasteurizador/Rotuladora).
- **`COL_V_Entrada_Pos_Saida`**: Coluna de velocidade da máquina mais externa na saída (ex: Encaixotadora).

### 3. Parâmetros de Comportamento
Variáveis que alteram a matemática ou lógica da simulação e otimização.

- **`Velocidade_Nominal_ECH`**: (Número) Velocidade Nominal (100%) da Enchedora em CPH (Garrafas por Hora).
  - Se for `0` ou omitido, o script calculará a velocidade nominal de forma dinâmica lendo o histórico e pegando o percentil 90 das velocidades ativas.
- **`Filtro_Minutos_Parada_Longa`**: (Número) Minutos de máquina parada contínua para que o script considere uma "Quebra Mecânica ou Parada de Operador".
  - O otimizador ignora (não tenta evitar) paradas maiores que esse valor, pois entende que são manutenções/falhas externas e não micro-paradas causadas por nível de esteira. O padrão é `10` minutos.
- **`Fator_Sobremarcha`**: (Número, ex: `1.05` para 105%, ou `1.10` para 110%). 
  - Se for maior que `1.0`, o relatório final vai gerar os gatilhos matematicamente calculados para você rodar a linha em regime de sprint (sobremarcha), exigindo uma margem percentual a mais (+15%) nos pulmões de entrada e de saída.

---
### Exemplo de um arquivo `config_colunas.json`:
```json
{
  "Col_Buffer_Antes_Entrada": "accumulation_percentage_dpl_to_uip_null",
  "Col_Buffer_Entrada": "accumulation_percentage_uip_to_ech_null",
  "Col_Buffer_Saida": "accumulation_percentage_ech_to_pz_null",
  "Col_Buffer_Pos_Saida": "accumulation_percentage_pz_to_epc_null",
  "COL_V_Antes_Entrada": "speed_actual_cph_null_third_upstream_machine_1",
  "COL_V_Entrada": "speed_actual_cph_null_eci_1",
  "COL_V_ECH": "speed_actual_cph_null_filler_1",
  "COL_V_Saida": "speed_actual_cph_null_pasteurizer",
  "COL_V_Entrada_Pos_Saida": "speed_actual_cph_null_second_downstream_machine_1",
  "Velocidade_Nominal_ECH": 0,
  "Filtro_Minutos_Parada_Longa": 10,
  "Fator_Sobremarcha": 1.10
}
```
