import pandas as pd

df = pd.read_csv("Panel Title-data-2026-10-01 07_07_32.csv")
df["Time"] = pd.to_datetime(df["Time"])
df = df.sort_values("Time").reset_index(drop=True)

rodando = df["velocidade_real_cph"] > 100
paradas_idx = df[(~rodando) & (rodando.shift(1, fill_value=True))].index

print("=== 1. CASO REAL: A MÁQUINA INDO A ZERO ENQUANTO O SEGUE TENTAVA MODULAR ===")
for p in paradas_idx:
    janela = df.iloc[max(0, p-4):p+3]
    if janela["b3_pct"].max() > 75:
        p_time = df.iloc[p]["Time"]
        print(f"\n--- Parada registrada em {p_time} ---")
        for _, row in janela.iterrows():
            t_str = row["Time"].strftime("%H:%M:%S")
            print(f"{t_str} | Vel Real: {row['velocidade_real_cph']:>6.0f} CPH | Setpoint Segue: {row['v_setpoint_cph']:>6.0f} CPH | B2: {row['b2_pct']:>4.1f}% | B3: {row['b3_pct']:>4.1f}% | {row['motivo_codigo']}")
        break

print("\n=== 2. CASO REAL: MÁQUINA RODANDO LENTO COM LINHA TOTALMENTE LIVRE ===")
perda = df[(df["velocidade_real_cph"] > 1000) & (df["velocidade_real_cph"] < 60000) & (df["b2_pct"] > 55) & (df["b3_pct"] < 45) & (df["v_setpoint_cph"] >= 85000)]
print(f"Total de registros nessa situação: {len(perda)} amostras ({len(perda)*10/60:.1f} minutos perdidos)")
for _, row in perda.iloc[5:10].iterrows():
    t_str = row["Time"].strftime("%H:%M:%S")
    print(f"{t_str} | Vel Real: {row['velocidade_real_cph']:>6.0f} CPH | Setpoint Segue: {row['v_setpoint_cph']:>6.0f} CPH | B2: {row['b2_pct']:>4.1f}% | B3: {row['b3_pct']:>4.1f}% | {row['motivo_codigo']}")

print("\n=== 3. RESUMO ESTATÍSTICO LADO A LADO (QUANDO RODANDO) ===")
df_rod = df[rodando]
print(f"Velocidade Real - Média: {df_rod['velocidade_real_cph'].mean():,.0f} CPH | Mediana: {df_rod['velocidade_real_cph'].median():,.0f} CPH | Desvio Padrão: {df_rod['velocidade_real_cph'].std():,.0f} CPH")
print(f"Segue (com Sprint) - Média: {df_rod['v_setpoint_cph'].mean():,.0f} CPH | Mediana: {df_rod['v_setpoint_cph'].median():,.0f} CPH | Desvio Padrão: {df_rod['v_setpoint_cph'].std():,.0f} CPH")
v_sem_sprint = df_rod['v_setpoint_cph'].clip(upper=90000)
print(f"Segue (sem Sprint) - Média: {v_sem_sprint.mean():,.0f} CPH | Mediana: {v_sem_sprint.median():,.0f} CPH | Desvio Padrão: {v_sem_sprint.std():,.0f} CPH")

