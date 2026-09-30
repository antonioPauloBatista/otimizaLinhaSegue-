import pandas as pd
import numpy as np

def analyze_file(path):
    df = pd.read_csv(path)
    df["Time"] = pd.to_datetime(df["Time"])
    df = df.sort_values("Time").reset_index(drop=True)
    
    # Calculate time delta in seconds between points
    # Cap extreme intervals (e.g. restarts or logging breaks) at 60s for dt_s
    dt_raw = df["Time"].diff().dt.total_seconds()
    df["dt_s"] = dt_raw.fillna(10.0)
    # If there are big gaps, let us know
    big_gaps = df[df["dt_s"] > 60]
    
    total_time_h = df["dt_s"].sum() / 3600.0
    time_span_h = (df["Time"].max() - df["Time"].min()).total_seconds() / 3600.0
    
    garrafas_reais = (df["velocidade_real_cph"].fillna(0) * df["dt_s"] / 3600.0).sum()
    garrafas_setpoint = (df["v_setpoint_cph"].fillna(0) * df["dt_s"] / 3600.0).sum()
    garrafas_potencial_nominal = (90000.0 * df["dt_s"] / 3600.0).sum()
    
    rodando = df["velocidade_real_cph"] > 100 # v > 100 cph
    tempo_rodando_h = df.loc[rodando, "dt_s"].sum() / 3600.0
    tempo_parada_h = df.loc[~rodando, "dt_s"].sum() / 3600.0
    
    disponibilidade = (tempo_rodando_h / total_time_h) * 100 if total_time_h > 0 else 0
    
    vel_media_global = garrafas_reais / total_time_h if total_time_h > 0 else 0
    vel_media_rodando = (df.loc[rodando, "velocidade_real_cph"] * df.loc[rodando, "dt_s"]).sum() / df.loc[rodando, "dt_s"].sum() if tempo_rodando_h > 0 else 0
    
    status_maq_true_h = 0
    status_maq_false_h = 0
    if "status_maquina" in df.columns:
        status_maq_true_h = df.loc[df["status_maquina"] == True, "dt_s"].sum() / 3600.0
        status_maq_false_h = df.loc[df["status_maquina"] == False, "dt_s"].sum() / 3600.0

    print("="*70)
    print(f"ARQUIVO: {path}")
    print(f"Período: {df['Time'].min()} até {df['Time'].max()} (Span: {time_span_h:.2f} h | Soma dt: {total_time_h:.2f} h)")
    print(f"Total de registros: {len(df)}")
    print(f"Produção Real Total: {garrafas_reais:,.0f} garrafas")
    print(f"Taxa Média de Produção Real: {vel_media_global:,.1f} garrafas/h")
    print(f"Velocidade Média quando Rodando (v > 100): {vel_media_rodando:,.1f} CPH")
    print(f"Disponibilidade Operacional: {disponibilidade:.1f}% ({tempo_rodando_h:.2f}h rodando vs {tempo_parada_h:.2f}h parada)")
    
    if "status_maquina" in df.columns:
        print(f"Tag status_maquina=True (Máq Habilitada/Pronta): {status_maq_true_h:.2f} h ({status_maq_true_h/total_time_h*100:.1f}%)")
        print(f"Tag status_maquina=False (Máq Desabilitada/Falha): {status_maq_false_h:.2f} h ({status_maq_false_h/total_time_h*100:.1f}%)")
        
        # Correlacao entre status_maquina e velocidade
        v_when_status_false = df.loc[df["status_maquina"] == False, "velocidade_real_cph"].describe()
        v_when_status_true = df.loc[df["status_maquina"] == True, "velocidade_real_cph"].describe()
        print(f"  -> Vel Média quando status_maquina=False: {v_when_status_false['mean']:.1f} CPH (max: {v_when_status_false['max']:.1f})")
        print(f"  -> Vel Média quando status_maquina=True: {v_when_status_true['mean']:.1f} CPH")
        
    print("\nStatus de Modulação (% do tempo):")
    if "status_modulacao" in df.columns:
        mod_s = df.groupby("status_modulacao")["dt_s"].sum() / df["dt_s"].sum() * 100
        for k, v in mod_s.items():
            print(f"  - {k}: {v:.1f}%")
            
    print("\nTop 5 Motivos de Modulação (% do tempo):")
    if "motivo_codigo" in df.columns:
        mot_s = df.groupby("motivo_codigo")["dt_s"].sum() / df["dt_s"].sum() * 100
        for k, v in mot_s.sort_values(ascending=False).head(5).items():
            print(f"  - {k}: {v:.1f}%")

    # Contagem de paradas (transições de rodando para parado)
    df["parando"] = (~rodando) & (rodando.shift(1, fill_value=True))
    num_paradas = df["parando"].sum()
    print(f"\nNúmero de eventos de parada (v caindo para 0): {num_paradas} vezes")
    if num_paradas > 0:
        print(f"Frequência de paradas: {num_paradas / total_time_h:.2f} paradas por hora")

for f in ["Panel Title-data-2026-09-29 08_44_34.csv", "Panel Title-data-2026-09-29 15_11_04.csv", "Panel Title-data-2026-09-30 08_11_24.csv"]:
    analyze_file(f)
