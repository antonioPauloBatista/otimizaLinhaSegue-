#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Assistente Interativo de Configuração V4 (Controle de Velocidade)
Permite configurar buffers, velocidades de máquinas vizinhas, parâmetros de filtros e proteção mecânica.
"""

import json
import os

def perguntar(mensagem, default=""):
    if default:
        res = input(f"{mensagem} [{default}]: ").strip()
        return res if res else default
    else:
        while True:
            res = input(f"{mensagem}: ").strip()
            if res: return res
            print("Este campo é obrigatório.")

def perguntar_opcional(mensagem, default=""):
    if default:
        res = input(f"{mensagem} [{default}] (Deixe em branco para pular): ").strip()
        return res if res else default
    else:
        return input(f"{mensagem} (Deixe em branco para pular): ").strip()

def main():
    print("="*75)
    print("   ASSISTENTE INTERATIVO DE CONFIGURAÇÃO V4 (CONTROLE DE VELOCIDADE)")
    print("="*75)
    print("Este assistente ajudará você a configurar o arquivo 'config_colunas.json'.")
    print("Para os nomes das colunas, use os nomes exatos do banco Grafana/CSV.\n")

    config = {}
    config["Arquivo_Dados"] = perguntar("Nome do arquivo CSV de dados", default="dados_completos_fabrica.csv")

    print("\n--- 1. CONFIGURAÇÃO DE PULMÕES (BUFFERS) ---")
    config["Col_Buffer_Antes_Entrada"] = perguntar_opcional("Coluna Buffer ANTES da Entrada (B1 - Opcional)", default="accumulation_percentage_pre_eci_null")
    config["Col_Buffer_Entrada"]       = perguntar("Coluna Buffer de ENTRADA (B2)", default="accumulation_percentage_eci_to_filler_null")
    config["Col_Buffer_Saida"]         = perguntar("Coluna Buffer de SAÍDA (B3)", default="accumulation_percentage_filler_to_pasteurizer_null")
    config["Col_Buffer_Pos_Saida"]     = perguntar_opcional("Coluna Buffer PÓS-SAÍDA (B4 - Opcional)", default="accumulation_percentage_post_pasteurizer_null")

    print("\n--- 2. VELOCIDADE DAS MÁQUINAS (BALANÇO DE MASSA FEEDFORWARD) ---")
    config["COL_V_Antes_Entrada"] = perguntar_opcional("Coluna Vel. Máquina ANTES da Entrada (Opcional)", default="speed_actual_cph_null_first_upstream_machine_1")
    config["COL_V_Entrada"]       = perguntar("Coluna Vel. Máquina de ENTRADA (ex: ECI)", default="speed_actual_cph_null_eci_1")
    
    print("\n[ MÁQUINA PRINCIPAL (ENCHEDORA / FILLER) ]")
    qtd_ech = input("Quantas máquinas principais trabalham em paralelo neste trecho? [1]: ").strip()
    if not qtd_ech: qtd_ech = "1"
    
    if qtd_ech == "2":
        ech1 = perguntar("Coluna Velocidade Máquina 1 (Ex: speed_actual_cph_null_filler_1)")
        ech2 = perguntar("Coluna Velocidade Máquina 2 (Ex: speed_actual_cph_null_filler_2)")
        config["COL_V_ECH"] = f"{ech1},{ech2}"
        v1 = int(perguntar("Velocidade Nominal Máquina 1 (Ex: 30000)"))
        v2 = int(perguntar("Velocidade Nominal Máquina 2 (Ex: 30000)"))
        config["Velocidade_Nominal_ECH"] = v1 + v2
        print(f"   ➔ Velocidade Nominal combinada: {config['Velocidade_Nominal_ECH']} CPH")
    else:
        config["COL_V_ECH"] = perguntar("Coluna Velocidade Enchedora", default="speed_actual_cph_null_filler_1")
        config["Velocidade_Nominal_ECH"] = int(perguntar("Velocidade Nominal da Enchedora (CPH)", default="60000"))

    print("\n[ MÁQUINAS POSTERIORES (SAÍDA E JUSANTE) ]")
    config["COL_V_Saida"]             = perguntar("Coluna Vel. Máquina de SAÍDA (ex: Pasteurizador)", default="speed_actual_cph_null_pasteurizer")
    config["COL_V_Entrada_Pos_Saida"] = perguntar_opcional("Coluna Vel. Máquinas PÓS-SAÍDA (Opcional, separe por vírgula se paralelas)", default="speed_actual_cph_null_first_downstream_machine_1,speed_actual_cph_null_first_downstream_machine_2")

    print("\n--- 3. PROTEÇÃO MECÂNICA E SOBREVELOCIDADE ---")
    config["Limiar_Velocidade_Manutencao"] = int(perguntar("Limiar de Velocidade para Manutenção/Quebra (CPH)", default=str(config["Velocidade_Nominal_ECH"] // 2)))
    config["Max_Rampa_CPH_Passo"] = float(perguntar("Taxa Máxima de Rampa Mecânica (CPH por passo de 30s)", default="3000.0"))
    config["Fator_Sobremarcha"] = float(perguntar("Fator de Sobrevelocidade / Sprint (Ex: 1.02 para 102%)", default="1.02"))
    config["Min_Modulacao"] = float(perguntar("Piso Mínimo de Modulação Inicial (Ex: 0.75 para 75%)", default="0.75"))
    config["Max_Modulacao"] = float(perguntar("Teto de Modulação Padrão", default="1.00"))
    config["Filtro_Minutos_Parada_Longa"] = int(perguntar("Janela de Parada Longa Externa (minutos)", default="10"))

    print("\n--- 4. FILTROS DE DADOS 100% SOFTWARE (ANTI-RUÍDO) ---")
    config["Janela_Mediana_Buffer"] = int(perguntar("Janela do Filtro Mediano (amostras, ex: 3)", default="3"))
    config["Alpha_Filtro_Buffer"] = float(perguntar("Fator Alpha do Filtro EWMA de Densidade [0.1 - 1.0]", default="0.65"))

    with open("config_colunas.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print("\n✅ ARQUIVO 'config_colunas.json' GERADO COM SUCESSO!")
    print("➔ Você pode agora executar 'python otimizador_velocidade_v4.py' para treinar e simular a nova lógica.")

if __name__ == "__main__":
    main()
