#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import sys
import datetime
import requests
import json
import pandas as pd
import base64

def get_auth_headers(user, password):
    usr_pass = f"{user}:{password}".encode("utf-8")
    b64_val = base64.b64encode(usr_pass).decode("utf-8")
    return {
        "Authorization": f"Basic {b64_val}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }

def parse_time_arg(t_str):
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

def list_datasources(session, headers, url):
    print(f"➔ Conectando ao Grafana em: {url} para listar fontes de dados...")
    ds_url = f"{url.rstrip('/')}/api/datasources"
    try:
        res = session.get(ds_url, headers=headers, timeout=10)
        if res.status_code == 200:
            ds_list = res.json()
            influx_ds = [ds for ds in ds_list if ds.get("type") == "influxdb"]
            if not influx_ds:
                print("ℹ Nenhuma fonte de dados do tipo 'influxdb' foi encontrada.")
            else:
                print("\n=====================================================================")
                print("  FONTES DE DADOS INFLUXDB ENCONTRADAS NO GRAFANA")
                print("=====================================================================")
                for ds in influx_ds:
                    db_name = ds.get("database", "N/A")
                    print(f"  ID: {ds.get('id'):<4} | Nome: {ds.get('name'):<25} | Banco (DB): {db_name:<15}")
                print("=====================================================================\n")
        else:
            print(f"❌ Erro ao listar (Status: {res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ Falha de conexão: {e}")

def get_datasource_id(session, headers, url, ds_selector=None):
    ds_url = f"{url.rstrip('/')}/api/datasources"
    res = session.get(ds_url, headers=headers, timeout=10)
    if res.status_code == 200:
        influx_ds = [ds for ds in res.json() if ds.get("type") == "influxdb"]
        if not influx_ds:
            return None, None
            
        if ds_selector:
            for ds in influx_ds:
                if str(ds.get("id")) == str(ds_selector) or ds.get("name").lower() == str(ds_selector).lower():
                    return ds.get("id"), ds.get("database")
            print(f"   ⚠ AVISO: Datasource '{ds_selector}' não encontrado! Verifique o nome ou ID.")
            # Fallback for safety if the user provided an invalid ID
        return influx_ds[0].get("id"), influx_ds[0].get("database")
    return None, None

def build_influxql_query(config, start_time, stop_time):
    equipment_type = config.get("equipment_type")
    tags = config.get("tags", {})
    fields_config = config.get("fields", [])
    
    select_parts = []
    if isinstance(fields_config, dict):
        for key, value in fields_config.items():
            select_parts.append(f'"{key}"')
    elif isinstance(fields_config, list):
        for field in fields_config:
            select_parts.append(f'"{field}"')
            
    select_clause = ", ".join(select_parts)
    
    where_parts = []
    for k, v in tags.items():
        if not str(v).strip():
            continue
            
        if k == "rule":
            where_parts.append(f'"{k}"::tag =~ /{v}/')
        else:
            where_parts.append(f'"{k}"::tag = \'{v}\'')
            
    if where_parts:
        tags_clause = " AND ".join(where_parts)
        where_clause = f"({tags_clause}) AND time >= '{start_time}' AND time <= '{stop_time}'"
    else:
        where_clause = f"time >= '{start_time}' AND time <= '{stop_time}'"
    
    # Removido o GROUP BY time(1m) para obter o valor bruto exato
    query = f'SELECT {select_clause} FROM "{equipment_type}" WHERE {where_clause}'
    return query

def parse_influxql_response(json_data):
    results = json_data.get("results", [])
    if not results or "series" not in results[0]:
        return pd.DataFrame()
        
    series = results[0]["series"][0]
    columns = series.get("columns", [])
    values = series.get("values", [])
    
    df = pd.DataFrame(values, columns=columns)
    if "time" in df.columns:
        # Since epoch="ms" is used, time is in milliseconds
        tz_local = datetime.datetime.now().astimezone().tzinfo
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert(tz_local).dt.tz_localize(None)
        # Ordena pelo tempo para garantir que o preenchimento seja cronológico
        df = df.sort_values(by="time").reset_index(drop=True)
        
    # Preenche os "buracos" (NaN/None) repetindo o último valor válido lido (forward-fill)
    df = df.ffill()
    
    # Remove linhas duplicadas com exatamente o mesmo timestamp (mantendo a última, que já sofreu o ffill completo)
    if "time" in df.columns:
        df = df.drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)
    
    return df

def main():
    parser = argparse.ArgumentParser(description="Busca dados InfluxQL via JSON params")
    parser.add_argument("--list", action="store_true", help="Lista as fontes de dados do Grafana e sai")
    parser.add_argument("--ds", default=None, help="ID ou nome do Datasource InfluxDB")
    parser.add_argument("--json", default="parametros_query.json", help="Arquivo JSON com as queries")
    parser.add_argument("--start", default=None, help="Tempo inicial (ex: -7d, -24h)")
    parser.add_argument("--stop", default=None, help="Tempo final (ex: now())")
    
    args = parser.parse_args()
    
    # 1. Leitura do JSON localmente
    try:
        with open(args.json, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Arquivo JSON '{args.json}' não encontrado.")
        sys.exit(1)

    # 2. Interpretação das configurações do JSON vs Parâmetros da CLI
    if isinstance(json_data, dict) and "config" in json_data and "queries" in json_data:
        global_config = json_data.get("config", {})
        queries = json_data.get("queries", [])
    elif isinstance(json_data, list):
        # Fallback caso alguém ainda esteja usando o JSON antigo
        global_config = {
            "grafana_url": "http://172.23.224.145:3000",
            "grafana_user": "admin",
            "grafana_password": "!ambev2021",
            "database": "soda",
            "datasource_selector": "13",
            "start_time": "-7d",
            "stop_time": "now()"
        }
        queries = json_data
    else:
        print("❌ O formato do JSON é inválido. Precisa ter 'config' e 'queries'.")
        sys.exit(1)

    grafana_url = global_config.get("grafana_url")
    grafana_user = global_config.get("grafana_user")
    grafana_password = global_config.get("grafana_password")
    database = global_config.get("database")
    
    # CLI arguments override JSON config
    ds_selector = args.ds if args.ds else global_config.get("datasource_selector")
    start_time_str = args.start if args.start else global_config.get("start_time")
    stop_time_str = args.stop if args.stop else global_config.get("stop_time")

    try:
        start_dt = parse_time_arg(start_time_str)
        stop_dt = parse_time_arg(stop_time_str)
    except Exception as e:
        print(f"❌ Erro nos parâmetros de tempo: {e}")
        sys.exit(1)
        
    t_start_str = start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    t_stop_str = stop_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    print(f"➔ Período: {t_start_str} até {t_stop_str}")
    
    # 3. Prepara e imprime TODAS as queries antes de conectar no Grafana
    queries_preparadas = []
    print("\n=====================================================================")
    print("   PREPARANDO QUERIES (ANTES DA EXECUÇÃO)")
    print("=====================================================================")
    for idx, config in enumerate(queries):
        fields_config = config.get("fields", [])
        if isinstance(fields_config, list):
            print("   ℹ AVISO: Configuração sem Global Code nos fields. Executando usando apenas os nomes.")
        elif isinstance(fields_config, dict):
            if not any(bool(str(v).strip()) for v in fields_config.values()):
                print("   ℹ AVISO: Configuração sem Global Code (valores vazios) nos fields. Executando usando apenas os nomes.")
                
        query_str = build_influxql_query(config, t_start_str, t_stop_str)
        queries_preparadas.append(query_str)
        print(f"\n[{idx+1}/{len(queries)}] {config.get('description', 'Sem descrição')}")
        print("   " + "-"*60)
        print("   🔍 QUERY INFLUXQL:")
        print(f"   {query_str}")
        print("   " + "-"*60)
    print("=====================================================================\n")
    
    # 4. Inicia conexão e tenta executar
    session = requests.Session()
    headers = get_auth_headers(grafana_user, grafana_password)
    
    if args.list:
        list_datasources(session, headers, grafana_url)
        sys.exit(0)
        
    print(f"➔ Conectando ao Grafana em {grafana_url} para validar Datasource...")
    try:
        ds_id, ds_db = get_datasource_id(session, headers, grafana_url, ds_selector)
        if not ds_id:
            print(f"❌ Erro: Não foi possível encontrar Datasource InfluxDB (seletor: {ds_selector}) no Grafana.")
            sys.exit(1)
        if ds_db:
            database = ds_db
            print(f"   ℹ Usando database configurado no Grafana: '{database}'")
    except Exception as e:
        print(f"❌ Falha de conexão ao Grafana: {e}")
        print("ℹ As queries foram geradas acima, mas a execução falhou por falta de rede.")
        sys.exit(1)
        
    print(f"➔ Datasource ID {ds_id} selecionado. Iniciando requisições...")
    proxy_url = f"{grafana_url.rstrip('/')}/api/datasources/proxy/{ds_id}/query"
    
    all_dfs = []
    
    for idx, (config, query_str) in enumerate(zip(queries, queries_preparadas)):
        print(f"\n[{idx+1}/{len(queries)}] Executando na API...")
        
        payload = {
            "db": database,
            "q": query_str,
            "epoch": "ms"
        }
        
        try:
            response = session.post(proxy_url, headers=headers, data=payload, timeout=60)
            if response.status_code == 200:
                df = parse_influxql_response(response.json())
                if not df.empty:
                    # Renomeia as colunas usando o equipment_name para não dar conflito ao juntar
                    eq_name = config.get("tags", {}).get("equipment_name", f"Equip_{idx+1}")
                    rename_dict = {}
                    for col in df.columns:
                        if col != "time":
                            rename_dict[col] = f"{eq_name}_{col}"
                    df = df.rename(columns=rename_dict)
                    
                    all_dfs.append(df)
                    print(f"   ✓ {len(df)} registros retornados.")
                else:
                    print("   ℹ A query rodou com sucesso, mas retornou vazia (sem dados).")
            else:
                print(f"   ❌ Erro do Grafana (Status {response.status_code}): {response.text}")
        except Exception as e:
            print(f"   ❌ Falha ao buscar dados para a query [{idx+1}]: {e}")

    # 5. Junta todas as queries em um único DataFrame alinhado no tempo
    if all_dfs:
        print("\n➔ Juntando os dados, alinhando o tempo e preenchendo falhas...")
        final_df = all_dfs[0]
        for df in all_dfs[1:]:
            final_df = pd.merge(final_df, df, on="time", how="outer")
        
        # Ordena cronologicamente
        final_df = final_df.sort_values("time").reset_index(drop=True)
        # Preenche os valores faltantes repetindo o último valor válido de cada coluna
        final_df = final_df.ffill()
        
        output_csv = "dados_consolidados.csv"
        final_df.to_csv(output_csv, index=False)
        print(f"✅ Sucesso! {len(final_df)} linhas consolidadas salvas em '{output_csv}'")
    else:
        print("\n⚠ Nenhum dado foi retornado por nenhuma das queries. O CSV não foi gerado.")

if __name__ == "__main__":
    main()
