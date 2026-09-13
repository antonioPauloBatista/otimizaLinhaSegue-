#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Controlador de Velocidade Live via Grafana / InfluxDB V4
Conecta a cada 30 segundos, extrai dados brutos via API Grafana (mesmo método da V3),
aplica filtros data-driven, calcula tendências e despacha o setpoint otimizado com rampa suave e Motivo ID.
Monitora em tempo real:
  1. Se o V4 manteria a enchedora rodando enquanto a real está parada.
  2. Garrafas acumuladas ciclo a ciclo (Real vs Otimizado V4).
Ao pressionar Ctrl+C:
  - Encerra com segurança
  - Exibe no terminal e grava resumo único consolidado em arquivo texto e JSON.
"""

import time
import datetime
import requests
import json
import base64
import pandas as pd
import numpy as np
import sys
import os
import argparse
from funcao_controle_v4 import ControladorVelocidadeV4

GRAFANA_URL = "http://172.23.224.145:3000"
GRAFANA_USER = "admin"
GRAFANA_PASSWORD = "!ambev2021"
GRAFANA_TOKEN = ""
DATASOURCE_SELECTOR = "13"
BUCKET = "Segue"
MEASUREMENT = "NS-541"

VEL_NOMINAL = 60000.0
LIMIAR_PARADA_CPH = 10000.0
ARQUIVO_JSON_GRAFANA = "eventos_motivos_grafana_v4.json"
ARQUIVO_CONFIG = "config_colunas.json"

COL_B1 = "accumulation_percentage_lgf_to_uip_null"
COL_B2 = "accumulation_percentage_uip_to_ech_null"
COL_B3 = "accumulation_percentage_ech_to_pz_null"
COL_B4 = "accumulation_percentage_pz_to_rot_null"
COL_V_ECH = "speed_actual_cph_null_filler_1"
COL_V_ENTRADA = "speed_actual_cph_null_eci_1"
COL_V_SAIDA = "speed_actual_cph_null_pasteurizer"

if os.path.exists(ARQUIVO_CONFIG):
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            COL_B1 = cfg.get("Col_Buffer_Antes_Entrada", COL_B1)
            COL_B2 = cfg.get("Col_Buffer_Entrada", COL_B2)
            COL_B3 = cfg.get("Col_Buffer_Saida", COL_B3)
            COL_B4 = cfg.get("Col_Buffer_Pos_Saida", COL_B4)
            COL_V_ECH = cfg.get("COL_V_ECH", COL_V_ECH)
            COL_V_ENTRADA = cfg.get("COL_V_Entrada", COL_V_ENTRADA)
            COL_V_SAIDA = cfg.get("COL_V_Saida", COL_V_SAIDA)
            GRAFANA_URL = cfg.get("Grafana_URL", GRAFANA_URL)
            MEASUREMENT = cfg.get("Grafana_Measurement", cfg.get("Measurement", MEASUREMENT))
            BUCKET = cfg.get("Grafana_Bucket", cfg.get("Bucket", BUCKET))
            DATASOURCE_SELECTOR = cfg.get("Grafana_Datasource", cfg.get("Datasource_Selector", DATASOURCE_SELECTOR))
    except Exception: pass

def resolver_info_datasource(session, headers, grafana_url, selector="8", fallback_name="SODA Template"):
    ds_url = f"{grafana_url.rstrip('/')}/api/datasources"
    try:
        r = session.get(ds_url, headers=headers, timeout=5)
        if r.status_code == 200:
            datasources = r.json()
            for ds in datasources:
                if str(ds.get("id")) == str(selector) or str(ds.get("name", "")).lower() == str(selector).lower() or str(ds.get("uid")) == str(selector):
                    return str(ds.get("id")), str(ds.get("uid", "")), str(ds.get("name", "")), str(ds.get("database", ""))
            for ds in datasources:
                if fallback_name.lower() in str(ds.get("name", "")).lower() or fallback_name.lower() in str(ds.get("database", "")).lower():
                    return str(ds.get("id")), str(ds.get("uid", "")), str(ds.get("name", "")), str(ds.get("database", ""))
    except Exception:
        pass
    return str(selector), "", fallback_name, ""

def extrair_valor_contador_grafana_json(json_data):
    if not isinstance(json_data, dict):
        return None
    # 1. Formato Frames do /api/ds/query (Grafana moderno)
    results = json_data.get("results", {})
    if isinstance(results, dict):
        for res_obj in results.values():
            frames = res_obj.get("frames", [])
            for f in frames:
                data_values = f.get("data", {}).get("values", [])
                if data_values and len(data_values) >= 2:
                    vals = data_values[-1]
                    for v in reversed(vals):
                        if v is not None:
                            try:
                                return float(v)
                            except (ValueError, TypeError):
                                pass
                elif data_values and len(data_values) == 1:
                    vals = data_values[0]
                    for v in reversed(vals):
                        if v is not None:
                            try:
                                return float(v)
                            except (ValueError, TypeError):
                                pass

    # 2. Formato InfluxQL tradicional {"results": [{"series": [{"values": [...]}]}]}
    res_list = results if isinstance(results, list) else json_data.get("results", [])
    if isinstance(res_list, list) and res_list:
        series = res_list[0].get("series", [])
        if series:
            values = series[0].get("values", [])
            if values:
                row = values[-1]
                for col_val in reversed(row[1:]):
                    if col_val is not None:
                        try:
                            return float(col_val)
                        except (ValueError, TypeError):
                            pass
    return None

def obter_ds_uid(session, headers, url=GRAFANA_URL, selector=DATASOURCE_SELECTOR):
    ds_url = f"{url.rstrip('/')}/api/datasources"
    try:
        r = session.get(ds_url, headers=headers, timeout=10)
        if r.status_code == 200:
            ds_list = r.json()
            influx_ds = [ds for ds in ds_list if ds.get("type") == "influxdb"]
            for ds in influx_ds:
                if str(ds.get("id")) == str(selector) or str(ds.get("name", "")).lower() == str(selector).lower():
                    return ds.get("uid")
            if influx_ds:
                return influx_ds[0].get("uid")
    except Exception: pass
    return None

def carregar_config_contador(caminho_custom=None):
    pasta_script = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else "."
    candidatos = [
        caminho_custom,
        os.path.join(pasta_script, "parametros_query.json"),
        os.path.join(os.getcwd(), "parametros_query.json"),
        "parametros_query.json",
        os.path.join(pasta_script, "..", "parametros_query.json"),
        os.path.join(pasta_script, "..", "Dados de json", "parametros_query.json"),
        os.path.join("..", "Dados de json", "parametros_query.json"),
        os.path.join("Dados de json", "parametros_query.json"),
        "/home/antonio/Projetos/OtimizadorSegue/Dados de json/parametros_query.json",
        "/home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4/parametros_query.json"
    ]

    import glob
    for p in glob.glob(os.path.join(pasta_script, "..", "*parametros_query.json")):
        if p not in candidatos: candidatos.append(p)
    for p in glob.glob(os.path.join(pasta_script, "..", "**", "*parametros_query.json"), recursive=True):
        if p not in candidatos: candidatos.append(p)

    for c in candidatos:
        if c and os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    data = json.load(f)
                config_glob = data.get("config", {})
                queries = data.get("queries", [])
                if not queries:
                    continue
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

                return {
                    "origem_arquivo": c,
                    "grafana_url": config_glob.get("grafana_url", "http://10.188.130.146:3000/"),
                    "grafana_user": config_glob.get("grafana_user", "admin"),
                    "grafana_password": config_glob.get("grafana_password", "!ambev2021"),
                    "database": config_glob.get("database", "soda"),
                    "datasource_selector": config_glob.get("datasource_selector", "9"),
                    "equipment_type": eq_type,
                    "equipment_name": eq_name,
                    "field_name": field_name,
                    "tags": tags
                }
            except Exception as err:
                print(f"⚠️ Aviso: Arquivo '{c}' encontrado, mas falhou ao ler JSON: {err}")

    # Fallback resiliente: Configuração padrão da linha caso o arquivo não seja encontrado
    return {
        "origem_arquivo": "Configuração Padrão Embutida (NS-05410-ENCHEDORA 01)",
        "grafana_url": "http://10.188.130.146:3000/",
        "grafana_user": "admin",
        "grafana_password": "!ambev2021",
        "database": "soda",
        "datasource_selector": "9",
        "equipment_type": "Filler",
        "equipment_name": "NS-05410-ENCHEDORA 01",
        "field_name": "Packaging Machine Production Counter - Total",
        "tags": {"equipment_name": "NS-05410-ENCHEDORA 01", "rule": ""}
    }

def montar_query_influxql_contador(cfg_contador):
    if not cfg_contador:
        return ""
    eq_type = cfg_contador.get("equipment_type", "Filler")
    field_name = cfg_contador.get("field_name", "Packaging Machine Production Counter - Total")
    tags = cfg_contador.get("tags", {})

    where_parts = []
    for k, v in tags.items():
        if not str(v).strip():
            continue
        if k == "rule":
            where_parts.append(f'"{k}"::tag =~ /{v}/')
        else:
            where_parts.append(f'"{k}"::tag = \'{v}\'')
    where_str = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
    return f'SELECT LAST("{field_name}") FROM "{eq_type}"{where_str}'

def gerar_variacoes_query_contador(query_sql):
    candidatos = [query_sql]
    if "::tag" in query_sql:
        candidatos.append(query_sql.replace("::tag", ""))

    janelas = ["time >= now() - 7d", "time >= now() - 30d", "time >= now() - 24h"]
    for base in list(candidatos):
        sep = " AND " if " WHERE " in base else " WHERE "
        for j in janelas:
            candidatos.append(f"{base}{sep}{j}")

    if "LAST(" in query_sql:
        try:
            inicio = query_sql.index("LAST(") + 5
            fim = query_sql.index(")", inicio)
            campo = query_sql[inicio:fim]
            q_limit = query_sql.replace(f"LAST({campo})", campo)
            candidatos.append(f"{q_limit} ORDER BY time DESC LIMIT 1")
            if "::tag" in q_limit:
                candidatos.append(f"{q_limit.replace('::tag', '')} ORDER BY time DESC LIMIT 1")
            for j in janelas:
                sep = " AND " if " WHERE " in q_limit else " WHERE "
                candidatos.append(f"{q_limit}{sep}{j} ORDER BY time DESC LIMIT 1")
        except Exception:
            pass

    vistas = set()
    unicas = []
    for q in candidatos:
        q_limpa = " ".join(q.split())
        if q_limpa not in vistas:
            vistas.add(q_limpa)
            unicas.append(q_limpa)
    return unicas

def consultar_contador_producao(session, headers, grafana_url, ds_id, database, query_sql, timeout=5, grafana_url_fallback=None, retornar_detalhe=False, ds_uid=""):
    urls = [grafana_url.rstrip("/")]
    if grafana_url_fallback and grafana_url_fallback.rstrip("/") not in urls:
        urls.append(grafana_url_fallback.rstrip("/"))

    ds_candidates = [str(ds_id)]
    for alt_ds in ["8", "9"]:
        if alt_ds not in ds_candidates:
            ds_candidates.append(alt_ds)

    db_candidates = [database]
    for alt_db in ["soda", "SODA Template"]:
        if alt_db and alt_db not in db_candidates:
            db_candidates.append(alt_db)

    queries = gerar_variacoes_query_contador(query_sql)

    ultimo_erro = "Sem resposta"
    for url in urls:
        # 1. Tentativa via API nativa /api/ds/query do Grafana (igual ao painel aberto)
        ds_query_url = f"{url}/api/ds/query"
        auth_hdr = headers.get("Authorization", "")
        api_headers = {"Authorization": auth_hdr, "Content-Type": "application/json", "Accept": "application/json"}
        
        ds_targets = []
        if ds_uid:
            ds_targets.append({"uid": ds_uid})
        ds_targets.extend([{"name": "SODA Template"}, {"name": "soda"}, {"id": ds_id}])

        for q in queries[:4]:
            for ds_ref in ds_targets:
                for fmt in ["table", "time_series"]:
                    ds_payload = {
                        "from": "now-1h",
                        "to": "now",
                        "queries": [
                            {
                                "datasource": {"type": "influxdb", **ds_ref},
                                "rawQuery": True,
                                "query": q,
                                "refId": "A",
                                "resultFormat": fmt
                            }
                        ]
                    }
                    try:
                        resp_api = session.post(ds_query_url, headers=api_headers, json=ds_payload, timeout=timeout)
                        if resp_api.status_code == 200:
                            v_extraido = extrair_valor_contador_grafana_json(resp_api.json())
                            if v_extraido is not None:
                                return (v_extraido, "OK") if retornar_detalhe else v_extraido
                    except Exception:
                        pass

        # 2. Tentativa via Proxy InfluxQL tradicional
        for cur_ds in ds_candidates:
            proxy_url = f"{url}/api/datasources/proxy/{cur_ds}/query"
            for cur_db in db_candidates:
                for q in queries:
                    payload = {
                        "db": cur_db,
                        "q": q,
                        "epoch": "ms"
                    }
                    try:
                        resp = session.post(proxy_url, headers=headers, data=payload, timeout=timeout)
                        if resp.status_code == 200:
                            v_extraido = extrair_valor_contador_grafana_json(resp.json())
                            if v_extraido is not None:
                                return (v_extraido, "OK") if retornar_detalhe else v_extraido
                            ultimo_erro = f"Série vazia no Influx ({url}, DS {cur_ds}, DB {cur_db})"
                        elif resp.status_code == 404:
                            ultimo_erro = f"Datasource {cur_ds} não encontrado ({url})"
                        else:
                            err_txt = resp.text[:60] if resp.text else f"Status {resp.status_code}"
                            ultimo_erro = f"HTTP {resp.status_code} ({err_txt}) [DS {cur_ds}, DB {cur_db}]"
                    except Exception as e:
                        ultimo_erro = f"Falha de rede em {url} (DS {cur_ds}): {e}"

    return (None, ultimo_erro) if retornar_detalhe else None

    return (None, ultimo_erro) if retornar_detalhe else None

def parse_grafana_ds_response(json_data):
    results = json_data.get("results", {})
    if not results: return pd.DataFrame()
    result = next(iter(results.values()))
    frames = result.get("frames", [])
    if not frames: return pd.DataFrame()

    all_dfs = []
    for frame in frames:
        schema = frame.get("schema", {})
        data   = frame.get("data", {})
        fields = schema.get("fields", [])
        values = data.get("values", [])
        if not fields or not values or len(fields) != len(values): continue
        df_data = {}
        for field, vals in zip(fields, values):
            fname = field.get("name", "value")
            ftype = field.get("type", "")
            if ftype == "time":
                df_data["Timestamp"] = pd.to_datetime(vals, unit="ms")
            else:
                df_data[fname] = vals
        if "Timestamp" not in df_data: continue
        all_dfs.append(pd.DataFrame(df_data))

    if not all_dfs: return pd.DataFrame()
    if len(all_dfs) == 1: return all_dfs[0]
    merged = all_dfs[0]
    for other in all_dfs[1:]:
        merged = merged.merge(other, on="Timestamp", how="outer")
    return merged

def find_col_val(df_line, target_col):
    if not target_col: return None
    if target_col in df_line: return df_line[target_col]
    target_clean = str(target_col).replace("_null", "")
    for col_name in df_line.index:
        if target_clean in str(col_name):
            return df_line[col_name]
    return None

def find_col_val_com_aliases(df_line, col_primaria, aliases=None):
    candidatos = [col_primaria] if col_primaria else []
    if aliases: candidatos.extend(aliases)
    for cand in candidatos:
        val = find_col_val(df_line, cand)
        if val is not None and pd.notna(val): return val
    return None

def gerar_relatorio_sessao(metricas, controlador, arquivo_saida="resumo_producao_live_v4.txt"):
    import glob
    for f_antigo in glob.glob("relatorio_sessao_live_v4_*.txt"):
        try: os.remove(f_antigo)
        except Exception: pass

    timestamp_fim = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    duracao_s = max(1.0, metricas.get("tempo_total_s", 0.0))
    horas = int(duracao_s // 3600)
    minutos = int((duracao_s % 3600) // 60)
    segundos = int(duracao_s % 60)
    duracao_str = f"{horas}h {minutos:02d}min {segundos:02d}s"

    t_real_parada = metricas.get("tempo_parada_real_s", 0.0)
    t_real_ligada = metricas.get("tempo_real_ligado_s", max(0.0, duracao_s - t_real_parada))
    p_real_ligada = (t_real_ligada / duracao_s) * 100.0
    p_real_parada = (t_real_parada / duracao_s) * 100.0

    t_parada_evitada = metricas.get("tempo_parada_evitada_s", 0.0)
    t_v4_parado = metricas.get("tempo_v4_parado_s", max(0.0, t_real_parada - t_parada_evitada))
    t_v4_ligado = metricas.get("tempo_v4_ligado_s", max(0.0, duracao_s - t_v4_parado))
    p_v4_ligado = (t_v4_ligado / duracao_s) * 100.0
    p_v4_parado = (t_v4_parado / duracao_s) * 100.0

    t_v4_nom = metricas.get("tempo_v4_nominal_s", 0.0)
    t_v4_spr = metricas.get("tempo_v4_sprint_s", 0.0)
    t_v4_mod = metricas.get("tempo_v4_modulando_s", max(0.0, t_v4_ligado - t_v4_nom - t_v4_spr))
    p_v4_nom = (t_v4_nom / duracao_s) * 100.0
    p_v4_spr = (t_v4_spr / duracao_s) * 100.0
    p_v4_mod = (t_v4_mod / duracao_s) * 100.0

    garrafas_reais = metricas.get("garrafas_reais_total", 0.0)
    garrafas_v4 = metricas.get("garrafas_v4_total", 0.0)
    garrafas_extras = metricas.get("garrafas_extras_total", garrafas_v4 - garrafas_reais)
    perc_ganho = (garrafas_extras / garrafas_reais * 100.0) if garrafas_reais > 0 else (100.0 if garrafas_v4 > 0 else 0.0)
    sinal = "+" if garrafas_extras >= 0 else ""

    v_media_real = (garrafas_reais / (t_real_ligada / 3600.0)) if t_real_ligada > 0 else 0.0
    v_media_v4 = (garrafas_v4 / (t_v4_ligado / 3600.0)) if t_v4_ligado > 0 else 0.0
    taxa_recup_parada = (t_parada_evitada / t_real_parada * 100.0) if t_real_parada > 0 else 0.0

    def formata_tempo(seg):
        h = int(seg // 3600)
        m = int((seg % 3600) // 60)
        s = int(seg % 60)
        return f"{h}h {m:02d}min {s:02d}s"

    linhas = []
    linhas.append("=" * 80)
    linhas.append("   RELATÓRIO DE MONITORAMENTO LIVE V4: RESUMO DE PRODUÇÃO E TEMPO LIGADO")
    linhas.append("=" * 80)
    linhas.append(f"➔ Início da Sessão            : {metricas.get('inicio', 'N/A')}")
    linhas.append(f"➔ Término da Sessão           : {timestamp_fim}")
    linhas.append(f"➔ Duração Monitorada          : {duracao_str} ({metricas.get('total_ciclos', 0)} ciclos de amostragem)")
    linhas.append(f"➔ Velocidade Nominal          : {VEL_NOMINAL:,.0f} garrafas/h")
    linhas.append("-" * 80)
    linhas.append("[1. RESUMO DA PROPORÇÃO DO TEMPO LIGADO (UPTIME vs PARADA)]")
    linhas.append(f"➔ Enchedora Real Ligada       : {formata_tempo(t_real_ligada)} ({p_real_ligada:5.1f}% do tempo total)")
    linhas.append(f"➔ Enchedora Real Parada       : {formata_tempo(t_real_parada)} ({p_real_parada:5.1f}% do tempo total)")
    linhas.append(f"➔ Controlador Ligado          : {formata_tempo(t_v4_ligado)} ({p_v4_ligado:5.1f}% do tempo total)")
    linhas.append(f"➔ Controlador Parado          : {formata_tempo(t_v4_parado)} ({p_v4_parado:5.1f}% do tempo total)")
    ganho_disp = p_v4_ligado - p_real_ligada
    sinal_disp = "+" if ganho_disp >= 0 else ""
    linhas.append(f"   ↳ GANHO DE TEMPO LIGADO    : {formata_tempo(max(0.0, t_v4_ligado - t_real_ligada))} ({sinal_disp}{ganho_disp:.1f}% de disponibilidade extra)")
    linhas.append("")
    linhas.append("[DETALHAMENTO DO TEMPO LIGADO COM CONTROLADOR]")
    linhas.append(f"   ↳ Operação Nominal (100%)  : {formata_tempo(t_v4_nom)} ({p_v4_nom:5.1f}% do tempo total)")
    linhas.append(f"   ↳ Modo Sprint (>100%)      : {formata_tempo(t_v4_spr)} ({p_v4_spr:5.1f}% do tempo total)")
    linhas.append(f"   ↳ Modulação Suave (<100%)  : {formata_tempo(t_v4_mod)} ({p_v4_mod:5.1f}% do tempo total)")
    linhas.append("-" * 80)
    linhas.append("[2. RESUMO DE PRODUÇÃO NO TEMPO LIGADO]")
    info_sensor = f" (Vazão Média: {v_media_real:,.0f} garrafas/h)"
    if metricas.get("ciclos_validacao_sensor", 0) > 0 and metricas.get("contador_final") is not None:
        tot_sensor = metricas.get("garrafas_fisicas_sensor_total", 0.0)
        c_fim = metricas.get("contador_final", 0.0)
        info_sensor = f" [Validada por Sensor Físico: {tot_sensor:,.0f} gf | Contador: {c_fim:,.0f} gf | Vazão: {v_media_real:,.0f} garrafas/h]"
    elif metricas.get("contador_final") is not None:
        info_sensor = f" [Contador Físico: {metricas['contador_final']:,.0f} gf | Vazão: {v_media_real:,.0f} garrafas/h]"

    linhas.append(f"➔ Produção Real Registrada    : {garrafas_reais:,.1f} garrafas{info_sensor}")
    linhas.append(f"➔ Produção Controlador        : {garrafas_v4:,.1f} garrafas (Vazão Média: {v_media_v4:,.0f} garrafas/h)")
    linhas.append(f"➔ SALDO DE GARRAFAS GERADAS   : {sinal}{garrafas_extras:,.1f} garrafas ({sinal}{perc_ganho:.2f}%)")
    linhas.append("-" * 80)
    linhas.append("[3. AVALIAÇÃO DE CONTINUIDADE OPERACIONAL - MANTERIA RODANDO?]")
    linhas.append(f"➔ Tempo Total em Parada Real  : {formata_tempo(t_real_parada)}")
    linhas.append(f"➔ Tempo de Parada Evitado V4  : {formata_tempo(t_parada_evitada)} ({taxa_recup_parada:.1f}% das paradas reais)")
    linhas.append(f"➔ Ciclos em que Manteria Rod  : {metricas.get('ciclos_manteria_rodando', 0)} ciclos de 30s")
    linhas.append(f"➔ Paradas Inevitáveis (Físicas): {metricas.get('ciclos_parada_inevitavel', 0)} ciclos")
    linhas.append("-" * 80)
    linhas.append("[4. CONSOLIDAÇÃO DAS CAUSAS / FALHAS POR PROPORÇÃO DO TEMPO]")
    total_c = max(1, metricas.get('total_ciclos', 1))
    contagem = metricas.get('contagem_motivos', {})
    for m_id, count in sorted(contagem.items(), key=lambda x: x[1], reverse=True):
        info_m = controlador.obter_motivo(m_id)
        p_motivo = (count / total_c) * 100.0
        t_motivo = metricas.get("tempo_motivos_s", {}).get(m_id, count * 30.0)
        maq = info_m.get("maquina_causadora", "Geral")[:20]
        linhas.append(f"   ↳ [{maq:<20}] ID {m_id:2d} - {info_m.get('codigo', 'OUTRO'):<26}: {formata_tempo(t_motivo)} ({p_motivo:5.1f}%) | {count:3d} ciclos")
    linhas.append("=" * 80)

    texto_relatorio = "\n".join(linhas)
    print("\n" + texto_relatorio + "\n")

    nome_arquivo_relatorio = arquivo_saida
    try:
        with open(nome_arquivo_relatorio, "w", encoding="utf-8") as f:
            f.write(texto_relatorio + "\n")
        print(f"📄 Resumo consolidado salvo com sucesso em: '{nome_arquivo_relatorio}'")
    except Exception as e:
        print(f"⚠️ Erro ao salvar arquivo de relatório '{nome_arquivo_relatorio}': {e}")

    arquivo_json_resumo = "resumo_producao_live_v4.json"
    dados_resumo_json = {
        "inicio": metricas.get("inicio"),
        "fim": timestamp_fim,
        "duracao_segundos": duracao_s,
        "total_ciclos": metricas.get("total_ciclos", 0),
        "proporcao_tempo_ligado": {
            "real_ligada_segundos": t_real_ligada,
            "real_ligada_percentual": round(p_real_ligada, 2),
            "real_parada_segundos": t_real_parada,
            "real_parada_percentual": round(p_real_parada, 2),
            "v4_ligado_segundos": t_v4_ligado,
            "v4_ligado_percentual": round(p_v4_ligado, 2),
            "v4_parado_segundos": t_v4_parado,
            "v4_parado_percentual": round(p_v4_parado, 2),
            "ganho_tempo_ligado_percentual": round(ganho_disp, 2),
            "detalhamento_v4": {
                "nominal_segundos": t_v4_nom,
                "nominal_percentual": round(p_v4_nom, 2),
                "sprint_segundos": t_v4_spr,
                "sprint_percentual": round(p_v4_spr, 2),
                "modulando_segundos": t_v4_mod,
                "modulando_percentual": round(p_v4_mod, 2)
            }
        },
        "resumo_producao": {
            "garrafas_reais": round(garrafas_reais, 1),
            "garrafas_v4": round(garrafas_v4, 1),
            "saldo_garrafas": round(garrafas_extras, 1),
            "percentual_ganho": round(perc_ganho, 2),
            "vazao_media_real_cph": round(v_media_real, 1),
            "vazao_media_v4_cph": round(v_media_v4, 1),
            "garrafas_sensor_fisico": round(metricas.get("garrafas_fisicas_sensor_total", 0.0), 1),
            "ciclos_validacao_sensor": metricas.get("ciclos_validacao_sensor", 0),
            "contador_inicial": metricas.get("contador_inicial"),
            "contador_final": metricas.get("contador_final")
        },
        "continuidade_operacional": {
            "tempo_parada_evitado_segundos": t_parada_evitada,
            "taxa_recuperacao_paradas_percentual": round(taxa_recup_parada, 2),
            "ciclos_manteria_rodando": metricas.get("ciclos_manteria_rodando", 0),
            "ciclos_parada_inevitavel": metricas.get("ciclos_parada_inevitavel", 0)
        }
    }
    try:
        with open(arquivo_json_resumo, "w", encoding="utf-8") as f:
            json.dump(dados_resumo_json, f, indent=2, ensure_ascii=False)
        print(f"📊 Resumo estruturado JSON salvo com sucesso em: '{arquivo_json_resumo}'")
    except Exception as e:
        print(f"⚠️ Erro ao salvar '{arquivo_json_resumo}': {e}")

    return nome_arquivo_relatorio

def interpretar_janela(janela_str):
    j = str(janela_str).strip().lower()
    try:
        if j.endswith("m"): return datetime.timedelta(minutes=int(j[:-1]))
        if j.endswith("h"): return datetime.timedelta(hours=int(j[:-1]))
        if j.endswith("d"): return datetime.timedelta(days=int(j[:-1]))
        if j.endswith("s"): return datetime.timedelta(seconds=int(j[:-1]))
    except Exception:
        pass
    return datetime.timedelta(minutes=30)

def main():
    parser = argparse.ArgumentParser(description="Controlador Live Grafana V4")
    parser.add_argument("--url", default=GRAFANA_URL, help="URL base do Grafana")
    parser.add_argument("--user", default=GRAFANA_USER, help="Usuário do Grafana")
    parser.add_argument("--password", default=GRAFANA_PASSWORD, help="Senha do Grafana")
    parser.add_argument("--token", default=GRAFANA_TOKEN, help="Token do Grafana")
    parser.add_argument("--ds", default=DATASOURCE_SELECTOR, help="ID ou Nome do Datasource")
    parser.add_argument("--bucket", default=BUCKET, help="Bucket do InfluxDB")
    parser.add_argument("--measurement", default=MEASUREMENT, help="Measurement (tabela) do InfluxDB")
    parser.add_argument("--janela", default="30m", help="Janela de busca das últimas medições (ex: 15m, 30m, 1h, 6h, 24h, 30d)")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout da requisição HTTP ao Grafana em segundos (default: 30)")
    parser.add_argument("--query-json", default=None, help="Caminho para o parametros_query.json com a query do contador físico")
    args = parser.parse_args()

    grafana_url = args.url.rstrip("/")
    measurement_ativo = args.measurement
    bucket_ativo = args.bucket
    ds_selector = args.ds
    delta_janela = interpretar_janela(args.janela)
    timeout_req = int(args.timeout)

    print("=" * 80)
    print("   CONTROLADOR DE VELOCIDADE LIVE GRAFANA V4 (BALANÇO + MOTIVOS)")
    print("=" * 80)
    print(f"Conectando ao Grafana: {grafana_url} a cada 30 segundos...")
    print(f"Datasource: '{ds_selector}' | Measurement: '{measurement_ativo}' | Bucket: '{bucket_ativo}'")
    print(f"Rastreamento de eventos ativo -> Arquivo JSON: '{ARQUIVO_JSON_GRAFANA}'")
    print("Pressione Ctrl+C a qualquer momento para finalizar e emitir o Relatório.\n")

    session = requests.Session()
    session.trust_env = False

    usr_pass = f"{args.user}:{args.password}".encode("utf-8")
    basic_auth = f"Basic {base64.b64encode(usr_pass).decode('utf-8')}"
    auth_header = f"Bearer {args.token}" if args.token else basic_auth
    headers = {"Accept": "application/json", "Content-Type": "application/json", "Authorization": auth_header}

    ds_uid = obter_ds_uid(session, headers, url=grafana_url, selector=ds_selector)
    if not ds_uid:
        print(f"⚠️ Aviso: Não foi possível obter UID do Datasource '{ds_selector}'. Tentando query com UID vazio.")
    else:
        print(f"➔ Datasource conectado com sucesso! UID: {ds_uid}")

    # Configuração e Conexão com o Contador Físico de Produção (via InfluxQL)
    cfg_contador = carregar_config_contador(args.query_json)
    query_sql_contador = ""
    session_contador = None
    headers_contador = None
    url_contador = ""
    ds_id_contador = ""
    db_contador = ""

    if cfg_contador:
        url_contador = cfg_contador["grafana_url"].rstrip("/")
        ds_id_contador = cfg_contador["datasource_selector"]
        db_contador = cfg_contador["database"]
        query_sql_contador = montar_query_influxql_contador(cfg_contador)

        session_contador = requests.Session()
        session_contador.trust_env = False
        usr_pass_cnt = f"{cfg_contador['grafana_user']}:{cfg_contador['grafana_password']}".encode("utf-8")
        basic_auth_cnt = f"Basic {base64.b64encode(usr_pass_cnt).decode('utf-8')}"
        headers_contador = {
            "Authorization": basic_auth_cnt,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        # Autodescoberta do Datasource ID e UID para o banco InfluxDB
        ds_id_auto, ds_uid_contador, ds_name_auto, ds_db_auto = resolver_info_datasource(
            session_contador, headers_contador,
            url_contador, selector=ds_id_contador, fallback_name=db_contador
        )
        if ds_id_auto:
            ds_id_contador = ds_id_auto
        if ds_db_auto:
            db_contador = ds_db_auto

        print(f"➔ Validação Física Conectada: Contador '{cfg_contador['field_name']}'")
        print(f"   ↳ Arquivo: '{cfg_contador['origem_arquivo']}' | Equipamento: '{cfg_contador['equipment_name']}' | DS: {ds_id_contador} (UID: {ds_uid_contador or 'N/A'})")

        # Teste imediato de leitura do contador na inicialização
        val_ini, err_ini = consultar_contador_producao(
            session_contador, headers_contador,
            url_contador, ds_id_contador, db_contador, query_sql_contador,
            timeout=5, grafana_url_fallback=grafana_url, retornar_detalhe=True, ds_uid=ds_uid_contador
        )
        if val_ini is not None:
            print(f"   ✓ Leitura física inicial OK: {val_ini:,.0f} garrafas no sensor.")
        else:
            print(f"   ⚠️ Aviso na leitura inicial do contador: {err_ini}")
    else:
        print("ℹ️ Validação Física: 'parametros_query.json' não localizado (produção estimada via velocidade do motor)")

    ds_query_url = f"{grafana_url}/api/ds/query"
    controlador = ControladorVelocidadeV4(velocidade_nominal=VEL_NOMINAL)

    hora_inicio = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    metricas = {
        "inicio": hora_inicio,
        "total_ciclos": 0,
        "tempo_total_s": 0.0,
        "garrafas_reais_total": 0.0,
        "garrafas_v4_total": 0.0,
        "garrafas_extras_total": 0.0,
        "tempo_real_ligado_s": 0.0,
        "tempo_real_parado_s": 0.0,
        "tempo_v4_ligado_s": 0.0,
        "tempo_v4_parado_s": 0.0,
        "tempo_v4_nominal_s": 0.0,
        "tempo_v4_sprint_s": 0.0,
        "tempo_v4_modulando_s": 0.0,
        "tempo_parada_real_s": 0.0,
        "tempo_parada_evitada_s": 0.0,
        "garrafas_evitadas_parada": 0.0,
        "ciclos_manteria_rodando": 0,
        "ciclos_parada_inevitavel": 0,
        "garrafas_fisicas_sensor_total": 0.0,
        "ciclos_validacao_sensor": 0,
        "contador_inicial": None,
        "contador_final": None,
        "contagem_motivos": {},
        "tempo_motivos_s": {}
    }

    tempo_anterior = time.time()
    contador_anterior = None

    while True:
        try:
            ciclo_inicio = time.time()
            delta_t_s = max(1.0, ciclo_inicio - tempo_anterior) if metricas["total_ciclos"] > 0 else 30.0
            tempo_anterior = ciclo_inicio

            # Janela de 30s nativa no InfluxDB (execução ultra-rápida sem escanear histórico pesado)
            janela_clean = str(args.janela).strip().lstrip("-")
            janela_flux = f"-{janela_clean}"

            flux_query = (
                'from(bucket: "' + str(bucket_ativo) + '")\n'
                '  |> range(start: ' + str(janela_flux) + ')\n'
                '  |> filter(fn: (r) =>\n'
                '      r["_measurement"] == "' + str(measurement_ativo) + '" and\n'
                '      (\n'
                '        r["_field"] == "accumulation_percentage" or\n'
                '        r["_field"] == "speed_actual_cph"\n'
                '      )\n'
                '  )\n'
                '  |> last()\n'
                '  |> map(fn: (r) => ({ r with _value: float(v: r._value) }))\n'
                '  |> group()\n'
                '  |> pivot(\n'
                '      rowKey: ["_measurement", "_time"],\n'
                '      columnKey: ["_field", "buffer_name_local", "machine_name_generic"],\n'
                '      valueColumn: "_value"\n'
                '  )'
            )

            ds_payload = {
                "from": "now-" + str(janela_clean),
                "to":   "now",
                "queries": [
                    {
                        "datasource": {"uid": ds_uid, "type": "influxdb"},
                        "query": flux_query,
                        "queryType": "flux",
                        "refId": "A",
                        "maxDataPoints": 100,
                        "intervalMs": 30000
                    }
                ]
            }

            b1, b2, b3, b4 = 50.0, 50.0, 50.0, 50.0
            vin, vout = VEL_NOMINAL, VEL_NOMINAL
            v_real = VEL_NOMINAL
            delay_segundos = 0.0
            conexao_ok = False

            try:
                resp = session.post(ds_query_url, headers=headers, json=ds_payload, timeout=timeout_req)
                if resp.status_code == 200:
                    df = parse_grafana_ds_response(resp.json())
                    # Se vier vazio nos 30s por jitter/atraso de rede, tenta janela de tolerância de 60s
                    if df.empty and janela_clean == "30s":
                        q_retry = flux_query.replace("range(start: -30s)", "range(start: -60s)")
                        ds_retry = {
                            "from": "now-60s",
                            "to": "now",
                            "queries": [
                                {
                                    "datasource": {"uid": ds_uid, "type": "influxdb"},
                                    "query": q_retry,
                                    "queryType": "flux",
                                    "refId": "A",
                                    "maxDataPoints": 100,
                                    "intervalMs": 30000
                                }
                            ]
                        }
                        resp_retry = session.post(ds_query_url, headers=headers, json=ds_retry, timeout=timeout_req)
                        if resp_retry.status_code == 200:
                            df = parse_grafana_ds_response(resp_retry.json())

                    if not df.empty:
                        linha = df.ffill().iloc[-1]
                        v_b1 = find_col_val_com_aliases(linha, COL_B1, ["lgf_to_uip", "pre_eci", "buffer_1"])
                        v_b2 = find_col_val_com_aliases(linha, COL_B2, ["uip_to_ech", "eci_to_filler", "buffer_2"])
                        v_b3 = find_col_val_com_aliases(linha, COL_B3, ["ech_to_pz", "filler_to_pasteurizer", "buffer_3"])
                        v_b4 = find_col_val_com_aliases(linha, COL_B4, ["pz_to_rot", "post_pasteurizer", "buffer_4"])

                        b1 = float(v_b1) if v_b1 is not None and pd.notna(v_b1) else 50.0
                        b2 = float(v_b2) if v_b2 is not None and pd.notna(v_b2) else 50.0
                        b3 = float(v_b3) if v_b3 is not None and pd.notna(v_b3) else 50.0
                        b4 = float(v_b4) if v_b4 is not None and pd.notna(v_b4) else 50.0

                        v_ech_val = find_col_val_com_aliases(linha, COL_V_ECH, ["filler_1", "enchedora"])
                        if v_ech_val is not None and pd.notna(v_ech_val):
                            v_real = float(v_ech_val)

                        v_in_val = find_col_val_com_aliases(linha, COL_V_ENTRADA, ["eci_1", "rotuladora"])
                        if v_in_val is not None and pd.notna(v_in_val):
                            vin = float(v_in_val)

                        v_out_val = find_col_val_com_aliases(linha, COL_V_SAIDA, ["pasteurizer", "pasteurizador"])
                        if v_out_val is not None and pd.notna(v_out_val):
                            vout = float(v_out_val)

                        t_stamp = linha.get("Timestamp")
                        if pd.notna(t_stamp):
                            agora_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                            delay_segundos = max(0.0, (agora_utc - t_stamp).total_seconds())

                        conexao_ok = True
                else:
                    try: err_msg = resp.json()
                    except Exception: err_msg = resp.text[:300]
                    print(f"⚠️ Status Grafana: {resp.status_code} | Detalhe: {err_msg}")
            except Exception as e:
                conexao_ok = False
                print(f"⚠️ Erro de conexão com Grafana: {e}")

            hora_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            hora_curta = datetime.datetime.now().strftime("%H:%M:%S")

            aviso_delay = ""
            if delay_segundos > 300 and conexao_ok:
                aviso_delay = f" ⚠️ DADOS COM ATRASO DE {delay_segundos:.0f}s"

            # Leitura do Contador Físico de Produção (via InfluxQL)
            contador_atual = None
            delta_contador = None
            erro_contador = ""
            if session_contador and query_sql_contador:
                try:
                    contador_atual, erro_contador = consultar_contador_producao(
                        session_contador, headers_contador,
                        url_contador, ds_id_contador, db_contador, query_sql_contador,
                        timeout=timeout_req, grafana_url_fallback=grafana_url, retornar_detalhe=True, ds_uid=ds_uid_contador
                    )
                except Exception as e:
                    contador_atual = None
                    erro_contador = str(e)

            if contador_atual is not None:
                if contador_anterior is None:
                    contador_anterior = contador_atual
                    if metricas["contador_inicial"] is None:
                        metricas["contador_inicial"] = contador_atual
                    delta_contador = 0.0
                else:
                    delta_contador = contador_atual - contador_anterior
                    if delta_contador < 0.0:
                        delta_contador = 0.0
                    contador_anterior = contador_atual
                metricas["contador_final"] = contador_atual

            real_ligada = (v_real >= LIMIAR_PARADA_CPH)

            if not real_ligada:
                # Regra industrial: se a máquina física real está parada (0 garrafas/h), os dois param!
                # Não há ganho de garrafas nem de disponibilidade durante paradas da máquina física.
                v_otim = 0.0
                controlador.v_atual = 0.0
                controlador.v_alvo_estabilizado = None
                v4_ligado = False
                perc = 0.0

                # Identificação de causa da parada física
                if b3 >= 80.0:
                    motivo_id = 92  # Intertravamento Saída B3 (Pasteurizador)
                elif b2 <= 15.0:
                    motivo_id = 91  # Intertravamento Entrada B2 (ECI)
                else:
                    motivo_id = 99  # Parada Própria da Enchedora

                controlador.ultimo_motivo_id = motivo_id
                controlador.registrar_evento(timestamp=hora_str, delta_t_s=delta_t_s, arquivo_json=ARQUIVO_JSON_GRAFANA)
                info = controlador.obter_motivo(motivo_id)

                g_real_ciclo = 0.0
                g_v4_ciclo = 0.0
                g_extra_ciclo = 0.0

                metricas["tempo_real_parado_s"] += delta_t_s
                metricas["tempo_parada_real_s"] += delta_t_s
                metricas["tempo_v4_parado_s"] += delta_t_s
                metricas["ciclos_parada_inevitavel"] += 1

                diagnostico_txt = f"🔴 MÁQUINA REAL PARADA (0 garrafas/h). Controlador parado em segurança por [{info.get('codigo')}]."
                if contador_atual is not None:
                    validacao_txt = f"🛑 Parada Real Confirmada (+0 gf) | Contador Físico: {contador_atual:,.0f} gf"
                else:
                    detalhe_off = f": {erro_contador}" if erro_contador else ""
                    validacao_txt = f"🛑 Parada Real (0 garrafas/h{detalhe_off})"
            else:
                # Máquina física real ligada: o controlador modula a velocidade de produção
                v_otim, motivo_id = controlador.calcular_velocidade(
                    b1, b2, b3, b4, v_in=vin, v_out=vout, delta_t_s=delta_t_s,
                    retornar_motivo=True, timestamp=hora_str,
                    registrar_evento=True, arquivo_json=ARQUIVO_JSON_GRAFANA
                )
                info = controlador.obter_motivo(motivo_id)
                perc = round((v_otim / VEL_NOMINAL) * 100.0, 1)

                v4_ligado = (v_otim >= LIMIAR_PARADA_CPH)

                # Produção real validada por sensor físico ou estimada por velocidade
                if delta_contador is not None and metricas["total_ciclos"] > 0:
                    g_real_ciclo = float(delta_contador)
                    metricas["garrafas_fisicas_sensor_total"] += delta_contador
                    metricas["ciclos_validacao_sensor"] += 1
                    if delta_contador == 0.0 and v_real >= LIMIAR_PARADA_CPH:
                        validacao_txt = f"⚠️ Motor Girando sem Garrafas (+0 gf no sensor) | Contador: {contador_atual:,.0f} gf"
                    else:
                        validacao_txt = f"✅ Produção Real Confirmada: +{delta_contador:,.0f} gf físicas no ciclo | Contador: {contador_atual:,.0f} gf"
                else:
                    g_real_ciclo = (v_real * delta_t_s) / 3600.0
                    if contador_atual is not None:
                        validacao_txt = f"ℹ️ Contador Físico Inicializado: {contador_atual:,.0f} gf | Estimativa por velocidade no 1º ciclo"
                    else:
                        detalhe_off = f": {erro_contador}" if erro_contador else ""
                        validacao_txt = f"ℹ️ Produção estimada pela velocidade do motor (contador físico offline{detalhe_off})"

                g_v4_ciclo = (v_otim * delta_t_s) / 3600.0
                g_extra_ciclo = g_v4_ciclo - g_real_ciclo

                metricas["tempo_real_ligado_s"] += delta_t_s

                if v4_ligado:
                    metricas["tempo_v4_ligado_s"] += delta_t_s
                    if perc > 100.0: metricas["tempo_v4_sprint_s"] += delta_t_s
                    elif perc == 100.0: metricas["tempo_v4_nominal_s"] += delta_t_s
                    else: metricas["tempo_v4_modulando_s"] += delta_t_s
                else:
                    metricas["tempo_v4_parado_s"] += delta_t_s

                if perc > 100.0:
                    diagnostico_txt = f"🚀 MODO SPRINT: +{g_extra_ciclo:+.1f} garrafas/ciclo geradas a mais"
                elif perc == 100.0:
                    diagnostico_txt = f"✅ OPERAÇÃO NOMINAL PLENA (100%)"
                else:
                    diagnostico_txt = f"⚠️ MODULAÇÃO SUAVE ATIVA: Proteção de buffer em curso"

            metricas["total_ciclos"] += 1
            metricas["tempo_total_s"] += delta_t_s
            metricas["garrafas_reais_total"] += g_real_ciclo
            metricas["garrafas_v4_total"] += g_v4_ciclo
            metricas["garrafas_extras_total"] += g_extra_ciclo

            metricas["contagem_motivos"][motivo_id] = metricas["contagem_motivos"].get(motivo_id, 0) + 1
            metricas["tempo_motivos_s"][motivo_id] = metricas["tempo_motivos_s"].get(motivo_id, 0.0) + delta_t_s

            t_tot = max(1.0, metricas["tempo_total_s"])
            p_real_lig = (metricas["tempo_real_ligado_s"] / t_tot) * 100.0
            p_v4_lig = (metricas["tempo_v4_ligado_s"] / t_tot) * 100.0
            ganho_uptime_p = p_v4_lig - p_real_lig
            sinal_upt = "+" if ganho_uptime_p >= 0 else ""
            perc_prod_ganho = (metricas["garrafas_extras_total"] / metricas["garrafas_reais_total"] * 100.0) if metricas["garrafas_reais_total"] > 0 else 0.0
            sinal_prod = "+" if metricas["garrafas_extras_total"] >= 0 else ""

            tag_status = " [ONLINE]" if conexao_ok else " ⚠️ [MODO CONTINGÊNCIA / SEM DADOS GRAFANA]"
            print(f"[{hora_curta}] Leituras{tag_status}: B1={b1:.1f}% | B2={b2:.1f}% | B3={b3:.1f}% | B4={b4:.1f}%{aviso_delay}")
            print(f"   ↳ Máquinas Vizinhas : Entrada (ECI): {vin:,.0f} garrafas/h | Saída (Pasteurizador): {vout:,.0f} garrafas/h")
            if not conexao_ok:
                print("   ↳ ⚠️ AVISO: Sem dados recentes do Grafana (timeout/rede). Valores calculados com base de segurança!")
            print(f"   ↳ Velocidade Real   : {v_real:,.0f} garrafas/h | Controlador: {v_otim:,.0f} garrafas/h ({perc}%) | Motivo [{motivo_id} - {info.get('codigo')}]: {info.get('descricao')}")
            print(f"   ↳ Validação Física  : {validacao_txt}")
            print(f"   ↳ Diagnóstico Uptime   : {diagnostico_txt}")
            print(f"   ↳ RESUMO TEMPO LIGADO  : Real: {p_real_lig:5.1f}% ({metricas['tempo_real_ligado_s']/60.0:.1f}min) | Controlador: {p_v4_lig:5.1f}% ({metricas['tempo_v4_ligado_s']/60.0:.1f}min) | Ganho: {sinal_upt}{ganho_uptime_p:.1f}% ({metricas['tempo_parada_evitada_s']/60.0:.1f}min evitados)")
            print(f"   ↳ RESUMO DE PRODUÇÃO   : Real: {metricas['garrafas_reais_total']:,.1f} gf | Controlador: {metricas['garrafas_v4_total']:,.1f} gf | Saldo: {sinal_prod}{metricas['garrafas_extras_total']:,.1f} gf ({sinal_prod}{perc_prod_ganho:.1f}%)")
            print("-" * 80)

            time.sleep(30)

        except KeyboardInterrupt:
            agora_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            controlador.finalizar_eventos(timestamp=agora_str, arquivo_json=ARQUIVO_JSON_GRAFANA)
            print("\n🚨 Interrupção manual detectada (Ctrl+C). Processando relatório final...")
            gerar_relatorio_sessao(metricas, controlador)
            print(f"Eventos salvos em '{ARQUIVO_JSON_GRAFANA}'. Encerrando com sucesso.\n")
            break

if __name__ == "__main__":
    main()
