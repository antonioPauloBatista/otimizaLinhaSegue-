# -*- coding: utf-8 -*-
"""
REPRODUÇÃO CONTRAFACTUAL NO DATASET HISTÓRICO
Executa o Gêmeo Digital Legado sobre o arquivo de dados reais de 36 horas
e compara o resultado do V4 contra o CLP Legado.
"""

import os
import pandas as pd
from modelo_gemeo_legado import GemeoDigitalLegado

def main():
    caminho_csv = "/home/antonio/Projetos/OtimizadorSegue/Panel Title-data-2026-10-03 21_55_56.csv"
    if not os.path.exists(caminho_csv):
        caminho_csv = "Panel Title-data-2026-10-03 21_55_56.csv"

    print(f"Carregando dataset: {caminho_csv}...")
    df = pd.read_csv(caminho_csv)
    df["Time"] = pd.to_datetime(df["Time"])
    df = df.sort_values("Time").reset_index(drop=True)
    df["dt"] = df["Time"].diff().dt.total_seconds().fillna(10.0).clip(upper=60)

    gemeo = GemeoDigitalLegado(
        velocidade_nominal=90000.0,
        capacidade_garrafas_b2=2800.0,
        capacidade_garrafas_b3=3500.0,
        limiar_corte_b3_pct=85.0,
        limiar_retomada_b3_pct=65.0,
        limiar_corte_b2_pct=15.0,
        limiar_retomada_b2_pct=35.0,
        ton_bloqueio_s=2.0,
        ton_retomada_s=2.0,
        tempo_rampa_subida_s=15.0,
        tempo_rampa_descida_s=8.0,
        tempo_ancoragem_parada_real_s=300.0,
        volume_garrafa_litros=0.355
    )

    v_legado_lista = []
    b2_virt_lista = []
    b3_virt_lista = []
    estado_legado_lista = []

    print(f"Simulando {len(df):,} ciclos contrafactuais...")
    for idx, row in df.iterrows():
        res = gemeo.atualizar(
            v_in=row["v_in_cph"],
            v_out=row["v_out_cph"],
            v_real=row["velocidade_real_cph"],
            b2_real=row["b2_pct"],
            b3_real=row["b3_pct"],
            status_maquina_real=row["status_maquina"],
            delta_t_s=row["dt"],
            timestamp=str(row["Time"])
        )
        v_legado_lista.append(res["v_legado_cph"])
        b2_virt_lista.append(res["b2_virt_pct"])
        b3_virt_lista.append(res["b3_virt_pct"])
        estado_legado_lista.append(res["estado_legado"])

    df["v_legado_cph"] = v_legado_lista
    df["b2_virt_pct"] = b2_virt_lista
    df["b3_virt_pct"] = b3_virt_lista
    df["estado_legado"] = estado_legado_lista

    print("\n=======================================================")
    print(" RESULTADO DA SIMULAÇÃO CONTRAFACTUAL (36 HORAS)")
    print("=======================================================")
    print(f"Produção Real Executada (V4): {gemeo.garrafas_real_total:,.0f} garrafas")
    print(f"Produção Gêmeo Legado:        {gemeo.garrafas_legado_total:,.0f} garrafas")
    delta_g = gemeo.garrafas_real_total - gemeo.garrafas_legado_total
    pct = (delta_g / gemeo.garrafas_legado_total) * 100 if gemeo.garrafas_legado_total > 0 else 0
    delta_hl = (delta_g * 0.355) / 100.0
    print(f"Saldo Incremental do V4:      {delta_g:+,.0f} garrafas ({pct:+.2f}%)")
    print(f"Saldo em Hectolitros:         {delta_hl:+,.2f} hL")
    print(f"Total de Microparadas Evitadas pelo V4: {gemeo.total_microparadas_evitadas} ocorrências")
    print(f"Tempo que o Legado ficou parado/bloqueado: {gemeo.tempo_legado_parado_s/3600.0:.2f} horas")
    print(f"Distribuição de Estados do CLP Legado:\n{df['estado_legado'].value_counts()}")

if __name__ == "__main__":
    main()
