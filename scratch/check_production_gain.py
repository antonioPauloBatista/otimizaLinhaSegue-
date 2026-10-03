import pandas as pd
import numpy as np

df = pd.read_csv("Panel Title-data-2026-10-01 07_07_32.csv")
df["Time"] = pd.to_datetime(df["Time"])
df = df.sort_values("Time").reset_index(drop=True)
dt = df["Time"].diff().dt.total_seconds().fillna(10.0).clip(upper=60.0)
df["dt_s"] = dt

# 1. Filtro estrito: APENAS quando a enchedora estava efetivamente em marcha (rodando)
rodando = df["velocidade_real_cph"] > 100
df_rod = df[rodando].copy()

total_h_rod = df_rod["dt_s"].sum() / 3600.0
prod_real_rod = (df_rod["velocidade_real_cph"] * df_rod["dt_s"] / 3600.0).sum()
prod_sp_rod = (df_rod["v_setpoint_cph"] * df_rod["dt_s"] / 3600.0).sum()

vm_real_rod = prod_real_rod / total_h_rod
vm_sp_rod = prod_sp_rod / total_h_rod

delta_prod = prod_sp_rod - prod_real_rod
delta_pct = (delta_prod / prod_real_rod) * 100

print("=== 1. COMPARAÇÃO ESTRITA: SOMENTE QUANDO A MÁQUINA ESTAVA RODANDO ===")
print(f"Tempo total em marcha: {total_h_rod:.2f} h")
print(f"Produção Real entregue: {prod_real_rod:,.0f} garrafas (Média: {vm_real_rod:,.0f} CPH)")
print(f"Produção recomendada pelo Segue: {prod_sp_rod:,.0f} garrafas (Média: {vm_sp_rod:,.0f} CPH)")
print(f"Saldo a favor do Segue: {delta_prod:+,.0f} garrafas ({delta_pct:+.1f}%)")

# 2. Distribuição momento a momento durante a marcha
segue_maior = df_rod[df_rod["v_setpoint_cph"] > df_rod["velocidade_real_cph"] + 500]
segue_menor = df_rod[df_rod["v_setpoint_cph"] < df_rod["velocidade_real_cph"] - 500]
segue_igual = df_rod[abs(df_rod["v_setpoint_cph"] - df_rod["velocidade_real_cph"]) <= 500]

h_maior = segue_maior["dt_s"].sum() / 3600.0
h_menor = segue_menor["dt_s"].sum() / 3600.0
h_igual = segue_igual["dt_s"].sum() / 3600.0

print("\n=== 2. DISTRIBUIÇÃO DAS DECISÕES DURANTE A MARCHA ===")
print(f"Segue recomendou velocidade MAIOR que o real: {h_maior:.2f} h ({h_maior/total_h_rod*100:.1f}% do tempo rodando)")
print(f"  -> Delta médio quando maior: +{(segue_maior['v_setpoint_cph'] - segue_maior['velocidade_real_cph']).mean():,.0f} CPH")
print(f"  -> Buffers médios nessas janelas: B2={segue_maior['b2_pct'].mean():.1f}%, B3={segue_maior['b3_pct'].mean():.1f}%")
print(f"Segue recomendou velocidade MENOR que o real (Modulação Preventiva): {h_menor:.2f} h ({h_menor/total_h_rod*100:.1f}% do tempo rodando)")
print(f"  -> Delta médio quando menor: -{(segue_menor['velocidade_real_cph'] - segue_menor['v_setpoint_cph']).mean():,.0f} CPH")
print(f"  -> Buffers médios nessas janelas: B2={segue_menor['b2_pct'].mean():.1f}%, B3={segue_menor['b3_pct'].mean():.1f}%")
print(f"Velocidades equivalentes (diferença <= 500 CPH): {h_igual:.2f} h ({h_igual/total_h_rod*100:.1f}%)")

# 3. Análise da modulação preventiva do Segue:
# O operador roda rápido até bater no sensor e parar (burlar modulação),
# enquanto o Segue reduz para 67.5k a 75k CPH mantendo o fluxo contínuo.
print("\n=== 3. ANÁLISE DOS MOTIVOS QUANDO SEGUE PEDIU MENOR VELOCIDADE ===")
print(segue_menor["motivo_codigo"].value_counts(normalize=True).round(3) * 100)

# 4. E quanto à dinâmica de paradas:
# Quantas paradas ocorreram por estouro de B3 ou secagem de B2?
paradas = (~rodando) & (rodando.shift(1, fill_value=True))
print(f"\nTotal de eventos de parada: {paradas.sum()}")

# Analisar os 60 segundos antes de cada parada
indices_parada = df[paradas].index
paradas_b3 = 0
paradas_b2 = 0
for idx in indices_parada:
    # olhar 6 amostras antes (1 minuto antes)
    janela = df.iloc[max(0, idx-6):idx]
    if len(janela) > 0:
        if janela["b3_pct"].max() >= 85:
            paradas_b3 += 1
        elif janela["b2_pct"].min() <= 15:
            paradas_b2 += 1

print(f"Paradas precedidas por saturação de saída (B3 >= 85%): {paradas_b3} de {paradas.sum()}")
print(f"Paradas precedidas por desabastecimento de entrada (B2 <= 15%): {paradas_b2} de {paradas.sum()}")

