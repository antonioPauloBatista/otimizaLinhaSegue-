# Documentação Técnica: Otimizador CMA-ES (Free)

Este módulo contém o algoritmo de otimização de velocidade de enchedora baseado em **CMA-ES** (*Covariance Matrix Adaptation Evolution Strategy*), implementado de forma totalmente autônoma em Python puro (`otimizador_cma_es_free.py`), sem necessidade de bibliotecas C/C++ externas ou compiladores.

O objetivo do módulo é processar o histórico real de produção da linha (exportado do Grafana/InfluxDB) e encontrar matematicamente os **melhores gatilhos de nível de esteira** e as **velocidades de modulação ótimas** para maximizar o volume de garrafas envasadas e eliminar paradas por falta ou acúmulo de garrafas.

---

## 1. Como Funciona o Algoritmo CMA-ES

O CMA-ES é uma técnica de inteligência artificial evolutiva de segunda ordem para otimização em espaços contínuos e multivariáveis:

1. **População e Mutações:** A cada geração, o algoritmo gera uma população de candidatos (vetores contendo limiares de acúmulo/falta e velocidades de modulação).
2. **Gêmeo Digital da Linha:** Cada vetor de parâmetros é injetado no simulador histórico ciclo a ciclo (amostragem de 30 segundos). O simulador calcula:
   - Quantas garrafas foram produzidas a mais.
   - Quantas paradas de máquina (0 CPH) foram evitadas.
   - Penalidades por oscilação excessiva de velocidade (*chattering* mecânico).
3. **Adaptação da Matriz de Covariância:** Em vez de fazer uma busca aleatória, o algoritmo aprende as correlações entre os buffers (por exemplo, como o nível de B2 se relaciona com a esteira B3) e ajusta o elipsoide de busca na direção do ganho máximo de produção.
4. **Early Stopping:** Quando a média das últimas 50 gerações atinge estabilidade sem melhora significativa, o otimizador encerra a busca automaticamente e exporta os parâmetros consolidados.

---

## 2. Modos de Operação: 4 Pulmões (B1-B4) vs 2 Pulmões (B2-B3)

O script permite escolher entre duas arquiteturas de linha diretamente pelo arquivo de configuração JSON:

### Modo 1: 4 Pulmões (B1, B2, B3 e B4)
* **Estrutura:** Monitora Lavadora/Despaletizadora (B1), Entrada da Enchedora (B2), Saída para Pasteurizador (B3) e Saída do Pasteurizador (B4).
* **Perfil:** Mais conservador. Adequado para linhas com esteiras curtas ou sem pulmão de alívio no pasteurizador.

### Modo 2: Alta Performance Agressiva (Apenas B2 e B3 - Recomendado)
* **Estrutura:** Desativa os pulmões distantes (B1 e B4) e foca **exclusivamente nas esteiras imediatas da Enchedora**.
* **Como ativar:** Deixe `"Col_Buffer_Antes_Entrada": ""` e `"Col_Buffer_Pos_Saida": ""` no JSON.
* **Benefício Operacional:** O Pasteurizador atua como um pulmão gigante de desacoplamento. A enchedora não freia por oscilações secundárias nas pontas da fábrica, mantendo a máquina no topo nominal (94.500 CPH) a maior parte do turno.

---

## 3. Calibração da Velocidade de Modulação (O Fim da Queixa dos 85%)

Historicamente, o otimizador reduzia a enchedora para **85%** (80.325 CPH). A operação fabril reportava que essa queda era excessiva para distúrbios rápidos de 15 a 30 segundos.

Com a atualização dos limites:
* **Modulação Leve em 95.0% (89.775 CPH):** A máquina desacelera apenas 5% durante oscilações normais. A queda é quase imperceptível visualmente no painel, a linha preserva um ritmo alto e a esteira ganha o tempo necessário para escoar garrafas.
* **Ganho Comprovado em Simulação:** Subir o teto de modulação de 85% para 95% gerou **mais de 1 milhão de garrafas adicionais** no histórico, mantendo as **315 paradas críticas de esteira evitadas**.

---

## 4. Estrutura do Arquivo `config_colunas.json`

O comportamento da otimização é guiado por um arquivo JSON. Você pode ter múltiplos arquivos (ex: `config_colunas.json`, `config_colunas_2.json`):

```json
{
  "Arquivo_Dados": "dados_completos_fabrica.csv",
  "Col_Buffer_Antes_Entrada": "",
  "Col_Buffer_Entrada": "accumulation_percentage_dpl_to_ech_null",
  "Col_Buffer_Saida": "accumulation_percentage_ech_to_pz_null",
  "Col_Buffer_Pos_Saida": "",
  "COL_V_Antes_Entrada": "",
  "COL_V_Entrada": "speed_actual_cph_null_first_upstream_machine_1",
  "COL_V_ECH": "speed_actual_cph_null_filler_1",
  "COL_V_Saida": "speed_actual_cph_null_pasteurizer",
  "COL_V_Entrada_Pos_Saida": "",
  "Velocidade_Nominal_ECH": 94500,
  "Fator_Sobremarcha": 1.03,
  "Min_Modulacao": 0.80,
  "Max_Modulacao": 1.00,
  "Limite_Parada_Falta": 10.0,
  "Limite_Parada_Acumulo": 75.0
}
```

### Explicação dos Campos:

| Chave | Tipo | Descrição |
| :--- | :---: | :--- |
| `Arquivo_Dados` | String | Nome do CSV histórico exportado do Grafana. |
| `Col_Buffer_Antes_Entrada` | String | Tag do buffer B1 (deixe vazio `""` para desativar). |
| `Col_Buffer_Entrada` | String | Tag do buffer de entrada imediata da Enchedora (B2). |
| `Col_Buffer_Saida` | String | Tag do buffer de saída imediata da Enchedora (B3). |
| `Col_Buffer_Pos_Saida` | String | Tag do buffer B4 pós-pasteurizador (deixe vazio `""` para desativar). |
| `COL_V_ECH` | String | Tag de velocidade real da Enchedora. |
| `COL_V_Entrada` | String | Tag de velocidade da máquina anterior (ECI/Descaixotadora). |
| `COL_V_Saida` | String | Tag de velocidade da máquina seguinte (Pasteurizador). |
| `Velocidade_Nominal_ECH` | Número | Velocidade nominal de projeto (ex: 94.500 CPH). |
| `Fator_Sobremarcha` | Número | Multiplicador de sprint (ex: 1.03 para 103% = 97.335 CPH). |
| `Filtro_Minutos_Parada_Longa`| Número | Minutos contínuos em 0 CPH para classificar quebra mecânica externa (padrão: 10 min). |

---

## 5. Como Executar a Otimização

No terminal, você pode rodar apontando para o arquivo de configuração desejado:

```bash
# Execução padrão (lê config_colunas.json)
python3 otimizador_cma_es_free.py

# Execução customizada (ex: modo focado em B2 e B3)
python3 otimizador_cma_es_free.py config_colunas_2.json
```

---

## 6. Arquivos Gerados Automaticamente

Ao concluir a convergência, o script gera automaticamente:

1. **`relatorio_otimizador_<tag>_<data_hora>.txt`**:
   Relatório consolidado com resumo de garrafas ganhas, paradas evitadas e os gatilhos finais prontos para copiar para o CLP.
2. **`parametros_cma_es_<tag>.json` e `parametros_cma_es.json`**:
   Arquivo estruturado com os valores numéricos exatos de gatilhos e velocidades para serem consumidos pelos controladores live.
3. **`dados_projetados_otimizado_<tag>.csv`**:
   Planilha com o comparativo segundo a segundo da velocidade real vs velocidade otimizada proposta pela IA.
4. **Gráficos Diários PNG (`comparacao_velocidades_otimizado_<tag>_<dia>.png`)**:
   Curvas temporais plotando a Enchedora Real vs IA e o nível das esteiras para validação visual dia a dia.

---

## 7. Aplicação Prática das Regras no CLP / PLC

Os parâmetros encontrados pelo otimizador traduzem-se diretamente em lógicas de blocos de controle no CLP:

* **Faixa Segura (100% Nominal):**
  * Todos os pulmões dentro da faixa segura (sem ativação preventiva).
* **Histerese Padronizada em 5.0% (Anti-Travamento):**
  * Elimina o travamento de estado booleano em esteiras cheias (como 68% no PZ-EPC).
  * Gatilho de Clear é sempre `Gatilho - 5.0%` (acúmulo) e `Gatilho + 5.0%` (falta).

---

## 8. Blindagem Contra Regressão e Detecção Automática de Limites

Para garantir que futuras alterações no código nunca reintroduzam limites estáticos ou distorções de histerese, o sistema conta com uma **arquitetura de proteção em três camadas**:

1. **Detecção Automática Orientada a Falhas (`calcular_limites_busca_automaticos`):**
   * O espaço de busca `bounds_lo` e `bounds_hi` não é fixado na mão: ele é calculado dinamicamente escaneando as paradas reais (`velocidade == 0 CPH`) e o regime de operação contínua do CSV.
   * Para os pulmões de saída (B3 e B4), o limite inferior de busca é mantido estritamente acima do regime de trabalho contínuo, impedindo que o algoritmo sugira cortes em faixas normais (como 65% ou 68%).
2. **Trava em Tempo de Execução (*Fail-Safe Industrial* no Código):**
   * Dentro de `otimizador_cma_es_free.py`, há verificações ativas que interrompem a execução com erro crítico caso `bounds_lo[6] < 70.0%` ou `Histerese > 8.0%`.
3. **Suíte de Testes Unitários Automatizados (`test_limites_automaticos.py`):**
   * Testes contínuos com `unittest` validando:
     * Cálculo dinâmico em datasets reais e sintéticos.
     * Prova matemática de que em 68% a enchedora roda livre a 100%.
     * Tolerância a ausência de paradas e buffers opcionais.
   * Executar os testes:
     ```bash
     python3 -m unittest Otimizador_CMA/test_limites_automaticos.py -v
     ```

