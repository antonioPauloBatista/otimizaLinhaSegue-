#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Medidor de Ganho de Controle Industrial - Controlador Segue V4
Calcula, audita e monitora em tempo real o ganho de controle (garrafas a mais e paradas a menos).
Calcula SEMPRE a cada novo dado que chega (streaming ou batch), avaliando ganho ou perca:
- Quando Segue LIGADO: ganho real entregue (ou perca) vs baseline sem controle.
- Quando Segue DESLIGADO: oportunidade V4 e perda acumulada por manter o Segue desligado.
- Comparativo A/B: confronto direto sob as mesmas condições físicas de buffer e rastejo.

Suporta:
1. Execução estática/batch sobre arquivos CSV locais.
2. Execução online streaming monitorando arquivo CSV (--online).
3. Streaming direto da API do Grafana / InfluxDB sem necessidade de CSV (--online-grafana).
"""

import os
import sys
import time
import json
import argparse
import datetime
import pandas as pd

# Importa o cliente Grafana local que replica exatamente a conexão do obter_dados_grafana.py
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
if DIRETORIO_ATUAL not in sys.path:
    sys.path.insert(0, DIRETORIO_ATUAL)

from cliente_grafana import ClienteGrafana


def deduplicar_colunas_df(cols):
    """Renomeia colunas repetidas (ex: tag + field 'trava_entrada') como '_1', '_2', padrão Grafana."""
    vistas = {}
    resultado = []
    for col in cols:
        nome = str(col)
        if nome not in vistas:
            vistas[nome] = 0
            resultado.append(nome)
        else:
            vistas[nome] += 1
            resultado.append(f"{nome}_{vistas[nome]}")
    return resultado


def _interpretar_bool(val):
    """Interpreta booleanos vindos como bool, int ou string ('true'/'false') do InfluxDB."""
    if isinstance(val, str):
        return val.lower().strip() in ["true", "1", "1.0", "t", "sim", "yes"]
    if pd.isna(val):
        return False
    return bool(val)


def _safe_float(val, padrao=0.0):
    """Converte valor de telemetria para float tratando None/NaN com segurança."""
    try:
        if val is None or pd.isna(val):
            return padrao
        return float(val)
    except (TypeError, ValueError):
        return padrao


def _normalizar_df_telemetria(df):
    """Garante colunas únicas, coluna Time padronizada, tipos numéricos e ordenação cronológica."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    if df.columns.duplicated().any():
        df.columns = deduplicar_colunas_df(df.columns.tolist())
    if "time" in df.columns and "Time" not in df.columns:
        df = df.rename(columns={"time": "Time"})

    cols_numericas = [
        "v_atual_cph", "velocidade_real_cph", "Velocidade Real LMS",
        "v_setpoint_cph", "velocidade_v4_cph", "Velocidade Segue",
        "velocidade_maquina_sem_controle_cph", "velocidade_maquina_sem_controle",
        "Velocidade Real Shadow", "b1_pct", "b2_pct", "b3_pct", "b4_pct",
        "accumulation_percentage_uip_to_ech_null", "accumulation_percentage_ech_to_pz_null",
        "trava_entrada_int", "v_in_cph", "v_out_cph", "v_nominal_cph",
        "delta_setpoint_real_cph", "percentual_nominal", "setpoint_percentual"
    ]
    for col in cols_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    col_t = "Time" if "Time" in df.columns else ("Timestamp" if "Timestamp" in df.columns else None)
    if col_t:
        df = df.drop_duplicates(subset=[col_t]).sort_values(col_t).reset_index(drop=True)
    return df


def _parsear_influxql_resiliente(data):
    """Converte resposta JSON do proxy InfluxQL em DataFrame normalizado com colunas deduplicadas."""
    results = data.get("results", [])
    if not results or "series" not in results[0]:
        return pd.DataFrame()

    dfs = []
    for series in results[0].get("series", []):
        cols = series.get("columns", [])
        vals = series.get("values", [])
        if not cols or not vals:
            continue
        df_s = pd.DataFrame(vals, columns=deduplicar_colunas_df(cols))
        for tag_k, tag_v in (series.get("tags") or {}).items():
            if tag_k not in df_s.columns:
                df_s[tag_k] = tag_v
        dfs.append(df_s)

    if not dfs:
        return pd.DataFrame()
    df_res = dfs[0] if len(dfs) == 1 else pd.concat(dfs, ignore_index=True)
    return _normalizar_df_telemetria(df_res)


def _parsear_ds_query_resiliente(data):
    """Converte resposta JSON de /api/ds/query (Data Frames Grafana) em DataFrame normalizado."""
    results = data.get("results", {})
    if not results:
        return pd.DataFrame()
    frames = next(iter(results.values()), {}).get("frames", [])
    if not frames:
        return pd.DataFrame()

    dfs = []
    for frame in frames:
        fields = frame.get("schema", {}).get("fields", [])
        values = frame.get("data", {}).get("values", [])
        if not fields or not values or len(fields) != len(values):
            continue
        nomes = deduplicar_colunas_df([f.get("name", "valor") for f in fields])
        dados = {}
        for nome, f, vals in zip(nomes, fields, values):
            if f.get("type") == "time" or nome.lower() in ["time", "_time"]:
                eh_ms = bool(vals and isinstance(vals[0], (int, float)) and vals[0] > 1e11)
                dados["Time"] = pd.to_datetime(vals, unit="ms" if eh_ms else None).astype(str)
            else:
                dados[nome] = vals
        if dados:
            dfs.append(pd.DataFrame(dados))

    if not dfs:
        return pd.DataFrame()
    df_res = dfs[0] if len(dfs) == 1 else pd.concat(dfs, ignore_index=True)
    return _normalizar_df_telemetria(df_res)


def buscar_dados_grafana_resiliente(
    cliente,
    measurement,
    bucket,
    limite=100,
    tempo_inicio_str=None,
    query_template=None
):
    """
    Consulta dados no Grafana/InfluxDB de forma autossuficiente e resiliente:
    - Não depende de métodos novos em cliente_grafana.py no Windows.
    - Deduplica colunas repetidas (tag+field 'trava_entrada').
    - Testa POST e GET no proxy InfluxQL, proxy por UID e /api/ds/query.
    - Faz fallback para ORDER BY time DESC LIMIT N (imune a skew de fuso horário/now()).
    """
    base_url = getattr(cliente, "url", "").rstrip("/")
    ds_id = getattr(cliente, "ds_id", None)
    ds_uid = getattr(cliente, "ds_uid", "")
    headers = dict(getattr(cliente, "headers", {}))
    timeout_q = getattr(cliente, "timeout", 15)
    sessao = getattr(cliente, "session", None)
    if not base_url or ds_id is None or sessao is None:
        return pd.DataFrame()

    proxy_url = f"{base_url}/api/datasources/proxy/{ds_id}/query"
    headers_post = dict(headers)
    headers_post["Content-Type"] = "application/x-www-form-urlencoded"
    headers_post["Accept"] = "application/json"

    meds_candidatas = [measurement]
    alt_med = measurement[:-3] if measurement.endswith("_v4") else f"{measurement}_v4"
    if alt_med not in meds_candidatas:
        meds_candidatas.append(alt_med)

    buckets_candidatos = [bucket]
    for b_alt in ["soda", "Segue"]:
        if b_alt and b_alt not in buckets_candidatos:
            buckets_candidatos.append(b_alt)

    def _rodar_sql(sql_str, db_alvo):
        params = {"db": db_alvo, "q": sql_str}
        # 1. Proxy InfluxQL via POST e GET
        for metodo in ("post", "get"):
            try:
                if metodo == "post":
                    res = sessao.post(proxy_url, headers=headers_post, data=params, timeout=timeout_q)
                else:
                    res = sessao.get(proxy_url, headers=headers, params=params, timeout=timeout_q)
                if res.status_code == 200:
                    df_ok = _parsear_influxql_resiliente(res.json())
                    if not df_ok.empty:
                        return df_ok
            except Exception:
                pass

        # 2. Proxy por UID (Grafana 8+)
        if ds_uid:
            uid_url = f"{base_url}/api/datasources/uid/{ds_uid}/resources/query"
            for metodo in ("post", "get"):
                try:
                    if metodo == "post":
                        res = sessao.post(uid_url, headers=headers_post, data=params, timeout=timeout_q)
                    else:
                        res = sessao.get(uid_url, headers=headers, params=params, timeout=timeout_q)
                    if res.status_code == 200:
                        df_ok = _parsear_influxql_resiliente(res.json())
                        if not df_ok.empty:
                            return df_ok
                except Exception:
                    pass

        # 3. API nativa /api/ds/query
        try:
            ds_query_url = f"{base_url}/api/ds/query"
            ds_headers = dict(headers)
            ds_headers["Content-Type"] = "application/json"
            ds_headers["Accept"] = "application/json"
            ds_ref = {"uid": ds_uid} if ds_uid else {"id": ds_id}
            payload = {
                "from": "now-6h",
                "to": "now",
                "queries": [{
                    "datasource": {"type": "influxdb", **ds_ref},
                    "rawQuery": True,
                    "query": sql_str,
                    "refId": "A",
                    "resultFormat": "table"
                }]
            }
            res_ds = sessao.post(ds_query_url, headers=ds_headers, json=payload, timeout=timeout_q)
            if res_ds.status_code == 200:
                df_ok = _parsear_ds_query_resiliente(res_ds.json())
                if not df_ok.empty:
                    return df_ok
        except Exception:
            pass
        return pd.DataFrame()

    # Fase 1: Tentativa por janela relativa (se solicitada na carga inicial)
    if tempo_inicio_str:
        t_inicio = str(tempo_inicio_str).strip()
        if t_inicio.startswith("-"):
            t_inicio = f"now() - {t_inicio[1:]}"
        for b_cand in buckets_candidatos:
            for med in meds_candidatas:
                if query_template:
                    sql_q = query_template.replace("$timeFilter", f"time >= {t_inicio}").replace("{tempo_inicio}", t_inicio).replace("{tempo_fim}", "now()")
                else:
                    sql_q = f'SELECT * FROM "{med}" WHERE time >= {t_inicio} ORDER BY time ASC'
                df_ret = _rodar_sql(sql_q, b_cand)
                if not df_ret.empty:
                    cliente.bucket = b_cand
                    cliente.measurement = med
                    return df_ret

    # Fase 2: Busca direta dos pontos mais recentes (imune a fuso horário UTC vs local)
    for b_cand in buckets_candidatos:
        for med in meds_candidatas:
            sql_rec = f'SELECT * FROM "{med}" ORDER BY time DESC LIMIT {int(limite)}'
            df_ret = _rodar_sql(sql_rec, b_cand)
            if not df_ret.empty:
                cliente.bucket = b_cand
                cliente.measurement = med
                return df_ret

    return pd.DataFrame()


def carregar_dados(caminho_csv):
    """Carrega o CSV com validação."""
    if not caminho_csv or not os.path.exists(caminho_csv):
        print(f"❌ Arquivo não encontrado: {caminho_csv}")
        return None
    try:
        return pd.read_csv(caminho_csv)
    except Exception as e:
        print(f"❌ Erro ao ler CSV '{caminho_csv}': {e}")
        return None


def obter_coluna_trava(df):
    """Localiza a coluna de telemetria da trava de entrada."""
    for col in ["trava_entrada_int", "trava_entrada", "trava_entrada_1", "Trava Entrada"]:
        if col in df.columns:
            return col
    return None


def obter_coluna_habilitado(df, col_custom=None):
    """Localiza a coluna de habilitação do Segue."""
    if col_custom and col_custom in df.columns:
        return col_custom
    for col in ["segue_habilitado", "SEGUE Habilitado", "segue_on", "Segue Habilitado", "tag_segue_habilitado"]:
        if col in df.columns:
            return col
    return "segue_habilitado"


def obter_coluna_velocidade(df, col_custom=None):
    """Localiza a coluna de velocidade física real da enchedora."""
    if col_custom and col_custom in df.columns:
        return col_custom
    for col in ["v_atual_cph", "velocidade_real_cph", "Velocidade Real LMS", "velocidade_real", "Velocidade_Real_Enchedora"]:
        if col in df.columns:
            return col
    return "v_atual_cph"


def obter_coluna_setpoint_v4(df, col_custom=None):
    """Localiza a coluna de velocidade/setpoint calculada pelo controlador V4."""
    if col_custom and col_custom in df.columns:
        return col_custom
    for col in ["v_setpoint_cph", "velocidade_v4_cph", "Velocidade Segue", "v_otim", "setpoint_v4"]:
        if col in df.columns:
            return col
    return None


def obter_coluna_sem_controle(df, col_custom=None):
    """Localiza a coluna de velocidade de referência sem controle / shadow / CLP nativo."""
    if col_custom and col_custom in df.columns:
        return col_custom
    for col in [
        "velocidade_maquina_sem_controle_cph",
        "velocidade_maquina_sem_controle",
        "Velocidade Real Shadow",
        "v_sem_controle",
        "velocidade_sem_controle",
        "v_shadow"
    ]:
        if col in df.columns:
            return col
    return None


def filtrar_trava(df, val_trava, col_trava=None):
    """Filtra dados pela tag de trava de entrada."""
    if val_trava is None or str(val_trava).lower() in ["none", "all", "todas"]:
        return df
    if col_trava is None:
        col_trava = obter_coluna_trava(df)
    if col_trava is None or col_trava not in df.columns:
        return df

    try:
        val_int = int(val_trava)
    except ValueError:
        return df

    serie_trava = df[col_trava]
    if isinstance(serie_trava, pd.DataFrame):
        serie_trava = serie_trava.iloc[:, 0]

    if serie_trava.dtype == bool:
        return df[serie_trava == (val_int == 1)].copy()
    elif serie_trava.dtype == object:
        is_match = serie_trava.astype(str).str.strip().isin([str(val_int), "True" if val_int == 1 else "False", f"{val_int}.0"])
        return df[is_match].copy()
    else:
        return df[serie_trava == val_int].copy()


def filtrar_on_off(df, col_en=None):
    """Separa períodos com e sem controle."""
    if col_en is None:
        col_en = obter_coluna_habilitado(df)
    if col_en not in df.columns:
        return None, None
    serie_en = df[col_en]
    if isinstance(serie_en, pd.DataFrame):
        serie_en = serie_en.iloc[:, 0]
    if serie_en.dtype == object:
        is_on = serie_en.astype(str).str.lower().str.strip().isin(["true", "1", "1.0", "t", "sim", "yes"])
    else:
        is_on = serie_en.astype(bool)
    return df[is_on].copy(), df[~is_on].copy()


def obter_duracao_horas(df):
    """Calcula a duração real em horas a partir do timestamp ou ciclo de 10s."""
    if len(df) == 0:
        return 0.0
    for col_time in ["Time", "Timestamp", "time", "_time"]:
        if col_time in df.columns:
            try:
                ts = pd.to_datetime(df[col_time])
                dt_s = ts.diff().dt.total_seconds().median()
                if pd.notnull(dt_s) and dt_s > 0:
                    return len(df) * (dt_s / 3600.0)
                duracao = (ts.max() - ts.min()).total_seconds() / 3600.0
                if duracao > 0:
                    return duracao
            except Exception:
                pass
    return len(df) * (10.0 / 3600.0)


def calcular_metricas(
    df_com,
    df_sem,
    col_velocidade=None,
    col_b_in=None,
    col_b_out=None,
    limiar_rastejo=20000.0,
    limiar_b_out_gargalo=70.0,
    limiar_b_in_min=30.0,
    horas_turno=8.0
):
    """Calcula todas as métricas de ganho físico e redução de paradas/rastejos."""
    col_v = col_velocidade if (col_velocidade and col_velocidade in df_com.columns) else obter_coluna_velocidade(df_com)
    if col_v not in df_sem.columns:
        col_v = col_velocidade if (col_velocidade and col_velocidade in df_sem.columns) else obter_coluna_velocidade(df_sem)

    if not col_b_out or col_b_out not in df_com.columns:
        col_b_out = "b3_pct" if "b3_pct" in df_com.columns else "accumulation_percentage_ech_to_pz_null"
    if not col_b_in or col_b_in not in df_com.columns:
        col_b_in = "b2_pct" if "b2_pct" in df_com.columns else "accumulation_percentage_uip_to_ech_null"

    t_sem_h = obter_duracao_horas(df_sem)
    t_com_h = obter_duracao_horas(df_com)

    if t_sem_h <= 0 or t_com_h <= 0 or len(df_com) == 0 or len(df_sem) == 0:
        return None

    # 1. Ritmo de Produção e Ganho
    taxa_sem = df_sem[col_v].mean()
    taxa_com = df_com[col_v].mean()
    ganho_cph = taxa_com - taxa_sem
    ganho_pct = (ganho_cph / taxa_sem) * 100.0 if taxa_sem > 0 else 0.0

    total_ganho_gf = ganho_cph * t_com_h
    ganho_turno_calc = ganho_cph * horas_turno

    # 2. Resgate de Paradas e Rastejos (< limiar_rastejo CPH)
    micro_sem_pct = (df_sem[col_v] < limiar_rastejo).mean() * 100.0
    micro_com_pct = (df_com[col_v] < limiar_rastejo).mean() * 100.0
    pct_salvo_rastejo = max(0.0, (micro_sem_pct - micro_com_pct) / 100.0)
    minutos_salvos = pct_salvo_rastejo * t_com_h * 60.0

    min_rastejo_sem_h = (micro_sem_pct / 100.0) * 60.0
    min_rastejo_com_h = (micro_com_pct / 100.0) * 60.0
    reducao_rastejo_pct = ((min_rastejo_sem_h - min_rastejo_com_h) / min_rastejo_sem_h * 100.0) if min_rastejo_sem_h > 0 else 0.0

    # 3. Paradas Totais (v == 0)
    paradas_zero_sem = (df_sem[col_v] == 0).sum()
    paradas_zero_com = (df_com[col_v] == 0).sum()
    min_parada_sem = paradas_zero_sem * (10.0 / 60.0)
    min_parada_com = paradas_zero_com * (10.0 / 60.0)

    # 4. Prova sob Gargalo
    v_sem_g, v_com_g, ganho_g_pct = None, None, None
    if (col_b_out in df_sem.columns) and (col_b_in in df_sem.columns) and \
       (col_b_out in df_com.columns) and (col_b_in in df_com.columns):
        sem_g = df_sem[(df_sem[col_b_in] >= limiar_b_in_min) & (df_sem[col_b_out] >= limiar_b_out_gargalo)]
        com_g = df_com[(df_com[col_b_in] >= limiar_b_in_min) & (df_com[col_b_out] >= limiar_b_out_gargalo)]
        if len(sem_g) > 0 and len(com_g) > 0:
            v_sem_g = sem_g[col_v].mean()
            v_com_g = com_g[col_v].mean()
            ganho_g_pct = ((v_com_g / v_sem_g) - 1.0) * 100.0 if v_sem_g > 0 else 0.0

    return {
        "t_sem_h": t_sem_h,
        "t_com_h": t_com_h,
        "taxa_sem": taxa_sem,
        "taxa_com": taxa_com,
        "ganho_cph": ganho_cph,
        "ganho_pct": ganho_pct,
        "total_ganho_gf": total_ganho_gf,
        "ganho_turno_8h": ganho_turno_calc,
        "horas_turno": horas_turno,
        "limiar_rastejo": limiar_rastejo,
        "micro_sem_pct": micro_sem_pct,
        "micro_com_pct": micro_com_pct,
        "minutos_salvos": minutos_salvos,
        "reducao_rastejo_pct": reducao_rastejo_pct,
        "min_rastejo_sem_h": min_rastejo_sem_h,
        "min_rastejo_com_h": min_rastejo_com_h,
        "paradas_zero_sem": paradas_zero_sem,
        "paradas_zero_com": paradas_zero_com,
        "min_parada_sem": min_parada_sem,
        "min_parada_com": min_parada_com,
        "v_sem_g": v_sem_g,
        "v_com_g": v_com_g,
        "ganho_g_pct": ganho_g_pct,
        "n_com": len(df_com),
        "n_sem": len(df_sem)
    }


def calcular_metricas_contrafactual_ou_sombra(df, col_v, col_sp=None, col_sem=None, horas_turno=8.0, limiar_rastejo=20000.0):
    """Calcula métricas quando há apenas um período (ex: 100% OFF ou 100% ON)."""
    dur_h = obter_duracao_horas(df)
    v_med = df[col_v].mean() if col_v in df.columns else 0.0

    paradas_zero = (df[col_v] == 0).sum() if col_v in df.columns else 0
    min_parada = paradas_zero * (10.0 / 60.0)
    micro_pct = (df[col_v] < limiar_rastejo).mean() * 100.0 if col_v in df.columns else 0.0
    min_rastejo_h = (micro_pct / 100.0) * 60.0

    # Compara V_SP vs V_Real (se houver setpoint V4)
    if col_sp and col_sp in df.columns:
        sp_med = df[col_sp].mean()
        deltas = df[col_sp] - df[col_v]
        delta_m = deltas.mean()
        tot_gf = delta_m * dur_h
        turno_gf = delta_m * horas_turno
        pct_m = (delta_m / v_med * 100.0) if v_med > 0 else 0.0
        return {
            "dur_h": dur_h,
            "n": len(df),
            "v_med": v_med,
            "sp_med": sp_med,
            "delta_m": delta_m,
            "pct_m": pct_m,
            "tot_gf": tot_gf,
            "turno_gf": turno_gf,
            "paradas_zero": paradas_zero,
            "min_parada": min_parada,
            "min_rastejo_h": min_rastejo_h,
            "tipo": "SP_VS_REAL"
        }

    # Compara V_Real vs V_Sem (se houver baseline sem controle)
    if col_sem and col_sem in df.columns:
        sem_med = df[col_sem].mean()
        deltas = df[col_v] - df[col_sem]
        delta_m = deltas.mean()
        tot_gf = delta_m * dur_h
        turno_gf = delta_m * horas_turno
        pct_m = (delta_m / sem_med * 100.0) if sem_med > 0 else 0.0
        return {
            "dur_h": dur_h,
            "n": len(df),
            "v_med": v_med,
            "sem_med": sem_med,
            "delta_m": delta_m,
            "pct_m": pct_m,
            "tot_gf": tot_gf,
            "turno_gf": turno_gf,
            "paradas_zero": paradas_zero,
            "min_parada": min_parada,
            "min_rastejo_h": min_rastejo_h,
            "tipo": "REAL_VS_SEM"
        }

    return None


def formatar_status_novo_dado(
    ultima_linha,
    df_acumulado,
    col_v,
    col_sp,
    col_sem,
    col_en,
    col_tr,
    h_turno=8.0,
    m_ab=None,
    novas_amostras=None
):
    """
    Gera linha de status a cada novo dado recebido:
    - Com Segue LIGADO: mostra ganho real entregue (ou perca) vs baseline.
    - Com Segue DESLIGADO: mostra oportunidade V4 e perda acumulada por manter Segue desligado.
    """
    v_col_nome = col_v if (col_v and col_v in df_acumulado.columns) else obter_coluna_velocidade(df_acumulado)
    en_col_nome = col_en if (col_en and col_en in df_acumulado.columns) else obter_coluna_habilitado(df_acumulado)
    tr_col_nome = col_tr if (col_tr and col_tr in df_acumulado.columns) else obter_coluna_trava(df_acumulado)

    sp_col_nome = col_sp if (col_sp and col_sp in df_acumulado.columns) else obter_coluna_setpoint_v4(df_acumulado)
    sem_col_nome = col_sem if (col_sem and col_sem in df_acumulado.columns) else obter_coluna_sem_controle(df_acumulado)

    v_atual = _safe_float(ultima_linha.get(v_col_nome, 0.0), 0.0)
    segue_on = _interpretar_bool(ultima_linha.get(en_col_nome, False))

    trava_val = ultima_linha.get(tr_col_nome or "trava_entrada_int", "N/A")
    ts_str = str(ultima_linha.get("Time", ultima_linha.get("Timestamp", datetime.datetime.now().strftime("%H:%M:%S"))))
    ts_curto = ts_str.split(".")[0].rstrip("Z")[-8:]

    v_sp = _safe_float(ultima_linha.get(sp_col_nome, v_atual), v_atual) if sp_col_nome else v_atual
    v_sem = _safe_float(ultima_linha.get(sem_col_nome, 0.0), 0.0) if sem_col_nome else None

    status_txt = "🟢 SEGUE ON " if segue_on else "🔴 SEGUE OFF"
    sufixo_novas = f" (+{novas_amostras} novas)" if (novas_amostras is not None and novas_amostras > 0) else ""
    amostras_txt = f"Amostras: {len(df_acumulado)}{sufixo_novas}"

    # Se a máquina física estiver parada (< 1000 CPH)
    if v_atual < 1000.0:
        return (
            f"\r[{ts_curto}] 🛑 PARADA FÍSICA | {status_txt} | Trava: {trava_val} | V_Real: 0 CPH | "
            f"Parada em segurança (0 gf geradas) | {amostras_txt}"
        )

    # 1. Se temos o comparativo A/B calculado (períodos com e sem controle no histórico)
    if m_ab:
        sinal_g = "+" if m_ab['ganho_cph'] >= 0 else ""
        rotulo = "🏆 Ganho A/B" if m_ab['ganho_cph'] >= 0 else "🔻 Perca A/B"
        ref_sp = f" (SP: {v_sp:,.0f})" if sp_col_nome else ""
        return (
            f"\r[{ts_curto}] {status_txt} | Trava: {trava_val} | V_Real: {v_atual:,.0f} CPH{ref_sp} | "
            f"{rotulo}: {sinal_g}{m_ab['total_ganho_gf']:,.0f} gf ({sinal_g}{m_ab['ganho_cph']:,.0f} CPH | {m_ab['ganho_pct']:+.1f}%) | "
            f"Turno {h_turno:.0f}h: {sinal_g}{m_ab['ganho_turno_8h']:,.0f} gf | {amostras_txt}"
        )

    duracao_h = obter_duracao_horas(df_acumulado)

    # 2. Se Segue está LIGADO
    if segue_on:
        if sem_col_nome and v_col_nome in df_acumulado.columns:
            deltas = df_acumulado[v_col_nome] - df_acumulado[sem_col_nome]
            delta_medio_cph = _safe_float(deltas.mean(), 0.0)
            garrafas_acum = delta_medio_cph * duracao_h
            sem_mean = _safe_float(df_acumulado[sem_col_nome].mean(), 0.0)
            pct_medio = (delta_medio_cph / sem_mean * 100.0) if sem_mean > 0 else 0.0
            rotulo = "🏆 Ganho Real" if delta_medio_cph >= 0 else "🔻 Perca Real"
            sinal = "+" if delta_medio_cph >= 0 else ""
            return (
                f"\r[{ts_curto}] {status_txt} | Trava: {trava_val} | V_Real: {v_atual:,.0f} CPH (SemCtrl: {v_sem:,.0f}) | "
                f"{rotulo}: {sinal}{garrafas_acum:,.0f} gf ({sinal}{delta_medio_cph:,.0f} CPH | {pct_medio:+.1f}%) | "
                f"Turno {h_turno:.0f}h: {sinal}{delta_medio_cph * h_turno:,.0f} gf | {amostras_txt}"
            )
        elif sp_col_nome and v_col_nome in df_acumulado.columns:
            delta_sp = _safe_float((df_acumulado[sp_col_nome] - df_acumulado[v_col_nome]).mean(), 0.0)
            sinal = "+" if delta_sp >= 0 else ""
            return (
                f"\r[{ts_curto}] {status_txt} | Trava: {trava_val} | V_Real: {v_atual:,.0f} CPH (SP: {v_sp:,.0f}) | "
                f"🎯 Delta SP: {sinal}{delta_sp:,.0f} CPH | Turno {h_turno:.0f}h: {v_atual * h_turno:,.0f} gf | {amostras_txt}"
            )

    # 3. Se Segue está DESLIGADO
    if sp_col_nome and v_col_nome in df_acumulado.columns:
        deltas = df_acumulado[sp_col_nome] - df_acumulado[v_col_nome]
        delta_medio_cph = _safe_float(deltas.mean(), 0.0)
        garrafas_oport = delta_medio_cph * duracao_h
        v_mean = _safe_float(df_acumulado[v_col_nome].mean(), 0.0)
        pct_medio = (delta_medio_cph / v_mean * 100.0) if v_mean > 0 else 0.0

        if delta_medio_cph > 0:
            rotulo = "⚡ Oportunidade V4"
            sinal = "+"
            detalhe_perda = f" [Perda Segue OFF: -{garrafas_oport:,.0f} gf]"
        elif delta_medio_cph < 0:
            rotulo = "🛡️ Modulação V4"
            sinal = ""
            detalhe_perda = " [Excesso de Risco]"
        else:
            rotulo = "⚖️ Equilíbrio"
            sinal = "+"
            detalhe_perda = ""

        return (
            f"\r[{ts_curto}] {status_txt} | Trava: {trava_val} | V_Real: {v_atual:,.0f} CPH (SP V4: {v_sp:,.0f}) | "
            f"{rotulo}: {sinal}{garrafas_oport:,.0f} gf ({sinal}{delta_medio_cph:,.0f} CPH | {pct_medio:+.1f}%){detalhe_perda} | "
            f"Turno {h_turno:.0f}h: {sinal}{delta_medio_cph * h_turno:,.0f} gf | {amostras_txt}"
        )

    return (
        f"\r[{ts_curto}] {status_txt} | Trava: {trava_val} | V_Real: {v_atual:,.0f} CPH (SP: {v_sp:,.0f}) | "
        f"{amostras_txt}"
    )


def exibir_relatorio(m, titulo="RESUMO EXECUTIVO: GANHO REAL DO CONTROLE"):
    """Exibe o relatório formatado de forma limpa e executiva."""
    print("\n" + "═" * 70)
    print(f" {titulo:^68}")
    print("═" * 70)
    print(f" Tempo Analisado : {m['t_com_h']:.2f} h COM controle ({m['n_com']} amostras) vs {m['t_sem_h']:.2f} h SEM controle ({m['n_sem']} amostras)")
    print("─" * 70)
    print(f" 🏆 GANHO TOTAL ENTREGUE   : +{m['total_ganho_gf']:,.0f} GARRAFAS A MAIS ({m['ganho_pct']:+.2f}%)")
    print(f" ⚡ Ritmo Médio da Linha   : Subiu de {m['taxa_sem']:,.0f} para {m['taxa_com']:,.0f} garrafas/hora (+{m['ganho_cph']:,.0f} CPH)")
    print(f" 📦 Impacto no Turno (8h)  : +{m['ganho_turno_8h']:,.0f} garrafas a mais por dia")
    print("─" * 70)
    print(" 🛑 ANÁLISE DE PARADAS E RASTEJOS:")
    print(f" • Redução do Tempo Lento : O rastejo (<20k CPH) caiu de {m['min_rastejo_sem_h']:.1f} para {m['min_rastejo_com_h']:.1f} min/h ({m['reducao_rastejo_pct']:+.1f}%)")
    print(f" • Tempo Salvo de Linha   : A enchedora economizou {m['minutos_salvos']:.1f} minutos de lentidão/rastejo.")

    if m["paradas_zero_sem"] > 0 or m["paradas_zero_com"] > 0:
        print(f" • Paradas a 0 CPH        : SEM controle: {m['min_parada_sem']:.1f} min | COM controle: {m['min_parada_com']:.1f} min")

    if m["v_sem_g"] and m["v_com_g"]:
        print(f"\n 🎯 PROVA SOB ESTRELA CHEIA / GARGALO (Buffer Saída >= 70%):")
        print(f" • Sem Controle : A máquina caía para {m['v_sem_g']:,.0f} garrafas/hora.")
        print(f" • Com Controle : Manteve fluxo a {m['v_com_g']:,.0f} garrafas/hora ({m['ganho_g_pct']:+.1f}% mais rápida).")
    print("═" * 70 + "\n")


def exibir_relatorio_modo_unico(m, segue_on, titulo="RESUMO EXECUTIVO: BALANÇO DE PRODUÇÃO"):
    """Exibe o relatório quando a medição possui apenas dados com Segue LIGADO ou DESLIGADO."""
    print("\n" + "═" * 70)
    print(f" {titulo:^68}")
    print("═" * 70)
    print(f" Tempo Analisado : {m['dur_h']:.2f} h ({m['n']} amostras)")
    print("─" * 70)

    sinal = "+" if m["delta_m"] >= 0 else ""
    sinal_t = "+" if m["turno_gf"] >= 0 else ""

    if segue_on:
        rotulo_bal = "GANHO LÍQUIDO ENTREGUE" if m["delta_m"] >= 0 else "PERCA / DESACELERAÇÃO"
        ref_txt = f"{m.get('sem_med', 0.0):,.0f} CPH (Sem Controle)" if 'sem_med' in m else f"{m.get('sp_med', 0.0):,.0f} CPH (Setpoint V4)"
        print(f" 🟢 CENÁRIO: SEGUE LIGADO (OPERAÇÃO ATIVA NO CONTROLE V4)")
        print(f" 🏆 {rotulo_bal:<23}: {sinal}{m['tot_gf']:,.0f} GARRAFAS ({m['pct_m']:+.2f}%)")
        print(f" ⚡ Ritmo Médio da Máquina : {m['v_med']:,.0f} garrafas/hora (Referência: {ref_txt})")
        print(f" 📦 Projeção no Turno (8h) : {sinal_t}{m['turno_gf']:,.0f} garrafas por turno")
    else:
        print(f" 🔴 CENÁRIO: SEGUE DESLIGADO (CLP NATIVO / MODO SOMBRA / BYPASS)")
        print(f" ⚡ Ritmo Médio da Máquina : {m['v_med']:,.0f} garrafas/hora")
        print(f" 🎯 Ritmo Recomendado V4   : {m.get('sp_med', 0.0):,.0f} garrafas/hora (Setpoint V4 em Modo Sombra)")
        if m["delta_m"] > 0:
            print(f" ⚡ OPORTUNIDADE NÃO GANHA : +{m['tot_gf']:,.0f} garrafas poderiam ter sido envasadas")
            print(f" 🔻 PERDA POR SEGUE OFF    : -{m['tot_gf']:,.0f} garrafas perdidas (-{m['delta_m']:,.0f} CPH | {m['pct_m']:+.2f}%)")
        else:
            print(f" 🛡️ MODULAÇÃO PREVENTIVA   : V4 teria reduzido {abs(m['delta_m']):,.0f} CPH para proteção de buffer")
        print(f" 📦 Impacto no Turno (8h)  : {sinal_t}{m['turno_gf']:,.0f} garrafas em 8h com Segue ativo")

    print(f" • Paradas a 0 CPH         : {m['min_parada']:.1f} min ({m['paradas_zero']} ocorrências)")
    print(f" • Tempo em Rastejo        : {m['min_rastejo_h']:.1f} min/h (< 20,000 CPH)")
    print("═" * 70 + "\n")


def exibir_inspecao_colunas(colunas, cfg_colunas=None, fonte=""):
    """Exibe um diagnóstico completo das colunas encontradas e valida com o config."""
    print("\n" + "═" * 70)
    print(f"       COLUNAS DISPONÍVEIS NA MEDIÇÃO / ARQUIVO ({fonte})")
    print("═" * 70)

    if not colunas:
        print("❌ Nenhuma coluna foi retornada. Verifique conexão ou arquivo.")
        print("═" * 70 + "\n")
        return

    cols_v = [c for c in colunas if any(k in c.lower() for k in ["velocidade", "speed", "cph"])]
    cols_tr = [c for c in colunas if any(k in c.lower() for k in ["trava"])]
    cols_en = [c for c in colunas if any(k in c.lower() for k in ["segue", "habilitado", "on_off"])]
    cols_b = [c for c in colunas if any(k in c.lower() for k in ["buffer", "accum", "b1", "b2", "b3", "b4"])]

    print(f" 📊 Total de Colunas Encontradas: {len(colunas)}\n")

    if cols_v:
        print(" ⚡ Variáveis de Velocidade Identificadas:")
        for c in cols_v:
            print(f"   • {c}")

    if cols_tr:
        print("\n 🔒 Variáveis de Trava Identificadas:")
        for c in cols_tr:
            print(f"   • {c}")

    if cols_en:
        print("\n 🟢 Variáveis de Controle / Segue Habilitado:")
        for c in cols_en:
            print(f"   • {c}")

    if cols_b:
        print("\n 📦 Variáveis de Buffers / Esteiras:")
        for c in cols_b:
            print(f"   • {c}")

    print("\n 📋 Lista Completa de Todas as Colunas:")
    for idx, c in enumerate(colunas, 1):
        print(f"   {idx:2d}. {c}")

    if cfg_colunas:
        print("\n" + "─" * 70)
        print(" 🔍 Validação com config_medidor.json:")
        for chave, nome in cfg_colunas.items():
            if chave.startswith("coluna_") and nome:
                status = "✅ Existe" if nome in colunas else "❌ NÃO Encontrada"
                print(f"   • {chave:<25}: '{nome}' -> {status}")
    print("═" * 70 + "\n")


def executar_modo_online(caminho_csv, trava_filtro=None, intervalo_s=2.0, caminho_sem=None):
    """Monitora o CSV em tempo real e calcula ganho ou perca a cada novo dado que chega."""
    print("\n" + "═" * 70)
    print("      MEDIDOR DE GANHO INDUSTRIAL - MODO ONLINE (TEMPO REAL)")
    print("═" * 70)
    print(f" 📂 Monitorando Arquivo : {caminho_csv}")
    print(f" 🔒 Filtro de Trava     : {'Trava Entrada == ' + str(trava_filtro) if trava_filtro is not None else 'Todas as condições'}")
    print(f" ⏱️ Intervalo de Varredura: {intervalo_s:.1f} segundos")
    print(" Pressione [Ctrl+C] a qualquer momento para encerrar e ver o resumo final.")
    print("─" * 70)

    ultimo_tamanho = -1
    df_sem_externo = None
    if caminho_sem:
        df_sem_externo = carregar_dados(caminho_sem)
        if df_sem_externo is not None:
            df_sem_externo = filtrar_trava(df_sem_externo, trava_filtro)

    try:
        while True:
            if not os.path.exists(caminho_csv):
                time.sleep(intervalo_s)
                continue

            tamanho_atual = os.path.getsize(caminho_csv)
            if tamanho_atual != ultimo_tamanho:
                ultimo_tamanho = tamanho_atual
                df = pd.read_csv(caminho_csv)
                total_linhas = len(df)

                if total_linhas > 0:
                    df_filtrado = filtrar_trava(df, trava_filtro)
                    df_com, df_sem_interno = filtrar_on_off(df_filtrado)
                    df_sem = df_sem_externo if df_sem_externo is not None else df_sem_interno

                    m = None
                    if df_com is not None and df_sem is not None and len(df_com) > 0 and len(df_sem) > 0:
                        m = calcular_metricas(df_com, df_sem)

                    ultima_linha = df.iloc[-1]
                    col_v = obter_coluna_velocidade(df)
                    col_en = obter_coluna_habilitado(df)
                    col_tr = obter_coluna_trava(df)
                    col_sp = obter_coluna_setpoint_v4(df)
                    col_sem_c = obter_coluna_sem_controle(df)

                    msg_linha = formatar_status_novo_dado(
                        ultima_linha=ultima_linha,
                        df_acumulado=df_filtrado,
                        col_v=col_v,
                        col_sp=col_sp,
                        col_sem=col_sem_c,
                        col_en=col_en,
                        col_tr=col_tr,
                        m_ab=m
                    )
                    sys.stdout.write(msg_linha)
                    sys.stdout.flush()

            time.sleep(intervalo_s)
    except KeyboardInterrupt:
        print("\n\n" + "─" * 70)
        print(" ⏹️ Monitoramento Online Interrompido. Consolidando relatório da sessão...")
        df_final = carregar_dados(caminho_csv)
        if df_final is not None:
            df_filtrado = filtrar_trava(df_final, trava_filtro)
            df_com, df_sem_interno = filtrar_on_off(df_filtrado)
            df_sem = df_sem_externo if df_sem_externo is not None else df_sem_interno
            col_v = obter_coluna_velocidade(df_filtrado)
            col_en = obter_coluna_habilitado(df_filtrado)
            col_sp = obter_coluna_setpoint_v4(df_filtrado)
            col_sem_c = obter_coluna_sem_controle(df_filtrado)

            if df_com is not None and df_sem is not None and len(df_com) > 0 and len(df_sem) > 0:
                m = calcular_metricas(df_com, df_sem)
                if m:
                    tit = "RESUMO DA SESSÃO ONLINE (TOTAL ACUMULADO A/B)"
                    if trava_filtro is not None:
                        tit += f" [TRAVA == {trava_filtro}]"
                    exibir_relatorio(m, titulo=tit)
            elif len(df_filtrado) > 0:
                val_en = df_filtrado.iloc[-1].get(col_en, False)
                segue_on = _interpretar_bool(val_en)
                m_unico = calcular_metricas_contrafactual_ou_sombra(df_filtrado, col_v=col_v, col_sp=col_sp, col_sem=col_sem_c)
                if m_unico:
                    tit = "RESUMO DA SESSÃO ONLINE"
                    if trava_filtro is not None:
                        tit += f" [TRAVA == {trava_filtro}]"
                    exibir_relatorio_modo_unico(m_unico, segue_on=segue_on, titulo=tit)


def _exibir_resumo_grafana(
    df_acumulado,
    trava_filtro,
    col_tr,
    col_v,
    col_en,
    col_sp,
    col_sem_cfg,
    col_b_in,
    col_b_out,
    lim_rastejo,
    lim_b_out,
    lim_b_in,
    h_turno,
    df_sem_externo,
    titulo_base
):
    """Calcula e exibe o resumo consolidado (A/B ou modo único) a partir do histórico em memória."""
    if df_acumulado is None or len(df_acumulado) == 0:
        return
    df_filtrado = filtrar_trava(df_acumulado, trava_filtro, col_trava=col_tr)
    df_alvo = df_filtrado if len(df_filtrado) > 0 else df_acumulado

    df_com, df_sem_interno = filtrar_on_off(df_alvo, col_en=col_en)
    df_sem = df_sem_externo if df_sem_externo is not None else df_sem_interno

    tit = titulo_base
    if trava_filtro is not None and len(df_filtrado) > 0:
        tit += f" [TRAVA == {trava_filtro}]"
    elif trava_filtro is not None:
        tit += f" [SEM REGISTROS COM TRAVA == {trava_filtro} - TODAS AS CONDIÇÕES]"

    if df_com is not None and df_sem is not None and len(df_com) > 0 and len(df_sem) > 0:
        m = calcular_metricas(
            df_com, df_sem,
            col_velocidade=col_v, col_b_in=col_b_in, col_b_out=col_b_out,
            limiar_rastejo=lim_rastejo, limiar_b_out_gargalo=lim_b_out,
            limiar_b_in_min=lim_b_in, horas_turno=h_turno
        )
        if m:
            exibir_relatorio(m, titulo=tit)
            return

    col_v_f = col_v if (col_v and col_v in df_alvo.columns) else obter_coluna_velocidade(df_alvo)
    col_en_f = col_en if (col_en and col_en in df_alvo.columns) else obter_coluna_habilitado(df_alvo)
    col_sp_f = col_sp if (col_sp and col_sp in df_alvo.columns) else obter_coluna_setpoint_v4(df_alvo)
    col_sem_f = col_sem_cfg if (col_sem_cfg and col_sem_cfg in df_alvo.columns) else obter_coluna_sem_controle(df_alvo)

    val_en = df_alvo.iloc[-1].get(col_en_f, False)
    segue_on = _interpretar_bool(val_en)
    m_unico = calcular_metricas_contrafactual_ou_sombra(
        df_alvo,
        col_v=col_v_f,
        col_sp=col_sp_f,
        col_sem=col_sem_f,
        horas_turno=h_turno,
        limiar_rastejo=lim_rastejo
    )
    if m_unico:
        exibir_relatorio_modo_unico(m_unico, segue_on=segue_on, titulo=tit)


def _montar_linha_status_grafana(
    cliente,
    df_acumulado,
    trava_filtro,
    col_tr,
    col_v,
    col_en,
    col_sp,
    col_sem_cfg,
    col_b_in,
    col_b_out,
    lim_rastejo,
    lim_b_out,
    lim_b_in,
    h_turno,
    df_sem_externo,
    soda_ativo,
    cfg_soda,
    novas_amostras=None
):
    """Prepara e formata a linha de telemetria em tempo real para exibição imediata."""
    df_filtrado = filtrar_trava(df_acumulado, trava_filtro, col_trava=col_tr)
    df_base_status = df_filtrado if len(df_filtrado) > 0 else df_acumulado

    df_com, df_sem_interno = filtrar_on_off(df_base_status, col_en=col_en)
    df_sem = df_sem_externo if df_sem_externo is not None else df_sem_interno

    m = None
    if df_com is not None and df_sem is not None and len(df_com) > 0 and len(df_sem) > 0:
        m = calcular_metricas(
            df_com, df_sem,
            col_velocidade=col_v, col_b_in=col_b_in, col_b_out=col_b_out,
            limiar_rastejo=lim_rastejo, limiar_b_out_gargalo=lim_b_out,
            limiar_b_in_min=lim_b_in, horas_turno=h_turno
        )

    ultima_linha = df_acumulado.iloc[-1]
    msg_linha = formatar_status_novo_dado(
        ultima_linha=ultima_linha,
        df_acumulado=df_base_status,
        col_v=col_v,
        col_sp=col_sp,
        col_sem=col_sem_cfg,
        col_en=col_en,
        col_tr=col_tr,
        h_turno=h_turno,
        m_ab=m,
        novas_amostras=novas_amostras
    )
    if soda_ativo:
        cnt_soda = cliente.buscar_contador_soda(cfg_soda)
        if cnt_soda is not None:
            msg_linha += f" | 🍾 SODA: {cnt_soda:,.0f} gf"
    return msg_linha


def executar_modo_online_grafana(
    url="http://10.91.7.221:3000",
    user="admin",
    password="!ambev2021",
    token="",
    ds_selector="17",
    bucket="Segue",
    measurement="512",
    org="ABinbev",
    trava_filtro=None,
    intervalo_s=5.0,
    janela_historico="4h",
    caminho_sem=None,
    query_template=None,
    cfg_colunas=None,
    cfg_analise=None,
    cfg_soda=None
):
    """Conecta diretamente à API do Grafana e monitora a telemetria a cada novo dado."""
    cfg_col = cfg_colunas or {}
    cfg_an = cfg_analise or {}
    soda_ativo = bool(cfg_soda and cfg_soda.get("habilitado", False))

    col_v = cfg_col.get("coluna_velocidade_real")
    col_tr = cfg_col.get("coluna_trava_entrada")
    col_en = cfg_col.get("coluna_segue_habilitado")
    col_b_in = cfg_col.get("coluna_buffer_entrada_b2")
    col_b_out = cfg_col.get("coluna_buffer_saida_b3")
    col_sp = cfg_col.get("coluna_velocidade_v4")
    col_sem_cfg = cfg_col.get("coluna_velocidade_sem_controle")

    lim_rastejo = float(cfg_an.get("limiar_rastejo_cph", 20000.0))
    lim_b_out = float(cfg_an.get("limiar_buffer_saida_gargalo_pct", 70.0))
    lim_b_in = float(cfg_an.get("limiar_buffer_entrada_min_pct", 30.0))
    h_turno = float(cfg_an.get("horas_turno_projecao", 8.0))

    print("\n" + "═" * 70)
    print("   MEDIDOR DE GANHO INDUSTRIAL - STREAMING DIRETO DA API DO GRAFANA")
    print("═" * 70)
    print(f" 🌐 URL Grafana       : {url}")
    print(f" 🏭 Measurement/Linha : {measurement} (Bucket: {bucket} | DS: {ds_selector})")
    print(f" 🔒 Filtro de Trava   : {'Trava Entrada == ' + str(trava_filtro) if trava_filtro is not None else 'Todas as condições'}")
    print(f" ⏱️ Ciclo de Varredura : {intervalo_s:.1f} segundos")
    print(f" ⏳ Janela Histórica  : {janela_historico}")
    print(f" 📊 Limiar Rastejo    : < {lim_rastejo:,.0f} CPH | Projeção Turno: {h_turno:.0f}h")
    if soda_ativo:
        print(f" 🍾 Auditoria SODA    : DB: {cfg_soda.get('database')} (DS: {cfg_soda.get('datasource')}) | Eq: {cfg_soda.get('equipment_name')}")
    if query_template:
        print(f" 📝 Query Raw InfluxQL : {query_template}")
    print(" Pressione [Ctrl+C] a qualquer momento para encerrar e ver o resumo consolidado.")
    print("─" * 70)

    try:
        cliente = ClienteGrafana(
            url=url, user=user, password=password, token=token,
            ds_selector=ds_selector, bucket=bucket, measurement=measurement, org=org,
            query_template=query_template
        )
    except TypeError:
        cliente = ClienteGrafana(
            url=url, user=user, password=password, token=token,
            ds_selector=ds_selector, bucket=bucket, measurement=measurement, org=org
        )
        if query_template:
            setattr(cliente, "query_template", query_template)

    if not cliente.conectar():
        print("❌ Falha na conexão com o Grafana. Verifique credenciais e rede.")
        return False

    print(f"➔ Conectando e buscando telemetria na medição '{cliente.measurement}' (histórico: {janela_historico})...")
    df_acumulado = buscar_dados_grafana_resiliente(
        cliente=cliente,
        measurement=cliente.measurement,
        bucket=cliente.bucket,
        limite=500,
        tempo_inicio_str=f"-{janela_historico}",
        query_template=query_template
    )

    df_sem_externo = None
    if caminho_sem:
        df_sem_externo = carregar_dados(caminho_sem)
        if df_sem_externo is not None:
            df_sem_externo = filtrar_trava(df_sem_externo, trava_filtro, col_trava=col_tr)

    if df_acumulado.empty:
        print(f"⚠ Nenhum ponto retornado para a medição '{cliente.measurement}' no intervalo inicial.")
        print("➔ Modo streaming ativo: aguardando chegada de novos pontos do CLP/Controlador...")
    else:
        print(f"✅ Telemetria conectada: {len(df_acumulado)} amostras carregadas de '{cliente.measurement}' (Bucket: '{cliente.bucket}').")
        # Exibe resumo parcial instantâneo e primeira linha ao vivo logo na partida
        _exibir_resumo_grafana(
            df_acumulado=df_acumulado,
            trava_filtro=trava_filtro,
            col_tr=col_tr,
            col_v=col_v,
            col_en=col_en,
            col_sp=col_sp,
            col_sem_cfg=col_sem_cfg,
            col_b_in=col_b_in,
            col_b_out=col_b_out,
            lim_rastejo=lim_rastejo,
            lim_b_out=lim_b_out,
            lim_b_in=lim_b_in,
            h_turno=h_turno,
            df_sem_externo=df_sem_externo,
            titulo_base=f"RESUMO PARCIAL INICIAL (LINHA {cliente.measurement})"
        )
        msg_inicial = _montar_linha_status_grafana(
            cliente=cliente,
            df_acumulado=df_acumulado,
            trava_filtro=trava_filtro,
            col_tr=col_tr,
            col_v=col_v,
            col_en=col_en,
            col_sp=col_sp,
            col_sem_cfg=col_sem_cfg,
            col_b_in=col_b_in,
            col_b_out=col_b_out,
            lim_rastejo=lim_rastejo,
            lim_b_out=lim_b_out,
            lim_b_in=lim_b_in,
            h_turno=h_turno,
            df_sem_externo=df_sem_externo,
            soda_ativo=soda_ativo,
            cfg_soda=cfg_soda,
            novas_amostras=len(df_acumulado)
        )
        sys.stdout.write(msg_inicial)
        sys.stdout.flush()

    contador_loop = 0
    try:
        while True:
            time.sleep(intervalo_s)
            contador_loop += 1

            # Busca contínua autossuficiente dos pontos mais recentes gravados no InfluxDB
            df_recente = buscar_dados_grafana_resiliente(
                cliente=cliente,
                measurement=cliente.measurement,
                bucket=cliente.bucket,
                limite=30
            )
            novas_amostras = 0
            if not df_recente.empty:
                df_recente = df_recente.loc[:, ~df_recente.columns.duplicated()]
                tam_antes = len(df_acumulado)
                if df_acumulado.empty:
                    df_acumulado = df_recente.copy()
                else:
                    df_acumulado = df_acumulado.loc[:, ~df_acumulado.columns.duplicated()]
                    df_acumulado = pd.concat([df_acumulado, df_recente], ignore_index=True)

                df_acumulado = _normalizar_df_telemetria(df_acumulado)
                novas_amostras = max(0, len(df_acumulado) - tam_antes)

            if len(df_acumulado) == 0:
                hora_agora = datetime.datetime.now().strftime("%H:%M:%S")
                sys.stdout.write(f"\r[{hora_agora}] ⏳ Aguardando telemetria em '{cliente.measurement}' (verificação #{contador_loop})...")
                sys.stdout.flush()
                continue

            msg_linha = _montar_linha_status_grafana(
                cliente=cliente,
                df_acumulado=df_acumulado,
                trava_filtro=trava_filtro,
                col_tr=col_tr,
                col_v=col_v,
                col_en=col_en,
                col_sp=col_sp,
                col_sem_cfg=col_sem_cfg,
                col_b_in=col_b_in,
                col_b_out=col_b_out,
                lim_rastejo=lim_rastejo,
                lim_b_out=lim_b_out,
                lim_b_in=lim_b_in,
                h_turno=h_turno,
                df_sem_externo=df_sem_externo,
                soda_ativo=soda_ativo,
                cfg_soda=cfg_soda,
                novas_amostras=novas_amostras
            )
            sys.stdout.write(msg_linha)
            sys.stdout.flush()

    except KeyboardInterrupt:
        print("\n\n" + "─" * 70)
        print(" ⏹️ Streaming do Grafana Interrompido. Consolidando relatório da sessão...")
        cliente.desconectar()
        _exibir_resumo_grafana(
            df_acumulado=df_acumulado,
            trava_filtro=trava_filtro,
            col_tr=col_tr,
            col_v=col_v,
            col_en=col_en,
            col_sp=col_sp,
            col_sem_cfg=col_sem_cfg,
            col_b_in=col_b_in,
            col_b_out=col_b_out,
            lim_rastejo=lim_rastejo,
            lim_b_out=lim_b_out,
            lim_b_in=lim_b_in,
            h_turno=h_turno,
            df_sem_externo=df_sem_externo,
            titulo_base=f"RESUMO DA SESSÃO ONLINE GRAFANA (LINHA {measurement})"
        )
    return True


def extrair_campo(fontes_dict, *chaves, padrao=None):
    """Procura uma lista de chaves candidatas em uma ou mais estruturas de dicionário."""
    for d in fontes_dict:
        if not isinstance(d, dict):
            continue
        for k in chaves:
            if k in d and d[k] is not None and str(d[k]).strip() != "":
                return d[k]
    return padrao


def main():
    parser = argparse.ArgumentParser(description="Medidor de Ganho de Linha Industrial")
    parser.add_argument("csv", nargs="?", default=None, help="Arquivo CSV com dados (opcional caso use --online-grafana)")
    parser.add_argument("--config", default=None, help="Arquivo JSON de configuração (não-inline) com dados raw de conexão e query")
    parser.add_argument("--csv-sem-controle", help="Segundo arquivo opcional com dados sem controle")
    parser.add_argument("--trava", type=str, default=None, help="Filtrar por trava de entrada: 0 (fluxo livre), 1 (acionada) ou 'all'")
    parser.add_argument("--online", action="store_true", help="Executar em modo streaming/online monitorando arquivo CSV local")
    parser.add_argument("--intervalo", type=float, default=None, help="Intervalo em segundos para varredura do modo online")

    # Parâmetros de Conexão Direta ao Grafana (idênticos ao obter_dados_grafana.py)
    parser.add_argument("--listar-colunas", "-l", action="store_true", help="Inspeciona e lista todas as colunas disponíveis antes de rodar o cálculo")
    parser.add_argument("--online-grafana", action="store_true", help="Conecta diretamente na API do Grafana/InfluxDB em tempo real sem CSV")
    parser.add_argument("--url", default=None, help="URL base do Grafana")
    parser.add_argument("--user", default=None, help="Usuário do Grafana")
    parser.add_argument("--password", default=None, help="Senha do Grafana")
    parser.add_argument("--token", default=None, help="Service Account Token do Grafana")
    parser.add_argument("--ds", default=None, help="Nome ou ID do Data Source InfluxDB no Grafana")
    parser.add_argument("--bucket", default=None, help="Bucket/Database do InfluxDB")
    parser.add_argument("--measurement", default=None, help="Nome da measurement (tabela/linha) no InfluxDB (ex: 512, 501, 512_v4)")
    parser.add_argument("--org", default=None, help="Organização do InfluxDB")
    parser.add_argument("--janela", default=None, help="Janela de histórico inicial (ex: 2h, 4h, 8h, 24h)")
    args = parser.parse_args()

    # Carregar configuração JSON (não-inline) se disponível
    caminho_config = args.config
    if not caminho_config:
        padrao_local = os.path.join(DIRETORIO_ATUAL, "config_medidor.json")
        if os.path.exists(padrao_local):
            caminho_config = padrao_local

    cfg_dados = {}
    if caminho_config and os.path.exists(caminho_config):
        try:
            with open(caminho_config, "r", encoding="utf-8") as f:
                cfg_dados = json.load(f)
                print(f"📄 Configurações raw carregadas de: {caminho_config}")
        except Exception as e:
            print(f"⚠️ Erro ao ler JSON '{caminho_config}': {e}")

    # Lista abrangente de sub-dicionários onde configurações de conexão podem estar
    fontes_conexao = [
        cfg_dados.get("dados_grafana"),
        cfg_dados.get("config"),
        cfg_dados.get("conexao"),
        cfg_dados.get("telemetria_influx"),
        cfg_dados
    ]
    fontes_proc = [
        cfg_dados.get("dados_calculo_analises"),
        cfg_dados.get("processo"),
        cfg_dados.get("controle"),
        cfg_dados
    ]
    fontes_colunas = [
        cfg_dados.get("colunas_grafana"),
        cfg_dados.get("dados_grafana"),
        cfg_dados.get("maquinas"),
        cfg_dados
    ]

    cfg_soda = cfg_dados.get("dados_soda", {})
    cfg_query_raw = cfg_dados.get("query_raw", {})

    # Resolução resiliente dos parâmetros de conexão (CLI sobrepõe JSON)
    url_json = extrair_campo(fontes_conexao, "url", "grafana_url", "Grafana_URL", "host", "influx_url")
    url = args.url or url_json or "http://10.46.12.163:3000"

    user_json = extrair_campo(fontes_conexao, "user", "grafana_user", "Grafana_User", "usuario", "username")
    user = args.user or user_json or "admin"

    password_json = extrair_campo(fontes_conexao, "password", "grafana_password", "Grafana_Password", "senha")
    password = args.password or password_json or "!ambev2021"

    token_json = extrair_campo(fontes_conexao, "token", "grafana_token", "Grafana_Token")
    token = args.token or token_json or ""

    ds_json = extrair_campo(fontes_conexao, "datasource", "datasource_selector", "Grafana_Datasource", "grafana_datasource", "ds")
    ds_selector = args.ds or (str(ds_json) if ds_json is not None else "17")

    bucket_json = extrair_campo(fontes_conexao, "bucket", "database", "Grafana_Bucket", "grafana_bucket", "db")
    bucket = args.bucket or bucket_json or "Segue"

    org_json = extrair_campo(fontes_conexao, "org", "Grafana_Org", "grafana_org")
    org = args.org or org_json or "ABinbev"

    measurement_json = extrair_campo(fontes_conexao, "measurement", "Grafana_Measurement", "grafana_measurement", "measurement_destino", "measurement_origem", "tabela", "linha")
    measurement = args.measurement or measurement_json or "512_v4"

    trava_filtro = args.trava if args.trava is not None else extrair_campo(fontes_proc, "trava_filtro")
    janela = args.janela or extrair_campo(fontes_proc, "janela_historico", "janela", padrao="4h")

    intervalo_padrao = float(extrair_campo(fontes_proc, "intervalo_varredura_segundos", "intervalo_segundos", "intervalo", padrao=5.0))
    intervalo = args.intervalo if args.intervalo is not None else intervalo_padrao

    col_v = extrair_campo(fontes_colunas, "coluna_velocidade_real", "COL_V_ECH", "tag_velocidade_atual", "col_v", "v_atual_cph", "velocidade_real_cph", padrao="v_atual_cph")
    col_tr = extrair_campo(fontes_colunas, "coluna_trava_entrada", "tag_trava_entrada", "col_trava", "trava_entrada_int", "trava_entrada", padrao="trava_entrada_int")
    col_en = extrair_campo(fontes_colunas, "coluna_segue_habilitado", "tag_segue_habilitado", "col_segue", "segue_habilitado", padrao="segue_habilitado")
    col_b_in = extrair_campo(fontes_colunas, "coluna_buffer_entrada_b2", "Col_Buffer_Entrada", "COL_B2", "b2_pct", padrao="b2_pct")
    col_b_out = extrair_campo(fontes_colunas, "coluna_buffer_saida_b3", "Col_Buffer_Saida", "COL_B3", "b3_pct", padrao="b3_pct")
    col_sp = extrair_campo(fontes_colunas, "coluna_velocidade_v4", "v_setpoint_cph", "velocidade_v4_cph", padrao="v_setpoint_cph")
    col_sem = extrair_campo(fontes_colunas, "coluna_velocidade_sem_controle", "velocidade_maquina_sem_controle_cph", "velocidade_maquina_sem_controle", padrao="velocidade_maquina_sem_controle_cph")

    # Fallback automático para Controle_Velocidade_4/config_colunas.json se parâmetros não estiverem definidos
    caminho_colunas_v4 = os.path.join(os.path.dirname(DIRETORIO_ATUAL), "Controle_Velocidade_4", "config_colunas.json")
    if os.path.exists(caminho_colunas_v4) and not args.url and not url_json:
        try:
            with open(caminho_colunas_v4, "r", encoding="utf-8") as f_v4_col:
                v4_cfg = json.load(f_v4_col)
                if v4_cfg.get("Grafana_URL"):
                    url = v4_cfg["Grafana_URL"]
                if v4_cfg.get("Grafana_Datasource") and not args.ds and ds_json is None:
                    ds_selector = str(v4_cfg["Grafana_Datasource"])
                if v4_cfg.get("Grafana_Bucket") and not args.bucket and bucket_json is None:
                    bucket = v4_cfg["Grafana_Bucket"]
                if v4_cfg.get("Grafana_Measurement") and not args.measurement and measurement_json is None:
                    measurement = v4_cfg["Grafana_Measurement"]
        except Exception:
            pass

    # Herança automática de parametros_controle_v4.json gerados pelo otimizador
    padrao_b3 = 74.37
    padrao_b2 = 30.05
    caminho_v4_params = os.path.join(os.path.dirname(DIRETORIO_ATUAL), "Controle_Velocidade_4", "parametros_controle_v4.json")
    if os.path.exists(caminho_v4_params):
        try:
            with open(caminho_v4_params, "r", encoding="utf-8") as fv4:
                pv4 = json.load(fv4)
                if pv4.get("b3_lim") is not None:
                    padrao_b3 = float(pv4.get("b3_lim"))
                if pv4.get("b2_lim") is not None:
                    padrao_b2 = float(pv4.get("b2_lim"))
        except Exception:
            pass

    lim_rastejo = float(extrair_campo(fontes_proc, "limiar_rastejo_cph", padrao=20000.0))
    lim_b_out = float(extrair_campo(fontes_proc, "limiar_buffer_saida_gargalo_pct", padrao=padrao_b3))
    lim_b_in = float(extrair_campo(fontes_proc, "limiar_buffer_entrada_min_pct", padrao=padrao_b2))
    h_turno = float(extrair_campo(fontes_proc, "horas_turno_projecao", padrao=8.0))

    csv_sem = args.csv_sem_controle or extrair_campo(fontes_proc, "csv_sem_controle")
    query_template = None
    if cfg_query_raw.get("habilitar_query_customizada"):
        query_template = cfg_query_raw.get("sql_influxql")

    cfg_colunas_resolvido = {
        "coluna_velocidade_real": col_v,
        "coluna_trava_entrada": col_tr,
        "coluna_segue_habilitado": col_en,
        "coluna_buffer_entrada_b2": col_b_in,
        "coluna_buffer_saida_b3": col_b_out,
        "coluna_velocidade_v4": col_sp,
        "coluna_velocidade_sem_controle": col_sem
    }
    cfg_analise_resolvido = {
        "limiar_rastejo_cph": lim_rastejo,
        "limiar_buffer_saida_gargalo_pct": lim_b_out,
        "limiar_buffer_entrada_min_pct": lim_b_in,
        "horas_turno_projecao": h_turno
    }

    # Modo de Inspeção Prévia de Colunas (restaura fallback robusto que funciona em qualquer InfluxDB)
    modo_config = cfg_dados.get("modo", "")
    deseja_listar = args.listar_colunas or (modo_config in ["listar-colunas", "inspecionar"])

    if deseja_listar:
        caminho_csv = args.csv or cfg_dados.get("csv_entrada")
        if caminho_csv and os.path.exists(caminho_csv):
            try:
                df_amostra = pd.read_csv(caminho_csv, nrows=5)
                cols = df_amostra.columns.tolist()
                exibir_inspecao_colunas(cols, cfg_colunas=cfg_colunas_resolvido, fonte=f"CSV Local: {caminho_csv}")
                return
            except Exception as e:
                print(f"❌ Erro ao ler colunas do CSV '{caminho_csv}': {e}")
                return

        print(f"➔ Conectando ao Grafana para inspecionar colunas da medição '{measurement}'...")
        try:
            cliente = ClienteGrafana(
                url=url, user=user, password=password, token=token,
                ds_selector=ds_selector, bucket=bucket, measurement=measurement, org=org
            )
        except TypeError:
            cliente = ClienteGrafana(
                url=url, user=user, password=password, token=token,
                ds_selector=ds_selector, bucket=bucket, measurement=measurement, org=org
            )

        if cliente.conectar():
            cols = []
            if hasattr(cliente, "listar_colunas_disponiveis"):
                try:
                    cols = cliente.listar_colunas_disponiveis()
                except Exception:
                    pass

            if not cols:
                # Fallback direto via InfluxQL proxy (idêntico ao script original com suporte a variações)
                colunas_set = set()
                proxy_url = f"{cliente.url}/api/datasources/proxy/{cliente.ds_id}/query"
                headers_sql = dict(getattr(cliente, "headers", {}))
                headers_sql["Content-Type"] = "application/x-www-form-urlencoded"
                headers_sql["Accept"] = "application/json"
                timeout_q = getattr(cliente, "timeout", 15)

                meds_tentar = [measurement]
                if measurement.endswith("_v4"):
                    meds_tentar.append(measurement[:-3])
                else:
                    meds_tentar.append(f"{measurement}_v4")

                for m_test in meds_tentar:
                    for q_try in [
                        f'SHOW FIELD KEYS FROM "{m_test}"',
                        f'SHOW TAG KEYS FROM "{m_test}"',
                        f'SELECT * FROM "{m_test}" LIMIT 1',
                        f'SELECT * FROM "{m_test}" ORDER BY time DESC LIMIT 1',
                        f'SELECT * FROM "{m_test}" WHERE time >= now() - 24h LIMIT 1'
                    ]:
                        try:
                            res_q = cliente.session.post(proxy_url, headers=headers_sql, data={"db": bucket, "q": q_try}, timeout=timeout_q)
                            if res_q.status_code == 200:
                                results = res_q.json().get("results", [])
                                if results and "series" in results[0]:
                                    s_item = results[0]["series"][0]
                                    if "columns" in s_item:
                                        for c_name in s_item["columns"]:
                                            if c_name.lower() != "time":
                                                colunas_set.add(c_name)
                                    if "values" in s_item:
                                        for v_row in s_item["values"]:
                                            if v_row and v_row[0] and str(v_row[0]).lower() != "time":
                                                colunas_set.add(str(v_row[0]))
                        except Exception:
                            pass
                    if colunas_set:
                        measurement = m_test
                        break

                if colunas_set:
                    cols = sorted(list(colunas_set))
                else:
                    try:
                        df_recente = cliente.buscar_dados(tempo_inicio_str="-24h")
                        if not df_recente.empty:
                            cols = [c for c in df_recente.columns if c.lower() != "time"]
                    except Exception:
                        pass

            exibir_inspecao_colunas(cols, cfg_colunas=cfg_colunas_resolvido, fonte=f"Grafana/InfluxDB: '{measurement}'")
        else:
            print("❌ Não foi possível conectar ao Grafana para listar as colunas.")
        return

    # Determinar modo de operação (auto-detecta online-grafana se houver URL no JSON e nenhum CSV fornecido)
    tem_url_config = bool(url_json or ("Grafana_URL" in cfg_dados) or ("grafana_url" in cfg_dados))
    usar_online_grafana = args.online_grafana or (modo_config == "online-grafana" and not args.online and not args.csv) or (tem_url_config and not args.csv and not args.online)

    # Modo 1: Streaming Direto da API do Grafana
    caminho_csv = args.csv or cfg_dados.get("csv_entrada")
    if usar_online_grafana:
        ok_grafana = executar_modo_online_grafana(
            url=url, user=user, password=password, token=token,
            ds_selector=ds_selector, bucket=bucket, measurement=measurement, org=org,
            trava_filtro=trava_filtro, intervalo_s=intervalo,
            janela_historico=janela, caminho_sem=csv_sem,
            query_template=query_template,
            cfg_colunas=cfg_colunas_resolvido,
            cfg_analise=cfg_analise_resolvido,
            cfg_soda=cfg_soda
        )
        if ok_grafana:
            return

        # Fallback para CSV local caso esteja fora da rede da fábrica
        if not args.online_grafana:
            import glob
            csv_candidatos = sorted(glob.glob("Panel Title-data-*.csv"), key=os.path.getmtime, reverse=True)
            csv_fallback = caminho_csv or (csv_candidatos[0] if csv_candidatos else None)
            if csv_fallback and os.path.exists(csv_fallback):
                print(f"\n💡 [Modo Contingência / Fora da VPN] Carregando CSV mais recente da fábrica: '{csv_fallback}'...")
                caminho_csv = csv_fallback
            else:
                return
        else:
            return

    # Modo 2: Modo Online Streaming de Arquivo CSV Local
    if args.online:
        caminho_csv = args.csv or cfg_dados.get("csv_entrada")
        if not caminho_csv:
            print("❌ Erro: Forneça o caminho do arquivo CSV para monitoramento online (ex: python medir_ganho.py dados.csv --online)")
            return
        executar_modo_online(caminho_csv, trava_filtro=trava_filtro, intervalo_s=intervalo if args.intervalo is not None else 2.0, caminho_sem=csv_sem)
        return

    # Modo 3: Modo Estático / Batch
    if not caminho_csv:
        caminho_csv = args.csv or cfg_dados.get("csv_entrada")
    if not caminho_csv:
        print("❌ Erro: Forneça um arquivo CSV ou utilize a opção '--online-grafana' para monitorar direto da rede.")
        print("   Exemplos:")
        print("   1) Direto do Grafana (JSON):  .venv/bin/python medidor_ganho_controle/medir_ganho.py --online-grafana")
        print("   2) Custom Config JSON:        .venv/bin/python medidor_ganho_controle/medir_ganho.py --config config_medidor.json")
        print("   3) Arquivo CSV:               .venv/bin/python medidor_ganho_controle/medir_ganho.py 'dados.csv' --trava 0")
        return

    df_principal = carregar_dados(caminho_csv)
    if df_principal is None:
        return

    # Aplicar filtro de trava se especificado
    col_t = cfg_colunas_resolvido.get("coluna_trava_entrada")
    if not col_t or col_t not in df_principal.columns:
        col_t = obter_coluna_trava(df_principal)
    df_analise = filtrar_trava(df_principal, trava_filtro, col_t) if trava_filtro is not None else df_principal

    # Caso 1: Dois arquivos passados
    if args.csv_sem_controle:
        df_sem_raw = carregar_dados(args.csv_sem_controle)
        if df_sem_raw is None:
            return
        df_sem_raw = filtrar_trava(df_sem_raw, trava_filtro, col_t) if trava_filtro is not None else df_sem_raw
        _, df_sem = filtrar_on_off(df_sem_raw, col_en=col_en)
        if df_sem is None or len(df_sem) == 0:
            df_sem = df_sem_raw

        df_com, _ = filtrar_on_off(df_analise, col_en=col_en)
        if df_com is None or len(df_com) == 0:
            df_com = df_analise

        titulo = "RESUMO EXECUTIVO: GANHO REAL DO CONTROLE"
        if trava_filtro is not None:
            titulo += f" (TRAVA == {trava_filtro})"
        m = calcular_metricas(
            df_com, df_sem,
            col_velocidade=col_v, col_b_in=col_b_in, col_b_out=col_b_out,
            limiar_rastejo=lim_rastejo, limiar_b_out_gargalo=lim_b_out,
            limiar_b_in_min=lim_b_in, horas_turno=h_turno
        )
        if m:
            exibir_relatorio(m, titulo=titulo)
        return

    # Caso 2: Um arquivo contendo ON e OFF
    df_com, df_sem = filtrar_on_off(df_analise, col_en=col_en)
    if df_com is not None and df_sem is not None and len(df_com) > 0 and len(df_sem) > 0:
        titulo = "RESUMO EXECUTIVO: GANHO REAL DO CONTROLE"
        if trava_filtro is not None:
            titulo += f" (ISOLADO SOB TRAVA ENTRADA == {trava_filtro})"
        m = calcular_metricas(
            df_com, df_sem,
            col_velocidade=col_v, col_b_in=col_b_in, col_b_out=col_b_out,
            limiar_rastejo=lim_rastejo, limiar_b_out_gargalo=lim_b_out,
            limiar_b_in_min=lim_b_in, horas_turno=h_turno
        )
        if m:
            exibir_relatorio(m, titulo=titulo)

        if trava_filtro is None and col_t is not None:
            df_com_t0 = filtrar_trava(df_com, 0, col_t)
            df_sem_t0 = filtrar_trava(df_sem, 0, col_t)
            if len(df_com_t0) > 0 and len(df_sem_t0) > 0:
                m_t0 = calcular_metricas(
                    df_com_t0, df_sem_t0,
                    col_velocidade=col_v, col_b_in=col_b_in, col_b_out=col_b_out,
                    limiar_rastejo=lim_rastejo, limiar_b_out_gargalo=lim_b_out,
                    limiar_b_in_min=lim_b_in, horas_turno=h_turno
                )
                if m_t0:
                    exibir_relatorio(m_t0, titulo="AUDITORIA TÉCNICA: ISOLADO SOB FLUXO LIVRE (TRAVA ENTRADA == 0)")
        return

    # Caso 3: Arquivo contendo dados apenas de um modo (100% ON ou 100% OFF)
    if len(df_analise) > 0:
        col_v_real = col_v if (col_v and col_v in df_analise.columns) else obter_coluna_velocidade(df_analise)
        col_en_real = col_en if (col_en and col_en in df_analise.columns) else obter_coluna_habilitado(df_analise)
        val_en = df_analise.iloc[-1].get(col_en_real, False)
        segue_on = _interpretar_bool(val_en)
        m_unico = calcular_metricas_contrafactual_ou_sombra(
            df_analise,
            col_v=col_v_real,
            col_sp=col_sp,
            col_sem=col_sem,
            horas_turno=h_turno,
            limiar_rastejo=lim_rastejo
        )
        if m_unico:
            tit = "RESUMO EXECUTIVO: BALANÇO DE PRODUÇÃO"
            if trava_filtro is not None:
                tit += f" (TRAVA == {trava_filtro})"
            exibir_relatorio_modo_unico(m_unico, segue_on=segue_on, titulo=tit)
            return

    print("⚠️ Este arquivo possui dados apenas de um modo de operação no filtro aplicado.")
    print(f'   Execute: .venv/bin/python medidor_ganho_controle/medir_ganho.py "{args.csv}" --csv-sem-controle "dados_sem_controle.csv"')


if __name__ == "__main__":
    main()
