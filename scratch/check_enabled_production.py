import pandas as pd

df = pd.read_csv("Panel Title-data-2026-10-01 07_07_32.csv")
df["Time"] = pd.to_datetime(df["Time"])
df = df.sort_values("Time").reset_index(drop=True)
dt = df["Time"].diff().dt.total_seconds().fillna(10.0).clip(upper=60.0)
df["dt_s"] = dt

v_nom = 90000.0

print("=== 1. QUANDO status_maquina == True ===")
sm_true = df[df["status_maquina"] == True]
th_sm = sm_true["dt_s"].sum() / 3600.0
prod_real_sm = (sm_true["velocidade_real_cph"] * sm_true["dt_s"] / 3600.0).sum()
prod_nom_sm = (v_nom * sm_true["dt_s"] / 3600.0).sum()
prod_sp_sm = (sm_true["v_setpoint_cph"] * sm_true["dt_s"] / 3600.0).sum()
vm_real_sm = prod_real_sm / th_sm
vm_sp_sm = prod_sp_sm / th_sm

print(f"Tempo com status_maquina=True: {th_sm:.2f} h ({th_sm/24.0*100:.1f}% do dia)")
print(f"Produção Real: {prod_real_sm:,.0f} garrafas")
print(f"Produção Esperada na vel normal (90.000 CPH): {prod_nom_sm:,.0f} garrafas")
print(f"Diferença (Real - Normal): {prod_real_sm - prod_nom_sm:,.0f} garrafas ({prod_real_sm/prod_nom_sm*100:.1f}%)")
print(f"Velocidade média Real: {vm_real_sm:,.0f} CPH (Normal: 90.000 CPH)")
print(f"Velocidade média Setpoint Segue: {vm_sp_sm:,.0f} CPH")

print("\n=== 2. QUANDO A MÁQUINA ESTAVA EFETIVAMENTE RODANDO (velocidade_real > 100) ===")
rodando = df[df["velocidade_real_cph"] > 100]
th_rod = rodando["dt_s"].sum() / 3600.0
prod_real_rod = (rodando["velocidade_real_cph"] * rodando["dt_s"] / 3600.0).sum()
prod_nom_rod = (v_nom * rodando["dt_s"] / 3600.0).sum()
vm_real_rod = prod_real_rod / th_rod

print(f"Tempo rodando: {th_rod:.2f} h")
print(f"Produção Real: {prod_real_rod:,.0f} garrafas")
print(f"Produção Normal se rodasse a 90.000 CPH contínuo: {prod_nom_rod:,.0f} garrafas")
print(f"Diferença: {prod_real_rod - prod_nom_rod:,.0f} garrafas")
print(f"Velocidade média Real em marcha: {vm_real_rod:,.0f} CPH ({vm_real_rod/v_nom*100:.1f}% da normal)")

print("\n=== 3. EM ALGUM MOMENTO A VELOCIDADE REAL SUPEROU A VELOCIDADE NORMAL (90.000 CPH)? ===")
acima_90k = df[df["velocidade_real_cph"] > 90000]
tempo_acima_90k = acima_90k["dt_s"].sum() / 3600.0
v_min_acima = acima_90k["velocidade_real_cph"].min()
v_max_acima = acima_90k["velocidade_real_cph"].max()
v_mean_acima = acima_90k["velocidade_real_cph"].mean()
print(f"Tempo com velocidade_real > 90.000 CPH: {tempo_acima_90k:.2f} h ({tempo_acima_90k/24.0*100:.1f}% do dia, {tempo_acima_90k/th_rod*100:.1f}% do tempo rodando)")
print(f"Velocidade máxima real registrada: {v_max_acima:,.0f} CPH")
print(f"Velocidade média nos momentos acima de 90k: {v_mean_acima:,.0f} CPH")

print("\n=== 4. E QUANDO O OTIMIZADOR ATIVOU SPRINT / SOBREVELOCIDADE (>100%)? ===")
sprint = df[df["motivo_codigo"] == "SPRINT_SOBREVELOCIDADE"]
th_sprint = sprint["dt_s"].sum() / 3600.0
prod_real_sprint = (sprint["velocidade_real_cph"] * sprint["dt_s"] / 3600.0).sum()
prod_sp_sprint = (sprint["v_setpoint_cph"] * sprint["dt_s"] / 3600.0).sum()
prod_nom_sprint = (v_nom * sprint["dt_s"] / 3600.0).sum()
vm_sp_sprint = sprint["v_setpoint_cph"].mean()

print(f"Tempo em Sprint Segue: {th_sprint:.2f} h ({th_sprint/24.0*100:.1f}% do dia)")
print(f"Setpoint do Segue no Sprint: {vm_sp_sprint:,.0f} CPH (103% da normal)")
print(f"Produção Real obtida durante janelas de Sprint: {prod_real_sprint:,.0f} garrafas")
print(f"Produção se estivesse na Vel Normal (90k): {prod_nom_sprint:,.0f} garrafas")
print(f"Produção proposta pelo Segue no Sprint: {prod_sp_sprint:,.0f} garrafas")
print(f"Velocidade média Real durante o Sprint: {prod_real_sprint/th_sprint:,.0f} CPH")
pct_real_acima_em_sprint = (sprint["velocidade_real_cph"] > 90000).mean()*100
print(f"Percentual do tempo em Sprint que a vel_real ficou > 90k: {pct_real_acima_em_sprint:.1f}%")

print("\n=== 5. ANÁLISE DE SEGUE HABILITADO / MODO SOMBRA ===")
print("segue_habilitado valores:", df["segue_habilitado"].value_counts().to_dict())
print("modo_sombra valores:", df["modo_sombra"].value_counts().to_dict())

