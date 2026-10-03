import pandas as pd
import numpy as np
import sys
import os

# Adiciona o caminho do projeto para importar a nova funcao_controle_v4
sys.path.insert(0, os.path.abspath("Controle_Velocidade_4"))
from funcao_controle_v4 import ControladorVelocidadeV4

file_path = "Panel Title-data-2026-10-02 09_12_53.csv"
df = pd.read_csv(file_path)

print("="*80)
print("ANÁLISE DETALHADA DA OPERAÇÃO REAL E SIMULAÇÃO COM A NOVA TRAVA DE SPRINT")
print("="*80)

# 1. Análise dos Patamares de Velocidade Real da Enchedora
v_real = df['velocidade_real_cph']
print("\n--- PATAMARES DE VELOCIDADE REAL DA ENCHEDORA (QUANDO LIGADA > 0 CPH) ---")
v_rodando = v_real[v_real > 1000]
top_vels = v_rodando.round(-2).value_counts().head(10)
for vel, count in top_vels.items():
    pct = (count / len(df)) * 100
    pct_tempo_rodando = (count / len(v_rodando)) * 100
    print(f"  {vel:6.0f} CPH ({vel/90000.0*100:5.1f}% nominal): {count:4d} amostras ({pct:4.1f}% do dia | {pct_tempo_rodando:4.1f}% do tempo rodando)")

# 2. Investigação do Sprint no CSV gravado (Antigo, sem a trava)
sprint_antigo = df[df['motivo_id'] == 1]
print(f"\n--- SPRINT NO CSV GRAVADO (VERSÃO ANTERIOR SEM TRAVA) ---")
print(f"Total de ciclos em Sprint gravados: {len(sprint_antigo)} ({len(sprint_antigo)*10/60:.1f} minutos)")
print("Distribuição da velocidade REAL da máquina durante esses Sprints:")
print(f"  Parada (0 CPH)                      : {(sprint_antigo['velocidade_real_cph'] == 0).sum()} ciclos")
print(f"  Rebaixada entre 1k e 80k CPH        : {((sprint_antigo['velocidade_real_cph'] > 0) & (sprint_antigo['velocidade_real_cph'] < 80000)).sum()} ciclos")
print(f"  Rebaixada ~85k CPH (80k a 88.2k CPH): {((sprint_antigo['velocidade_real_cph'] >= 80000) & (sprint_antigo['velocidade_real_cph'] < 88200)).sum()} ciclos")
print(f"  Plena nominal (>= 88.2k CPH)        : {(sprint_antigo['velocidade_real_cph'] >= 88200).sum()} ciclos")

# 3. Simulação ciclo a ciclo com a NOVA Função de Controle V4 (com a trava de Sprint)
print("\n--- SIMULAÇÃO DO DIA COMPLETO COM A NOVA TRAVA DE SPRINT ---")
ctrl_novo = ControladorVelocidadeV4(
    velocidade_nominal=90000,
    v_atual_inicial=float(df['velocidade_real_cph'].iloc[0])
)

vel_novas = []
motivos_novos = []
sprint_ativos_novo = []

for idx, row in df.iterrows():
    b1 = row['b1_pct']
    b2 = row['b2_pct']
    b3 = row['b3_pct']
    b4 = row['b4_pct']
    vin = row['v_in_cph']
    vout = row['v_out_cph']
    v_real_atual = row['velocidade_real_cph']
    
    # Se a máquina real estiver parada (status_maquina == False ou v_real == 0)
    # No cliente OPC real, status_maquina modula ou mantem setpoint
    v_calc, m_id = ctrl_novo.calcular_velocidade(
        b1=b1, b2=b2, b3=b3, b4=b4,
        v_in=vin, v_out=vout,
        v_atual=v_real_atual,  # <-- Passando velocidade real medida com a TRAVA!
        delta_t_s=10.0,
        retornar_motivo=True
    )
    vel_novas.append(v_calc)
    motivos_novos.append(m_id)
    sprint_ativos_novo.append(ctrl_novo.sprint_ativo)

df['v_nova_calc'] = vel_novas
df['motivo_novo'] = motivos_novos
df['sprint_novo'] = sprint_ativos_novo

sprint_novo_count = sum(df['sprint_novo'])
sprint_novo_motivo = sum(df['motivo_novo'] == 1)

print(f"Total de ciclos em Sprint com a NOVA TRAVA: {sprint_novo_count} ({sprint_novo_count*10/60:.1f} minutos)")
print(f"Total com motivo_id == 1 (Sprint): {sprint_novo_motivo}")

sprint_novos_df = df[df['sprint_novo']]
if len(sprint_novos_df) > 0:
    print("Distribuição da velocidade REAL durante o Sprint na nova versão:")
    print(f"  Parada (0 CPH)              : {(sprint_novos_df['velocidade_real_cph'] == 0).sum()} ciclos")
    print(f"  Rebaixada (< 88.2k CPH)     : {(sprint_novos_df['velocidade_real_cph'] < 88200).sum()} ciclos")
    print(f"  Plena nominal (>= 88.2k CPH): {(sprint_novos_df['velocidade_real_cph'] >= 88200).sum()} ciclos")

# Comparação de Produção
delta_t_h = 10.0 / 3600.0
prod_real = (df['velocidade_real_cph'] * delta_t_h).sum()
prod_v4_gravado = (df['velocidade_v4_cph'] * delta_t_h).sum()
prod_v4_novo = (df['v_nova_calc'] * delta_t_h).sum()

print("\n--- COMPARAÇÃO DE PRODUÇÃO (GARRAFAS EM 24H) ---")
print(f"  Produção Real da Linha           : {prod_real:,.0f} garrafas")
print(f"  Produção V4 Anterior (sem trava) : {prod_v4_gravado:,.0f} garrafas (+{prod_v4_gravado - prod_real:,.0f} gf)")
print(f"  Produção V4 Nova (com trava)     : {prod_v4_novo:,.0f} garrafas (+{prod_v4_novo - prod_real:,.0f} gf)")

# Análise dos motivos na nova versão
print("\n--- DISTRIBUIÇÃO DE MOTIVOS NA NOVA VERSÃO COM A TRAVA ---")
m_comp = df.groupby(['motivo_novo']).size().reset_index(name='contagem')
m_comp['pct'] = (m_comp['contagem'] / len(df)) * 100
for idx, row in m_comp.iterrows():
    m_id = row['motivo_novo']
    info = ctrl_novo.obter_motivo(m_id)
    print(f"  ID {m_id:2d} - {info['codigo']:<30}: {row['contagem']:4d} amostras ({row['pct']:5.1f}%)")
