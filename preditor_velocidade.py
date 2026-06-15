import joblib
import json
import os
import pandas as pd
import numpy as np

MODELO_ARQUIVO = 'modelo_rf_velocidade.pkl'
FEATURES_ARQUIVO = 'features_rf.json'

def carregar_modelo():
    if not os.path.exists(MODELO_ARQUIVO) or not os.path.exists(FEATURES_ARQUIVO):
        print("Erro: Arquivos do modelo não encontrados.")
        print("Execute primeiro o script 'analise_random_forest.py' para treinar e exportar o modelo.")
        exit(1)
        
    try:
        modelo = joblib.load(MODELO_ARQUIVO)
        with open(FEATURES_ARQUIVO, 'r', encoding='utf-8') as f:
            features = json.load(f)['features']
        return modelo, features
    except Exception as e:
        print(f"Erro ao carregar o modelo: {e}")
        exit(1)

def traduzir_nome(coluna):
    if "DPL" in coluna and "UIP" in coluna: return "Pulmão B1 (Antes Entrada) [%]"
    elif "UIP" in coluna and "ECH" in coluna: return "Pulmão B2 (Entrada) [%]"
    elif "ECH" in coluna and "PZ" in coluna: return "Pulmão B3 (Saída) [%]"
    elif "PZ" in coluna and "EPC" in coluna: return "Pulmão B4 (Pós Saída) [%]"
    elif "speed" in coluna:
        if "first_upstream" in coluna: return "Vel. Máquina DPL [CPH]"
        elif "eci_1" in coluna: return "Vel. Máquina UIP [CPH]"
        elif "pasteurizer" in coluna: return "Vel. Máquina ROT/PZ [CPH]"
        elif "first_downstream" in coluna: return "Vel. Máquina EPC [CPH]"
        else: return "Velocidade Outra [CPH]"
    else: return coluna

def modo_interativo():
    print("==========================================================")
    print(" PREDITOR DE VELOCIDADE DA ENCHEDORA (Coração da Linha)")
    print("==========================================================")
    print("Carregando modelo treinado...")
    modelo, features = carregar_modelo()
    print("Modelo carregado com sucesso!\n")
    
    print("Para sair, digite 'sair' ou pressione Ctrl+C.\n")
    
    while True:
        entradas = {}
        print("--- Informe os valores atuais do momento ---")
        
        try:
            for feat in features:
                nome_amigavel = traduzir_nome(feat)
                while True:
                    val = input(f"{nome_amigavel}: ")
                    if val.strip().lower() == 'sair':
                        print("Saindo...")
                        return
                    try:
                        entradas[feat] = float(val)
                        break
                    except ValueError:
                        print("Por favor, digite um número válido.")
            
            # Criar dataframe com os inputs
            df_input = pd.DataFrame([entradas], columns=features)
            
            # Realizar predição
            previsao = modelo.predict(df_input)[0]
            
            print("\n" + "="*50)
            print(f" ➔ PREVISÃO DA ENCHEDORA: {previsao:.0f} CPH")
            print("="*50 + "\n")
            
        except KeyboardInterrupt:
            print("\nSaindo...")
            break

if __name__ == "__main__":
    modo_interativo()
