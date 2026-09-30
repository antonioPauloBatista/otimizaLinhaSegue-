# Controlador de Velocidade V4 (Data-Driven Feedforward, Slew-Rate & OPC UA)

Sistema inteligente de controle de velocidade e otimização para linhas de envase de bebidas (cervejaria / refrigerantes), focado na máquina mestra (**Enchedora / Filler**).

A versão V4 combina processamento de sinais em software, controle preditivo *Feedforward*, lógica Takagi-Sugeno, limitador de rampa mecânica (*Slew Rate Limiter*) e integração direta via protocolo industrial **OPC UA** ou supervisório **Grafana / InfluxDB**.

---

## 📖 1. Base Técnica de Funcionamento

### 1.1 A Enchedora como Máquina Mestra (*Benchmark Machine*)
Na linha de envase, a Enchedora dita a cadência de produção de toda a fábrica:
```text
[DPL / Lavadora] ──> ( B1 ) ──> [ ECI ] ──> ( B2 ) ──> [[ ENCHEDORA ]] ──> ( B3 ) ──> [ Pasteurizador ] ──> ( B4 ) ──> [ Rotuladora ]
```
* **Impacto no Produto (Qualidade da Cerveja):**
  * **TPO (Oxigênio Dissolvido / Total Packaged Oxygen):** Paradas bruscas ou oscilações de velocidade despressurizam o carrossel, rompem a barreira de gás carbônico (CO2) e puxam oxigênio atmosférico para dentro do gargalo. Isso oxida os compostos de lúpulo e malte, degrada o sabor (*stale flavor*) e encurta o prazo de validade da cerveja.
  * **Espumamento (*Fobbing*) e Subenchimento:** Trancos mecânicos e acelerações repentinas nas estrelas de transferência agitam o líquido pressurizado, causando transbordamento de espuma e rejeição massiva de garrafas por nível incorreto na inspetora eletrônica.
* **Impacto Mecânico:**
  * O carrossel pesa dezenas de toneladas. Saltos bruscos de setpoint (*step changes*) causam choque mecânico (*jerk*), folga nas engrenagens de acionamento e quebra de garrafas nas guias de entrada e saída.
* **Objetivo do Controlador V4:**
  * Substituir paradas de emergência por **modulações suaves de velocidade** (marcha reduzida segura).
  * Manter a enchedora o máximo de tempo na velocidade nominal de projeto ou em sobrevelocidade segura (*Sprint*).

---

### 1.2 Física dos 4 Buffers e Balanço de Massa Feedforward
Os buffers não se comportam como tanques de fluido contínuo; são esteiras com garrafas que sofrem compressões mecânicas, ondas de choque e vazios transitórios (*gaps*).

* **Buffers Imediatos (Controle Reativo Local):**
  * **Buffer B2 (Entrada Imediata: ECI ➔ Enchedora):** Evita falta de garrafas no carrossel. Se o acúmulo cai abaixo do limiar (ex: 27.3%), reduz a velocidade preventivamente.
  * **Buffer B3 (Saída Imediata: Enchedora ➔ Pasteurizador):** Evita engavetamento na saída. Se o acúmulo ultrapassa o limiar (ex: 74.4%), freia a máquina para não colidir recipientes nas estrelas. Se atingir 80%, aplica desaceleração protetiva máxima.
* **Buffers Extremos (Feedforward Preditivo de Longo Prazo):**
  * **Buffer B1 (Extremo Entrada: DPL ➔ ECI):** Alerta antecipatório de falta. Quando B1 seca (abaixo de 16.0%), o algoritmo sabe minutos antes que o buffer B2 secará. Inicia uma descida suave antecipada, evitando parada brusca quando o vazio chegar à Enchedora.
  * **Buffer B4 (Extremo Saída: Pasteurizador ➔ Rotuladora):** Alerta antecipatório de engavetamento. Se o fim de linha parar, B4 acumula. Quando o Pasteurizador começa a perder vazão de escoamento, o V4 reduz preventivamente a Enchedora, protegendo B3 de um transbordamento súbito.
* **Retomada Sincronizada Pós-Parada:**  
  Quando a máquina de jusante (Pasteurizador) destrava e sua aceleração se torna positiva, a Enchedora arranca imediatamente em sincronismo, sem esperar o esvaziamento completo das esteiras.

---

### 1.3 Pipeline de Tratamento de Sinais 100% em Software
Para operar em esteiras com sensores ópticos com ruídos, gotas e reflexos sem exigir recalibração de campo:
1. **Filtro Mediano Móvel (Janela N = 3):** Elimina quedas instantâneas espúrias (ex: leitura caindo de 60% para 18% por 1 ciclo e voltando para 60%).
2. **Debounce de Persistência:** Distingue recipientes passando em alta velocidade de um acúmulo real e consolidado.
3. **Filtro EWMA (Exponencial, fator alfa = 0.65):** Suaviza o chaveamento digital dos sensores discretos, gerando uma estimativa contínua da densidade de garrafas na esteira.

---

### 1.4 Proteção Mecânica Ativa: Rampa Slew Rate Parametrizada por Tempo
A taxa de aceleração e desaceleração é ajustada de forma física e direta em segundos (padrão de parametrização de inversores de frequência):
* **Tempo de Rampa de Subida (ex: 10.0s de 0 a 100%):** Aceleração progressiva e cautelosa.
* **Tempo de Rampa de Descida (ex: 8.0s de 100% a 0):** Desaceleração rápida para proteção contra engavetamento.
* **Referência Estrita:** A taxa (garrafas/hora por segundo) é calculada estritamente sobre a **Velocidade Máxima Nominal**, e nunca sobre sobremarcha.
* **Banda Morta (300 CPH):** Evita microvariações contínuas de setpoint no motor (*hunting*).

---

## 🛠️ 2. Guia de Configuração e Execução do Otimizador

O processo de otimização calibra os limiares matemáticos e as rampas mecânicas a partir do histórico real da sua linha.

---

### 2.0 Passo 0: Extrair Dados Recentes do Grafana / InfluxDB
Para baixar automaticamente o histórico da fábrica no formato exato esperado pelo otimizador:

```bash
cd Controle_Velocidade_4
python3 obter_dados_grafana_v4.py --start -7d
```
* O script divide a busca em blocos diários para evitar timeouts no Grafana.
* Gera automaticamente o arquivo `dados_completos_fabrica.csv` com as colunas já nomeadas e alinhadas por Timestamp.
* Se a máquina tiver uma tag/coluna de status de produção, ela pode ser puxada adicionando `--status-col <nome_campo>`.

---

### 2.1 Passo 1: Conferir o `config_colunas.json`
O arquivo [`config_colunas.json`](config_colunas.json) mapeia as colunas do seu arquivo CSV histórico (`dados_completos_fabrica.csv`) para as variáveis internas do otimizador:

```json
{
  "Arquivo_Dados": "dados_completos_fabrica.csv",
  "Col_Buffer_Antes_Entrada": "",
  "Col_Buffer_Entrada": "accumulation_percentage_dpl_to_ech_null",
  "Col_Buffer_Saida": "accumulation_percentage_ech_to_pz_null",
  "Col_Buffer_Pos_Saida": "accumulation_percentage_pz_to_epc_null",
  "COL_V_Antes_Entrada": "",
  "COL_V_Entrada": "speed_actual_cph_null_first_upstream_machine_1",
  "COL_V_ECH": "speed_actual_cph_null_filler_1",
  "COL_V_Saida": "speed_actual_cph_null_pasteurizer",
  "COL_V_Entrada_Pos_Saida": "speed_actual_cph_null_first_downstream_machine_1",
  "Velocidade_Nominal_ECH": 94500,
  "Tempo_Rampa_Subida_s": 10.0,
  "Tempo_Rampa_Descida_s": 8.0,
  "Fator_Sobremarcha": 1.01,
  "Min_Modulacao": 0.75,
  "Banda_Morta_CPH": 300.0,
  "Alpha_Filtro_Buffer": 0.65,
  "Janela_Mediana_Buffer": 3
}
```

#### O que preencher em cada campo:
| Campo | Descrição e O que Inserir | Exemplo |
| :--- | :--- | :--- |
| **`Arquivo_Dados`** | Nome ou caminho do CSV exportado com o histórico da linha. | `"dados_completos_fabrica.csv"` |
| **`Col_Buffer_Antes_Entrada`** | Nome da coluna do **Buffer B1** (Extremo de entrada, ex: DPL ➔ ECI). Deixe `""` ou `null` se a linha não tiver esse sensor. | `""` ou `"accumulation_percentage_dpl_to_eci_null"` |
| **`Col_Buffer_Entrada`** | Nome da coluna do **Buffer B2** (Entrada imediata da Enchedora: ECI ➔ ECH). | `"accumulation_percentage_dpl_to_ech_null"` |
| **`Col_Buffer_Saida`** | Nome da coluna do **Buffer B3** (Saída imediata da Enchedora: ECH ➔ Pasteurizador). | `"accumulation_percentage_ech_to_pz_null"` |
| **`Col_Buffer_Pos_Saida`** | Nome da coluna do **Buffer B4** (Extremo de saída, ex: Pasteurizador ➔ Rotuladora). Deixe `""` se não houver. | `"accumulation_percentage_pz_to_epc_null"` |
| **`COL_V_Entrada`** | Coluna da velocidade da máquina a montante (**V_in**, ex: ECI ou Despaletizadora). | `"speed_actual_cph_null_first_upstream_machine_1"` |
| **`COL_V_ECH`** | Coluna da velocidade real da **Enchedora** no histórico. | `"speed_actual_cph_null_filler_1"` |
| **`COL_V_Saida`** | Coluna da velocidade da máquina a jusante (**V_out**, ex: Pasteurizador). | `"speed_actual_cph_null_pasteurizer"` |
| **`Velocidade_Nominal_ECH`** | Velocidade de projeto máxima contínua da Enchedora em garrafas/hora (CPH). | `94500` |
| **`Tempo_Rampa_Subida_s`** | Tempo em segundos para a máquina acelerar de 0 a 100% nominal (parâmetro do inversor). | `10.0` |
| **`Tempo_Rampa_Descida_s`** | Tempo em segundos para a máquina desacelerar de 100% a 0 (parâmetro do inversor). | `8.0` |
| **`Fator_Sobremarcha`** | Multiplicador de velocidade quando a linha estiver em sprint (ex: 1.01 = 101%). | `1.01` |
| **`Min_Modulacao`** | Fração mínima da velocidade nominal antes de optar por parar (ex: 0.75 = 75%). | `0.75` |
| **`Banda_Morta_CPH`** | Variação mínima em CPH para enviar novo comando ao motor (evita repique). | `300.0` |

---

### 2.2 Passo 2: Executar o Otimizador V4
Com o `config_colunas.json` preenchido e o CSV na pasta, execute:

```bash
cd Controle_Velocidade_4
python3 otimizador_velocidade_v4.py
```

#### O que o otimizador faz durante a execução:
1. Carrega os dados e aplica o pipeline anti-ruído (Mediana N=3 + EWMA 0.65).
2. Executa a calibração matemática via CMA-ES buscando a melhor combinação de limiares dos buffers (B1, B2, B3, B4).
3. **Recompila e salva** os módulos e parâmetros prontos:
   * [`funcao_controle_v4.py`](funcao_controle_v4.py) (Função autônoma do controlador)
   * [`parametros_controle_v4.json`](parametros_controle_v4.json) (Parâmetros ótimos)
   * [`obter_dados_grafana_v4.py`](obter_dados_grafana_v4.py) (Extrator de histórico Grafana com paridade de colunas)
   * [`controlador_velocidade_live_v4.py`](controlador_velocidade_live_v4.py) (Simulador interativo de bancada)
4. **Gera as Imagens e Gráficos de Produção:**
   * Pasta **`graficos_velocidade_otimizada_v4/`**: Imagens `.png` de cada dia com o comparativo `Velocidade Real vs V4 Otimizada`, buffers e motivos.
   * Arquivo **`curva_convergencia_v4.png`**: Gráfico demonstrando a minimização da função custo e convergência do algoritmo.
   * Arquivo **`relatorio_otimizacao_v4_<data>.txt`**: Resumo de garrafas ganhas e paradas evitadas.

---

## 🏭 3. Configuração do CLP / OPC UA (`config_opc_v4.json`)

Para conectar o controlador ao CLP físico da fábrica através do módulo [`cliente_opc_v4.py`](cliente_opc_v4.py), preencha o arquivo [`config_opc_v4.json`](config_opc_v4.json):

```json
{
  "servidor_opc": {
    "url": "opc.tcp://192.168.1.10:4840",
    "usuario": "",
    "senha": "",
    "timeout_s": 5.0,
    "reconectar_delay_s": 3.0,
    "publishing_interval_ms": 500
  },
  "heartbeat": {
    "tag": "ns=2;s=L512_TRP512002.TRP512001.SEGUE.OTIMIZADOR.HEARTBEAT",
    "intervalo_s": 1.0,
    "modo": "pulse_one"
  },
  "maquinas": {
    "tag_velocidade_montante": "ns=2;s=L512_TRP512002.TRP512001.SEGUE.DPL.VELOCIDADE_ATUAL",
    "tag_velocidade_atual": "ns=2;s=L512_TRP512002.TRP512001.SEGUE.ECH.VELOCIDADE_ATUAL",
    "tag_velocidade_jusante": "ns=2;s=L512_TRP512002.TRP512001.SEGUE.PZ.VELOCIDADE_ATUAL",
    "tag_escrita_setpoint": "ns=2;s=L512_TRP512002.TRP512001.SEGUE.ECH.SETPOINT_VELOCIDADE",
    "tag_segue_habilitado": "ns=2;s=L512_TRP512002.TRP512001.SEGUE.GERAL.HABILITADO",
    "velocidade_nominal": 94500.0
  },
  "buffers": {
    "B2": {
      "nome": "B2 - Entrada Imediata",
      "capacidade_area_total_m2": 32.0,
      "setores": [
        {
          "ordem": 1,
          "tag": "ns=2;s=L512_TRP512002.TRP512001.SEGUE.DPL-ECH.106B2",
          "comprimento_m": 2.9,
          "largura_m": 0.4,
          "contato_ativo": false,
          "habilitado": true
        }
      ]
    }
  },
  "controle": {
    "ciclo_controle_s": 10.0,
    "tempo_rampa_subida_s": 10.0,
    "tempo_rampa_descida_s": 8.0,
    "banda_morta_cph": 300.0,
    "modo_sombra": true
  }
}
```

#### Pontos Principais do `config_opc_v4.json`:
* **`url`**: Endereço do Servidor OPC UA do CLP ou Gateway industrial.
* **`usuario` e `senha` (Opcional)**: Se o servidor OPC UA exigir autenticação, informe o usuário e senha (ou defina via variáveis de ambiente `OPC_USER` e `OPC_PASSWORD`). Se deixados vazios `""`, a conexão é estabelecida de forma anônima (`None`).
* **`tag_escrita_setpoint`**: Tag do CLP onde o setpoint calculado em CPH será gravado.
* **`tag_segue_habilitado`**: Tag booleana da IHM/CLP que permite ligar/desligar a modulação. Quando `False`, o V4 entra em bypass automaticamente.
* **`heartbeat.modo` (3 Modos Suportados)**:
  * **`pulse_one`** *(Padrão de Fábrica)*: O controlador sempre escreve `1` (ou `True`) e o CLP é quem zera a tag de volta para `0` (handshake ativo).
  * **`toggle`**: O controlador inverte o booleano a cada segundo (`True` ➔ `False` ➔ `True`...), e o CLP detecta bordas de subida/descida.
  * **`counter`**: O controlador incrementa um número de `0` até `32767` (Int16) a cada pulso.
* **`fator_sprint`**: Multiplicador de velocidade em sobremarcha quando a linha estiver livre (ex: `1.03` = 103%).
* **`margem_sprint_b2_liga` e `margem_sprint_b2_desliga`**: Histerese de garrafas no buffer de entrada B2 para ligar (+15%) e desligar (+5%) o sprint com estabilidade.
* **`tempo_minimo_sprint_s`**: Tempo mínimo de permanência em sobremarcha (ex: `60.0`s) para eliminar repicadas mecânicas.
* **`tag_status_maquina`**: Tag do CLP de status operacional da máquina (usada para diagnóstico de parada própria).
* **`telemetria_influx`**: Transmissão em segundo plano para Grafana/InfluxDB sem atrasar o loop de controle.
* Para ver a tabela completa de todos os parâmetros detalhados, consulte a Seção 3 do [MANUAL_CLIENTE_OPC_V4.md](MANUAL_CLIENTE_OPC_V4.md#3-dicionário-completo-de-parâmetros-config_opc_v4json).

---

## 🐳 4. Como Gerar a Imagem Docker e Rodar com Docker Compose

O diretório já possui o [`Dockerfile`](Dockerfile) autocontido e o arquivo [`docker-compose.yml`](docker-compose.yml) configurado.

### 4.1 Anatomia do `Dockerfile`:
O `Dockerfile` copia todos os módulos necessários diretamente para a imagem, dispensando mapeamento de volumes de código e fixando o Modo Sombra por padrão:
```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODO_SOMBRA=true

WORKDIR /app

RUN pip install --no-cache-dir asyncua==1.1.5 cryptography

COPY cliente_opc_v4.py .
COPY funcao_controle_v4.py .
COPY gerenciador_buffers.py .
COPY motivos_modulacao_enum.json .
COPY config_opc_v4.json .

CMD ["python", "cliente_opc_v4.py"]
```

---

### 4.2 Gerando a Imagem e Subindo com Docker Compose

Execute diretamente de dentro da pasta `Controle_Velocidade_4`:

```bash
cd Controle_Velocidade_4

# 1. Construir a imagem Docker e iniciar o serviço em segundo plano:
docker compose up -d --build

# 2. Visualizar os logs estruturados e o fluxograma sinótico da linha:
docker logs -f controlador-v4-opc

# 3. Parar o serviço:
docker compose down
```

---

### 4.3 Gerando a Imagem via Docker Build e Exportando (.tar) para Fábrica / Edge

Em ambientes industriais onde o servidor/IPC na fábrica **não possui acesso à internet** para baixar dependências, você pode compilar a imagem na sua máquina e exportar o arquivo `.tar`:

```bash
cd Controle_Velocidade_4

# 1. Gerar a imagem com tag de versão:
docker build -t controlador-v4-opc:latest .

# 2. Exportar (salvar) a imagem em arquivo compactado para levar via pendrive/SCP:
docker save controlador-v4-opc:latest | gzip > controlador-v4-opc.tar.gz

# (Opcional) Sem compactação gzip:
# docker save -o controlador-v4-opc.tar controlador-v4-opc:latest
```

#### No IPC / Servidor da Fábrica (Máquina Destino sem Internet):
```bash
# 1. Carregar a imagem a partir do arquivo exportado:
docker load < controlador-v4-opc.tar.gz

# 2. Iniciar o container usando a imagem carregada:
docker run -d \
  --name controlador-v4-opc \
  --restart always \
  -e MODO_SOMBRA=true \
  --network host \
  controlador-v4-opc:latest

# 3. Acompanhar os logs ao vivo:
docker logs -f controlador-v4-opc
```

> **Como liberar a escrita no CLP no futuro (Modo Ativo):**  
> Altere a variável de ambiente para `MODO_SOMBRA=false` (no `docker-compose.yml` ou no `docker run -e MODO_SOMBRA=false`) e recrie o container. Caso contrário, ele permanecerá protegido em modo sombra (apenas leitura).

## 📊 5. Modos Alternativos: Live Grafana e Simulador de Bancada

### 5.1 Simulador Interativo de Bancada
Permite ao operador digitar valores manuais de buffers e velocidades no terminal para testar as reações do algoritmo e o motivo disparado:
```bash
python3 Controle_Velocidade_4/controlador_velocidade_live_v4.py
```

### 5.2 Controlador Live via Grafana / InfluxDB
Usado para auditoria e simulação em malha aberta a partir dos dados gravados no InfluxDB:
```bash
python3 Controle_Velocidade_4/controlador_velocidade_grafana_v4.py
```

---

## 🏷️ 6. Tabela de Causas-Raiz e Diagnóstico Operacional

O V4 categoriza cada decisão de velocidade em códigos mapeados em [`motivos_modulacao_enum.json`](motivos_modulacao_enum.json):

| ID | Código | Categoria | Descrição Operacional |
| :---: | :--- | :--- | :--- |
| **0** | `NORMAL_FULL` | Operação Normal | Enchedora operando a 100% da velocidade nominal plena. |
| **1** | `SPRINT_SOBREVELOCIDADE` | Oportunidade | Linha com entrada abundante e saída livre. Operação a 101% - 105%. |
| **10** | `FALTA_ENTRADA_B2` | Modulação / Gargalo | Buffer imediato B2 baixo. Modulação suave para evitar parada por falta. |
| **20** | `ACUMULO_SAIDA_B3` | Modulação / Gargalo | Buffer imediato B3 alto. Redução de velocidade para evitar colisão. |
| **25** | `RETOMADA_ACELERANDO_SAIDA` | Retomada | Pasteurizador acelerando. Enchedora retoma velocidade antecipadamente. |
| **30** | `CONFLITO_ENTRADA_SAIDA` | Conflito | B2 baixo e B3 alto simultaneamente. Prioridade para proteção de saída. |
| **40** | `FEEDFORWARD_ALERTA_B1` | Preditivo Montante | Buffer extremo B1 secando. Redução suave preventiva antes de afetar B2. |
| **50** | `FEEDFORWARD_ALERTA_B4` | Preditivo Jusante | Fim de linha acumulando. Pasteurizador perdendo vazão e limitando enchedora. |
| **60** | `LIMITADOR_RAMPA_MECANICA` | Inércia | Transição suave limitada pela rampa de aceleração/desaceleração. |
| **70** | `MAQUINA_ENTRADA_LENTA` | Balanço de Massa | ECI operando abaixo de 85% da capacidade. |
| **80** | `MAQUINA_SAIDA_LENTA` | Balanço de Massa | Pasteurizador operando abaixo de 85% da capacidade. |
| **90** | `PARADA_SEGURANCA_BUFFER` | Intertravamento | Buffers em níveis críticos simultâneos. |
| **91** | `PARADA_INTERTRAV_ENTRADA` | Intertravamento | Falta total de embalagens na entrada (B2 <= 10%). |
| **92** | `PARADA_INTERTRAV_SAIDA` | Intertravamento | Saída completamente bloqueada (B3 >= 90%). |
