#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extrator de Dados do Grafana / InfluxDB V4 para Treinamento do Modelo Segue
Conecta na API do Grafana (proxy InfluxDB), extrai as séries temporais da linha,
reconstrói o DataFrame no formato tabular wide padronizado (com Timestamp) e salva
o arquivo CSV no formato exato esperado pelo otimizador matemático (CMA-ES).

Gerado automaticamente pelo modelo V4 em: 2026-10-05 19:04:52
Linha Alvo: 512 | Measurement: 512 | Bucket: Segue
"""

import os
import sys
import json
import base64
import datetime
import argparse
import requests
import pandas as pd
import numpy as np

# =====================================================================
# CONFIGURAÇÃO PADRÃO (Injetada automaticamente pelo Modelo V4)
# =====================================================================
DIR_ATUAL = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_CONFIG_COLUNAS = os.path.join(DIR_ATUAL, "config_colunas.json")
ARQUIVO_CONFIG_OPC = os.path.join(DIR_ATUAL, "config_opc_v4.json")

# Valores padrão de fallback injetados na compilação do template
GRAFANA_URL_DEFAULT = "http://10.46.12.163:3000"
GRAFANA_USER_DEFAULT = "admin"
GRAFANA_PASSWORD_DEFAULT = "!ambev2021"
GRAFANA_TOKEN_DEFAULT = ""
DATASOURCE_SELECTOR_DEFAULT = "17"
BUCKET_DEFAULT = "Segue"
MEASUREMENT_DEFAULT = "512"
ORG_DEFAULT = "ABinbev"
OUTPUT_FILE_DEFAULT = "dados_completos_fabrica.csv"

def carregar_configuracoes_locais():
    """Lê dinamicamente config_colunas.json e config_opc_v4.json para herdar parâmetros da linha."""
    cfg_final = {
        "url": GRAFANA_URL_DEFAULT,
        "user": GRAFANA_USER_DEFAULT,
        "password": GRAFANA_PASSWORD_DEFAULT,
        "token": GRAFANA_TOKEN_DEFAULT,
        "ds": DATASOURCE_SELECTOR_DEFAULT,
        "bucket": BUCKET_DEFAULT,
        "measurement": MEASUREMENT_DEFAULT,
        "org": ORG_DEFAULT,
        "output": OUTPUT_FILE_DEFAULT,
        "col_status": ""
    }

    if os.path.exists(ARQUIVO_CONFIG_COLUNAS):
        try:
            with open(ARQUIVO_CONFIG_COLUNAS, "r", encoding="utf-8") as f:
                c_col = json.load(f)
                if "Arquivo_Dados" in c_col and c_col["Arquivo_Dados"]:
                    cfg_final["output"] = c_col["Arquivo_Dados"]
                if "Grafana_URL" in c_col and c_col["Grafana_URL"]:
                    cfg_final["url"] = c_col["Grafana_URL"]
                if "Grafana_Bucket" in c_col and c_col["Grafana_Bucket"]:
                    cfg_final["bucket"] = c_col["Grafana_Bucket"]
                if "Grafana_Measurement" in c_col and c_col["Grafana_Measurement"]:
                    cfg_final["measurement"] = c_col["Grafana_Measurement"]
                if "Grafana_Datasource" in c_col and c_col["Grafana_Datasource"]:
                    cfg_final["ds"] = str(c_col["Grafana_Datasource"])
                if "Col_Status_Maquina" in c_col and c_col["Col_Status_Maquina"]:
                    cfg_final["col_status"] = str(c_col["Col_Status_Maquina"])
        except Exception as e:
            print(f"⚠️ Aviso ao carregar '{ARQUIVO_CONFIG_COLUNAS}': {e}")

    if os.path.exists(ARQUIVO_CONFIG_OPC):
        try:
            with open(ARQUIVO_CONFIG_OPC, "r", encoding="utf-8") as f:
                c_opc = json.load(f)
                tele = c_opc.get("telemetria_influx", {})
                if tele.get("grafana_url"):
                    cfg_final["url"] = tele["grafana_url"]
                if tele.get("database") or tele.get("bucket"):
                    cfg_final["bucket"] = tele.get("database") or tele.get("bucket")
                if tele.get("org"):
                    cfg_final["org"] = tele["org"]
                if tele.get("measurement_origem"):
                    cfg_final["measurement"] = tele["measurement_origem"]
                elif tele.get("measurement_destino") and cfg_final["measurement"] == "512":
                    cfg_final["measurement"] = tele["measurement_destino"].replace("_v4", "")
        except Exception as e:
            print(f"⚠️ Aviso ao carregar '{ARQUIVO_CONFIG_OPC}': {e}")

    return cfg_final


def parse_time_arg(t_str):
    t_str = t_str.strip()
    now = datetime.datetime.now(datetime.timezone.utc)
    if t_str.lower() in ["now()", "v.timerangestop"]:
        return now
    if t_str.startswith("-"):
        try:
            val = int(t_str[1:-1])
            unit = t_str[-1].lower()
            if unit == 'd': return now - datetime.timedelta(days=val)
            elif unit == 'h': return now - datetime.timedelta(hours=val)
            elif unit == 'm': return now - datetime.timedelta(minutes=val)
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
    """Reconstrói DataFrame wide a partir de retorno InfluxQL com formato: {campo}_{buffer}_{maquina}."""
    results = json_data.get("results", [])
    if not results or results[0].get("error"):
        if results and results[0].get("error"):
            print(f"   ❌ Erro InfluxDB: {results[0].get('error')}")
        return pd.DataFrame()

    series_list = results[0].get("series", [])
    if not series_list:
        return pd.DataFrame()

    df_list = []
    for s in series_list:
        tags = s.get("tags", {})
        buffer_name = tags.get("buffer_name_local")
        machine_name = tags.get("machine_name_generic")

        buffer_str = str(buffer_name).strip() if buffer_name else "null"
        machine_str = str(machine_name).strip() if machine_name else "null"

        columns = s.get("columns", [])
        values = s.get("values", [])
        if not values or not columns:
            continue

        temp_df = pd.DataFrame(values, columns=columns)
        time_col = None
        for col_cand in ["time", "Timestamp", "timestamp"]:
            if col_cand in temp_df.columns:
                time_col = col_cand
                break

        if time_col:
            temp_df["Timestamp"] = pd.to_datetime(temp_df[time_col])
            if temp_df["Timestamp"].dt.tz is not None:
                temp_df["Timestamp"] = temp_df["Timestamp"].dt.tz_convert(None)
            temp_df = temp_df.set_index("Timestamp")
            if time_col != "Timestamp":
                temp_df.drop(columns=[time_col], inplace=True, errors="ignore")
        else:
            continue

        rename_dict = {}
        for col in temp_df.columns:
            rename_dict[col] = f"{col}_{buffer_str}_{machine_str}"
        temp_df = temp_df.rename(columns=rename_dict)
        df_list.append(temp_df)

    if not df_list:
        return pd.DataFrame()

    final_df = pd.concat(df_list, axis=1)
    final_df = final_df.reset_index()
    return final_df


def parse_grafana_ds_response(json_data):
    """Trata resposta do /api/ds/query do Grafana (Data Frames modernos)."""
    results = json_data.get("results", {})
    if not results:
        return pd.DataFrame(), None

    result = next(iter(results.values()))
    if result.get("error"):
        return pd.DataFrame(), result.get("error")

    frames = result.get("frames", [])
    if not frames:
        return pd.DataFrame(), None

    all_dfs = []
    for frame in frames:
        schema = frame.get("schema", {})
        data = frame.get("data", {})
        fields = schema.get("fields", [])
        values = data.get("values", [])
        if not fields or not values or len(fields) != len(values):
            continue

        df_data = {}
        for field, vals in zip(fields, values):
            fname = field.get("name", "value")
            ftype = field.get("type", "")
            labels = field.get("labels") or {}
            b_lbl = labels.get("buffer_name_local", "null")
            m_lbl = labels.get("machine_name_generic", "null")

            if ftype == "time" or fname in ["time", "_time", "Timestamp"]:
                df_data["Timestamp"] = pd.to_datetime(vals, unit="ms" if isinstance(vals[0] if vals else 0, (int, float)) and (vals[0] if vals else 0) > 1e11 else None)
            else:
                col_formatada = f"{fname}_{b_lbl}_{m_lbl}" if (b_lbl != "null" or m_lbl != "null") else fname
                df_data[col_formatada] = vals

        if "Timestamp" in df_data:
            all_dfs.append(pd.DataFrame(df_data))

    if not all_dfs:
        return pd.DataFrame(), None

    merged = all_dfs[0]
    for other in all_dfs[1:]:
        merged = merged.merge(other, on="Timestamp", how="outer")
    return merged, None


def main():
    cfg_dinamica = carregar_configuracoes_locais()

    parser = argparse.ArgumentParser(description="Busca dados do Grafana/InfluxDB no formato exato de colunas do Otimizador V4.")
    parser.add_argument("--url", default=cfg_dinamica["url"], help="URL base do Grafana")
    parser.add_argument("--user", default=cfg_dinamica["user"], help="Usuário do Grafana")
    parser.add_argument("--password", default=cfg_dinamica["password"], help="Senha do Grafana")
    parser.add_argument("--token", default=cfg_dinamica["token"], help="Service Account Token do Grafana")
    parser.add_argument("--ds", default=cfg_dinamica["ds"], help="Nome ou ID do Data Source InfluxDB")
    parser.add_argument("--bucket", default=cfg_dinamica["bucket"], help="Bucket / Database do InfluxDB")
    parser.add_argument("--measurement", default=cfg_dinamica["measurement"], help="Nome da measurement (tabela)")
    parser.add_argument("--org", default=cfg_dinamica["org"], help="Organização do InfluxDB v2")
    parser.add_argument("--start", default="-7d", help="Janela inicial (ex: -7d, -24h, 2026-09-01)")
    parser.add_argument("--stop", default="now()", help="Janela final (ex: now(), 2026-09-15)")
    parser.add_argument("--output", default=cfg_dinamica["output"], help="Nome do arquivo CSV de saída")
    parser.add_argument("--status-col", default=cfg_dinamica["col_status"], help="Nome opcional da coluna/tag de status da máquina")
    parser.add_argument("--list", action="store_true", help="Lista os datasources InfluxDB disponíveis no Grafana")

    args = parser.parse_args()

    if not args.url.startswith("http://") and not args.url.startswith("https://"):
        args.url = f"http://{args.url}"
    args.url = args.url.rstrip("/")

    session = requests.Session()
    session.trust_env = False

    usr_pass = f"{args.user}:{args.password}".encode("utf-8") if (args.user and args.password) else b""
    b64_val = base64.b64encode(usr_pass).decode("utf-8") if usr_pass else ""
    basic_auth_header = f"Basic {b64_val}" if b64_val else ""

    headers = {"Accept": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    elif basic_auth_header:
        headers["Authorization"] = basic_auth_header

    if args.list:
        print(f"➔ Listando fontes de dados no Grafana: {args.url}...")
        try:
            res = session.get(f"{args.url}/api/datasources", headers=headers, timeout=10)
            if res.status_code == 200:
                print("Datasources InfluxDB encontrados:")
                for d in res.json():
                    if d.get("type") == "influxdb":
                        print(f"  ID: {d.get('id')} | UID: {d.get('uid')} | Nome: '{d.get('name')}' | Database: '{d.get('database')}'")
            else:
                print(f"❌ Erro ao listar: Status {res.status_code}")
        except Exception as e:
            print(f"❌ Falha de conexão: {e}")
        return

    print("=" * 75)
    print("   EXTRATOR DE DADOS GRAFANA / INFLUXDB - MODELO V4")
    print("=" * 75)
    print(f"➔ Destino CSV  : {args.output}")
    print(f"➔ Grafana URL  : {args.url}")
    print(f"➔ Database/Bkt : {args.bucket} | Measurement: {args.measurement}")
    print(f"➔ Janela Tempo : De {args.start} até {args.stop}")
    if args.status_col:
        print(f"➔ Status Máq.  : Coluna '{args.status_col}' incluída na query")
    print("=" * 75)

    # Auto-descoberta do Data Source
    ds_uid = ""
    ds_id = args.ds
    try:
        res = session.get(f"{args.url}/api/datasources", headers=headers, timeout=10)
        if res.status_code == 200:
            influx_ds = [d for d in res.json() if d.get("type") == "influxdb"]
            for d in influx_ds:
                if str(d.get("id")) == str(args.ds) or d.get("name") == str(args.ds) or str(d.get("uid")) == str(args.ds):
                    ds_uid = d.get("uid", "")
                    ds_id = d.get("id")
                    if d.get("database"): args.bucket = d.get("database")
                    break
            if not ds_uid and influx_ds:
                ds_uid = influx_ds[0].get("uid", "")
                ds_id = influx_ds[0].get("id")
                print(f"ℹ️ Datasource InfluxDB selecionado automaticamente: '{influx_ds[0].get('name')}' (UID: {ds_uid})")
    except Exception as e:
        print(f"⚠️ Aviso na listagem de datasources: {e}")

    try:
        t_start = parse_time_arg(args.start)
        t_stop = parse_time_arg(args.stop)
    except Exception as e:
        print(f"❌ Erro de formato de tempo: {e}")
        sys.exit(1)

    if t_start >= t_stop:
        print("❌ Data de início deve ser anterior ao fim.")
        sys.exit(1)

    # Blocos diários
    blocos = []
    curr = t_start
    dia = datetime.timedelta(days=1)
    while curr < t_stop:
        prox = min(curr + dia, t_stop)
        blocos.append((curr, prox))
        curr = prox

    print(f"➔ Período dividido em {len(blocos)} bloco(s) de 1 dia para evitar sobrecarga no Grafana.")

    campos_filtro = 'r._field == "accumulation_percentage" or r._field == "speed_actual_cph"'
    if args.status_col:
        campos_filtro += f' or r._field == "{args.status_col}"'

    dfs_acumulados = []
    for idx, (b_ini, b_fim) in enumerate(blocos, start=1):
        ini_iso = b_ini.strftime("%Y-%m-%dT%H:%M:%SZ")
        fim_iso = b_fim.strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"   [{idx}/{len(blocos)}] Baixando {ini_iso} até {fim_iso}...", end="", flush=True)

        flux_query = f'''from(bucket: "{args.bucket}")
  |> range(start: {ini_iso}, stop: {fim_iso})
  |> filter(fn: (r) => r._measurement == "{args.measurement}" and ({campos_filtro}))
  |> aggregateWindow(every: 30s, fn: last, createEmpty: false)
  |> group()
  |> pivot(rowKey: ["_time"], columnKey: ["_field", "buffer_name_local", "machine_name_generic"], valueColumn: "_value")
  |> sort(columns: ["_time"])'''

        payload = {
            "from": str(int(b_ini.timestamp() * 1000)),
            "to": str(int(b_fim.timestamp() * 1000)),
            "queries": [{
                "datasource": {"uid": ds_uid, "type": "influxdb"},
                "query": flux_query,
                "queryType": "flux",
                "refId": "A",
                "maxDataPoints": 100000,
                "intervalMs": 30000
            }]
        }

        try:
            r = session.post(f"{args.url}/api/ds/query", headers=headers, json=payload, timeout=90)
            if r.status_code == 200:
                df_bloco, err = parse_grafana_ds_response(r.json())
                if err:
                    print(f" ⚠️ Erro na resposta: {err}")
                elif not df_bloco.empty:
                    dfs_acumulados.append(df_bloco)
                    print(f" ✓ ({len(df_bloco)} linhas)")
                else:
                    print(" (vazio)")
            else:
                print(f" ❌ HTTP {r.status_code}")
        except Exception as e:
            print(f" ❌ Exceção: {e}")

    if not dfs_acumulados:
        print("❌ Nenhum dado foi retornado nas consultas. Verifique URL, token e se a medição existe no Grafana.")
        sys.exit(1)

    df_final = pd.concat(dfs_acumulados, ignore_index=True)
    df_final.drop_duplicates(subset=["Timestamp"], inplace=True)
    df_final.sort_values("Timestamp", inplace=True)

    caminho_saida = args.output if os.path.isabs(args.output) else os.path.join(DIR_ATUAL, args.output)
    df_final.to_csv(caminho_saida, index=False)

    print("\n" + "=" * 75)
    print(f"✅ Extração concluída com sucesso!")
    print(f"➔ Arquivo salvo: {caminho_saida}")
    print(f"➔ Total de amostras : {len(df_final):,} registros")
    print(f"➔ Colunas geradas   : {len(df_final.columns)}")
    for col in df_final.columns[:10]:
        print(f"   ↳ {col}")
    if len(df_final.columns) > 10:
        print(f"   ↳ ... e mais {len(df_final.columns) - 10} colunas.")
    print("=" * 75)
    print("➔ PRÓXIMO PASSO RECOMENDADO:")
    print(f"   python otimizador_velocidade_v4.py")
    print("=" * 75)

if __name__ == "__main__":
    main()
