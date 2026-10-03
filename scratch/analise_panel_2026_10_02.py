import pandas as pd
import numpy as np
import json

file_path = "Panel Title-data-2026-10-02 09_12_53.csv"
df = pd.read_csv(file_path)

print("="*80)
print(f"ANÁLISE DO DATASET: {file_path}")
print("="*80)
print(f"Total de Registros: {len(df)}")
print(f"Período Inicial   : {df['Time'].iloc[0]}")
print(f"Período Final     : {df['Time'].iloc[-1]}")

# Tipos de dados e colunas
print("\n--- COLUNAS PRESENTES ---")
print(list(df.columns))

# Estatísticas de Velocidade
print("\n--- ESTATÍSTICAS DE VELOCIDADE (CPH) ---")
vel_cols = ['velocidade_real_cph', 'v_atual_cph', 'v_setpoint_cph', 'velocidade_v4_cph', 'v_in_cph', 'v_out_cph', 'v_nominal_cph']
vel_cols = [c for c in vel_cols if c in df.columns]
print(df[vel_cols].describe().round(1))

# Buffers
print("\n--- ESTATÍSTICAS DOS BUFFERS (%) ---")
buf_cols = ['b1_pct', 'b2_pct', 'b3_pct', 'b4_pct']
buf_cols = [c for c in buf_cols if c in df.columns]
print(df[buf_cols].describe().round(1))

# Verificação de Buffers Zerados / Congelados
print("\n--- ANÁLISE DE SENSORES DE BUFFER ---")
for b in buf_cols:
    zeros = (df[b] == 0).sum()
    pct_zeros = (zeros / len(df)) * 100
    nunique = df[b].nunique()
    print(f"  {b}: {zeros}/{len(df)} amostras zeradas ({pct_zeros:.1f}%) | {nunique} valores distintos | Mín: {df[b].min()}, Máx: {df[b].max()}")

# Status Operacional e Flags
print("\n--- DISTRIBUIÇÃO DE FLAGS OPERACIONAIS ---")
for col in ['status_operacional', 'maquina_ligada', 'status_maquina', 'segue_habilitado', 'modo_sombra', 'status_modulacao', 'hb_status']:
    if col in df.columns:
        print(f"\n[{col}]:")
        print(df[col].value_counts(dropna=False))

# Motivos de Modulação
print("\n--- MOTIVOS DE MODULAÇÃO (REASON CODES) ---")
if 'motivo_codigo' in df.columns and 'motivo_id' in df.columns:
    motivos = df.groupby(['motivo_id', 'motivo_codigo', 'maquina_causadora']).size().reset_index(name='contagem')
    motivos['pct_tempo'] = (motivos['contagem'] / len(df)) * 100
    print(motivos.to_string(index=False))

# Análise de Sprint
print("\n--- ANÁLISE DE SPRINT / SOBREVELOCIDADE ---")
v_nom = df['v_nominal_cph'].iloc[0] if 'v_nominal_cph' in df.columns else 90000.0
sprint_v4 = df[df['velocidade_v4_cph'] > v_nom + 10.0]
sprint_motivo_1 = df[df['motivo_id'] == 1]
print(f"Amostras com velocidade_v4_cph > nominal ({v_nom}): {len(sprint_v4)} ({len(sprint_v4)/len(df)*100:.2f}%)")
print(f"Amostras com motivo_id == 1 (SPRINT): {len(sprint_motivo_1)} ({len(sprint_motivo_1)/len(df)*100:.2f}%)")

if len(sprint_v4) > 0:
    print("\nQuando o V4 calculou Sprint:")
    print("  Velocidade Real Enchedora - Mín:", sprint_v4['velocidade_real_cph'].min(), "Méd:", sprint_v4['velocidade_real_cph'].mean(), "Máx:", sprint_v4['velocidade_real_cph'].max())
    print("  v_atual_cph               - Mín:", sprint_v4['v_atual_cph'].min(), "Méd:", sprint_v4['v_atual_cph'].mean(), "Máx:", sprint_v4['v_atual_cph'].max())
    print("  B2 médio:", sprint_v4['b2_pct'].mean(), "B3 médio:", sprint_v4['b3_pct'].mean())
    print("  V_in médio:", sprint_v4['v_in_cph'].mean(), "V_out médio:", sprint_v4['v_out_cph'].mean())
    # Verificar se Sprint acionou com máquina abaixo da nominal
    sprint_maq_rebaixada = sprint_v4[sprint_v4['v_atual_cph'] < 0.98 * v_nom]
    print(f"  --> Amostras de Sprint acionadas com Enchedora < 98% nominal: {len(sprint_maq_rebaixada)} ({len(sprint_maq_rebaixada)/len(sprint_v4)*100:.1f}%)")

# Regime da Máquina Real
print("\n--- COMPORTAMENTO DA ENCHEDORA REAL ---")
v_real = df['velocidade_real_cph']
parada = (v_real <= 0).sum()
rebaixada = ((v_real > 0) & (v_real < 0.98 * v_nom)).sum()
plena = (v_real >= 0.98 * v_nom).sum()
print(f"  Parada (0 CPH)              : {parada} amostras ({parada/len(df)*100:.1f}%) -> {parada*10/3600:.2f} horas")
print(f"  Rebaixada (< 98% de {v_nom}): {rebaixada} amostras ({rebaixada/len(df)*100:.1f}%) -> {rebaixada*10/3600:.2f} horas")
print(f"  Plena (>= 98% de {v_nom})   : {plena} amostras ({plena/len(df)*100:.1f}%) -> {plena*10/3600:.2f} horas")

# Produção integrada (base 10s por ciclo)
delta_t_h = 10.0 / 3600.0
prod_real = (df['velocidade_real_cph'] * delta_t_h).sum()
prod_v4 = (df['velocidade_v4_cph'] * delta_t_h).sum()
print("\n--- SALDO DE PRODUÇÃO (INTEGRAÇÃO DE VAZÃO) ---")
print(f"  Produção Real Estimada : {prod_real:,.0f} garrafas")
print(f"  Produção Calculada V4  : {prod_v4:,.0f} garrafas")
print(f"  Diferença (V4 - Real)  : {prod_v4 - prod_real:+,.0f} garrafas ({(prod_v4/prod_real - 1)*100:+.2f}%)")
