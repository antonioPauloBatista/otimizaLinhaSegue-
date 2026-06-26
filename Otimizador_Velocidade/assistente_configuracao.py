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
    print("="*70)
    print("   ASSISTENTE INTERATIVO DE CONFIGURAÇÃO V3 (MÁQUINAS EM PARALELO)")
    print("="*70)
    print("Este assistente ajudará você a configurar o arquivo 'config_colunas.json'.")
    print("Para os nomes das colunas, use os nomes exatos do banco Grafana/CSV.\n")

    config = {}
    
    print("--- 1. CONFIGURAÇÃO DE PULMÕES (BUFFERS) ---")
    config["Col_Buffer_Antes_Entrada"] = perguntar_opcional("Coluna do Buffer ANTES da Entrada (Opcional)")
    config["Col_Buffer_Entrada"]       = perguntar("Coluna do Buffer de ENTRADA (Ex: accumulation_percentage_uip_to_ech_null)")
    config["Col_Buffer_Saida"]         = perguntar("Coluna do Buffer de SAÍDA (Ex: accumulation_percentage_ech_to_pz_null)")
    config["Col_Buffer_Pos_Saida"]     = perguntar_opcional("Coluna do Buffer PÓS-SAÍDA (Opcional)")

    print("\n--- 2. CONFIGURAÇÃO DE VELOCIDADE DAS MÁQUINAS ---")
    config["COL_V_Antes_Entrada"] = perguntar_opcional("Coluna de Vel. Máquina ANTES da Entrada (Opcional)")
    config["COL_V_Entrada"]       = perguntar("Coluna de Vel. Máquina de ENTRADA")
    
    print("\n[ MÁQUINA PRINCIPAL (ENCHEDORA / GARGALO) ]")
    qtd_ech = input("Quantas máquinas principais (Enchedoras) trabalham em paralelo neste trecho? [1]: ").strip()
    if not qtd_ech: qtd_ech = "1"
    
    if qtd_ech == "2":
        ech1 = perguntar("Coluna de Velocidade da Máquina 1 (Ex: speed_actual_cph_null_filler_1)")
        ech2 = perguntar("Coluna de Velocidade da Máquina 2 (Ex: speed_actual_cph_null_filler_2)")
        config["COL_V_ECH"] = f"{ech1},{ech2}"
        
        v1 = int(perguntar("Qual a Velocidade Nominal da Máquina 1? (Ex: 35000)"))
        v2 = int(perguntar("Qual a Velocidade Nominal da Máquina 2? (Ex: 35000)"))
        config["Velocidade_Nominal_ECH"] = v1 + v2
        print(f"   ➔ Velocidade Nominal Total combinada salva: {config['Velocidade_Nominal_ECH']} CPH")
    else:
        config["COL_V_ECH"] = perguntar("Coluna de Velocidade da Máquina Principal")
        config["Velocidade_Nominal_ECH"] = int(perguntar("Qual a Velocidade Nominal da Máquina? (Ex: 70000)"))

    print("\n[ MANUTENÇÃO ]")
    config["Limiar_Velocidade_Manutencao"] = int(perguntar("Qual a Velocidade de Manutenção?", default=str(config["Velocidade_Nominal_ECH"] // 2)))

    print("\n[ MÁQUINAS POSTERIORES ]")
    config["COL_V_Saida"]             = perguntar("Coluna de Vel. Máquina de SAÍDA")
    config["COL_V_Entrada_Pos_Saida"] = perguntar_opcional("Coluna de Vel. Máquina PÓS-SAÍDA (Opcional)")

    print("\n--- 3. PARÂMETROS DO OTIMIZADOR ---")
    config["Filtro_Minutos_Parada_Longa"] = int(perguntar("Filtro Minutos Parada Longa (Para limpeza de dados)", default="10"))
    config["Min_Modulacao"] = float(perguntar("Piso Inicial de Modulação para o Treino (Ex: 0.80 para 80%)", default="0.80"))
    config["Max_Modulacao"] = float(perguntar("Teto Máximo de Modulação (Ex: 1.00 para 100%)", default="1.00"))

    with open("config_colunas.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print("\n✅ ARQUIVO 'config_colunas.json' GERADO COM SUCESSO!")
    print("-> Você já pode rodar o 'otimizador_velocidade_v3.py' para analisar os dados com essas novas máquinas somadas.")

if __name__ == "__main__":
    main()
