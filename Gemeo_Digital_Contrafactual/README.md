# Gêmeo Digital Contrafactual da Linha Legada (Pré-V4)

Módulo autônomo de engenharia para simulação contrafactual em tempo real (*Digital Shadow em Malha Fechada*).  
Ele calcula exatamente qual seria o comportamento de velocidade da enchedora e dos buffers caso o CLP antigo ainda estivesse controlando a fábrica sob os mesmos distúrbios operacionais reais.

---

## 1. Estrutura do Diretório

```
Gemeo_Digital_Contrafactual/
├── config.json                     # Arquivo de configuração idêntico ao config_opc_v4.json do V4 com setores, tags e parâmetros do legado
├── gerenciador_buffers.py          # Gestão física setor por setor (esteiras divididas em células discretas com sensores)
├── modelo_gemeo_legado.py          # Núcleo matemático: Balanço de massa espacial B2/B3, autômato PackML, rampa e ancoragem
├── cliente_opc_gemeo.py            # Cliente OPC UA assíncrono em tempo real com leitura de cada sensor e painel sinótico
├── simular_dataset_historico.py    # Script de reprodução contrafactual sobre logs históricos em CSV
├── gerar_graficos_contrafactual.py # Script de geração de gráficos industriais diários (dia a dia) e consolidado
├── graficos_diarios/               # Pasta contendo os gráficos de alta resolução separados dia a dia
│   ├── contrafactual_2026-10-02.png
│   └── contrafactual_2026-10-03.png
├── teste_unitario_gemeo.py         # Suíte de testes unitários automatizados (9 testes completos aprovados)
├── ARQUITETURA_E_MEMORIAL_TECNICO.md # Memorial descritivo detalhado de engenharia e fórmulas
└── README.md                       # Manual de uso e instruções operacionais
```

---

## 2. Modelagem por Setores e Sensores (Compatibilidade V4)

O Gêmeo Digital Contrafactual utiliza o **mesmo `config.json` do Otimizador V4 (`Controle_Velocidade_4/config_opc_v4.json`)**, reproduzindo a geometria real da esteira física:
- **Buffer B2 (Alimentação da Enchedora):** 10 setores discretos com suas respectivas tags OPC (ex: fotocélula de entrada no setor 10 `102B2`).
- **Buffer B3 (Descarga da Enchedora):** 12 setores discretos com suas respectivas tags OPC (ex: fotocélula de saída no setor 1 `125B3`).
- **Propagação Espacial e Balanço de Garrafas:** O acúmulo e esvaziamento das esteiras propaga-se setor a setor conforme a velocidade das máquinas a montante e a jusante.
- **Intertravamentos Reais do CLP Legado:** As decisões de corte e retomada do CLP antigo monitoram diretamente os sensores de fim de curso e fotocélulas discretas de estrela (`125B3` na saída e `102B2` na entrada) combinados com o balanço de massa dos setores.


---

## 3. Como Executar

### 3.1 Executar a Suíte de Testes Unitários
Para validar o funcionamento matemático, conservação de massa, intertravamentos do CLP legado, temporizadores TON, rampa do inversor e ancoragem PackML:

```bash
/home/antonio/Projetos/OtimizadorSegue/.venv/bin/python -m unittest teste_unitario_gemeo.py
```

### 3.2 Executar em Tempo Real via OPC UA
Para conectar ao servidor OPC da fábrica e iniciar o monitoramento em tempo real:

```bash
/home/antonio/Projetos/OtimizadorSegue/.venv/bin/python cliente_opc_gemeo.py
```

O cliente exibirá o painel sinótico contrafactual no terminal:
```
========================================================================================
 🏭 GÊMEO DIGITAL CONTRAFACTUAL DA LINHA LEGADA (PRÉ-V4) | 2026-10-03 23:10:00
----------------------------------------------------------------------------------------
 🟢 REAL (V4 ATIVO):    90,000 CPH | B2 Real:  75.0% | B3 Real:  25.0%
 🔴 LEGADO (SIMULADO):       0 CPH | B2 Virt:  80.0% | B3 Virt:  86.2%
 Estado CLP Legado: [BLOQUEADO_SAIDA_CHEIA] | Ancoragem: [LIVRE (Simulação)]
----------------------------------------------------------------------------------------
 📊 AUDITORIA DE GANHO CONTRAFACTUAL DO V4:
   • Garrafas Incrementais Salvas:     +45,210 gf
   • Volume Incremental em Hectolitros:  +160.50 hL
   • Ganho Real de OEE:                  +12.56 %
   • Microparadas Evitadas pelo V4:          12 ocorrências
========================================================================================
```

### 3.3 Simular um Dataset Histórico em CSV
Para reprocessar um arquivo de dados brutos (ex: as 36 horas do V4) e obter a comparação consolidada:

```bash
/home/antonio/Projetos/OtimizadorSegue/.venv/bin/python simular_dataset_historico.py
```

### 3.4 Gerar Gráficos de Auditoria e Desempenho (Dia a Dia e Consolidado)
Para gerar os painéis gráficos de alta resolução (`.png`), separados dia a dia no mesmo padrão do controlador V4:

```bash
/home/antonio/Projetos/OtimizadorSegue/.venv/bin/python gerar_graficos_contrafactual.py
```

O script cria a pasta `graficos_diarios/` e salva um gráfico completo por dia contendo EXCLUSIVAMENTE o perfil de velocidades em escala de 24 horas (00:00 às 24:00):
- `graficos_diarios/contrafactual_velocidade_2026-10-02.png`: Dia 02/10 (Real: 814.248 gf vs Legado: 580.978 gf | Saldo V4: +233.270 gf / +40,2%).
- `graficos_diarios/contrafactual_velocidade_2026-10-03.png`: Dia 03/10 (Real: 877.989 gf vs Legado: 421.800 gf | Saldo V4: +456.189 gf / +108,2%).

---

## 4. Principais Parâmetros de Configuração (`config.json`)

* **`servidor_opc.url`:** Endereço do servidor OPC UA da linha (ex: `opc.tcp://10.46.12.163:49500`).
* **`maquinas`:**
  * `velocidade_nominal`: Velocidade nominal de projeto da enchedora (ex: `90000.0` ou `94500.0` CPH).
  * `tag_velocidade_montante`: Tag OPC da Despaletizadora/ECI.
  * `tag_velocidade_atual`: Tag OPC da Enchedora.
  * `tag_velocidade_jusante`: Tag OPC do Pasteurizador.
  * `tag_status_maquina`: Tag booleana de status operacional do CLP.
* **`parametros_legado`:**
  * `limiar_corte_b3_pct`: Nível de buffer de saída para corte por acúmulo (ex: `85.0%`).
  * `limiar_retomada_b3_pct`: Nível de buffer de saída para alívio e religamento (ex: `65.0%`).
  * `limiar_corte_b2_pct`: Nível de buffer de entrada para corte por falta (ex: `15.0%`).
  * `limiar_retomada_b2_pct`: Nível de buffer de entrada para alívio e religamento (ex: `35.0%`).
  * `ton_bloqueio_s`: Tempo de persistência do temporizador TON para confirmar bloqueio (ex: `2.0s`).
  * `ton_retomada_s`: Tempo de persistência do temporizador TON para confirmar retomada (ex: `2.0s`).
  * `tempo_rampa_subida_s`: Tempo em segundos para o inversor legado acelerar de 0 a 100% nominal (ex: `15.0s`).
  * `tempo_ancoragem_parada_real_s`: Tempo contínuo de parada real (> 300s / 5 min) para reset determinístico de drift.
* **`buffers_capacidade`:**
  * `capacidade_garrafas_b2`: Capacidade física aproximada da mesa B2 em garrafas (ex: `2800.0`).
  * `capacidade_garrafas_b3`: Capacidade física aproximada da mesa B3 em garrafas (ex: `3500.0`).
* **`auditoria_envase`:**
  * `volume_garrafa_litros`: Volume unitário do vasilhame em litros (ex: `0.355` para garrafas de 355ml).

---

## 5. Auditoria de Ganho

O modelo gera 4 métricas oficiais para apresentação à gerência e auditoria industrial:
1. **Delta Garrafas:** Total acumulado de garrafas físicas a mais produzidas pelo V4 em comparação com o legado.
2. **Delta Hectolitros (hL):** Volume incremental de cerveja embalada (`Delta_Garrafas * Volume_Garrafa / 100`).
3. **Delta OEE (%):** Ganho percentual direto na Eficiência Global do Equipamento.
4. **Microparadas Evitadas:** Contagem de eventos onde o V4 manteve a linha rodando enquanto o CLP antigo teria caído em corte de esteira.

---

## 6. Fluxo de Engenharia: Do CSV ao Modelo em Tempo Real

1. **Dados Brutos (CSV):** O arquivo histórico (ex: `Panel Title-data-2026-10-03 21_55_56.csv`) fornece a série temporal com velocidades e buffers.
2. **Calibração Física:** O método `autocalibrar_capacidade()` extrai as capacidades das esteiras medindo o tempo de subida dos buffers quando as máquinas vizinhas desaceleram.
3. **Identificação de Regras:** Os limiares de corte (85%/15%) e rampa de aceleração (15s) são consolidados no `config.json`.
4. **Simulação Histórica:** O script `simular_dataset_historico.py` reprocessa o CSV e apura os ganhos de OEE e garrafas.
5. **Geração de Gráficos:** O script `gerar_graficos_contrafactual.py` gera as figuras comprobatórias em PNG.
6. **Execução em Produção:** O script `cliente_opc_gemeo.py` lê os mesmos sensores diretamente do CLP via OPC UA e roda a simulação contrafactual ao vivo.
