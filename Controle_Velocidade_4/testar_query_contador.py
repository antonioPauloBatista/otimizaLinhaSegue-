#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Diagnóstico e Teste da Query do Contador Físico via Grafana
Lê 'parametros_query.json', localiza o Datasource no Grafana (ID e UID)
e executa a query tanto pela API nativa /api/ds/query quanto pelo proxy.
"""

import json
import os
import sys
import base64
import requests

def main():
    print("=" * 80)
    print("   DIAGNÓSTICO E TESTE DA QUERY DO CONTADOR FÍSICO (GRAFANA / INFLUXDB)")
    print("=" * 80)

    # 1. Localizar e carregar parametros_query.json
    caminhos = [
        "parametros_query.json",
        os.path.join("..", "Dados de json", "parametros_query.json"),
        os.path.join("Dados de json", "parametros_query.json"),
        os.path.join("..", "parametros_query.json")
    ]
    caminho_json = None
    for c in caminhos:
        if os.path.exists(c):
            caminho_json = c
            break

    if not caminho_json:
        print("❌ Arquivo 'parametros_query.json' não encontrado em nenhum dos diretórios padrão!")
        sys.exit(1)

    print(f"➔ Arquivo de configuração carregado: '{caminho_json}'")
    with open(caminho_json, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    glob = cfg.get("config", {})
    queries = cfg.get("queries", [])
    if not queries:
        print("❌ Nenhuma query configurada em 'queries'!")
        sys.exit(1)

    q0 = queries[0]
    eq_type = q0.get("equipment_type", "Filler")
    tags = q0.get("tags", {})
    eq_name = tags.get("equipment_name", "")
    fields = q0.get("fields", {})
    if isinstance(fields, dict):
        field_name = list(fields.keys())[0] if fields else ""
    elif isinstance(fields, list):
        field_name = fields[0] if fields else ""
    else:
        field_name = str(fields)

    grafana_url = glob.get("grafana_url", "http://172.23.224.145:3000").rstrip("/")
    user = glob.get("grafana_user", "admin")
    pwd = glob.get("grafana_password", "!ambev2021")
    database = glob.get("database", "SODA Template")
    ds_selector = str(glob.get("datasource_selector", "8"))

    print(f"   ↳ Grafana URL : {grafana_url}")
    print(f"   ↳ Usuário     : {user}")
    print(f"   ↳ Database    : '{database}'")
    print(f"   ↳ Seletor DS  : '{ds_selector}'")
    print(f"   ↳ Equipamento : '{eq_name}' (Tipo: '{eq_type}')")
    print(f"   ↳ Campo       : '{field_name}'")

    # Autenticação
    usr_pass = f"{user}:{pwd}".encode("utf-8")
    basic_auth = f"Basic {base64.b64encode(usr_pass).decode('utf-8')}"
    headers_auth = {"Authorization": basic_auth}

    session = requests.Session()
    session.trust_env = False

    # 2. Conexão ao Grafana e listagem dos datasources
    print(f"\n➔ [Etapa 1] Conectando ao Grafana em: {grafana_url}/api/datasources ...")
    try:
        r = session.get(f"{grafana_url}/api/datasources", headers=headers_auth, timeout=5)
        if r.status_code != 200:
            print(f"❌ Falha de autenticação ou conexão com Grafana (Status HTTP {r.status_code}): {r.text[:150]}")
            sys.exit(1)
        datasources = r.json()
        print(f"  ✅ Conectado com sucesso! {len(datasources)} fontes de dados cadastradas.")
    except Exception as e:
        print(f"❌ Erro ao conectar no Grafana: {e}")
        sys.exit(1)

    print("\n--------------------------------------------------------------------------------")
    print(f"  {'ID':<4} | {'NOME':<22} | {'TIPO':<10} | {'UID':<16} | {'DATABASE'}")
    print("--------------------------------------------------------------------------------")
    ds_encontrado = None
    for ds in datasources:
        ds_id = str(ds.get("id"))
        ds_nome = str(ds.get("name"))
        ds_tipo = str(ds.get("type"))
        ds_uid = str(ds.get("uid", ""))
        ds_db = str(ds.get("database", ""))
        
        marcador = ""
        # Verifica correspondência com o seletor ou banco
        if ds_id == ds_selector or ds_nome.lower() == ds_selector.lower():
            marcador = " ◄◄ [SELECIONADO NO JSON]"
            ds_encontrado = ds
        elif not ds_encontrado and ("soda" in ds_nome.lower() or "soda" in ds_db.lower()):
            marcador = " ◄◄ [CANDIDATO SODA]"
            ds_encontrado = ds

        print(f"  {ds_id:<4} | {ds_nome:<22} | {ds_tipo:<10} | {ds_uid:<16} | {ds_db}{marcador}")
    print("--------------------------------------------------------------------------------")

    if not ds_encontrado:
        print(f"⚠️ Datasource '{ds_selector}' não encontrado diretamente. Usando ID '{ds_selector}'.")
        ds_target_id = ds_selector
        ds_target_uid = ""
        ds_target_name = "SODA Template"
    else:
        ds_target_id = str(ds_encontrado.get("id"))
        ds_target_uid = str(ds_encontrado.get("uid", ""))
        ds_target_name = str(ds_encontrado.get("name", ""))
        print(f"\n🎯 Datasource Selecionado: ID={ds_target_id} | Nome='{ds_target_name}' | UID='{ds_target_uid}'")

    # 3. Montar queries InfluxQL
    query_principal = f'SELECT last("{field_name}") FROM "{eq_type}" WHERE ("equipment_name"::tag = \'{eq_name}\')'
    queries_teste = [
        ("Query Exata do Painel Grafana", query_principal),
        ("Sem ::tag", f'SELECT last("{field_name}") FROM "{eq_type}" WHERE ("equipment_name" = \'{eq_name}\')'),
        ("Com Janela now() - 1h", f'SELECT last("{field_name}") FROM "{eq_type}" WHERE ("equipment_name"::tag = \'{eq_name}\') AND time >= now() - 1h'),
        ("ORDER BY time DESC LIMIT 1", f'SELECT "{field_name}" FROM "{eq_type}" WHERE ("equipment_name"::tag = \'{eq_name}\') ORDER BY time DESC LIMIT 1')
    ]

    # 4. TESTE A: API Nativa do Grafana (/api/ds/query) - Idêntico ao Painel do Navegador
    print("\n" + "=" * 80)
    print("   [MÉTODO 1] TESTANDO VIA API NATIVA DO GRAFANA (/api/ds/query)")
    print("   (Mesma rota e protocolo que o painel do seu navegador executou)")
    print("=" * 80)

    sucesso_metodo_1 = False
    ds_query_url = f"{grafana_url}/api/ds/query"
    headers_api = {
        "Authorization": basic_auth,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    ds_ref_options = []
    if ds_target_uid:
        ds_ref_options.append({"uid": ds_target_uid})
    ds_ref_options.append({"name": ds_target_name})
    ds_ref_options.append({"id": int(ds_target_id) if ds_target_id.isdigit() else ds_target_id})

    for desc, q_sql in queries_teste:
        print(f"\n➔ Testando: {desc}")
        print(f"   SQL: {q_sql}")

        for ds_ref in ds_ref_options:
            for fmt in ["table", "time_series"]:
                payload = {
                    "from": "now-1h",
                    "to": "now",
                    "queries": [
                        {
                            "datasource": {"type": "influxdb", **ds_ref},
                            "rawQuery": True,
                            "query": q_sql,
                            "refId": "A",
                            "resultFormat": fmt
                        }
                    ]
                }
                try:
                    resp = session.post(ds_query_url, headers=headers_api, json=payload, timeout=8)
                    if resp.status_code == 200:
                        j_data = resp.json()
                        # Extrai valor do DataFrame
                        results = j_data.get("results", {})
                        for r_val in results.values():
                            frames = r_val.get("frames", [])
                            for f in frames:
                                values = f.get("data", {}).get("values", [])
                                schema_fields = [fld.get("name") for fld in f.get("schema", {}).get("fields", [])] if "schema" in f else []
                                if values and len(values) >= 2:
                                    col_vals = values[-1]
                                    for v in reversed(col_vals):
                                        if v is not None:
                                            try:
                                                v_float = float(v)
                                                print(f"   🎉 SUCESSO ABSOLUTO VIA /api/ds/query!")
                                                print(f"   ✅ VALOR DO CONTADOR LIDO: {v_float:,.0f} garrafas")
                                                print(f"   ↳ Referência DS usada: {ds_ref} | Formato: {fmt}")
                                                print(f"   ↳ Colunas: {schema_fields or len(values)} | Linhas: {len(col_vals)}")
                                                sucesso_metodo_1 = True
                                                break
                                            except (ValueError, TypeError):
                                                pass
                                if sucesso_metodo_1:
                                    break
                            if sucesso_metodo_1:
                                break
                    if sucesso_metodo_1:
                        break
                except Exception as err:
                    pass
            if sucesso_metodo_1:
                break
        if sucesso_metodo_1:
            break

    # 5. TESTE B: Proxy InfluxQL (/api/datasources/proxy/{id}/query)
    print("\n" + "=" * 80)
    print("   [MÉTODO 2] TESTANDO VIA PROXY INFLUXQL (/api/datasources/proxy/{id}/query)")
    print("=" * 80)

    headers_proxy = {
        "Authorization": basic_auth,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }

    sucesso_metodo_2 = False
    proxy_url = f"{grafana_url}/api/datasources/proxy/{ds_target_id}/query"
    dbs_para_testar = [database, "soda"] if database.lower() != "soda" else ["soda", "SODA Template"]

    for db_test in dbs_para_testar:
        print(f"\n➔ Testando com Banco: '{db_test}'")
        for desc, q_sql in queries_teste[:2]:
            payload = {
                "db": db_test,
                "q": q_sql,
                "epoch": "ms"
            }
            try:
                resp = session.post(proxy_url, headers=headers_proxy, data=payload, timeout=8)
                print(f"   ↳ Query: {desc} (Status: {resp.status_code})")
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    if results and "series" in results[0]:
                        series = results[0]["series"][0]
                        valores = series.get("values", [])
                        if valores:
                            val_final = valores[-1][1]
                            print(f"   🎉 SUCESSO VIA PROXY! Valor: {float(val_final):,.0f} garrafas")
                            sucesso_metodo_2 = True
                            break
                        else:
                            print("   ℹ️ Série vazia na resposta do Influx.")
                    else:
                        print("   ℹ️ Sem série retornada (verifique banco ou permissão).")
                else:
                    err_msg = resp.text[:120] if resp.text else ""
                    print(f"   ⚠️ HTTP {resp.status_code}: {err_msg}")
            except Exception as e:
                print(f"   ❌ Erro de conexão no proxy: {e}")
        if sucesso_metodo_2:
            break

    # 6. Resumo Final
    print("\n" + "=" * 80)
    print("   RESUMO FINAL DO DIAGNÓSTICO")
    print("=" * 80)
    if sucesso_metodo_1 or sucesso_metodo_2:
        print("✅ SUCESSO! A query e o acesso ao contador físico estão funcionando!")
        if sucesso_metodo_1:
            print("   ↳ Método 1 (/api/ds/query): OK (Recomendado para ambientes industriais)")
        if sucesso_metodo_2:
            print("   ↳ Método 2 (Proxy InfluxQL): OK")
    else:
        print("❌ Nenhuma das tentativas conseguiu extrair o valor do contador.")
        print("   Verifique as permissões de usuário ou o nome exato da base no InfluxDB.")
    print("=" * 80)

if __name__ == "__main__":
    main()
