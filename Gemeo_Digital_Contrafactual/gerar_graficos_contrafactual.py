# -*- coding: utf-8 -*-
"""
GERADOR DE GRÁFICOS DIÁRIOS DE VELOCIDADE (PADRÃO OFICIAL DO CONTROLADOR V4)
=============================================================================
Gera gráficos dia a dia em alta resolução contendo EXCLUSIVAMENTE as velocidades:
- Real Fábrica (Linha Vermelha)
- Otimizado V4 / Gêmeo Suave (Linha Verde)
- Faixas coloridas verticais de motivos operacionais:
  * Laranja: B3 Saída Cheia
  * Azul: B2 Entrada Baixa
  * Verde Claro: Sprint (> 100%)
  * Rosa: Parada Fábrica
- Linhas horizontais de referência: Nominal (90k CPH), Sprint (94.5k CPH), Piso (67.5k CPH)
- Resampling de 15 minutos para eliminação de ruídos de alta frequência
- Eixo horizontal com escala 24h completa (00:00 às 24:00) formatado de 3 em 3 horas
"""

import os
import shutil
import argparse
import matplotlib
os.environ["MPLCONFIGDIR"] = "/tmp"
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

def pintar_regioes(ax, timestamps, mascara, cor, rotulo, alpha=0.18):
    in_region, t_inicio, primeiro = False, None, True
    for t, ativo in zip(timestamps, mascara):
        if ativo and not in_region:
            t_inicio, in_region = t, True
        elif not ativo and in_region:
            ax.axvspan(t_inicio, t, alpha=alpha, color=cor, label=rotulo if primeiro else "_nolegend_")
            primeiro, in_region = False, False
    if in_region:
        ax.axvspan(t_inicio, timestamps.iloc[-1], alpha=alpha, color=cor, label=rotulo if primeiro else "_nolegend_")

def gerar_graficos_diarios(caminho_csv=None):
    if caminho_csv is None:
        caminho_csv = "/home/antonio/Projetos/OtimizadorSegue/Panel Title-data-2026-10-03 21_55_56.csv"
        if not os.path.exists(caminho_csv):
            caminho_csv = "Panel Title-data-2026-10-03 21_55_56.csv"

    print(f"Carregando dataset: {caminho_csv}...")
    df = pd.read_csv(caminho_csv)
    df["Time"] = pd.to_datetime(df["Time"])
    df = df.sort_values("Time").reset_index(drop=True)
    df["dt"] = df["Time"].diff().dt.total_seconds().fillna(10.0).clip(upper=60)

    # Identificar colunas de velocidade
    col_real = "velocidade_real_cph"
    col_v4 = "velocidade_v4_cph" if "velocidade_v4_cph" in df.columns else "v_atual_cph"

    v_nom = 90000.0
    if "v_nominal_cph" in df.columns and df["v_nominal_cph"].dropna().mean() > 50000:
        v_nom = float(df["v_nominal_cph"].dropna().iloc[0])

    # Resampling de 15 minutos (padrão oficial do otimizador V4)
    df_15 = df.set_index("Time").resample("15Min").mean(numeric_only=True).reset_index()
    df_15["Date"] = df_15["Time"].dt.date
    df["Date"] = df["Time"].dt.date

    dir_base = "/home/antonio/Projetos/OtimizadorSegue/Gemeo_Digital_Contrafactual"
    pasta_diarios = os.path.join(dir_base, "graficos_diarios")
    os.makedirs(pasta_diarios, exist_ok=True)

    dias = df_15["Date"].dropna().unique()
    print(f"Gerando gráficos de velocidades no padrão V4 para {len(dias)} dias...")
    caminhos_salvos = []

    for dia in dias:
        sub = df_15[df_15["Date"] == dia].copy()
        sub_raw = df[df["Date"] == dia].copy()
        if len(sub) < 5: continue

        # Cálculo de produção do dia em garrafas a partir dos dados brutos
        prod_real_dia = (sub_raw[col_real] * (sub_raw["dt"] / 3600.0)).sum()
        prod_v4_dia = (sub_raw[col_v4] * (sub_raw["dt"] / 3600.0)).sum()
        delta_dia = prod_v4_dia - prod_real_dia
        pct_dia = (delta_dia / prod_real_dia) * 100.0 if prod_real_dia > 0 else 0.0
        hl_dia = (delta_dia * 0.355) / 100.0

        fig, ax = plt.subplots(figsize=(16, 7.2))

        # Gatilhos operacionais para as faixas coloridas verticais
        gatilho_b3 = sub["b3_pct"] > 74.0 if "b3_pct" in sub.columns else pd.Series(False, index=sub.index)
        gatilho_b2 = sub["b2_pct"] < 26.0 if "b2_pct" in sub.columns else pd.Series(False, index=sub.index)
        gatilho_sprint = sub[col_v4] > (v_nom + 50.0)
        gatilho_parada = sub[col_real] < 5000.0

        pintar_regioes(ax, sub["Time"], gatilho_b3 & ~gatilho_b2, "#E67E22", "⬇ [20] B3 Saída Cheia", alpha=0.18)
        pintar_regioes(ax, sub["Time"], gatilho_b2 & ~gatilho_b3, "#2980B9", "⬇ [10] B2 Entrada Baixa", alpha=0.18)
        pintar_regioes(ax, sub["Time"], gatilho_sprint, "#27AE60", "▲ [1] Sprint (> 100%)", alpha=0.12)
        pintar_regioes(ax, sub["Time"], gatilho_parada, "#C0392B", "■ Parada Fábrica (< 5k CPH)", alpha=0.14)

        # Curvas de Velocidade
        ax.plot(sub["Time"], sub[col_real], label="Real Fábrica", color="#E74C3C", alpha=0.85, linewidth=1.8)
        ax.plot(sub["Time"], sub[col_v4], label="Otimizado V4 (Suave)", color="#2ECC71", alpha=0.95, linewidth=2.2)

        # Linhas de Referência
        ax.axhline(v_nom * 1.05, color="#8E44AD", linestyle=":", alpha=0.7, label=f"Sprint 105% ({v_nom*1.05:,.0f} CPH)")
        ax.axhline(v_nom, color="#27AE60", linestyle=":", alpha=0.7, label=f"Nominal 100% ({v_nom:,.0f} CPH)")
        ax.axhline(v_nom * 0.75, color="#F39C12", linestyle=":", alpha=0.7, label=f"Piso Modulação 75% ({v_nom*0.75:,.0f} CPH)")

        ax.set_title(
            f"Controle de Velocidade Otimizado V4 vs Real Fábrica — Linha 512 | Dia: {dia}\n"
            f"Produção Real: {prod_real_dia:,.0f} gf | Otimizado V4: {prod_v4_dia:,.0f} gf | "
            f"Ganho V4: {delta_dia:+,.0f} gf ({pct_dia:+.1f}%) | +{hl_dia:,.1f} hL",
            fontsize=13, fontweight="bold", pad=12
        )
        ax.set_ylabel("Velocidade (CPH)", fontsize=11, fontweight="bold")
        ax.set_ylim(-2000, max(v_nom * 1.18, 105000))

        # Eixo 24 Horas completo (00:00 às 24:00) com marcação de 3 em 3 horas
        t_start = pd.Timestamp(f"{dia} 00:00:00")
        t_end = pd.Timestamp(f"{dia} 23:59:59")
        ax.set_xlim(t_start, t_end)
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 3, 6, 9, 12, 15, 18, 21]))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.set_xlabel("Hora do Dia (HH:MM)", fontsize=11, fontweight="bold")

        ax.grid(True, linestyle="--", alpha=0.35)
        ax.legend(loc="upper right", fontsize=9, ncol=3, framealpha=0.92)

        plt.tight_layout()
        caminho_fig = os.path.join(pasta_diarios, f"contrafactual_velocidade_{dia}.png")
        plt.savefig(caminho_fig, dpi=160)
        plt.close(fig)
        caminhos_salvos.append(caminho_fig)
        print(f"  -> Salvo: {caminho_fig}")

    dir_artefatos = "/home/antonio/.gemini/antigravity/brain/58efa634-a43f-4bf7-9c51-ffc871990c24"
    if os.path.exists(dir_artefatos):
        for arq in caminhos_salvos:
            shutil.copy(arq, os.path.join(dir_artefatos, os.path.basename(arq)))
        print(f"Gráficos diários copiados para: {dir_artefatos}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gerador de gráficos diários de velocidade padrão oficial V4")
    parser.add_argument("--csv", type=str, default=None, help="Caminho do arquivo CSV")
    args = parser.parse_args()
    gerar_graficos_diarios(args.csv)
