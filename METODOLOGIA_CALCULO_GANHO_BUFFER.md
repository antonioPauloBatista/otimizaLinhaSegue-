# Metodologia de Validação e Cálculo de Ganho em Controle de Linha

Este documento define o procedimento padrão para medir, calcular e auditar o ganho real de produção entregue por controladores industriais (como o Segue v4), isolando perturbações externas através da análise de estresse de buffer.

---

## 1. O Problema da Validação em Tempo Real

Em linhas industriais de envase, comparar a **Velocidade Real** diretamente contra a **Velocidade Sem Controle** gera distorções matemáticas:
- A "Velocidade Sem Controle" configurada no CLP é um valor estático (ex: 94.500 CPH) que assume uma linha ideal sem engarrafamentos.
- Na prática, a máquina sozinha não sustenta esse valor porque colapsa os buffers à frente, fecha a trava de segurança e sofre micro-stops.
- Para comprovar ganho real sem contestação, é necessário comparar o desempenho da linha sob as **mesmas condições físicas de estresse**.

---

## 2. Variáveis Obrigatórias no Banco de Dados

Para aplicar esta metodologia em qualquer máquina ou linha, devem ser registradas as seguintes colunas a cada ciclo fixo de amostragem (ex: 5s ou 10s):

| Nome da Coluna | Tipo | Descrição Operacional |
| :--- | :---: | :--- |
| **`Time`** | Timestamp | Data e hora da amostragem (base de integração). |
| **`velocidade_real_cph`** | Float | Velocidade física medida pelo sensor da máquina. |
| **`segue_habilitado`** | Booleano | `True` se o controle otimizador está atuando; `False` se está no CLP nativo. |
| **`velocidade_maquina_sem_controle_cph`** | Float | Setpoint padrão que a máquina tentaria usar sem o otimizador. |
| **`b3_pct`** (ou `buffer_jusante`) | Float | Nível de ocupação percentual da esteira à frente da máquina (0 a 100%). |
| **`trava_entrada_int`** | Inteiro | `0` = Esteira livre para passar produto; `1` = Trava atuada bloqueando fluxo. |

---

## 3. Roteiro de Cálculo em 3 Etapas

### Etapa 1: Normalização por Taxa Horária (Produção Real)
Quando os períodos de teste têm durações diferentes (ex: 114 min sem controle vs 77 min com controle), calcula-se a taxa horária equivalente em Garrafas por Hora (CPH):

$$\text{Fração de Hora por Amostra } (\Delta t) = \frac{\text{Intervalo de Amostragem (s)}}{3600}$$

$$\text{Volume de Garrafas} = \sum \left( \text{velocidade\_real\_cph} \times \Delta t \right)$$

$$\text{Taxa Horária (CPH)} = \frac{\text{Volume de Garrafas}}{\text{Tempo Total em Horas}} = \text{Média}(\text{velocidade\_real\_cph})$$

---

### Etapa 2: Determinação do Ponto de Estresse de Buffer ($B_{limite}$)
Para isolar fatores externos (como paradas de máquinas vizinhas), determina-se o limiar crítico onde a esteira entra em risco de colapso:
1. Analisa-se o nível de buffer em que a trava de entrada começa a fechar com frequência.
2. No caso da enchedora sob o Segue v4, esse ponto crítico ocorre em **$B3 \ge 70\%$** (parâmetro de alerta de acúmulo).
3. Em outros modelos, adota-se o percentual onde a máquina nativa começa a rastejar (geralmente entre 60% e 80%).

---

### Etapa 3: Cálculo do Ganho sob Condição Idêntica
Filtram-se apenas os instantes em que a esteira esteve sob estresse severo ($Buffer \ge B_{limite}$) nos dois cenários:

$$\text{Ganho sob Gargalo (CPH)} = \text{Média}(V_{real}[\text{Com Controle, } B \ge B_{limite}]) - \text{Média}(V_{real}[\text{Sem Controle, } B \ge B_{limite}])$$

$$\text{Ganho Percentual sob Gargalo (\%)} = \left(\frac{\text{Ganho sob Gargalo}}{\text{Média}(V_{real}[\text{Sem Controle, } B \ge B_{limite}])}\right) \times 100$$

---

## 4. Script de Automação para Qualquer Modelo (Python)

O script abaixo executa a leitura do arquivo CSV e gera o relatório consolidado automaticamente:

```python
import pandas as pd

def calcular_ganho_controle(caminho_csv, limiar_buffer=70.0, dt_segundos=10.0):
    df = pd.read_csv(caminho_csv)
    dt_h = dt_segundos / 3600.0

    # 1. Separação dos períodos
    sem_ctrl = df[df["segue_habilitado"] == False]
    com_ctrl = df[df["segue_habilitado"] == True]

    if len(sem_ctrl) == 0 or len(com_ctrl) == 0:
        print("Erro: O arquivo precisa conter períodos com segue_habilitado True e False.")
        return

    # 2. Taxas Globais Normalizadas
    taxa_sem = sem_ctrl["velocidade_real_cph"].mean()
    taxa_com = com_ctrl["velocidade_real_cph"].mean()
    ganho_global_cph = taxa_com - taxa_sem
    ganho_global_pct = (ganho_global_cph / taxa_sem) * 100.0

    # 3. Análise de Paradas Totais (v == 0)
    paradas_sem_s = (sem_ctrl["velocidade_real_cph"] == 0).sum() * dt_segundos
    paradas_com_s = (com_ctrl["velocidade_real_cph"] == 0).sum() * dt_segundos
    horas_sem = len(sem_ctrl) * dt_h
    horas_com = len(com_ctrl) * dt_h
    taxa_parada_sem_h = paradas_sem_s / horas_sem
    taxa_parada_com_h = paradas_com_s / horas_com
    reducao_paradas_pct = (1.0 - taxa_parada_com_h / taxa_parada_sem_h) * 100.0

    # 4. Auditoria sob Mesma Condição de Buffer (Isolando Fatores Externos)
    sem_gargalo = sem_ctrl[sem_ctrl["b3_pct"] >= limiar_buffer]
    com_gargalo = com_ctrl[com_ctrl["b3_pct"] >= limiar_buffer]
    
    v_sem_gargalo = sem_gargalo["velocidade_real_cph"].mean()
    v_com_gargalo = com_gargalo["velocidade_real_cph"].mean()
    ganho_gargalo_cph = v_com_gargalo - v_sem_gargalo
    ganho_gargalo_pct = (ganho_gargalo_cph / v_sem_gargalo) * 100.0

    # 5. Relatório Formatado
    print("=" * 65)
    print("        RELATÓRIO DE VALIDAÇÃO DE GANHO DE PROCESSO")
    print("=" * 65)
    print(f"Limiar de Estresse de Buffer Utilizado: {limiar_buffer:.1f}%\n")
    print(f"1. TAXA DE PRODUÇÃO REAL:")
    print(f"   • Ritmo Sem Controle:       {taxa_sem:,.0f} CPH ({horas_sem:.2f} h analisadas)")
    print(f"   • Ritmo Com Controle:       {taxa_com:,.0f} CPH ({horas_com:.2f} h analisadas)")
    print(f"   • GANHO LÍQUIDO REAL:       {ganho_global_cph:+,.0f} CPH ({ganho_global_pct:+.2f}%)\n")

    print(f"2. TEMPO PARADO DE LINHA (v = 0):")
    print(f"   • Sem Controle:             {taxa_parada_sem_h:.0f} s/hora de parada")
    print(f"   • Com Controle:             {taxa_parada_com_h:.0f} s/hora de parada")
    print(f"   • REDUÇÃO DE PARADAS:       {reducao_paradas_pct:+.1f}%\n")

    print(f"3. PERFORMANCE SOB MESMA CONDIÇÃO EXTERNA (Buffer >= {limiar_buffer:.1f}%):")
    print(f"   • Velocidade Sem Controle:  {v_sem_gargalo:,.0f} CPH")
    print(f"   • Velocidade Com Controle:  {v_com_gargalo:,.0f} CPH")
    print(f"   • GANHO COMPROVADO SOB GARGALO: {ganho_gargalo_cph:+,.0f} CPH ({ganho_gargalo_pct:+.2f}%)")
    print("=" * 65)

# Execução de exemplo:
# calcular_ganho_controle("Panel Title-data-2026-11-12 09_22_20.csv", limiar_buffer=70.0)
```

---

## 5. Como Apresentar o Resultado para a Gestão Industrial

Ao justificar o ganho para a equipe técnica ou gerência:
1. **Destaque o Ganho Líquido:** Apresente sempre em garrafas reais entregues por hora de fábrica (CPH), evitando promessas baseadas em setpoints teóricos.
2. **Apresente a Redução de Paradas:** Mostre que o ganho de volume veio da estabilização da linha (redução drástica de paradas de esteira).
3. **Use o Teste de Buffer como Evidência:** Utilize a comparação sob estresse ($Buffer \ge B_{limite}$) para provar que a linha produziu mais por causa da inteligência do algoritmo de modulação, e não por mera coincidência das máquinas adjacentes.
