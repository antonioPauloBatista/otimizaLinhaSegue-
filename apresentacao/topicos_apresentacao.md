# 📊 Apresentação Otimizador SEGUE (3 Slides)

Este documento contém a estrutura oficial da apresentação resumida em **3 Slides**, conforme diretrizes do projeto.

---

## 🖥️ SLIDE 1: ADOÇÃO & GOVERNANÇA DE DESEMPENHO

### 1. Diagnóstico de Performance Pós-Implantação
* **Casos de Perda Registrados:** Oscilações bruscas (*hunting*), ruídos/latência nos sensores do buffer intermediário e descompasso com rampas do PLC.
* **Plano de Ação:** Aplicação de filtros de histese/suavização, validação de integridade de sinais e engajamento com time operacional.

### 2. Endereçamento Global: Benefício com Setpoints Iguais
* **Problema Metrológico:** Quando o setpoint do otimizador iguala o manual, a variação de velocidade instantânea ($\Delta V$) resulta em $0\%$, mascarando ganhos reais.
* **Solução Homologada:** Troca da métrica para **Produção Líquida Realizada (Hectolitros / Garrafas por hora)** via *A/B Testing* dinâmico e redução de microparadas por afogamento/desabastecimento.

### 🖼️ Evidência Visual do Diagnóstico & Cálculo de Benefício
![Atuação Real da Velocidade e Ocupação dos Buffers vs Limites de Parada](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/cma_es_grafico_real_atuacao.png)
*Figura: Comparativo em tempo real entre velocidade nominal real, proposta otimizada e oscilação dos buffers B2/B3.*

![Simulação e Cálculo de Ganho do Gêmeo Digital](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/cma_es_simulacao_ganho.svg)
*Figura: Metodologia de cálculo do ganho via simulação de ocorrência histórica vs proposta do otimizador.*

### 🖼️ Entendendo o Buffer: Indicador de 29% na IHM vs Composição por 5 Sensores
![Conceito do Buffer e Composição por 5 Sensores a partir da IHM do CLP](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/explicacao_buffer_sensores_ihm.png)
*Figura: Mapeamento direto entre o indicador de acúmulo da IHM do CLP (29%) e a física dos 5 sensores na esteira.*

### 🖼️ Lista Ilustrada de Pendências & Desafios da Adoção
![Lista de Pendências e Desafios da Adoção](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/lista_pendencias_adocao.png)
*Figura: Lista simples dos 5 pontos de atenção e pendências operacionais para governança do projeto.*

### 3. Versão SEGUE na Camada PLC (Plano de Implantação)
* **Variação por Cervejaria:** Algumas plantas possuem a implementação na camada diferente para as novas versões do SEGUE (necessidade de harmonização de blocos IEC 61131-3).

### 4. O SEGUE MELHORA OU NÃO MINHA LINHA?

### 📈 Gráficos de Evolução de Desempenho (Adoção)
* **Visão Global de Adoção (Agosto 43,14%):**
  ![Gráfico de Evolução de Performance - Adoção Global](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/grafico_evolucao_ouro.svg)

* **Evolução Específica — Ponta Grossa (PG L502 - Salto de 2,28% para 27,0%):**
  ![Evolução de Adoção PG L502](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/grafico_evolucao_pg502.svg)

---

## 🖥️ SLIDE 2: ESTRATÉGIA DE ROLLOUT 2026

### 1. Seleção & Status Atual das Linhas (Pipeline 2026)
* ✅ **NS 503:** Implantação Concluída (**OK**)
* ✅ **PG 501:** Implantação Concluída (**OK**)
* ✅ **AQ 541:** Implantação Concluída (**OK**)
* ⚙️ **PI 541:** **Em Execução nesta Semana**
* 📅 **UB 511:** Implantação Prevista para **Setembro/2026**
* 📅 **QM 511:** Implantação Prevista para **Setembro/Outubro 2026**

### 2. Gráfico Visual do Status do Rollout por Linha
![Status do Rollout por Linha 2026](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/grafico_rollout_2026.svg)

### 3. Otimizador como Feature do Produto (Redução de Setup)
| Abordagem | Tempo Médio | Característica |
| :--- | :---: | :--- |
| **Projeto Ad-Hoc (Sem Feature)** | 6 a 8 semanas | Configuração manual, alta dependência de engenharia de dados e customização por planta. |
| **Otimizador como Feature (Plug & Play)** | **< 1 semana** | Bloco de função padronizado no PLC, autotuning de parâmetros e alta escalabilidade. |

---

## 🖥️ SLIDE 3: SUGESTÕES DE MELHORIA DO PRODUTO (CONTROLE APC & SODA ETL)

### 1. Transição Tecnológica: De Gatilhos Discretos para Controle APC
* ⚠️ **Abordagem Atual por Gatilhos Discretos:** Degraus de velocidade (85%, 95%, 100%) geram choque mecânico, desgaste nas esteiras e risco de *hunting*.
* 🚀 **Visão de Futuro — Controle Avançado de Processo (APC / MPC Preditivo):** Modulação fina e contínua de velocidade no PLC, eliminando trancos e estabilizando os 4 buffers na Zona de Ouro.

### 2. Migração para Soda ETL (Fim da Aplicação Local Isolada)
* ❌ **Problema Atual (Aplicação Local em Cada Cervejaria):** Falta de gestão centralizada de atualizações, falta de política automatizada de backups e risco de versões desatualizadas em cada planta.
* 🌐 **Solução com Soda ETL (Governança Corporativa Global):** Centralização de rotinas de deploy (CI/CD), backups automáticos, padronização de versão em 100% das cervejarias e pipeline contínuo de dados integrados.

### 🖼️ Infográfico de Futuro da Arquitetura (Controle APC + Soda ETL)
![Evolução do Produto: Controle APC e Integração com Soda ETL](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/visao_futuro_apc_soda_ai.png)

### 3. Evidências do Relatório Oficial de Validação
* **Relatório Oficial em Imagem Quadrada:** [`relatorio_otimizador_quadrado.png`](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/relatorio_otimizador_quadrado.png) (**+11,39% Produção Líquida** | **2.640 Paradas de Buffer Evitadas**).
* **Visualização da Arquitetura da Linha (Imagem Oficial):**

![Arquitetura SEGUE](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/segue_slide_final.png)
