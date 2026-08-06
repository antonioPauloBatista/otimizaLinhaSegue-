import pandas as pd
import sys

def main():
    try:
        df = pd.read_csv("Otimizador_CMA/dados_projetados_otimizado.csv", parse_dates=["Timestamp"])
    except Exception as e:
        print(f"Erro ao ler arquivo: {e}")
        sys.exit(1)

    if len(df) > 1:
        time_step = (df["Timestamp"].iloc[1] - df["Timestamp"].iloc[0]).total_seconds()
        if time_step <= 0: time_step = 1
    else:
        time_step = 1

    df["Prod_Real"] = (df["Velocidade_Real_Enchedora"] / 3600.0) * time_step
    df["Prod_Otimizada"] = (df["Velocidade_Simulada_Otimizada"] / 3600.0) * time_step
    
    # Agrupar por Dia
    df['Dia'] = df['Timestamp'].dt.date
    agrupado_dia = df.groupby('Dia')[['Prod_Real', 'Prod_Otimizada']].sum()
    agrupado_dia['Ganho (%)'] = ((agrupado_dia['Prod_Otimizada'] - agrupado_dia['Prod_Real']) / agrupado_dia['Prod_Real'] * 100).fillna(0)
    
    print("=======================================")
    print("      GANHO DIA A DIA (UNIDADES)       ")
    print("=======================================")
    for date, row in agrupado_dia.iterrows():
        print(f"[{date}]: Real: {int(row['Prod_Real']):,d} | Otimizada: {int(row['Prod_Otimizada']):,d} | Ganho: {row['Ganho (%)']:.1f}%")

    print("\n=======================================")
    print("    GANHO HORA A HORA (MÉDIA POR HORA) ")
    print("=======================================")
    # Agrupar por hora do dia
    df['Hora'] = df['Timestamp'].dt.hour
    agrupado_hora = df.groupby('Hora')[['Prod_Real', 'Prod_Otimizada']].sum() # sum across all days for that hour, or mean? 
    # Média de produção por aquela hora específica
    dias_unicos = df['Dia'].nunique()
    agrupado_hora = agrupado_hora / dias_unicos
    agrupado_hora['Ganho (%)'] = ((agrupado_hora['Prod_Otimizada'] - agrupado_hora['Prod_Real']) / agrupado_hora['Prod_Real'] * 100).fillna(0)

    for hr, row in agrupado_hora.iterrows():
        print(f"[{hr:02d}:00]: Real: {int(row['Prod_Real']):,d} | Otimizada: {int(row['Prod_Otimizada']):,d} | Ganho: {row['Ganho (%)']:.1f}%")

if __name__ == "__main__":
    main()
