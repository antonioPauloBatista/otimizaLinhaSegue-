#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste Simples e Direto de Software:
Valida se a sobrevelocidade (Fator_Sobremarcha) definida no config_colunas.json
está salva corretamente como fator_sprint no config_opc_v4.json.
Não depende de CLP, OPC online, rede ou telemetria em tempo real.
"""

import os
import sys
import json

DIR_ATUAL = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_CONFIG = os.path.join(DIR_ATUAL, "config_colunas.json")
ARQUIVO_OPC = os.path.join(DIR_ATUAL, "config_opc_v4.json")

def testar_sobrevelocidade_salva_no_opc():
    # 1. Verifica se os arquivos existem
    assert os.path.exists(ARQUIVO_CONFIG), f"Erro: {ARQUIVO_CONFIG} não encontrado!"
    assert os.path.exists(ARQUIVO_OPC), f"Erro: {ARQUIVO_OPC} não encontrado!"

    # 2. Lê config_colunas.json
    with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
        cfg_col = json.load(f)
    sobremarcha_origem = float(cfg_col.get("Fator_Sobremarcha", 0.0))

    # 3. Lê config_opc_v4.json
    with open(ARQUIVO_OPC, "r", encoding="utf-8") as f:
        cfg_opc = json.load(f)
    fator_salvo_opc = float(cfg_opc.get("controle", {}).get("fator_sprint", 0.0))

    # 4. Compara os valores
    print(f"-> Fator_Sobremarcha no config_colunas.json : {sobremarcha_origem}")
    print(f"-> fator_sprint no config_opc_v4.json      : {fator_salvo_opc}")

    assert abs(sobremarcha_origem - fator_salvo_opc) < 1e-4, (
        f"FALHA: A sobrevelocidade não está sincronizada! "
        f"config_colunas tem {sobremarcha_origem} mas config_opc_v4 tem {fator_salvo_opc}"
    )

    print("✅ TESTE PASSOU: A sobrevelocidade está salva e correta no config_opc_v4.json!")
    return True

if __name__ == "__main__":
    try:
        testar_sobrevelocidade_salva_no_opc()
        sys.exit(0)
    except AssertionError as e:
        print(f"❌ {e}")
        sys.exit(1)
