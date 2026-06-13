import pandas as pd
import numpy as np
import os

import json

# =====================================================================
# 1. CONFIGURAÇÃO DOS ARQUIVOS E COLUNAS
# =====================================================================
ARQUIVO_CSV = "dados_completos_fabrica.csv"
ARQUIVO_CONFIG = "config_colunas.json"

# Valores padrão de fallback
COL_B1_DPL_UIP = "accumulation_percentage_DPL_UIP_null"  # Extremo Entrada (%)
COL_B2_UIP_ECH = "accumulation_percentage_UIP_ECH_null"  # Interno Entrada (%)
COL_B3_ECH_PZ  = "accumulation_percentage_ECH_PZ_null"   # Interno Saída (%)
COL_B4_PZ_EPC  = "accumulation_percentage_PZ_EPC_null"   # Extremo Saída (%)

COL_V_DPL = "speed_actual_cph_null_first_upstream_machine_1"
COL_V_UIP = "speed_actual_cph_null_eci_1"
COL_V_ECH = "speed_actual_cph_null_filler_1"       # Enchedora (Coração da Linha)
COL_V_ROT = "speed_actual_cph_null_pasteurizer"
COL_V_EPC = "speed_actual_cph_null_first_downstream_machine_3"

if os.path.exists(ARQUIVO_CONFIG):
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            ARQUIVO_CSV = cfg.get("Arquivo_Dados", ARQUIVO_CSV)
            COL_B1_DPL_UIP = cfg.get("Col_Buffer_Antes_Entrada", COL_B1_DPL_UIP)
            COL_B2_UIP_ECH = cfg.get("Col_Buffer_Entrada", COL_B2_UIP_ECH)
            COL_B3_ECH_PZ  = cfg.get("Col_Buffer_Saida", COL_B3_ECH_PZ)
            COL_B4_PZ_EPC  = cfg.get("Col_Buffer_Pos_Saida", COL_B4_PZ_EPC)
            
            COL_V_DPL = cfg.get("COL_V_Antes_Entrada", COL_V_DPL)
            COL_V_UIP = cfg.get("COL_V_Entrada", COL_V_UIP)
            COL_V_ECH = cfg.get("COL_V_ECH", COL_V_ECH)
            COL_V_ROT = cfg.get("COL_V_Saida", COL_V_ROT)
            COL_V_EPC = cfg.get("COL_V_Entrada_Pos_Saida", COL_V_EPC)
            
            VELOCIDADE_NOMINAL_CONFIG = cfg.get("Velocidade_Nominal", None)
            FILTRO_MINUTOS_PARADA_LONGA_CONFIG = cfg.get("Filtro_Minutos_Parada_Longa", None)
        print(f"➔ Configuração de colunas carregada de '{ARQUIVO_CONFIG}'.")
    except Exception as e:
        print(f"⚠️ Erro ao ler '{ARQUIVO_CONFIG}': {e}. Usando padrões.")

VELOCIDADE_NOMINAL_ECH = 52700.0
FILTRO_MINUTOS_PARADA_LONGA = 10
CAPACIDADE_ESTEIRAS_INTERNAS = 500
CAPACIDADE_ESTEIRAS_EXTREMAS = 1000

SALVAR_CSV_COMPARATIVO = True
GERAR_GRAFICO_PLOTS    = True

# =====================================================================
# 2. GERADOR DE MASSA DE DADOS (teste sem CSV real)
# =====================================================================
if not os.path.exists(ARQUIVO_CSV):
    print(f"Arquivo '{ARQUIVO_CSV}' não encontrado. Gerando dados simulados...")
    linhas = 3600
    time_idx = pd.date_range(start="2026-05-29 10:00:00", periods=linhas, freq="s")
    v_epc = [52700] * linhas
    for i in range(600, 1200): v_epc[i] = 0
    v_rot = [52700] * linhas
    for i in range(700, 1200): v_rot[i] = 15000

    gen_b1 = COL_B1_DPL_UIP if COL_B1_DPL_UIP else "accumulation_percentage_DPL_UIP_null"
    gen_b2 = COL_B2_UIP_ECH if COL_B2_UIP_ECH else "accumulation_percentage_UIP_ECH_null"
    gen_b3 = COL_B3_ECH_PZ  if COL_B3_ECH_PZ  else "accumulation_percentage_ECH_PZ_null"
    gen_b4 = COL_B4_PZ_EPC  if COL_B4_PZ_EPC  else "accumulation_percentage_PZ_EPC_null"
    gen_v_dpl = COL_V_DPL if COL_V_DPL else "speed_actual_cph_null_first_upstream_machine_1"
    gen_v_uip = COL_V_UIP if COL_V_UIP else "speed_actual_cph_null_eci_1"
    gen_v_ech = COL_V_ECH if COL_V_ECH else "speed_actual_cph_null_filler_1"
    gen_v_rot = COL_V_ROT if COL_V_ROT else "speed_actual_cph_null_pasteurizer"
    gen_v_epc = COL_V_EPC if COL_V_EPC else "speed_actual_cph_null_first_downstream_machine_3"

    df_fake = pd.DataFrame({
        "Timestamp": time_idx,
        gen_b1: np.random.uniform(50, 60, linhas),
        gen_b2: np.random.uniform(45, 55, linhas),
        gen_b3:  np.linspace(40, 95, linhas),
        gen_b4:  np.linspace(50, 100, linhas),
        gen_v_dpl: [70400] * linhas,
        gen_v_uip: [52700] * linhas,
        gen_v_ech: [52700] * linhas,
        gen_v_rot: v_rot,
        gen_v_epc: v_epc
    })
    df_fake.to_csv(ARQUIVO_CSV, index=False)

df = pd.read_csv(ARQUIVO_CSV)

# Função para resolver coluna com nome EXATO
def resolver_coluna(col_config, col_padrao, opcional=False):
    if not col_config or str(col_config).strip().lower() in ["null", "none", ""]:
        if opcional:
            return None
        col_config = col_padrao  # Se for obrigatória, tenta o fallback
    
    # Procura exata na configuração
    if col_config in df.columns:
        return col_config
            
    # Procura exata no padrão de fallback
    if col_padrao in df.columns:
        return col_padrao
            
    if opcional:
        return None
    raise ValueError(f"Coluna exata '{col_config}' não encontrada no CSV. Verifique o arquivo 'config_colunas.json'.")

# Resolução de todas as colunas
COL_B1_DPL_UIP = resolver_coluna(COL_B1_DPL_UIP, "accumulation_percentage_DPL_UIP_null", opcional=True)
COL_B2_UIP_ECH = resolver_coluna(COL_B2_UIP_ECH, "accumulation_percentage_UIP_ECH_null")
COL_B3_ECH_PZ  = resolver_coluna(COL_B3_ECH_PZ, "accumulation_percentage_ECH_PZ_null")
COL_B4_PZ_EPC  = resolver_coluna(COL_B4_PZ_EPC, "accumulation_percentage_PZ_EPC_null", opcional=True)

COL_V_DPL = resolver_coluna(COL_V_DPL, "speed_actual_cph_null_first_upstream_machine_1", opcional=True)
COL_V_UIP = resolver_coluna(COL_V_UIP, "speed_actual_cph_null_eci_1")
COL_V_ECH = resolver_coluna(COL_V_ECH, "speed_actual_cph_null_filler_1")
COL_V_ROT = resolver_coluna(COL_V_ROT, "speed_actual_cph_null_pasteurizer")
COL_V_EPC = resolver_coluna(COL_V_EPC, "speed_actual_cph_null_first_downstream_machine_3", opcional=True)

HAS_B1 = COL_B1_DPL_UIP is not None
HAS_V_DPL = COL_V_DPL is not None
HAS_B4 = COL_B4_PZ_EPC is not None
HAS_V_EPC = COL_V_EPC is not None

ativo_b1 = "ATIVO" if HAS_B1 else "INATIVO"
ativo_b4 = "ATIVO" if HAS_B4 else "INATIVO"
print(f"➔ Configuração dos pulmões de extremidade: B1 (Antes Entrada) = {ativo_b1} | B4 (Pós Saída) = {ativo_b4}")

df["Timestamp"] = pd.to_datetime(df["Timestamp"])

# FIX: Preencher NaNs oriundos do outer join do Grafana para não quebrar a simulação
df.ffill(inplace=True)
df.fillna(0.0, inplace=True)


if len(df) > 1:
    time_step_seconds = int((df["Timestamp"].iloc[1] - df["Timestamp"].iloc[0]).total_seconds())
    if time_step_seconds <= 0:
        time_step_seconds = 1
else:
    time_step_seconds = 1

print(f"➔ Intervalo de amostragem detectado: {time_step_seconds} segundos.")

v_ech_real_hist = df[COL_V_ECH].values

# FIX: Calcular a Velocidade Nominal Dinamicamente (P90 das velocidades ativas)
# Isso corrige a diferença de escala de velocidade entre diferentes fábricas/bancos
if 'VELOCIDADE_NOMINAL_CONFIG' in locals() and VELOCIDADE_NOMINAL_CONFIG is not None and VELOCIDADE_NOMINAL_CONFIG > 0:
    VELOCIDADE_NOMINAL_ECH = float(VELOCIDADE_NOMINAL_CONFIG)
    print(f"➔ Velocidade Nominal ECH definida pelo usuário: {VELOCIDADE_NOMINAL_ECH:.0f} CPH")
else:
    vels_ativas = v_ech_real_hist[v_ech_real_hist > 1000]
    if len(vels_ativas) > 0:
        VELOCIDADE_NOMINAL_ECH = float(np.percentile(vels_ativas, 90))
        print(f"➔ Velocidade Nominal ECH calculada dinamicamente (p90): {VELOCIDADE_NOMINAL_ECH:.0f} CPH")
        print(f"⚠ Não foram encontradas velocidades válidas. Mantendo nominal em {VELOCIDADE_NOMINAL_ECH:.0f} CPH")

if 'FILTRO_MINUTOS_PARADA_LONGA_CONFIG' in locals() and FILTRO_MINUTOS_PARADA_LONGA_CONFIG is not None:
    FILTRO_MINUTOS_PARADA_LONGA = int(FILTRO_MINUTOS_PARADA_LONGA_CONFIG)

b2_hist = df[COL_B2_UIP_ECH].values
b3_hist = df[COL_B3_ECH_PZ].values

hist_stops_total    = int((v_ech_real_hist == 0.0).sum())
hist_stops_buffer   = int(((v_ech_real_hist == 0.0) & ((b2_hist <= 15.0) | (b3_hist >= 85.0))).sum())
hist_stops_external = hist_stops_total - hist_stops_buffer

# FIX: Identificar paradas externas longas inegociáveis (> FILTRO_MINUTOS_PARADA_LONGA)
limite_amostras_parada = int((FILTRO_MINUTOS_PARADA_LONGA * 60) / time_step_seconds)
is_zero = (v_ech_real_hist == 0.0)
mascara_parada_longa = np.zeros(len(df), dtype=bool)
contador_parada = 0
inicio_parada = -1

for i in range(len(df)):
    if is_zero[i]:
        if contador_parada == 0:
            inicio_parada = i
        contador_parada += 1
    else:
        if contador_parada > limite_amostras_parada:
            mascara_parada_longa[inicio_parada:i] = True
        contador_parada = 0
if contador_parada > limite_amostras_parada:
    mascara_parada_longa[inicio_parada:] = True

print(f"➔ Filtro Parada Longa: {FILTRO_MINUTOS_PARADA_LONGA}min ({limite_amostras_parada} amostras). {mascara_parada_longa.sum()} amostras marcadas como inegociáveis.")

# =====================================================================
# 3. MAPEAMENTO VETOR → DICIONÁRIO DE PARÂMETROS
# =====================================================================
BOUNDS_LO = np.array([35.0, 85.0, 20.0, 70.0, 70.0, 70.0, 65.0, 85.0])
BOUNDS_HI = np.array([48.0, 95.0, 30.0, 85.0, 80.0, 85.0, 75.0, 95.0])

def vetor_para_params(x):
    """Clipa e converte vetor numérico em dicionário de parâmetros."""
    x = np.clip(x, BOUNDS_LO, BOUNDS_HI)
    return {
        "gatilho_b1_falta_extrema":   x[0],
        "vel_ech_falta_extrema":       x[1],
        "gatilho_b2_falta_critica":   x[2],
        "vel_ech_falta_critica":       x[3],
        "gatilho_b3_acumulo_critico": x[4],
        "vel_ech_acumulo_critico":    x[5],
        "gatilho_b4_acumulo_extremo": x[6],
        "vel_ech_acumulo_extremo":    x[7],
    }

# =====================================================================
# 4. MOTOR DO GÊMEO DIGITAL
# =====================================================================
def simular_historico_com_regras_ia(dados_df, p, time_step, mascara_parada, retornar_series=False):
    b2 = dados_df[COL_B2_UIP_ECH].values
    b3 = dados_df[COL_B3_ECH_PZ].values
    v_rot     = dados_df[COL_V_ROT].values
    v_ech_real = dados_df[COL_V_ECH].values
    
    b1 = dados_df[COL_B1_DPL_UIP].values if HAS_B1 else None
    v_dpl = dados_df[COL_V_DPL].values if HAS_V_DPL else None
    
    b4 = dados_df[COL_B4_PZ_EPC].values if HAS_B4 else None
    v_epc = dados_df[COL_V_EPC].values if HAS_V_EPC else None

    producao_total_simulada   = 0.0
    paradas_soco_evitadas     = 0
    paradas_soco_reais_ocorridas = 0
    paradas_externas_ocorridas   = 0
    mudancas_velocidade       = 0
    ultima_velocidade_fator   = 1.0

    b1_ativo = b2_ativo = b3_ativo = b4_ativo = False
    velocidades_simuladas = []

    for i in range(len(dados_df)):
        if b2[i] <= p["gatilho_b2_falta_critica"]:
            b2_ativo = True
        elif b2[i] > p["gatilho_b2_falta_critica"] + 10.0:
            b2_ativo = False

        if b3[i] >= p["gatilho_b3_acumulo_critico"]:
            b3_ativo = True
        elif b3[i] < p["gatilho_b3_acumulo_critico"] - 10.0:
            b3_ativo = False

        if HAS_B4 and b4 is not None:
            if b4[i] >= p["gatilho_b4_acumulo_extremo"]:
                b4_ativo = True
            elif b4[i] < p["gatilho_b4_acumulo_extremo"] - 15.0:
                b4_ativo = False
        else:
            b4_ativo = False

        if HAS_B1 and b1 is not None:
            if b1[i] <= p["gatilho_b1_falta_extrema"]:
                b1_ativo = True
            elif b1[i] > p["gatilho_b1_falta_extrema"] + 10.0:
                b1_ativo = False
        else:
            b1_ativo = False

        if mascara_parada[i]:
            # Parada externa inegociável (quebra mecânica longa)
            fator_velocidade = 0.0
            paradas_externas_ocorridas += 1
        elif b2[i] <= 5.0 or b3[i] >= 97.0:  # V2: gatilho ampliado (era 2%/99%)
            # Parada de buffer crítico no histórico: otimizador pode evitá-la
            # convertendo-a em produção a velocidade reduzida (ganho real).
            fator_reduzido = 1.0
            if b2_ativo:
                fator_reduzido = p["vel_ech_falta_critica"] / 100.0
            elif b3_ativo:
                fator_reduzido = p["vel_ech_acumulo_critico"] / 100.0
            else:
                fator_reduzido = 0.7  # redução conservadora padrão
            fator_velocidade = fator_reduzido
            paradas_soco_reais_ocorridas += 1  # ainda conta como parada evitada (para penalidade)
        elif v_ech_real[i] == 0.0:
            # Parada externa (mecânica/operador): preservada integralmente
            fator_velocidade = 0.0
            paradas_externas_ocorridas += 1
        else:
            # Máquina rodando: preserva SEMPRE a velocidade real histórica.
            # O simulador não reduz a velocidade durante períodos de marcha porque
            # os dados históricos são fixos — reduzir aqui apenas tira produção
            # sem capturar o efeito real de estabilização do buffer.
            # O ganho real do otimizador vem de EVITAR paradas (bloco acima),
            # não de reduzir velocidade em períodos que já estavam rodando.
            fator_velocidade = v_ech_real[i] / VELOCIDADE_NOMINAL_ECH

            # Conta paradas de soco proativas (momento em que o buffer extremo
            # teria causado parada breve, mas o operador/CLP teria desacelerado):
            if HAS_B4 and b4_ativo and v_rot[i] < VELOCIDADE_NOMINAL_ECH:
                paradas_soco_evitadas += 1
            elif HAS_B1 and HAS_V_DPL and b1_ativo and v_dpl[i] < VELOCIDADE_NOMINAL_ECH:
                paradas_soco_evitadas += 1

        cph_calculado = VELOCIDADE_NOMINAL_ECH * fator_velocidade
        producao_total_simulada += (cph_calculado / 3600.0) * time_step
        if retornar_series:
            velocidades_simuladas.append(cph_calculado)

        if fator_velocidade != ultima_velocidade_fator:
            mudancas_velocidade += 1
            ultima_velocidade_fator = fator_velocidade

    score_fitness = producao_total_simulada - (paradas_soco_reais_ocorridas * 150) - (mudancas_velocidade * 0.25)

    if retornar_series:
        return score_fitness, producao_total_simulada, paradas_soco_reais_ocorridas, paradas_externas_ocorridas, paradas_soco_evitadas, velocidades_simuladas
    return score_fitness, producao_total_simulada, paradas_soco_reais_ocorridas, paradas_externas_ocorridas, paradas_soco_evitadas

# =====================================================================
# 5. IMPLEMENTAÇÃO CMA-ES (sem dependência externa)
# =====================================================================
# CMA-ES — Covariance Matrix Adaptation Evolution Strategy
# Referência: Hansen, N. (2016). The CMA Evolution Strategy: A Tutorial.
# Vantagem sobre busca aleatória: adapta a direção e escala da busca
# usando a matriz de covariância da população, convergindo muito mais
# rápido em problemas contínuos e multimodais.

def cma_es(
    func,           # função a MAXIMIZAR (retorna escalar)
    x0,             # ponto inicial (vetor numpy)
    sigma0=1.5,     # desvio-padrão inicial
    max_iter=500,   # máximo de gerações
    tol=1e-8,       # tolerância de convergência (sigma)
    seed=42
):
    rng = np.random.default_rng(seed)
    n   = len(x0)   # dimensão do espaço de busca (8)

    # --- Tamanho da população ---
    lam = 4 + int(np.floor(3 * np.log(n)))   # ~10 para n=8
    mu  = lam // 2                             # ~5 pais selecionados

    # --- Pesos de recombinação (log-rank) ---
    weights_raw = np.log(mu + 0.5) - np.log(np.arange(1, mu + 1))
    weights     = weights_raw / weights_raw.sum()
    mueff       = 1.0 / (weights ** 2).sum()   # variância efetiva

    # --- Constantes de adaptação ---
    cc    = (4 + mueff / n) / (n + 4 + 2 * mueff / n)
    cs    = (mueff + 2) / (n + mueff + 5)
    c1    = 2.0 / ((n + 1.3) ** 2 + mueff)
    cmu   = min(1 - c1, 2 * (mueff - 2 + 1 / mueff) / ((n + 2) ** 2 + mueff))
    damps = 1 + 2 * max(0, np.sqrt((mueff - 1) / (n + 1)) - 1) + cs
    chiN  = n ** 0.5 * (1 - 1 / (4 * n) + 1 / (21 * n ** 2))  # E[||N(0,I)||]

    # --- Estado inicial ---
    xmean  = x0.copy().astype(float)
    sigma  = float(sigma0)
    pc     = np.zeros(n)   # caminho de evolução para C
    ps     = np.zeros(n)   # caminho de evolução para sigma
    B      = np.eye(n)     # autovetores de C
    D      = np.ones(n)    # autovalores de C (raiz)
    C      = np.eye(n)     # matriz de covariância
    invsqrtC = np.eye(n)
    eigeneval = 0          # controle de reavaliação da decomposição

    melhor_score  = -np.inf
    melhor_x      = xmean.copy()
    historico_scores = []
    gen_sem_melhoria = 0       # Early stopping
    PACIENCIA = 100            # para se não melhorar em 100 gerações

    print(f"\n{'='*60}")
    print(f"  OTIMIZADOR AVANÇADO  |  n={n}  λ={lam}  μ={mu}")
    print(f"  σ₀={sigma0}  max_iter={max_iter}")
    print(f"{'='*60}")

    for gen in range(max_iter):
        # --- Amostragem da população ---
        arz  = rng.standard_normal((lam, n))      # amostras padrão
        arx  = xmean + sigma * (arz @ (B * D).T)  # amostras no espaço original

        # --- Avaliação (CMA-ES maximiza, passamos -score para minimizar internamente) ---
        fitness = np.array([func(xi) for xi in arx])

        # --- Ordenação: do melhor ao pior ---
        idx = np.argsort(fitness)[::-1]   # decrescente (maximização)

        # Atualiza melhor global (melhoria mínima de 1.0 para contar)
        if fitness[idx[0]] > melhor_score + 1.0:
            melhor_score = fitness[idx[0]]
            melhor_x     = arx[idx[0]].copy()
            gen_sem_melhoria = 0
        else:
            gen_sem_melhoria += 1

        historico_scores.append(melhor_score)

        # Log a cada 50 gerações
        if gen % 50 == 0 or gen == max_iter - 1:
            print(f"  Geração {gen:4d} | Melhor score: {melhor_score:,.1f} | σ: {sigma:.4f}")

        # --- Recombinação dos μ melhores ---
        xold   = xmean.copy()
        xmean  = weights @ arx[idx[:mu]]

        # --- Atualização do caminho ps (para controle de sigma) ---
        ps = (1 - cs) * ps + np.sqrt(cs * (2 - cs) * mueff) * invsqrtC @ (xmean - xold) / sigma

        # --- Atualização do caminho pc (para rank-1 da covariância) ---
        hsig   = (np.linalg.norm(ps) / np.sqrt(1 - (1 - cs) ** (2 * (gen + 1))) / chiN) < (1.4 + 2 / (n + 1))
        pc     = (1 - cc) * pc + hsig * np.sqrt(cc * (2 - cc) * mueff) * (xmean - xold) / sigma

        # --- Atualização da Matriz de Covariância C ---
        artmp = (1 / sigma) * (arx[idx[:mu]] - xold)
        # Calcula a soma ponderada dos produtos externos usando np.einsum
        C_mu = np.einsum('k,ki,kj->ij', weights, artmp, artmp)
        C = (
            (1 - c1 - cmu) * C
            + c1 * (np.outer(pc, pc) + (1 - hsig) * cc * (2 - cc) * C)
            + cmu * C_mu
        )

        # --- Atualização do passo sigma ---
        sigma *= np.exp((cs / damps) * (np.linalg.norm(ps) / chiN - 1))

        # --- Decomposição espectral de C (a cada n/10 gerações para eficiência) ---
        if gen - eigeneval > lam / (c1 + cmu) / n / 10:
            eigeneval = gen
            C = np.triu(C) + np.triu(C, 1).T   # simetrização
            D, B = np.linalg.eigh(C)
            D    = np.sqrt(np.maximum(D, 1e-20))
            invsqrtC = B @ np.diag(1.0 / D) @ B.T

        # --- Critérios de convergência ---
        if sigma < tol:
            print(f"\n  ✔ Convergência por σ na geração {gen} (σ={sigma:.2e})")
            break
        if gen_sem_melhoria >= PACIENCIA:
            print(f"\n  ✔ Early stop: sem melhoria há {PACIENCIA} gerações (geração {gen})")
            break

    return melhor_x, melhor_score, historico_scores

# =====================================================================
# 6. EXECUÇÃO DA OTIMIZAÇÃO  [V2: multi-seed + 1500 iterações]
# =====================================================================
print("\nIniciando Otimização Avançada Multivariável (V2)...")
print("V2: gatilho ampliado | 1000 gerações (max) | 3 seeds | early stop\n")

x0     = (BOUNDS_LO + BOUNDS_HI) / 2.0
sigma0 = 2.0

def objetivo(x):
    """Wrapper: recebe vetor, converte, simula e retorna score (a maximizar)."""
    p = vetor_para_params(x)
    score, _, _, _, _ = simular_historico_com_regras_ia(df, p, time_step_seconds, mascara_parada_longa)
    penalidade = 0.0
    for i in range(len(x)):
        if x[i] < BOUNDS_LO[i]:
            penalidade += (BOUNDS_LO[i] - x[i]) ** 2 * 100000.0
        elif x[i] > BOUNDS_HI[i]:
            penalidade += (x[i] - BOUNDS_HI[i]) ** 2 * 100000.0
    return score - penalidade

# --- Multi-seed: 3 corridas independentes, pega o melhor resultado global ---
SEEDS = [42, 123, 777]
melhor_x          = None
melhor_score_cma  = -np.inf
historico         = []

for seed_atual in SEEDS:
    print(f"\n>>> Rodada seed={seed_atual} ({SEEDS.index(seed_atual)+1}/{len(SEEDS)})")
    x_s, score_s, hist_s = cma_es(
        func     = objetivo,
        x0       = x0,
        sigma0   = sigma0,
        max_iter = 1000,
        tol      = 1e-8,
        seed     = seed_atual
    )
    if score_s > melhor_score_cma:
        melhor_score_cma = score_s
        melhor_x         = x_s
        historico        = hist_s
        print(f"  ★ Novo melhor global: {melhor_score_cma:,.1f} (seed={seed_atual})")
    else:
        print(f"  → Score {score_s:,.1f} não superou o atual {melhor_score_cma:,.1f}")

print(f"\n✔ Melhor resultado global encontrado com score: {melhor_score_cma:,.1f}")

melhores_parametros = vetor_para_params(melhor_x)

# Coleta série temporal com os melhores parâmetros encontrados
_, v_prod, v_paradas, v_paradas_ext, v_evitadas, vel_simulada = simular_historico_com_regras_ia(
    df, melhores_parametros, time_step_seconds, mascara_parada_longa, retornar_series=True
)

producao_real_historica = (df[COL_V_ECH].sum() / 3600.0) * time_step_seconds
ganho_garrafas  = v_prod - producao_real_historica
ganho_percentual = (ganho_garrafas / producao_real_historica * 100) if producao_real_historica > 0 else 0.0

# =====================================================================
# 7. RELATÓRIO FINAL
# =====================================================================

# Contabilização real das paradas simuladas (quando a velocidade simulada é de fato zero)
vel_sim_arr = np.array(vel_simulada)
sim_stops_buffer = int(((vel_sim_arr == 0.0) & ((b2_hist <= 15.0) | (b3_hist >= 85.0))).sum())
sim_stops_external = int(((vel_sim_arr == 0.0) & (b2_hist > 15.0) & (b3_hist < 85.0)).sum())

# Contabilização de amostras em nível crítico de buffer onde a parada foi evitada reduzindo a velocidade
criticos_evitados = int(((df[COL_B2_UIP_ECH] <= 2.0) | (df[COL_B3_ECH_PZ] >= 99.0)).sum())
reducao = hist_stops_buffer - sim_stops_buffer

# --- Monta o relatório numa lista de linhas para reutilizar no terminal e no arquivo ---
_rel = []
_rel.append("")
_rel.append("="*65)
_rel.append("   RELATÓRIO FINAL DO OTIMIZADOR: CONFIGURAÇÃO OTIMIZADA DA LINHA   ")
_rel.append("="*65)
_rel.append(f"➔ Produção Real Registrada no Histórico: {int(producao_real_historica)} unidades.")
_rel.append(f"➔ Produção Simulada Otimizada : {int(v_prod)} unidades.")
if ganho_garrafas > 0:
    _rel.append(f"➔ GANHO DE PRODUÇÃO ESTIMADO  : +{int(ganho_garrafas)} unidades (+{ganho_percentual:.2f}%)")
else:
    _rel.append(f"➔ GANHO DE PRODUÇÃO ESTIMADO  : 0 unidades (Linha já rodou de forma ótima)")

_rel.append("")
_rel.append("[MÉTRICAS DE PARADAS DE MÁQUINA (0 CPH)]")
_rel.append(f"➔ Paradas por Falta/Acúmulo (Buffers):")
_rel.append(f"   ↳ No histórico original : {hist_stops_buffer} amostras")
_rel.append(f"   ↳ Na simulação Otimizada : {sim_stops_buffer} amostras")
_rel.append(f"   ↳ EVITADAS PELO OTIMIZADOR  : {reducao} amostras ({(reducao/max(1,hist_stops_buffer)*100):.1f}% de melhoria)")
_rel.append(f"   ↳ Amostras críticas de buffer mantidas em marcha reduzida: {criticos_evitados} amostras")
_rel.append(f"➔ Paradas por Motivos Externos (Mecânica/Operador):")
_rel.append(f"   ↳ No histórico original : {hist_stops_external} amostras")
_rel.append(f"   ↳ Na simulação Otimizada : {sim_stops_external} amostras")

_rel.append("")
_rel.append("[VELOCIDADE ALTA (100%)]")
_rel.append(f"➔ Ação: Enchedora → 100.0% ({int(VELOCIDADE_NOMINAL_ECH)} CPH)")
_rel.append("➔ Condições para rodar a 100% (Todos os pulmões ativos na faixa segura):")
if HAS_B1 and HAS_V_DPL:
    _rel.append(f"   ↳ Nível do Pulmão DPL-UIP (Antes Entrada) > {melhores_parametros['gatilho_b1_falta_extrema'] + 10.0:.1f}%")
_rel.append(f"   ↳ Nível do Pulmão UIP-ECH (Entrada)        > {melhores_parametros['gatilho_b2_falta_critica'] + 10.0:.1f}%")
_rel.append(f"   ↳ Nível do Pulmão ECH-PZ (Saída)           < {melhores_parametros['gatilho_b3_acumulo_critico'] - 10.0:.1f}%")
if HAS_B4:
    _rel.append(f"   ↳ Nível do Pulmão PZ-EPC (Pós Saída)       < {melhores_parametros['gatilho_b4_acumulo_extremo'] - 15.0:.1f}%")

_rel.append("")
_rel.append("[CADEIA DE ENTRADA - PROTEÇÃO CONTRA FALTA DE GARRAFAS]")
contador_entrada = 1
if HAS_B1 and HAS_V_DPL:
    _rel.append(f" {contador_entrada}. Tela Falta DPL-UIP (Extremo):")
    _rel.append(f"    ↳ Gatilho REDUZIR (Start): nível ABAIXO de {melhores_parametros['gatilho_b1_falta_extrema']:.1f}% → Ação: Enchedora → {melhores_parametros['vel_ech_falta_extrema']:.1f}% ({int(VELOCIDADE_NOMINAL_ECH * melhores_parametros['vel_ech_falta_extrema']/100)} CPH)")
    _rel.append(f"    ↳ Gatilho LIGAR   (Clear): nível ACIMA de {(melhores_parametros['gatilho_b1_falta_extrema'] + 10.0):.1f}%")
    contador_entrada += 1

_rel.append(f"")
_rel.append(f" {contador_entrada}. Tela Falta UIP-ECH (Interno):")
_rel.append(f"    ↳ Gatilho REDUZIR (Start): nível ABAIXO de {melhores_parametros['gatilho_b2_falta_critica']:.1f}% → Ação: Enchedora → {melhores_parametros['vel_ech_falta_critica']:.1f}% ({int(VELOCIDADE_NOMINAL_ECH * melhores_parametros['vel_ech_falta_critica']/100)} CPH)")
_rel.append(f"    ↳ Gatilho LIGAR   (Clear): nível ACIMA de {(melhores_parametros['gatilho_b2_falta_critica'] + 10.0):.1f}%")

_rel.append("")
_rel.append("-"*65)
_rel.append("[CADEIA DE SAÍDA - PROTEÇÃO CONTRA ACÚMULO / ENGARRAFAMENTO]")
contador_saida = 1
_rel.append(f" {contador_saida}. Tela Acúmulo ECH-PZ (Interno - Mais Próximo):")
_rel.append(f"    ↳ Gatilho REDUZIR (Start): nível ACIMA de {melhores_parametros['gatilho_b3_acumulo_critico']:.1f}% → Ação: Enchedora → {melhores_parametros['vel_ech_acumulo_critico']:.1f}% ({int(VELOCIDADE_NOMINAL_ECH * melhores_parametros['vel_ech_acumulo_critico']/100)} CPH)")
_rel.append(f"    ↳ Gatilho LIGAR   (Clear): nível ABAIXO de {(melhores_parametros['gatilho_b3_acumulo_critico'] - 10.0):.1f}%")
contador_saida += 1

if HAS_B4:
    _rel.append(f"")
    _rel.append(f" {contador_saida}. Tela Acúmulo PZ-EPC (Extremo - Mais Afastado):")
    _rel.append(f"    ↳ Gatilho REDUZIR (Start): nível ACIMA de {melhores_parametros['gatilho_b4_acumulo_extremo']:.1f}% → Ação: Enchedora → {melhores_parametros['vel_ech_acumulo_extremo']:.1f}% ({int(VELOCIDADE_NOMINAL_ECH * melhores_parametros['vel_ech_acumulo_extremo']/100)} CPH)")
    _rel.append(f"    ↳ Gatilho LIGAR   (Clear): nível ABAIXO de {(melhores_parametros['gatilho_b4_acumulo_extremo'] - 15.0):.1f}%")
_rel.append("="*65)
_rel.append("Pronto! Use esses parâmetros nas suas regras de controle do CLP.")

# --- Imprime no terminal ---
for linha in _rel:
    print(linha)

# --- Salva em arquivo de texto ---
import datetime as _dt
_nome_relatorio = f"relatorio_otimizador_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
with open(_nome_relatorio, "w", encoding="utf-8") as _f:
    _f.write("\n".join(_rel) + "\n")
print(f"\n➔ Relatório final salvo em '{_nome_relatorio}'.")

# =====================================================================
# 8. EXPORTAÇÃO CSV E GRÁFICO
# =====================================================================
if SALVAR_CSV_COMPARATIVO:
    df_comparado = pd.DataFrame({
        "Timestamp":                  df["Timestamp"],
        "Velocidade_Real_Enchedora":  df[COL_V_ECH],
        "Velocidade_Simulada_Otimizada": vel_simulada,
        "Buffer_B2_UIP_ECH":          df[COL_B2_UIP_ECH],
        "Buffer_B3_ECH_PZ":           df[COL_B3_ECH_PZ]
    })
    df_comparado.to_csv("dados_projetados_otimizado.csv", index=False)
    print("\n➔ CSV comparativo salvo em 'dados_projetados_otimizado.csv'.")

if GERAR_GRAFICO_PLOTS:
    try:
        import matplotlib.pyplot as plt

        # --- Prepara os dados para o gráfico ---
        df_plot = pd.DataFrame({
            "Timestamp": df["Timestamp"],
            "Real":      df[COL_V_ECH],
            "Otimizado": vel_simulada
        }).set_index("Timestamp")
        df_smooth = df_plot.resample("15Min").mean().reset_index()

        # Extrai os dias únicos para separar os gráficos
        df_smooth['Date'] = df_smooth['Timestamp'].dt.date
        dias_unicos = df_smooth['Date'].unique()
        
        print("\n➔ Gerando gráficos detalhados dia a dia...")

        # Gera e salva um gráfico para cada dia
        for dia in dias_unicos:
            df_dia = df_smooth[df_smooth['Date'] == dia]
            
            # Pula dias que podem ter ficado sem dados após o resample
            if df_dia.empty:
                continue

            fig, axes = plt.subplots(2, 1, figsize=(15, 10))

            # --- Painel 1: Comparação de velocidades (Focado no Dia) ---
            axes[0].plot(df_dia["Timestamp"], df_dia["Real"],   label="Velocidade Real (15m)",    color="#E74C3C", alpha=0.7, linewidth=2)
            axes[0].plot(df_dia["Timestamp"], df_dia["Otimizado"], label="Velocidade Otimizada (15m)",  color="#27AE60", alpha=0.9, linewidth=2)
            axes[0].set_title(f"Comparação de Velocidades da Enchedora (Dia: {dia})", fontsize=13, fontweight="bold")
            axes[0].set_ylabel("Velocidade (CPH)")
            axes[0].legend()
            axes[0].grid(True, linestyle="--", alpha=0.4)

            # --- Painel 2: Convergência do Otimizador ---
            axes[1].plot(historico, color="#2980B9", linewidth=1.5)
            axes[1].set_title("Curva de Evolução do Otimizador", fontsize=13, fontweight="bold")
            axes[1].set_xlabel("Geração")
            axes[1].set_ylabel("Melhor Score (fitness)")
            axes[1].grid(True, linestyle="--", alpha=0.4)

            plt.tight_layout()
            nome_arquivo = f"comparacao_velocidades_otimizado_{dia}.png"
            plt.savefig(nome_arquivo, dpi=150)
            plt.close(fig) # Fecha a figura para não consumir RAM acumulada
            print(f"   ↳ Salvo: {nome_arquivo}")
    except Exception as e:
        print(f"⚠️ Erro ao gerar gráfico: {e}")
