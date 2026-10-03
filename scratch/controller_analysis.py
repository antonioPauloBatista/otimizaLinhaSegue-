import pandas as pd
import numpy as np

df = pd.read_csv("Panel Title-data-2026-10-01 07_07_32.csv")
df["Time"] = pd.to_datetime(df["Time"])
df = df.sort_values("Time").reset_index(drop=True)
dt = df["Time"].diff().dt.total_seconds().fillna(10.0).clip(upper=60.0)
df["dt_s"] = dt

# Check setpoint changes (hunting / chattering)
df["delta_sp"] = df["v_setpoint_cph"].diff().abs()
frequent_changes = df["delta_sp"] > 1000

print("=== ESTABILIDADE DO CONTROLADOR V4 (MODO SOMBRA) ===")
print("Média do Setpoint Recomendado:", f"{df['v_setpoint_cph'].mean():,.0f} CPH")
print("Mediana do Setpoint Recomendado:", f"{df['v_setpoint_cph'].median():,.0f} CPH")
print("Desvio Padrão do Setpoint:", f"{df['v_setpoint_cph'].std():,.0f} CPH")
print("Mudanças de Setpoint > 1000 CPH a cada 10s:", f"{frequent_changes.sum()} vezes ({frequent_changes.mean()*100:.1f}%)")
print("Variação média do Setpoint por ciclo de 10s:", f"{df['delta_sp'].mean():,.1f} CPH")

# Split before and after 19:38
split_time = pd.to_datetime("2026-09-30 19:38:00")
df_before = df[df["Time"] < split_time]
df_after = df[df["Time"] >= split_time]

print("\n--- Estabilidade ANTES das 19:38 ---")
print("Média variação SP a cada 10s:", f"{df_before['delta_sp'].mean():,.1f} CPH")
print("Mudanças > 1000 CPH:", f"{(df_before['delta_sp'] > 1000).mean()*100:.1f}%")

print("\n--- Estabilidade DEPOIS das 19:38 (Nova Agressividade) ---")
print("Média variação SP a cada 10s:", f"{df_after['delta_sp'].mean():,.1f} CPH")
print("Mudanças > 1000 CPH:", f"{(df_after['delta_sp'] > 1000).mean()*100:.1f}%")

# Correlation between setpoint and real speed
rodando = df["velocidade_real_cph"] > 100
print("\n--- Delta Setpoint vs Real (quando rodando) ---")
df_rod = df[rodando]
print("Delta médio (Setpoint - Real):", f"{(df_rod['v_setpoint_cph'] - df_rod['velocidade_real_cph']).mean():+,.0f} CPH")
print("Percentual do tempo em que Real < Setpoint Segue:", f"{(df_rod['velocidade_real_cph'] < df_rod['v_setpoint_cph']).mean()*100:.1f}%")
print("Percentual do tempo em que Real > Setpoint Segue:", f"{(df_rod['velocidade_real_cph'] > df_rod['v_setpoint_cph']).mean()*100:.1f}%")

# Sprints analysis
sprints = df[df["motivo_codigo"] == "SPRINT_SOBREVELOCIDADE"]
print("\n--- Estatísticas dos Sprints ---")
print("Total de registros de sprint:", len(sprints), f"({len(sprints)/len(df)*100:.1f}% do tempo)")
print("Setpoint médio durante Sprint:", f"{sprints['v_setpoint_cph'].mean():,.0f} CPH")
print("Velocidade real média durante Sprint:", f"{sprints['velocidade_real_cph'].mean():,.0f} CPH")
print("Velocidade ECI (v_in) durante Sprint:", f"{sprints['v_in_cph'].mean():,.0f} CPH")
print("Velocidade Pasteurizador (v_out) durante Sprint:", f"{sprints['v_out_cph'].mean():,.0f} CPH")
print("Buffer B2 durante Sprint:", f"{sprints['b2_pct'].mean():.1f}%")
print("Buffer B3 durante Sprint:", f"{sprints['b3_pct'].mean():.1f}%")

# When machine was stopped: what was Segue doing?
parada = df[~rodando]
print("\n--- O que o Segue recomendava com a máquina PARADA? ---")
print("Distribuição de motivos Segue durante parada:")
print(parada["motivo_codigo"].value_counts(normalize=True).round(3) * 100)
print("Setpoint médio quando parada:", f"{parada['v_setpoint_cph'].mean():,.0f} CPH")

