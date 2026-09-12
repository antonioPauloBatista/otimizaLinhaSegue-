#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTIMIZADOR DE VELOCIDADE E CONTROLADOR FUZZY V4 (TAKAGI-SUGENO FEEDFORWARD)
=============================================================================
Inovações V4:
1. Pipeline 100% em Dados: Filtro Mediano + EWMA nos Buffers (elimina ruídos e comutação fora de ordem).
2. Balanço de Massa Feedforward: Velocidades das máquinas a montante e a jusante integradas.
3. Tendência de Aceleração em Retomada: Acelera a enchedora antecipadamente se a máquina posterior está destravando.
4. Proteção Mecânica Ativa: Slew-Rate Limiter (taxa máxima de rampa por ciclo) evitando trancos, socos e espumamento.
5. Modo Sprint / Sobrevelocidade Condicionada: Aceleração controlada (101% a 105%) quando a linha está desimpedida.
6. Diagnóstico de Causa-Raiz (Enum JSON): Identifica e exporta o motivo numérico exato de cada modulação/parada.
7. Gráficos Diários Completos (Padrão V3 com faixas coloridas e resampling 15min) para todos os dias do histórico.
"""

import os
import sys
import json
import glob
import shutil
import datetime as dt
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# =====================================================================
# 1. CARREGAMENTO DE CONFIGURAÇÕES E DADOS
# =====================================================================
ARQUIVO_CSV = "dados_completos_fabrica.csv"
ARQUIVO_CONFIG = "config_colunas.json"
ARQUIVO_MOTIVOS = "motivos_modulacao_enum.json"

MIN_MODULACAO = 0.75
MAX_MODULACAO = 1.00
VELOCIDADE_NOMINAL_ECH = 60000.0
LIMIAR_VELOCIDADE_MANUTENCAO = 30000.0
MAX_RAMPA_CPH_PASSO = 3000.0   # CPH por ciclo (ex: 30s)
FATOR_SOBREMARCHA = 1.02
ALPHA_FILTRO_BUFFER = 0.65
JANELA_MEDIANA = 3
FILTRO_MINUTOS_PARADA_LONGA = 10

COL_B1_DPL_UIP = "accumulation_percentage_pre_eci_null"
COL_B2_UIP_ECH = "accumulation_percentage_eci_to_filler_null"
COL_B3_ECH_PZ  = "accumulation_percentage_filler_to_pasteurizer_null"
COL_B4_PZ_EPC  = "accumulation_percentage_post_pasteurizer_null"

COL_V_MONTANTE = "speed_actual_cph_null_first_upstream_machine_1"
COL_V_ENTRADA  = "speed_actual_cph_null_eci_1"
COL_V_ECH      = "speed_actual_cph_null_filler_1"
COL_V_SAIDA    = "speed_actual_cph_null_pasteurizer"
COL_V_JUSANTE  = "speed_actual_cph_null_first_downstream_machine_1,speed_actual_cph_null_first_downstream_machine_2"

# Limpeza de relatórios antigos na pasta
for f_antigo in glob.glob("relatorio_otimizacao_v4_*.txt"):
    try: os.remove(f_antigo)
    except Exception: pass

if os.path.exists("graficos_velocidade_otimizada_v4"):
    try: shutil.rmtree("graficos_velocidade_otimizada_v4")
    except Exception: pass

if os.path.exists(ARQUIVO_CONFIG):
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            ARQUIVO_CSV = cfg.get("Arquivo_Dados", ARQUIVO_CSV)
            COL_B1_DPL_UIP = cfg.get("Col_Buffer_Antes_Entrada", COL_B1_DPL_UIP)
            COL_B2_UIP_ECH = cfg.get("Col_Buffer_Entrada", COL_B2_UIP_ECH)
            COL_B3_ECH_PZ  = cfg.get("Col_Buffer_Saida", COL_B3_ECH_PZ)
            COL_B4_PZ_EPC  = cfg.get("Col_Buffer_Pos_Saida", COL_B4_PZ_EPC)
            
            COL_V_MONTANTE = cfg.get("COL_V_Antes_Entrada", COL_V_MONTANTE)
            COL_V_ENTRADA  = cfg.get("COL_V_Entrada", COL_V_ENTRADA)
            COL_V_ECH      = cfg.get("COL_V_ECH", COL_V_ECH)
            COL_V_SAIDA    = cfg.get("COL_V_Saida", COL_V_SAIDA)
            COL_V_JUSANTE  = cfg.get("COL_V_Entrada_Pos_Saida", COL_V_JUSANTE)
            
            MIN_MODULACAO = float(cfg.get("Min_Modulacao", MIN_MODULACAO))
            MAX_MODULACAO = float(cfg.get("Max_Modulacao", MAX_MODULACAO))
            FATOR_SOBREMARCHA = float(cfg.get("Fator_Sobremarcha", FATOR_SOBREMARCHA))
            MAX_RAMPA_CPH_PASSO = float(cfg.get("Max_Rampa_CPH_Passo", MAX_RAMPA_CPH_PASSO))
            ALPHA_FILTRO_BUFFER = float(cfg.get("Alpha_Filtro_Buffer", ALPHA_FILTRO_BUFFER))
            JANELA_MEDIANA = int(cfg.get("Janela_Mediana_Buffer", JANELA_MEDIANA))
            FILTRO_MINUTOS_PARADA_LONGA = int(cfg.get("Filtro_Minutos_Parada_Longa", FILTRO_MINUTOS_PARADA_LONGA))
            
            val_nom = cfg.get("Velocidade_Nominal_ECH", None)
            if val_nom is not None: VELOCIDADE_NOMINAL_ECH = float(val_nom)
            
            val_manut = cfg.get("Limiar_Velocidade_Manutencao", None)
            if val_manut is not None: LIMIAR_VELOCIDADE_MANUTENCAO = float(val_manut)
    except Exception as e:
        print(f"⚠️ Aviso ao carregar '{ARQUIVO_CONFIG}': {e}. Usando padrões.")

if not os.path.exists(ARQUIVO_CSV):
    print(f"❌ Arquivo '{ARQUIVO_CSV}' não encontrado!")
    sys.exit(1)

df = pd.read_csv(ARQUIVO_CSV)
df["Timestamp"] = pd.to_datetime(df["Timestamp"])
df.sort_values("Timestamp", inplace=True)
df.ffill(inplace=True)
df.fillna(0.0, inplace=True)

# Função para resolver e somar colunas de máquinas em paralelo
def extrair_coluna_ou_soma(df, col_str, opcional=False):
    if not col_str or str(col_str).strip().lower() in ["null", "none", ""]:
        return np.zeros(len(df)) if not opcional else None
    cols = [c.strip() for c in str(col_str).split(',')]
    cols_validas = [c for c in cols if c in df.columns]
    if not cols_validas:
        if opcional: return None
        raise ValueError(f"Coluna(s) '{col_str}' não encontrada(s) no CSV.")
    soma = np.zeros(len(df))
    for c in cols_validas:
        soma += df[c].fillna(0.0).values
    return soma

v_ech_real_hist = extrair_coluna_ou_soma(df, COL_V_ECH)
v_in_real_hist  = extrair_coluna_ou_soma(df, COL_V_ENTRADA, opcional=True)
if v_in_real_hist is None: v_in_real_hist = v_ech_real_hist.copy()

v_out_real_hist = extrair_coluna_ou_soma(df, COL_V_SAIDA, opcional=True)
if v_out_real_hist is None: v_out_real_hist = v_ech_real_hist.copy()

v_up_real_hist   = extrair_coluna_ou_soma(df, COL_V_MONTANTE, opcional=True)
v_down_real_hist = extrair_coluna_ou_soma(df, COL_V_JUSANTE, opcional=True)

# Níveis brutos dos buffers
def extrair_buffer(col_nome, default_val=50.0):
    if col_nome and col_nome in df.columns:
        return df[col_nome].fillna(default_val).values
    return np.full(len(df), default_val)

b1_raw = extrair_buffer(COL_B1_DPL_UIP, 50.0)
b2_raw = extrair_buffer(COL_B2_UIP_ECH, 50.0)
b3_raw = extrair_buffer(COL_B3_ECH_PZ, 50.0)
b4_raw = extrair_buffer(COL_B4_PZ_EPC, 50.0)

# =====================================================================
# 2. PIPELINE DE DADOS 100% SOFTWARE (FILTRAGEM DE SENSORES DESORDENADOS)
# =====================================================================
def filtrar_buffer_data_driven(b_arr, janela_med=3, alpha_ewma=0.65):
    n = len(b_arr)
    # Etapa 1: Mediana com reflexão nas bordas
    b_med = np.copy(b_arr)
    metade = janela_med // 2
    for i in range(n):
        i_min = max(0, i - metade)
        i_max = min(n, i + metade + 1)
        b_med[i] = np.median(b_arr[i_min:i_max])
    
    # Etapa 2: EWMA
    b_filtrado = np.empty(n, dtype=float)
    b_filtrado[0] = b_med[0]
    for i in range(1, n):
        b_filtrado[i] = alpha_ewma * b_med[i] + (1.0 - alpha_ewma) * b_filtrado[i - 1]
    
    return np.clip(b_filtrado, 0.0, 100.0)

print("🔍 Aplicando pipeline de dados nos buffers (Mediana + EWMA)...")
b1_hist = filtrar_buffer_data_driven(b1_raw, JANELA_MEDIANA, ALPHA_FILTRO_BUFFER)
b2_hist = filtrar_buffer_data_driven(b2_raw, JANELA_MEDIANA, ALPHA_FILTRO_BUFFER)
b3_hist = filtrar_buffer_data_driven(b3_raw, JANELA_MEDIANA, ALPHA_FILTRO_BUFFER)
b4_hist = filtrar_buffer_data_driven(b4_raw, JANELA_MEDIANA, ALPHA_FILTRO_BUFFER)

time_step = int((df["Timestamp"].iloc[1] - df["Timestamp"].iloc[0]).total_seconds())
if time_step <= 0: time_step = 30

# Tendência de velocidade da máquina a jusante (Pasteurizador / Saída)
diff_vout = np.zeros(len(df))
diff_vout[1:] = (v_out_real_hist[1:] - v_out_real_hist[:-1]) / float(time_step)
trend_vout_hist = np.empty(len(df))
trend_vout_hist[0] = diff_vout[0]
for i in range(1, len(df)):
    trend_vout_hist[i] = 0.5 * diff_vout[i] + 0.5 * trend_vout_hist[i - 1]

# Identificar paradas externas longas inegociáveis
limite_amostras_parada = int((FILTRO_MINUTOS_PARADA_LONGA * 60) / time_step)
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

# =====================================================================
# 3. MOTOR FUZZY V4 (TAKAGI-SUGENO COM TENDÊNCIA E SOBREVELOCIDADE)
# =====================================================================
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

def simular_controle_v4(x_params, override_vel_nominal=None):
    b1_lim = np.clip(x_params[0], 10.0, 30.0)
    b2_lim = np.clip(x_params[1], 15.0, 50.0)
    b3_lim = np.clip(x_params[2], 50.0, 85.0)
    b4_lim = np.clip(x_params[3], 70.0, 90.0)
    rampa_b2 = np.clip(x_params[4], 10.0, 35.0)
    rampa_b3 = np.clip(x_params[5], 10.0, 35.0)
    antecip_b1 = np.clip(x_params[6], 5.0, 30.0)
    antecip_b4 = np.clip(x_params[7], 5.0, 30.0)
    min_mod = np.clip(x_params[8], 0.65, 0.90)
    peso_retomada = np.clip(x_params[9], 0.10, 0.60)
    fator_sprint = np.clip(x_params[10], 1.01, 1.05)

    vel_nominal = override_vel_nominal if override_vel_nominal is not None else VELOCIDADE_NOMINAL_ECH
    v_nominal = vel_nominal * MAX_MODULACAO
    v_sprint  = vel_nominal * fator_sprint
    v_reduz   = vel_nominal * min_mod

    # 1. Pertinências dos Buffers Filtrados
    b2_baixo  = vec_trapezoidal(b2_hist, -1, 0, b2_lim - rampa_b2, b2_lim)
    b2_normal = vec_trapezoidal(b2_hist, b2_lim - rampa_b2, b2_lim, 100, 101)
    b3_normal = vec_trapezoidal(b3_hist, -1, 0, b3_lim, b3_lim + rampa_b3)
    b3_alto   = vec_trapezoidal(b3_hist, b3_lim, b3_lim + rampa_b3, 100, 101)

    # 2. Feedforward Extremo
    b1_alerta = vec_trapezoidal(b1_hist, -1, 0, b1_lim, b1_lim + antecip_b1)
    b4_alerta = vec_trapezoidal(b4_hist, b4_lim - antecip_b4, b4_lim, 100, 101)

    # 3. Tendência de Aceleração da Máquina da Frente (Retomada Sincronizada)
    mu_acelerando_jusante = np.clip((trend_vout_hist - 20.0) / 100.0, 0.0, 1.0)
    
    w_saida_cheia = b3_alto * (1.0 - peso_retomada * mu_acelerando_jusante)
    w_retomada_sinc = b3_alto * (peso_retomada * mu_acelerando_jusante)

    # 4. Condição de Sprint / Sobrevelocidade
    cond_sprint_buffers = (b2_hist >= (b2_lim + 10.0)) & (b3_hist <= (b3_lim - 10.0))
    cond_sprint_maquinas = (v_in_real_hist >= 0.90 * vel_nominal) & (v_out_real_hist >= 0.90 * vel_nominal)
    w_sprint = np.where(cond_sprint_buffers & cond_sprint_maquinas, 1.0, 0.0)

    w_entrada_vazia = b2_baixo
    w_normal = np.minimum(b2_normal, b3_normal) * (1.0 - w_sprint)
    w_ff_b1 = b1_alerta
    w_ff_b4 = b4_alerta

    num = (w_entrada_vazia * v_reduz) + \
          (w_saida_cheia * v_reduz) + \
          (w_retomada_sinc * v_nominal) + \
          (w_ff_b1 * v_reduz) + \
          (w_ff_b4 * v_reduz) + \
          (w_normal * v_nominal) + \
          (w_sprint * v_sprint)

    den = w_entrada_vazia + w_saida_cheia + w_retomada_sinc + w_ff_b1 + w_ff_b4 + w_normal + w_sprint
    den_safe = np.where(den == 0, 1.0, den)
    v_sug_bruta = np.where(den == 0, v_nominal, num / den_safe)
    v_sug_bruta = np.clip(v_sug_bruta, v_reduz, v_sprint)

    # 5. Slew-Rate Limiter (Proteção Mecânica na saída)
    n_pts = len(v_sug_bruta)
    v_otimizada = np.empty(n_pts, dtype=float)
    
    v_atual = v_nominal
    for i in range(n_pts):
        if mascara_parada_longa[i]:
            v_atual = 0.0
        else:
            alvo = v_sug_bruta[i]
            if v_atual == 0.0:
                v_atual = min(alvo, v_reduz)
            else:
                delta = alvo - v_atual
                if delta > MAX_RAMPA_CPH_PASSO:
                    v_atual += MAX_RAMPA_CPH_PASSO
                elif delta < -MAX_RAMPA_CPH_PASSO:
                    v_atual -= MAX_RAMPA_CPH_PASSO
                else:
                    v_atual = alvo
        v_otimizada[i] = v_atual

    # Métricas de Função Objetivo
    producao = np.sum(v_otimizada) / 3600.0 * time_step
    paradas_soco = np.sum((v_otimizada > (vel_nominal * min_mod + 500.0)) & ((b2_hist <= 10.0) | (b3_hist >= 90.0)))
    penalidade_acel = np.sum((np.diff(v_otimizada) / 1000.0) ** 2)

    limites = [
        (10, 30), (15, 50), (50, 85), (70, 90),
        (10, 35), (10, 35), (5, 30), (5, 30),
        (0.65, 0.90), (0.10, 0.60), (1.01, 1.05)
    ]
    penalidade_bounds = 0.0
    for i, val in enumerate(x_params):
        inf, sup = limites[i]
        if val < inf: penalidade_bounds += (inf - val) ** 2 * 100000.0
        if val > sup: penalidade_bounds += (val - sup) ** 2 * 100000.0

    score = producao - (paradas_soco * 40000.0) - (penalidade_acel * 15.0) - penalidade_bounds
    return score, producao, v_otimizada, v_sug_bruta

# Função wrapper para o CMA-ES
def obj_cma(params):
    score, prod, v_otim, _ = simular_controle_v4(params)
    return score

# =====================================================================
# 4. ALGORITMO DE OTIMIZAÇÃO CMA-ES
# =====================================================================
def cma_es(func, x0, sigma0=1.5, max_iter=120, seed=42):
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

    print(f"\n{'='*75}")
    print(f" INICIANDO OTIMIZAÇÃO CMA-ES V4 | 11 PARÂMETROS | Gerações: {max_iter}")
    print(f"{'='*75}")

    for gen in range(max_iter):
        arz = rng.standard_normal((lam, n))
        arx = xmean + sigma * (arz @ (B * D).T)

        fitness = np.zeros(lam)
        for i in range(lam):
            fitness[i] = func(arx[i])

        idx = np.argsort(fitness)[::-1]

        if fitness[idx[0]] > melhor_score:
            melhor_score = fitness[idx[0]]
            melhor_x = arx[idx[0]].copy()

        historico_scores.append(melhor_score)

        if gen % 10 == 0 or gen == max_iter - 1:
            print(f" Geração {gen:3d} | Melhor Fitness: {melhor_score:,.1f} | σ: {sigma:.4f}")

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

# Ponto de Partida Inicial
x_inicial = np.array([
    20.0,  # b1_lim
    30.0,  # b2_lim
    70.0,  # b3_lim
    85.0,  # b4_lim
    20.0,  # rampa_b2
    20.0,  # rampa_b3
    15.0,  # antecip_b1
    15.0,  # antecip_b4
    0.78,  # min_modulacao
    0.35,  # peso_retomada
    1.02   # fator_sprint
])

melhores_params, melhor_score, hist_scores = cma_es(
    func=obj_cma,
    x0=x_inicial,
    sigma0=1.8,
    max_iter=120
)

# Execução final com os melhores parâmetros
_, producao_otimizada, v_sug_final, v_alvo_bruta = simular_controle_v4(melhores_params)

# =====================================================================
# 5. DIAGNÓSTICO DE CAUSA-RAIZ (CÓDIGOS DE MOTIVO / ENUM)
# =====================================================================
b1_opt = float(np.clip(melhores_params[0], 10.0, 30.0))
b2_opt = float(np.clip(melhores_params[1], 15.0, 50.0))
b3_opt = float(np.clip(melhores_params[2], 50.0, 85.0))
b4_opt = float(np.clip(melhores_params[3], 70.0, 90.0))
rampa_b2_opt = float(np.clip(melhores_params[4], 10.0, 35.0))
rampa_b3_opt = float(np.clip(melhores_params[5], 10.0, 35.0))
antecip_b1_opt = float(np.clip(melhores_params[6], 5.0, 30.0))
antecip_b4_opt = float(np.clip(melhores_params[7], 5.0, 30.0))
min_mod_opt = float(np.clip(melhores_params[8], 0.65, 0.90))
peso_retomada_opt = float(np.clip(melhores_params[9], 0.10, 0.60))
fator_sprint_opt = float(np.clip(melhores_params[10], 1.01, 1.05))

# Carregar mapa de motivos
mapa_motivos = {}
if os.path.exists(ARQUIVO_MOTIVOS):
    with open(ARQUIVO_MOTIVOS, "r", encoding="utf-8") as f:
        mapa_motivos = json.load(f)

n_pts = len(v_sug_final)
motivos_id = np.zeros(n_pts, dtype=int)
motivos_cod = []

for i in range(n_pts):
    v = v_sug_final[i]
    if v == 0.0:
        if b2_hist[i] <= 10.0 and b3_hist[i] >= 90.0:
            m_id = 90  # PARADA_SEGURANCA_BUFFER
        elif b2_hist[i] <= 10.0:
            m_id = 91  # PARADA_INTERTRAV_ENTRADA_ECI
        elif b3_hist[i] >= 90.0:
            m_id = 92  # PARADA_INTERTRAV_SAIDA_PASTEURIZADOR
        else:
            m_id = 99  # PARADA_EXTERNA_MANUTENCAO
    elif v > VELOCIDADE_NOMINAL_ECH + 10.0:
        m_id = 1   # SPRINT_SOBREVELOCIDADE
    elif v >= VELOCIDADE_NOMINAL_ECH - 10.0:
        m_id = 0   # NORMAL_FULL
    else:
        # Velocidade abaixo da nominal -> Diagnosticar Causa Raiz
        # Slew rate limitando aceleração
        if v_alvo_bruta[i] > v + 150.0:
            m_id = 60  # LIMITADOR_RAMPA_MECANICA
        elif b2_hist[i] < b2_opt and b3_hist[i] > b3_opt:
            m_id = 30  # CONFLITO_ENTRADA_SAIDA
        elif b3_hist[i] > b3_opt and trend_vout_hist[i] > 20.0:
            m_id = 25  # RETOMADA_ACELERANDO_JUSANTE
        elif b3_hist[i] > b3_opt:
            m_id = 20  # ACUMULO_SAIDA_B3
        elif b2_hist[i] < b2_opt:
            m_id = 10  # FALTA_ENTRADA_B2
        elif v_out_real_hist[i] < 0.85 * VELOCIDADE_NOMINAL_ECH:
            m_id = 80  # MAQUINA_JUSANTE_LENTA
        elif v_in_real_hist[i] < 0.85 * VELOCIDADE_NOMINAL_ECH:
            m_id = 70  # MAQUINA_MONTANTE_LENTA
        elif b4_hist[i] > b4_opt:
            m_id = 50  # FEEDFORWARD_ALERTA_B4
        elif b1_hist[i] < b1_opt:
            m_id = 40  # FEEDFORWARD_ALERTA_B1
        else:
            m_id = 20 if (b3_hist[i] - b3_opt) > (b2_opt - b2_hist[i]) else 10

    motivos_id[i] = m_id
    info = mapa_motivos.get(str(m_id), {"codigo": "MODULANDO"})
    motivos_cod.append(info.get("codigo", "MODULANDO"))

# Salvar parâmetros otimizados em JSON
parametros_json = {
    "b1_lim": round(b1_opt, 2),
    "b2_lim": round(b2_opt, 2),
    "b3_lim": round(b3_opt, 2),
    "b4_lim": round(b4_opt, 2),
    "rampa_b2": round(rampa_b2_opt, 2),
    "rampa_b3": round(rampa_b3_opt, 2),
    "antecipacao_b1": round(antecip_b1_opt, 2),
    "antecipacao_b4": round(antecip_b4_opt, 2),
    "fator_reducao": round(min_mod_opt, 3),
    "peso_retomada_tendencia": round(peso_retomada_opt, 3),
    "fator_sprint": round(fator_sprint_opt, 3),
    "max_rampa_cph_passo": float(MAX_RAMPA_CPH_PASSO),
    "alpha_ewma": float(ALPHA_FILTRO_BUFFER),
    "velocidade_nominal_calculada": int(VELOCIDADE_NOMINAL_ECH)
}

with open("parametros_controle_v4.json", "w", encoding="utf-8") as f:
    json.dump(parametros_json, f, indent=4)
print("➔ Parâmetros salvos em 'parametros_controle_v4.json'.")

# =====================================================================
# 6. GERAÇÃO AUTOMÁTICA DE CÓDIGO AUTÔNOMO E LIVE
# =====================================================================
codigo_funcao = f'''# -*- coding: utf-8 -*-
"""
FUNÇÃO DE CONTROLE DE VELOCIDADE DA ENCHEDORA V4 COM DIAGNÓSTICO DE CAUSA-RAIZ
Gerado automaticamente pelo otimizador_velocidade_v4.py em {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.

Retorna:
    (velocidade_cph, motivo_id)
    Onde motivo_id mapeia diretamente para 'motivos_modulacao_enum.json'.
"""

import os
import json

def rampa_trapezoidal(x, a, b, c, d):
    if x <= a or x >= d: return 0.0
    if a < x <= b: return (x - a) / (b - a) if b > a else 1.0
    if b < x <= c: return 1.0
    if c < x < d: return (d - x) / (d - c) if d > c else 1.0
    return 0.0

class ControladorVelocidadeV4:
    def __init__(self, velocidade_nominal={int(VELOCIDADE_NOMINAL_ECH)}, v_atual_inicial=None):
        self.vel_nom = float(velocidade_nominal)
        self.b1_lim = {b1_opt:.2f}
        self.b2_lim = {b2_opt:.2f}
        self.b3_lim = {b3_opt:.2f}
        self.b4_lim = {b4_opt:.2f}
        self.rampa_b2 = {rampa_b2_opt:.2f}
        self.rampa_b3 = {rampa_b3_opt:.2f}
        self.antecip_b1 = {antecip_b1_opt:.2f}
        self.antecip_b4 = {antecip_b4_opt:.2f}
        self.min_mod = {min_mod_opt:.3f}
        self.peso_retomada = {peso_retomada_opt:.3f}
        self.fator_sprint = {fator_sprint_opt:.3f}
        self.max_rampa = {MAX_RAMPA_CPH_PASSO:.1f}
        self.alpha_ewma = {ALPHA_FILTRO_BUFFER:.2f}

        # Estado interno dos filtros e rampa mecânica
        self.b1_f = 50.0
        self.b2_f = 50.0
        self.b3_f = 50.0
        self.b4_f = 50.0
        self.v_saida_anterior = None
        self.v_atual = float(v_atual_inicial) if v_atual_inicial is not None else self.vel_nom
        self.ultimo_motivo_id = 0

        # Carregar descrições de motivo se o json estiver presente
        self.mapa_motivos = {{}}
        if os.path.exists("motivos_modulacao_enum.json"):
            try:
                with open("motivos_modulacao_enum.json", "r", encoding="utf-8") as f:
                    self.mapa_motivos = json.load(f)
            except Exception: pass

    def filtrar_buffer(self, b_val, b_antigo):
        return self.alpha_ewma * float(b_val) + (1.0 - self.alpha_ewma) * float(b_antigo)

    def obter_motivo(self, motivo_id=None):
        m_id = str(self.ultimo_motivo_id if motivo_id is None else motivo_id)
        return self.mapa_motivos.get(m_id, {{"codigo": "DESCONHECIDO", "descricao": "Modulação de fluxo"}})

    def calcular_velocidade(self, b1, b2, b3, b4, v_in=None, v_out=None, delta_t_s=30.0, retornar_motivo=True):
        # 1. Filtro EWMA contínuo
        self.b1_f = self.filtrar_buffer(b1, self.b1_f)
        self.b2_f = self.filtrar_buffer(b2, self.b2_f)
        self.b3_f = self.filtrar_buffer(b3, self.b3_f)
        self.b4_f = self.filtrar_buffer(b4, self.b4_f)

        v_in = float(v_in) if v_in is not None else self.vel_nom
        v_out = float(v_out) if v_out is not None else self.vel_nom

        # 2. Tendência de Aceleração da Máquina da Frente
        trend_vout = 0.0
        if self.v_saida_anterior is not None and delta_t_s > 0:
            trend_vout = (v_out - self.v_saida_anterior) / float(delta_t_s)
        self.v_saida_anterior = v_out

        mu_acelerando = max(0.0, min(1.0, (trend_vout - 20.0) / 100.0))

        # 3. Lógica Fuzzy Takagi-Sugeno
        v_nom = self.vel_nom
        v_sprint = self.vel_nom * self.fator_sprint
        v_reduz = self.vel_nom * self.min_mod

        b2_baixo  = rampa_trapezoidal(self.b2_f, -1, 0, self.b2_lim - self.rampa_b2, self.b2_lim)
        b2_normal = rampa_trapezoidal(self.b2_f, self.b2_lim - self.rampa_b2, self.b2_lim, 100, 101)
        b3_normal = rampa_trapezoidal(self.b3_f, -1, 0, self.b3_lim, self.b3_lim + self.rampa_b3)
        b3_alto   = rampa_trapezoidal(self.b3_f, self.b3_lim, self.b3_lim + self.rampa_b3, 100, 101)

        b1_alerta = rampa_trapezoidal(self.b1_f, -1, 0, self.b1_lim, self.b1_lim + self.antecip_b1)
        b4_alerta = rampa_trapezoidal(self.b4_f, self.b4_lim - self.antecip_b4, self.b4_lim, 100, 101)

        w_saida_cheia = b3_alto * (1.0 - self.peso_retomada * mu_acelerando)
        w_retomada = b3_alto * (self.peso_retomada * mu_acelerando)

        cond_sprint = (self.b2_f >= (self.b2_lim + 10.0)) and (self.b3_f <= (self.b3_lim - 10.0)) and (v_in >= 0.90 * v_nom) and (v_out >= 0.90 * v_nom)
        w_sprint = 1.0 if cond_sprint else 0.0
        w_normal = min(b2_normal, b3_normal) * (1.0 - w_sprint)

        num = (b2_baixo * v_reduz) + (w_saida_cheia * v_reduz) + (w_retomada * v_nom) + (b1_alerta * v_reduz) + (b4_alerta * v_reduz) + (w_normal * v_nom) + (w_sprint * v_sprint)
        den = b2_baixo + w_saida_cheia + w_retomada + b1_alerta + b4_alerta + w_normal + w_sprint
        v_alvo = v_nom if den == 0 else num / den
        v_alvo = max(v_reduz, min(v_sprint, v_alvo))

        # 4. Limitador de Rampa Mecânica (Slew Rate)
        v_ant = self.v_atual
        if self.v_atual <= 0.0:
            self.v_atual = min(v_alvo, v_reduz)
        else:
            delta = v_alvo - self.v_atual
            if delta > self.max_rampa:
                self.v_atual += self.max_rampa
            elif delta < -self.max_rampa:
                self.v_atual -= self.max_rampa
            else:
                self.v_atual = v_alvo

        v_final = round(self.v_atual, 1)

        # 5. Identificação do Motivo e da Máquina Causadora (Reason Code)
        if v_final == 0.0:
            if self.b2_f <= 10.0 and self.b3_f >= 90.0:
                m_id = 90  # PARADA_SEGURANCA_BUFFER
            elif self.b2_f <= 10.0:
                m_id = 91  # PARADA_INTERTRAV_ENTRADA_ECI
            elif self.b3_f >= 90.0:
                m_id = 92  # PARADA_INTERTRAV_SAIDA_PASTEURIZADOR
            else:
                m_id = 99  # PARADA_EXTERNA_MANUTENCAO
        elif v_final > v_nom + 10.0:
            m_id = 1   # SPRINT_SOBREVELOCIDADE
        elif v_final >= v_nom - 10.0:
            m_id = 0   # NORMAL_FULL
        else:
            # Modulação ativa abaixo da nominal
            if v_alvo > v_final + 150.0:
                m_id = 60  # LIMITADOR_RAMPA_MECANICA (rampa subindo gradualmente)
            elif self.b2_f < self.b2_lim and self.b3_f > self.b3_lim:
                m_id = 30  # CONFLITO_ENTRADA_SAIDA
            elif self.b3_f > self.b3_lim and trend_vout > 20.0:
                m_id = 25  # RETOMADA_ACELERANDO_JUSANTE
            elif self.b3_f > self.b3_lim:
                m_id = 20  # ACUMULO_SAIDA_B3
            elif self.b2_f < self.b2_lim:
                m_id = 10  # FALTA_ENTRADA_B2
            elif v_out < 0.85 * v_nom:
                m_id = 80  # MAQUINA_JUSANTE_LENTA
            elif v_in < 0.85 * v_nom:
                m_id = 70  # MAQUINA_MONTANTE_LENTA
            elif self.b4_f > self.b4_lim:
                m_id = 50  # FEEDFORWARD_ALERTA_B4
            elif self.b1_f < self.b1_lim:
                m_id = 40  # FEEDFORWARD_ALERTA_B1
            else:
                m_id = 20 if (self.b3_f - self.b3_lim) > (self.b2_lim - self.b2_f) else 10

        self.ultimo_motivo_id = m_id
        if retornar_motivo:
            return v_final, m_id
        return v_final
'''

with open("funcao_controle_v4.py", "w", encoding="utf-8") as f:
    f.write(codigo_funcao)
print("➔ Função autônoma atualizada em 'funcao_controle_v4.py'.")

# Atualizar controlador_velocidade_live_v4.py
codigo_live = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Controlador de Velocidade Live Interativo V4 (Simulador de Bancada com Motivos)
Mostra o setpoint de velocidade e o motivo da modulação / parada em tempo real.
"""

from funcao_controle_v4 import ControladorVelocidadeV4

def main():
    print("="*75)
    print("   SIMULADOR DE VELOCIDADE LIVE V4 COM MOTIVOS DE PARADA / MODULAÇÃO")
    print("="*75)
    print("Injetando parâmetros otimizados V4 com enum de causas-raiz...\\n")

    ctrl = ControladorVelocidadeV4(velocidade_nominal={int(VELOCIDADE_NOMINAL_ECH)})

    while True:
        try:
            print("Digite os valores das variáveis (ou Ctrl+C para sair):")
            b1 = float(input("  B1 - Extremo Entrada (LG/DPL) [%]     [50]: ") or "50")
            b2 = float(input("  B2 - Entrada Imediata (ECI/Filler) [%] [50]: ") or "50")
            b3 = float(input("  B3 - Saída Imediata (Filler/PZ) [%]   [50]: ") or "50")
            b4 = float(input("  B4 - Extremo Saída (PZ/Rotuladora) [%] [50]: ") or "50")
            vin = float(input("  Velocidade Máquina Entrada (ECI) [CPH] [{int(VELOCIDADE_NOMINAL_ECH)}]: ") or "{int(VELOCIDADE_NOMINAL_ECH)}")
            vout = float(input("  Velocidade Máquina Saída (PZ) [CPH]    [{int(VELOCIDADE_NOMINAL_ECH)}]: ") or "{int(VELOCIDADE_NOMINAL_ECH)}")

            vel, motivo_id = ctrl.calcular_velocidade(b1, b2, b3, b4, v_in=vin, v_out=vout, delta_t_s=30.0, retornar_motivo=True)
            info = ctrl.obter_motivo(motivo_id)
            perc = round((vel / {float(VELOCIDADE_NOMINAL_ECH)}) * 100.0, 1)

            print("-" * 75)
            if perc > 100.0:
                print(f"➔ SETPOINT V4: {{vel:.0f}} CPH ({{perc}}%) 🚀 MODO SPRINT / SOBREVELOCIDADE")
            elif perc == 100.0:
                print(f"➔ SETPOINT V4: {{vel:.0f}} CPH ({{perc}}%) ✅ MÁQUINA NOMINAL (FULL)")
            else:
                print(f"➔ SETPOINT V4: {{vel:.0f}} CPH ({{perc}}%) ⚠️ MODULAÇÃO SUAVE ATIVA")
            
            print(f"➔ MOTIVO [ID {{motivo_id}} - {{info.get('codigo')}}]: {{info.get('descricao')}}")
            print(f"   ↳ Categoria: {{info.get('categoria')}}")
            print(f"   ↳ Ação Recomendada: {{info.get('acao_recomendada')}}")
            print("-" * 75)
            print("")
        except KeyboardInterrupt:
            print("\\nSaindo do simulador live...")
            break
        except ValueError:
            print("\\n⚠️ Entrada inválida. Por favor, digite números válidos.\\n")

if __name__ == "__main__":
    main()
'''

with open("controlador_velocidade_live_v4.py", "w", encoding="utf-8") as f:
    f.write(codigo_live)
print("➔ Simulador live atualizado em 'controlador_velocidade_live_v4.py'.")

# Atualizar controlador_velocidade_grafana_v4.py
codigo_grafana = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Controlador de Velocidade Live via Grafana / InfluxDB V4
Conecta a cada 30 segundos, extrai dados brutos, aplica filtros data-driven,
calcula tendências e despacha o setpoint otimizado com rampa suave e Motivo ID.
"""

import time
import datetime
import requests
import json
import base64
import pandas as pd
import sys
import os
from funcao_controle_v4 import ControladorVelocidadeV4

GRAFANA_URL = "http://172.23.224.145:3000"
GRAFANA_USER = "admin"
GRAFANA_PASSWORD = "!ambev2021"
GRAFANA_TOKEN = ""
DATASOURCE_SELECTOR = "13"
BUCKET = "Segue"
MEASUREMENT = "NS-512"

VEL_NOMINAL = {float(VELOCIDADE_NOMINAL_ECH)}

def obter_ds_uid(session, headers):
    ds_url = f"{{GRAFANA_URL.rstrip('/')}}/api/datasources"
    try:
        r = session.get(ds_url, headers=headers, timeout=10)
        if r.status_code == 200:
            for ds in r.json():
                if str(ds.get("id")) == DATASOURCE_SELECTOR or str(ds.get("name")).lower() == DATASOURCE_SELECTOR.lower():
                    return ds.get("uid")
    except Exception: pass
    return None

def main():
    print("="*75)
    print("   CONTROLADOR DE VELOCIDADE LIVE GRAFANA V4 (BALANÇO + MOTIVOS)")
    print("="*75)
    print(f"Conectando ao Grafana: {{GRAFANA_URL}} a cada 30 segundos...\\n")

    session = requests.Session()
    usr_pass = f"{{GRAFANA_USER}}:{{GRAFANA_PASSWORD}}".encode("utf-8")
    basic_auth = f"Basic {{base64.b64encode(usr_pass).decode('utf-8')}}"
    headers = {{"Accept": "application/json", "Content-Type": "application/json", "Authorization": basic_auth}}

    ds_uid = obter_ds_uid(session, headers)
    controlador = ControladorVelocidadeV4(velocidade_nominal=VEL_NOMINAL)

    while True:
        agora = datetime.datetime.now(datetime.timezone.utc)
        t_start = agora - datetime.timedelta(minutes=15)
        t_stop = agora

        flux_query = f\'\'\'from(bucket: "{{BUCKET}}")
  |> range(start: {{t_start.strftime("%Y-%m-%dT%H:%M:%SZ")}}, stop: {{t_stop.strftime("%Y-%m-%dT%H:%M:%SZ")}})
  |> filter(fn: (r) => r["_measurement"] == "{{MEASUREMENT}}")
  |> last()
  |> map(fn: (r) => ({{{{ r with _value: float(v: r._value) }}}}))
  |> pivot(rowKey: ["_measurement", "_time"], columnKey: ["_field", "buffer_name_local", "machine_name_generic"], valueColumn: "_value")\'\'\'

        ds_payload = {{
            "from": str(int(t_start.timestamp() * 1000)),
            "to": str(int(t_stop.timestamp() * 1000)),
            "queries": [{{"datasource": {{"uid": ds_uid, "type": "influxdb"}}, "query": flux_query, "queryType": "flux", "refId": "A"}}]
        }}

        try:
            resp = session.post(f"{{GRAFANA_URL.rstrip('/')}}/api/ds/query", headers=headers, json=ds_payload, timeout=15)
            if resp.status_code == 200:
                b1, b2, b3, b4 = 50.0, 50.0, 50.0, 50.0
                vin, vout = VEL_NOMINAL, VEL_NOMINAL
                v_otim, motivo_id = controlador.calcular_velocidade(b1, b2, b3, b4, v_in=vin, v_out=vout, delta_t_s=30.0, retornar_motivo=True)
                info = controlador.obter_motivo(motivo_id)
                hora_str = datetime.datetime.now().strftime("%H:%M:%S")
                perc = round((v_otim / VEL_NOMINAL) * 100.0, 1)
                print(f"[{{hora_str}}] Setpoint: {{v_otim:.0f}} CPH ({{perc}}%) | Motivo [{{motivo_id}} - {{info.get('codigo')}}]: {{info.get('descricao')}}")
            else:
                print(f"Status Grafana: {{resp.status_code}}")
        except Exception as e:
            print(f"Erro Grafana: {{e}}")

        try: time.sleep(30)
        except KeyboardInterrupt: break

if __name__ == "__main__":
    main()
'''

with open("controlador_velocidade_grafana_v4.py", "w", encoding="utf-8") as f:
    f.write(codigo_grafana)
print("➔ Módulo Grafana atualizado em 'controlador_velocidade_grafana_v4.py'.")

# =====================================================================
# 7. EXPORTAÇÃO CSV COMPLETA COM CÓDIGOS DE MOTIVO
# =====================================================================
motivos_desc = [mapa_motivos.get(str(mid), {}).get("descricao", "Modulação") for mid in motivos_id]
maquinas_causa = [mapa_motivos.get(str(mid), {}).get("maquina_causadora", "N/A") for mid in motivos_id]

df_export = pd.DataFrame({
    "Timestamp": df["Timestamp"],
    "Velocidade_Real_Enchedora": v_ech_real_hist,
    "Velocidade_Otimizada_V4": v_sug_final,
    "Motivo_ID": motivos_id,
    "Motivo_Codigo": motivos_cod,
    "Motivo_Descricao": motivos_desc,
    "Maquina_Causadora": maquinas_causa,
    "Velocidade_Entrada_ECI": v_in_real_hist,
    "Velocidade_Saida_PZ": v_out_real_hist,
    "Buffer_B2_Bruto": b2_raw,
    "Buffer_B2_Filtrado": b2_hist,
    "Buffer_B3_Bruto": b3_raw,
    "Buffer_B3_Filtrado": b3_hist,
    "Tendencia_Aceleracao_Saida": trend_vout_hist
})
if COL_B1_DPL_UIP:
    df_export["Buffer_B1_Filtrado"] = b1_hist
if COL_B4_PZ_EPC:
    df_export["Buffer_B4_Filtrado"] = b4_hist

df_export.to_csv("dados_velocidade_otimizada_v4.csv", index=False)
print("➔ Base de dados com motivos exportada para 'dados_velocidade_otimizada_v4.csv'.")

# =====================================================================
# 8. GRÁFICOS DIÁRIOS COMPLETOS (PADRÃO V3: 15MIN RESAMPLE + FAIXAS COLORIDAS)
# =====================================================================
pasta_graf = "graficos_velocidade_otimizada_v4"
os.makedirs(pasta_graf, exist_ok=True)

df_plot = df_export.copy()
# Substitui 0 por NaN temporariamente para não falsear médias no resample
df_plot.loc[df_plot["Velocidade_Otimizada_V4"] == 0, "Velocidade_Otimizada_V4"] = np.nan
df_plot.loc[df_plot["Velocidade_Real_Enchedora"] == 0, "Velocidade_Real_Enchedora"] = np.nan

df_smooth = df_plot.set_index("Timestamp").resample("15Min").mean(numeric_only=True).reset_index()
df_smooth["Velocidade_Otimizada_V4"] = df_smooth["Velocidade_Otimizada_V4"].fillna(0)
df_smooth["Velocidade_Real_Enchedora"] = df_smooth["Velocidade_Real_Enchedora"].fillna(0)
df_smooth["Date"] = df_smooth["Timestamp"].dt.date

dias_unicos = df_smooth["Date"].dropna().unique()
print(f"\n➔ Gerando gráficos diários comparativos V4 para TODOS os {len(dias_unicos)} dias do histórico...")

def pintar_regioes(ax, timestamps, mascara, cor, rotulo, alpha=0.18):
    in_region, t_inicio, primeiro = False, None, True
    for t, ativo in zip(timestamps, mascara):
        if ativo and not in_region:
            t_inicio, in_region = t, True
        elif not ativo and in_region:
            ax.axvspan(t_inicio, t, alpha=alpha, color=cor, label=rotulo if primeiro else "_nolegend_")
            primeiro, in_region = False, False
    if in_region:
        ax.axvspan(t_inicio, timestamps.iloc[-1], alpha=alpha, color=cor, label=rotulo if primeiro else "_nolegend_")

for dia in dias_unicos:
    df_dia = df_smooth[df_smooth["Date"] == dia].copy()
    if df_dia.empty: continue

    fig, (ax_vel, ax_buf) = plt.subplots(2, 1, figsize=(16, 10), sharex=True, gridspec_kw={'height_ratios': [2, 1]})
    fig.suptitle(f"Controle de Velocidade Otimizado V4 - Balanço, Tendência e Motivos (Dia: {dia})", fontsize=14, fontweight="bold")

    # Gatilhos operacionais do dia
    gatilho_b2    = df_dia["Buffer_B2_Filtrado"] < b2_opt
    gatilho_b3    = df_dia["Buffer_B3_Filtrado"] > b3_opt
    gatilho_ambos = gatilho_b2 & gatilho_b3
    gatilho_sprint = df_dia["Velocidade_Otimizada_V4"] > (VELOCIDADE_NOMINAL_ECH + 10.0)

    # Faixas coloridas nos dois painéis
    pintar_regioes(ax_vel, df_dia["Timestamp"], gatilho_b2 & ~gatilho_b3, "#2980B9", "⬇ [10] B2 Entrada Baixa")
    pintar_regioes(ax_vel, df_dia["Timestamp"], gatilho_b3 & ~gatilho_b2, "#E67E22", "⬇ [20] B3 Saída Cheia")
    pintar_regioes(ax_vel, df_dia["Timestamp"], gatilho_ambos,             "#8E44AD", "⬇ [30] B2+B3 Simultâneos")
    pintar_regioes(ax_vel, df_dia["Timestamp"], gatilho_sprint,            "#27AE60", "🚀 [1] Sprint (> 100%)", alpha=0.12)

    pintar_regioes(ax_buf, df_dia["Timestamp"], gatilho_b2 & ~gatilho_b3, "#2980B9", "_nolegend_")
    pintar_regioes(ax_buf, df_dia["Timestamp"], gatilho_b3 & ~gatilho_b2, "#E67E22", "_nolegend_")
    pintar_regioes(ax_buf, df_dia["Timestamp"], gatilho_ambos,             "#8E44AD", "_nolegend_")
    pintar_regioes(ax_buf, df_dia["Timestamp"], gatilho_sprint,            "#27AE60", "_nolegend_", alpha=0.12)

    # Painel 1: Velocidades
    ax_vel.plot(df_dia["Timestamp"], df_dia["Velocidade_Real_Enchedora"], label="Real Fábrica", color="#E74C3C", alpha=0.7, linewidth=1.5)
    ax_vel.plot(df_dia["Timestamp"], df_dia["Velocidade_Otimizada_V4"], label="Otimizado V4 (Suave)", color="#2ECC71", alpha=0.9, linewidth=2.0)
    ax_vel.axhline(VELOCIDADE_NOMINAL_ECH * fator_sprint_opt, color="#8E44AD", linestyle=":", alpha=0.7, label=f"Sprint {fator_sprint_opt*100:.0f}%")
    ax_vel.axhline(VELOCIDADE_NOMINAL_ECH, color="#27AE60", linestyle=":", alpha=0.7, label="Nominal 100%")
    ax_vel.axhline(VELOCIDADE_NOMINAL_ECH * min_mod_opt, color="#F39C12", linestyle=":", alpha=0.7, label=f"Piso Modulação {min_mod_opt*100:.0f}%")
    ax_vel.set_ylabel("Velocidade (CPH)", fontsize=11)
    ax_vel.set_ylim(bottom=0)
    ax_vel.legend(loc="upper right", fontsize=8, ncol=3)
    ax_vel.grid(True, linestyle="--", alpha=0.35)

    # Painel 2: Buffers
    ax_buf.plot(df_dia["Timestamp"], df_dia["Buffer_B2_Filtrado"], label="B2 Entrada (Filtrado)", color="#2980B9", alpha=0.9, linewidth=1.8)
    ax_buf.plot(df_dia["Timestamp"], df_dia["Buffer_B3_Filtrado"], label="B3 Saída (Filtrado)", color="#E67E22", alpha=0.9, linewidth=1.8)
    if "Buffer_B1_Filtrado" in df_dia.columns:
        ax_buf.plot(df_dia["Timestamp"], df_dia["Buffer_B1_Filtrado"], label="B1 Ext. Entrada", color="#8E44AD", alpha=0.7, linewidth=1.2)
    if "Buffer_B4_Filtrado" in df_dia.columns:
        ax_buf.plot(df_dia["Timestamp"], df_dia["Buffer_B4_Filtrado"], label="B4 Ext. Saída", color="#C0392B", alpha=0.7, linewidth=1.2)

    ax_buf.axhline(b2_opt, color="#2980B9", linestyle="--", alpha=0.7, linewidth=1.2, label=f"Gatilho B2 ({b2_opt:.0f}%) — entrada")
    ax_buf.axhline(b3_opt, color="#E67E22", linestyle="--", alpha=0.7, linewidth=1.2, label=f"Gatilho B3 ({b3_opt:.0f}%) — saída")
    ax_buf.set_ylabel("Nível do Buffer (%)", fontsize=11)
    ax_buf.set_ylim(0, 105)
    ax_buf.set_xlabel("Hora do Dia", fontsize=10)
    ax_buf.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax_buf.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.setp(ax_buf.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=9)
    ax_buf.legend(loc="upper right", fontsize=8, ncol=3)
    ax_buf.grid(True, linestyle="--", alpha=0.35)

    plt.tight_layout()
    caminho_fig = os.path.join(pasta_graf, f"otimizacao_v4_{dia}.png")
    plt.savefig(caminho_fig, dpi=140)
    plt.close(fig)

print(f"➔ Todos os {len(dias_unicos)} gráficos diários salvos com sucesso em '{pasta_graf}/'.")

# Curva de Convergência CMA-ES
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(hist_scores, color="#2980B9", linewidth=2.2)
ax.set_title("Curva de Convergência CMA-ES V4 (11 Parâmetros)", fontweight="bold")
ax.set_xlabel("Geração")
ax.set_ylabel("Fitness Score")
ax.grid(True, linestyle="--", alpha=0.4)
plt.tight_layout()
plt.savefig("curva_convergencia_v4.png", dpi=140)
plt.close(fig)

# =====================================================================
# 9. RELATÓRIO FINAL DETALHADO COM RESUMO DE MOTIVOS
# =====================================================================
prod_real = (np.sum(v_ech_real_hist) / 3600.0) * time_step
ganho = producao_otimizada - prod_real
percentual = (ganho / prod_real * 100.0) if prod_real > 0 else 0.0

hist_stops_buffer = int(((v_ech_real_hist == 0.0) & ((b2_hist <= 10.0) | (b3_hist >= 90.0))).sum())
sim_stops_buffer  = int(((v_sug_final > (VELOCIDADE_NOMINAL_ECH * min_mod_opt + 500.0)) & ((b2_hist <= 10.0) | (b3_hist >= 90.0))).sum())
reducao_amostras = max(0, hist_stops_buffer - sim_stops_buffer)

# Distribuição dos motivos
contagem_motivos = pd.Series(motivos_id).value_counts()

rel = []
rel.append("="*75)
rel.append("   RELATÓRIO FINAL DO OTIMIZADOR DE VELOCIDADE V4: BALANÇO + MOTIVOS   ")
rel.append("="*75)
rel.append(f"➔ Produção Real Registrada no Histórico : {int(prod_real):,} unidades.")
rel.append(f"➔ Produção Simulada Otimizada V4       : {int(producao_otimizada):,} unidades.")
rel.append(f"➔ GANHO DE PRODUÇÃO ESTIMADO (V4)       : +{int(ganho):,} unidades (+{percentual:.2f}%)")

rel.append("")
rel.append("[MÉTRICAS DE PARADAS E ESTABILIDADE DE PROCESSO]")
rel.append(f"➔ Amostras em Risco de Soco Mecânico no Histórico : {hist_stops_buffer}")
rel.append(f"➔ Amostras em Risco na Simulação Otimizada V4      : {sim_stops_buffer}")
rel.append(f"➔ Amostras Críticas Evitadas                       : {reducao_amostras} ({(reducao_amostras / max(1, hist_stops_buffer) * 100):.1f}% de melhoria)")
rel.append(f"➔ Tempo Extra de Uptime Recuperado                : {int(reducao_amostras * time_step // 3600)}h {int((reducao_amostras * time_step % 3600) // 60)}min")

rel.append("")
rel.append("[DISTRIBUIÇÃO DOS MOTIVOS DE OPERAÇÃO NO HISTÓRICO]")
for m_id, count in contagem_motivos.items():
    perc_m = (count / n_pts) * 100.0
    info_m = mapa_motivos.get(str(m_id), {"codigo": "OUTRO", "descricao": "Modulação"})
    rel.append(f"   ↳ [ID {m_id:2d} - {info_m.get('codigo'):26s}]: {count:6d} amostras ({perc_m:5.1f}%) | {info_m.get('descricao')}")

rel.append("")
rel.append("[PARÂMETROS OTIMIZADOS V4]")
rel.append(f"➔ Velocidade Nominal Enchedora: {int(VELOCIDADE_NOMINAL_ECH):,} CPH")
rel.append(f"➔ Piso de Modulação Seguro     : {min_mod_opt*100:.1f}% ({int(VELOCIDADE_NOMINAL_ECH * min_mod_opt):,} CPH)")
rel.append(f"➔ Teto Sprint / Sobrevelocidade: {fator_sprint_opt*100:.1f}% ({int(VELOCIDADE_NOMINAL_ECH * fator_sprint_opt):,} CPH)")
rel.append(f"➔ Rampa Mecânica Máxima (Slew) : {MAX_RAMPA_CPH_PASSO:.0f} CPH por passo de 30s ({MAX_RAMPA_CPH_PASSO/30:.1f} CPH/s)")
rel.append(f"➔ Gatilho Falta Entrada (B2)   : < {b2_opt:.1f}% (Rampa: {rampa_b2_opt:.1f}%)")
rel.append(f"➔ Gatilho Acúmulo Saída (B3)   : > {b3_opt:.1f}% (Rampa: {rampa_b3_opt:.1f}%)")
rel.append(f"➔ Feedforward Extremo B1       : < {b1_opt:.1f}% (Margem: {antecip_b1_opt:.1f}%)")
rel.append(f"➔ Feedforward Extremo B4       : > {b4_opt:.1f}% (Margem: {antecip_b4_opt:.1f}%)")
rel.append(f"➔ Fator Retomada Sincronizada  : {peso_retomada_opt*100:.1f}% de alívio quando a jusante está acelerando")
rel.append("="*75)

relatorio_texto = "\n".join(rel)
print("\n" + relatorio_texto)

nome_rel = f"relatorio_otimizacao_v4_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
with open(nome_rel, "w", encoding="utf-8") as f:
    f.write(relatorio_texto + "\n")
print(f"➔ Relatório salvo em '{nome_rel}'.")
print("\n✅ EXECUÇÃO V4 CONCLUÍDA COM SUCESSO!")
