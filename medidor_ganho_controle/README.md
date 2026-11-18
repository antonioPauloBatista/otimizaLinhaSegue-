# Medidor de Ganho de Controle Industrial - Segue V4

Ferramenta em Python (CLI) para calcular, auditar e monitorar em tempo real o ganho físico de produção entregue pelo Controlador Segue V4, avaliando o desempenho da linha tanto quando o Segue está **LIGADO** quanto quando está **DESLIGADO**:

- **Com Segue LIGADO (`🟢 SEGUE LIGADO`):** Mede o ganho líquido real entregue (ou perca) frente à operação sem controle / contrafactual do CLP nativo.
- **Com Segue DESLIGADO (`🔴 SEGUE DESLIGADO`):** Mede a cada novo dado a oportunidade de vazão e o total de garrafas perdidas por manter a linha desabilitada vs o setpoint ótimo calculado pelo V4.
- **Confronto A/B Auditado:** Compara rigorosamente os períodos com e sem controle sob as mesmas condições físicas de estresse de buffer e rastejo.

Suporta **análise estática (batch)** de arquivos CSV, **monitoramento contínuo em tempo real de arquivos locais (`--online`)** e **streaming direto da API do Grafana / InfluxDB sem necessidade de arquivos intermediários (`--online-grafana`)**.

---

## Estrutura da Pasta

```
medidor_ganho_controle/
├── medir_ganho.py                    # Script executável CLI (Batch, Online CSV e Online Grafana)
├── config_medidor.json               # Configurações raw de conexão, filtros e tags
├── cliente_grafana.py                # Cliente de conexão e pooling direto na API do Grafana
├── README.md                         # Manual completo de uso, arquitetura e metodologia
└── grafico_ganho_gemeo_habilitado.png # Evidência gráfica de validação contrafactual
```

---

## Funcionamento do Cálculo a Cada Novo Dado

A cada nova amostra recebida da linha (via streaming do Grafana ou apensada no CSV), o script calcula imediatamente:

1. **Estado Operacional da Amostra:**
   - Detecta automaticamente se o Segue está Habilitado (`segue_habilitado == True`) ou em Bypass / Modo Sombra (`segue_habilitado == False`).
   - Identifica se a máquina física está em parada real (`v_atual_cph < 1.000 CPH`), evitando acúmulo de produção fictícia em paradas.

2. **Quando o Segue está LIGADO:**
   - Confronta a velocidade real física medida (`v_atual_cph`) contra o baseline sem controle (`velocidade_maquina_sem_controle_cph` ou média sem controle).
   - Apresenta:
     - Ritmo instantâneo: Ganho Real (`+CPH`) ou Perca Real (`-CPH`).
     - Volume acumulado na sessão: Saldo líquido de garrafas a mais ou a menos.
     - Projeção no turno de 8 horas.

3. **Quando o Segue está DESLIGADO:**
   - Confronta a velocidade real da máquina física contra a velocidade sugerida pelo V4 (`v_setpoint_cph`).
   - Apresenta:
     - Oportunidade V4: Quanto a máquina poderia estar envasando a mais caso o Segue estivesse ligado (`+CPH`).
     - Perda Acumulada por Segue OFF: Total de garrafas que deixaram de ser produzidas na sessão.
     - Projeção no turno de 8 horas com Segue ativo.

---

## Configuração Raw Não-Inline (`config_medidor.json`)

Para não precisar digitar parâmetros longos na linha de comando, edite o arquivo `config_medidor.json`:

```json
{
  "modo": "online-grafana",

  "dados_grafana": {
    "url": "http://10.186.99.7:3000",
    "user": "admin",
    "password": "!ambev2021",
    "datasource": "4",
    "bucket": "soda",
    "measurement": "512_v4",
    "coluna_velocidade_real": "v_atual_cph",
    "coluna_trava_entrada": "trava_entrada_int",
    "coluna_segue_habilitado": "segue_habilitado",
    "coluna_buffer_entrada_b2": "b2_pct",
    "coluna_buffer_saida_b3": "b3_pct"
  },

  "dados_calculo_analises": {
    "trava_filtro": "0",
    "limiar_buffer_saida_gargalo_pct": 74.37,
    "limiar_buffer_entrada_min_pct": 30.05
  }
}
```

Ao executar sem parâmetros adicionais, o `medir_ganho.py` carrega automaticamente esse arquivo:

```bash
.venv/bin/python medidor_ganho_controle/medir_ganho.py
```

O medidor possui **compatibilidade universal**, aceitando tanto arquivos nativos quanto configurações herdadas do projeto (`Controle_Velocidade_4/config_colunas.json` ou `parametros_query.json`):

```bash
# Apontando para o config da linha 512 do V4
.venv/bin/python medidor_ganho_controle/medir_ganho.py --config Controle_Velocidade_4/config_colunas.json

# Apontando para o JSON de queries do SODA
.venv/bin/python medidor_ganho_controle/medir_ganho.py --config parametros_query.json
```

---

## Modos de Operação

Execute sempre utilizando o ambiente virtual do projeto: `.venv/bin/python`.

### 1. Inspecionar Colunas Disponíveis (`--listar-colunas`)

```bash
# Inspecionar direto no Grafana / InfluxDB:
.venv/bin/python medidor_ganho_controle/medir_ganho.py --listar-colunas

# Inspecionar em um arquivo CSV:
.venv/bin/python medidor_ganho_controle/medir_ganho.py "dados.csv" --listar-colunas
```

---

### 2. Streaming Direto da API do Grafana (`--online-grafana`)

Conecta na API do Grafana via rede da fábrica, captura a telemetria a cada ciclo e atualiza o ganho ou perca a cada novo dado que chega:

```bash
.venv/bin/python medidor_ganho_controle/medir_ganho.py --online-grafana --measurement 512_v4 --trava 0
```

* **Exemplo de saída contínua do terminal (atualizada a cada ciclo com Segue LIGADO):**
  ```text
  [14:20:15] 🟢 SEGUE LIGADO    | Trava: 0 | V_Real: 85,200 CPH (SemCtrl: 80,000) | 🏆 Ganho Real: +12,450 gf (+5,200 CPH | +6.5%) | Turno 8h: +41,600 gf | Amostras: 145
  ```

* **Exemplo de saída contínua do terminal (atualizada a cada ciclo com Segue DESLIGADO):**
  ```text
  [16:35:26] 🔴 SEGUE DESLIGADO | Trava: 0 | V_Real: 70,129 CPH (SP V4: 88,976) | ⚡ Oportunidade V4: +84 gf (+15,056 CPH | +21.5%) [Perda Segue OFF: -84 gf] | Turno 8h: +120,452 gf | Amostras: 2
  ```

* Ao pressionar **Ctrl+C**, encerra a sessão com segurança e imprime o **Relatório Consolidado Completo**.

---

### 3. Streaming via Arquivo CSV Local (`--online`)

Monitora um arquivo CSV local à medida que novas linhas são gravadas pelo controlador ou pela coleta:

```bash
.venv/bin/python medidor_ganho_controle/medir_ganho.py "dados_coleta.csv" --trava 0 --online
```

---

### 4. Auditoria Estática / Batch de Arquivo CSV

Executa a auditoria completa de um arquivo gravado (seja contendo apenas Segue LIGADO, apenas Segue DESLIGADO, ou ambos):

```bash
# Executa para arquivo com trava filtrada (ex: Trava 0 = fluxo livre):
.venv/bin/python medidor_ganho_controle/medir_ganho.py "Panel Title-data-2026-11-17 17_35_46.csv" --trava 0

# Executa para todas as condições de trava:
.venv/bin/python medidor_ganho_controle/medir_ganho.py "Panel Title-data-2026-11-12 15_52_19.csv" --trava all
```

---

## Exemplo Real de Relatório Consolidado

```text
══════════════════════════════════════════════════════════════════════════
 RELATÓRIO CONSOLIDADO: AVALIAÇÃO DE GANHO / PERCA DO SEGUE V4 [TRAVA ENTRADA == all]
══════════════════════════════════════════════════════════════════════════
 🟢 CENÁRIO: SEGUE LIGADO (OPERAÇÃO ATIVA NO CONTROLE V4)
──────────────────────────────────────────────────────────────────────────
 • Amostras Monitoradas    : 2319 ciclos (6.44 horas de controle)
 • Ritmo Médio Entregue    : 68,263 garrafas/hora
 • Ritmo de Referência     : 93,862 garrafas/hora (Coluna Contrafactual 'velocidade_maquina_sem_controle_cph')
 • 🏆 PERCA / DESACELERAÇÃO: -164,901 garrafas (-25,599 CPH | -27.27%)
 • 📦 Projeção no Turno    : -204,793 garrafas em 8h
 • 🛑 Paradas Físicas (0)  : 11.7 minutos (70 ocorrências)
 • 🐢 Tempo em Rastejo     : 12.4 minutos/hora (< 20,000 CPH)
 • 🎯 Sob Estresse Buffer  : Manteve 45,268 CPH sob buffer de saída elevado
──────────────────────────────────────────────────────────────────────────
 🔴 CENÁRIO: SEGUE DESLIGADO (CLP NATIVO / MODO SOMBRA / BYPASS)
──────────────────────────────────────────────────────────────────────────
 • Amostras Monitoradas    : 561 ciclos (1.56 horas sem controle)
 • Ritmo Médio da Máquina  : 63,280 garrafas/hora
 • Ritmo Recomendado V4    : 87,691 garrafas/hora (Setpoint V4 em Modo Sombra 'v_setpoint_cph')
 • ⚡ OPORTUNIDADE NÃO GANHA: +38,041 garrafas poderiam ter sido envasadas
 • 🔻 PERDA POR SEGUE OFF  : -38,041 garrafas perdidas (-24,411 CPH | +38.58%)
 • 📦 Impacto no Turno     : +195,289 garrafas em 8h com Segue ativo
 • 🛑 Paradas Físicas (0)  : 0.0 minutos (0 ocorrências)
 • 🐢 Tempo em Rastejo     : 18.0 minutos/hora (< 20,000 CPH)
 • 🎯 Sob Estresse Buffer  : Caiu para 26,683 CPH sob buffer de saída elevado
──────────────────────────────────────────────────────────────────────────
 ⚖️ CONFRONTO A/B AUDITADO: PERÍODO COM SEGUE vs PERÍODO SEM SEGUE
──────────────────────────────────────────────────────────────────────────
 • 🏆 GANHO REAL COMPROVADO: +32,098 GARRAFAS A MAIS (+4,983 CPH | +7.87%)
 • 📦 Impacto no Turno     : +39,863 garrafas a mais por dia de 8h
 • 🛑 Redução de Rastejos  : Rastejo (< 20k CPH) reduziu em +30.9%
 • ⏱️ Tempo Salvo de Linha : Economizou 35.7 minutos de lentidão/rastejo
 • 🎯 Sob Gargalo (B3>=70%): Sem Segue: 26,683 CPH -> Com Segue: 45,268 CPH (+69.7%)
──────────────────────────────────────────────────────────────────────────
══════════════════════════════════════════════════════════════════════════
```

---

## Tabela de Parâmetros da CLI

| Argumento | Tipo | Padrão | Descrição |
| :--- | :---: | :---: | :--- |
| `csv` | Posicional | `None` | Caminho do arquivo CSV (opcional no modo `--online-grafana`). |
| `--online-grafana` | Flag | `False` | Ativa o streaming contínuo direto da API do Grafana. |
| `--online` | Flag | `False` | Ativa o monitoramento contínuo de arquivo CSV local. |
| `--measurement` | String | `"512_v4"` | Nome da medição/linha no InfluxDB (ex.: `512`, `512_v4`). |
| `--trava` | String | `None` | Filtra por estado da trava: `0` (livre), `1` (bloqueada) ou `all`. |
| `--janela` | String | `"4h"` | Janela histórica inicial carregada na partida (`2h`, `4h`, `8h`, `24h`). |
| `--intervalo` | Float | `2.0` / `5.0` | Intervalo em segundos entre varreduras de rede ou de disco. |
| `--url` | String | `"http://10.186.99.7:3000"` | URL base da interface web / API do Grafana (ou herdada do JSON). |
| `--user` | String | `"admin"` | Usuário de autenticação do Grafana. |
| `--password` | String | `"!ambev2021"` | Senha de autenticação do Grafana. |
| `--token` | String | `""` | Service Account Token do Grafana (Bearer Token). |
| `--ds` | String | `"4"` / `"17"` | Identificador ou nome do Datasource InfluxDB no Grafana. |
| `--bucket` | String | `"soda"` / `"Segue"` | Bucket / Database do InfluxDB. |
| `--csv-sem-controle` | String | `None` | Segundo CSV de referência histórica para comparação A/B. |
| `--listar-colunas` | Flag | `False` | Inspeciona e lista todas as variáveis disponíveis na fonte. |
