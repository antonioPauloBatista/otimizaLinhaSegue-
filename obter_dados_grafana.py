#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script para buscar dados do InfluxDB utilizando o proxy da API do Grafana.
Isso é útil caso você não tenha acesso direto ao InfluxDB, mas tenha acesso ao Grafana.
Suporta fallback automático para InfluxQL caso o serviço Flux esteja desabilitado no InfluxDB.
"""

import argparse
import sys
import datetime
import requests
import io
import base64
import json
import pandas as pd

# =====================================================================
# CONFIGURAÇÃO DE ACESSO AO GRAFANA (Edite estes valores)
# =====================================================================
GRAFANA_URL = "http://10.91.7.221:3000"         # URL base do Grafana (ex: http://seu-grafana.com)

# --- MÉTODO DE AUTENTICAÇÃO ---
# Coloque aqui seu usuário e senha de acesso ao Grafana
GRAFANA_USER = "admin"                             # Seu login/e-mail do Grafana
GRAFANA_PASSWORD = "!ambev2021"                         # Sua senha do Grafana

# TOKEN DO GRAFANA (Recomendado - evita conflito de autenticação com InfluxDB)
# Crie em: Grafana -> Administration -> Service Accounts -> Add token
# Ou em versões antigas: Configuration -> API Keys
# Cole o token aqui (ex: glsa_xxxxxxxxxx) e deixe USER/PASSWORD preenchidos para o --list
GRAFANA_TOKEN = ""                            # Cole seu Service Account Token aqui

# --- SELEÇÃO DO BANCO (Opcional - Descoberta Automática) ---
# Você pode deixar vazio ("") e o script vai achar o banco InfluxDB sozinho!
# Se tiver mais de um e quiser especificar, coloque o NOME (ex: "InfluxDB-1") ou o ID numérico (ex: 3).
DATASOURCE_SELECTOR = "17"                      

# --- CONFIGURAÇÃO DA QUERY ---
BUCKET = "Segue"                              # Nome do Bucket no InfluxDB
MEASUREMENT = "501"                        # Nome da measurement (tabela) no InfluxDB
ORG = "ABinbev"                               # Organização (opcional/requerido se InfluxDB for v2)
START_TIME = "-30d"                            # Intervalo inicial (ex: -7d, -24h)
STOP_TIME = "now()"                           # Intervalo final (ex: now(), ou data ISO)
OUTPUT_FILE = "dados_completos_fabrica.csv"   # Nome do arquivo CSV gerado
# =====================================================================


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


def parse_influxql_json(json_data):
    """
    Trata a estrutura JSON de retorno do InfluxQL e reconstrói o DataFrame pivotado
    no formato esperado: {campo}_{buffer}_{maquina}.
    """
    results = json_data.get("results", [])
    if not results:
        return pd.DataFrame()
    
    # Verifica se o InfluxDB retornou um erro interno na query
    error = results[0].get("error")
    if error:
        print(f"   ❌ Erro interno do InfluxDB: {error}")
        return pd.DataFrame()
        
    series_list = results[0].get("series", [])
    if not series_list:
        return pd.DataFrame()
        
    df_list = []
    for s in series_list:
        tags = s.get("tags", {})
        buffer_name = tags.get("buffer_name_local")
        machine_name = tags.get("machine_name_generic")
        
        # Formata tags vazias como "null" para manter compatibilidade com o CSV do Grafana
        buffer_str = str(buffer_name).strip() if buffer_name else "null"
        machine_str = str(machine_name).strip() if machine_name else "null"
        
        columns = s.get("columns", [])
        values = s.get("values", [])
        
        if not values or not columns:
            continue
            
        temp_df = pd.DataFrame(values, columns=columns)
        
        # Converte a coluna de tempo para datetime e limpa fuso horário
        if "time" in temp_df.columns:
            time_col = pd.to_datetime(temp_df["time"])
            if time_col.dt.tz is not None:
                time_col = time_col.dt.tz_convert(None)
            temp_df["time"] = time_col
            temp_df = temp_df.set_index("time")
        elif "Timestamp" in temp_df.columns:
            time_col = pd.to_datetime(temp_df["Timestamp"])
            if time_col.dt.tz is not None:
                time_col = time_col.dt.tz_convert(None)
            temp_df["Timestamp"] = time_col
            temp_df = temp_df.set_index("Timestamp")
        else:
            continue
            
        # Renomeia colunas de valores para bater com as chaves do config_colunas.json
        rename_dict = {}
        for col in temp_df.columns:
            rename_dict[col] = f"{col}_{buffer_str}_{machine_str}"
            
        temp_df = temp_df.rename(columns=rename_dict)
        df_list.append(temp_df)
        
    if not df_list:
        return pd.DataFrame()
        
    # Junta todas as séries alinhando os índices de tempo
    final_df = pd.concat(df_list, axis=1)
    
    # Reseta o index trazendo a coluna Timestamp de volta
    final_df = final_df.reset_index()
    final_df = final_df.rename(columns={"index": "Timestamp", "time": "Timestamp"})
    
    return final_df


def parse_grafana_ds_response(json_data):
    """
    Trata a resposta do endpoint /api/ds/query do Grafana (formato Data Frames).
    Reconstrói o DataFrame no formato de tabela wide (pivotada).
    """
    results = json_data.get("results", {})
    if not results:
        return pd.DataFrame(), None

    # Pega o primeiro resultado (refId "A")
    result = next(iter(results.values()))
    
    # Verifica erro no resultado
    if result.get("error"):
        return pd.DataFrame(), result.get("error")
    if result.get("status") not in (None, 200):
        return pd.DataFrame(), f"Status {result.get('status')}"

    frames = result.get("frames", [])
    if not frames:
        return pd.DataFrame(), None

    all_dfs = []
    for frame in frames:
        schema = frame.get("schema", {})
        data   = frame.get("data", {})
        fields = schema.get("fields", [])
        values = data.get("values", [])

        if not fields or not values or len(fields) != len(values):
            continue

        df_data = {}
        time_col = None
        for field, vals in zip(fields, values):
            fname = field.get("name", "value")
            ftype = field.get("type", "")
            if ftype == "time":
                time_col = fname
                # Converte milissegundos para datetime
                df_data["Timestamp"] = pd.to_datetime(vals, unit="ms")
            else:
                df_data[fname] = vals

        if "Timestamp" not in df_data:
            continue

        all_dfs.append(pd.DataFrame(df_data))

    if not all_dfs:
        return pd.DataFrame(), None

    # Se vieram múltiplos frames, junta por Timestamp
    if len(all_dfs) == 1:
        return all_dfs[0], None

    merged = all_dfs[0]
    for other in all_dfs[1:]:
        merged = merged.merge(other, on="Timestamp", how="outer")
    return merged, None


def main():
    parser = argparse.ArgumentParser(description="Busca dados do InfluxDB via API do Grafana e exporta para CSV.")
    parser.add_argument("--url", default=GRAFANA_URL, help="URL base do Grafana")
    parser.add_argument("--user", default=GRAFANA_USER, help="Usuário do Grafana")
    parser.add_argument("--password", default=GRAFANA_PASSWORD, help="Senha do Grafana")
    parser.add_argument("--ds", default=DATASOURCE_SELECTOR, help="Nome ou ID do Data Source")
    parser.add_argument("--bucket", default=BUCKET, help="Bucket/Database do InfluxDB")
    parser.add_argument("--measurement", default=MEASUREMENT, help="Nome da measurement (tabela) no InfluxDB")
    parser.add_argument("--org", default=ORG, help="Organização do InfluxDB")
    parser.add_argument("--start", default=START_TIME, help="Início do tempo")
    parser.add_argument("--stop", default=STOP_TIME, help="Fim do tempo")
    parser.add_argument("--output", default=OUTPUT_FILE, help="Caminho do CSV de saída")
    parser.add_argument("--token", default=GRAFANA_TOKEN, help="Service Account Token do Grafana (recomendado)")
    parser.add_argument("--list", action="store_true", help="Lista as fontes de dados do tipo InfluxDB cadastradas no Grafana e sai.")

    args = parser.parse_args()

    # Garante que a URL possui o protocolo http:// ou https://
    if not args.url.startswith("http://") and not args.url.startswith("https://"):
        args.url = f"http://{args.url}"
    args.url = args.url.rstrip("/")

    session = requests.Session()
    # Ignora variáveis de ambiente de proxy que costumam causar timeouts em scripts Python
    session.trust_env = False

    # Prepara cabeçalhos base com Basic Auth (para uso na API admin do Grafana)
    if not (args.user and args.password) and not args.token:
        print("❌ Erro: Configure GRAFANA_USER/GRAFANA_PASSWORD ou GRAFANA_TOKEN no script.")
        sys.exit(1)

    usr_pass = f"{args.user}:{args.password}".encode("utf-8") if (args.user and args.password) else b""
    b64_val = base64.b64encode(usr_pass).decode("utf-8") if usr_pass else ""
    basic_auth_header = f"Basic {b64_val}" if b64_val else ""

    # Determina o header de autorização para chamadas ao proxy do datasource:
    # Prioridade 1: Token do Service Account (nunca é repassado ao InfluxDB)
    # Prioridade 2: Tentar criar API Key temporária via Basic Auth
    # Prioridade 3: Fallback para Basic Auth direto (pode falhar no proxy)
    api_key_id = None
    bearer_token = args.token if args.token else None

    if bearer_token:
        print("➔ Usando Token de Service Account do Grafana configurado no script.")
    elif basic_auth_header:
        # Tenta criar API Key temporária
        api_key_name = "otimizador-tmp-key"
        try:
            key_url = f"{args.url.rstrip('/')}/api/auth/keys"
            key_res = session.post(
                key_url,
                headers={"Authorization": basic_auth_header, "Content-Type": "application/json"},
                json={"name": api_key_name, "role": "Viewer"},
                timeout=10
            )
            if key_res.status_code == 200:
                key_data = key_res.json()
                bearer_token = key_data.get("key")
                api_key_id = key_data.get("id")
                print(f"➔ API Key temporária criada (ID: {api_key_id}). Será removida ao final.")
            elif key_res.status_code == 409:
                # Chave já existe — lista e pega o ID para recriar
                try:
                    list_res = session.get(key_url, headers={"Authorization": basic_auth_header}, timeout=10)
                    if list_res.status_code == 200:
                        for k in list_res.json():
                            if k.get("name") == api_key_name:
                                session.delete(f"{key_url}/{k['id']}", headers={"Authorization": basic_auth_header}, timeout=10)
                                break
                except Exception:
                    pass
                key_res2 = session.post(
                    key_url,
                    headers={"Authorization": basic_auth_header, "Content-Type": "application/json"},
                    json={"name": api_key_name, "role": "Viewer"},
                    timeout=10
                )
                if key_res2.status_code == 200:
                    key_data = key_res2.json()
                    bearer_token = key_data.get("key")
                    api_key_id = key_data.get("id")
                    print(f"➔ API Key temporária recriada (ID: {api_key_id}).")
            else:
                print(f"   ⚠ Criação de API Key não suportada ({key_res.status_code}). Usando Basic Auth como fallback.")
                print(f"   ℹ DICA: Crie um Service Account Token no Grafana e coloque em GRAFANA_TOKEN no script.")
        except Exception as e:
            print(f"   ⚠ Erro ao criar API Key: {e}")

    # Prepara cabeçalhos da requisição
    headers = {
        "Accept": "application/csv",
        "Content-Type": "application/flux"
    }

    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
        print("➔ Usando Bearer Token — credenciais NÃO serão repassadas ao InfluxDB.")
    else:
        headers["Authorization"] = basic_auth_header
        print("➔ Fallback para Basic Auth (pode causar falha no proxy InfluxDB).")


    # Se o usuário pediu apenas para listar
    if args.list:
        print(f"➔ Conectando ao Grafana em: {args.url} para listar fontes de dados...")
        try:
            ds_url = f"{args.url.rstrip('/')}/api/datasources"
            ds_response = session.get(ds_url, headers=headers, timeout=10)
            if ds_response.status_code == 200:
                ds_list = ds_response.json()
                influx_ds = [ds for ds in ds_list if ds.get("type") == "influxdb"]
                if not influx_ds:
                    print("ℹ Nenhuma fonte de dados do tipo 'influxdb' foi encontrada.")
                else:
                    print("\n=====================================================================")
                    print("  FONTES DE DADOS INFLUXDB ENCONTRADAS NO GRAFANA")
                    print("=====================================================================")
                    for ds in influx_ds:
                        db_name = ds.get("database", "N/A")
                        print(f"  ID: {ds.get('id'):<4} | Nome: {ds.get('name'):<25} | Banco (DB): {db_name:<15} | Tipo: {ds.get('type')}")
                    print("=====================================================================\n")
            else:
                print(f"❌ Erro ao listar fontes de dados (Status: {ds_response.status_code}): {ds_response.text}")
        except Exception as e:
            print(f"❌ Falha ao conectar ao Grafana: {e}")
        sys.exit(0)

    print(f"➔ Conectando ao Grafana em: {args.url}")

    # --- DESCOBERTA AUTOMÁTICA DO DATASOURCE ---
    ds_id = None
    ds_database = None
    try:
        ds_url = f"{args.url.rstrip('/')}/api/datasources"
        ds_response = session.get(ds_url, headers=headers, timeout=10)
        
        if ds_response.status_code == 200:
            ds_list = ds_response.json()
            influx_ds = [ds for ds in ds_list if ds.get("type") == "influxdb"]
            
            if not influx_ds:
                print("❌ Erro: Nenhuma fonte de dados do tipo 'influxdb' foi encontrada cadastrada no seu Grafana.")
                sys.exit(1)
                
            target_ds = None
            selector = str(args.ds).strip()
            
            if selector:
                # Tenta buscar por ID numérico ou por Nome
                for ds in influx_ds:
                    if str(ds.get("id")) == selector or ds.get("name").lower() == selector.lower():
                        target_ds = ds
                        break
            
            if target_ds is None:
                # Pega o primeiro banco InfluxDB encontrado
                target_ds = influx_ds[0]
                if selector:
                    print(f"⚠ Não encontramos banco InfluxDB correspondente a '{selector}'.")
                print(f"➔ Banco InfluxDB detectado automaticamente: '{target_ds.get('name')}' (ID: {target_ds.get('id')})")
            else:
                print(f"➔ Utilizando banco InfluxDB: '{target_ds.get('name')}' (ID: {target_ds.get('id')})")
                
            ds_id = target_ds.get("id")
            ds_uid = target_ds.get("uid", "")
            ds_database = target_ds.get("database")
            print(f"   UID: {ds_uid}")
        else:
            print(f"⚠ Não foi possível listar os bancos automaticamente (Status Grafana: {ds_response.status_code}).")
    except Exception as e:
        print(f"⚠ Falha ao conectar ao Grafana para listar os bancos: {e}")

    # Define o database a ser usado (sobrescrevendo o bucket configurado no script se for auto-detectado)
    if ds_database:
        print(f"➔ Nome do Banco (Database) configurado no Grafana: '{ds_database}'")
        args.bucket = ds_database
    else:
        print(f"➔ Usando nome do banco configurado no script: '{args.bucket}'")

    # Fallback se a auto-descoberta falhou mas o usuário especificou um ID numérico no script
    if ds_id is None:
        try:
            ds_id = int(args.ds)
            print(f"➔ Usando ID numérico fornecido como fallback: {ds_id}")
        except ValueError:
            print("❌ Erro: Não foi possível determinar o ID do banco. Por favor, forneça o ID numérico do Data Source.")
            sys.exit(1)

    # Endpoints do proxy (tenta a API moderna /resources/ e tem fallback para /proxy/)
    base = args.url.rstrip('/')
    if 'ds_uid' in dir() and ds_uid:
        # Grafana 8+ — endpoint por UID (preferencial, não repassa credenciais ao datasource)
        proxy_url_flux_uid    = f"{base}/api/datasources/uid/{ds_uid}/resources/api/v2/query"
        proxy_url_influxql_uid = f"{base}/api/datasources/uid/{ds_uid}/resources/query"
    else:
        proxy_url_flux_uid    = None
        proxy_url_influxql_uid = None
    # Fallback por ID numérico (legado)
    proxy_url_flux    = f"{base}/api/datasources/proxy/{ds_id}/api/v2/query"
    proxy_url_influxql = f"{base}/api/datasources/proxy/{ds_id}/query"
    
    params = {}
    if args.org:
        params["org"] = args.org

    # Parseia datas
    try:
        start_dt = parse_time_arg(args.start)
        stop_dt = parse_time_arg(args.stop)
    except Exception as e:
        print(f"❌ Erro nos parâmetros de tempo: {e}")
        sys.exit(1)

    if start_dt >= stop_dt:
        print("❌ A data de início (--start) deve ser anterior à data de fim (--stop).")
        sys.exit(1)

    # Divide o intervalo em blocos de 1 dia para evitar timeouts no Grafana
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
    print(f"➔ Dividido em {len(intervals)} blocos de 1 dia via API do Grafana.")

    accumulated_df = None
    use_influxql = False

    for idx, (t_start, t_stop) in enumerate(intervals):
        t_start_str = t_start.strftime('%Y-%m-%dT%H:%M:%SZ')
        t_stop_str = t_stop.strftime('%Y-%m-%dT%H:%M:%SZ')
        print(f"\n➔ [{idx+1}/{len(intervals)}] Buscando dados de {t_start_str} até {t_stop_str}...")

        chunk_df = pd.DataFrame()
        success = False

        if not use_influxql:
            # Query Flux principal (idêntica à que você usa no Grafana Explore)
            flux_query = f'''from(bucket: "{args.bucket}")
  |> range(start: {t_start_str}, stop: {t_stop_str})
  |> filter(fn: (r) =>
      r._measurement == "{args.measurement}" and
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
  |> sort(columns: ["_time"])'''

            # -------------------------------------------------------
            # Método 1: /api/ds/query — endpoint nativo que o Grafana
            # usa internamente para painéis e Explore.
            # -------------------------------------------------------
            try:
                ds_query_url = f"{args.url.rstrip('/')}/api/ds/query"
                from_ms = int(t_start.timestamp() * 1000)
                to_ms   = int(t_stop.timestamp()  * 1000)
                ds_payload = {
                    "from": str(from_ms),
                    "to":   str(to_ms),
                    "queries": [
                        {
                            "datasource": {
                                "uid":  ds_uid,
                                "type": "influxdb"
                            },
                            "query":         flux_query,
                            "queryType":     "flux",
                            "refId":         "A",
                            "maxDataPoints": 100000,
                            "intervalMs":    30000
                        }
                    ]
                }
                ds_headers = headers.copy()
                ds_headers["Content-Type"] = "application/json"
                ds_headers["Accept"]       = "application/json"

                response = session.post(
                    ds_query_url,
                    headers=ds_headers,
                    params={"ds_type": "influxdb"},
                    json=ds_payload,
                    timeout=90
                )

                if response.status_code == 200:
                    chunk_df, err = parse_grafana_ds_response(response.json())
                    if err:
                        print(f"   ⚠ [ds/query] Erro na query: {err}")
                    elif not chunk_df.empty:
                        success = True
                    else:
                        print("   ℹ [ds/query] Nenhum dado neste bloco.")
                        success = True
                else:
                    print(f"   ⚠ [ds/query] Status {response.status_code}: {response.text[:300]}")
            except Exception as e:
                print(f"   ⚠ Erro em ds/query: {e}")

        # Se InfluxQL foi acionado

        if use_influxql:
            # Query InfluxQL equivalente agrupando a cada 30 segundos
            query_str = f'''
SELECT last("accumulation_percentage") AS "accumulation_percentage", 
       last("speed_actual_cph") AS "speed_actual_cph" 
FROM "{args.measurement}" 
WHERE time >= '{t_start_str}' AND time < '{t_stop_str}' 
GROUP BY time(30s), "buffer_name_local", "machine_name_generic"
'''
            payload = {
                "db": args.bucket,
                "q": query_str
            }
            
            influxql_headers = headers.copy()
            influxql_headers["Content-Type"] = "application/x-www-form-urlencoded"
            influxql_headers["Accept"] = "application/json"

            try:
                response = session.post(proxy_url_influxql, headers=influxql_headers, data=payload, timeout=60)
                if response.status_code == 200:
                    json_data = response.json()
                    chunk_df = parse_influxql_json(json_data)
                    success = True
                    if chunk_df.empty:
                        # Se veio vazio, vamos printar a resposta JSON para fins de depuração
                        print("   ℹ Resposta bruta (JSON) vazia ou sem séries válidas.")
                        try:
                            import json
                            print(f"   DEBUG JSON: {json.dumps(json_data)[:400]}")
                        except Exception:
                            print(f"   DEBUG RAW: {str(json_data)[:400]}")
                else:
                    print(f"   ⚠ Falha na requisição InfluxQL (Status {response.status_code}): {response.text[:200]}. Pulando...")
                    continue
            except Exception as e:
                print(f"   ⚠ Erro ao buscar via InfluxQL: {e}. Pulando...")
                continue

        if not success or chunk_df.empty:
            print("   ℹ Nenhum dado obtido neste bloco.")
            continue

        # Limpeza e formatação de colunas
        if "_time" in chunk_df.columns:
            chunk_df = chunk_df.rename(columns={"_time": "Timestamp"})
        elif "time" in chunk_df.columns:
            chunk_df = chunk_df.rename(columns={"time": "Timestamp"})

        # Remove colunas indesejadas geradas pelo Influx
        metadados = ["result", "table", "_measurement", "_start", "_stop"]
        chunk_df = chunk_df.drop(columns=[col for col in metadados if col in chunk_df.columns], errors="ignore")

        # Garante o Timestamp na primeira coluna
        if "Timestamp" in chunk_df.columns:
            cols = ["Timestamp"] + [col for col in chunk_df.columns if col != "Timestamp"]
            chunk_df = chunk_df[cols]

        if accumulated_df is None:
            accumulated_df = chunk_df
        else:
            accumulated_df = pd.concat([accumulated_df, chunk_df], ignore_index=True)

        # Remove duplicatas
        accumulated_df = accumulated_df.drop_duplicates(subset=["Timestamp"]).sort_values("Timestamp")
        print(f"   ➔ Salvando progresso... Total acumulado: {len(accumulated_df)} linhas.")
        accumulated_df.to_csv(args.output, index=False)

    if accumulated_df is not None and not accumulated_df.empty:
        print(f"\n➔ Extração via Grafana concluída com sucesso! Total de {len(accumulated_df)} linhas salvas em '{args.output}'.")
    else:
        print("\n⚠ Nenhum dado foi encontrado em todo o intervalo solicitado via Grafana.")

    # Limpeza: Remove a API Key temporária criada no início
    if api_key_id:
        try:
            del_url = f"{args.url.rstrip('/')}/api/auth/keys/{api_key_id}"
            session.delete(del_url, headers={"Authorization": basic_auth_header}, timeout=10)
            print(f"➔ API Key temporária removida do Grafana (ID: {api_key_id}).")
        except Exception:
            pass


if __name__ == "__main__":
    main()
