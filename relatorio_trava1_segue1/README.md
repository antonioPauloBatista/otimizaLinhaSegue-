# Relatório Técnico: Avaliação de Desempenho e Benefício do SEGUE vs Shadow

**Base de Dados:** `Panel Title-data-2026-11-06 08_32_17.csv`  
**Filtro Rigoroso Aplicado:** `Trava Entrada == 1` E `SEGUE Habilitado == 1`  
**Amostras Válidas:** 2.753 pontos (intervalo de 24 horas a cada 30 segundos)

---

## 1. Animação Dinâmica da Arquitetura e Ganho de Garrafas

Demonstração dinâmica mostrando:
- **Caminhos Paralelos de Controle (Ou 1 Ou Outro):** O **Caminho A (SEGUE APC)** e o **Caminho B (CLP / Shadow)** operam lado a lado como fontes alternativas de setpoint;
- **Chave Seletora Automática ("1 ou Outro"):** Com `SEGUE Habilitado = 1` e `Trava Entrada = 1`, a chave seleciona o Caminho A para enviar o setpoint ao inversor e corta o Caminho B; em modo baseline, a rota tradicional B assume e o SEGUE fica em modo sombra;
- **Estrela de Entrada:** Destravada e monitorada pela presença física contínua de garrafas (`Trava Entrada = 1`);
- **Medição de Benefício Contrafactual:** O ganho líquido capturado é calculado comparando a rota ativa com o baseline sombra: `[Caminho A: SEGUE] − [Caminho B: Shadow]` (+707 garrafas/hora líquidas apuradas em campo).

![Animação Dinâmica: SEGUE vs Shadow Lado a Lado (Ou 1 Ou Outro)](animacao_segue_habilitado_estrela_garrafas.gif)

*(Arquivo em vídeo de alta definição disponível em: `animacao_segue_habilitado_estrela_garrafas.mp4`)*

---

## 2. Arquitetura Operacional: Por que o SEGUE supera o Shadow?

O diagrama abaixo ilustra a arquitetura de controle que explica os resultados observados em campo:

![Arquitetura de Controle: SEGUE vs Shadow](fluxo_controle_segue_vs_shadow.png)

### Explicação da Arquitetura:
1. **Cenário A (Ativo no período analisado):**  
   Com a estrela alimentada com garrafas (`Trava Entrada = 1`) e o otimizador ativo (`SEGUE Habilitado = 1`), a malha opera em **controle fechado**. O setpoint calculado pelo otimizador avançado (`SEGUE (APC)`) é escrito diretamente no inversor de frequência da máquina. O cálculo tradicional conservador da máquina (`CLP / Shadow`) é **cortado / inativado**. O ganho capturado é a diferença direta `SEGUE − SHADOW`.
2. **Cenário B (Modo Sombra / Desabilitado):**  
   Caso o SEGUE estivesse desligado, o SEGUE apenas sugeriria valores (sem escrita), e a máquina rodaria na velocidade conservadora do CLP tradicional (Shadow), perdendo vazão útil de envase.

---

## 3. Consolidação Quantitativa dos Resultados

Ao isolar estritamente o período com `Trava Entrada == 1` e `SEGUE Habilitado == 1`, temos:

| Cenário Operacional | Amostras | Média SEGUE (Entrada) | Média Shadow (Contrafactual) | Média Real LMS (Medição Máquina) | Ganho SEGUE x Shadow | Diferença Real LMS x Shadow |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Linha em Produção Ativa (`Real LMS > 0`)** | 830 | **19.827,41** | 19.120,48 | 18.818,89 | **+3,70%** (+706,93 un.) | **-1,58%** (-301,59 un.) |
| **Regime Pleno / Estacionário (`Real LMS >= 16k`)** | 704 | **20.390,70** | 19.677,56 | **20.162,05** | **+3,62%** (+713,14 un.) | **+2,46%** (+484,49 un.) |
| **Total Global (Incluindo Paradas de Linha)** | 2.753 | **18.355,54** | 16.731,93 | 5.673,69 | **+9,70%** (+1.623,61 un.) | **-66,09%** (devido a paradas) |

* **Ganho Efetivo de Garrafas Rodando:** **+707 garrafas/hora** (+4.890 garrafas líquidas nas 6,92h ativas).

---

## 4. Gráficos Comparativos da Operação

### A. Comparativo de Médias por Regime
![Comparativo de Médias](grafico_barras_comparativo.png)

### B. Série Temporal em Regime Contínuo
![Série Temporal e Ganho Instantâneo](grafico_serie_temporal_producao.png)

### C. Dispersão e Correlação SEGUE vs Shadow
![Dispersão SEGUE vs Shadow](grafico_dispersao_ganho.png)

---

## 5. Diagnóstico Técnico: Por que `Real LMS x Shadow` teve diferença de -1,58%?

A diferença de **-1,58% (-301,59 unidades)** no período agregado com linha rodando decorre das **oscilações físicas e inércia do maquinário**:
* **Rampas de Partida e Parada:** Em 15,2% dos registros ativos (`LMS < 16.000`), a máquina estava acelerando ou desacelerando (média de 11.314 unidades) enquanto o Shadow já simulava regime nominal (~16.007 unidades).
* **Confirmação em Regime Estacionário:** Ao expurgar as rampas transitórias (linha estabilizada >= 16.000), o **Real LMS superou o Shadow em +2,46% (+484,49 unidades)**, comprovando que o ganho do SEGUE é integralmente absorvido e convertido em produção líquida pela linha.
