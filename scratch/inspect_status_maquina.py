import pandas as pd

df = pd.read_csv("Panel Title-data-2026-09-30 08_11_24.csv")
df["Time"] = pd.to_datetime(df["Time"])
df = df.sort_values("Time").reset_index(drop=True)

print("=== TRANSICOES DE status_maquina ===")
df["status_change"] = df["status_maquina"] != df["status_maquina"].shift(1)
changes = df[df["status_change"]]
print(f"Total de mudanças de status_maquina: {len(changes)}")

# Mostrar trechos onde status_maquina foi False
false_periods = []
in_false = False
start_idx = 0

for i, row in df.iterrows():
    if not row["status_maquina"] and not in_false:
        in_false = True
        start_idx = i
    elif row["status_maquina"] and in_false:
        in_false = False
        false_periods.append((start_idx, i-1))
if in_false:
    false_periods.append((start_idx, len(df)-1))

print(f"\nNúmero de episódios de status_maquina == False: {len(false_periods)}")
for idx, (s, e) in enumerate(false_periods):
    t_start = df.loc[s, "Time"]
    t_end = df.loc[e, "Time"]
    duration_min = (t_end - t_start).total_seconds() / 60.0
    vel_mean = df.loc[s:e, "velocidade_real_cph"].mean()
    vel_max = df.loc[s:e, "velocidade_real_cph"].max()
    sp_mean = df.loc[s:e, "v_setpoint_cph"].mean()
    motivos = df.loc[s:e, "motivo_codigo"].value_counts().to_dict()
    print(f"Episódio {idx+1}: {t_start.strftime('%H:%M:%S')} até {t_end.strftime('%H:%M:%S')} ({duration_min:.1f} min, {e-s+1} pts)")
    print(f"   Vel Real Média: {vel_mean:.0f} CPH | Vel Real Max: {vel_max:.0f} CPH | SP Médio: {sp_mean:.0f} CPH")
    print(f"   Motivos no período: {motivos}")

