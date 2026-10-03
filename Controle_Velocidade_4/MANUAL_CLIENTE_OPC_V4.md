# Manual Técnico e Operacional: Cliente OPC UA V4 em Tempo Real

Este manual descreve o funcionamento, a configuração e a operação do **Cliente OPC UA V4** para controle de velocidade e otimização da linha de envase.

O módulo opera de forma assíncrona, conectando o **Controlador de Velocidade V4** (`ControladorVelocidadeV4`) diretamente ao CLP da fábrica através de:
- **Modo Subscription (Assinatura de Eventos DataChange):** Atualização instantânea dos sensores de esteira e velocidades de máquinas sem sobrecarregar a rede com *polling*.
- **Cálculo Geométrico Multi-Setor de Buffers:** Consolidação do nível percentual (0 a 100%) a partir das dimensões físicas (comprimento e largura em metros) de cada setor da esteira e do estado do sensor.
- **Escrita Segura de Setpoint:** Gravação contínua da velocidade ideal na tag do CLP com adequação automática de tipos de dados (`Double`, `Float`, `Int32`).
- **Watchdog Heartbeat:** Pulso periódico de vida no CLP para garantia de segurança e retorno a modo manual/local caso ocorra falha de comunicação (*Fail-Safe*).

---

## 1. Arquitetura da Solução e Fluxograma no Terminal

A cada ciclo de controle, o terminal renderiza um **Fluxograma Sinótico da Linha em Tempo Real** espelhando a interface supervisória da fábrica:

```text
==========================================================================================================
 LINHA 512 | Fábrica: Uberlândia | Máquina: ECH512001 | Modulação: ATIVA (MODULAÇÃO) | Decisão: 87,412 CPH [ 92.5% ]
 Bloco Ativo: [ ACÚMULO ECH-PZ ] Acúmulo de Garrafas na Saída | 🛡️ MODO SOMBRA (APENAS LEITURA - SEM ESCRITA NO CLP)
----------------------------------------------------------------------------------------------------------
 FLUXOGRAMA SINÓTICO DA LINHA EM TEMPO REAL:

  [B1] [██░░] 50.0% ─> ┌──────────────┐          ┌──────────────┐          ┌──────────────┐          ┌──────────────┐
                       │  DPL512001   │   ──B2─> │  ECH512001   │   ──B3─> │   PZ512001   │   ──B4─> │  EPC512001   │
                       │   90,000 CPH │ [███░] 60%│   82,000 CPH │ [████] 82%│        0 CPH │ [█░░░] 25%│   94,500 CPH │
                       └──────────────┘          └──────┬───────┘          └──────────────┘          └──────────────┘
                                                        │
                                                        ▼
                                             ┌─────────────────────┐
                                             │ SETPOINT V4 RECOM.  │
                                             │   87,412 CPH (92.5%)│
                                             └─────────────────────┘
----------------------------------------------------------------------------------------------------------
 📊 COMPARAÇÃO: Setpoint V4: 87,412 CPH  vs  Real no CLP: 82,000 CPH  (Diferença: +5,412 CPH)
 🔍 CAUSA-RAIZ: Máquina: ECI (Entrada da Enchedora) | Watchdog HB: Desativado (Modo Sombra)
 ⚠️  AVISO: Setpoint NÃO gravado no CLP pois o MODO SOMBRA está ativo.
==========================================================================================================
```

---

## 2. Como Funciona o Cálculo dos Buffers (Esteiras)

Cada buffer (B1, B2, B3, B4) é dividido em **setores físicos**, exatamente como parametrizado na tela de supervisão:

### Fórmulas de Cálculo:
1. **Área Física do Setor (m²):**
   ```
   Área_Setor = Comprimento (m) x Largura (m)
   ```
2. **Capacidade Total da Esteira (m²):**
   ```
   Área_Total = Soma das áreas de todos os setores habilitados
   (ou o valor fixado no parâmetro 'capacidade_area_total_m2')
   ```
3. **Área Incremental de Cada Setor (%):**
   ```
   Área_Incremental (%) = (Área_Setor / Área_Total) x 100
   ```
4. **Condição de Ocupação do Sensor:**
   - **Contato de Sinal = False:** Típico de sensores ópticos industriais com feixe retrorrefletivo. Quando há garrafas interrompendo o feixe, o sinal vai para `False` (0). Logo, `Sinal == False` indica **setor cheio/ocupado**.
   - **Contato de Sinal = True:** Típico de sensores indutivos ou contatos normalmente abertos. Quando há garrafas, o sinal vai para `True` (1).
5. **Nível Total do Buffer (%):**
   ```
   Nível_Buffer (%) = Soma da Área_Incremental (%) de todos os setores ocupados
   ```

### Exemplo Real (Buffer B2 da Linha Segue - 9 Sensores):
Com base nos dados reais configurados em `config_opc_v4.json` (capacidade de 32.0 m²):

| Ordem | Tag OPC UA | Comprimento | Largura | Área (m²) | Área Incremental | Contato | Ocupação |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| 1 | `...SEGUE.DPL-ECH.106B2` | 2.90 m | 0.40 m | 1.16 m² | **3.63 %** | False | Garrafa se Sinal=False |
| 2 | `...SEGUE.DPL-ECH.105B3` | 2.81 m | 0.40 m | 1.12 m² | **3.51 %** | False | Garrafa se Sinal=False |
| 3 | `...SEGUE.DPL-ECH.105B2` | 2.70 m | 1.13 m | 3.05 m² | **9.54 %** | False | Garrafa se Sinal=False |
| 4 | `...SEGUE.DPL-ECH.104B2` | 3.26 m | 0.93 m | 3.03 m² | **9.48 %** | False | Garrafa se Sinal=False |
| 5 | `...SEGUE.DPL-ECH.103B3` | 6.88 m | 0.93 m | 6.40 m² | **20.00 %** | False | Garrafa se Sinal=False |
| 6 | `...SEGUE.DPL-ECH.103B2` | 2.73 m | 0.99 m | 2.70 m² | **8.45 %** | False | Garrafa se Sinal=False |
| 7 | `...SEGUE.DPL-ECH.102B5` | 4.06 m | 0.94 m | 3.82 m² | **11.93 %** | False | Garrafa se Sinal=False |
| 8 | `...SEGUE.DPL-ECH.102B4` | 4.39 m | 0.97 m | 4.26 m² | **13.31 %** | False | Garrafa se Sinal=False |
| 9 | `...SEGUE.DPL-ECH.102B3` | 3.70 m | 0.94 m | 3.48 m² | **10.87 %** | False | Garrafa se Sinal=False |

Se os sensores 5 e 1 forem acionados, o buffer B2 reporta instantaneamente:
```
Nível B2 = 20.00% + 3.63% = 23.63%
```

---

## 3. Dicionário Completo de Parâmetros (`config_opc_v4.json`)

O arquivo reúne todas as definições da planta em um único local, dividido em 6 blocos operacionais:

```json
{
  "identificacao_linha": { ... },
  "servidor_opc": { ... },
  "heartbeat": { ... },
  "maquinas": { ... },
  "buffers": { "B1": { ... }, "B2": { ... }, "B3": { ... }, "B4": { ... } },
  "controle": { ... },
  "telemetria_influx": { ... }
}
```

### 3.1 Identificação da Linha (`identificacao_linha`)
Mapeia os nomes das máquinas e a identificação do processo para logs, relatórios e sinóticos:

| Parâmetro | Tipo | Exemplo | Descrição |
| :--- | :--- | :--- | :--- |
| `linha` | String | `"512"` | Número ou identificador da linha de produção. |
| `fabrica` | String | `"Equatorial"` | Nome da cervejaria ou planta industrial. |
| `nome_montante` | String | `"DPL512001"` | Tag/Nome da máquina anterior (ex: Despaletizadora). |
| `nome_principal` | String | `"ECH512001"` | Tag/Nome da máquina governada pelo Segue (ex: Enchedora). |
| `nome_jusante` | String | `"PZ512001"` | Tag/Nome da máquina seguinte (ex: Pasteurizador). |
| `nome_pos_jusante` | String | `"EPC512001"` | Tag/Nome da máquina pós-saída (ex: Rotuladora/Empacotadora). |

### 3.2 Conexão com o CLP (`servidor_opc`)
Configura o endpoint e os parâmetros de rede do protocolo OPC UA:

| Parâmetro | Tipo | Padrão | Descrição |
| :--- | :--- | :--- | :--- |
| `url` | String | `"opc.tcp://10.46.12.163:49500"` | Endpoint do servidor OPC UA do CLP ou Gateway. |
| `usuario` | String | `""` | Usuário de autenticação (deixar vazio para anônimo). |
| `senha` | String | `""` | Senha de autenticação (deixar vazio para anônimo). |
| `timeout_s` | Float | `5.0` | Tempo limite em segundos para requisições síncronas. |
| `reconectar_delay_s` | Float | `3.0` | Tempo de espera antes de tentar reconectar caso o CLP caia. |
| `publishing_interval_ms` | Integer | `500` | Taxa de atualização da assinatura de dados do CLP em ms. |

### 3.3 Watchdog Heartbeat (`heartbeat`)
Garante a segurança mecânica da linha contra travamentos de software ou falhas de rede:

| Parâmetro | Tipo | Padrão | Descrição |
| :--- | :--- | :--- | :--- |
| `tag` | String | `"ns=2;s=..._SG_HB"` | Tag OPC UA do watchdog no CLP. |
| `intervalo_s` | Float | `1.0` | Frequência de envio do pulso de vida em segundos. |
| `modo` | String | `"pulse_one"` | Estratégia de handshake: `"pulse_one"` (escreve 1 e CLP zera), `"toggle"` (inverte bit) ou `"counter"` (contador 0 a 32767). |
| `descricao` | String | `""` | Texto explicativo da rotina para operadores. |

### 3.4 Máquinas e Setpoint (`maquinas`)
Define as tags de medição e a interface de comando de velocidade:

| Parâmetro | Tipo | Exemplo | Descrição |
| :--- | :--- | :--- | :--- |
| `tag_velocidade_montante` | String | `"ns=2;s=...DPL512001_S"` | Tag de leitura da velocidade da máquina de entrada (DPL) em CPH. |
| `tag_velocidade_atual` | String | `"ns=2;s=...ECH512001_S"` | Tag de leitura da velocidade real da enchedora em CPH. |
| `tag_velocidade_jusante` | String | `"ns=2;s=...PZ512001_S"` | Tag de leitura da velocidade do pasteurizador (PZ) em CPH. |
| `tag_escrita_setpoint` | String | `"ns=2;s=..._SG_SP_W"` | Tag do CLP onde o setpoint calculado é escrito. |
| `unidade_escrita_setpoint` | String | `"percentual"` | `"percentual"` (envia 0 a 103%) ou `"cph"` (envia em garrafas/h). |
| `tag_segue_habilitado` | String | `"ns=2;s=..._SG_EN_BT"` | Chave física/IHM de habilitação do Segue. Quando `False`, entra em bypass. |
| `tag_status_maquina` | String | `"ns=2;s=..._STATUS"` | Tag booleana do status operacional da máquina no CLP (para telemetria de parada própria). |
| `velocidade_nominal` | Float | `90000.0` | Velocidade nominal de regime normal da máquina em CPH. |

### 3.5 Setores dos Buffers (`buffers.B1` a `buffers.B4`)
Mapeia a geometria física e os sensores ópticos de cada esteira de acúmulo:

| Parâmetro | Tipo | Descrição |
| :--- | :--- | :--- |
| `nome` | String | Nome descritivo do buffer (ex: "B2 - Entrada Imediata DPL-ECH"). |
| `capacidade_area_total_m2` | Float | Área total física da esteira em metros quadrados. |
| `setores[].ordem` | Integer | Sequência do sensor na esteira (1, 2, 3...). |
| `setores[].tag` | String | Endereço OPC UA do sensor digital. |
| `setores[].comprimento_m` | Float | Comprimento da seção coberta pelo sensor em metros. |
| `setores[].largura_m` | Float | Largura da esteira naquele setor em metros. |
| `setores[].contato_ativo` | Boolean | `false` se garrafa corta o feixe (sinal 0 = setor ocupado). `true` se 1 = ocupado. |
| `setores[].habilitado` | Boolean | Permite isolar um sensor em pane sem parar o sistema (`true`/`false`). |
| `setores[].descricao` | String | Identificação mecânica da fotocélula (ex: "Sensor 106B2"). |

### 3.6 Parâmetros do Controlador Segue (`controle`)
Configura a dinâmica matemática, rampas, histereses e segurança do algoritmo:

| Parâmetro | Tipo | Padrão | Descrição |
| :--- | :--- | :--- | :--- |
| `ciclo_controle_s` | Float | `10.0` | Intervalo do loop de otimização em segundos (ideal para esteiras de garrafas). |
| `tempo_rampa_subida_s` | Float | `10.0` | Tempo em segundos para aceleração suave (0 a 100%), protegendo garrafas contra tombamento. |
| `tempo_rampa_descida_s` | Float | `8.0` | Tempo em segundos para desaceleração controlada. |
| `banda_morta_cph` | Float | `100.0` | Variação mínima em CPH necessária para enviar novo valor ao inversor, evitando hunting. |
| `fator_sprint` | Float | `1.03` | Multiplicador de velocidade em sobremarcha quando a linha estiver desimpedida (ex: 1.03 = 103%). |
| `margem_sprint_b2_liga` | Float | `15.0` | Margem percentual acima de `b2_lim` necessária para ATIVAR o Sprint (garante garrafa de sobra na entrada). |
| `margem_sprint_b2_desliga` | Float | `5.0` | Margem percentual acima de `b2_lim` para DESATIVAR o Sprint por histerese (evita repicadas). |
| `tempo_minimo_sprint_s` | Float | `60.0` | Tempo mínimo de permanência em sprint para evitar picos curtos de aceleração. |
| `modo_sombra` | Boolean | `true` | Trava de segurança: se `true`, apenas calcula e monitora (sem escrita no CLP). |
| `escrever_heartbeat_modo_sombra` | Boolean | `false` | Define se deve pulsar o watchdog mesmo com o modo sombra ativo. |
| `arquivo_eventos_json` | String | `"eventos_motivos_live_v4.json"` | Arquivo local onde cada ciclo e motivo de decisão são registrados. |

### 3.7 Telemetria Grafana / InfluxDB (`telemetria_influx`)
Transmite a cada ciclo todos os campos em tempo real para o InfluxDB e dashboards do Grafana:

| Parâmetro | Tipo | Exemplo | Descrição |
| :--- | :--- | :--- | :--- |
| `habilitado` | Boolean | `true` | Ativa ou desativa a gravação de telemetria em segundo plano. |
| `influx_url` | String | `"http://10.46.12.167:8086"` | URL de acesso ao banco de dados InfluxDB. |
| `database` / `bucket` | String | `"soda"` | Nome do bucket ou banco de dados no InfluxDB. |
| `org` | String | `"ABinbev"` | Organização configurada no InfluxDB v2. |
| `measurement_destino` | String | `"512_v4"` | Nome da measurement (tabela) onde os pontos da linha são salvos. |
| `usuario` / `senha` | String | `""` | Credenciais de acesso ao banco (se exigidas). |
| `timeout_envio_s` | Float | `2.0` | Timeout máximo HTTP não-bloqueante para nunca travar o ciclo de controle. |

---

## 4. Integração com a Função de Controle V4

O cliente utiliza diretamente a classe `ControladorVelocidadeV4` de `funcao_controle_v4.py` sem alteração de lógica:
1. No início de cada ciclo (ex: a cada 10 segundos):
   - Lê os níveis calculados dos buffers: `b1, b2, b3, b4`.
   - Lê as velocidades das máquinas vizinhas e da própria enchedora: `v_in`, `v_out` e `v_atual`.
2. Executa:
   ```python
   vel, motivo_id = ctrl.calcular_velocidade(
       b1=b1, b2=b2, b3=b3, b4=b4,
       v_in=v_in, v_out=v_out, v_atual=v_atual,
       delta_t_s=ciclo_controle_s,
       retornar_motivo=True,
       timestamp=agora_str,
       registrar_evento=True,
       arquivo_json=arquivo_eventos
   )
   ```
3. **Trava de Segurança Operacional (Sprint Interlock):**
   - O controlador avalia `v_atual`. Se a enchedora estiver rodando abaixo de 98% da velocidade nominal de projeto (ex.: operador rebaixou a máquina na IHM por restrição mecânica ou de embalagem), o Sprint fica **100% bloqueado**, garantindo que a máquina nunca seja forçada além da velocidade operacional permitida.
4. Grava o setpoint `vel` diretamente na tag OPC UA do CLP.
5. Identifica a causa-raiz com `ctrl.obter_motivo(motivo_id)` e exibe no console em tempo real.

---

## 5. Modos de Watchdog Heartbeat e Segurança Industrial (Fail-Safe)

Para prevenir acidentes e garantir a integridade da linha em caso de falha de software, queda de container ou interrupção de rede, o cliente possui uma tarefa em segundo plano dedicada ao Heartbeat.

O parâmetro `"modo"` no arquivo `config_opc_v4.json` suporta **3 estratégias de watchdog**:

| Modo | Como Opera o Controlador | Como Opera o CLP | Aplicação Recomendada |
| :--- | :--- | :--- | :--- |
| **`pulse_one`** *(Padrão)* | **Sempre escreve `1` (ou `True`)** na tag a cada intervalo (ex: 1s). | O CLP lê o `1`, reinicia seu temporizador de watchdog (TON de 3 a 5s) e **zera a tag de volta para `0`**. | Padrão mais comum em linhas industriais com handshake ativo. |
| **`toggle`** | **Inverte o valor booleano a cada segundo** (`True` ➔ `False` ➔ `True`...). | O CLP detecta qualquer **borda de subida ou descida** (R_TRIG / F_TRIG) para reiniciar o temporizador. | Redes onde o CLP apenas monitora sem precisar escrever de volta na tag. |
| **`counter`** | **Incrementa um contador de `0` até `32767`** (formato Int16) e reinicia. | O CLP verifica se o valor atual é diferente do ciclo anterior (`Contador_Atual <> Contador_Anterior`). | Linhas que usam palavras inteiras de diagnóstico em blocos de dados (DBs / Tags DINT/INT). |

### Intertravamento de Segurança no CLP (Fail-Safe Obrigatório):
Independentemente do modo escolhido:
1. O CLP deve possuir um bloco de temporizador de perda de comunicação (*Watchdog Timer TON* ajustado entre 3 e 5 segundos).
2. Se o container travar, o processo cair ou a conexão Ethernet/OPC for interrompida, o sinal do Heartbeat congela.
3. O temporizador do CLP estoura e o programa da Enchedora comuta imediatamente para velocidade manual/local segura de fábrica.

---

## 6. Comandos e Operação

### 1. Visualizar e Conferir a Tabela de Esteiras:
Mostra no terminal a tabela completa de setores, áreas e percentuais calculados:
```bash
python3 Controle_Velocidade_4/assistente_opc.py
```

Para também testar a conexão com o servidor OPC UA e ler as tags ao vivo:
```bash
python3 Controle_Velocidade_4/assistente_opc.py --testar-conexao
```

### 2. Rodar a Suíte de Testes Automatizados (com Servidor Simulado):
Valida o cálculo dimensional e sobe um servidor OPC UA de teste para comprovar a subscrição, cálculo, escrita e watchdog:
```bash
python3 Controle_Velocidade_4/teste_cliente_opc.py
```

### 3. Execução em Modo Sombra (Padrão de Segurança / Apenas Leitura):
Por padrão de segurança operacional industrial (*Fail-Safe*), **o controlador sempre inicia em Modo Sombra**:
```bash
python3 Controle_Velocidade_4/cliente_opc_v4.py
```
Neste modo:
* O cliente lê todos os sensores e velocidades via Subscription.
* Calcula o nível de cada buffer e a velocidade recomendada.
* **Bloqueia qualquer escrita de setpoint no CLP.**
* Exibe no terminal a comparação: `V4 Calculado vs Real do CLP` e a diferença de velocidade.

### 4. Execução em Produção (Modo Ativo com Escrita no CLP):
Para permitir que o controlador envie os setpoints calculados para o CLP, utilize a flag `--modo-ativo` (ou defina a variável de ambiente `MODO_SOMBRA=false`):
```bash
python3 Controle_Velocidade_4/cliente_opc_v4.py --modo-ativo
```

---

## 7. Intertravamento via Tag "Segue Habilitado"

No arquivo `config_opc_v4.json`, o parâmetro `tag_segue_habilitado` monitora a chave de habilitação da modulação diretamente do CLP ou da IHM:
```json
"tag_segue_habilitado": "ns=2;s=L512_TRP512002.TRP512001.SEGUE.GERAL.HABILITADO"
```

### Comportamento Operacional:
1. **Comutação em Tempo Real:** O cliente assina a tag via evento *DataChange*. Sempre que o operador habilitar ou desabilitar o Segue na IHM, o controlador atualiza seu estado instantaneamente.
2. **Bypass Automático:** Se `tag_segue_habilitado == False`, o controlador entra em bypass: calcula as variáveis normalmente, mas **não escreve nenhum setpoint no CLP**.
3. **Reflexo nos Logs e no Sinótico:**
   * **No Sinótico:** Exibe o banner de alerta `⛔ SEGUE DESABILITADO NO CLP (MODULAÇÃO EM BYPASS)` e o indicador `Segue no CLP: DESABILITADO (BYPASS)`.
   * **Nos Logs Estruturados:** A cada ciclo, registra a tag `Segue_Hab=SIM` ou `Segue_Hab=NAO_BYPASS` (visível em `docker logs` ou ferramentas de monitoramento como Grafana Loki).
   * **No Evento de Comutação:** Registra imediatamente a mensagem `[CLP] Segue Habilitado atualizado para: False/True`.

---

## 8. Execução via Docker Compose (Mesma Máquina)

A aplicação possui uma imagem autocontida através do arquivo `Dockerfile` e `.dockerignore`, sem necessidade de montar volumes de código.

### Serviço no `Controle_Velocidade_4/docker-compose.yml`:
```yaml
  controlador-v4-opc:
    container_name: controlador-v4-opc
    build:
      context: .
      dockerfile: Dockerfile
    image: controlador-v4-opc:latest
    restart: always
    environment:
      - MODO_SOMBRA=true       # Inicia protegido em modo sombra por padrão
    deploy:
      resources:
        limits:
          cpus: '0.50'
          memory: 256M
    networks:
      - segue-network
```

### Comandos de Gestão do Container:
```bash
# Entrar na pasta do controlador
cd Controle_Velocidade_4

# Fazer o build e iniciar o serviço
docker compose up -d --build

# Visualizar o sinótico e logs em tempo real
docker logs -f controlador-v4-opc

# Parar o serviço
docker compose down
```

---

### 8.2 Build Manual e Exportação de Imagem (`.tar.gz`) para Ambiente sem Internet

Caso o IPC / Servidor da planta industrial não tenha saída para a internet, você pode compilar a imagem no seu ambiente de desenvolvimento e exportá-la:

#### No seu computador / máquina com internet:
```bash
cd Controle_Velocidade_4

# 1. Compilar a imagem
docker build -t controlador-v4-opc:latest .

# 2. Exportar a imagem compactada em .tar.gz (ideal para pendrive ou scp)
docker save controlador-v4-opc:latest | gzip > controlador-v4-opc.tar.gz
```

#### No IPC / Servidor da Fábrica (Offline):
```bash
# 1. Carregar a imagem no Docker local da máquina industrial
docker load < controlador-v4-opc.tar.gz

# 2. Rodar o container (Modo Sombra por padrão)
docker run -d \
  --name controlador-v4-opc \
  --restart always \
  -e MODO_SOMBRA=true \
  --network host \
  controlador-v4-opc:latest

# 3. Conferir o funcionamento e logs ao vivo
docker logs -f controlador-v4-opc
```

---

## 9. Telemetria Direta no InfluxDB (Porta 8086 / InfluxQL / Sem CSV)

O Controlador V4 grava todas as variáveis de processo de cada ciclo diretamente no InfluxDB na porta `8086`, dispensando arquivos CSV locais no container (garantindo execução 100% stateless e resiliente).

### Configuração em `config_opc_v4.json`:
```json
"telemetria_influx": {
  "habilitado": true,
  "influx_url": "http://localhost:8086",
  "database": "Segue",
  "measurement_destino": "512_v4",
  "usuario": "",
  "senha": "",
  "timeout_envio_s": 2.0
}
```

### Estrutura dos Dados na Medição (`512_v4`):
* **Tags (Indexadas para filtros rápidos):**
  - `linha`: Linha de envase (ex: `512`)
  - `fabrica`: Planta industrial (ex: `Equatorial`)
  - `maquina`: Máquina principal / Enchedora (ex: `ECH512001`)
  - `modo_sombra`: `true` ou `false`
  - `segue_habilitado`: `true` (CLP ativo) ou `false` (Bypass)
  - `status_operacional`: `RODANDO` ou `PARADA`
  - `status_modulacao`: `DESATIVADA_NOMINAL`, `ATIVA_MODULACAO`, `SOBREMARCHA_SPRINT`
  - `motivo_codigo`: Código da regra atuante (ex: `NORMAL_FULL`, `ACUMULO_ECH_PZ`)
  - `maquina_causadora`: Gargalo que motivou a decisão

* **Fields (Valores numéricos e métricas):**
  - `b1_pct`, `b2_pct`, `b3_pct`, `b4_pct`: Níveis calculados dos buffers (%)
  - `v_atual_cph`: Velocidade medida da máquina no CLP (CPH)
  - `v_setpoint_cph`: Velocidade calculada e recomendada pelo V4 (CPH)
  - `v_nominal_cph`: Velocidade nominal de projeto (CPH)
  - `percentual_nominal`: Taxa calculada em relação à nominal (%)
  - `setpoint_percentual`: Valor percentual equivalente enviado/indicado (0.0% a 103.8%)
  - `delta_setpoint_real_cph`: Diferença entre o setpoint V4 e a velocidade real
  - `v_in_cph`: Velocidade da máquina a montante (DPL)
  - `v_out_cph`: Velocidade da máquina a jusante (PZ)
  - `motivo_id`: ID numérico da regra do V4
  - `motivo_descricao`: Descrição em texto da condição
  - `acao_recomendada`: Ação prescritiva de controle
  - `heartbeat_counter`: Contador do watchdog
  - `total_eventos_opc`: Total de eventos recebidos do CLP

---

### Como Consultar os Dados (Queries InfluxQL / SQL):

#### 1. Consulta via Terminal (Influx CLI):
```bash
# Ver os últimos 10 ciclos gravados
influx -database Segue -execute 'SELECT * FROM "512_v4" ORDER BY time DESC LIMIT 10'

# Ver apenas buffers e setpoint calculados
influx -database Segue -execute 'SELECT b1_pct, b2_pct, b3_pct, b4_pct, v_atual_cph, v_setpoint_cph, motivo_codigo FROM "512_v4" ORDER BY time DESC LIMIT 5'
```

#### 2. Consulta via HTTP API (Curl / Script):
```bash
# Query completa em formato JSON
curl -G "http://localhost:8086/query?db=Segue" \
  --data-urlencode 'q=SELECT * FROM "512_v4" ORDER BY time DESC LIMIT 5'
```

#### 3. Query para Painéis no Grafana (Datasource InfluxDB / InfluxQL):
* **Gráfico de Velocidades:**
  ```sql
  SELECT mean("v_atual_cph") AS "Real", mean("v_setpoint_cph") AS "Setpoint V4" FROM "512_v4" WHERE $timeFilter GROUP BY time($__interval) fill(null)
  ```
* **Gráfico dos Buffers:**
  ```sql
  SELECT mean("b2_pct") AS "B2", mean("b3_pct") AS "B3", mean("b4_pct") AS "B4" FROM "512_v4" WHERE $timeFilter GROUP BY time($__interval) fill(linear)
  ```
* **Tabela de Diagnóstico e Motivos:**
  ```sql
  SELECT "motivo_codigo", "maquina_causadora", "status_modulacao", "delta_setpoint_real_cph" FROM "512_v4" ORDER BY time DESC LIMIT 20
  ```

---

## 10. Extrator de Dados do Grafana / InfluxDB (`obter_dados_grafana_v4.py`)

Para fechar o ciclo de melhoria contínua da fábrica, o módulo V4 inclui o script de extração automática:

```text
Controle_Velocidade_4/obter_dados_grafana_v4.py
```

Esse script é compilado automaticamente pelo otimizador e garante que os dados históricos baixados do Grafana ou InfluxDB tenham **100% de compatibilidade** com o formato de colunas esperado pelo `otimizador_velocidade_v4.py`.

### 10.1 Principais Características:
- **Paridade de Colunas:** Gera o CSV com as mesmas colunas especificadas em `config_colunas.json` (`accumulation_percentage_*`, `speed_actual_cph_*`, `Timestamp`).
- **Fatiamento Automático em Blocos Diários:** Evita timeouts no Grafana ao dividir janelas longas (ex: 7 ou 30 dias) em requisições de 1 dia.
- **Suporte à Tag de Status da Máquina:** Se a chave `Col_Status_Maquina` for informada, o extrator puxa automaticamente o status operacional junto com as velocidades e buffers.
- **Geração do Arquivo Padrão:** Salva o arquivo CSV diretamente com o nome configurado em `Arquivo_Dados` (padrão: `dados_completos_fabrica.csv`).

### 10.2 Como Usar no Terminal:

```bash
# 1. Baixar os últimos 7 dias da fábrica no padrão do otimizador:
python obter_dados_grafana_v4.py --start -7d

# 2. Baixar um período específico:
python obter_dados_grafana_v4.py --start 2026-09-01 --stop 2026-09-15 --output dados_setembro.csv

# 3. Listar as fontes de dados do Grafana para conferir UIDs e nomes:
python obter_dados_grafana_v4.py --list
```

### 10.3 Fluxo de Treinamento e Operação de Ponta a Ponta:

```text
1. Baixar Histórico da Fábrica
   └─► python obter_dados_grafana_v4.py --start -7d

2. Treinar CMA-ES e Calibrar Parâmetros
   └─► python otimizador_velocidade_v4.py
       (Gera: funcao_controle_v4.py, parametros_controle_v4.json,
              controlador_velocidade_live_v4.py e obter_dados_grafana_v4.py)

3. Operar em Tempo Real via OPC UA
   └─► python cliente_opc_v4.py
```


