import pandas as pd
import numpy as np
import random
import os

import json

# =====================================================================
# 1. CONFIGURAÇÃO DOS ARQUIVOS E COLUNAS (Mapeie conforme seu CSV)
# =====================================================================
ARQUIVO_CSV = "dados_completos_fabrica.csv"
ARQUIVO_CONFIG = "config_colunas.json"

# Valores padrão de fallback
COL_B1_DPL_UIP = "accumulation_percentage_DPL_UIP_null"
COL_B2_UIP_ECH = "accumulation_percentage_UIP_ECH_null"
COL_B3_ECH_PZ  = "accumulation_percentage_ECH_PZ_null"
COL_B4_PZ_EPC  = "accumulation_percentage_PZ_EPC_null"

COL_V_DPL = "speed_actual_cph_null_first_upstream_machine_1"
COL_V_UIP = "speed_actual_cph_null_eci_1"
COL_V_ECH = "speed_actual_cph_null_filler_1"
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


# Parâmetros Físicos Nominais da Fábrica
VELOCIDADE_NOMINAL_ECH = 52700.0  # CPH Máximo da Enchedora
FILTRO_MINUTOS_PARADA_LONGA = 10  # Tempo máximo (min) antes de considerar parada inegociável
CAPACIDADE_ESTEIRAS_INTERNAS = 500  # Capacidade estimada em garrafas (B2 e B3)
CAPACIDADE_ESTEIRAS_EXTREMAS = 1000 # Capacidade estimada em garrafas (B1 e B4)

# Configurações de exportação de resultados (Opcionais)
SALVAR_CSV_COMPARATIVO = True
GERAR_GRAFICO_PLOTS    = True

# =====================================================================
# 2. GERADOR DE MASSA DE DADOS (Caso você queira testar sem o CSV real)
# =====================================================================
if not os.path.exists(ARQUIVO_CSV):
    print(f"Arquivo '{ARQUIVO_CSV}' não encontrado. Gerando dados simulados para teste...")
    linhas = 3600  # 1 hora de produção segundo a segundo
    time_idx = pd.date_range(start="2026-05-29 10:00:00", periods=linhas, freq="s")
    
    # Simula uma parada da linha de caixas (EPC) que gera efeito dominó de acúmulo
    v_epc = [speed_nominal := 52700 / 3600.0 * 3600] * linhas
    for i in range(600, 1200): v_epc[i] = 0  # EPC quebra por 10 minutos
    
    v_rot = [52700] * linhas
    for i in range(700, 1200): v_rot[i] = 15000  # ROT reduz a marcha logo em seguida

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
        gen_b3:  np.linspace(40, 95, linhas),  # Força o acúmulo no histórico
        gen_b4:  np.linspace(50, 100, pandas_placeholder := linhas), # Força o acúmulo no histórico
        gen_v_dpl: [70400] * linhas,
        gen_v_uip: [52700] * pandas_placeholder,
        gen_v_ech: [52700] * pandas_placeholder,
        gen_v_rot: v_rot,
        gen_v_epc: v_epc
    })
    df_fake.to_csv(ARQUIVO_CSV, index=False)

# Carrega a base de dados
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

# Detecção automática do time step (intervalo em segundos entre amostras)
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

# Contagem e classificação das paradas reais no histórico original
v_ech_real_hist = df[COL_V_ECH].values

# FIX: Calcular a Velocidade Nominal Dinamicamente (P90 das velocidades ativas)
if 'VELOCIDADE_NOMINAL_CONFIG' in locals() and VELOCIDADE_NOMINAL_CONFIG is not None and VELOCIDADE_NOMINAL_CONFIG > 0:
    VELOCIDADE_NOMINAL_ECH = float(VELOCIDADE_NOMINAL_CONFIG)
    print(f"➔ Velocidade Nominal ECH definida pelo usuário: {VELOCIDADE_NOMINAL_ECH:.0f} CPH")
else:
    vels_ativas = v_ech_real_hist[v_ech_real_hist > 1000]
    if len(vels_ativas) > 0:
        VELOCIDADE_NOMINAL_ECH = float(np.percentile(vels_ativas, 90))
        print(f"➔ Velocidade Nominal ECH calculada dinamicamente (p90): {VELOCIDADE_NOMINAL_ECH:.0f} CPH")
    else:
        print(f"⚠ Não foram encontradas velocidades válidas. Mantendo nominal em {VELOCIDADE_NOMINAL_ECH:.0f} CPH")

if 'FILTRO_MINUTOS_PARADA_LONGA_CONFIG' in locals() and FILTRO_MINUTOS_PARADA_LONGA_CONFIG is not None:
    FILTRO_MINUTOS_PARADA_LONGA = int(FILTRO_MINUTOS_PARADA_LONGA_CONFIG)


b2_hist = df[COL_B2_UIP_ECH].values
b3_hist = df[COL_B3_ECH_PZ].values

hist_stops_total = int((v_ech_real_hist == 0.0).sum())
hist_stops_buffer = int(((v_ech_real_hist == 0.0) & ((b2_hist <= 15.0) | (b3_hist >= 85.0))).sum())
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
# 3. MOTOR DO GÊMEO DIGITAL (Simula o passado com as novas regras da IA)
# =====================================================================
def simular_historico_com_regras_ia(dados_df, p, time_step, mascara_parada, retornar_series=False):
    """
    Roda o histórico aplicando os parâmetros dinâmicos 'p' gerados pela IA
    e calcula a eficiência matemática final daquele cenário com base na lógica de histerese.
    """
    # Conversão para arrays numpy para máxima velocidade de processamento
    b2 = dados_df[COL_B2_UIP_ECH].values
    b3 = dados_df[COL_B3_ECH_PZ].values
    
    v_uip = dados_df[COL_V_UIP].values
    v_rot = dados_df[COL_V_ROT].values
    v_ech_real = dados_df[COL_V_ECH].values
    
    b1 = dados_df[COL_B1_DPL_UIP].values if HAS_B1 else None
    v_dpl = dados_df[COL_V_DPL].values if HAS_V_DPL else None
    
    b4 = dados_df[COL_B4_PZ_EPC].values if HAS_B4 else None
    v_epc = dados_df[COL_V_EPC].values if HAS_V_EPC else None
    
    producao_total_simulada = 0.0
    paradas_soco_evitadas = 0
    paradas_soco_reais_ocorridas = 0
    paradas_externas_ocorridas = 0
    mudancas_velocidade = 0
    ultima_velocidade_fator = 1.0
    
    # Estados de ativação com Histerese (memória)
    b1_ativo = False
    b2_ativo = False
    b3_ativo = False
    b4_ativo = False
    
    velocidades_simuladas = []
    
    for i in range(len(dados_df)):
        # Atualização dos estados de gatilho com histerese
        
        # B2: Falta crítica UIP-ECH (Interno Entrada) -> Libera com +10%
        if b2[i] <= p["gatilho_b2_falta_critica"]:
            b2_ativo = True
        elif b2[i] > p["gatilho_b2_falta_critica"] + 10.0:
            b2_ativo = False
            
        # B3: Acúmulo crítico ECH-PZ (Interno Saída) -> Libera com -10%
        if b3[i] >= p["gatilho_b3_acumulo_critico"]:
            b3_ativo = True
        elif b3[i] < p["gatilho_b3_acumulo_critico"] - 10.0:
            b3_ativo = False
            
        # B4: Acúmulo extremo PZ-EPC (Extremo Saída) -> Libera com -15%
        if HAS_B4 and b4 is not None:
            if b4[i] >= p["gatilho_b4_acumulo_extremo"]:
                b4_ativo = True
            elif b4[i] < p["gatilho_b4_acumulo_extremo"] - 15.0:
                b4_ativo = False
        else:
            b4_ativo = False
            
        # B1: Falta extrema DPL-UIP (Extremo Entrada) -> Libera com +10%
        if HAS_B1 and b1 is not None:
            if b1[i] <= p["gatilho_b1_falta_extrema"]:
                b1_ativo = True
            elif b1[i] > p["gatilho_b1_falta_extrema"] + 10.0:
                b1_ativo = False
        else:
            b1_ativo = False

        # Condição Física Real do histórico: Se o cano entupiu de verdade, a enchedora parou
        if mascara_parada[i]:
            fator_velocidade = 0.0
            paradas_externas_ocorridas += 1
        elif b2[i] <= 2.0 or b3[i] >= 99.0:
            fator_velocidade = 0.0
            paradas_soco_reais_ocorridas += 1
        elif v_ech_real[i] == 0.0 and b2[i] > 15.0 and b3[i] < 85.0:
            # Parada externa detectada (manutenção, operador, quebra mecânica etc.)
            # A IA não tem controle sobre isso, então a simulação replica a parada.
            fator_velocidade = 0.0
            paradas_externas_ocorridas += 1
        else:
            # A IA entra em ação cruzando BUFFERS + VELOCIDADES das outras máquinas
            fator_velocidade = 1.0
            
            # Camada 1: Alerta Crítico por Falta na Entrada (UIP_ECH)
            if b2_ativo:
                fator_velocidade = p["vel_ech_falta_critica"] / 100.0
                
            # Camada 2: Alerta Crítico por Acúmulo na Saída (ECH_PZ)
            elif b3_ativo:
                fator_velocidade = p["vel_ech_acumulo_critico"] / 100.0
                
            # Camada 3: ANTECIPAÇÃO Inteligente pela velocidade da Rotuladora e Buffer Extremo (PZ_EPC)
            elif HAS_B4 and b4_ativo and v_rot[i] < VELOCIDADE_NOMINAL_ECH:
                fator_velocidade = p["vel_ech_acumulo_extremo"] / 100.0
                paradas_soco_evitadas += 1
                
            # Camada 4: ANTECIPAÇÃO Inteligente pela velocidade da Despaletizadora e Buffer Extremo (DPL_UIP)
            elif HAS_B1 and HAS_V_DPL and b1_ativo and v_dpl[i] < VELOCIDADE_NOMINAL_ECH:
                fator_velocidade = p["vel_ech_falta_extrema"] / 100.0
                paradas_soco_evitadas += 1

        # Acumula a produção real simulada naquele período
        cph_calculado = VELOCIDADE_NOMINAL_ECH * fator_velocidade
        producao_total_simulada += (cph_calculado / 3600.0) * time_step
        if retornar_series:
            velocidades_simuladas.append(cph_calculado)
        
        # Contabiliza penalidade por oscilação (efeito chicote no motor)
        if fator_velocidade != ultima_velocidade_fator:
            mudancas_velocidade += 1
            ultima_velocidade_fator = fator_velocidade
            
    # EQUAÇÃO DA FUNÇÃO OBJETIVO (A nota que a IA quer maximizar)
    # Aumentamos a penalidade de paradas físicas e oscilações para estabilização
    score_fitness = producao_total_simulada - (paradas_soco_reais_ocorridas * 150) - (mudancas_velocidade * 0.25)
    
    if retornar_series:
        return score_fitness, producao_total_simulada, paradas_soco_reais_ocorridas, paradas_externas_ocorridas, paradas_soco_evitadas, velocidades_simuladas
    return score_fitness, producao_total_simulada, paradas_soco_reais_ocorridas, paradas_externas_ocorridas, paradas_soco_evitadas

# =====================================================================
# 4. ALGORITMO GENÉTICO / ESPAÇO DE BUSCA DA IA
# =====================================================================
print("Iniciando Otimização Multivariável Inteligente...")
print("Cruzando velocidades de todas as máquinas com níveis de acúmulo...")

melhor_score = -float('inf')
melhores_parametros = {}
v_prod, v_paradas, v_paradas_ext, v_evitadas = 0, 0, 0, 0

# Fixa a semente aleatória para garantir resultados repetíveis/idênticos em cada execução
random.seed(42)

# A IA vai testar 1000 combinações diferentes de forma evolutiva
for geracao in range(1000):
    proposta_ia = {
        # Regras de Falta (Entrada)
        "gatilho_b1_falta_extrema": random.uniform(30.0, 45.0),
        "vel_ech_falta_extrema":     random.uniform(85.0, 95.0), # Redução suave
        
        "gatilho_b2_falta_critica": random.uniform(15.0, 25.0),
        "vel_ech_falta_critica":     random.uniform(70.0, 85.0), # Redução forte
        
        # Regras de Acúmulo (Saída)
        "gatilho_b3_acumulo_critico": random.uniform(75.0, 88.0),
        "vel_ech_acumulo_critico":    random.uniform(70.0, 85.0), # Redução forte
        
        "gatilho_b4_acumulo_extremo": random.uniform(70.0, 80.0),
        "vel_ech_acumulo_extremo":    random.uniform(85.0, 95.0)  # Redução suave
    }
    
    # Roda a simulação matemática baseada nas velocidades do seu CSV
    score, prod, paradas_criticas, paradas_ext, paradas_salvas = simular_historico_com_regras_ia(df, proposta_ia, time_step_seconds, mascara_parada_longa)
    
    # Seleção natural: guarda apenas a combinação mais eficiente de todas
    if score > melhor_score:
        melhor_score = score
        melhores_parametros = proposta_ia
        v_prod = prod
        v_paradas = paradas_criticas
        v_paradas_ext = paradas_ext
        v_evitadas = paradas_salvas

# Roda a simulação final coletando a série temporal das velocidades simuladas
_, _, _, _, _, vel_simulada = simular_historico_com_regras_ia(
    df, melhores_parametros, time_step_seconds, mascara_parada_longa, retornar_series=True
)

# Calcula a produção real contida no histórico original para comparação
producao_real_historica = (df[COL_V_ECH].sum() / 3600.0) * time_step_seconds
ganho_garrafas = v_prod - producao_real_historica
ganho_percentual = (ganho_garrafas / producao_real_historica * 100) if producao_real_historica > 0 else 0.0

# =====================================================================
# 5. IMPRESSÃO DO RELATÓRIO DE CONFIGURAÇÃO DO SUPERVISÓRIO
# =====================================================================
print("\n" + "="*65)
print("   RELATÓRIO FINAL DA IA: CONFIGURAÇÃO OTIMIZADA DA LINHA   ")
print("="*65)
print(f"➔ Produção Real Registrada no Histórico: {int(producao_real_historica)} unidades.")
print(f"➔ Produção Simulada Otimizada com IA  : {int(v_prod)} unidades.")
if ganho_garrafas > 0:
    print(f"➔ GANHO DE PRODUÇÃO ESTIMADO COM A IA  : +{int(ganho_garrafas)} unidades (+{ganho_percentual:.2f}%)")
else:
    print(f"➔ GANHO DE PRODUÇÃO ESTIMADO COM A IA  : 0 unidades (A linha já rodou de forma ótima)")

# Contabilização real das paradas simuladas (quando a velocidade simulada é de fato zero)
vel_sim_arr = np.array(vel_simulada)
sim_stops_buffer = int(((vel_sim_arr == 0.0) & ((b2_hist <= 15.0) | (b3_hist >= 85.0))).sum())
sim_stops_external = int(((vel_sim_arr == 0.0) & (b2_hist > 15.0) & (b3_hist < 85.0)).sum())

# Contabilização de amostras em nível crítico de buffer onde a parada foi evitada reduzindo a velocidade
criticos_evitados = int(((df[COL_B2_UIP_ECH] <= 2.0) | (df[COL_B3_ECH_PZ] >= 99.0)).sum() - sim_stops_buffer)

print("\n[MÉTRICAS DE PARADAS DE MÁQUINA (0 CPH)]")
print(f"➔ Paradas por Falta/Acúmulo (Buffers):")
print(f"   ↳ No histórico original : {hist_stops_buffer} amostras")
print(f"   ↳ Na simulação com IA   : {sim_stops_buffer} amostras")
reducao = hist_stops_buffer - sim_stops_buffer
print(f"   ↳ EVITADAS PELA IA      : {reducao} amostras ({(reducao/max(1,hist_stops_buffer)*100):.1f}% de melhoria)")
print(f"   ↳ Amostras críticas de buffer mantidas em marcha reduzida: {criticos_evitados} amostras")
print(f"➔ Paradas por Motivos Externos (Mecânica/Operador):")
print(f"   ↳ No histórico original : {hist_stops_external} amostras")
print(f"   ↳ Na simulação com IA   : {sim_stops_external} amostras")

print("\n[VELOCIDADE ALTA (100%)]")
print(f"➔ Ação: Enchedora → 100.0% ({int(VELOCIDADE_NOMINAL_ECH)} CPH)")
print("➔ Condições para rodar a 100% (Todos os pulmões ativos na faixa segura):")
if HAS_B1 and HAS_V_DPL:
    print(f"   ↳ Nível do Pulmão DPL-UIP (Antes Entrada) > {(melhores_parametros['gatilho_b1_falta_extrema'] + 10.0):.1f}%")
print(f"   ↳ Nível do Pulmão UIP-ECH (Entrada)        > {(melhores_parametros['gatilho_b2_falta_critica'] + 10.0):.1f}%")
print(f"   ↳ Nível do Pulmão ECH-PZ (Saída)           < {(melhores_parametros['gatilho_b3_acumulo_critico'] - 10.0):.1f}%")
if HAS_B4:
    print(f"   ↳ Nível do Pulmão PZ-EPC (Pós Saída)       < {(melhores_parametros['gatilho_b4_acumulo_extremo'] - 15.0):.1f}%")

print("\n[CADEIA DE ENTRADA - PROTEÇÃO CONTRA FALTA DE GARRAFAS]")
contador_entrada = 1
if HAS_B1 and HAS_V_DPL:
    print(f" {contador_entrada}. Tela Falta DPL-UIP (Extremo):")
    print(f"    ↳ Gatilho REDUZIR (Start): nível ABAIXO de {melhores_parametros['gatilho_b1_falta_extrema']:.1f}% → Ação: Enchedora → {melhores_parametros['vel_ech_falta_extrema']:.1f}% ({int(VELOCIDADE_NOMINAL_ECH * melhores_parametros['vel_ech_falta_extrema']/100)} CPH)")
    print(f"    ↳ Gatilho LIGAR   (Clear): nível ACIMA de {(melhores_parametros['gatilho_b1_falta_extrema'] + 10.0):.1f}%")
    contador_entrada += 1

print(f"\n {contador_entrada}. Tela Falta UIP-ECH (Interno):")
print(f"    ↳ Gatilho REDUZIR (Start): nível ABAIXO de {melhores_parametros['gatilho_b2_falta_critica']:.1f}% → Ação: Enchedora → {melhores_parametros['vel_ech_falta_critica']:.1f}% ({int(VELOCIDADE_NOMINAL_ECH * melhores_parametros['vel_ech_falta_critica']/100)} CPH)")
print(f"    ↳ Gatilho LIGAR   (Clear): nível ACIMA de {(melhores_parametros['gatilho_b2_falta_critica'] + 10.0):.1f}%")

print("\n" + "-"*65)
print("[CADEIA DE SAÍDA - PROTEÇÃO CONTRA ACÚMULO / ENGARRAFAMENTO]")
contador_saida = 1
print(f" {contador_saida}. Tela Acúmulo ECH-PZ (Interno - Mais Próximo):")
print(f"    ↳ Gatilho REDUZIR (Start): nível ACIMA de {melhores_parametros['gatilho_b3_acumulo_critico']:.1f}% → Ação: Enchedora → {melhores_parametros['vel_ech_acumulo_critico']:.1f}% ({int(VELOCIDADE_NOMINAL_ECH * melhores_parametros['vel_ech_acumulo_critico']/100)} CPH)")
print(f"    ↳ Gatilho LIGAR   (Clear): nível ABAIXO de {(melhores_parametros['gatilho_b3_acumulo_critico'] - 10.0):.1f}%")
contador_saida += 1

if HAS_B4:
    print(f"\n {contador_saida}. Tela Acúmulo PZ-EPC (Extremo - Mais Afastado):")
    print(f"    ↳ Gatilho REDUZIR (Start): nível ACIMA de {melhores_parametros['gatilho_b4_acumulo_extremo']:.1f}% → Ação: Enchedora → {melhores_parametros['vel_ech_acumulo_extremo']:.1f}% ({int(VELOCIDADE_NOMINAL_ECH * melhores_parametros['vel_ech_acumulo_extremo']/100)} CPH)")
    print(f"    ↳ Gatilho LIGAR   (Clear): nível ABAIXO de {(melhores_parametros['gatilho_b4_acumulo_extremo'] - 15.0):.1f}%")
print("="*65)
print("Pronto! Digite esses parâmetros nas suas regras de controle para estabilizar a linha.")

# =====================================================================
# 6. EXPORTAÇÃO DO CSV COMPARATIVO E GRÁFICO (OPCIONAL)
# =====================================================================
if SALVAR_CSV_COMPARATIVO:
    df_comparado = pd.DataFrame({
        "Timestamp": df["Timestamp"],
        "Velocidade_Real_Enchedora": df[COL_V_ECH],
        "Velocidade_Simulada_IA": vel_simulada,
        "Buffer_B2_UIP_ECH": df[COL_B2_UIP_ECH],
        "Buffer_B3_ECH_PZ": df[COL_B3_ECH_PZ]
    })
    df_comparado.to_csv("dados_projetados_comparados.csv", index=False)
    print("\n➔ Arquivo CSV comparativo salvo em 'dados_projetados_comparados.csv'.")

if GERAR_GRAFICO_PLOTS:
    try:
        import matplotlib.pyplot as plt
        
        # Criamos um DataFrame de plotagem temporário com índice de data
        df_plot = pd.DataFrame({
            "Timestamp": df["Timestamp"],
            "Real": df[COL_V_ECH],
            "IA": vel_simulada
        }).set_index("Timestamp")
        
        # Agrupamos os dados por média de 15 minutos para eliminar o ruído visual
        df_smooth = df_plot.resample("15Min").mean().reset_index()
        
        plt.figure(figsize=(15, 6))
        
        # Plota a velocidade média suavizada em 15 minutos
        plt.plot(df_smooth["Timestamp"], df_smooth["Real"], label="Velocidade Média Real (15m)", color="#E74C3C", alpha=0.7, linewidth=2)
        plt.plot(df_smooth["Timestamp"], df_smooth["IA"], label="Velocidade Média IA (15m)", color="#2980B9", alpha=0.9, linewidth=2)
        
        # Estilização do gráfico
        plt.title("Comparação de Velocidades da Enchedora (Suavizada em Médias de 15 minutos)", fontsize=14, fontweight='bold', pad=15)
        plt.xlabel("Tempo (Data/Hora)", fontsize=12)
        plt.ylabel("Velocidade Média (CPH)", fontsize=12)
        plt.grid(True, linestyle="--", alpha=0.5)
        plt.legend(fontsize=11, loc="upper right")
        
        plt.xticks(rotation=15)
        plt.tight_layout()
        
        plt.savefig("comparacao_velocidades.png", dpi=150)
        print("➔ Gráfico comparativo (suavizado em 15min) gerado e salvo em 'comparacao_velocidades.png'.")
    except Exception as e:
        print(f"⚠️ Erro ao gerar o gráfico: {e}")
