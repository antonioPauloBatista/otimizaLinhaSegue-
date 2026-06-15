# Otimizador de Velocidade da Enchedora (Gêmeo Digital & IA)

Este projeto contém ferramentas para simular e otimizar os gatilhos e velocidades de controle de uma enchedora industrial com base no comportamento de 3 ou 4 buffers da linha de envase.

---

## 🛠️ Como Configurar o Ambiente

O projeto utiliza um ambiente virtual local (`.venv`) para gerenciar as dependências.

1. **Criar o ambiente virtual (venv):**
   ```bash
   python3 -m venv .venv
   ```

2. **Instalar as dependências:**
   ```bash
   .venv/bin/pip install -r requirements.txt
   ```

---

## 📂 Arquivos do Projeto

* **`requirements.txt`**: Lista de dependências Python necessárias para rodar todos os otimizadores e o extrator do InfluxDB.
* **`config_colunas.json`**: Arquivo de mapeamento único onde você define os nomes das colunas reais do CSV para cada buffer/máquina. Permite desativar buffers de extremidade (B1 e B4) configurando seus valores como `null`.
* **`obter_dados_influx.py`**: Extrator robusto que consulta o InfluxDB usando a query Flux fornecida, dividindo o período de consulta em lotes de 1 dia (para evitar timeouts) e salvando o progresso incrementalmente no CSV.
* **`otimizador.py`**: O algoritmo principal de IA que utiliza um Algoritmo Genético personalizado para encontrar a melhor sintonia de velocidades e gatilhos de histerese.
* **`otimizador_cma_es.py`**: Otimizador alternativo baseado em CMA-ES (Estratégia de Evolução de Adaptação da Matriz de Covariância) para sintonia fina multivariável de alta performance.
* **`gerar_template_csv.py`**: Script auxiliar para criar um arquivo `dados_completos_fabrica.csv` de teste com dados simulados representativos de distúrbios da fábrica.
* **`explicacao_conceitos.md`**: Explicação teórica detalhada sobre a dinâmica dos pulmões da linha, a importância da histerese e os limites de controle.
* **`agents.md`**: Modelagem do projeto sob a arquitetura de **Agentes de IA** (Otimização) e **Agentes Físicos** (CLP).

---

## 📥 Como Buscar os Dados do InfluxDB

Se você utiliza o InfluxDB para coletar a telemetria do supervisório da fábrica, use o script `obter_dados_influx.py` para extrair os dados. Ele divide a busca dia a dia e salva de forma incremental:

```bash
./.venv/bin/python obter_dados_influx.py \
  --url "http://localhost:8086" \
  --token "SEU_TOKEN_AQUI" \
  --org "SUA_ORGANIZACAO" \
  --bucket "Segue" \
  --start "2026-05-01" \
  --stop "2026-05-15" \
  --output "dados_completos_fabrica.csv"
```

### Argumentos suportados pelo extrator:
* `--url`: URL de conexão do InfluxDB (padrão: `http://localhost:8086`).
* `--token`: Token de acesso/autenticação (obrigatório).
* `--org`: Nome da organização no InfluxDB (obrigatório).
* `--bucket`: Nome do bucket (padrão: `Segue`).
* `--start`: Início da janela de tempo. Aceita formato relativo (ex: `-7d`, `-24h`) ou absoluto (ex: `2026-05-01`).
* `--stop`: Fim da janela de tempo. Padrão: `now()`.
* `--output`: Caminho para o arquivo CSV de saída (padrão: `dados_completos_fabrica.csv`).

---

## 🚀 Como Rodar os Otimizadores

### Passo 1: Configurar Mapeamento (`config_colunas.json`)
Antes de rodar, verifique se o arquivo `config_colunas.json` está apontando para o seu CSV de dados e mapeando os nomes corretos das colunas. 
* **Linha com 4 Buffers:** Preencha os nomes das colunas para todos os 4 buffers.
* **Linha com 3 Buffers:** Defina as colunas `Col_Buffer_Antes_Entrada` e `Col_Buffer_Pos_Saida` como `null`.

### Passo 2: Executar o Otimizador Desejado

**Opção A: Otimizador por Algoritmo Genético (Rápido)**
```bash
.venv/bin/python otimizador.py
```

**Opção B: Otimizador por Machine Learning + CMA-ES (Recomendado para provar valor)**
Cria um modelo Surrogate (Random Forest) que aprende o comportamento da linha sem controle, e usa CMA-ES para buscar os setpoints ideais que evitam paradas, gerando um comparativo de ganho de produção.
```bash
.venv/bin/python otimizador_ml_cma_es.py
```

**Opção C: Otimizador por CMA-ES (Sintonia Fina)**
```bash
.venv/bin/python otimizador_cma_es.py
```

### Passo 3: Programar o CLP
Ambos os scripts imprimirão no console um relatório final pronto contendo:
1. As condições globais de nível seguro para rodar a **Velocidade Alta (100%)**.
2. Os parâmetros de **REDUZIR (Start)** e **LIGAR (Clear)** e as respectivas velocidades reduzidas para cada buffer de proteção da máquina.
