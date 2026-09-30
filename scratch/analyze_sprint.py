import pandas as pd

df = pd.read_csv("Panel Title-data-2026-09-30 08_11_24.csv")
df["Time"] = pd.to_datetime(df["Time"])

sprint = df[df["motivo_codigo"] == "SPRINT_SOBREVELOCIDADE"]
normal = df[df["motivo_codigo"] == "NORMAL_FULL"]
modula = df[df["status_modulacao"] == "ATIVA_MODULACAO"]

print("=== COMPORTAMENTO DURANTE SPRINT_SOBREVELOCIDADE ===")
print("Total de registros em Sprint:", len(sprint), f"({len(sprint)/len(df)*100:.1f}% do tempo)")
print("Setpoint médio:", sprint["v_setpoint_cph"].mean(), "min:", sprint["v_setpoint_cph"].min(), "max:", sprint["v_setpoint_cph"].max())
print("Buffer Entrada B2 em Sprint: média =", f"{sprint['b2_pct'].mean():.1f}%", "min =", f"{sprint['b2_pct'].min():.1f}%")
print("Buffer Saída B3 em Sprint: média =", f"{sprint['b3_pct'].mean():.1f}%", "max =", f"{sprint['b3_pct'].max():.1f}%")
print("Velocidade Pasteurizador (v_out) em Sprint: média =", f"{sprint['v_out_cph'].mean():.0f} CPH", "min =", f"{sprint['v_out_cph'].min():.0f} CPH")

print("\n=== COMPORTAMENTO QUANDO EM MODULAÇÃO (REDUÇÃO) ===")
print("Total de registros em Modulação:", len(modula), f"({len(modula)/len(df)*100:.1f}% do tempo)")
print("Buffer Saída B3 em Modulação: média =", f"{modula['b3_pct'].mean():.1f}%", "max =", f"{modula['b3_pct'].max():.1f}%")
print("Buffer Entrada B2 em Modulação: média =", f"{modula['b2_pct'].mean():.1f}%", "min =", f"{modula['b2_pct'].min():.1f}%")
print("Velocidade Pasteurizador em Modulação: média =", f"{modula['v_out_cph'].mean():.0f} CPH")
