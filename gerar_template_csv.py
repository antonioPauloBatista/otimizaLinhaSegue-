import pandas as pd
import numpy as np
import os

# Nome do arquivo CSV que o otimizador.py espera ler
NOME_ARQUIVO = "dados_completos_fabrica.csv"

def gerar_dados_fabrica():
    print(f"Criando template de dados históricos com simulação de paradas reais (CLP baseline)...")
    
    # Fixa a semente para repetibilidade
    np.random.seed(42)
    
    total_segundos = 7200  # 2 horas
    tempo = pd.date_range(start="2026-05-30 08:00:00", periods=total_segundos, freq="s")
    
    # Velocidade nominal da Enchedora
    cph_max_ech = 52700.0
    
    # Pre-aloca arrays de velocidade
    v_dpl = np.zeros(total_segundos)
    v_uip = np.zeros(total_segundos)
    v_ech = np.zeros(total_segundos)
    v_rot = np.zeros(total_segundos)
    v_epc = np.zeros(total_segundos)
    
    # Pre-aloca arrays dos buffers
    b1_dpl_uip = np.zeros(total_segundos)
    b2_uip_ech = np.zeros(total_segundos)
    b3_ech_pz  = np.zeros(total_segundos)
    b4_pz_epc  = np.zeros(total_segundos)
    
    # Inicializa buffers no nível operacional médio (50%)
    b1, b2, b3, b4 = 50.0, 50.0, 50.0, 50.0
    
    # Estados de parada da Enchedora no CLP sem otimização
    enchedora_parada_falta = False
    enchedora_parada_acumulo = False
    
    for i in range(total_segundos):
        # 1. Definir velocidade das máquinas externas baseada nos cenários de falha
        
        # Cenário A: Parada da Encaxotadora (EPC) de 15 minutos (segundos 1200 a 2100)
        if 1200 <= i < 2100:
            v_epc[i] = 0.0
            v_rot[i] = 12000.0  # Rotuladora reduz ritmo devido ao acúmulo
        else:
            v_epc[i] = cph_max_ech
            v_rot[i] = cph_max_ech
            
        # Cenário B: Falha na Despaletizadora (DPL) de 10 minutos (segundos 4000 a 4600)
        if 4000 <= i < 4600:
            v_dpl[i] = 0.0
            v_uip[i] = 10000.0  # Inspetor reduz ritmo devido a falta de produto
        else:
            v_dpl[i] = 70500.0  # DPL roda mais rápido para alimentar a linha
            v_uip[i] = 52700.0
            
        # Adiciona ruído nas velocidades das outras máquinas para realismo
        if v_dpl[i] > 0: v_dpl[i] += np.random.uniform(-400, 400)
        if v_uip[i] > 0: v_uip[i] += np.random.uniform(-200, 200)
        if v_rot[i] > 0: v_rot[i] += np.random.uniform(-200, 200)
        if v_epc[i] > 0: v_epc[i] += np.random.uniform(-200, 200)

        # 2. Simulação do CLP Físico Sem Otimização (Liga/Desliga direto)
        # Se B2 cair abaixo de 10%, a enchedora desliga por falta e só religa quando subir acima de 30%
        if b2 <= 10.0:
            enchedora_parada_falta = True
        elif b2 >= 30.0:
            enchedora_parada_falta = False
            
        # Se B3 subir acima de 90%, a enchedora desliga por acúmulo e só religa quando baixar de 70%
        if b3 >= 90.0:
            enchedora_parada_acumulo = True
        elif b3 <= 70.0:
            enchedora_parada_acumulo = False
            
        # Define a velocidade real da enchedora neste segundo
        if enchedora_parada_falta or enchedora_parada_acumulo:
            v_ech[i] = 0.0
        else:
            v_ech[i] = cph_max_ech + np.random.uniform(-100, 100) # Roda a 100% com leve ruído

        # 3. Evolução dinâmica dos pulmões (Garrafas que entram - Garrafas que saem)
        # Multiplicadores ajustam a velocidade de enchimento físico dos pulmões
        b1 += (v_dpl[i] - v_uip[i]) / 3600.0 * 0.4 + np.random.uniform(-0.05, 0.05)
        b2 += (v_uip[i] - v_ech[i]) / 3600.0 * 0.8 + np.random.uniform(-0.05, 0.05)
        b3 += (v_ech[i] - v_rot[i]) / 3600.0 * 0.8 + np.random.uniform(-0.05, 0.05)
        b4 += (v_rot[i] - v_epc[i]) / 3600.0 * 0.4 + np.random.uniform(-0.05, 0.05)
        
        # Limita buffers entre 0% e 100%
        b1 = np.clip(b1, 0.0, 100.0)
        b2 = np.clip(b2, 0.0, 100.0)
        b3 = np.clip(b3, 0.0, 100.0)
        b4 = np.clip(b4, 0.0, 100.0)
        
        b1_dpl_uip[i] = b1
        b2_uip_ech[i] = b2
        b3_ech_pz[i]  = b3
        b4_pz_epc[i]  = b4
        
    # 4. Criar Dataframe com o mapeamento exato
    df = pd.DataFrame({
        "Timestamp": tempo,
        "Buffer_DPL_UIP": np.round(b1_dpl_uip, 2),
        "Buffer_UIP_ECH": np.round(b2_uip_ech, 2),
        "Buffer_ECH_PZ":  np.round(b3_ech_pz, 2),
        "Buffer_PZ_EPC":  np.round(b4_pz_epc, 2),
        
        "Velocidade_DPL": np.round(v_dpl, 1),
        "Velocidade_UIP": np.round(v_uip, 1),
        "Velocidade_ECH": np.round(v_ech, 1),
        "Velocidade_ROT": np.round(v_rot, 1),
        "Velocidade_EPC": np.round(v_epc, 1)
    })
    
    df.to_csv(NOME_ARQUIVO, index=False)
    print(f"Sucesso! Novo arquivo '{NOME_ARQUIVO}' gerado simulando paradas reais.")

if __name__ == "__main__":
    gerar_dados_fabrica()
