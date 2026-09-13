# Controle de Velocidade V4 (Data-Driven Feedforward & Slew-Rate)

Este diretório contém a versão **V4** do sistema inteligente de controle de velocidade e otimização de linhas de envase (cervejaria / refrigerantes), com foco na máquina mestra (Enchedora / Filler).

A versão V4 incorpora todas as capacidades da V3 com evoluções de engenharia para resolver limitações de sensores em campo e proteger a integridade mecânica da máquina.

---

## 🌟 Principais Inovações da V4

1. **Tratamento de Dados 100% em Software (Zero Intervenção em Campo):**
   - **Filtro Mediano Móvel (Janela de 3 amostras):** Elimina pulsos espúrios e picos isolados decorrentes de sensores óticos desordenados (ex: desvios súbitos de 40% que retornam em 30 segundos).
   - **Debounce de Persistência:** Diferencia garrafas passando rapidamente de acúmulo consolidado na esteira.
   - **EWMA (Exponentially Weighted Moving Average):** Converte a comutação discreta das fotocélulas em uma curva suave contínua de densidade de acúmulo (fator α = 0.65).

2. **Balanço de Massa Feedforward (Máquinas Vizinhas):**
   - Monitora em tempo real a velocidade da máquina na entrada (V_in, ex: ECI) e da máquina na saída (V_out, ex: Pasteurizador).
   - Não depende apenas do nível acumulado dos buffers: antecipa o desvio antes que o buffer atinja o limite.

3. **Retomada Sincronizada Pós-Parada com Tendência:**
   - Calcula a taxa de aceleração da máquina da saída (dV_out/dt).
   - Quando a máquina na saída destrava e começa a acelerar, a enchedora inicia imediatamente sua rampa de aceleração sem esperar o buffer de saída esvaziar por completo, eliminando o tempo morto de linha.

4. **Proteção Mecânica Ativa (Slew-Rate Limiter em Software):**
   - O setpoint despachado pelo algoritmo é estritamente limitado por uma taxa máxima de variação (ΔV_max / Δt).
   - Elimina degraus bruscos, socos mecânicos no carrossel da enchedora, quebra de garrafas e perda de produto por espumamento (CO₂).

5. **Modo Sprint / Sobrevelocidade Condicionada:**
   - Permite que a enchedora opere acima da nominal (ex: 101% a 105%) quando a linha está completamente desafogada (buffers de entrada e saída em zona segura e máquinas vizinhas rodando a ≥ 90% da nominal).

6. **Rastreamento de Eventos de Parada e Modulação em JSON (Início e Fim):**
   - Registra estruturadamente em arquivo JSON cada ocorrência de modulação ou parada (quando a enchedora opera fora de 100% nominal), contendo timestamp de início, timestamp de término (fim), duração, código do motivo e máquina causadora.
   - **Regra de Processo:** Se a enchedora estiver operando em 100% nominal (regime pleno equilibrado), nenhum evento de perda é gerado no JSON.

---

## 📁 Ecossistema de Arquivos Gerados Automaticamente

Assim como na versão anterior (V3), ao executar o [`otimizador_velocidade_v4.py`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/otimizador_velocidade_v4.py), o sistema calibra os dados históricos da linha e **gera ou atualiza automaticamente o ecossistema completo de arquivos**:

| Arquivo / Pasta | Tipo | Função e Conteúdo |
| :--- | :--- | :--- |
| **`funcao_controle_v4.py`** | Código Python | Módulo autônomo com a classe `ControladorVelocidadeV4`, contendo os limiares sintonizados, rampas suaves, filtros e registro de eventos em JSON. Pronto para execução no CLP ou Edge. |
| **`controlador_velocidade_live_v4.py`** | Script Live | Simulador interativo de bancada via terminal para testes de hipóteses com Reason Code (ID 0 a 99) e arquivo JSON. |
| **`controlador_velocidade_grafana_v4.py`** | Script Live | Controlador de tempo real conectado via API ao Grafana/InfluxDB. Criado automaticamente do zero ou sincronizado com a velocidade nominal calibrada. |
| **`parametros_controle_v4.json`** | Dados JSON | Limiares ótimos calculados pelo CMA-ES (buffers B1-B4, rampas, EWMA, fatores de modulação e sprint). |
| **`parametros_query.json`** | Configuração InfluxQL | Mapeamento e credenciais da query para consulta do contador físico de garrafas no InfluxDB (DB `soda`, datasource `9`). |
| **`dados_velocidade_otimizada_v4.csv`** | Dataset CSV | Série temporal completa contendo velocidade real vs. otimizada, colunas de buffers brutos e filtrados, motivos e máquinas causadoras. |
| **`eventos_motivos_historico_v4.json`** | Eventos JSON | Histórico cronológico de todos os períodos de perda com início, término, duração e máquina causadora. |
| **`resumo_producao_live_v4.txt`** | Relatório Único | Resumo consolidado de proporção do tempo ligado (uptime), produção em garrafas e causas de perda por tempo (arquivo único fixo, sem poluir a pasta). |
| **`resumo_producao_live_v4.json`** | Dados JSON | Estrutura consolidada em JSON com tempos ligados/parados, detalhamento de velocidade e produção acumulada. |
| **`relatorio_otimizacao_v4_<data>.txt`** | Relatório | Balanço executivo da calibração: ganho de garrafas, redução de socos mecânicos e paradas evitadas. |
| **`graficos_velocidade_otimizada_v4/`** | Gráficos PNG | Pasta contendo os gráficos diários comparativos de todos os dias analisados no histórico. |
| **`curva_convergencia_v4.png`** | Gráfico PNG | Gráfico demonstrativo da evolução da função custo ao longo das iterações da calibração. |

---

## 🌐 Integração Live Grafana / InfluxDB

### 1. Conexão Resiliente e Autodescoberta
O módulo [`controlador_velocidade_grafana_v4.py`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/controlador_velocidade_grafana_v4.py) opera como um controlador contínuo em malha supervisória, conectando-se a cada 30 segundos ao Grafana:
- **Janela de 30 dias com `last()`**: Resgata o último dado válido de cada tag mesmo que um sensor tenha ficado inativo temporariamente.
- **`group()` antes do `pivot()`**: Garante que o InfluxDB não retorne erro HTTP 400 ao pivotar tags com cardinalidades distintas.
- **Filtro Numérico Estrito**: Lê com segurança medições de `accumulation_percentage` e `speed_actual_cph`.
- **Suporte a Aliases**: Encontra automaticamente variáveis da linha `NS-512` (`lgf_to_uip`, `uip_to_ech`, `ech_to_pz`, `pz_to_rot`, `filler_1`, `eci_1`, `pasteurizer`) ou mapeamentos customizados de `config_colunas.json`.

### 2. Formas de Configuração
- **Linha de Comando (CLI):**
  ```bash
  python controlador_velocidade_grafana_v4.py --url "http://172.23.224.145:3000" --measurement "NS-512" --bucket "Segue" --ds "13"
  ```
- **Arquivo `config_colunas.json`:**
  ```json
  {
    "Grafana_URL": "http://172.23.224.145:3000",
    "Grafana_Measurement": "NS-512",
    "Grafana_Bucket": "Segue",
    "Grafana_Datasource": "13"
  }
  ```
- **Direto no Topo do Script `controlador_velocidade_grafana_v4.py`:**
  Editando as variáveis globais `GRAFANA_URL`, `MEASUREMENT`, etc.

### 3. Diagnóstico e Resumo Consolidado do Tempo Ligado (`Ctrl+C`)
- **Resumo do Tempo Ligado (Uptime vs Parada)**: Mostra claramente o tempo em que a enchedora real passou ligada vs parada e quanto o controlador V4 proporcionou de tempo ativo adicional (uptime recuperado).
- **Detalhamento do Tempo Ligado**: Proporção do tempo em operação nominal plena (100%), sprint (>100%) e modulação suave (<100%).
- **Resumo de Produção no Tempo Ligado**: Garrafas reais vs V4, saldo de garrafas geradas a mais e vazão média efetiva quando em operação.
- **Consolidação de Causas/Falhas**: Em vez de gerar vários registros ou relatórios picados, consolida o tempo total e a porcentagem que cada causa ou máquina roubou da linha em uma tabela limpa.
- **Arquivo Único Fixo (`resumo_producao_live_v4.txt`)**: Não gera múltiplos arquivos com datas diferentes; mantém sempre atualizado o resumo da sessão mais recente em arquivo fixo de texto e em JSON (`resumo_producao_live_v4.json`).

### 4. Validação Física de Produção Real via Contador (`parametros_query.json`)
Para garantir auditoria precisa dos ganhos de produção e comprovar que o aumento de velocidade se converteu em garrafas físicas envasadas (e não em esteira girando a vazio durante purgas ou falta de produto), o controlador V4 integra a leitura em tempo real do **Contador Totalizador de Embalagens**:

- **Localização do Arquivo de Configuração:**
  O arquivo fica na mesma pasta do script live: [`Controle_Velocidade_4/parametros_query.json`](file:///home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/parametros_query.json).
  O script busca prioritariamente o arquivo na sua própria pasta (`os.path.dirname(__file__)`), permitindo que seja executado de qualquer diretório sem necessidade de argumentos adicionais.

> [!IMPORTANT]
> **Arquitetura de Fontes de Dados Distintas (Dual-Datasource):**
> - **Contador Físico de Garrafas:** Consulta realizada no banco **`soda-template`** (Datasource ID `8` - Nome: `SODA Template`, UID: `qbSajtHSz`) via linguagem **InfluxQL** contra a tabela `"Filler"`.
> - **Buffers (B1..B4) e Velocidades:** Consultas dinâmicas de esteiras e controle executadas no bucket **`Segue`** (Datasource ID `13` - Nome: `Segue`, UID: `ef1kgorem6by8f`) via linguagem **FLUX**.
> 
> Essa separação de bancos é mandatória: o bucket `Segue` armazena telemetrias de alta frequência das esteiras (porcentagem de acúmulo e velocidades), enquanto a base `soda-template` armazena os totalizadores industriais de produção das máquinas.

- **Estrutura do `parametros_query.json`:**
  ```json
  {
    "config": {
      "grafana_url": "http://172.23.224.145:3000",
      "grafana_user": "admin",
      "grafana_password": "!ambev2021",
      "database": "soda-template",
      "datasource_selector": "8"
    },
    "queries": [
      {
        "description": "Enchedora contagem de produto",
        "equipment_type": "Filler",
        "tags": {
          "equipment_name": "NS-05410-ENCHEDORA 01"
        },
        "fields": {
          "Packaging Machine Production Counter - Total": "1.14.37.162.2.24-1.32-1.0.7275"
        }
      }
    ]
  }
  ```

- **Mecânica de Validação Ciclo a Ciclo (a cada 30 segundos):**
  1. **Consulta Instantânea via InfluxQL:** Executa uma requisição ultra-rápida (menos de 15 ms) via proxy da API do Grafana resgatando o último valor registrado:
     `SELECT LAST("Packaging Machine Production Counter - Total") FROM "Filler" WHERE "equipment_name"::tag = 'NS-05410-ENCHEDORA 01'`
  2. **Cálculo da Produção Física Real:**
     `Delta_Contador = Contador_Atual - Contador_Anterior`
  3. **Detecção de Falso Giro (Motor Girando em Vazio):**
     Se a velocidade do motor estiver alta (ex: 45.000 garrafas/h), mas `Delta_Contador == 0`, o sistema detecta e exibe:
     `⚠️ Validação Física: Motor Girando sem Garrafas (+0 gf no sensor) | Contador: 15,420,800 gf`
     Dessa forma, a produção real registrada é zero, impedindo a geração de ganhos fictícios.
  4. **Confirmação de Produção Real:**
     Havendo incremento físico (`Delta_Contador > 0`), o valor do sensor é registrado como a produção real do ciclo:
     `✅ Validação Física: Produção Real Confirmada: +380 gf físicas no ciclo | Contador: 15,421,150 gf`
  5. **Regra de Parada Real:**
     Quando a máquina real está parada (0 garrafas/h), o controlador V4 também para em 0 garrafas/h em segurança:
     `🛑 Validação Física: Parada Real Confirmada (+0 gf) | Contador: 15,420,800 gf`
  6. **Fallback Resiliente:**
     Caso o contador físico esteja inacessível ou offline, o sistema estima a produção pela velocidade do motor com aviso explícito no console `(Estimada por Velocidade)`, mantendo a operação contínua.

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
*O script calibra os parâmetros, salva os resultados, recompila a função autônoma e gera ou sincroniza todos os módulos live.*

### 3. Teste Interativo de Bancada
```bash
python controlador_velocidade_live_v4.py
```

### 4. Execução em Produção via Grafana / InfluxDB
```bash
python controlador_velocidade_grafana_v4.py
```
