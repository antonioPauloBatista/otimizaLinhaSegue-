import pandas as pd
import numpy as np

file_path = "Panel Title-data-2026-10-02 09_12_53.csv"
df = pd.read_csv(file_path)

dt_h = 10.0 / 3600.0  # 10 segundos em horas

v_real = df['velocidade_real_cph']
v_v4 = df['velocidade_v4_cph']

# 1. Total Geral Integrado
prod_real_total = (v_real * dt_h).sum()
prod_v4_total = (v_v4 * dt_h).sum()
saldo_total = prod_v4_total - prod_real_total
pct_total = (saldo_total / prod_real_total) * 100

print("="*80)
print("AUDITORIA COMPLETA DE PRODUÇÃO: SE O SEGUE PRODUZIU MAIS OU NÃO")
print("="*80)
print(f"Período: 24 horas ({len(df)} ciclos de 10s)")
print(f"Produção Real da Fábrica      : {prod_real_total:,.1f} garrafas")
print(f"Produção Calculada pelo Segue : {prod_v4_total:,.1f} garrafas")
print(f"Saldo Total                   : {saldo_total:+,.1f} garrafas ({pct_total:+.2f}%)")

# 2. Decomposição: Quando a máquina real estava LIGADA vs PARADA
mask_real_parada = (v_real == 0)
mask_real_rodando = (v_real > 0)

tempo_real_parada_min = mask_real_parada.sum() * 10 / 60
tempo_real_rodando_min = mask_real_rodando.sum() * 10 / 60

print("\n--- DECOMPOSIÇÃO POR ESTADO DA ENCHEDORA REAL ---")
print(f"Tempo Real Parada  : {tempo_real_parada_min:.1f} minutos ({mask_real_parada.sum()} ciclos | {mask_real_parada.sum()/len(df)*100:.1f}%)")
print(f"Tempo Real Rodando : {tempo_real_rodando_min:.1f} minutos ({mask_real_rodando.sum()} ciclos | {mask_real_rodando.sum()/len(df)*100:.1f}%)")

# 3. Durante as PARADAS REAIS da enchedora:
df_parada = df[mask_real_parada]
prod_v4_durante_parada = (df_parada['velocidade_v4_cph'] * dt_h).sum()
ciclos_v4_tentou_rodar = (df_parada['velocidade_v4_cph'] > 0).sum()
ciclos_v4_parou_junto = (df_parada['velocidade_v4_cph'] == 0).sum()

print("\n--- COMPORTAMENTO DO SEGUE DURANTE AS PARADAS REAIS (v_real == 0) ---")
print(f"Ciclos em que o Segue também PAROU (0 CPH) : {ciclos_v4_parou_junto} ciclos")
print(f"Ciclos em que o Segue MANTEVE RODANDO      : {ciclos_v4_tentou_rodar} ciclos")
print(f"Garrafas geradas pelo Segue na parada real : {prod_v4_durante_parada:,.1f} garrafas")

# Analisar por que a máquina real parou nesses ciclos:
# Se B2 <= 10 ou B3 >= 90 -> Parada por buffer (evitável pelo Segue)
# Se B2 > 10 e B3 < 90 -> Parada própria / mecânica da enchedora
mask_parada_buffer = (df_parada['b2_pct'] <= 10.0) | (df_parada['b3_pct'] >= 90.0)
mask_parada_propria = ~mask_parada_buffer

print(f"  ↳ Paradas Reais causadas por BUFFER (B2<=10% ou B3>=90%) : {mask_parada_buffer.sum()} ciclos ({mask_parada_buffer.sum()*10/60:.1f} min)")
print(f"  ↳ Paradas Reais PRÓPRIAS da Enchedora (Buffers OK)       : {mask_parada_propria.sum()} ciclos ({mask_parada_propria.sum()*10/60:.1f} min)")

prod_evitavel_buffer = (df_parada[mask_parada_buffer]['velocidade_v4_cph'] * dt_h).sum()
prod_parada_propria = (df_parada[mask_parada_propria]['velocidade_v4_cph'] * dt_h).sum()
print(f"  ↳ Garrafas extras do Segue que EVITARIAM parada de buffer: {prod_evitavel_buffer:,.1f} garrafas (GANHO REAL)")
print(f"  ↳ Garrafas em paradas próprias da máquina (Buffers OK)   : {prod_parada_propria:,.1f} garrafas (Depende de intervenção física)")

# 4. Durante os períodos em que a máquina real estava RODANDO (v_real > 0):
df_rodando = df[mask_real_rodando]
prod_real_rodando = (df_rodando['velocidade_real_cph'] * dt_h).sum()
prod_v4_rodando = (df_rodando['velocidade_v4_cph'] * dt_h).sum()
saldo_rodando = prod_v4_rodando - prod_real_rodando

print("\n--- COMPORTAMENTO DO SEGUE COM A MÁQUINA RODANDO (v_real > 0) ---")
print(f"Produção Real com máquina rodando : {prod_real_rodando:,.1f} garrafas")
print(f"Produção Segue com máquina rodando: {prod_v4_rodando:,.1f} garrafas")
print(f"Saldo com máquina rodando         : {saldo_rodando:+,.1f} garrafas ({saldo_rodando/prod_real_rodando*100:+.2f}%)")

# Quando o Segue produziu MAIS vs MENOS enquanto a máquina rodava:
segue_mais = df_rodando[df_rodando['velocidade_v4_cph'] > df_rodando['velocidade_real_cph']]
segue_menos = df_rodando[df_rodando['velocidade_v4_cph'] < df_rodando['velocidade_real_cph']]
segue_igual = df_rodando[df_rodando['velocidade_v4_cph'] == df_rodando['velocidade_real_cph']]

print(f"  ↳ Ciclos em que Segue pediu MAIS velocidade : {len(segue_mais)} ciclos (+{( (segue_mais['velocidade_v4_cph'] - segue_mais['velocidade_real_cph']) * dt_h ).sum():,.1f} gf)")
print(f"  ↳ Ciclos em que Segue pediu MENOS velocidade: {len(segue_menos)} ciclos (-{( (segue_menos['velocidade_real_cph'] - segue_menos['velocidade_v4_cph']) * dt_h ).sum():,.1f} gf)")
print(f"  ↳ Ciclos em que velocidades foram IGUAIS   : {len(segue_igual)} ciclos")

# 5. O papel do SPRINT no ganho gravado:
sprint_df = df[df['motivo_id'] == 1]
garrafas_geradas_sprint_v4 = (sprint_df['velocidade_v4_cph'] * dt_h).sum()
garrafas_real_mesmo_periodo = (sprint_df['velocidade_real_cph'] * dt_h).sum()
saldo_sprint = garrafas_geradas_sprint_v4 - garrafas_real_mesmo_periodo

print("\n--- O PAPEL DO SPRINT (SOBREVELOCIDADE) NO RESULTADO ---")
print(f"Ciclos em Modo Sprint (92.700 CPH) : {len(sprint_df)} ciclos ({len(sprint_df)*10/60:.1f} min)")
print(f"Produção V4 durante o Sprint       : {garrafas_geradas_sprint_v4:,.1f} garrafas")
print(f"Produção Real no mesmo período     : {garrafas_real_mesmo_periodo:,.1f} garrafas")
print(f"Saldo gerado pelo Sprint           : {saldo_sprint:+,.1f} garrafas")
print(f"Proporção do saldo total do Segue  : {(saldo_sprint / saldo_total)*100:.1f}% do ganho total de 32k garrafas veio do Sprint!")

# 6. E se a nova trava estivesse ativa? (Sem o Sprint indevido com máquina rebaixada a 85k)
# Na simulação com a trava:
import sys, os
sys.path.insert(0, os.path.abspath("Controle_Velocidade_4"))
from funcao_controle_v4 import ControladorVelocidadeV4
ctrl_novo = ControladorVelocidadeV4(velocidade_nominal=90000, v_atual_inicial=float(v_real.iloc[0]))
vel_com_trava = []
for idx, row in df.iterrows():
    v, _ = ctrl_novo.calcular_velocidade(
        b1=row['b1_pct'], b2=row['b2_pct'], b3=row['b3_pct'], b4=row['b4_pct'],
        v_in=row['v_in_cph'], v_out=row['v_out_cph'], v_atual=row['velocidade_real_cph'],
        delta_t_s=10.0, retornar_motivo=True
    )
    vel_com_trava.append(v)

prod_v4_com_trava = (pd.Series(vel_com_trava) * dt_h).sum()
print("\n--- CENÁRIO COM A NOVA TRAVA DE SEGURANÇA ATIVA ---")
print(f"Produção Segue com Trava de Sprint : {prod_v4_com_trava:,.1f} garrafas")
print(f"Saldo frente à Produção Real       : {prod_v4_com_trava - prod_real_total:+,.1f} garrafas")
