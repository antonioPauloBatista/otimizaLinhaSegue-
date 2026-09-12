# Controle de Velocidade V4 (Data-Driven Feedforward & Slew-Rate)

Este diretório contém a versão **V4** do sistema inteligente de controle de velocidade e otimização de linhas de envase (cervejaria / refrigerantes), com foco na máquina mestra (Enchedora / Filler).

A versão V4 incorpora todas as capacidades da V3 com evoluções de engenharia para resolver limitações de sensores em campo e proteger a integridade mecânica da máquina.

---

## 🌟 Principais Inovações da V4

1. **Tratamento de Dados 100% em Software (Zero Intervenção em Campo):**
   - **Filtro Mediano Móvel (Janela de 3 amostras):** Elimina pulsos espúrios e picos isolados decorrentes de sensores óticos desordenados (ex: desvios súbitos de 40% que retornam em 30 segundos).
   - **Debounce de Persistência:** Diferencia garrafas passando rapidamente de acúmulo consolidado na esteira.
   - **EWMA (Exponentially Weighted Moving Average):** Converte a comutação discreta das fotocélulas em uma curva suave contínua de densidade de acúmulo ($\alpha = 0.65$).

2. **Balanço de Massa Feedforward (Máquinas Vizinhas):**
   - Monitora em tempo real a velocidade da máquina a montante ($V_{\text{in}}$, ex: ECI) e da máquina a jusante ($V_{\text{out}}$, ex: Pasteurizador).
   - Não depende apenas do nível acumulado dos buffers: antecipa o desvio antes que o buffer atinja o limite.

3. **Retomada Sincronizada Pós-Parada com Tendência:**
   - Calcula a taxa de aceleração da máquina da frente ($\frac{dV_{\text{out}}}{dt}$).
   - Quando a máquina posterior destrava e começa a acelerar, a enchedora inicia imediatamente sua rampa de aceleração sem esperar o buffer de saída esvaziar por completo, eliminando o tempo morto de linha.

4. **Proteção Mecânica Ativa (Slew-Rate Limiter em Software):**
   - O setpoint despachado pelo algoritmo é estritamente limitado por uma taxa máxima de variação ($\Delta V_{\text{max}} / \Delta t$).
   - Elimina degraus bruscos, socos mecânicos no carrossel da enchedora, quebra de garrafas e perda de produto por espumamento ($CO_2$).

5. **Modo Sprint / Sobrevelocidade Condicionada:**
   - Permite que a enchedora opere acima da nominal (ex: 101% a 105%) quando a linha está completamente desafogada (buffers de entrada e saída em zona segura e máquinas vizinhas rodando a $\ge 90\%$ da nominal).

---

## 📁 Estrutura de Arquivos

| Arquivo / Pasta | Descrição |
| :--- | :--- |
| [`ARQUITETURA_E_FUNCIONAMENTO_V4.md`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/ARQUITETURA_E_FUNCIONAMENTO_V4.md) | Memorial técnico completo com a física do processo, equações matemáticas e filtros. |
| [`motivos_modulacao_enum.json`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/motivos_modulacao_enum.json) | Dicionário Enum formal com os códigos numéricos de causa-raiz de modulação/parada. |
| [`otimizador_velocidade_v4.py`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/otimizador_velocidade_v4.py) | Algoritmo CMA-ES de otimização de 11 parâmetros + Digital Twin sobre dados históricos. |
| [`funcao_controle_v4.py`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/funcao_controle_v4.py) | Módulo Python autônomo com a classe `ControladorVelocidadeV4`, filtros e rampa. |
| [`controlador_velocidade_live_v4.py`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/controlador_velocidade_live_v4.py) | Simulador de bancada interativo no terminal com diagnóstico de motivos em tempo real. |
| [`controlador_velocidade_grafana_v4.py`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/controlador_velocidade_grafana_v4.py) | Controlador em tempo real conectado via API do Grafana / InfluxDB. |
| [`assistente_configuracao.py`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/assistente_configuracao.py) | CLI interativo para gerar o [`config_colunas.json`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/config_colunas.json). |
| [`config_colunas.json`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/config_colunas.json) | Mapeamento das colunas de buffers, velocidades e limites operacionais. |
| [`parametros_controle_v4.json`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/parametros_controle_v4.json) | Parâmetros ótimos calibrados pelo CMA-ES. |
| [`teste_unitario_v4.py`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/teste_unitario_v4.py) | Suite de testes unitários para verificação de slew rate, sprint e aceleração por tendência. |
| `graficos_velocidade_otimizada_v4/` | Gráficos diários comparativos (Velocidade Real vs Otimizada e Buffers Brutos vs Filtrados). |
| `curva_convergencia_v4.png` | Gráfico da evolução do fitness ao longo das gerações do CMA-ES. |

---

## 🚀 Como Executar

### 1. Configurar Mapeamento da Linha (Opcional se já estiver configurado)
```bash
python assistente_configuracao.py
```

### 2. Rodar a Otimização e Digital Twin
```bash
python otimizador_velocidade_v4.py
```
*O script executará o CMA-ES, salvará os melhores parâmetros em `parametros_controle_v4.json`, gerará os gráficos comparativos na pasta `graficos_velocidade_otimizada_v4/` e recompilará a função autônoma.*

### 3. Teste Interativo de Bancada
```bash
python controlador_velocidade_live_v4.py
```

### 4. Execução em Produção via Grafana / InfluxDB
```bash
python controlador_velocidade_grafana_v4.py
```
