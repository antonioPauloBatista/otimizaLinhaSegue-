# Matriz de Agentes Especializados — Controle de Velocidade V4

Este documento registra a atuação, o escopo de responsabilidade e as decisões técnicas tomadas por cada um dos **Agentes Especializados** que colaboraram na concepção, modelagem, calibração, implementação e validação do sistema **`Controle_Velocidade_4`**.

A governança do projeto seguiu a diretriz de **intervenção 100% data-driven** (zero modificação física em esteiras ou fiação de campo), com **foco na Enchedora (benchmark machine)** e **proteção rigorosa para máquinas antigas**.

---

## 🏛️ 1. Leader (Líder Técnico e Coordenador de Projeto)

### Escopo e Objetivos:
* Entender as dores do processo fabril e os gargalos de OEE da linha de envase.
* Garantir que todas as propostas dos especialistas fossem exequíveis em ambiente industrial real sem necessidade de paradas de produção para obras civis ou instalação de sensores.
* Coordenar a divisão de camadas, resolver conflitos entre desempenho produtivo e conservadorismo mecânico, e consolidar o projeto.

### Principais Decisões Tomadas na V4:
1. **Criação do diretório independente `Controle_Velocidade_4`:** Preservou intacta a versão anterior V3, permitindo auditoria comparativa lado a lado.
2. **Priorização da Enchedora:** A enchedora é a máquina mestra que dita o ritmo da cervejaria; todas as outras máquinas e esteiras devem modular para mantê-la operando de forma contínua e estável.
3. **Rejeição de Intervenções Físicas:** Vetou qualquer proposta que exigisse medição manual de esteiras com trena ou reconfiguração de fotocélulas no CLP, exigindo que a inteligência fosse 100% em software e dados.

---

## 🧠 2. Memory (Guardião do Histórico e Contexto)

### Escopo e Objetivos:
* Reter todo o histórico de desenvolvimento da linha, decisões de versões anteriores e restrições aprendidas.
* Alertar sempre que uma nova decisão contradisser uma premissa consolidada no passado.

### Principais Decisões Tomadas na V4:
1. **Preservação dos Ganhos da V3:** Lembrou que a versão V3 já havia calibrado com sucesso a rampa suave fuzzy nos buffers ($19.25\%$ em $B_2$ e $18.48\%$ em $B_3$) e os limiares centrais ($b_{2\_lim}=31.47\%$, $b_{3\_lim}=69.24\%$). Garantiu que esses avanços fossem herdados como Camada 1 da V4.
2. **Resolução da Discrepância Histórica do Dia 28:** Identificou que no projeto legado o sinal `COL_V_ECH` havia sido mapeado incorretamente para a velocidade da ECI (nominal $72.000\text{ CPH}$), enquanto a enchedora real operava em $60.000\text{ CPH}$. Corrigiu o mapeamento para a enchedora real (`speed_actual_cph_null_filler_1`).

---

## 🏭 3. Process Specialist (Especialista em Processo e Cervejaria)

### Escopo e Objetivos:
* Analisar os impactos físico-químicos no produto (cerveja) e a integridade dos equipamentos mecânicos de envase.
* Garantir que a lógica de modulação respeite a termodinâmica dos fluidos carbonatados e o comportamento das embalagens de vidro/lata nas esteiras.

### Principais Decisões Tomadas na V4:
1. **Mitigação de TPO (Oxigênio Dissolvido):** Alertou que paradas bruscas e degraus de velocidade rompem o colchão de gás inerte ($CO_2$) nas válvulas de enchimento, causando oxidação da cerveja e perda de *shelf-life*. Exigiu a eliminação de qualquer controle liga/desliga.
2. **Controle de Espumamento (*Fobbing*):** Demonstrou que acelerações repentinas nas estrelas de transferência agitam o líquido pressurizado, causando transbordamento de espuma e subenchimento descartado pela inspetora de nível.
3. **Física das Esteiras de Massa:** Explicou que garrafas em esteiras lubrificadas formam ondas de pressão e efeito sanfona, com pacotes densos alternados com vãos (*gaps*), justificando por que as fotocélulas sofrem comutações fora de ordem.

---

## 🔬 4. Data Scientist (Especialista em Tratamento de Dados e Sinais)

### Escopo e Objetivos:
* Avaliar a qualidade dos dados históricos e em tempo real, tratando ruídos, outliers, drift e problemas de amostragem.
* Projetar os filtros matemáticos para transformar dados brutos caóticos em sinais contínuos de alta fidelidade.

### Principais Decisões Tomadas na V4:
1. **Detecção do Ruído de Queda Súbita:** Identificou no CSV de fábrica que o buffer de entrada despencava artificialmente de $59.6\%$ para $18.7\%$ e retornava a $59.6\%$ em apenas 30 segundos, devido a garrafas em trânsito cruzando os feixes óticos.
2. **Arquitetura do Pipeline de Dados em 3 Estágios:**
   * *Filtro Mediano Móvel ($N=3$):* Elimina pulsos isolados de 1 amostra sem causar atraso de fase;
   * *Debounce Temporal:* Confirma se a variação persiste por 2 amostras consecutivas na mesma direção;
   * *EWMA ($\alpha = 0.65$):* Atua como integrador exponencial contínuo, fornecendo uma estimativa fidedigna da densidade de acúmulo real.

---

## 📈 5. Optimization Engineer (Especialista em Otimização Matemática)

### Escopo e Objetivos:
* Formular o problema de maximização de produção sujeito a restrições de processo, perdas econômicas e integridade de linha.
* Calibrar globalmente os parâmetros do controlador utilizando metaheurísticas avançadas.

### Principais Decisões Tomadas na V4:
1. **Algoritmo CMA-ES (Covariance Matrix Adaptation Evolution Strategy):** Adotou o CMA-ES para buscar o ótimo global no espaço contínuo de 11 parâmetros, evitando mínimos locais típicos de algoritmos de gradiente.
2. **Função Objetivo com Penalidade Severa:**
   $$\text{Fitness} = \text{Produção Total} - \left(N_{\text{socos}} \times 40.000\right) - \left(\sum \left(\frac{\Delta V}{1000}\right)^2 \times 15\right) - \text{Penalidades}$$
   Penalizou fortemente amostras onde a enchedora operava rápida com buffers em zonas de perigo ($B_2 \le 10\%$ ou $B_3 \ge 90\%$).
3. **Digital Twin Histórico Realista:** Respeitou as paradas longas reais de manutenção ($> 10\text{ min}$ com velocidade zero), garantindo que o ganho de $+21.9\%$ (+203 mil garrafas no período) fosse 100% factível.

---

## 🎛️ 6. Fuzzy Specialist (Especialista em Lógica Fuzzy e Inferência)

### Escopo e Objetivos:
* Projetar as variáveis linguísticas, funções de pertinência (*Membership Functions*) e regras de inferência para decisão suave em cenários de incerteza.

### Principais Decisões Tomadas na V4:
1. **Motor Takagi-Sugeno de Ordem Zero:** Escolheu a formulação Sugeno por sua altíssima eficiência computacional ($O(1)$) e facilidade de portabilidade para linguagens industriais de CLP.
2. **Base de 7 Regras de Produção:**
   * R1 (Falta Entrada), R2 (Acúmulo Saída), R3 (Retomada Sincronizada com máquina da frente), R4 (Alerta Feedforward $B_1$), R5 (Alerta Feedforward $B_4$), R6 (Fluxo Nominal) e R7 (Sprint Condicionado).
3. **Rampas Trapezoidais Contínuas:** Manteve as rampas de transição contínuas nos pulmões imediatos, garantindo que o cálculo do setpoint seja suave em todo o curso percentual do buffer.

---

## ⚙️ 7. Control Engineer (Engenheiro de Controle e Automação)

### Escopo e Objetivos:
* Projetar a malha fechada de controle, garantindo estabilidade, tempo de resposta adequado, amortecimento e proteção mecânica para equipamentos envelhecidos.

### Principais Decisões Tomadas na V4:
1. **Balanço de Massa Feedforward ($V_{\text{in}}$ e $V_{\text{out}}$):** Adicionou monitoramento das velocidades das máquinas vizinhas para antecipar desvios de esteira antes que o nível atinja zonas críticas.
2. **Retomada Antecipada por Tendência ($\frac{dV_{\text{out}}}{dt} > 0$):** Desenvolveu a detecção da taxa de aceleração da máquina a jusante, aliviando a restrição de saída cheia assim que o pasteurizador começa a puxar garrafas.
3. **Limitador Temporal de Rampa (*Slew-Rate Limiter*):** Impôs uma taxa máxima de variação ($\Delta V_{\text{max\_ciclo}} = \frac{\text{Max\_Rampa}}{30} \times \Delta t$), impedindo saltos em degrau no atuador da enchedora.
4. **Banda Morta Anti-Chattering (`Banda_Morta_CPH: 300.0`):** Implementou o congelamento de variações inferiores a 300 CPH, evitando vibrações, histerese e desgaste em potenciômetros e engrenagens com folga mecânica.

---

## 🔍 8. Failure Analyst (Especialista em Análise de Falhas e OEE)

### Escopo e Objetivos:
* Catalogar os modos de falha industriais, evitar oscilações descontroladas (*hunting*) e garantir que cada modulação de velocidade tenha causa-raiz identificável.

### Principais Decisões Tomadas na V4:
1. **Dicionário Enum Estruturado (`motivos_modulacao_enum.json`):** Padronizou códigos numéricos de 0 a 99 descrevendo exatamente por que a enchedora modulou ou parou.
2. **Atribuição Formal da Máquina Causadora:**
   * Falta crítica de garrafas ($B_2 \le 10\%$, ID 91) $\to$ Causa: **ECI / DPL** (*Starvation*);
   * Acúmulo crítico de garrafas ($B_3 \ge 90\%$, ID 92) $\to$ Causa: **Pasteurizador** (*Blockage*);
   * Parada com buffers em faixa normal (ID 99) $\to$ Causa: **Enchedora (Própria Máquina)** (*Breakdown*);
   * Máquina em marcha lenta com esteiras livres (ID 65) $\to$ Causa: **Enchedora (Restrição Local / Manutenção)**;
   * Transição em rampa (ID 60) $\to$ Causa: **Enchedora (Inércia Mecânica Própria)**.

---

## 🚀 9. Industrial Deployment (Especialista em Implantação e Edge)

### Escopo e Objetivos:
* Garantir que o modelo rode em tempo real, em hardware industrial de baixo custo ou diretamente embarcado em CLP, com tempo de inferência determinístico e fail-safe.

### Principais Decisões Tomadas na V4:
1. **Complexidade Computacional $O(1)$:** O algoritmo executa em menos de $1\text{ ms}$ por ciclo, sem dependências de frameworks pesados de IA, permitindo execução em containers Docker leves ou Raspberry Pi.
2. **Watchdog de Segurança (5 Minutos):** No conector [`controlador_velocidade_grafana_v4.py`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/controlador_velocidade_grafana_v4.py), inseriu proteção contra dados congelados do InfluxDB/Grafana, forçando rampa para velocidade segura caso as medições não atualizem.
3. **Mapeamento para CLP (IEC 61131-3 SCL):** Documentou a estrutura do bloco de função SCL (`FB_ControleVelocidadeV4`) para portabilidade imediata em Siemens S7-1500 ou Rockwell ControlLogix.
4. **Rastreamento de Eventos em JSON (Início e Fim):** Implementou exportação estruturada em JSON para o Live (`eventos_motivos_live_v4.json`), Grafana (`eventos_motivos_grafana_v4.json`) e Histórico (`eventos_motivos_historico_v4.json`), registrando início, término e causa-raiz de paradas e modulações, com a regra estrita de que em 100% nominal nenhum evento de perda é gerado.

---

## 🧪 10. Validation Engineer (Engenheiro de Testes e Validação)

### Escopo e Objetivos:
* Desenvolver suítes de testes automatizados para estressar a lógica em todas as condições de contorno e verificar o cumprimento estrito de cada especificação.

### Principais Decisões Tomadas na V4:
1. **Suíte Automatizada ([`teste_unitario_v4.py`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/teste_unitario_v4.py)):**
   * *Teste de Slew Rate:* Validação de que degraus repentinos de buffer nunca excedem a rampa máxima configurada;
   * *Teste de Retomada por Tendência:* Confirmação de que a enchedora acelera mais cedo quando a jusante destrava;
   * *Teste de Sprint:* Verificação da sobrevelocidade condicionada quando a linha está desimpedida;
   * *Teste de Banda Morta:* Comprovação de tolerância zero a micro-oscilações inferiores a 300 CPH;
   * *Teste de Identificação de Causa e Máquina:* Auditoria da consulta correta aos códigos do enum JSON;
   * *Teste de Eventos JSON (Início e Fim):* Verificação estrita de que a 100% nominal nenhum evento é gerado, e que desvios de velocidade (< 100%) registram início, término ('fim') e causa no arquivo JSON.

---

## 📋 11. Reviewer (Auditor Técnico Final)

### Escopo e Objetivos:
* Realizar a revisão final antes da entrega, validando conformidade técnica, clareza da documentação, ausência de riscos operacionais e aderência às regras do [`AGENTS.md`](file:///home/antonio/Projetos/OtimizadorSegue/AGENTS.md).

### Principais Decisões Tomadas na V4:
1. **Memorial Técnico Completo ([`ARQUITETURA_E_FUNCIONAMENTO_V4.md`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/ARQUITETURA_E_FUNCIONAMENTO_V4.md)):** Exigiu a consolidação de todas as 14 seções teóricas, matemáticas e operacionais em um documento único autoexplicativo, permitindo que qualquer equipe de engenharia ou outra LLM audite o projeto.
2. **Garantia de Não Agressão a Máquinas Antigas:** Confirmou que a integração entre rampa fuzzy, limitador temporal e banda morta atende tanto a linhas modernas de alta performance quanto a linhas antigas com folgas mecânicas acentuadas.
3. **Padrão Estrito de Legibilidade Documental:** Estabeleceu que todos os READMEs e documentos técnicos devem priorizar texto claro e legível, sem sintaxe LaTeX crua (como `$...$`, `\text{}`, `\frac{}`) que fique ilegível ou poluída em visualizadores comuns de Markdown (GitHub, VS Code, editores de texto). Símbolos matemáticos devem ser expressos de forma limpa (ex: `V_in`, `dV/dt`, `ΔV_max`, `CO₂`, `α = 0.65`).
