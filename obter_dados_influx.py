#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script para buscar dados do InfluxDB usando a query Flux e salvar em formato CSV,
dividindo a busca em blocos de 1 dia para evitar timeouts e ir completando o arquivo.
"""

import argparse
import sys
import datetime
import pandas as pd
from influxdb_client import InfluxDBClient

def parse_time_arg(t_str):
    """
    Converte argumentos de tempo relativos ou absolutos para datetime UTC com fuso horário.
    """
    t_str = t_str.strip()
    now = datetime.datetime.now(datetime.timezone.utc)
    
    if t_str.lower() in ["now()", "v.timerangestop"]:
        return now
    
    if t_str.startswith("-"):
        try:
            val = int(t_str[1:-1])
            unit = t_str[-1].lower()
            if unit == 'd':
                return now - datetime.timedelta(days=val)
            elif unit == 'h':
                return now - datetime.timedelta(hours=val)
            elif unit == 'm':
                return now - datetime.timedelta(minutes=val)
        except Exception:
            pass

    try:
        import dateutil.parser
        dt = dateutil.parser.parse(t_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        raise ValueError(f"Não foi possível interpretar o formato de tempo: '{t_str}'")

def main():
    parser = argparse.ArgumentParser(description="Busca dados do InfluxDB em blocos de 1 dia e exporta para CSV.")
    parser.add_argument("--url", default="http://localhost:8086", help="URL do InfluxDB (padrão: http://localhost:8086)")
    parser.add_argument("--token", required=True, help="Token de autenticação do InfluxDB")
    parser.add_argument("--org", required=True, help="Organização do InfluxDB")
    parser.add_argument("--bucket", default="Segue", help="Bucket do InfluxDB (padrão: Segue)")
    parser.add_argument("--start", default="-7d", help="Início do intervalo de tempo (padrão: -7d)")
    parser.add_argument("--stop", default="now()", help="Fim do intervalo de tempo (padrão: now())")
    parser.add_argument("--output", default="dados_completos_fabrica.csv", help="Caminho do CSV de saída (padrão: dados_completos_fabrica.csv)")

    args = parser.parse_args()

    # Parseia datas de início e fim
    try:
        start_dt = parse_time_arg(args.start)
        stop_dt = parse_time_arg(args.stop)
    except Exception as e:
        print(f"❌ Erro nos parâmetros de tempo: {e}")
        sys.exit(1)

    if start_dt >= stop_dt:
        print("❌ A data de início (--start) deve ser anterior à data de fim (--stop).")
        sys.exit(1)

    # Conecta ao InfluxDB
    print("➔ Conectando ao InfluxDB...")
    try:
        client = InfluxDBClient(url=args.url, token=args.token, org=args.org)
        query_api = client.query_api()
    except Exception as e:
        print(f"❌ Erro ao conectar ao cliente InfluxDB: {e}")
        sys.exit(1)

    # Divide o intervalo em chunks de no máximo 1 dia
    intervals = []
    current = start_dt
    one_day = datetime.timedelta(days=1)

    while current < stop_dt:
        next_chunk = current + one_day
        if next_chunk > stop_dt:
            next_chunk = stop_dt
        intervals.append((current, next_chunk))
        current = next_chunk

    print(f"➔ Intervalo total: {start_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC a {stop_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"➔ Dividido em {len(intervals)} blocos de 1 dia.")

    accumulated_df = None

    try:
        for idx, (t_start, t_stop) in enumerate(intervals):
            t_start_str = t_start.strftime('%Y-%m-%dT%H:%M:%SZ')
            t_stop_str = t_stop.strftime('%Y-%m-%dT%H:%M:%SZ')
            print(f"\n➔ [{idx+1}/{len(intervals)}] Buscando dados de {t_start_str} até {t_stop_str}...")

            # Query Flux para o chunk atual
            flux_query = f'''
from(bucket: "{args.bucket}")
  |> range(start: {t_start_str}, stop: {t_stop_str})
  |> filter(fn: (r) => 
      r._measurement == "502" and
      (
        r._field == "accumulation_percentage" or
        r._field == "speed_actual_cph"
      )
  )
  |> aggregateWindow(every: 30s, fn: last, createEmpty: false)
  |> map(fn: (r) => ({{ 
      r with _value: float(v: r._value)
  }}))
  |> group()
  |> pivot(
      rowKey: ["_time"], 
      columnKey: ["_field", "buffer_name_local", "machine_name_generic"], 
      valueColumn: "_value"
  )
  |> sort(columns: ["_time"])
'''
            try:
                df_result = query_api.query_data_frame(flux_query)
                
                if isinstance(df_result, list):
                    chunk_df = pd.concat(df_result, ignore_index=True) if len(df_result) > 0 else pd.DataFrame()
                else:
                    chunk_df = df_result

            except Exception as e:
                print(f"   ⚠ Falha ao buscar bloco atual: {e}. Pulando...")
                continue

            if chunk_df.empty:
                print("   ℹ Nenhum dado retornado neste bloco.")
                continue

            # Limpeza do chunk atual
            if "_time" in chunk_df.columns:
                chunk_df = chunk_df.rename(columns={"_time": "Timestamp"})
            elif "time" in chunk_df.columns:
                chunk_df = chunk_df.rename(columns={"time": "Timestamp"})

            metadados = ["result", "table", "_measurement", "_start", "_stop"]
            chunk_df = chunk_df.drop(columns=[col for col in metadados if col in chunk_df.columns], errors="ignore")

            if "Timestamp" in chunk_df.columns:
                # Ordena colunas colocando Timestamp primeiro
                cols = ["Timestamp"] + [col for col in chunk_df.columns if col != "Timestamp"]
                chunk_df = chunk_df[cols]

            # Adiciona ao dataframe acumulado
            if accumulated_df is None:
                accumulated_df = chunk_df
            else:
                # pd.concat alinha as colunas por nome e preenche ausências com NaN
                accumulated_df = pd.concat([accumulated_df, chunk_df], ignore_index=True)

            # Remove duplicatas baseadas no Timestamp e ordena cronologicamente
            accumulated_df = accumulated_df.drop_duplicates(subset=["Timestamp"]).sort_values("Timestamp")

            # Salva o progresso atual no disco de forma incremental
            print(f"   ➔ Salvando progresso... Total acumulado: {len(accumulated_df)} linhas.")
            try:
                accumulated_df.to_csv(args.output, index=False)
            except Exception as e:
                print(f"   ❌ Erro ao salvar arquivo incremental: {e}")

    finally:
        client.close()

    if accumulated_df is not None and not accumulated_df.empty:
        print(f"\n➔ Extração concluída com sucesso! Total de {len(accumulated_df)} linhas salvas em '{args.output}'.")
    else:
        print("\n⚠ Nenhum dado foi encontrado em todo o intervalo solicitado.")

if __name__ == "__main__":
    main()
