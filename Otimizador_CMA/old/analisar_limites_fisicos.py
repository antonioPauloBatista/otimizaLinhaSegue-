#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script de Análise dos Limites Físicos dos Buffers
Analisa o histórico do CSV da fábrica para identificar os níveis exatos de buffer 
onde a enchedora sofreu paradas de linha (falta ou acúmulo).
"""

import os
import json
import pandas as pd
import numpy as np

ARQUIVO_CONFIG = "config_colunas.json"
ARQUIVO_CSV = "dados_completos_fabrica.csv"

def main():
    print("==================================================================")
    print("      ANALISADOR AUTOMÁTICO DE LIMITES FÍSICOS DE PARADA          ")
    print("==================================================================")

    # 1. Carrega as configurações
    if os.path.exists(ARQUIVO_CONFIG):
        try:
            with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                ARQUIVO_CSV = cfg.get("Arquivo_Dados", "dados_completos_fabrica.csv")
                COL_B2_UIP_ECH = cfg.get("Col_Buffer_Entrada", "accumulation_percentage_UIP_ECH_null")
                COL_B3_ECH_PZ  = cfg.get("Col_Buffer_Saida", "accumulation_percentage_ECH_PZ_null")
                COL_V_ECH = cfg.get("COL_V_ECH", "speed_actual_cph_null_filler_1")
            print(f"➔ Configuração carregada com sucesso do arquivo '{ARQUIVO_CONFIG}'.")
        except Exception as e:
            print(f"⚠️ Erro ao carregar '{ARQUIVO_CONFIG}': {e}. Usando padrões.")
            return
    else:
        print(f"❌ Arquivo '{ARQUIVO_CONFIG}' não encontrado.")
        return

    # 2. Carrega os dados reais do CSV
    if not os.path.exists(ARQUIVO_CSV):
        print(f"❌ Arquivo de dados '{ARQUIVO_CSV}' não encontrado.")
        return

    print(f"➔ Lendo o arquivo de dados: '{ARQUIVO_CSV}'...")
    df = pd.read_csv(ARQUIVO_CSV)
    
    # Tratamento básico dos dados
    df.ffill(inplace=True)
    df.fillna(0.0, inplace=True)

    if COL_V_ECH not in df.columns or COL_B2_UIP_ECH not in df.columns or COL_B3_ECH_PZ not in df.columns:
        print("❌ Uma ou mais colunas de velocidade/buffer não foram encontradas no CSV.")
        return

    v_ech = df[COL_V_ECH].values
    b2 = df[COL_B2_UIP_ECH].values
    b3 = df[COL_B3_ECH_PZ].values

    # Filtra apenas os períodos onde a enchedora está PARADA (v = 0)
    paradas_idx = (v_ech == 0.0)
    total_amostras = len(df)
    total_paradas = int(paradas_idx.sum())

    if total_paradas == 0:
        print("⚠️ Nenhuma amostra de enchedora parada (velocidade = 0 CPH) foi encontrada no histórico.")
        return

    print(f"➔ Total de amostras no histórico: {total_amostras}")
    print(f"➔ Amostras com enchedora parada (0 CPH): {total_paradas} ({((total_paradas/total_amostras)*100):.1f}% do tempo)\n")

    b2_parado = b2[paradas_idx]
    b3_parado = b3[paradas_idx]

    # Vamos calcular uma tabela detalhada de percentis para ambos os buffers quando parados
    percentis = [0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100]
    
    print("------------------------------------------------------------------")
    print("📊 Tabela de Percentis dos Buffers com Enchedora Parada:")
    print("------------------------------------------------------------------")
    print(f"{'Percentil':<12} | {'B2 (Entrada/Falta)':<20} | {'B3 (Saída/Acúmulo)':<20}")
    print("-" * 60)
    for p in percentis:
        val_b2 = np.percentile(b2_parado, p)
        val_b3 = np.percentile(b3_parado, p)
        print(f"{p:<12}% | {val_b2:<20.2f}% | {val_b3:<20.2f}%")
    print("------------------------------------------------------------------\n")

    # Identificação inteligente:
    # 1. Paradas de Falta de garrafas: ocorrem quando o buffer de entrada está muito baixo.
    #    Olhamos o percentil 5% ou 10% dos menores valores de B2 quando parado.
    # 2. Paradas de Acúmulo: ocorrem quando o buffer de saída está muito alto.
    #    Olhamos o percentil 90% ou 95% dos maiores valores de B3 quando parado.
    
    sugestao_falta = np.percentile(b2_parado, 10)
    sugestao_acumulo = np.percentile(b3_parado, 90)

    # Arredondando para maior clareza
    sugestao_falta = round(sugestao_falta)
    sugestao_acumulo = round(sugestao_acumulo)

    print("==================================================================")
    print("💡 SUGESTÃO DETECTADA DE LIMITES FÍSICOS DE PARADA:")
    print("==================================================================")
    print(f"➔ Limite de Parada por Falta (Entrada)  : {sugestao_falta}% (baseado no P10 das paradas)")
    print(f"➔ Limite de Parada por Acúmulo (Saída)  : {sugestao_acumulo}% (baseado no P90 das paradas)")
    print("==================================================================")
    print("Nota: Verifique na tabela acima se esses limites fazem sentido. ")
    print("Se a enchedora para por falta com 15%, o P10 costuma ficar próximo disso.")
    print("Você pode definir esses valores no seu 'config_colunas.json':")
    print(f'  "Limite_Parada_Falta": {sugestao_falta}')
    print(f'  "Limite_Parada_Acumulo": {sugestao_acumulo}')
    print("==================================================================\n")

if __name__ == "__main__":
    main()
