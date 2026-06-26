# 🍺 Otimizador e Controlador de Velocidade da Enchedora

Solução de modulação inteligente de velocidade baseada em telemetria de pulmões (buffers). Substitui controles rígidos de Liga/Desliga por uma modulação suave dentro de uma **faixa de operação inegociável**, maximizando o uptime e eliminando "socos" mecânicos.

---

## ⚙️ Regra de Ouro do Sistema

> **O controlador NUNCA comanda parada (0 CPH).**
> O setpoint de velocidade é sempre mantido entre o **Piso** e o **Teto** configurados no `config_colunas.json`.
> Paradas de emergência são responsabilidade exclusiva do **intertravamento físico do CLP** (sensor seco, guardas de segurança, etc.).

| Parâmetro | Fonte | Exemplo |
|---|---|---|
| Piso (mínimo absoluto) | `Min_Modulacao` no JSON | `0.80` → 56.000 CPH |
| Teto (máximo absoluto) | `Max_Modulacao` no JSON | `1.00` → 70.000 CPH |
| Velocidade Nominal | `Velocidade_Nominal_ECH` no JSON | `70000` CPH |

---

## 🚀 Como a Solução Funciona

A solução tem **3 componentes** que trabalham em cadeia:

### 1. Os Motores de Otimização (Versões)

O projeto possui diferentes evoluções do motor de inteligência artificial (CMA-ES) que lê o histórico real da fábrica (`dados_completos_fabrica.csv`) para descobrir os gatilhos ideais:

- **V1 (`otimizador_velocidade.py`)**: Lógica Fuzzy focada nos dois pulmões principais (B2 Entrada e B3 Saída). A velocidade mínima (piso) de modulação é inegociável e fixa, vindo do `config_colunas.json`.
- **V2 (`otimizador_velocidade_v2.py`)**: Adiciona a lógica de **Feedforward** (Alerta Antecipado). Além de B2 e B3, monitora os pulmões das extremidades da linha (B1 Despaletizadora e B4 Empacotadora) para prever faltas ou gargalos antes de chegarem à enchedora. A velocidade mínima continua sendo uma regra fixa (inegociável).
- **V3 (`otimizador_velocidade_v3.py`)**: Otimização Dinâmica do Piso. Além de otimizar os gatilhos dos 4 pulmões com Feedforward, **a Inteligência Artificial descobre qual é a Velocidade Mínima de Modulação ideal**. O piso deixa de ser uma regra fixa humana e vira uma variável otimizada (ex: o algoritmo pode provar que modular até 73.5% é melhor do que travar em 80%). O teto continua sendo fixo e inegociável.

### 2. `controlador_velocidade_live.py` — O Simulador Interativo
- Carrega os parâmetros otimizados do `parametros_controle.json`
- Recebe os níveis dos 4 pulmões em tempo real (digitados ou via integração)
- Retorna o **setpoint de velocidade em CPH** — sempre entre Piso e Teto
- Nunca retorna 0 CPH

### 3. `funcao_controle.py` — Função Standalone para Deploy
- Código Python puro, sem dependências pesadas
- Parâmetros otimizados já "chumbados" no código
- Pronto para importar em qualquer sistema: `from funcao_controle import calcular_velocidade`
- Segue as mesmas regras: piso e teto inegociáveis, nunca retorna 0 CPH

---

## 📁 Arquivos de Configuração

### `config_colunas.json` — Arquivo Mestre
```json
{
  "Velocidade_Nominal_ECH": 70000,
  "Min_Modulacao": 0.80,
  "Max_Modulacao": 1.00,
  "Col_Buffer_Entrada": "nome_da_coluna_b2",
  "Col_Buffer_Saida":   "nome_da_coluna_b3",
  ...
}
```
> **Importante:** `Min_Modulacao` e `Max_Modulacao` são as únicas travas que o operador precisa tocar. O algoritmo respeita esses valores sem questionamento.

---

## 📂 Arquivos de Saída Gerados

### Para Automação / Deploy
| Arquivo | Uso |
|---|---|
| `funcao_controle.py` | Função Python pronta para integração no supervisório |
| `parametros_controle.json` | Parâmetros de gatilho lidos pelo `controlador_velocidade_live.py` |
| `relatorio_otimizacao_*.txt` | Relatório executivo com regras de CLP em linguagem SCL/Texto Estruturado |

### Para Análise e Auditoria
| Arquivo | Uso |
|---|---|
| `dados_velocidade_otimizada.csv` | Base de dados com coluna `Velocidade_Otimizada` para PowerBI/Grafana |
| `graficos_velocidade_otimizada/` | Gráficos diários com Velocidade + Buffers sobrepostos |
| `curva_convergencia.png` | Evolução da pontuação matemática do algoritmo CMA-ES |

---

## 🏃 Como Executar

```bash
# 1. Escolha a versão do otimizador e rode (leva ~15s)
.venv/bin/python otimizador_velocidade_v3.py

# 2. Testar o controlador interativamente (o script apropriado gerado na saída)
.venv/bin/python controlador_velocidade_live_v3.py
```

---

## 🧠 Lógica de Controle Resumida

```
SE B2 (Entrada) < 15%  →  Modular: reduz para o Piso (80%)
SE B3 (Saída)   > 85%  →  Modular: reduz para o Piso (80%)
SE ambos normais       →  Rodar no Teto (100%)

Em QUALQUER caso:
  setpoint >= Velocidade_Nominal * Min_Modulacao  (NUNCA abaixo do piso)
  setpoint <= Velocidade_Nominal * Max_Modulacao  (NUNCA acima do teto)
  setpoint != 0  (parada é responsabilidade do CLP físico)
```

---

## 📊 Como Interpretar os Gráficos

Cada imagem em `graficos_velocidade_otimizada/` tem 2 painéis:
- **Painel superior:** Velocidade Real (🔴) vs Velocidade Otimizada (🟢), com linhas de Piso e Teto
- **Painel inferior:** Nível dos pulmões B2, B3, B4 em %, com linhas tracejadas dos **gatilhos de modulação**

> Quando a linha verde desce até o Piso mas a linha vermelha já está em 0, isso representa **produção perdida por motivo externo** (operador, mecânica) que o controlador teria mantido ativa.

---

*Documentação atualizada em 2026-06-18 — versão com adição da V3 (velocidade mínima otimizável).*
