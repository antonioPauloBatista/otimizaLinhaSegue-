import pandas as pd
import numpy as np

df = pd.read_csv("Panel Title-data-2026-10-01 07_07_32.csv")
df["Time"] = pd.to_datetime(df["Time"])
df = df.sort_values("Time").reset_index(drop=True)
dt = df["Time"].diff().dt.total_seconds().fillna(10.0).clip(upper=60.0)
df["dt_s"] = dt

# Hour by hour
df["hour"] = df["Time"].dt.floor("h")

hourly = df.groupby("hour").apply(lambda g: pd.Series({
    "prod_real": (g["velocidade_real_cph"] * g["dt_s"] / 3600.0).sum(),
    "prod_setpoint": (g["v_setpoint_cph"] * g["dt_s"] / 3600.0).sum(),
    "disponibilidade": (g["velocidade_real_cph"] > 100).mean() * 100,
    "vel_media_rodando": g.loc[g["velocidade_real_cph"] > 100, "velocidade_real_cph"].mean(),
    "pct_sprint": (g["motivo_codigo"] == "SPRINT_SOBREVELOCIDADE").mean() * 100,
    "pct_modulacao": (g["status_modulacao"] == "ATIVA_MODULACAO").mean() * 100,
    "pct_b3_alto": (g["motivo_codigo"] == "ACUMULO_SAIDA_B3").mean() * 100,
    "pct_b2_baixo": (g["motivo_codigo"] == "FALTA_ENTRADA_B2").mean() * 100,
    "pct_parada_propria": (g["motivo_codigo"] == "PARADA_PROPRIA_ENCHEDORA").mean() * 100,
    "v_in_mean": g["v_in_cph"].mean(),
    "v_out_mean": g["v_out_cph"].mean(),
    "b2_mean": g["b2_pct"].mean(),
    "b3_mean": g["b3_pct"].mean(),
})).reset_index()

print("=== PRODUÇÃO HORA A HORA (ÚLTIMAS 24H) ===")
print(hourly.to_string())

# Analyze before and after 19:38 (the commit time of aggressiveness change)
split_time = pd.to_datetime("2026-09-30 19:38:00")
df_before = df[df["Time"] < split_time]
df_after = df[df["Time"] >= split_time]

print("\n=== COMPARAÇÃO ANTES E DEPOIS DAS 19:38 (AJUSTE DE AGRESSIVIDADE) ===")
for name, sub in [("Antes 19:38 (07:07 - 19:38)", df_before), ("Depois 19:38 (19:38 - 07:07)", df_after)]:
    sub_dt = sub["dt_s"].sum() / 3600.0
    prod = (sub["velocidade_real_cph"] * sub["dt_s"] / 3600.0).sum()
    rod = sub["velocidade_real_cph"] > 100
    disp = rod.mean() * 100
    vel_rod = sub.loc[rod, "velocidade_real_cph"].mean()
    sprint_pct = (sub["motivo_codigo"] == "SPRINT_SOBREVELOCIDADE").mean() * 100
    mod_pct = (sub["status_modulacao"] == "ATIVA_MODULACAO").mean() * 100
    print(f"\n{name} - Duração: {sub_dt:.2f}h")
    print(f"  Produção Real: {prod:,.0f} garrafas ({prod/sub_dt:,.0f} g/h)")
    print(f"  Disponibilidade: {disp:.1f}%")
    print(f"  Vel Média Rodando: {vel_rod:,.0f} CPH")
    print(f"  Sprint (% tempo): {sprint_pct:.1f}%")
    print(f"  Modulação (% tempo): {mod_pct:.1f}%")
    print(f"  Top motivos:")
    top_m = (sub.groupby("motivo_codigo")["dt_s"].sum() / sub["dt_s"].sum() * 100).sort_values(ascending=False).head(4)
    for k, v in top_m.items():
        print(f"    - {k}: {v:.1f}%")

# Stop events breakdown
rodando = df["velocidade_real_cph"] > 100
df["is_stop"] = ~rodando
df["stop_block"] = (df["is_stop"] != df["is_stop"].shift(1)).cumsum()

stops = df[df["is_stop"]].groupby("stop_block").agg(
    start_time=("Time", "min"),
    end_time=("Time", "max"),
    duration_s=("dt_s", "sum"),
    predominant_motivo=("motivo_codigo", lambda x: x.mode()[0] if len(x) > 0 else ""),
    predominant_causa=("maquina_causadora", lambda x: x.mode()[0] if len(x) > 0 else ""),
    mean_b2=("b2_pct", "mean"),
    mean_b3=("b3_pct", "mean"),
    v_out_mean=("v_out_cph", "mean"),
    v_in_mean=("v_in_cph", "mean")
).reset_index()

stops["duration_min"] = stops["duration_s"] / 60.0
stops = stops.sort_values("duration_min", ascending=False)

print("\n=== MAIORES PARADAS (TOP 10) ===")
print(stops[["start_time", "end_time", "duration_min", "predominant_causa", "predominant_motivo", "mean_b2", "mean_b3"]].head(10).to_string())

