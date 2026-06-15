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
            VELOCIDADE_NOMINAL_ECH = float(cfg.get("Velocidade_Nominal_ECH", 52700.0))
    except Exception as e:
        print(f"⚠️ Erro ao ler '{ARQUIVO_CONFIG}': {e}.")
else:
    VELOCIDADE_NOMINAL_ECH = 52700.0

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
# A VELOCIDADE_NOMINAL_ECH agora vem estritamente do config_colunas.json

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

limitador_velocidade_lenta = np.where(~is_zero & (v_ech_real_hist < VELOCIDADE_NOMINAL_ECH * 0.5), v_ech_real_hist, VELOCIDADE_NOMINAL_ECH)

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

def simular_controle_vetorizado(x_params):
    b1_lim = np.clip(x_params[0], 10, 30)
    b2_lim = np.clip(x_params[1], 15, 50)
    b3_lim = np.clip(x_params[2], 50, 85)
    b4_lim = np.clip(x_params[3], 70, 90)

    # PISO E TETO SÃO INEGOCIÁVEIS (Vêm direto do JSON, sem otimização)
    v_alta = VELOCIDADE_NOMINAL_ECH * MAX_MODULACAO
    v_reduzida = VELOCIDADE_NOMINAL_ECH * MIN_MODULACAO

    # Rampas de Pertinência Vetorizadas
    b2_baixo = vec_trapezoidal(b2_hist, -1, 0, b2_lim - 15, b2_lim)
    b2_normal = vec_trapezoidal(b2_hist, b2_lim - 15, b2_lim, 100, 101)
    
    b3_normal = vec_trapezoidal(b3_hist, -1, 0, b3_lim, b3_lim + 15)
    b3_alto = vec_trapezoidal(b3_hist, b3_lim, b3_lim + 15, 100, 101)

    b1_baixo = vec_trapezoidal(b1_hist, -1, 0, b1_lim - 10, b1_lim)
    b4_alto = vec_trapezoidal(b4_hist, b4_lim, b4_lim + 10, 100, 101)

    # Inferência de Modulação
    w1 = b2_baixo
    w2 = b3_alto
    w3 = np.minimum(b2_normal, b3_normal)

    num_base = (w1 * v_reduzida) + (w2 * v_reduzida) + (w3 * v_alta)
    den_base = w1 + w2 + w3
    den_base_safe = np.where(den_base == 0, 1.0, den_base)
    
    v_base = np.where(den_base == 0, v_alta, num_base / den_base_safe)

    # O Algoritmo matemático NÃO comanda parada (setpoint mínimo = vel_reduzida)
    v_sug_controlador = np.maximum(v_base, v_reduzida)

    # SIMULAÇÃO DA FÍSICA: Se o pulmão cruzar a linha crítica, o intertravamento do CLP corta o motor (0 CPH real)
    # Se o pulmão extremo (B1 ou B4) não existir, o corte seco recai sobre o pulmão principal (B2 < 5% ou B3 > 95%)
    parada_falta = (b2_hist < 5.0) if b1_vazio else (b1_hist < b1_lim)
    parada_acumulo = (b3_hist > 95.0) if b4_vazio else (b4_hist > b4_lim)
    
    parada_emergencia = parada_falta | parada_acumulo
    v_sug_fisica = np.where(parada_emergencia, 0.0, v_sug_controlador)

    # Filtros Históricos Físicos
    v_sug = np.where(mascara_parada_longa, 0.0, v_sug_fisica)
    # Limitador do histórico real, mas NUNCA rompendo o piso de modulação exigido
    v_sug_limitada = np.minimum(v_sug, limitador_velocidade_lenta)
    v_sug = np.where((v_sug_limitada > 0) & (v_sug_limitada < v_reduzida), v_reduzida, v_sug_limitada)

    # Cálculo do Score de Fitness (Produção - Penalidades)
    mudancas_velocidade = np.sum(np.abs(np.diff(v_sug)) > 2000)
    paradas_soco = np.sum((v_sug < 100) & ((b2_hist <= 15.0) | (b3_hist >= 85.0)))
    
    producao = np.sum(v_sug) / 3600.0 * time_step
    
    # Penalidades Quadráticas para respeitar limites
    penalidade_bounds = 0.0
    for i, val in enumerate(x_params[:4]):
        lim_inf = [10, 15, 50, 70][i]
        lim_sup = [30, 50, 85, 90][i]
        if val < lim_inf: penalidade_bounds += (lim_inf - val)**2 * 100000.0
        if val > lim_sup: penalidade_bounds += (val - lim_sup)**2 * 100000.0

    score = producao - (paradas_soco * 150) - (mudancas_velocidade * 0.5) - penalidade_bounds
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
x_inicial = np.array([20.0, 30.0, 70.0, 85.0])

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
v_red_final = MIN_MODULACAO

# =====================================================================
# 3. ALGORITMO EVOLUTIVO (CMA-ES)
# =====================================================================
def otimizar_parametros():
    global b1_lim_otimizado, b2_lim_otimizado, b3_lim_otimizado, b4_lim_otimizado, fator_reducao_otimizado
    
    # [b1_lim, b2_lim, b3_lim, b4_lim]
    x0 = [19.6, 15.0, 79.0, 90.0]
    
    MIN_MODULACAO = float(cfg_colunas.get("Min_Modulacao", 0.80))
    MAX_MODULACAO = float(cfg_colunas.get("Max_Modulacao", 1.00))

    bounds = [
        [10.0, 30.0],
        [10.0, 30.0],
        [50.0, 85.0],
        [70.0, 95.0]
    ]

    es = cma.CMAEvolutionStrategy(x0, 2.0, {'bounds': [[b[0] for b in bounds], [b[1] for b in bounds]], 'verbose': -9})
    
    print("\n=================================================================")
    print(f" INICIANDO OTIMIZAÇÃO DE FLUXO DA LINHA | Gerações: 150")
    print("=================================================================")

    try:
        geracao = 0
        while not es.stop() and geracao < 150:
            X = es.ask()
            f_values = [simular_controle_vetorizado(x) for x in X]
            es.tell(X, f_values)
            if geracao % 10 == 0 or geracao == 149:
                best_f = np.min(f_values)
                print(f" Geração {geracao:>3} | Progresso Otimização: {-best_f:,.1f} | σ: {es.sigma:.4f}")
            geracao += 1
    except KeyboardInterrupt:
        print("\nOtimização interrompida. Salvando melhor resultado...\n")

    res = es.result.xbest
    b1_lim_otimizado, b2_lim_otimizado, b3_lim_otimizado, b4_lim_otimizado = res
    fator_reducao_otimizado = MIN_MODULACAO
    
    # Salvar Modelo
    parametros_otimizados = {
        "b1_lim": round(b1_lim_otimizado, 2),
        "b2_lim": round(b2_lim_otimizado, 2),
        "b3_lim": round(b3_lim_otimizado, 2),
    "b4_lim": round(b4_lim_otimizado, 2),
        "fator_reducao": round(fator_reducao_otimizado, 3),
        "velocidade_nominal_calculada": int(VELOCIDADE_NOMINAL_ECH)
    }
    with open("parametros_controle.json", "w", encoding="utf-8") as f:
        json.dump(parametros_otimizados, f, indent=4)
    print("➔ Parâmetros de controle salvos em 'parametros_controle.json'.")

def gerar_codigo_controlador():
    codigo = f"""
# ==========================================================
# CÓDIGO DA FUNÇÃO DO CONTROLADOR DE FLUXO DA MÁQUINA
# (Gerado Automaticamente pelo otimizador_velocidade.py)
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


def calcular_velocidade(b1, b2, b3, b4, velocidade_nominal={int(VELOCIDADE_NOMINAL_ECH)}, min_modulacao={MIN_MODULACAO}, max_modulacao={MAX_MODULACAO}):
    \"\"\"
    Recebe o nivel atual dos 4 pulmoes (%) e retorna o setpoint em CPH.
    Parametros otimizados via CMA-ES em {dt.datetime.now().strftime('%Y-%m-%d')}.
    \"\"\"
    # --- Gatilhos de modulacao otimizados pelo algoritmo ---
    b2_lim = {b2_final:.2f}   # B2 abaixo disto -> iniciar reducao
    b3_lim = {b3_final:.2f}   # B3 acima disto  -> iniciar reducao

    # --- Travas Operacionais (vindas do config_colunas.json) ---
    vel_maxima   = velocidade_nominal * max_modulacao   # Teto absoluto
    vel_reduzida = velocidade_nominal * min_modulacao   # Piso absoluto

    # --- Logica Fuzzy: Avaliacao dos Pulmoes ---
    b2_baixo  = rampa_trapezoidal(b2, -1, 0, b2_lim - 15, b2_lim)
    b2_normal = rampa_trapezoidal(b2, b2_lim - 15, b2_lim, 100, 101)
    b3_normal = rampa_trapezoidal(b3, -1, 0, b3_lim, b3_lim + 15)
    b3_alto   = rampa_trapezoidal(b3, b3_lim, b3_lim + 15, 100, 101)

    # --- Inferencia: pesos e calculo da velocidade ---
    w1 = b2_baixo                       # Entrada vazia -> reduz
    w2 = b3_alto                        # Saida cheia   -> reduz
    w3 = min(b2_normal, b3_normal)      # Ambos OK      -> teto

    num = (w1 * vel_reduzida) + (w2 * vel_reduzida) + (w3 * vel_maxima)
    den = w1 + w2 + w3

    v_base = vel_maxima if den == 0 else num / den

    # --- Garantia do Piso: nunca retorna 0 CPH ---
    return int(max(v_base, vel_reduzida))
"""
    with open("funcao_controle.py", "w", encoding="utf-8") as f:
        f.write(codigo.strip() + "\n")
    print(f"➔ Função autônoma gerada com sucesso em 'funcao_controle.py'.")

gerar_codigo_controlador()

print("\n" + "="*65)
print("     RESULTADO DA OTIMIZAÇÃO DE FLUXO     ")
print("="*65)
print(f"➔ Parâmetros de Controle Otimizados:")
print(f"   ↳ Limite Inferior B1: Abaixo de {b1_final:.1f}%")
print(f"   ↳ Limite Inferior B2: Abaixo de {b2_final:.1f}%")
print(f"   ↳ Limite Superior B3: Acima de {b3_final:.1f}%")
print(f"   ↳ Limite Superior B4: Acima de {b4_final:.1f}%")
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

sim_stops_buffer = int(((v_sug_final == 0.0) & ((b2_hist <= 15.0) | (b3_hist >= 85.0))).sum())
sim_stops_external = int(((v_sug_final == 0.0) & (b2_hist > 15.0) & (b3_hist < 85.0)).sum())

criticos_evitados = int(((b2_hist <= 2.0) | (b3_hist >= 99.0)).sum())
reducao = hist_stops_buffer - sim_stops_buffer

# Cálculo de Eventos de Parada (Transições de Rodando para Zero)
eventos_parada_real = int(np.sum((v_ech_real_hist[:-1] > 0) & (v_ech_real_hist[1:] == 0)))
eventos_parada_sim = int(np.sum((v_sug_final[:-1] > 0) & (v_sug_final[1:] == 0)))
microparadas_evitadas = max(0, eventos_parada_real - eventos_parada_sim)

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
_rel.append(f"    ↳ Iniciar rampa de redução quando o nível cair abaixo de {b2_final:.1f}%")
_rel.append(f" 2. Acúmulo Leve ECH-PZ (Saída):")
_rel.append(f"    ↳ Iniciar rampa de redução quando o nível passar de {b3_final:.1f}%")

_rel.append("")
_rel.append("-"*65)
_rel.append("[LIMITES DE EMERGÊNCIA - PROTEÇÃO CONTRA SOCO MECÂNICO]")
_rel.append(f"➔ Ação: Enchedora → Reduz agressivamente para 0 CPH")
_rel.append(f" 1. Falta Extrema DPL-UIP:")
_rel.append(f"    ↳ Forçar parada quando nível cair abaixo de {b1_final:.1f}%")
_rel.append(f" 2. Engarrafamento Extremo PZ-EPC:")
_rel.append(f"    ↳ Forçar parada quando nível passar de {b4_final:.1f}%")

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
df_cma = pd.DataFrame({
    "Timestamp": df["Timestamp"],
    "Velocidade_Real": v_ech_real_hist,
    "Velocidade_Otimizada": v_sug_final,
    "Buffer_B1": b1_hist,
    "Buffer_B2": b2_hist,
    "Buffer_B3": b3_hist,
    "Buffer_B4": b4_hist
})
df_cma.to_csv("dados_velocidade_otimizada.csv", index=False)
print("\n➔ CSV exportado para 'dados_velocidade_otimizada.csv'.")

pasta_graficos = "graficos_velocidade_otimizada"
if not os.path.exists(pasta_graficos):
    os.makedirs(pasta_graficos)

df_smooth = df_cma.set_index("Timestamp").resample("15Min").mean().reset_index()
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
        if df_dia[col].nunique() > 1:
            ax_buf.plot(df_dia["Timestamp"], df_dia[col],
                        label=labels_buf[col], color=cor, alpha=0.85, linewidth=1.5)

    ax_buf.axhline(b2_final, color="#2980B9", linestyle="--", alpha=0.6, linewidth=1.2,
                   label=f"Gatilho B2 ({b2_final:.0f}%) — entrada")
    ax_buf.axhline(b3_final, color="#E67E22", linestyle="--", alpha=0.6, linewidth=1.2,
                   label=f"Gatilho B3 ({b3_final:.0f}%) — saída")
    ax_buf.set_ylabel("Nível do Buffer (%)", fontsize=11)
    ax_buf.set_ylim(0, 105)
    ax_buf.set_xlabel("Hora", fontsize=10)
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
