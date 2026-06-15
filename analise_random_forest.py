import pandas as pd
import numpy as np
import os
import json
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
import matplotlib.pyplot as plt
import joblib

# =====================================================================
# 1. CONFIGURAÇÃO DOS ARQUIVOS E COLUNAS
# =====================================================================
ARQUIVO_CSV = "dados_completos_fabrica.csv"
ARQUIVO_CONFIG = "config_colunas.json"

COL_B1_DPL_UIP = "accumulation_percentage_DPL_UIP_null"  
COL_B2_UIP_ECH = "accumulation_percentage_UIP_ECH_null"  
COL_B3_ECH_PZ  = "accumulation_percentage_ECH_PZ_null"   
COL_B4_PZ_EPC  = "accumulation_percentage_PZ_EPC_null"   

COL_V_DPL = "speed_actual_cph_null_first_upstream_machine_1"
COL_V_UIP = "speed_actual_cph_null_eci_1"
COL_V_ROT = "speed_actual_cph_null_pasteurizer"
COL_V_EPC = "speed_actual_cph_null_first_downstream_machine_3"

COL_V_ECH = "speed_actual_cph_null_filler_1"       

if os.path.exists(ARQUIVO_CONFIG):
    with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)
        ARQUIVO_CSV = cfg.get("Arquivo_Dados", ARQUIVO_CSV)
        COL_B1_DPL_UIP = cfg.get("Col_Buffer_Antes_Entrada", COL_B1_DPL_UIP)
        COL_B2_UIP_ECH = cfg.get("Col_Buffer_Entrada", COL_B2_UIP_ECH)
        COL_B3_ECH_PZ  = cfg.get("Col_Buffer_Saida", COL_B3_ECH_PZ)
        COL_B4_PZ_EPC  = cfg.get("Col_Buffer_Pos_Saida", COL_B4_PZ_EPC)
        
        COL_V_DPL = cfg.get("COL_V_Antes_Entrada", COL_V_DPL)
        COL_V_UIP = cfg.get("COL_V_Entrada", COL_V_UIP)
        COL_V_ROT = cfg.get("COL_V_Saida", COL_V_ROT)
        COL_V_EPC = cfg.get("COL_V_Entrada_Pos_Saida", COL_V_EPC)

        COL_V_ECH = cfg.get("COL_V_ECH", COL_V_ECH)

print(f"Carregando dados de '{ARQUIVO_CSV}'...")
if not os.path.exists(ARQUIVO_CSV):
    print("Arquivo CSV não encontrado! Execute o otimizador primeiro para gerar os dados simulados/reais.")
    exit()

df = pd.read_csv(ARQUIVO_CSV)
df["Timestamp"] = pd.to_datetime(df["Timestamp"])
df.ffill(inplace=True)
df.fillna(0, inplace=True)

# Função auxiliar para garantir que as colunas existem
def get_col(col_name):
    return col_name if col_name in df.columns else None

b1 = get_col(COL_B1_DPL_UIP)
b2 = get_col(COL_B2_UIP_ECH)
b3 = get_col(COL_B3_ECH_PZ)
b4 = get_col(COL_B4_PZ_EPC)

v_dpl = get_col(COL_V_DPL)
v_uip = get_col(COL_V_UIP)
v_rot = get_col(COL_V_ROT)
v_epc = get_col(COL_V_EPC)

features = []
if b1: features.append(b1)
if b2: features.append(b2)
if b3: features.append(b3)
if b4: features.append(b4)
if v_dpl: features.append(v_dpl)
if v_uip: features.append(v_uip)
if v_rot: features.append(v_rot)
if v_epc: features.append(v_epc)

# =====================================================================
# 2. FEATURE ENGINEERING (Somente Estado Atual)
# =====================================================================
print("Selecionando apenas o estado exato dos Pulmões e Velocidades (Foto do Momento)...")

features_treino = []
for col in features:
    features_treino.append(col)

target = get_col(COL_V_ECH)
if not target:
    print("ERRO: Coluna da Velocidade da Enchedora não encontrada.")
    exit()

X = df[features_treino]
y = df[target]

# Limpar possíveis zeros ou NAs gerados pelo Pandas
X = X.copy()
X.fillna(0, inplace=True)

# =====================================================================
# 3. TREINAMENTO DO RANDOM FOREST
# =====================================================================
print("\nDividindo base em 80% Treino (Passado) e 20% Teste (Futuro)...")
# Como é temporal, não fazemos shuffle (o teste será as últimas horas do dataset)
split_idx = int(len(X) * 0.8)
X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
t_test = df["Timestamp"].iloc[split_idx:]

print(f"Treinando as Árvores de Decisão com {len(X_train)} amostras (Modo Pesado - Aguarde)...")
# Parâmetros mais agressivos (Hyperparameter Tuning)
rf = RandomForestRegressor(n_estimators=150, max_depth=25, min_samples_split=4, random_state=42, n_jobs=-1)
rf.fit(X_train, y_train)

# =====================================================================
# 4. INSIGHTS E RESULTADOS
# =====================================================================
print("\nTestando o modelo em dados que ele nunca viu...")
y_pred = rf.predict(X_test)
r2 = r2_score(y_test, y_pred)
mae = mean_absolute_error(y_test, y_pred)

print("\n" + "="*60)
print("  RESULTADOS PREDITIVOS (DINÂMICA DA LINHA)")
print("="*60)
print(f"➔ Acurácia de Previsão (R²): {r2*100:.1f}%")
print(f"   (Significa o quanto as oscilações da Enchedora são explicadas SOMENTE pelos pulmões)")
print(f"➔ Margem de Erro (MAE): ± {mae:.0f} Garrafas/Hora")
print("="*60)

print("\n📊 QUEM DITA O RITMO DA MÁQUINA? (Feature Importance)")
print("   (Descobrindo o principal gargalo logístico)\n")

importancias = rf.feature_importances_
ranking = pd.DataFrame({
    'Variavel': X_train.columns,
    'Importancia': importancias * 100
}).sort_values(by='Importancia', ascending=False)

nomes_legiveis = {}
for c in features_treino:
    # Traduz o nome da coluna para algo fácil de ler
    if "DPL" in c and "UIP" in c: nome_base = "B1 (Antes Entr.)"
    elif "UIP" in c and "ECH" in c: nome_base = "B2 (Entrada)"
    elif "ECH" in c and "PZ" in c: nome_base = "B3 (Saída)"
    elif "PZ" in c and "EPC" in c: nome_base = "B4 (Pós Saída)"
    elif "speed" in c:
        if "first_upstream" in c: nome_base = "Velocidade DPL"
        elif "eci_1" in c: nome_base = "Velocidade UIP"
        elif "pasteurizer" in c: nome_base = "Velocidade PZ/ROT"
        elif "first_downstream" in c: nome_base = "Velocidade EPC"
        else: nome_base = "Velocidade Outra"
    else: nome_base = c
    
    nomes_legiveis[c] = f"Estado Exato de {nome_base}"

ranking['Nome_Amigavel'] = ranking['Variavel'].map(nomes_legiveis)

for idx, row in ranking.head(8).iterrows():
    print(f" {row['Importancia']:5.1f}% | {row['Nome_Amigavel']}")

# =====================================================================
# 5. GERANDO GRÁFICOS VISUAIS
# =====================================================================
print("\nGerando Gráficos na pasta raiz...")

try:
    # 1. Gráfico de Importância
    plt.figure(figsize=(11, 6))
    top = ranking.head(10)
    plt.barh(top['Nome_Amigavel'][::-1], top['Importancia'][::-1], color='#3498db')
    plt.xlabel('Impacto (%) no Ritmo da Enchedora')
    plt.title('Descobrindo o Gargalo: Quais características dos Pulmões mais importam?')
    plt.grid(axis='x', linestyle='--', alpha=0.4)
    plt.tight_layout()
    plt.savefig('analise_rf_gargalo.png', dpi=120)
    plt.close()
    print(" ➔ 'analise_rf_gargalo.png' gerado com sucesso.")

    # 2. Gráfico da Previsão vs Real
    plt.figure(figsize=(14, 6))
    # Vamos pegar apenas as primeiras 2 horas do teste para o gráfico não ficar esmagado
    amostra = min(7200, len(y_test)) 
    plt.plot(t_test.iloc[:amostra], y_test.iloc[:amostra], label='Velocidade Real (Máquina)', color='#e74c3c', alpha=0.8)
    plt.plot(t_test.iloc[:amostra], y_pred[:amostra], label='Previsão do Random Forest', color='#2ecc71', alpha=0.8, linestyle='--')
    plt.title('Dinâmica Oculta: O ML conseguiu prever a velocidade lendo apenas o nível dos pulmões?')
    plt.ylabel('Velocidade (CPH)')
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.4)
    plt.tight_layout()
    plt.savefig('analise_rf_comportamento.png', dpi=120)
    plt.close()
    print(" ➔ 'analise_rf_comportamento.png' gerado com sucesso.")

except Exception as e:
    print(f"Erro ao gerar gráficos: {e}")

# =====================================================================
# 6. EXPORTAÇÃO DO MODELO
# =====================================================================
print("\nExportando modelo treinado...")
try:
    joblib.dump(rf, 'modelo_rf_velocidade.pkl')
    with open('features_rf.json', 'w', encoding='utf-8') as f:
        json.dump({"features": features_treino}, f, indent=4)
    print(" ➔ Modelo exportado como 'modelo_rf_velocidade.pkl'.")
    print(" ➔ Lista de features exportada como 'features_rf.json'.")
except Exception as e:
    print(f"Erro ao exportar modelo: {e}")

print("\nAnálise concluída!")
