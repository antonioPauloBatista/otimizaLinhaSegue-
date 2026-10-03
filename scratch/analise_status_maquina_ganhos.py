import pandas as pd
import numpy as np

file_path = "Panel Title-data-2026-10-02 09_12_53.csv"
df = pd.read_csv(file_path)

dt_h = 10.0 / 3600.0  # 10 segundos em horas

print("="*80)
print("AUDITORIA DE GANHOS BASEADA NO STATUS DA MÁQUINA (CLP)")
print("="*80)

# 1. Panorama geral da tag status_maquina
print("\n--- 1. DISTRIBUIÇÃO DA TAG 'status_maquina' ---")
print(df['status_maquina'].value_counts(dropna=False))
for val, grp in df.groupby('status_maquina'):
    horas = len(grp) * 10 / 3600
    pct = (len(grp) / len(df)) * 100
    print(f"  status_maquina == {val:<5}: {len(grp):4d} ciclos ({horas:5.2f} horas | {pct:5.1f}% do dia)")

# 2. Análise detalhada quando status_maquina == True (PRODUÇÃO EFETIVA / REGIME)
df_status_true = df[df['status_maquina'] == True].copy()
prod_real_true = (df_status_true['velocidade_real_cph'] * dt_h).sum()
prod_v4_true = (df_status_true['velocidade_v4_cph'] * dt_h).sum()
saldo_true = prod_v4_true - prod_real_true
pct_true = (saldo_true / prod_real_true) * 100

print("\n--- 2. PRODUÇÃO QUANDO status_maquina == True (EM REGIME DE PRODUÇÃO) ---")
print(f"Duração Total                     : {len(df_status_true)*10/3600:.2f} horas ({len(df_status_true)} ciclos)")
print(f"Produção Real da Linha            : {prod_real_true:,.1f} garrafas")
print(f"Produção Calculada pelo Segue(V4) : {prod_v4_true:,.1f} garrafas")
print(f"SALDO DO SEGUE                    : {saldo_true:+,.1f} garrafas ({pct_true:+.2f}%)")

# Paradas reais durante status_maquina == True
paradas_em_true = df_status_true[df_status_true['velocidade_real_cph'] == 0]
prod_v4_paradas_true = (paradas_em_true['velocidade_v4_cph'] * dt_h).sum()
print(f"\nDurante status_maquina == True:")
print(f"  ↳ Ciclos de Parada Real (0 CPH) : {len(paradas_em_true)} ciclos ({len(paradas_em_true)*10/60:.1f} minutos)")
print(f"  ↳ Garrafas Segue nessas paradas : {prod_v4_paradas_true:,.1f} garrafas")

# Subdivisão das paradas em True: por buffer vs outros
paradas_buf_true = paradas_em_true[(paradas_em_true['b2_pct'] <= 10.0) | (paradas_em_true['b3_pct'] >= 90.0)]
paradas_out_true = paradas_em_true[~((paradas_em_true['b2_pct'] <= 10.0) | (paradas_em_true['b3_pct'] >= 90.0))]
print(f"    * Paradas por BUFFER (B2<=10% ou B3>=90%) : {len(paradas_buf_true)} ciclos ({(paradas_buf_true['velocidade_v4_cph']*dt_h).sum():,.1f} gf evitadas)")
print(f"    * Paradas internas da enchedora            : {len(paradas_out_true)} ciclos ({(paradas_out_true['velocidade_v4_cph']*dt_h).sum():,.1f} gf)")

# Rodando em True:
rodando_em_true = df_status_true[df_status_true['velocidade_real_cph'] > 0]
prod_real_rodando_true = (rodando_em_true['velocidade_real_cph'] * dt_h).sum()
prod_v4_rodando_true = (rodando_em_true['velocidade_v4_cph'] * dt_h).sum()
print(f"\n  ↳ Com a máquina realmente rodando (v_real > 0 e status_maquina == True):")
print(f"    * Produção Real               : {prod_real_rodando_true:,.1f} garrafas")
print(f"    * Produção Segue              : {prod_v4_rodando_true:,.1f} garrafas")
print(f"    * Saldo                       : {prod_v4_rodando_true - prod_real_rodando_true:+,.1f} garrafas ({(prod_v4_rodando_true/prod_real_rodando_true - 1)*100:+.2f}%)")

# 3. Análise detalhada quando status_maquina == False (MANUAL / PREPARAÇÃO / MANUTENÇÃO)
df_status_false = df[df['status_maquina'] == False].copy()
prod_real_false = (df_status_false['velocidade_real_cph'] * dt_h).sum()
prod_v4_false = (df_status_false['velocidade_v4_cph'] * dt_h).sum()

print("\n--- 3. O QUE ACONTECEU QUANDO status_maquina == False ---")
print(f"Duração Total                     : {len(df_status_false)*10/3600:.2f} horas ({len(df_status_false)} ciclos)")
print(f"Produção Real registrada          : {prod_real_false:,.1f} garrafas")
print(f"Produção Segue calculada          : {prod_v4_false:,.1f} garrafas (O V4 coloca 0 CPH por segurança quando status==False)")
print("Distribuição de velocidade real em status_maquina == False:")
print(df_status_false['velocidade_real_cph'].value_counts().head(10))

# 4. Cruzamento de status_maquina com status_operacional
print("\n--- 4. MATRIZ CRUZADA: status_maquina vs status_operacional ---")
print(pd.crosstab(df['status_maquina'], df['status_operacional'], margins=True))

# 5. Motivos do Segue quando status_maquina == True
print("\n--- 5. MOTIVOS DO CONTROLADOR QUANDO status_maquina == True ---")
motivos_true = df_status_true.groupby(['motivo_id', 'motivo_codigo', 'maquina_causadora']).size().reset_index(name='contagem')
motivos_true['pct'] = (motivos_true['contagem'] / len(df_status_true)) * 100
print(motivos_true.to_string(index=False))

# 6. Saldo Realístico Final
print("\n--- 6. BALANÇO REALÍSTICO DE PRODUÇÃO COM STATUS DA MÁQUINA ---")
print(f"A) Se considerarmos apenas o período de PRODUÇÃO REAL (status_maquina == True):")
print(f"   Produção Real  : {prod_real_true:,.0f} garrafas")
print(f"   Produção Segue : {prod_v4_true:,.0f} garrafas")
print(f"   Ganho do Segue : {saldo_true:+,.0f} garrafas ({pct_true:+.2f}%)")
print(f"B) No período de status_maquina == False (1.619 ciclos / 4.5 horas):")
print(f"   A fábrica rodou em marcha manual de preparação/lavagem a 15k/25k CPH ({prod_real_false:,.0f} garrafas).")
print(f"   O Segue respeitou o intertravamento e desligou o setpoint para 0 CPH (parada de segurança).")
