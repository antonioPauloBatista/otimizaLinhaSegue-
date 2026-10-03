import pandas as pd
import numpy as np

def run_deep_analysis(csv_path):
    df = pd.read_csv(csv_path)
    df["Time"] = pd.to_datetime(df["Time"])
    df = df.sort_values("Time").reset_index(drop=True)
    dt = df["Time"].diff().dt.total_seconds().fillna(10.0)
    dt = dt.clip(upper=60.0)
    df["dt_s"] = dt
    
    total_hours = df["dt_s"].sum() / 3600.0
    rodando = df["velocidade_real_cph"] > 100
    
    prod_real = (df["velocidade_real_cph"].fillna(0) * df["dt_s"] / 3600.0).sum()
    prod_setpoint = (df["v_setpoint_cph"].fillna(0) * df["dt_s"] / 3600.0).sum()
    prod_potencial_nominal = (90000.0 * df["dt_s"] / 3600.0).sum()
    
    tempo_rodando_h = df.loc[rodando, "dt_s"].sum() / 3600.0
    tempo_parada_h = df.loc[~rodando, "dt_s"].sum() / 3600.0
    disponibilidade = tempo_rodando_h / total_hours * 100
    
    vel_media_rodando = (df.loc[rodando, "velocidade_real_cph"] * df.loc[rodando, "dt_s"]).sum() / df.loc[rodando, "dt_s"].sum() if tempo_rodando_h > 0 else 0
    vel_media_global = prod_real / total_hours
    
    # Paradas
    df["parando"] = (~rodando) & (rodando.shift(1, fill_value=True))
    num_paradas = df["parando"].sum()
    
    t_min = df["Time"].min()
    t_max = df["Time"].max()
    print(f"=== ANÁLISE: {csv_path} ===")
    print(f"Período: {t_min} a {t_max} ({total_hours:.2f} h)")
    print(f"Produção Real: {prod_real:,.0f} garrafas")
    print(f"Produção Setpoint Segue: {prod_setpoint:,.0f} garrafas (Delta vs Real: {prod_setpoint - prod_real:+,.0f})")
    print(f"Disponibilidade: {disponibilidade:.1f}% ({tempo_rodando_h:.2f}h rodando | {tempo_parada_h:.2f}h parada)")
    print(f"Velocidade Média Rodando: {vel_media_rodando:,.0f} CPH (Nominal: 90,000 CPH -> {vel_media_rodando/90000*100:.1f}%)")
    print(f"Velocidade Média Global: {vel_media_global:,.0f} CPH")
    print(f"Número de Paradas (v=0): {num_paradas} ({num_paradas/total_hours:.1f} paradas/hora)")
    
    # Modulações
    print("\n--- Distribuição de Modulação (% do tempo) ---")
    mod_dist = (df.groupby("status_modulacao")["dt_s"].sum() / df["dt_s"].sum() * 100).round(1)
    for k, v in mod_dist.items():
        print(f"  {k}: {v}%")
        
    print("\n--- Motivos de Controle (% do tempo) ---")
    mot_dist = (df.groupby("motivo_codigo")["dt_s"].sum() / df["dt_s"].sum() * 100).round(1).sort_values(ascending=False)
    for k, v in mot_dist.items():
        print(f"  {k}: {v}%")
        
    print("\n--- Máquina Causadora (% do tempo) ---")
    maq_dist = (df.groupby("maquina_causadora")["dt_s"].sum() / df["dt_s"].sum() * 100).round(1).sort_values(ascending=False)
    for k, v in maq_dist.items():
        print(f"  {k}: {v}%")

    print("\n--- Médias de Buffers e Velocidades Globais ---")
    print(f"  Buffer B1: {df['b1_pct'].mean():.1f}%")
    print(f"  Buffer B2 (Entrada): {df['b2_pct'].mean():.1f}%")
    print(f"  Buffer B3 (Saída): {df['b3_pct'].mean():.1f}%")
    print(f"  Buffer B4: {df['b4_pct'].mean():.1f}%")
    print(f"  v_in (ECI): {df['v_in_cph'].mean():,.0f} CPH")
    print(f"  v_real (Enchedora): {df['velocidade_real_cph'].mean():,.0f} CPH")
    print(f"  v_out (Pasteurizador): {df['v_out_cph'].mean():,.0f} CPH")
    print(f"  v_setpoint (Segue): {df['v_setpoint_cph'].mean():,.0f} CPH")

if __name__ == "__main__":
    run_deep_analysis("Panel Title-data-2026-10-01 07_07_32.csv")
    print("\n" + "="*80 + "\n")
    run_deep_analysis("Panel Title-data-2026-09-30 08_11_24.csv")
