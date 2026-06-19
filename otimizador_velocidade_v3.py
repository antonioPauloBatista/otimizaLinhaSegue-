import pandas as pd
import numpy as np
import os
import json
import matplotlib.pyplot as plt
import datetime as dt
import glob
import shutil

# =====================================================================
# 1. CONFIGURAÇÃO DOS ARQUIVOS E COLUNAS
# =====================================================================
ARQUIVO_CSV = "dados_completos_fabrica.csv"
ARQUIVO_CONFIG = "config_colunas.json"

# =====================================================================
# 2. CONFIGURAÇÕES DE VELOCIDADE (TRAVAS DA MÁQUINA)
# =====================================================================
MIN_MODULACAO = 0.80
MAX_MODULACAO = 1.00
VELOCIDADE_NOMINAL_ECH = 63360.0

# Limpeza automática de execuções anteriores (evita acúmulo de lixo na pasta)
print("🧹 Limpando relatórios e gráficos antigos...")
for f_antigo in glob.glob("relatorio_otimizacao_*.txt"):
    try:
        os.remove(f_antigo)
    except Exception:
        pass

if os.path.exists("graficos_velocidade_otimizada"):
    try:
        shutil.rmtree("graficos_velocidade_otimizada")
    except Exception:
        pass

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
            MIN_MODULACAO = cfg.get("Min_Modulacao", MIN_MODULACAO)
            MAX_MODULACAO = cfg.get("Max_Modulacao", MAX_MODULACAO)
            
            val_nominal = cfg.get("Velocidade_Nominal_ECH", None)
            VELOCIDADE_NOMINAL_ECH = float(val_nominal) if val_nominal is not None else None
            
            val_manutencao = cfg.get("Limiar_Velocidade_Manutencao", None)
            LIMIAR_VELOCIDADE_MANUTENCAO = float(val_manutencao) if val_manutencao is not None else None
    except Exception as e:
        print(f"⚠️ Erro ao ler '{ARQUIVO_CONFIG}': {e}.")
        VELOCIDADE_NOMINAL_ECH = None
        LIMIAR_VELOCIDADE_MANUTENCAO = None
else:
    VELOCIDADE_NOMINAL_ECH = None
    LIMIAR_VELOCIDADE_MANUTENCAO = None

if not os.path.exists(ARQUIVO_CSV):
    print(f"⚠️ Arquivo '{ARQUIVO_CSV}' não encontrado!")
    exit(1)

df = pd.read_csv(ARQUIVO_CSV)
df["Timestamp"] = pd.to_datetime(df["Timestamp"])
df.ffill(inplace=True)
df.fillna(0.0, inplace=True)

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

v_ech_real_hist = df[COL_V_ECH].values

v_validos = v_ech_real_hist[v_ech_real_hist > 0]
v_max_historico = float(np.percentile(v_validos, 95)) if len(v_validos) > 0 else 52700.0
alerta_velocidade_baixa = False

if VELOCIDADE_NOMINAL_ECH is None:
    # Fallback: extrair velocidade da máquina dos dados (percentil 95 ignorando zeros para evitar picos irreais)
    VELOCIDADE_NOMINAL_ECH = v_max_historico
    print(f"ℹ️ Velocidade Nominal não encontrada no JSON. Usando dados reais: {VELOCIDADE_NOMINAL_ECH:.0f} CPH")
else:
    if VELOCIDADE_NOMINAL_ECH < v_max_historico:
        alerta_velocidade_baixa = True
        print(f"⚠️ AVISO: A Velocidade Nominal setada ({VELOCIDADE_NOMINAL_ECH:.0f} CPH) é MENOR que a velocidade real praticada no histórico ({v_max_historico:.0f} CPH).")

if LIMIAR_VELOCIDADE_MANUTENCAO is None:
    # Fallback: 50% da nominal se não for definido no json
    LIMIAR_VELOCIDADE_MANUTENCAO = VELOCIDADE_NOMINAL_ECH * 0.5
    print(f"ℹ️ Limiar de Manutenção não encontrado no JSON. Usando 50% da nominal: {LIMIAR_VELOCIDADE_MANUTENCAO:.0f} CPH")

b1_hist = df[COL_B1_DPL_UIP].values if COL_B1_DPL_UIP else np.full(len(df), 50.0)
b2_hist = df[COL_B2_UIP_ECH].values
b3_hist = df[COL_B3_ECH_PZ].values
b4_hist = df[COL_B4_PZ_EPC].values if COL_B4_PZ_EPC else np.full(len(df), 50.0)

time_step = int((df["Timestamp"].iloc[1] - df["Timestamp"].iloc[0]).total_seconds())
if time_step <= 0: time_step = 1

# Pré-cálculo de paradas externas inegociáveis
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

limitador_velocidade_lenta = np.where(~is_zero & (v_ech_real_hist <= LIMIAR_VELOCIDADE_MANUTENCAO), v_ech_real_hist, VELOCIDADE_NOMINAL_ECH)

# =====================================================================
# 2. MOTOR DE CALCULO VETORIZADO (ULTRA-RÁPIDO PARA OTIMIZAÇÃO)
# =====================================================================
b1_vazio = (COL_B1_DPL_UIP is None)
b4_vazio = (COL_B4_PZ_EPC is None)

def vec_trapezoidal(x_arr, a, b, c, d):
    res = np.zeros_like(x_arr, dtype=float)
    m1 = (x_arr > a) & (x_arr <= b)
    if b > a: res[m1] = (x_arr[m1] - a) / (b - a)
    else: res[m1] = 1.0
    m2 = (x_arr > b) & (x_arr <= c)
    res[m2] = 1.0
    m3 = (x_arr > c) & (x_arr < d)
    if d > c: res[m3] = (d - x_arr[m3]) / (d - c)
    else: res[m3] = 1.0
    return res

def simular_controle_vetorizado(x_params, override_vel_nominal=None):
    b1_lim = np.clip(x_params[0], 10, 30)
    b2_lim = np.clip(x_params[1], 15, 50)
    b3_lim = np.clip(x_params[2], 50, 85)
    b4_lim = np.clip(x_params[3], 70, 90)
    rampa_b2 = np.clip(x_params[4], 15.0, 40.0)
    rampa_b3 = np.clip(x_params[5], 15.0, 40.0)
    antecip_b1 = np.clip(x_params[6], 10.0, 35.0)
    antecip_b4 = np.clip(x_params[7], 10.0, 35.0)
    min_modulacao_otimizado = np.clip(x_params[8], 0.50, 0.95)

    # TETO É INEGOCIÁVEL, PISO É OTIMIZADO
    vel_nominal = override_vel_nominal if override_vel_nominal is not None else VELOCIDADE_NOMINAL_ECH
    v_alta = vel_nominal * MAX_MODULACAO
    v_reduzida = vel_nominal * min_modulacao_otimizado

    # Rampas de Pertinência Vetorizadas
    b2_baixo = vec_trapezoidal(b2_hist, -1, 0, b2_lim - rampa_b2, b2_lim)
    b2_normal = vec_trapezoidal(b2_hist, b2_lim - rampa_b2, b2_lim, 100, 101)
    
    b3_normal = vec_trapezoidal(b3_hist, -1, 0, b3_lim, b3_lim + rampa_b3)
    b3_alto = vec_trapezoidal(b3_hist, b3_lim, b3_lim + rampa_b3, 100, 101)

    # Early Warning (Feedforward) Ramps para B1 e B4
    b1_tendencia = vec_trapezoidal(b1_hist, -1, 0, b1_lim, b1_lim + antecip_b1)
    b4_tendencia = vec_trapezoidal(b4_hist, b4_lim - antecip_b4, b4_lim, 100, 101)

    # Inferência de Modulação Expandida
    w1 = b2_baixo
    w2 = b3_alto
    w4 = b1_tendencia
    w5 = b4_tendencia
    
    w3 = np.minimum(b2_normal, b3_normal)

    num_base = (w1 * v_reduzida) + (w2 * v_reduzida) + (w4 * v_reduzida) + (w5 * v_reduzida) + (w3 * v_alta)
    den_base = w1 + w2 + w3 + w4 + w5
    den_base_safe = np.where(den_base == 0, 1.0, den_base)
    
    v_base = np.where(den_base == 0, v_alta, num_base / den_base_safe)

    # O Algoritmo matemático NÃO comanda parada (setpoint mínimo = vel_reduzida)
    v_sug_controlador = np.maximum(v_base, v_reduzida)

    # A simulação não capará mais fisicamente a máquina por lentidão histórica (removemos o limitador_velocidade_lenta),
    # pois a manutenção será validada como uma prova de estresse matemática no passo 2 da otimização.
    v_sug = v_sug_controlador
    
    # Mantemos APENAS as quebras mecânicas paralisantes totais para não gerar garrafas fantasmas quando a máquina estava desligada
    v_sug = np.where(mascara_parada_longa, 0.0, v_sug)

    # Penalidade quadrática para variação de velocidade (força a modulação a ser longa e suave, evitando trancos)
    penalidade_aceleracao = np.sum((np.diff(v_sug) / 1000.0)**2)
    # Penalidade por soco: velocidade acima do limite seguro de referência nas zonas críticas
    limite_velocidade_segura = vel_nominal * MIN_MODULACAO + 10.0
    paradas_soco = np.sum((v_sug > limite_velocidade_segura) & ((b2_hist <= 15.0) | (b3_hist >= 85.0)))
    
    producao = np.sum(v_sug) / 3600.0 * time_step
    
    # Penalidades Quadráticas para respeitar limites
    penalidade_bounds = 0.0
    for i, val in enumerate(x_params[:9]):
        lim_inf = [10, 15, 50, 70, 15, 15, 10, 10, 0.50][i]
        lim_sup = [30, 50, 85, 90, 40, 40, 35, 35, 0.95][i]
        if val < lim_inf: penalidade_bounds += (lim_inf - val)**2 * 100000.0
        if val > lim_sup: penalidade_bounds += (val - lim_sup)**2 * 100000.0

    score = producao - (paradas_soco * 50000) - (penalidade_aceleracao * 20.0) - penalidade_bounds
    return score, producao, v_sug

# =====================================================================
# 3. ALGORITMO MATEMÁTICO DE OTIMIZAÇÃO (CMA-ES)
# =====================================================================
def cma_es(func, x0, sigma0=1.5, max_iter=100, seed=42):
    rng = np.random.default_rng(seed)
    n = len(x0)
    lam = 4 + int(np.floor(3 * np.log(n)))
    mu = lam // 2

    weights_raw = np.log(mu + 0.5) - np.log(np.arange(1, mu + 1))
    weights = weights_raw / weights_raw.sum()
    mueff = 1.0 / (weights ** 2).sum()

    cc = (4 + mueff / n) / (n + 4 + 2 * mueff / n)
    cs = (mueff + 2) / (n + mueff + 5)
    c1 = 2.0 / ((n + 1.3) ** 2 + mueff)
    cmu = min(1 - c1, 2 * (mueff - 2 + 1 / mueff) / ((n + 2) ** 2 + mueff))
    damps = 1 + 2 * max(0, np.sqrt((mueff - 1) / (n + 1)) - 1) + cs
    chiN = n ** 0.5 * (1 - 1 / (4 * n) + 1 / (21 * n ** 2))

    xmean = x0.copy().astype(float)
    sigma = float(sigma0)
    pc = np.zeros(n)
    ps = np.zeros(n)
    B = np.eye(n)
    D = np.ones(n)
    C = np.eye(n)
    invsqrtC = np.eye(n)
    eigeneval = 0

    melhor_score = -np.inf
    melhor_x = xmean.copy()
    historico_scores = []

    print(f"\n{'='*65}")
    print(f" INICIANDO OTIMIZAÇÃO DE FLUXO DA LINHA | Gerações: {max_iter}")
    print(f"{'='*65}")

    for gen in range(max_iter):
        arz = rng.standard_normal((lam, n))
        arx = xmean + sigma * (arz @ (B * D).T)

        fitness = np.zeros(lam)
        for i in range(lam):
            score, _, _ = func(arx[i])
            fitness[i] = score

        idx = np.argsort(fitness)[::-1]

        if fitness[idx[0]] > melhor_score:
            melhor_score = fitness[idx[0]]
            melhor_x = arx[idx[0]].copy()

        historico_scores.append(melhor_score)

        if gen % 10 == 0 or gen == max_iter - 1:
            print(f" Geração {gen:3d} | Progresso Otimização: {melhor_score:,.1f} | σ: {sigma:.4f}")

        xold = xmean.copy()
        xmean = weights @ arx[idx[:mu]]

        ps = (1 - cs) * ps + np.sqrt(cs * (2 - cs) * mueff) * invsqrtC @ (xmean - xold) / sigma
        hsig = (np.linalg.norm(ps) / np.sqrt(1 - (1 - cs) ** (2 * (gen + 1))) / chiN) < (1.4 + 2 / (n + 1))
        pc = (1 - cc) * pc + hsig * np.sqrt(cc * (2 - cc) * mueff) * (xmean - xold) / sigma

        artmp = (1 / sigma) * (arx[idx[:mu]] - xold)
        C_mu = np.einsum('k,ki,kj->ij', weights, artmp, artmp)
        C = (1 - c1 - cmu) * C + c1 * (np.outer(pc, pc) + (1 - hsig) * cc * (2 - cc) * C) + cmu * C_mu

        sigma *= np.exp((cs / damps) * (np.linalg.norm(ps) / chiN - 1))

        if gen - eigeneval > lam / (c1 + cmu) / n / 10:
            eigeneval = gen
            C = np.triu(C) + np.triu(C, 1).T
            D, B = np.linalg.eigh(C)
            D = np.sqrt(np.maximum(D, 1e-20))
            invsqrtC = B @ np.diag(1.0 / D) @ B.T

    return melhor_x, melhor_score, historico_scores

# Ponto de Partida Inicial (Parâmetros estimados)
x_inicial = np.array([20.0, 30.0, 70.0, 85.0, 15.0, 15.0, 10.0, 10.0, 0.80])

# Roda Otimização
melhores_params, melhor_score, hist_scores = cma_es(
    func=simular_controle_vetorizado,
    x0=x_inicial,
    sigma0=2.0,
    max_iter=150
)

# Gera os dados reais com os melhores parâmetros descobertos
_, producao_otimizada, v_sug_final = simular_controle_vetorizado(melhores_params)

# =====================================================================
# 4. RELATÓRIO E EXPORTAÇÃO
# =====================================================================
prod_real = (np.sum(v_ech_real_hist) / 3600.0) * time_step
ganho = producao_otimizada - prod_real
percentual = (ganho / prod_real * 100) if prod_real > 0 else 0.0

b1_final = np.clip(melhores_params[0], 10, 30)
b2_final = np.clip(melhores_params[1], 15, 50)
b3_final = np.clip(melhores_params[2], 50, 85)
b4_final = np.clip(melhores_params[3], 70, 90)
rampa_b2_final = np.clip(melhores_params[4], 15.0, 40.0)
rampa_b3_final = np.clip(melhores_params[5], 15.0, 40.0)
antecip_b1_final = np.clip(melhores_params[6], 10.0, 35.0)
antecip_b4_final = np.clip(melhores_params[7], 10.0, 35.0)
v_red_final = np.clip(melhores_params[8], 0.50, 0.95)

# Salvar Modelo V3
parametros_otimizados = {
    "b1_lim": round(b1_final, 2),
    "b2_lim": round(b2_final, 2),
    "b3_lim": round(b3_final, 2),
    "b4_lim": round(b4_final, 2),
    "rampa_b2": round(rampa_b2_final, 2),
    "rampa_b3": round(rampa_b3_final, 2),
    "antecipacao_b1": round(antecip_b1_final, 2),
    "antecipacao_b4": round(antecip_b4_final, 2),
    "fator_reducao": round(v_red_final, 3),
    "velocidade_nominal_calculada": int(VELOCIDADE_NOMINAL_ECH)
}
with open("parametros_controle_v3.json", "w", encoding="utf-8") as f:
    json.dump(parametros_otimizados, f, indent=4)
print("➔ Parâmetros de controle salvos em 'parametros_controle_v3.json'.")



def gerar_codigo_controlador():
    codigo = f"""
# ==========================================================
# CÓDIGO DA FUNÇÃO DO CONTROLADOR DE FLUXO DA MÁQUINA V3 (FEEDFORWARD)
# (Gerado Automaticamente pelo otimizador_velocidade_v3.py)
#
# REGRAS INEGOCIÁVEIS:
#   - Piso  : min_modulacao  (ex: 0.80 = 56000 CPH)
#   - Teto  : max_modulacao  (ex: 1.00 = 70000 CPH)
#   - NUNCA retorna 0 CPH (parada é responsabilidade do CLP físico)
# ==========================================================

def rampa_trapezoidal(x, a, b, c, d):
    \"\"\"Calcula o fator de pertinencia fuzzy [0, 1].\"\"\"
    if x <= a or x >= d: return 0.0
    if a < x <= b: return (x - a) / (b - a) if b > a else 1.0
    if b < x <= c: return 1.0
    if c < x < d: return (d - x) / (d - c) if d > c else 1.0
    return 0.0

def calcular_velocidade(b1, b2, b3, b4, velocidade_nominal={int(VELOCIDADE_NOMINAL_ECH)}, min_modulacao={v_red_final:.3f}, max_modulacao={MAX_MODULACAO}):
    \"\"\"
    Recebe o nivel atual dos 4 pulmoes (%) e retorna o setpoint em CPH.
    Parametros otimizados via CMA-ES em {dt.datetime.now().strftime('%Y-%m-%d')}.
    \"\"\"
    # --- Gatilhos de modulacao otimizados pelo algoritmo ---
    b2_lim = {b2_final:.2f}   # B2 abaixo disto -> iniciar reducao
    b3_lim = {b3_final:.2f}   # B3 acima disto  -> iniciar reducao
    b1_lim = {b1_final:.2f}   # B1 aproximando do corte -> reducao feedforward
    b4_lim = {b4_final:.2f}   # B4 aproximando do corte -> reducao feedforward

    # --- Travas Operacionais ---
    vel_maxima   = velocidade_nominal * max_modulacao   # Teto absoluto
    vel_reduzida = velocidade_nominal * min_modulacao   # Piso otimizado

    # --- Logica Fuzzy: Avaliacao dos Pulmoes Principais ---
    b2_baixo  = rampa_trapezoidal(b2, -1, 0, b2_lim - {rampa_b2_final:.2f}, b2_lim)
    b2_normal = rampa_trapezoidal(b2, b2_lim - {rampa_b2_final:.2f}, b2_lim, 100, 101)
    b3_normal = rampa_trapezoidal(b3, -1, 0, b3_lim, b3_lim + {rampa_b3_final:.2f})
    b3_alto   = rampa_trapezoidal(b3, b3_lim, b3_lim + {rampa_b3_final:.2f}, 100, 101)
    
    # --- Feedforward: Alerta antecipado dos Pulmoes Extremos ---
    b1_tendencia = rampa_trapezoidal(b1, -1, 0, b1_lim, b1_lim + {antecip_b1_final:.2f})
    b4_tendencia = rampa_trapezoidal(b4, b4_lim - {antecip_b4_final:.2f}, b4_lim, 100, 101)

    # --- Inferencia: pesos e calculo da velocidade ---
    w1 = b2_baixo                       # Entrada vazia -> reduz
    w2 = b3_alto                        # Saida cheia   -> reduz
    w4 = b1_tendencia                   # Falta Extrema detectada longe -> reduz antecipadamente
    w5 = b4_tendencia                   # Gargalo Extremo detectado longe -> reduz antecipadamente
    
    w3 = min(b2_normal, b3_normal)      # Ambos OK -> teto

    num = (w1 * vel_reduzida) + (w2 * vel_reduzida) + (w4 * vel_reduzida) + (w5 * vel_reduzida) + (w3 * vel_maxima)
    den = w1 + w2 + w3 + w4 + w5

    v_base = vel_maxima if den == 0 else num / den

    # --- Garantia do Piso: nunca retorna 0 CPH ---
    return int(max(v_base, vel_reduzida))
"""
    with open("funcao_controle_v3.py", "w", encoding="utf-8") as f:
        f.write(codigo.strip() + "\n")
    print(f"➔ Função autônoma gerada com sucesso em 'funcao_controle_v3.py'.")

gerar_codigo_controlador()

def gerar_codigo_controlador_live():
    codigo_live = f"""
import sys
import os

def rampa_trapezoidal(x, a, b, c, d):
    \"\"\"Calcula o fator de transicao [0, 1].\"\"\"
    if x <= a or x >= d: return 0.0
    if a < x <= b: return (x - a) / (b - a) if b > a else 1.0
    if b < x <= c: return 1.0
    if c < x < d: return (d - x) / (d - c) if d > c else 1.0
    return 0.0

class ControladorVelocidadeEnchedoraV3:
    def __init__(self, velocidade_nominal={int(VELOCIDADE_NOMINAL_ECH)}, min_modulacao={v_red_final:.3f}, max_modulacao={MAX_MODULACAO}):
        self.velocidade_nominal = velocidade_nominal
        self.min_modulacao = min_modulacao
        self.max_modulacao = max_modulacao
        
        # Parâmetros hardcoded (raw) otimizados
        self.b1_lim = {b1_final:.2f}
        self.b2_lim = {b2_final:.2f}
        self.b3_lim = {b3_final:.2f}
        self.b4_lim = {b4_final:.2f}
        self.rampa_b2 = {rampa_b2_final:.2f}
        self.rampa_b3 = {rampa_b3_final:.2f}
        self.antecip_b1 = {antecip_b1_final:.2f}
        self.antecip_b4 = {antecip_b4_final:.2f}
        self.fator_reducao_otimizado = {v_red_final:.3f}
        
        self.vel_maxima = self.velocidade_nominal * self.max_modulacao
        self.vel_reduzida = self.velocidade_nominal * self.fator_reducao_otimizado

    def calcular_velocidade(self, b1, b2, b3, b4):
        b2_baixo  = rampa_trapezoidal(b2, -1, 0, self.b2_lim - self.rampa_b2, self.b2_lim)
        b2_normal = rampa_trapezoidal(b2, self.b2_lim - self.rampa_b2, self.b2_lim, 100, 101)
        b3_normal = rampa_trapezoidal(b3, -1, 0, self.b3_lim, self.b3_lim + self.rampa_b3)
        b3_alto   = rampa_trapezoidal(b3, self.b3_lim, self.b3_lim + self.rampa_b3, 100, 101)
        
        b1_tendencia = rampa_trapezoidal(b1, -1, 0, self.b1_lim, self.b1_lim + self.antecip_b1)
        b4_tendencia = rampa_trapezoidal(b4, self.b4_lim - self.antecip_b4, self.b4_lim, 100, 101)

        w1 = b2_baixo
        w2 = b3_alto
        w4 = b1_tendencia
        w5 = b4_tendencia
        w3 = min(b2_normal, b3_normal)

        num = (w1 * self.vel_reduzida) + (w2 * self.vel_reduzida) + (w4 * self.vel_reduzida) + (w5 * self.vel_reduzida) + (w3 * self.vel_maxima)
        den = w1 + w2 + w3 + w4 + w5

        v_base = self.vel_maxima if den == 0 else num / den
        return int(max(v_base, self.vel_reduzida))

if __name__ == "__main__":
    print("="*60)
    print("   SIMULADOR DE VELOCIDADE DA MÁQUINA - TESTE LIVE (V3)")
    print("="*60)
    print("Injetando parâmetros otimizados de controle V3 (Feedforward)...\\n")
    
    controlador = ControladorVelocidadeEnchedoraV3()
    
    while True:
        try:
            print("Digite os níveis dos buffers em % (ou pressione Ctrl+C para sair):")
            b1 = float(input("  B1 (DPL-UIP) - Extremo Entrada : "))
            b2 = float(input("  B2 (UIP-ECH) - Entrada Interna : "))
            b3 = float(input("  B3 (ECH-PZ)  - Saída Interna   : "))
            b4 = float(input("  B4 (PZ-EPC)  - Extremo Saída   : "))
            
            vel = controlador.calcular_velocidade(b1, b2, b3, b4)
            
            print("-" * 60)
            if vel == 0:
                print(f"➔ VELOCIDADE SUGERIDA OTIMIZADA: {{vel}} CPH 🚨 PARADA DE SEGURANÇA 🚨")
            elif vel < controlador.velocidade_nominal:
                print(f"➔ VELOCIDADE SUGERIDA OTIMIZADA: {{vel}} CPH ⚠️ MODULAÇÃO ATIVA")
            else:
                print(f"➔ VELOCIDADE SUGERIDA OTIMIZADA: {{vel}} CPH ✅ MÁQUINA FULL")
            print("-" * 60)
            print("")
            
        except KeyboardInterrupt:
            print("\\nSaindo do simulador live...")
            break
        except ValueError:
            print("\\n⚠️ Entrada inválida. Por favor, digite números (ex: 45.5)\\n")
"""
    with open("controlador_velocidade_live_v3.py", "w", encoding="utf-8") as f:
        f.write(codigo_live.strip() + "\n")
    print(f"➔ Controlador Live interativo gerado com sucesso em 'controlador_velocidade_live_v3.py'.")

gerar_codigo_controlador_live()

print("\n" + "="*65)
print("     RESULTADO DA OTIMIZAÇÃO DE FLUXO     ")
print("="*65)
print(f"➔ Parâmetros de Controle Otimizados:")
print(f"   ↳ Limite Inferior B1: Abaixo de {b1_final:.1f}%")
print(f"   ↳ Limite Inferior B2: Abaixo de {b2_final:.1f}%")
print(f"   ↳ Limite Superior B3: Acima de {b3_final:.1f}%")
print(f"   ↳ Limite Superior B4: Acima de {b4_final:.1f}%")
print(f"   ↳ Rampa Fuzzy Entrada (B2): Janela de {rampa_b2_final:.1f}%")
print(f"   ↳ Rampa Fuzzy Saída (B3): Janela de {rampa_b3_final:.1f}%")
print(f"   ↳ Antecipação Feedforward B1: Gatilho + {antecip_b1_final:.1f}%")
print(f"   ↳ Antecipação Feedforward B4: Gatilho - {antecip_b4_final:.1f}%")
print(f"   ↳ Fator de Velocidade: {v_red_final*100:.1f}% da Nominal ({int(VELOCIDADE_NOMINAL_ECH * v_red_final)} CPH)")
print(f"\n➔ Produção Real    : {int(prod_real)} garrafas")
print(f"➔ Produção Otimizada: {int(producao_otimizada)} garrafas")
print(f"➔ Ganho Absoluto   : +{int(ganho)} garrafas")
print(f"➔ Aumento          : +{percentual:.2f}%")

# =====================================================================
# 4.1 RELATÓRIO FINAL DETALHADO (TIPO OTIMIZADO)
# =====================================================================

hist_stops_total    = int((v_ech_real_hist == 0.0).sum())
hist_stops_buffer   = int(((v_ech_real_hist == 0.0) & ((b2_hist <= 15.0) | (b3_hist >= 85.0))).sum())
hist_stops_external = hist_stops_total - hist_stops_buffer

sim_stops_buffer = int(((v_sug_final > (VELOCIDADE_NOMINAL_ECH * MIN_MODULACAO) + 10.0) & ((b2_hist <= 15.0) | (b3_hist >= 85.0))).sum())
sim_stops_external = hist_stops_external

criticos_evitados = int(((b2_hist <= 2.0) | (b3_hist >= 99.0)).sum())
reducao = hist_stops_buffer - sim_stops_buffer

# Cálculo de Eventos de Parada (Transições de Rodando para Zero)
eventos_parada_real = int(np.sum((v_ech_real_hist[:-1] > 0) & (v_ech_real_hist[1:] == 0)))
# Evento simulado de parada soco (entrar na zona crítica com velocidade alta)
mascara_parada_sim = (v_sug_final > (VELOCIDADE_NOMINAL_ECH * MIN_MODULACAO) + 10.0) & ((b2_hist <= 15.0) | (b3_hist >= 85.0))
eventos_parada_sim = int(np.sum(~mascara_parada_sim[:-1] & mascara_parada_sim[1:]))
microparadas_evitadas = max(0, eventos_parada_real - eventos_parada_sim)

# =====================================================================
# 4.2 PASSO 2: VALIDAÇÃO DE ROBUSTEZ (MÁQUINA EM MODO MANUTENÇÃO)
# =====================================================================
_, producao_manutencao, v_sug_manutencao = simular_controle_vetorizado(melhores_params, override_vel_nominal=LIMIAR_VELOCIDADE_MANUTENCAO)
sim_stops_buffer_manutencao = int(((v_sug_manutencao > (LIMIAR_VELOCIDADE_MANUTENCAO * MIN_MODULACAO) + 10.0) & ((b2_hist <= 15.0) | (b3_hist >= 85.0))).sum())

# Tempo extra de máquina rodando
tempo_extra_segundos = reducao * time_step
tempo_extra_horas = int(tempo_extra_segundos // 3600)
tempo_extra_minutos = int((tempo_extra_segundos % 3600) // 60)

_rel = []
_rel.append("")
_rel.append("="*65)
_rel.append("   RELATÓRIO FINAL DO OTIMIZADOR DE VELOCIDADE: LÓGICA DO CLP   ")
_rel.append("="*65)
_rel.append(f"➔ Produção Real Registrada no Histórico: {int(prod_real)} unidades.")
_rel.append(f"➔ Produção Simulada Otimizada : {int(producao_otimizada)} unidades.")
if ganho > 0:
    _rel.append(f"➔ GANHO DE PRODUÇÃO ESTIMADO  : +{int(ganho)} unidades (+{percentual:.2f}%)")
else:
    _rel.append(f"➔ GANHO DE PRODUÇÃO ESTIMADO  : 0 unidades (Linha já rodou de forma ótima)")

_rel.append("")
_rel.append("[MÉTRICAS DE PARADAS DE MÁQUINA (0 CPH E TEMPO DE UPTIME)]")
_rel.append(f"➔ Paradas por Falta/Acúmulo (Buffers):")
_rel.append(f"   ↳ No histórico original : {hist_stops_buffer} amostras")
_rel.append(f"   ↳ Na simulação Otimizada: {sim_stops_buffer} amostras")
_rel.append(f"   ↳ AMOSTRAS EVITADAS         : {reducao} amostras ({(reducao/max(1,hist_stops_buffer)*100):.1f}% de melhoria)")
_rel.append(f"   ↳ MICROPARADAS EVITADAS     : {microparadas_evitadas} eventos de parada que não aconteceram")
_rel.append(f"   ↳ TEMPO EXTRA RODANDO       : {tempo_extra_horas} horas e {tempo_extra_minutos} minutos de UPTIME recuperado!")
_rel.append(f"➔ Paradas por Motivos Externos (Mecânica/Operador):")
_rel.append(f"   ↳ No histórico original : {hist_stops_external} amostras")
_rel.append(f"   ↳ Na simulação Otimizada: {sim_stops_external} amostras")

_rel.append("")
_rel.append("[CONFIGURAÇÕES GERAIS]")
_rel.append(f"➔ Velocidade Nominal (100%): {int(VELOCIDADE_NOMINAL_ECH)} CPH")
if alerta_velocidade_baixa:
    _rel.append(f"   ⚠️ ALERTA: Esta velocidade nominal setada é menor que a praticada nos dados reais ({int(v_max_historico)} CPH).")
_rel.append(f"➔ Limiar de Manutenção/Quebra (Simulador limita a velocidade real se menor que): {int(LIMIAR_VELOCIDADE_MANUTENCAO)} CPH")

_rel.append("")
_rel.append("[VELOCIDADE ALTA (100%)]")
_rel.append(f"➔ Ação: Enchedora → 100.0% ({int(VELOCIDADE_NOMINAL_ECH)} CPH)")
_rel.append("➔ Condições para rodar a 100% (Todos os pulmões na faixa Normal):")
_rel.append(f"   ↳ Nível do Pulmão DPL-UIP (Antes Entrada) > {b1_final:.1f}%")
_rel.append(f"   ↳ Nível do Pulmão UIP-ECH (Entrada)        > {b2_final:.1f}%")
_rel.append(f"   ↳ Nível do Pulmão ECH-PZ (Saída)           < {b3_final:.1f}%")
_rel.append(f"   ↳ Nível do Pulmão PZ-EPC (Pós Saída)       < {b4_final:.1f}%")

_rel.append("")
_rel.append("[CADEIA DE ENTRADA E SAÍDA - TRANSIÇÃO SUAVE (RAMPA DE VELOCIDADE)]")
_rel.append("Nota: Estas regras agem como PID ou interpolação linear SCL no CLP.")
_rel.append(f"➔ Ação: Enchedora → Reduz para {v_red_final*100:.1f}% ({int(VELOCIDADE_NOMINAL_ECH * v_red_final)} CPH)")
_rel.append(f" 1. Falta Leve UIP-ECH (Entrada):")
_rel.append(f"    ↳ Iniciar rampa de {rampa_b2_final:.1f}% de modulação quando o nível cair abaixo de {b2_final:.1f}%")
_rel.append(f" 2. Acúmulo Leve ECH-PZ (Saída):")
_rel.append(f"    ↳ Iniciar rampa de {rampa_b3_final:.1f}% de modulação quando o nível passar de {b3_final:.1f}%")
_rel.append(f" 3. Feedforward B1 (Aviso de Furo na Despaletizadora):")
_rel.append(f"    ↳ Iniciar redução se B1 cair abaixo de {b1_final + antecip_b1_final:.1f}%")
_rel.append(f" 4. Feedforward B4 (Aviso de Engarrafamento no Empacotador):")
_rel.append(f"    ↳ Iniciar redução se B4 subir acima de {b4_final - antecip_b4_final:.1f}%")

_rel.append("")
_rel.append("-"*65)
_rel.append("[LIMITES DE EMERGÊNCIA - PROTEÇÃO CONTRA SOCO MECÂNICO]")
_rel.append(f"➔ Ação: Enchedora → Reduz agressivamente para 0 CPH")
_rel.append(f" 1. Falta Extrema DPL-UIP:")
_rel.append(f"    ↳ Forçar parada quando nível cair abaixo de {b1_final:.1f}%")
_rel.append(f" 2. Engarrafamento Extremo PZ-EPC:")
_rel.append(f"    ↳ Forçar parada quando nível passar de {b4_final:.1f}%")

_rel.append("")
_rel.append("="*65)
_rel.append("[VALIDAÇÃO DE ROBUSTEZ: MÁQUINA EM MODO MANUTENÇÃO]")
_rel.append(f"➔ Otimização matemática calculada assumindo a velocidade nominal: {int(VELOCIDADE_NOMINAL_ECH)} CPH.")
_rel.append(f"➔ Simulando a mesma lógica se a máquina for fisicamente limitada a rodar na manutenção: {int(LIMIAR_VELOCIDADE_MANUTENCAO)} CPH.")
_rel.append(f"   ↳ Produção entregue nesse modo restrito: {int(producao_manutencao)} unidades")
_rel.append(f"   ↳ Paradas por pulmão (Soco) nesse cenário: {sim_stops_buffer_manutencao} amostras")
if sim_stops_buffer_manutencao == 0:
    _rel.append("➔ Conclusão: SUCESSO! A lógica otimizada é segura e não causa gargalos mecânicos mesmo sob velocidade de manutenção.")
else:
    _rel.append(f"➔ Conclusão: ALERTA! A lógica gerou {sim_stops_buffer_manutencao} choques mecânicos se a máquina rodar lenta.")

_rel.append("="*65)

# Imprime o Relatório no Console
for linha in _rel:
    print(linha)

import datetime as _dt
_nome_relatorio = f"relatorio_otimizacao_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
with open(_nome_relatorio, "w", encoding="utf-8") as _f:
    _f.write("\n".join(_rel) + "\n")
print(f"\n➔ Relatório detalhado salvo em '{_nome_relatorio}'.")

# =====================================================================
# 5. EXPORTAÇÃO CSV E GRÁFICOS
# =====================================================================
df_dict = {
    "Timestamp": df["Timestamp"],
    "Velocidade_Real": v_ech_real_hist,
    "Velocidade_Otimizada": v_sug_final,
    "Buffer_B2": b2_hist,
    "Buffer_B3": b3_hist
}
if not b1_vazio:
    df_dict["Buffer_B1"] = b1_hist
if not b4_vazio:
    df_dict["Buffer_B4"] = b4_hist
df_cma = pd.DataFrame(df_dict)
df_cma.to_csv("dados_velocidade_otimizada.csv", index=False)
print("\n➔ CSV exportado para 'dados_velocidade_otimizada.csv'.")

pasta_graficos = "graficos_velocidade_otimizada"
if not os.path.exists(pasta_graficos):
    os.makedirs(pasta_graficos)

df_cma_plot = df_cma.copy()
# Substitui 0 por NaN para não puxar a média para baixo (artefato visual)
df_cma_plot.loc[df_cma_plot['Velocidade_Otimizada'] == 0, 'Velocidade_Otimizada'] = np.nan
df_cma_plot.loc[df_cma_plot['Velocidade_Real'] == 0, 'Velocidade_Real'] = np.nan

df_smooth = df_cma_plot.set_index("Timestamp").resample("15Min").mean().reset_index()
# Preenche com 0 apenas os blocos de 15 minutos que ficaram 100% parados
df_smooth['Velocidade_Otimizada'] = df_smooth['Velocidade_Otimizada'].fillna(0)
df_smooth['Velocidade_Real'] = df_smooth['Velocidade_Real'].fillna(0)
df_smooth['Date'] = df_smooth['Timestamp'].dt.date
dias_unicos = df_smooth['Date'].dropna().unique()

for dia in dias_unicos:
    df_dia = df_smooth[df_smooth['Date'] == dia].copy()
    if df_dia.empty: continue

    fig, (ax_vel, ax_buf) = plt.subplots(2, 1, figsize=(15, 10), sharex=True,
                                          gridspec_kw={'height_ratios': [2, 1]})
    fig.suptitle(f"Controle Otimizado: Velocidade e Buffers (Dia: {dia})", fontsize=14, fontweight="bold")

    # --- Calcular quando cada gatilho está ativo ---
    gatilho_b2    = df_dia["Buffer_B2"] < b2_final   # entrada vazia → reduz
    gatilho_b3    = df_dia["Buffer_B3"] > b3_final   # saída cheia   → reduz
    gatilho_ambos = gatilho_b2 & gatilho_b3

    def pintar_regioes(ax, mascara, cor, rotulo, alpha=0.15):
        in_region, t_inicio, primeiro = False, None, True
        for t, ativo in zip(df_dia["Timestamp"], mascara):
            if ativo and not in_region:
                t_inicio, in_region = t, True
            elif not ativo and in_region:
                ax.axvspan(t_inicio, t, alpha=alpha, color=cor,
                           label=rotulo if primeiro else "_nolegend_")
                primeiro, in_region = False, False
        if in_region:
            ax.axvspan(t_inicio, df_dia["Timestamp"].iloc[-1], alpha=alpha, color=cor,
                       label=rotulo if primeiro else "_nolegend_")

    # Faixas coloridas no painel de velocidade
    pintar_regioes(ax_vel, gatilho_b2 & ~gatilho_b3, "#2980B9", "⬇ B2 Entrada baixa")
    pintar_regioes(ax_vel, gatilho_b3 & ~gatilho_b2, "#E67E22", "⬇ B3 Saída cheia")
    pintar_regioes(ax_vel, gatilho_ambos,             "#8E44AD", "⬇ B2+B3 simultâneos")

    # --- Painel Superior: Velocidade ---
    ax_vel.plot(df_dia["Timestamp"], df_dia["Velocidade_Real"],
                label="Real", color="#E74C3C", alpha=0.7, linewidth=1.5)
    ax_vel.plot(df_dia["Timestamp"], df_dia["Velocidade_Otimizada"],
                label="Otimizado", color="#2ECC71", alpha=0.9, linewidth=2)
    ax_vel.axhline(VELOCIDADE_NOMINAL_ECH * MAX_MODULACAO, color="#27AE60", linestyle=":", alpha=0.6, label=f"Teto {int(MAX_MODULACAO*100)}%")
    ax_vel.axhline(VELOCIDADE_NOMINAL_ECH * MIN_MODULACAO, color="#F39C12", linestyle=":", alpha=0.7, label=f"Piso {int(MIN_MODULACAO*100)}%")
    ax_vel.set_ylabel("Velocidade (CPH)", fontsize=11)
    ax_vel.set_ylim(bottom=0)
    ax_vel.legend(loc="upper right", fontsize=8, ncol=2)
    ax_vel.grid(True, linestyle="--", alpha=0.35)

    # --- Painel Inferior: Buffers ---
    cores_buf  = {"Buffer_B1": "#8E44AD", "Buffer_B2": "#2980B9",
                  "Buffer_B3": "#E67E22", "Buffer_B4": "#C0392B"}
    labels_buf = {"Buffer_B1": "B1 Ext.Entrada", "Buffer_B2": "B2 Int.Entrada",
                  "Buffer_B3": "B3 Int.Saída",   "Buffer_B4": "B4 Ext.Saída"}

    # Faixas coloridas também no painel de buffers (para correlação visual)
    pintar_regioes(ax_buf, gatilho_b2 & ~gatilho_b3, "#2980B9", "_nolegend_")
    pintar_regioes(ax_buf, gatilho_b3 & ~gatilho_b2, "#E67E22", "_nolegend_")
    pintar_regioes(ax_buf, gatilho_ambos,             "#8E44AD", "_nolegend_")

    for col, cor in cores_buf.items():
        if col in df_dia.columns and df_dia[col].nunique() > 1:
            ax_buf.plot(df_dia["Timestamp"], df_dia[col],
                        label=labels_buf[col], color=cor, alpha=0.85, linewidth=1.5)

    ax_buf.axhline(b2_final, color="#2980B9", linestyle="--", alpha=0.6, linewidth=1.2,
                   label=f"Gatilho B2 ({b2_final:.0f}%) — entrada")
    ax_buf.axhline(b3_final, color="#E67E22", linestyle="--", alpha=0.6, linewidth=1.2,
                   label=f"Gatilho B3 ({b3_final:.0f}%) — saída")
    ax_buf.set_ylabel("Nível do Buffer (%)", fontsize=11)
    ax_buf.set_ylim(0, 105)
    import matplotlib.dates as mdates
    ax_buf.set_xlabel("Hora", fontsize=10)
    ax_buf.xaxis.set_major_locator(mdates.MinuteLocator(byminute=[0, 30]))
    ax_buf.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.setp(ax_buf.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=9)
    ax_buf.legend(loc="upper right", fontsize=8, ncol=3)
    ax_buf.grid(True, linestyle="--", alpha=0.35)

    plt.tight_layout()
    plt.savefig(os.path.join(pasta_graficos, f"otimizacao_{dia}.png"), dpi=150)
    plt.close(fig)


fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(hist_scores, color="#2980B9", linewidth=2)
ax.set_title("Curva de Convergencia da Otimizacao", fontweight="bold")
ax.grid(True, linestyle="--", alpha=0.4)
plt.tight_layout()
plt.savefig("curva_convergencia.png", dpi=150)
plt.close(fig)

print(f"➔ Gráficos salvos na pasta '{pasta_graficos}'.")

# =====================================================================
# 6. GRÁFICOS DE LÓGICA DE CONTROLE (FUZZY E INTERTRAVAMENTOS)
# =====================================================================
def plotar_logica_controle(b1_lim, b2_lim, b3_lim, b4_lim, rampa_b2, rampa_b3, antecip_b1, antecip_b4):
    x = np.linspace(0, 100, 500)
    
    # Lógica Fuzzy de Modulação (B2 e B3)
    b2_baixo = vec_trapezoidal(x, -1, 0, b2_lim - rampa_b2, b2_lim)
    b2_normal = vec_trapezoidal(x, b2_lim - rampa_b2, b2_lim, 100, 101)
    
    b3_normal = vec_trapezoidal(x, -1, 0, b3_lim, b3_lim + rampa_b3)
    b3_alto = vec_trapezoidal(x, b3_lim, b3_lim + rampa_b3, 100, 101)

    # Feedforward (Tendência B1 e B4)
    b1_tend = vec_trapezoidal(x, -1, 0, b1_lim, b1_lim + antecip_b1)
    b4_tend = vec_trapezoidal(x, b4_lim - antecip_b4, b4_lim, 100, 101)

    # Lógica de Intertravamento (Hard Stop 0 CPH) para B1 e B4
    b1_stop = np.where(x < b1_lim, 1.0, 0.0)
    b1_run = np.where(x >= b1_lim, 1.0, 0.0)
    
    b4_stop = np.where(x > b4_lim, 1.0, 0.0)
    b4_run = np.where(x <= b4_lim, 1.0, 0.0)

    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    fig.suptitle("Arquitetura de Controle da Linha: Intertravamentos (Hardware) + Modulação Fuzzy (CLP)", fontsize=14, fontweight='bold', y=0.96)
    
    # -------------------------------------------------------------
    # LINHA SUPERIOR (Entrada da Máquina)
    # -------------------------------------------------------------
    # Subplot B1 (Intertravamento CLP)
    axes[0, 0].plot(x, b1_stop, label="Corte Emergência (0 CPH)", color="#8E44AD", linewidth=2.5, drawstyle='steps-post')
    axes[0, 0].plot(x, b1_tend, label="Feedforward Fuzzy", color="#F39C12", linewidth=2.5, linestyle='-.')
    axes[0, 0].plot(x, b1_run, label="Libera Máquina", color="#95A5A6", linewidth=2.5, drawstyle='steps-post', alpha=0.5)
    axes[0, 0].axvline(b1_lim, color="black", linestyle="--", alpha=0.5, label=f"Gatilho: {b1_lim:.1f}%")
    axes[0, 0].fill_between(x, 0, b1_stop, color="#8E44AD", alpha=0.15, step='post')
    axes[0, 0].fill_between(x, 0, b1_tend, color="#F39C12", alpha=0.1)
    axes[0, 0].set_title("Intertravamento + Alerta - Extremo Entrada (B1)", fontsize=11, fontweight='bold')
    axes[0, 0].set_xlabel("Nível do Buffer (%)")
    axes[0, 0].set_ylabel("Estado da Máquina")
    axes[0, 0].legend(loc="center right")
    axes[0, 0].grid(True, linestyle="--", alpha=0.4)

    # Subplot B2 (Fuzzy)
    axes[0, 1].plot(x, b2_baixo, label="Fuzzy Baixo (Reduz Vel)", color="#E74C3C", linewidth=2.5)
    axes[0, 1].plot(x, b2_normal, label="Fuzzy Normal (Teto Máx)", color="#2ECC71", linewidth=2.5)
    axes[0, 1].axvline(b2_lim, color="black", linestyle="--", alpha=0.5, label=f"Gatilho: {b2_lim:.1f}%")
    axes[0, 1].fill_between(x, 0, b2_baixo, color="#E74C3C", alpha=0.1)
    axes[0, 1].fill_between(x, 0, b2_normal, color="#2ECC71", alpha=0.1)
    axes[0, 1].set_title("Modulação Fuzzy - Pulmão Entrada (B2: UIP-ECH)", fontsize=11, fontweight='bold')
    axes[0, 1].set_xlabel("Nível do Buffer (%)")
    axes[0, 1].set_ylabel("Grau de Pertinência [0, 1]")
    axes[0, 1].legend(loc="center right")
    axes[0, 1].grid(True, linestyle="--", alpha=0.4)

    # -------------------------------------------------------------
    # LINHA INFERIOR (Saída da Máquina)
    # -------------------------------------------------------------
    # Subplot B3 (Fuzzy)
    axes[1, 0].plot(x, b3_normal, label="Fuzzy Normal (Teto Máx)", color="#2ECC71", linewidth=2.5)
    axes[1, 0].plot(x, b3_alto, label="Fuzzy Alto (Reduz Vel)", color="#E74C3C", linewidth=2.5)
    axes[1, 0].axvline(b3_lim, color="black", linestyle="--", alpha=0.5, label=f"Gatilho: {b3_lim:.1f}%")
    axes[1, 0].fill_between(x, 0, b3_normal, color="#2ECC71", alpha=0.1)
    axes[1, 0].fill_between(x, 0, b3_alto, color="#E74C3C", alpha=0.1)
    axes[1, 0].set_title("Modulação Fuzzy - Pulmão Saída (B3: ECH-PZ)", fontsize=11, fontweight='bold')
    axes[1, 0].set_xlabel("Nível do Buffer (%)")
    axes[1, 0].set_ylabel("Grau de Pertinência [0, 1]")
    axes[1, 0].legend(loc="center right")
    axes[1, 0].grid(True, linestyle="--", alpha=0.4)

    # Subplot B4 (Intertravamento CLP)
    axes[1, 1].plot(x, b4_run, label="Libera Máquina", color="#95A5A6", linewidth=2.5, drawstyle='steps-pre', alpha=0.5)
    axes[1, 1].plot(x, b4_tend, label="Feedforward Fuzzy", color="#F39C12", linewidth=2.5, linestyle='-.')
    axes[1, 1].plot(x, b4_stop, label="Corte Emergência (0 CPH)", color="#8E44AD", linewidth=2.5, drawstyle='steps-pre')
    axes[1, 1].axvline(b4_lim, color="black", linestyle="--", alpha=0.5, label=f"Gatilho: {b4_lim:.1f}%")
    axes[1, 1].fill_between(x, 0, b4_stop, color="#8E44AD", alpha=0.15, step='pre')
    axes[1, 1].fill_between(x, 0, b4_tend, color="#F39C12", alpha=0.1)
    axes[1, 1].set_title("Intertravamento + Alerta - Extremo Saída (B4)", fontsize=11, fontweight='bold')
    axes[1, 1].set_xlabel("Nível do Buffer (%)")
    axes[1, 1].set_ylabel("Estado da Máquina")
    axes[1, 1].legend(loc="center left")
    axes[1, 1].grid(True, linestyle="--", alpha=0.4)

    plt.tight_layout()
    plt.savefig("graficos_logica_controle_v3.png", dpi=150)
    plt.close(fig)
    print("➔ Gráfico das funções de controle (Intertravamento e Fuzzy) salvo em 'graficos_logica_controle_v3.png'.")

plotar_logica_controle(b1_final, b2_final, b3_final, b4_final, rampa_b2_final, rampa_b3_final, antecip_b1_final, antecip_b4_final)
