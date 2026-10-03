import pandas as pd
import numpy as np

df = pd.read_csv("Panel Title-data-2026-10-01 07_07_32.csv")
df["Time"] = pd.to_datetime(df["Time"])
df = df.sort_values("Time").reset_index(drop=True)
dt = df["Time"].diff().dt.total_seconds().fillna(10.0).clip(upper=60.0)
df["dt_s"] = dt

rodando = df["velocidade_real_cph"] > 100
df["rodando"] = rodando

# Overall KPI
total_hours = df["dt_s"].sum() / 3600.0
tempo_rodando = df.loc[rodando, "dt_s"].sum() / 3600.0
tempo_parada = df.loc[~rodando, "dt_s"].sum() / 3600.0
disponibilidade = (tempo_rodando / total_hours) * 100

prod_real = (df["velocidade_real_cph"] * df["dt_s"] / 3600.0).sum()
prod_sp = (df["v_setpoint_cph"] * df["dt_s"] / 3600.0).sum()
prod_nom_potencial = (90000.0 * df["dt_s"] / 3600.0).sum() # 24h * 90k = 2,160,000

vel_media_rod = (df.loc[rodando, "velocidade_real_cph"] * df.loc[rodando, "dt_s"]).sum() / df.loc[rodando, "dt_s"].sum()
performance_op = (vel_media_rod / 90000.0) * 100

print(f"Total Horas: {total_hours:.2f} h")
print(f"Tempo Rodando: {tempo_rodando:.2f} h ({disponibilidade:.1f}%)")
print(f"Tempo Parado: {tempo_parada:.2f} h ({100-disponibilidade:.1f}%)")
print(f"Produção Real: {prod_real:,.0f} garrafas")
print(f"Produção Setpoint: {prod_sp:,.0f} garrafas")
print(f"Produção Nominal Potencial (100% tempo a 90k): {prod_nom_potencial:,.0f} garrafas")
print(f"Velocidade Média Geral: {prod_real/total_hours:,.0f} CPH")
print(f"Velocidade Média em Marcha: {vel_media_rod:,.0f} CPH ({performance_op:.1f}% da nominal)")

# Modulações
print("\n--- DISTRIBUIÇÃO STATUS MODULAÇÃO ---")
for mod, g in df.groupby("status_modulacao"):
    h = g["dt_s"].sum() / 3600.0
    pct = h / total_hours * 100
    prod = (g["velocidade_real_cph"] * g["dt_s"] / 3600.0).sum()
    vm = prod / h if h > 0 else 0
    print(f"{mod}: {h:.2f} h ({pct:.1f}%) | Produção: {prod:,.0f} | Vel Média: {vm:,.0f} CPH")

print("\n--- DISTRIBUIÇÃO MOTIVO CÓDIGO ---")
for mot, g in df.groupby("motivo_codigo"):
    h = g["dt_s"].sum() / 3600.0
    pct = h / total_hours * 100
    prod = (g["velocidade_real_cph"] * g["dt_s"] / 3600.0).sum()
    vm = prod / h if h > 0 else 0
    print(f"{mot}: {h:.2f} h ({pct:.1f}%) | Produção: {prod:,.0f} | Vel Média: {vm:,.0f} CPH")

print("\n--- DISTRIBUIÇÃO MÁQUINA CAUSADORA ---")
for maq, g in df.groupby("maquina_causadora"):
    h = g["dt_s"].sum() / 3600.0
    pct = h / total_hours * 100
    prod = (g["velocidade_real_cph"] * g["dt_s"] / 3600.0).sum()
    vm = prod / h if h > 0 else 0
    print(f"{maq}: {h:.2f} h ({pct:.1f}%) | Produção: {prod:,.0f} | Vel Média: {vm:,.0f} CPH")

# Paradas agrupadas por causa
df["is_stop"] = ~rodando
df["stop_block"] = (df["is_stop"] != df["is_stop"].shift(1)).cumsum()
stops = df[df["is_stop"]].groupby("stop_block").agg(
    inicio=("Time", "min"),
    fim=("Time", "max"),
    duracao_min=("dt_s", lambda x: x.sum() / 60.0),
    causa=("maquina_causadora", lambda x: x.mode()[0] if len(x)>0 else ""),
    motivo=("motivo_codigo", lambda x: x.mode()[0] if len(x)>0 else ""),
    b2=("b2_pct", "mean"),
    b3=("b3_pct", "mean")
).reset_index()

print("\n--- RESUMO DE PARADAS POR CAUSA ---")
stops_summary = stops.groupby("causa").agg(
    qtd=("duracao_min", "count"),
    tempo_total_min=("duracao_min", "sum"),
    tempo_medio_min=("duracao_min", "mean"),
    tempo_max_min=("duracao_min", "max")
).reset_index().sort_values("tempo_total_min", ascending=False)
print(stops_summary.to_string())

# Turnos (Shifts): Turno 1 (07:00 - 15:00), Turno 2 (15:00 - 23:00), Turno 3 (23:00 - 07:00)
def get_shift(dt):
    h = dt.hour
    if 7 <= h < 15:
        return "Turno 1 (07h-15h)"
    elif 15 <= h < 23:
        return "Turno 2 (15h-23h)"
    else:
        return "Turno 3 (23h-07h)"

df["turno"] = df["Time"].apply(get_shift)
print("\n--- ANÁLISE COMPARATIVA POR TURNO OPERACIONAL ---")
for t_name, g in df.groupby("turno"):
    th = g["dt_s"].sum() / 3600.0
    r = g["velocidade_real_cph"] > 100
    th_rod = g.loc[r, "dt_s"].sum() / 3600.0
    disp = (th_rod / th) * 100
    prod = (g["velocidade_real_cph"] * g["dt_s"] / 3600.0).sum()
    vm_rod = (g.loc[r, "velocidade_real_cph"] * g.loc[r, "dt_s"]).sum() / g.loc[r, "dt_s"].sum() if th_rod > 0 else 0
    sprint_pct = (g["motivo_codigo"] == "SPRINT_SOBREVELOCIDADE").mean() * 100
    b3_alto_pct = (g["motivo_codigo"] == "ACUMULO_SAIDA_B3").mean() * 100
    b2_baixo_pct = (g["motivo_codigo"] == "FALTA_ENTRADA_B2").mean() * 100
    parada_propria_pct = (g["motivo_codigo"] == "PARADA_PROPRIA_ENCHEDORA").mean() * 100
    
    print(f"\n{t_name} ({th:.2f} h):")
    print(f"  Produção Real: {prod:,.0f} garrafas (Média: {prod/th:,.0f} g/h)")
    print(f"  Disponibilidade: {disp:.1f}% (Rodando: {th_rod:.2f}h | Parada: {th-th_rod:.2f}h)")
    print(f"  Velocidade Média em Marcha: {vm_rod:,.0f} CPH")
    print(f"  Sprint: {sprint_pct:.1f}%")
    print(f"  Acúmulo Saída B3: {b3_alto_pct:.1f}%")
    print(f"  Falta Entrada B2: {b2_baixo_pct:.1f}%")
    print(f"  Parada Própria Enchedora: {parada_propria_pct:.1f}%")

