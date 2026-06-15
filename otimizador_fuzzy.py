import pandas as pd
import numpy as np
import os
import json
import matplotlib.pyplot as plt
import datetime as dt

# =====================================================================
# 1. CONFIGURAÇÃO DOS ARQUIVOS E COLUNAS
# =====================================================================
ARQUIVO_CSV = "dados_completos_fabrica.csv"
ARQUIVO_CONFIG = "config_colunas.json"

# Fallbacks
COL_B1_DPL_UIP = "accumulation_percentage_DPL_UIP_null"
COL_B2_UIP_ECH = "accumulation_percentage_UIP_ECH_null"
COL_B3_ECH_PZ  = "accumulation_percentage_ECH_PZ_null"
COL_B4_PZ_EPC  = "accumulation_percentage_PZ_EPC_null"

COL_V_ECH = "speed_actual_cph_null_filler_1"

if os.path.exists(ARQUIVO_CONFIG):
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            ARQUIVO_CSV = cfg.get("Arquivo_Dados", ARQUIVO_CSV)
            COL_B1_DPL_UIP = cfg.get("Col_Buffer_Antes_Entrada", COL_B1_DPL_UIP)
            COL_B2_UIP_ECH = cfg.get("Col_Buffer_Entrada", COL_B2_UIP_ECH)
            COL_B3_ECH_PZ  = cfg.get("Col_Buffer_Saida", COL_B3_ECH_PZ)
            COL_B4_PZ_EPC  = cfg.get("Col_Buffer_Pos_Saida", COL_B4_PZ_EPC)
            COL_V_ECH = cfg.get("COL_V_ECH", COL_V_ECH)
        print(f"➔ Configuração carregada de '{ARQUIVO_CONFIG}'.")
    except Exception as e:
        print(f"⚠️ Erro ao ler '{ARQUIVO_CONFIG}': {e}. Usando padrões.")

VELOCIDADE_NOMINAL_ECH = 52700.0

if not os.path.exists(ARQUIVO_CSV):
    print(f"⚠️ Arquivo '{ARQUIVO_CSV}' não encontrado! Execute a geração de dados primeiro.")
    exit(1)

df = pd.read_csv(ARQUIVO_CSV)

# Identificar colunas válidas
def resolver_coluna(col_config, col_padrao, opcional=False):
    if not col_config or str(col_config).strip().lower() in ["null", "none", ""]:
        if opcional: return None
        col_config = col_padrao
    if col_config in df.columns: return col_config
    if col_padrao in df.columns: return col_padrao
    if opcional: return None
    raise ValueError(f"Coluna exata '{col_config}' não encontrada no CSV.")

COL_B1_DPL_UIP = resolver_coluna(COL_B1_DPL_UIP, "accumulation_percentage_DPL_UIP_null", opcional=True)
COL_B2_UIP_ECH = resolver_coluna(COL_B2_UIP_ECH, "accumulation_percentage_UIP_ECH_null")
COL_B3_ECH_PZ  = resolver_coluna(COL_B3_ECH_PZ, "accumulation_percentage_ECH_PZ_null")
COL_B4_PZ_EPC  = resolver_coluna(COL_B4_PZ_EPC, "accumulation_percentage_PZ_EPC_null", opcional=True)
COL_V_ECH = resolver_coluna(COL_V_ECH, "speed_actual_cph_null_filler_1")

df["Timestamp"] = pd.to_datetime(df["Timestamp"])
df.ffill(inplace=True)
df.fillna(0.0, inplace=True)

v_ech_real_hist = df[COL_V_ECH].values
vels_ativas = v_ech_real_hist[v_ech_real_hist > 1000]
if len(vels_ativas) > 0:
    VELOCIDADE_NOMINAL_ECH = float(np.percentile(vels_ativas, 90))

# Extrair vetores para iterar rápido
b1_hist = df[COL_B1_DPL_UIP].values if COL_B1_DPL_UIP else np.full(len(df), 50.0)
b2_hist = df[COL_B2_UIP_ECH].values
b3_hist = df[COL_B3_ECH_PZ].values
b4_hist = df[COL_B4_PZ_EPC].values if COL_B4_PZ_EPC else np.full(len(df), 50.0)

# =====================================================================
# 2. MOTOR FUZZY (TAKAGI-SUGENO ORDEM ZERO)
# =====================================================================

def trapezoidal(x, a, b, c, d):
    """Calcula o grau de pertinência trapezoidal [0, 1]."""
    if x <= a or x >= d: return 0.0
    if a < x <= b: return (x - a) / (b - a) if b > a else 1.0
    if b < x <= c: return 1.0
    if c < x < d: return (d - x) / (d - c) if d > c else 1.0
    return 0.0

# Funções de pertinência (Ajustáveis)
def func_baixo(x): return trapezoidal(x, -1, 0, 15, 30)
def func_normal(x): return trapezoidal(x, 15, 30, 70, 85)
def func_alto(x): return trapezoidal(x, 70, 85, 100, 101)

def calcular_velocidade_fuzzy(b1, b2, b3, b4):
    """
    Infere a velocidade baseada nos níveis de pulmão.
    Regras Base (B2 e B3) determinam a operação normal (V_ALTA vs V_REDUZIDA).
    Regras Extremas (B1 e B4) podem sobrepor e forçar V_ZERO.
    """
    v_alta = VELOCIDADE_NOMINAL_ECH
    v_reduzida = VELOCIDADE_NOMINAL_ECH * 0.70
    v_zero = 0.0

    # 1. Avalia pertinências (Fuzzificação)
    b2_baixo = func_baixo(b2)
    b2_normal = func_normal(b2)
    b2_alto = func_alto(b2)
    
    b3_baixo = func_baixo(b3)
    b3_normal = func_normal(b3)
    b3_alto = func_alto(b3)

    # 2. Regras Base (Sistema B2 e B3)
    # R1: Se falta na entrada (B2 Baixo), precisa reduzir
    w1 = b2_baixo
    z1 = v_reduzida
    
    # R2: Se acumulou na saída (B3 Alto), precisa reduzir
    w2 = b3_alto
    z2 = v_reduzida
    
    # R3: Se condição é segura (B2 não é baixo, B3 não é alto), pode rodar na Nominal
    w3 = min(max(b2_normal, b2_alto), max(b3_baixo, b3_normal))
    z3 = v_alta

    num_base = (w1 * z1) + (w2 * z2) + (w3 * z3)
    den_base = w1 + w2 + w3
    
    v_base = (num_base / den_base) if den_base > 0 else v_alta

    # 3. Regras Extremas (Modificador Mestre)
    # Se B1 está em falta extrema ou B4 em acúmulo extremo, o risco é 1.
    b1_baixo = func_baixo(b1) if b1 is not None else 0.0
    b4_alto = func_alto(b4) if b4 is not None else 0.0
    
    risco_extremo = max(b1_baixo, b4_alto)
    
    # Mistura o output base com a parada extrema
    v_sugerida = v_base * (1.0 - risco_extremo) + v_zero * risco_extremo
    
    return v_sugerida

# =====================================================================
# 3. SIMULAÇÃO HISTÓRICA
# =====================================================================
print("\nIniciando Simulação com Controlador Fuzzy Takagi-Sugeno...")

vel_fuzzy = []

# Detectar paradas mecânicas históricas longas para preservar no simulador
time_step = int((df["Timestamp"].iloc[1] - df["Timestamp"].iloc[0]).total_seconds())
if time_step <= 0: time_step = 1

limite_amostras_parada = int((10 * 60) / time_step)
is_zero = (v_ech_real_hist == 0.0)
mascara_parada_longa = np.zeros(len(df), dtype=bool)
contador_parada = 0
inicio_parada = -1

for i in range(len(df)):
    if is_zero[i]:
        if contador_parada == 0: inicio_parada = i
        contador_parada += 1
    else:
        if contador_parada > limite_amostras_parada:
            mascara_parada_longa[inicio_parada:i] = True
        contador_parada = 0
if contador_parada > limite_amostras_parada:
    mascara_parada_longa[inicio_parada:] = True

# Roda o Fuzzy a cada timestamp
for i in range(len(df)):
    if mascara_parada_longa[i]:
        vel_fuzzy.append(0.0)
    else:
        v_sug = calcular_velocidade_fuzzy(b1_hist[i], b2_hist[i], b3_hist[i], b4_hist[i])
        # Limita para não rodar mais rápido que a máquina consegue fisicamente no histórico caso o histórico estivesse lento por setup
        if not is_zero[i] and v_ech_real_hist[i] < VELOCIDADE_NOMINAL_ECH * 0.5:
            # Preserva micro-paradas não atreladas a buffer e transições lentas
            v_sug = min(v_sug, v_ech_real_hist[i])
        vel_fuzzy.append(v_sug)

# =====================================================================
# 4. EXPORTAÇÃO CSV E GRÁFICO
# =====================================================================
print("➔ Salvando resultados em CSV...")
df_fuzzy = pd.DataFrame({
    "Timestamp": df["Timestamp"],
    "Velocidade_Real_Enchedora": v_ech_real_hist,
    "Velocidade_Fuzzy_Sugerida": vel_fuzzy,
    "Buffer_B1": b1_hist,
    "Buffer_B2": b2_hist,
    "Buffer_B3": b3_hist,
    "Buffer_B4": b4_hist
})
df_fuzzy.to_csv("dados_fuzzy_otimizado.csv", index=False)

print("➔ Gerando gráficos comparativos dia a dia...")
df_smooth = df_fuzzy.set_index("Timestamp").resample("15Min").mean().reset_index()
df_smooth['Date'] = df_smooth['Timestamp'].dt.date

pasta_graficos = "graficos_fuzzy"
if not os.path.exists(pasta_graficos):
    os.makedirs(pasta_graficos)

dias_unicos = df_smooth['Date'].dropna().unique()

for dia in dias_unicos:
    df_dia = df_smooth[df_smooth['Date'] == dia]
    if df_dia.empty:
        continue
        
    fig, ax = plt.subplots(figsize=(15, 6))
    ax.plot(df_dia["Timestamp"], df_dia["Velocidade_Real_Enchedora"], label="Velocidade Real (Fábrica)", color="#E74C3C", alpha=0.7, linewidth=2)
    ax.plot(df_dia["Timestamp"], df_dia["Velocidade_Fuzzy_Sugerida"], label="Velocidade Fuzzy", color="#27AE60", alpha=0.9, linewidth=2)
    ax.set_title(f"Comparação de Velocidades da Enchedora (Dia: {dia})", fontsize=14, fontweight="bold")
    ax.set_ylabel("Velocidade (CPH)")
    ax.legend()
    ax.grid(True, linestyle="--", alpha=0.4)

    plt.tight_layout()
    caminho_arquivo = os.path.join(pasta_graficos, f"comparacao_fuzzy_{dia}.png")
    plt.savefig(caminho_arquivo, dpi=150)
    plt.close(fig)
    print(f"   ↳ Salvo: {caminho_arquivo}")

prod_real = (np.array(v_ech_real_hist).sum() / 3600.0) * time_step
prod_fuzzy = (np.array(vel_fuzzy).sum() / 3600.0) * time_step

print(f"\nResultados da Simulação Fuzzy:")
print(f"➔ Produção Real: {int(prod_real)} garrafas")
print(f"➔ Produção Fuzzy: {int(prod_fuzzy)} garrafas")
if prod_fuzzy > prod_real:
    print(f"➔ Ganho Estimado: +{int(prod_fuzzy - prod_real)} ({(prod_fuzzy - prod_real)/prod_real*100:.2f}%)")
else:
    print("➔ Controlador focou em estabilidade (não houve ganho de volume absoluto, mas provável redução de socos).")

print("\nFinalizado com sucesso! Gráfico salvo como 'comparacao_fuzzy.png'.")
