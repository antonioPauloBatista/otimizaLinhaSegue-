import pandas as pd
import numpy as np
import os
import json
import sys

# =====================================================================
# 1. FUNÇÕES MODULARES E DETECÇÃO AUTOMÁTICA DE LIMITES
# =====================================================================

def resolver_coluna(df, col_config, col_padrao, opcional=False):
    """Localiza uma coluna no DataFrame com base na configuração ou padrão de fallback."""
    if not col_config or str(col_config).strip().lower() in ["null", "none", ""]:
        if opcional:
            return None
        col_config = col_padrao

    if col_config in df.columns:
        return col_config

    if col_padrao in df.columns:
        return col_padrao

    if opcional:
        return None
    raise ValueError(f"Coluna exata '{col_config}' não encontrada no CSV. Verifique o arquivo de configuração.")


def calcular_limites_busca_automaticos(
    df,
    col_v_ech,
    col_b2,
    col_b3,
    col_b1=None,
    col_b4=None,
    vel_nominal=52000.0,
    histerese=5.0
):
    """
    Analisa estatisticamente o histórico da fábrica para calcular as fronteiras
    reais de falha (quando a enchedora parou por falta ou acúmulo) e o regime
    de operação contínua.

    Retorna:
        bounds_lo: np.ndarray de 8 elementos
        bounds_hi: np.ndarray de 8 elementos
        info_diagnostico: dict com limites de falha e percentis
    """
    v = df[col_v_ech].values
    mask_paradas = (v == 0.0)
    mask_rodando = (v >= 0.5 * vel_nominal)

    total_paradas = int(mask_paradas.sum())

    # Fallback robusto caso não haja paradas no histórico
    if total_paradas == 0:
        bounds_lo = np.array([25.0, 80.0, 30.0, 80.0, 70.0, 85.0, 74.0, 85.0])
        bounds_hi = np.array([45.0, 95.0, 48.0, 95.0, 82.0, 95.0, 85.0, 95.0])
        info = {
            "total_paradas": 0,
            "limite_falta_b1": 35.0,
            "limite_falta_b2": 40.0,
            "limite_acumulo_b3": 85.0,
            "limite_acumulo_b4": 80.0,
            "histerese": float(histerese)
        }
        return bounds_lo, bounds_hi, info

    # 2. B2 (Entrada UIP-ECH: Falta)
    b2_rodando = df.loc[mask_rodando, col_b2].dropna() if col_b2 in df.columns else pd.Series([], dtype=float)
    b2_parado = df.loc[mask_paradas, col_b2].dropna() if col_b2 in df.columns else pd.Series([], dtype=float)
    med_b2_rodando = float(np.percentile(b2_rodando, 50)) if len(b2_rodando) else 65.0

    paradas_falta_b2 = b2_parado[b2_parado < med_b2_rodando]
    if len(paradas_falta_b2) > 0:
        p_falta_b2 = float(np.percentile(paradas_falta_b2, 25))
    else:
        p_falta_b2 = float(np.percentile(b2_parado, 15)) if len(b2_parado) else 35.0

    limite_falta_b2 = float(np.clip(p_falta_b2, 25.0, 50.0))
    b2_lo = max(25.0, limite_falta_b2 - 8.0)
    b2_hi = min(50.0, max(b2_lo + 8.0, limite_falta_b2 + 8.0))

    # 3. B1 (Antes Entrada DPL-UIP: Falta, se ativo)
    if col_b1 and col_b1 in df.columns:
        b1_rodando = df.loc[mask_rodando, col_b1].dropna()
        b1_parado = df.loc[mask_paradas, col_b1].dropna()
        med_b1_rodando = float(np.percentile(b1_rodando, 50)) if len(b1_rodando) else 60.0
        paradas_falta_b1 = b1_parado[b1_parado < med_b1_rodando]
        if len(paradas_falta_b1) > 0:
            p_falta_b1 = float(np.percentile(paradas_falta_b1, 25))
        else:
            p_falta_b1 = float(np.percentile(b1_parado, 15)) if len(b1_parado) else 35.0
        limite_falta_b1 = float(np.clip(p_falta_b1, 20.0, 48.0))
        b1_lo = max(20.0, limite_falta_b1 - 8.0)
        b1_hi = min(48.0, max(b1_lo + 8.0, limite_falta_b1 + 8.0))
    else:
        limite_falta_b1 = 30.0
        b1_lo = 25.0
        b1_hi = 45.0

    # 4. B3 (Saída Interna ECH-PZ: Acúmulo)
    b3_rodando = df.loc[mask_rodando, col_b3].dropna() if col_b3 in df.columns else pd.Series([], dtype=float)
    b3_parado = df.loc[mask_paradas, col_b3].dropna() if col_b3 in df.columns else pd.Series([], dtype=float)
    p75_b3_rodando = float(np.percentile(b3_rodando, 75)) if len(b3_rodando) else 70.0
    med_b3_rodando = float(np.percentile(b3_rodando, 50)) if len(b3_rodando) else 55.0

    paradas_acumulo_b3 = b3_parado[b3_parado > med_b3_rodando]
    if len(paradas_acumulo_b3) > 0:
        p_acumulo_b3 = float(np.percentile(paradas_acumulo_b3, 85))
    else:
        p_acumulo_b3 = float(np.percentile(b3_parado, 85)) if len(b3_parado) else 85.0

    limite_acumulo_b3 = float(np.clip(p_acumulo_b3, 75.0, 95.0))
    b3_lo = max(70.0, min(p75_b3_rodando, limite_acumulo_b3 - 8.0))
    b3_hi = min(88.0, max(b3_lo + 8.0, limite_acumulo_b3))

    # 5. B4 (Pós Saída PZ-EPC: Acúmulo, se ativo)
    if col_b4 and col_b4 in df.columns:
        b4_rodando = df.loc[mask_rodando, col_b4].dropna()
        b4_parado = df.loc[mask_paradas, col_b4].dropna()
        p90_b4_rodando = float(np.percentile(b4_rodando, 90)) if len(b4_rodando) else 68.0
        med_b4_rodando = float(np.percentile(b4_rodando, 50)) if len(b4_rodando) else 55.0

        paradas_acumulo_b4 = b4_parado[b4_parado > med_b4_rodando]
        if len(paradas_acumulo_b4) > 0:
            p_acumulo_b4 = float(np.percentile(paradas_acumulo_b4, 85))
        else:
            p_acumulo_b4 = float(np.percentile(b4_parado, 85)) if len(b4_parado) else 78.0

        limite_acumulo_b4 = float(np.clip(p_acumulo_b4, 75.0, 90.0))
        # O limite inferior de busca deve ficar estritamente acima do regime normal (p90 rodando)
        # para que o otimizador NUNCA recomende 65% em esteiras que operam normalmente a 68%
        b4_lo = max(72.0, min(p90_b4_rodando + 1.0, limite_acumulo_b4 - 5.0))
        b4_hi = min(86.0, max(b4_lo + 8.0, limite_acumulo_b4 + 4.0))
    else:
        limite_acumulo_b4 = 78.0
        b4_lo = 74.0
        b4_hi = 85.0

    # 6. Montagem dos limites do vetor (8 parâmetros)
    bounds_lo = np.array([
        b1_lo,  80.0,   # B1 Falta, Vel B1
        b2_lo,  80.0,   # B2 Falta, Vel B2
        b3_lo,  85.0,   # B3 Acúmulo, Vel B3
        b4_lo,  85.0    # B4 Acúmulo, Vel B4
    ])

    bounds_hi = np.array([
        b1_hi,  95.0,   # B1 Falta, Vel B1
        b2_hi,  95.0,   # B2 Falta, Vel B2
        b3_hi,  95.0,   # B3 Acúmulo, Vel B3
        b4_hi,  95.0    # B4 Acúmulo, Vel B4
    ])

    info = {
        "total_paradas": total_paradas,
        "limite_falta_b1": limite_falta_b1,
        "limite_falta_b2": limite_falta_b2,
        "limite_acumulo_b3": limite_acumulo_b3,
        "limite_acumulo_b4": limite_acumulo_b4,
        "histerese": float(histerese)
    }

    return bounds_lo, bounds_hi, info


def vetor_para_params(x, bounds_lo, bounds_hi):
    """Clipa e converte vetor numérico em dicionário de parâmetros."""
    x = np.clip(x, bounds_lo, bounds_hi)
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


def simular_historico_com_regras_ia(
    dados_df, p, time_step, mascara_parada,
    col_b2, col_b3, col_v_ech, col_v_rot,
    col_b1=None, col_v_dpl=None,
    col_b4=None, col_v_epc=None,
    vel_nominal_ech=52000.0,
    fator_sobremarcha=1.0,
    limite_parada_falta=25.0,
    limite_parada_acumulo=75.0,
    histerese=5.0,
    retornar_series=False
):
    b2 = dados_df[col_b2].values
    b3 = dados_df[col_b3].values
    v_rot = dados_df[col_v_rot].values
    v_ech_real = dados_df[col_v_ech].values

    has_b1 = col_b1 is not None and col_b1 in dados_df.columns
    has_v_dpl = col_v_dpl is not None and col_v_dpl in dados_df.columns
    b1 = dados_df[col_b1].values if has_b1 else None
    v_dpl = dados_df[col_v_dpl].values if has_v_dpl else None

    has_b4 = col_b4 is not None and col_b4 in dados_df.columns
    b4 = dados_df[col_b4].values if has_b4 else None

    producao_total_simulada = 0.0
    paradas_soco_evitadas = 0
    paradas_soco_reais_ocorridas = 0
    paradas_externas_ocorridas = 0
    mudancas_velocidade = 0
    ultima_velocidade_fator = 1.0

    b1_ativo = b2_ativo = b3_ativo = b4_ativo = False
    velocidades_simuladas = []

    for i in range(len(dados_df)):
        # Avaliação com histerese padronizada (5.0%)
        if b2[i] <= p["gatilho_b2_falta_critica"]:
            b2_ativo = True
        elif b2[i] > p["gatilho_b2_falta_critica"] + histerese:
            b2_ativo = False

        if b3[i] >= p["gatilho_b3_acumulo_critico"]:
            b3_ativo = True
        elif b3[i] < p["gatilho_b3_acumulo_critico"] - histerese:
            b3_ativo = False

        if has_b4 and b4 is not None:
            if b4[i] >= p["gatilho_b4_acumulo_extremo"]:
                b4_ativo = True
            elif b4[i] < p["gatilho_b4_acumulo_extremo"] - histerese:
                b4_ativo = False
        else:
            b4_ativo = False

        if has_b1 and b1 is not None:
            if b1[i] <= p["gatilho_b1_falta_extrema"]:
                b1_ativo = True
            elif b1[i] > p["gatilho_b1_falta_extrema"] + histerese:
                b1_ativo = False
        else:
            b1_ativo = False

        if mascara_parada[i]:
            # Parada externa inegociável (quebra mecânica longa)
            fator_velocidade = 0.0
            paradas_externas_ocorridas += 1
        elif v_ech_real[i] == 0.0 and (b2[i] <= limite_parada_falta or b3[i] >= limite_parada_acumulo):
            # Modulação para absorver micro-paradas sem derrubar a linha
            if b2[i] <= limite_parada_falta and b2_ativo:
                if p["vel_ech_falta_critica"] <= 95.0:
                    fator_velocidade = p["vel_ech_falta_critica"] / 100.0
                else:
                    fator_velocidade = 0.0
                    paradas_soco_reais_ocorridas += 1
            elif b3[i] >= limite_parada_acumulo and b3_ativo:
                if p["vel_ech_acumulo_critico"] <= 95.0:
                    fator_velocidade = p["vel_ech_acumulo_critico"] / 100.0
                else:
                    fator_velocidade = 0.0
                    paradas_soco_reais_ocorridas += 1
            else:
                fator_velocidade = 0.0
                paradas_soco_reais_ocorridas += 1
        elif v_ech_real[i] == 0.0:
            # Parada externa preservada integralmente
            fator_velocidade = 0.0
            paradas_externas_ocorridas += 1
        else:
            # Máquina rodando no histórico:
            if b2_ativo:
                fator_velocidade = p["vel_ech_falta_critica"] / 100.0
            elif b3_ativo:
                fator_velocidade = p["vel_ech_acumulo_critico"] / 100.0
            elif has_b4 and b4_ativo and v_rot[i] < vel_nominal_ech:
                fator_velocidade = p["vel_ech_acumulo_extremo"] / 100.0
                paradas_soco_evitadas += 1
            elif has_b1 and has_v_dpl and b1_ativo and v_dpl[i] < vel_nominal_ech:
                fator_velocidade = p["vel_ech_falta_extrema"] / 100.0
                paradas_soco_evitadas += 1
            else:
                # Verificação de modo Sobremarcha (Sprint)
                sprint_ativo = False
                if fator_sobremarcha > 1.0:
                    sprint_ativo = True
                    if b2[i] <= p["gatilho_b2_falta_critica"] + (histerese + 5.0):
                        sprint_ativo = False
                    if b3[i] >= p["gatilho_b3_acumulo_critico"] - (histerese + 5.0):
                        sprint_ativo = False
                    if sprint_ativo and has_b1 and b1 is not None:
                        if b1[i] <= p["gatilho_b1_falta_extrema"] + (histerese + 5.0):
                            sprint_ativo = False
                    if sprint_ativo and has_b4 and b4 is not None:
                        if b4[i] >= p["gatilho_b4_acumulo_extremo"] - (histerese + 10.0):
                            sprint_ativo = False

                if sprint_ativo:
                    fator_velocidade = max(fator_sobremarcha, v_ech_real[i] / vel_nominal_ech)
                else:
                    fator_velocidade = v_ech_real[i] / vel_nominal_ech

            if has_b4 and b4_ativo and v_rot[i] < vel_nominal_ech:
                paradas_soco_evitadas += 1
            elif has_b1 and has_v_dpl and b1_ativo and v_dpl[i] < vel_nominal_ech:
                paradas_soco_evitadas += 1

        cph_calculado = vel_nominal_ech * fator_velocidade
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


def cma_es(
    func,
    x0,
    sigma0=1.5,
    max_iter=500,
    tol=1e-8,
    seed=42
):
    """Implementação do algoritmo CMA-ES puro (sem dependência externa)."""
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

    max_stagnation = 50
    geracoes_sem_melhora = 0
    tol_score = 1.0

    print(f"\n{'='*60}")
    print(f"  OTIMIZADOR CMA-ES  |  n={n}  λ={lam}  μ={mu}")
    print(f"  σ₀={sigma0}  max_iter={max_iter}")
    print(f"{'='*60}")

    for gen in range(max_iter):
        arz = rng.standard_normal((lam, n))
        arx = xmean + sigma * (arz @ (B * D).T)

        fitness = np.array([func(xi) for xi in arx])
        idx = np.argsort(fitness)[::-1]

        melhor_da_geracao = fitness[idx[0]]
        if melhor_da_geracao > melhor_score + tol_score:
            melhor_score = melhor_da_geracao
            melhor_x = arx[idx[0]].copy()
            geracoes_sem_melhora = 0
        elif melhor_da_geracao > melhor_score:
            melhor_score = melhor_da_geracao
            melhor_x = arx[idx[0]].copy()
            geracoes_sem_melhora += 1
        else:
            geracoes_sem_melhora += 1

        historico_scores.append(melhor_score)

        if gen % 50 == 0 or gen == max_iter - 1:
            print(f"  Geração {gen:4d} | Melhor score: {melhor_score:,.1f} | σ: {sigma:.4f} | Estagnação: {geracoes_sem_melhora}/{max_stagnation}")

        xold = xmean.copy()
        xmean = weights @ arx[idx[:mu]]

        ps = (1 - cs) * ps + np.sqrt(cs * (2 - cs) * mueff) * invsqrtC @ (xmean - xold) / sigma
        hsig = (np.linalg.norm(ps) / np.sqrt(1 - (1 - cs) ** (2 * (gen + 1))) / chiN) < (1.4 + 2 / (n + 1))
        pc = (1 - cc) * pc + hsig * np.sqrt(cc * (2 - cc) * mueff) * (xmean - xold) / sigma

        artmp = (1 / sigma) * (arx[idx[:mu]] - xold)
        C_mu = np.einsum('k,ki,kj->ij', weights, artmp, artmp)
        C = (
            (1 - c1 - cmu) * C
            + c1 * (np.outer(pc, pc) + (1 - hsig) * cc * (2 - cc) * C)
            + cmu * C_mu
        )

        sigma *= np.exp((cs / damps) * (np.linalg.norm(ps) / chiN - 1))

        if gen - eigeneval > lam / (c1 + cmu) / n / 10:
            eigeneval = gen
            C = np.triu(C) + np.triu(C, 1).T
            D, B = np.linalg.eigh(C)
            D = np.sqrt(np.maximum(D, 1e-20))
            invsqrtC = B @ np.diag(1.0 / D) @ B.T

        if sigma < tol:
            print(f"\n  ✔ Convergência atingida na geração {gen} (σ={sigma:.2e})")
            break

        if geracoes_sem_melhora >= max_stagnation:
            print(f"\n  ✔ Parada antecipada (Early Stopping) na geração {gen}: Sem melhora após {max_stagnation} gerações.")
            break

    return melhor_x, melhor_score, historico_scores


# =====================================================================
# 2. FLUXO PRINCIPAL DE EXECUÇÃO
# =====================================================================

def main():
    arquivo_config = sys.argv[1] if len(sys.argv) > 1 else "config_colunas.json"
    arquivo_csv = "dados_completos_fabrica.csv"

    # Valores padrão de fallback
    col_b1 = "accumulation_percentage_DPL_UIP_null"
    col_b2 = "accumulation_percentage_UIP_ECH_null"
    col_b3 = "accumulation_percentage_ECH_PZ_null"
    col_b4 = "accumulation_percentage_PZ_EPC_null"

    col_v_dpl = "speed_actual_cph_null_first_upstream_machine_1"
    col_v_uip = "speed_actual_cph_null_eci_1"
    col_v_ech = "speed_actual_cph_null_filler_1"
    col_v_rot = "speed_actual_cph_null_pasteurizer"
    col_v_epc = "speed_actual_cph_null_first_downstream_machine_3"

    vel_nominal_config = None
    filtro_minutos_parada_longa = 10
    fator_sobremarcha = 1.0
    limite_parada_falta = None
    limite_parada_acumulo = None
    histerese = 5.0

    if os.path.exists(arquivo_config):
        try:
            with open(arquivo_config, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                arquivo_csv = cfg.get("Arquivo_Dados", arquivo_csv)
                col_b1 = cfg.get("Col_Buffer_Antes_Entrada", col_b1)
                col_b2 = cfg.get("Col_Buffer_Entrada", col_b2)
                col_b3 = cfg.get("Col_Buffer_Saida", col_b3)
                col_b4 = cfg.get("Col_Buffer_Pos_Saida", col_b4)

                col_v_dpl = cfg.get("COL_V_Antes_Entrada", col_v_dpl)
                col_v_uip = cfg.get("COL_V_Entrada", col_v_uip)
                col_v_ech = cfg.get("COL_V_ECH", col_v_ech)
                col_v_rot = cfg.get("COL_V_Saida", col_v_rot)
                col_v_epc = cfg.get("COL_V_Entrada_Pos_Saida", col_v_epc)

                vel_nominal_config = cfg.get("Velocidade_Nominal_ECH", cfg.get("Velocidade_Nominal", None))
                filtro_minutos_parada_longa_config = cfg.get("Filtro_Minutos_Parada_Longa", None)
                if filtro_minutos_parada_longa_config is not None:
                    filtro_minutos_parada_longa = int(filtro_minutos_parada_longa_config)

                fator_sobremarcha = float(cfg.get("Fator_Sobremarcha", 1.0))
                limite_parada_falta = cfg.get("Limite_Parada_Falta", None)
                limite_parada_acumulo = cfg.get("Limite_Parada_Acumulo", None)
                histerese = float(cfg.get("Histerese", 5.0))
            print(f"➔ Configuração de colunas carregada de '{arquivo_config}'. Histerese: {histerese:.1f}%")
        except Exception as e:
            print(f"⚠️ Erro ao ler '{arquivo_config}': {e}. Usando padrões.")

    # Se não existir no diretório atual, busca relativo ao arquivo de configuração
    if not os.path.exists(arquivo_csv):
        dir_cfg = os.path.dirname(os.path.abspath(arquivo_config))
        caminho_alt = os.path.join(dir_cfg, arquivo_csv)
        if os.path.exists(caminho_alt):
            arquivo_csv = caminho_alt

    # Se ainda assim não existir CSV real, gera dados simulados
    if not os.path.exists(arquivo_csv):
        print(f"Arquivo '{arquivo_csv}' não encontrado. Gerando dados simulados...")
        linhas = 3600
        time_idx = pd.date_range(start="2026-05-29 10:00:00", periods=linhas, freq="s")
        v_epc = [52700] * linhas
        for i in range(600, 1200): v_epc[i] = 0
        v_rot = [52700] * linhas
        for i in range(700, 1200): v_rot[i] = 15000

        gen_b1 = col_b1 if col_b1 else "accumulation_percentage_DPL_UIP_null"
        gen_b2 = col_b2 if col_b2 else "accumulation_percentage_UIP_ECH_null"
        gen_b3 = col_b3 if col_b3 else "accumulation_percentage_ECH_PZ_null"
        gen_b4 = col_b4 if col_b4 else "accumulation_percentage_PZ_EPC_null"
        gen_v_dpl = col_v_dpl if col_v_dpl else "speed_actual_cph_null_first_upstream_machine_1"
        gen_v_uip = col_v_uip if col_v_uip else "speed_actual_cph_null_eci_1"
        gen_v_ech = col_v_ech if col_v_ech else "speed_actual_cph_null_filler_1"
        gen_v_rot = col_v_rot if col_v_rot else "speed_actual_cph_null_pasteurizer"
        gen_v_epc = col_v_epc if col_v_epc else "speed_actual_cph_null_first_downstream_machine_3"

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
        df_fake.to_csv(arquivo_csv, index=False)

    df = pd.read_csv(arquivo_csv)

    # Resolução de colunas
    col_b1 = resolver_coluna(df, col_b1, "accumulation_percentage_DPL_UIP_null", opcional=True)
    col_b2 = resolver_coluna(df, col_b2, "accumulation_percentage_UIP_ECH_null")
    col_b3 = resolver_coluna(df, col_b3, "accumulation_percentage_ECH_PZ_null")
    col_b4 = resolver_coluna(df, col_b4, "accumulation_percentage_PZ_EPC_null", opcional=True)

    col_v_dpl = resolver_coluna(df, col_v_dpl, "speed_actual_cph_null_first_upstream_machine_1", opcional=True)
    col_v_uip = resolver_coluna(df, col_v_uip, "speed_actual_cph_null_eci_1")
    col_v_ech = resolver_coluna(df, col_v_ech, "speed_actual_cph_null_filler_1")
    col_v_rot = resolver_coluna(df, col_v_rot, "speed_actual_cph_null_pasteurizer")
    col_v_epc = resolver_coluna(df, col_v_epc, "speed_actual_cph_null_first_downstream_machine_3", opcional=True)

    has_b1 = col_b1 is not None
    has_v_dpl = col_v_dpl is not None
    has_b4 = col_b4 is not None
    has_v_epc = col_v_epc is not None

    ativo_b1 = "ATIVO" if has_b1 else "INATIVO"
    ativo_b4 = "ATIVO" if has_b4 else "INATIVO"
    print(f"➔ Configuração dos pulmões de extremidade: B1 (Antes Entrada) = {ativo_b1} | B4 (Pós Saída) = {ativo_b4}")

    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    df.ffill(inplace=True)
    df.fillna(0.0, inplace=True)

    # Detecção do timestep
    if len(df) > 1:
        time_step_seconds = int((df["Timestamp"].iloc[1] - df["Timestamp"].iloc[0]).total_seconds())
        if time_step_seconds <= 0:
            time_step_seconds = 1
    else:
        time_step_seconds = 1

    print(f"➔ Intervalo de amostragem detectado: {time_step_seconds} segundos.")

    v_ech_real_hist = df[col_v_ech].values

    # Velocidade Nominal
    if vel_nominal_config is not None and vel_nominal_config > 0:
        vel_nominal_ech = float(vel_nominal_config)
        print(f"➔ Velocidade Nominal ECH definida pelo usuário: {vel_nominal_ech:.0f} CPH")
    else:
        vels_ativas = v_ech_real_hist[v_ech_real_hist > 1000]
        if len(vels_ativas) > 0:
            vel_nominal_ech = float(np.percentile(vels_ativas, 90))
            print(f"➔ Velocidade Nominal ECH calculada dinamicamente (p90): {vel_nominal_ech:.0f} CPH")
        else:
            vel_nominal_ech = 52700.0

    # =====================================================================
    # 3. DETECÇÃO AUTOMÁTICA DE FRONTEIRAS DE FALHA E LIMITES DE BUSCA
    # =====================================================================
    bounds_lo, bounds_hi, info_limites_auto = calcular_limites_busca_automaticos(
        df=df,
        col_v_ech=col_v_ech,
        col_b2=col_b2,
        col_b3=col_b3,
        col_b1=col_b1,
        col_b4=col_b4,
        vel_nominal=vel_nominal_ech,
        histerese=histerese
    )

    # Trava de segurança contra regressão (Fail-Safe industrial):
    if has_b4 and bounds_lo[6] < 70.0:
        raise ValueError(f"CRÍTICO: O limite inferior de busca para B4 ({bounds_lo[6]:.1f}%) não pode ser menor que 70.0% para evitar travamento da linha em 68%!")
    if histerese > 8.0:
        raise ValueError(f"CRÍTICO: Histerese de {histerese:.1f}% é excessiva. O valor seguro para evitar armadilha de estado booleano é <= 8.0%!")

    # Atualiza limites de parada física caso não configurados manualmente
    if limite_parada_falta is None:
        limite_parada_falta = info_limites_auto["limite_falta_b2"]
    if limite_parada_acumulo is None:
        limite_parada_acumulo = info_limites_auto["limite_acumulo_b3"]

    print("\n" + "="*65)
    print("📊 LIMITES DE BUSCA DINÂMICOS DETECTADOS A PARTIR DAS FALHAS:")
    print("="*65)
    print(f" ➔ B2 (Entrada):       [{bounds_lo[2]:.1f}%, {bounds_hi[2]:.1f}%] (Fronteira Falta: {info_limites_auto['limite_falta_b2']:.1f}%)")
    print(f" ➔ B3 (Saída ECH-PZ):  [{bounds_lo[4]:.1f}%, {bounds_hi[4]:.1f}%] (Fronteira Acúmulo: {info_limites_auto['limite_acumulo_b3']:.1f}%)")
    if has_b4:
        print(f" ➔ B4 (Pós PZ-EPC):    [{bounds_lo[6]:.1f}%, {bounds_hi[6]:.1f}%] (Fronteira Acúmulo: {info_limites_auto['limite_acumulo_b4']:.1f}%)")
    if has_b1:
        print(f" ➔ B1 (Antes Entrada): [{bounds_lo[0]:.1f}%, {bounds_hi[0]:.1f}%] (Fronteira Falta: {info_limites_auto['limite_falta_b1']:.1f}%)")
    print(f" ➔ Histerese Global:   {histerese:.1f}%")
    print(f" ➔ Limites Parada CLP: Falta <= {limite_parada_falta:.1f}% | Acúmulo >= {limite_parada_acumulo:.1f}%")
    print("="*65 + "\n")

    # Filtro de paradas externas longas inegociáveis
    limite_amostras_parada = int((filtro_minutos_parada_longa * 60) / time_step_seconds)
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

    print(f"➔ Filtro Parada Longa: {filtro_minutos_parada_longa}min ({limite_amostras_parada} amostras). {mascara_parada_longa.sum()} amostras inegociáveis.")

    # Ponto inicial e sigma
    x0 = (bounds_lo + bounds_hi) / 2.0
    sigma0 = 2.0

    def objetivo(x):
        p = vetor_para_params(x, bounds_lo, bounds_hi)
        score, prod, paradas_reais, paradas_ext, evitadas = simular_historico_com_regras_ia(
            df, p, time_step_seconds, mascara_parada_longa,
            col_b2, col_b3, col_v_ech, col_v_rot,
            col_b1, col_v_dpl, col_b4, col_v_epc,
            vel_nominal_ech, fator_sobremarcha,
            limite_parada_falta, limite_parada_acumulo,
            histerese
        )

        # Penalidades suaves de risco físico (baseadas na fronteira de falha real)
        margem_falta = p["gatilho_b2_falta_critica"] - limite_parada_falta
        penalidade_risco_falta = (4.0 - margem_falta) ** 2 * 1000.0 if margem_falta < 4.0 else 0.0

        margem_acumulo = limite_parada_acumulo - p["gatilho_b3_acumulo_critico"]
        penalidade_risco_acumulo = (4.0 - margem_acumulo) ** 2 * 1000.0 if margem_acumulo < 4.0 else 0.0

        penalidade_bounds = 0.0
        for i in range(len(x)):
            if x[i] < bounds_lo[i]:
                penalidade_bounds += (bounds_lo[i] - x[i]) ** 2 * 100000.0
            elif x[i] > bounds_hi[i]:
                penalidade_bounds += (x[i] - bounds_hi[i]) ** 2 * 100000.0

        return score - penalidade_risco_falta - penalidade_risco_acumulo - penalidade_bounds

    # Execução do CMA-ES
    melhor_x, melhor_score_cma, historico = cma_es(
        func=objetivo,
        x0=x0,
        sigma0=sigma0,
        max_iter=500,
        tol=1e-8,
        seed=42
    )

    melhores_parametros = vetor_para_params(melhor_x, bounds_lo, bounds_hi)

    # Coleta da simulação com a melhor parametrização
    _, v_prod, v_paradas, v_paradas_ext, v_evitadas, vel_simulada = simular_historico_com_regras_ia(
        df, melhores_parametros, time_step_seconds, mascara_parada_longa,
        col_b2, col_b3, col_v_ech, col_v_rot,
        col_b1, col_v_dpl, col_b4, col_v_epc,
        vel_nominal_ech, fator_sobremarcha,
        limite_parada_falta, limite_parada_acumulo,
        histerese,
        retornar_series=True
    )

    producao_real_historica = (df[col_v_ech].sum() / 3600.0) * time_step_seconds
    ganho_garrafas = v_prod - producao_real_historica
    ganho_percentual = (ganho_garrafas / producao_real_historica * 100) if producao_real_historica > 0 else 0.0

    b2_hist = df[col_b2].values
    b3_hist = df[col_b3].values
    vel_sim_arr = np.array(vel_simulada)

    hist_stops_total = int((v_ech_real_hist == 0.0).sum())
    hist_stops_buffer = int(((v_ech_real_hist == 0.0) & ((b2_hist <= limite_parada_falta) | (b3_hist >= limite_parada_acumulo))).sum())
    hist_stops_external = hist_stops_total - hist_stops_buffer

    sim_stops_buffer = int(((vel_sim_arr == 0.0) & ((b2_hist <= limite_parada_falta) | (b3_hist >= limite_parada_acumulo))).sum())
    sim_stops_external = int(((vel_sim_arr == 0.0) & (b2_hist > limite_parada_falta) & (b3_hist < limite_parada_acumulo)).sum())

    reducoes_velocidade_critica = int(((vel_sim_arr > 0.0) & (vel_sim_arr < vel_nominal_ech * 0.99)).sum())

    # =====================================================================
    # 4. GERAÇÃO DO RELATÓRIO TÉCNICO
    # =====================================================================
    _rel = []
    _rel.append("")
    _rel.append("="*65)
    _rel.append("   RELATÓRIO FINAL DO OTIMIZADOR: CONFIGURAÇÃO OTIMIZADA DA LINHA   ")
    _rel.append("="*65)
    _rel.append(f"➔ Produção Real Registrada no Histórico: {int(producao_real_historica)} unidades.")
    _rel.append(f"➔ Produção Simulada Otimizada : {int(v_prod)} unidades.")
    _rel.append(f"➔ GANHO DE PRODUÇÃO ESTIMADO  : +{int(ganho_garrafas)} unidades (+{ganho_percentual:.2f}%)")
    _rel.append("")
    _rel.append("[MÉTRICAS DE PARADAS DE MÁQUINA (0 CPH)]")
    _rel.append("➔ Paradas por Falta/Acúmulo (Buffers):")
    _rel.append(f"   ↳ No histórico original : {hist_stops_buffer} amostras")
    _rel.append(f"   ↳ Na simulação Otimizada : {sim_stops_buffer} amostras")
    melhoria_buffer = ((hist_stops_buffer - sim_stops_buffer) / hist_stops_buffer * 100) if hist_stops_buffer > 0 else 0.0
    _rel.append(f"   ↳ EVITADAS PELO OTIMIZADOR  : {hist_stops_buffer - sim_stops_buffer} amostras ({melhoria_buffer:.1f}% de melhoria)")
    _rel.append(f"   ↳ Amostras críticas de buffer mantidas em marcha reduzida: {reducoes_velocidade_critica} amostras")
    _rel.append("➔ Paradas por Motivos Externos (Mecânica/Operador):")
    _rel.append(f"   ↳ No histórico original : {hist_stops_external} amostras")
    _rel.append(f"   ↳ Na simulação Otimizada : {sim_stops_external} amostras")
    _rel.append("")
    _rel.append("[VELOCIDADE ALTA (100%)]")
    _rel.append(f"➔ Ação: Enchedora → 100.0% ({int(vel_nominal_ech)} CPH)")
    _rel.append("➔ Condições para rodar a 100% (Todos os pulmões ativos na faixa segura):")
    if has_b1 and has_v_dpl:
        _rel.append(f"   ↳ Nível do Pulmão DPL-UIP (Antes Entrada) > {melhores_parametros['gatilho_b1_falta_extrema'] + histerese:.1f}%")
    _rel.append(f"   ↳ Nível do Pulmão UIP-ECH (Entrada)        > {melhores_parametros['gatilho_b2_falta_critica'] + histerese:.1f}%")
    _rel.append(f"   ↳ Nível do Pulmão ECH-PZ (Saída)           < {melhores_parametros['gatilho_b3_acumulo_critico'] - histerese:.1f}%")
    if has_b4:
        _rel.append(f"   ↳ Nível do Pulmão PZ-EPC (Pós Saída)       < {melhores_parametros['gatilho_b4_acumulo_extremo'] - histerese:.1f}%")

    if fator_sobremarcha > 1.0:
        _rel.append("")
        _rel.append(f"[VELOCIDADE SPRINT ({(fator_sobremarcha*100):.1f}%)]")
        _rel.append(f"➔ Ação: Enchedora → {(fator_sobremarcha*100):.1f}% ({int(vel_nominal_ech * fator_sobremarcha)} CPH)")
        _rel.append("➔ Condições para rodar no Sprint:")
        if has_b1 and has_v_dpl:
            _rel.append(f"   ↳ Nível do Pulmão DPL-UIP > {melhores_parametros['gatilho_b1_falta_extrema'] + histerese + 5.0:.1f}%")
        _rel.append(f"   ↳ Nível do Pulmão UIP-ECH > {melhores_parametros['gatilho_b2_falta_critica'] + histerese + 5.0:.1f}%")
        _rel.append(f"   ↳ Nível do Pulmão ECH-PZ  < {melhores_parametros['gatilho_b3_acumulo_critico'] - histerese - 5.0:.1f}%")
        if has_b4:
            _rel.append(f"   ↳ Nível do Pulmão PZ-EPC  < {melhores_parametros['gatilho_b4_acumulo_extremo'] - histerese - 10.0:.1f}%")

    _rel.append("")
    _rel.append("[CADEIA DE ENTRADA - PROTEÇÃO CONTRA FALTA DE GARRAFAS]")
    contador_entrada = 1
    if has_b1 and has_v_dpl:
        _rel.append(f" {contador_entrada}. Tela Falta DPL-UIP (Extremo):")
        _rel.append(f"    ↳ Gatilho REDUZIR (Start): nível ABAIXO de {melhores_parametros['gatilho_b1_falta_extrema']:.1f}% → Ação: Enchedora → {melhores_parametros['vel_ech_falta_extrema']:.1f}% ({int(vel_nominal_ech * melhores_parametros['vel_ech_falta_extrema']/100)} CPH)")
        _rel.append(f"    ↳ Gatilho LIGAR   (Clear): nível ACIMA de {(melhores_parametros['gatilho_b1_falta_extrema'] + histerese):.1f}%")
        contador_entrada += 1

    _rel.append(f" {contador_entrada}. Tela Falta UIP-ECH (Interno):")
    _rel.append(f"    ↳ Gatilho REDUZIR (Start): nível ABAIXO de {melhores_parametros['gatilho_b2_falta_critica']:.1f}% → Ação: Enchedora → {melhores_parametros['vel_ech_falta_critica']:.1f}% ({int(vel_nominal_ech * melhores_parametros['vel_ech_falta_critica']/100)} CPH)")
    _rel.append(f"    ↳ Gatilho LIGAR   (Clear): nível ACIMA de {(melhores_parametros['gatilho_b2_falta_critica'] + histerese):.1f}%")

    _rel.append("")
    _rel.append("-"*65)
    _rel.append("[CADEIA DE SAÍDA - PROTEÇÃO CONTRA ACÚMULO / ENGARRAFAMENTO]")
    contador_saida = 1
    _rel.append(f" {contador_saida}. Tela Acúmulo ECH-PZ (Interno - Mais Próximo):")
    _rel.append(f"    ↳ Gatilho REDUZIR (Start): nível ACIMA de {melhores_parametros['gatilho_b3_acumulo_critico']:.1f}% → Ação: Enchedora → {melhores_parametros['vel_ech_acumulo_critico']:.1f}% ({int(vel_nominal_ech * melhores_parametros['vel_ech_acumulo_critico']/100)} CPH)")
    _rel.append(f"    ↳ Gatilho LIGAR   (Clear): nível ABAIXO de {(melhores_parametros['gatilho_b3_acumulo_critico'] - histerese):.1f}%")
    contador_saida += 1

    if has_b4:
        _rel.append(f"")
        _rel.append(f" {contador_saida}. Tela Acúmulo PZ-EPC (Extremo - Mais Afastado):")
        _rel.append(f"    ↳ Gatilho REDUZIR (Start): nível ACIMA de {melhores_parametros['gatilho_b4_acumulo_extremo']:.1f}% → Ação: Enchedora → {melhores_parametros['vel_ech_acumulo_extremo']:.1f}% ({int(vel_nominal_ech * melhores_parametros['vel_ech_acumulo_extremo']/100)} CPH)")
        _rel.append(f"    ↳ Gatilho LIGAR   (Clear): nível ABAIXO de {(melhores_parametros['gatilho_b4_acumulo_extremo'] - histerese):.1f}%")
        _rel.append(f"    ↳ [Recomendação]: Acionar prioritariamente quando a máquina de jusante estiver com velocidade reduzida.")
    _rel.append("="*65)
    _rel.append("Pronto! Use esses parâmetros nas suas regras de controle do CLP.")

    for linha in _rel:
        print(linha)

    import datetime as _dt
    _tag = os.path.splitext(os.path.basename(arquivo_config))[0]
    _nome_relatorio = f"relatorio_otimizador_{_tag}_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(_nome_relatorio, "w", encoding="utf-8") as _f:
        _f.write("\n".join(_rel) + "\n")
    print(f"\n➔ Relatório final salvo em '{_nome_relatorio}'.")

    # Salva JSON de parâmetros
    _dados_exportar = {
        "data_otimizacao": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Velocidade_Nominal_ECH": float(vel_nominal_ech),
        "gatilho_b1_falta_extrema": float(melhores_parametros.get("gatilho_b1_falta_extrema", 0.0)),
        "vel_ech_falta_extrema": float(melhores_parametros.get("vel_ech_falta_extrema", 0.0)),
        "gatilho_b2_falta_critica": float(melhores_parametros.get("gatilho_b2_falta_critica", 0.0)),
        "vel_ech_falta_critica": float(melhores_parametros.get("vel_ech_falta_critica", 0.0)),
        "gatilho_b3_acumulo_critico": float(melhores_parametros.get("gatilho_b3_acumulo_critico", 0.0)),
        "vel_ech_acumulo_critico": float(melhores_parametros.get("vel_ech_acumulo_critico", 0.0)),
        "gatilho_b4_acumulo_extremo": float(melhores_parametros.get("gatilho_b4_acumulo_extremo", 0.0)),
        "vel_ech_acumulo_extremo": float(melhores_parametros.get("vel_ech_acumulo_extremo", 0.0)),
        "Histerese": float(histerese),
        "Fator_Sobremarcha": float(fator_sobremarcha)
    }
    with open(f"parametros_cma_es_{_tag}.json", "w", encoding="utf-8") as _fjson:
        json.dump(_dados_exportar, _fjson, indent=2, ensure_ascii=False)
    with open("parametros_cma_es.json", "w", encoding="utf-8") as _fjson:
        json.dump(_dados_exportar, _fjson, indent=2, ensure_ascii=False)
    print(f"➔ Configurações ótimas salvas em 'parametros_cma_es_{_tag}.json' e 'parametros_cma_es.json'.")

    # Exportação de CSV comparativo e gráficos
    try:
        df_export = df.copy()
        df_export["Velocidade_Otimizada"] = vel_simulada
        nome_csv_export = f"dados_projetados_otimizado_{_tag}.csv"
        df_export.to_csv(nome_csv_export, index=False)
        print(f"➔ CSV com simulação salvo em '{nome_csv_export}'.")
    except Exception as e:
        print(f"⚠️ Erro ao salvar CSV projetado: {e}")

    # Gráficos
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        df_plot = pd.DataFrame({
            "Timestamp": df["Timestamp"],
            "Real": df[col_v_ech],
            "Otimizado": vel_simulada,
            "B2_Entrada": df[col_b2],
            "B3_Saida": df[col_b3]
        }).set_index("Timestamp")

        df_smooth = df_plot.resample("5min").mean().reset_index()
        df_smooth["Date"] = df_smooth["Timestamp"].dt.date
        dias_unicos = df_smooth["Date"].unique()

        print("\n➔ Gerando gráficos dia a dia...")
        for dia in dias_unicos:
            df_dia = df_smooth[df_smooth['Date'] == dia]
            if df_dia.empty: continue

            fig, axes = plt.subplots(2, 1, figsize=(15, 10))
            axes[0].plot(df_dia["Timestamp"], df_dia["Real"], label="Velocidade Real (5m)", color="#E74C3C", alpha=0.7, linewidth=2)
            axes[0].plot(df_dia["Timestamp"], df_dia["Otimizado"], label="Velocidade Otimizada (5m)", color="#27AE60", alpha=0.9, linewidth=2)

            if fator_sobremarcha > 1.0:
                vel_sprint = vel_nominal_ech * fator_sobremarcha
                sprint_series = df_dia["Otimizado"].where(df_dia["Otimizado"] >= vel_sprint * 0.99)
                axes[0].plot(df_dia["Timestamp"], sprint_series, color="#8E44AD", linewidth=3.0, marker=".", label="Sobremarcha Ativa")

            axes[0].set_title(f"Comparação de Velocidades da Enchedora (Dia: {dia})", fontsize=13, fontweight="bold")
            axes[0].set_ylabel("Velocidade (CPH)")
            axes[0].legend()
            axes[0].grid(True, linestyle="--", alpha=0.4)

            axes[1].plot(df_dia["Timestamp"], df_dia["B2_Entrada"], label="Buffer Entrada (B2)", color="#F39C12", linewidth=2)
            axes[1].plot(df_dia["Timestamp"], df_dia["B3_Saida"], label="Buffer Saída (B3)", color="#8E44AD", linewidth=2)
            axes[1].axhline(y=limite_parada_falta, color='r', linestyle=':', label=f"Parada Falta ({limite_parada_falta:.1f}%)")
            axes[1].axhline(y=limite_parada_acumulo, color='r', linestyle='--', label=f"Parada Acúmulo ({limite_parada_acumulo:.1f}%)")
            axes[1].set_title("Ocupação dos Buffers vs. Tempo", fontsize=13, fontweight="bold")
            axes[1].set_ylabel("Ocupação (%)")
            axes[1].set_ylim(-5, 105)
            axes[1].legend(loc="upper right")
            axes[1].grid(True, linestyle="--", alpha=0.4)

            plt.tight_layout()
            nome_arquivo = f"comparacao_velocidades_otimizado_{_tag}_{dia}.png"
            plt.savefig(nome_arquivo, dpi=150)
            plt.close(fig)
            print(f"   ↳ Salvo: {nome_arquivo}")
    except Exception as e:
        print(f"⚠️ Erro ao gerar gráfico: {e}")


if __name__ == "__main__":
    main()
