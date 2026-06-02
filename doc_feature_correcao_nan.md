# Feature: Proteção e Preenchimento Automático de Dados Faltantes (NaN)

## O Problema
Ao extrair dados temporais de sistemas como Grafana e InfluxDB, podem ocorrer instantes onde a conexão falha, ou o sensor não reportou dado naquele exato segundo. No CSV, isso se converte em valores vazios, lidos pelo Pandas como `NaN` (Not a Number).

Se a simulação encontrar um `NaN` durante o loop temporal para calcular os disparos de histerese (Start/Clear) ou cálculos de produção acumulada, toda a simulação retorna um erro (produzindo `NaN` como score final).

## A Solução (Forward Fill)
A correção injetada no script emula o comportamento de um historiador industrial: se a máquina não reportou sua velocidade/nível às 10:00:30, mas às 10:00:00 ela estava rodando a 90.000 CPH, assume-se que ela continua a 90.000 CPH.

O trecho de código inserido nos otimizadores foi:

```python
# Detecção automática do time step (intervalo em segundos entre amostras)
df["Timestamp"] = pd.to_datetime(df["Timestamp"])

# FIX: Preencher NaNs oriundos do outer join do Grafana para não quebrar a simulação
df.ffill(inplace=True)    # 1. Forward Fill: repete o último valor numérico válido para os buracos seguintes
df.fillna(0.0, inplace=True) # 2. Preenchimento Zero: Se o buraco for logo na linha 1 do CSV, substitui por 0.0
```

Com isso, evitamos resultados `-inf` na otimização CMA-ES e crashes prematuros no algoritmo Genético, tornando a simulação universal e blindada contra falhas no banco de dados.
