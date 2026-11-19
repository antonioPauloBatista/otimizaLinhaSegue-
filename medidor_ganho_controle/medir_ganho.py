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


def _obter_fuso_local():
    """Retorna o fuso horário local do sistema operacional."""
    return datetime.datetime.now().astimezone().tzinfo


def _trava_eh_restritiva(trava_filtro):
    """Indica se o filtro de trava restringe amostras (diferente de None/'all'/'todas')."""
    if trava_filtro is None:
        return False
    return str(trava_filtro).strip().lower() not in ["", "none", "all", "todas"]


def _descrever_filtro_trava(trava_filtro, maiusculo=False):
    """Retorna descrição legível do filtro de trava de entrada (1 = Aberta, 0 = Fechada)."""
    val = str(trava_filtro).strip().lower() if trava_filtro is not None else ""
    if val in ["", "none", "all", "todas"]:
        desc = "Todas as condições (Aberta + Fechada)"
        return desc.upper() if maiusculo else desc
    if val == "1":
        return "TRAVA == 1 (TRAVA ABERTA / FLUXO LIVRE)" if maiusculo else "Trava Aberta / Fluxo Livre (Trava == 1)"
    if val == "0":
        return "TRAVA == 0 (TRAVA FECHADA / BLOQUEADA)" if maiusculo else "Trava Fechada / Bloqueada (Trava == 0)"
    return f"TRAVA == {trava_filtro}" if maiusculo else f"Trava Entrada == {trava_filtro}"


def _formatar_tag_trava_curta(trava_val):
    """Formata o estado instantâneo da trava indicando Aberta (1) ou Fechada (0)."""
    if isinstance(trava_val, bool):
        return "🔓 T:1(Aberta)" if trava_val else "🔒 T:0(Fechada)"
    if trava_val is None or pd.isna(trava_val):
        return "T:N/A"
    s = str(trava_val).strip().lower()
    if s in ["1", "1.0", "true", "aberta", "livre"]:
        return "🔓 T:1(Aberta)"
    if s in ["0", "0.0", "false", "fechada", "bloqueada"]:
        return "🔒 T:0(Fechada)"
    return f"T:{trava_val}"


def _converter_serie_tempo_local(serie):
    """Converte timestamps (UTC ISO, epoch ou naive local) para datetime naive no horário local."""
    if serie is None or len(serie) == 0:
        return pd.Series(dtype="datetime64[ns]", index=getattr(serie, "index", None))

    tz_local = _obter_fuso_local()
    if pd.api.types.is_datetime64_any_dtype(serie):
        if getattr(serie.dt, "tz", None) is not None:
            return serie.dt.tz_convert(tz_local).dt.tz_localize(None)
        return serie

    if pd.api.types.is_numeric_dtype(serie):
        vals_num = pd.to_numeric(serie, errors="coerce")
        med = vals_num.dropna().median()
        if pd.isna(med):
            return pd.Series(pd.NaT, index=serie.index)
        unidade = "ms" if med > 1e11 else "s"
        dt = pd.to_datetime(vals_num, unit=unidade, utc=True, errors="coerce")
        return dt.dt.tz_convert(tz_local).dt.tz_localize(None)

    s_str = serie.dropna().astype(str).str.strip()
    s_str = s_str[s_str != ""]
    if len(s_str) == 0:
        return pd.Series(pd.NaT, index=serie.index)

    has_tz = s_str.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", case=False, regex=True).any()
    try:
        dt = pd.to_datetime(serie, format="mixed", errors="coerce", utc=has_tz)
        if has_tz:
            return dt.dt.tz_convert(tz_local).dt.tz_localize(None)
        return dt
    except Exception:
        return pd.Series(pd.NaT, index=serie.index)


def _obter_serie_tempo_local(df, col_t=None):
    """Localiza a coluna temporal do DataFrame e retorna a série convertida para o fuso local."""
    if df is None or df.empty:
        return pd.Series(dtype="datetime64[ns]")
    candidatas = [col_t] if col_t else ["Time", "Timestamp", "time", "_time"]
    for col in candidatas:
        if col and col in df.columns:
            return _converter_serie_tempo_local(df[col])
    return pd.Series(dtype="datetime64[ns]", index=df.index)


def _obter_ts_max(df):
    """Retorna o timestamp máximo local de um DataFrame ou None se indisponível."""
    ts = _obter_serie_tempo_local(df)
    if ts is None or len(ts) == 0 or not ts.notna().any():
        return None
    return ts.max()


def _formatar_ts_local(val):
    """Formata um timestamp único para HH:MM:SS no horário local."""
    try:
        if val is not None and not pd.isna(val):
            ts_conv = _converter_serie_tempo_local(pd.Series([val])).iloc[0]
            if pd.notnull(ts_conv):
                return ts_conv.strftime("%H:%M:%S")
    except Exception:
        pass
    return datetime.datetime.now().strftime("%H:%M:%S")


def _estimar_cadencia_segundos(df, padrao=10.0):
    """Estima a cadência base (intervalo modal entre amostras consecutivas) em segundos."""
    ts = _obter_serie_tempo_local(df)
    if ts is None or len(ts) < 2:
        return padrao
    ts_valid = ts.dropna()
    if len(ts_valid) < 2:
        return padrao
    dt_s = ts_valid.diff().dt.total_seconds()
    dt_pos = dt_s[dt_s > 0]
    if len(dt_pos) == 0:
        return padrao
    modos = dt_pos.round(1).mode()
    if len(modos) > 0 and modos.iloc[0] > 0:
        # Quando ha poucas amostras com lacuna (ex: 10s e 1172s), preferir o menor intervalo regular
        if len(dt_pos) < 3 and dt_pos.min() <= 60.0:
            return float(dt_pos.min())
        return float(modos.iloc[0])
    med = float(dt_pos.median())
    return med if med > 0 else padrao


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
        ts_ord = _obter_serie_tempo_local(df, col_t=col_t)
        if ts_ord is not None and ts_ord.notna().any():
            df = df.assign(_ts_ord=ts_ord)
            df = df.drop_duplicates(subset=["_ts_ord"], keep="last").sort_values("_ts_ord")
            df = df.drop(columns=["_ts_ord"]).reset_index(drop=True)
        else:
            df = df.drop_duplicates(subset=[col_t], keep="last").sort_values(col_t).reset_index(drop=True)
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
                dt_vals = pd.to_datetime(vals, unit="ms" if eh_ms else None, utc=True, errors="coerce")
                dados["Time"] = pd.Series(dt_vals.strftime("%Y-%m-%dT%H:%M:%SZ"), index=range(len(vals))).fillna("")
            else:
                dados[nome] = vals
        if dados:
            dfs.append(pd.DataFrame(dados))

    if not dfs:
        return pd.DataFrame()
    df_res = dfs[0] if len(dfs) == 1 else pd.concat(dfs, ignore_index=True)
    return _normalizar_df_telemetria(df_res)


def _parsear_horas_janela(janela_str):
    """Converte strings como '-24h', '48h', '2d', '90m' para total de horas (float) ou None."""
    if not janela_str:
        return None
    txt = str(janela_str).strip().lower()
    if txt.startswith("now"):
        txt = txt[3:].strip().lstrip("()").strip()
    txt = txt.lstrip("-").strip()
    try:
        if txt.endswith("h"):
            val = float(txt[:-1].strip())
            return val if val > 0 else None
        if txt.endswith("d"):
            val = float(txt[:-1].strip()) * 24.0
            return val if val > 0 else None
        if txt.endswith("m"):
            val = float(txt[:-1].strip()) / 60.0
            return val if val > 0 else None
        if txt.endswith("s"):
            val = float(txt[:-1].strip()) / 3600.0
            return val if val > 0 else None
    except ValueError:
        return None
    return None


def _formatar_offset_horas(h):
    """Formata um deslocamento em horas para sintaxe InfluxQL ('24h', '90m', etc.)."""
    if abs(h - round(h)) < 1e-6:
        return f"{int(round(h))}h"
    minutos = max(1, int(round(h * 60.0)))
    return f"{minutos}m"


def _gerar_blocos_horarios(total_horas, passo_horas=1.0):
    """Divide total_horas em fatias [(h_ini, h_fim), ...] de passo_horas, da mais antiga à mais recente."""
    if total_horas is None or total_horas <= 0:
        return []
    passo = float(passo_horas) if (passo_horas is not None and passo_horas > 0) else 1.0
    blocos = []
    cur = float(total_horas)
    while cur > 1e-6:
        nxt = max(0.0, round(cur - passo, 6))
        blocos.append((round(cur, 6), nxt))
        cur = nxt
    return blocos


def _calcular_limite_janela(janela_str, minimo=10000):
    """Calcula limite seguro de amostras para cobrir a janela histórica solicitada."""
    horas = _parsear_horas_janela(janela_str)
    if horas is not None:
        return max(minimo, int(horas * 360) + 500)
    return minimo


def buscar_dados_grafana_resiliente(
    cliente,
    measurement,
    bucket,
    limite=10000,
    tempo_inicio_str=None,
    query_template=None,
    passo_horas=1.0,
    pausa_bloco_s=0.05,
    mostrar_progresso=True
):
    """
    Consulta dados no Grafana/InfluxDB de forma autossuficiente e resiliente:
    - Não depende de métodos novos em cliente_grafana.py no Windows.
    - Deduplica colunas repetidas (tag+field 'trava_entrada').
    - Para janelas longas (ex: 24h, 48h+), busca de hora em hora para não sobrecarregar Grafana/InfluxDB.
    - Testa POST e GET no proxy InfluxQL, proxy por UID e /api/ds/query.
    - Faz fallback paginado por LIMIT/OFFSET (imune a skew de fuso horário/now()).
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

    ds_from = "now-24h"
    if tempo_inicio_str:
        t_raw = str(tempo_inicio_str).strip()
        if t_raw.startswith("-"):
            ds_from = f"now{t_raw}"
        elif t_raw.startswith("now"):
            ds_from = t_raw.replace("()", "").replace(" ", "")

    meds_candidatas = [measurement]
    alt_med = measurement[:-3] if measurement.endswith("_v4") else f"{measurement}_v4"
    if alt_med not in meds_candidatas:
        meds_candidatas.append(alt_med)

    buckets_candidatos = [bucket]
    for b_alt in ["soda", "Segue"]:
        if b_alt and b_alt not in buckets_candidatos:
            buckets_candidatos.append(b_alt)

    def _resposta_influxql_vazia_sem_erro(res_json):
        results = res_json.get("results") if isinstance(res_json, dict) else None
        if not results:
            return False
        return not any(isinstance(r, dict) and r.get("error") for r in results)

    def _rodar_sql(sql_str, db_alvo, ds_from_override=None, ds_to_override=None):
        params = {"db": db_alvo, "q": sql_str}
        # 1. Proxy InfluxQL via POST e GET
        for metodo in ("post", "get"):
            try:
                if metodo == "post":
                    res = sessao.post(proxy_url, headers=headers_post, data=params, timeout=timeout_q)
                else:
                    res = sessao.get(proxy_url, headers=headers, params=params, timeout=timeout_q)
                if res.status_code == 200:
                    payload_json = res.json()
                    df_ok = _parsear_influxql_resiliente(payload_json)
                    if not df_ok.empty:
                        return df_ok
                    if _resposta_influxql_vazia_sem_erro(payload_json):
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
                        payload_json = res.json()
                        df_ok = _parsear_influxql_resiliente(payload_json)
                        if not df_ok.empty:
                            return df_ok
                        if _resposta_influxql_vazia_sem_erro(payload_json):
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
                "from": ds_from_override or ds_from,
                "to": ds_to_override or "now",
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

    def _descobrir_par_ativo():
        for b_cand in buckets_candidatos:
            for med in meds_candidatas:
                df_probe = _rodar_sql(f'SELECT * FROM "{med}" ORDER BY time DESC LIMIT 1', b_cand)
                if not df_probe.empty:
                    cliente.bucket = b_cand
                    cliente.measurement = med
                    return b_cand, med
        return None, None

    def _montar_sql_bloco(med, cond_tempo, t_ini_expr, t_fim_expr):
        if query_template:
            return (
                query_template
                .replace("$timeFilter", cond_tempo)
                .replace("{tempo_inicio}", t_ini_expr)
                .replace("{tempo_fim}", t_fim_expr)
            )
        return f'SELECT * FROM "{med}" WHERE {cond_tempo} ORDER BY time ASC'

    # Fase 1: Tentativa por janela relativa (fatiando de hora em hora quando > passo_horas)
    if tempo_inicio_str:
        horas_totais = _parsear_horas_janela(tempo_inicio_str)
        if horas_totais is not None and passo_horas and horas_totais > float(passo_horas):
            b_ativo, med_ativa = _descobrir_par_ativo()
            if b_ativo is None and query_template:
                b_ativo, med_ativa = buckets_candidatos[0], meds_candidatas[0]

            if b_ativo is not None and med_ativa is not None:
                blocos = _gerar_blocos_horarios(horas_totais, passo_horas=passo_horas)
                dfs_blocos = []
                total_am = 0
                imprimiu_progresso = False
                for idx, (h_ini, h_fim) in enumerate(blocos, 1):
                    str_ini = _formatar_offset_horas(h_ini)
                    t_ini_expr = f"now() - {str_ini}"
                    ds_from_bloco = f"now-{str_ini}"
                    if h_fim > 0:
                        str_fim = _formatar_offset_horas(h_fim)
                        t_fim_expr = f"now() - {str_fim}"
                        cond_tempo = f"time >= {t_ini_expr} AND time < {t_fim_expr}"
                        ds_to_bloco = f"now-{str_fim}"
                    else:
                        t_fim_expr = "now()"
                        cond_tempo = f"time >= {t_ini_expr}"
                        ds_to_bloco = "now"

                    sql_bloco = _montar_sql_bloco(med_ativa, cond_tempo, t_ini_expr, t_fim_expr)
                    df_bloco = _rodar_sql(
                        sql_bloco,
                        b_ativo,
                        ds_from_override=ds_from_bloco,
                        ds_to_override=ds_to_bloco,
                    )
                    if not df_bloco.empty:
                        dfs_blocos.append(df_bloco)
                        total_am += len(df_bloco)

                    if mostrar_progresso:
                        sys.stdout.write(
                            f"\r   ⏳ Buscando histórico de 1 em 1 hora: [{idx}/{len(blocos)}h] ({total_am} amostras carregadas)...\033[K"
                        )
                        sys.stdout.flush()
                        imprimiu_progresso = True

                    if pausa_bloco_s and pausa_bloco_s > 0 and idx < len(blocos):
                        time.sleep(pausa_bloco_s)

                if imprimiu_progresso:
                    sys.stdout.write("\r\033[K")
                    sys.stdout.flush()

                if dfs_blocos:
                    df_unido = dfs_blocos[0] if len(dfs_blocos) == 1 else pd.concat(dfs_blocos, ignore_index=True)
                    return _normalizar_df_telemetria(df_unido)
        else:
            t_inicio = str(tempo_inicio_str).strip()
            if t_inicio.startswith("-"):
                t_inicio = f"now() - {t_inicio[1:]}"
            for b_cand in buckets_candidatos:
                for med in meds_candidatas:
                    sql_q = _montar_sql_bloco(med, f"time >= {t_inicio}", t_inicio, "now()")
                    df_ret = _rodar_sql(sql_q, b_cand)
                    if not df_ret.empty:
                        cliente.bucket = b_cand
                        cliente.measurement = med
                        return df_ret

    # Fase 2: Busca direta dos pontos mais recentes (paginada se limite > 500; imune a fuso UTC vs local)
    limite_total = int(limite)
    if limite_total <= 500:
        for b_cand in buckets_candidatos:
            for med in meds_candidatas:
                sql_rec = f'SELECT * FROM "{med}" ORDER BY time DESC LIMIT {limite_total}'
                df_ret = _rodar_sql(sql_rec, b_cand)
                if not df_ret.empty:
                    cliente.bucket = b_cand
                    cliente.measurement = med
                    return df_ret
        return pd.DataFrame()

    b_ativo, med_ativa = _descobrir_par_ativo()
    if b_ativo is not None and med_ativa is not None:
        tam_pag = 400
        dfs_pags = []
        offset = 0
        total_pag = 0
        imprimiu_pag = False
        total_pags_est = max(1, (limite_total + tam_pag - 1) // tam_pag)
        pag_num = 0
        while offset < limite_total:
            pag_num += 1
            qtd_lote = min(tam_pag, limite_total - offset)
            if offset == 0:
                sql_pag = f'SELECT * FROM "{med_ativa}" ORDER BY time DESC LIMIT {qtd_lote}'
            else:
                sql_pag = f'SELECT * FROM "{med_ativa}" ORDER BY time DESC LIMIT {qtd_lote} OFFSET {offset}'
            df_pag = _rodar_sql(sql_pag, b_ativo)
            if df_pag.empty:
                break
            dfs_pags.append(df_pag)
            total_pag += len(df_pag)
            if mostrar_progresso:
                sys.stdout.write(
                    f"\r   ⏳ Carregando histórico em lotes: [{pag_num}/{total_pags_est}] ({total_pag} amostras)...\033[K"
                )
                sys.stdout.flush()
                imprimiu_pag = True
            if len(df_pag) < qtd_lote:
                break
            offset += len(df_pag)
            if pausa_bloco_s and pausa_bloco_s > 0 and offset < limite_total:
                time.sleep(pausa_bloco_s)

        if imprimiu_pag:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

        if dfs_pags:
            df_unido = dfs_pags[0] if len(dfs_pags) == 1 else pd.concat(dfs_pags, ignore_index=True)
            return _normalizar_df_telemetria(df_unido)

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


def obter_duracao_horas(df, dt_padrao_s=None):
    """Calcula a duração real em horas usando a cadência fixa informada ou estimada."""
    if df is None or len(df) == 0:
        return 0.0
    if dt_padrao_s is not None and dt_padrao_s > 0:
        return len(df) * (float(dt_padrao_s) / 3600.0)
    dt_est = _estimar_cadencia_segundos(df, padrao=10.0)
    return len(df) * (dt_est / 3600.0)


def calcular_metricas(
    df_com,
    df_sem,
    col_velocidade=None,
    col_b_in=None,
    col_b_out=None,
    limiar_rastejo=20000.0,
    limiar_b_out_gargalo=70.0,
    limiar_b_in_min=30.0,
    horas_turno=8.0,
    dt_padrao_s=None,
    limiar_parada=1000.0
):
    """Calcula todas as métricas de ganho físico e redução de paradas/rastejos."""
    col_v = col_velocidade if (col_velocidade and col_velocidade in df_com.columns) else obter_coluna_velocidade(df_com)
    if col_v not in df_sem.columns:
        col_v = col_velocidade if (col_velocidade and col_velocidade in df_sem.columns) else obter_coluna_velocidade(df_sem)

    if not col_b_out or col_b_out not in df_com.columns:
        col_b_out = "b3_pct" if "b3_pct" in df_com.columns else "accumulation_percentage_ech_to_pz_null"
    if not col_b_in or col_b_in not in df_com.columns:
        col_b_in = "b2_pct" if "b2_pct" in df_com.columns else "accumulation_percentage_uip_to_ech_null"

    dt_sem = dt_padrao_s if (dt_padrao_s is not None and dt_padrao_s > 0) else _estimar_cadencia_segundos(df_sem, padrao=10.0)
    dt_com = dt_padrao_s if (dt_padrao_s is not None and dt_padrao_s > 0) else _estimar_cadencia_segundos(df_com, padrao=10.0)
    t_sem_h = obter_duracao_horas(df_sem, dt_padrao_s=dt_sem)
    t_com_h = obter_duracao_horas(df_com, dt_padrao_s=dt_com)

    if t_sem_h <= 0 or t_com_h <= 0 or len(df_com) == 0 or len(df_sem) == 0:
        return None

    # 1. Ritmo de Produção e Ganho (calculados sobre amostras com máquina rodando > limiar_parada)
    df_sem_ativo = df_sem[df_sem[col_v] > limiar_parada]
    df_com_ativo = df_com[df_com[col_v] > limiar_parada]

    taxa_sem = _safe_float(df_sem_ativo[col_v].mean(), 0.0) if len(df_sem_ativo) > 0 else _safe_float(df_sem[col_v].mean(), 0.0)
    taxa_com = _safe_float(df_com_ativo[col_v].mean(), 0.0) if len(df_com_ativo) > 0 else _safe_float(df_com[col_v].mean(), 0.0)

    dt_amostra_h = (t_com_h / len(df_com)) if len(df_com) > 0 else (dt_com / 3600.0)
    deltas_com = (df_com[col_v] - taxa_sem).where(df_com[col_v] > limiar_parada, 0.0)
    total_ganho_gf = float((deltas_com * dt_amostra_h).sum())
    ganho_cph = (taxa_com - taxa_sem) if len(df_com_ativo) > 0 else 0.0
    ganho_pct = (ganho_cph / taxa_sem) * 100.0 if taxa_sem > 0 else 0.0
    ganho_turno_calc = ganho_cph * horas_turno

    # 2. Resgate de Paradas e Rastejos (< limiar_rastejo CPH)
    micro_sem_pct = (df_sem[col_v] < limiar_rastejo).mean() * 100.0
    micro_com_pct = (df_com[col_v] < limiar_rastejo).mean() * 100.0
    pct_salvo_rastejo = max(0.0, (micro_sem_pct - micro_com_pct) / 100.0)
    minutos_salvos = pct_salvo_rastejo * t_com_h * 60.0

    min_rastejo_sem_h = (micro_sem_pct / 100.0) * 60.0
    min_rastejo_com_h = (micro_com_pct / 100.0) * 60.0
    reducao_rastejo_pct = ((min_rastejo_sem_h - min_rastejo_com_h) / min_rastejo_sem_h * 100.0) if min_rastejo_sem_h > 0 else 0.0

    # 3. Paradas Totais (v <= limiar_parada)
    paradas_zero_sem = int((df_sem[col_v] <= limiar_parada).sum())
    paradas_zero_com = int((df_com[col_v] <= limiar_parada).sum())
    min_parada_sem = paradas_zero_sem * (dt_sem / 60.0)
    min_parada_com = paradas_zero_com * (dt_com / 60.0)

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
        "limiar_parada": limiar_parada,
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


def calcular_metricas_contrafactual_ou_sombra(df, col_v, col_sp=None, col_sem=None, horas_turno=8.0, limiar_rastejo=20000.0, dt_padrao_s=None, limiar_parada=1000.0):
    """Calcula métricas quando há apenas um período (ex: 100% OFF ou 100% ON)."""
    dt_ciclo = dt_padrao_s if (dt_padrao_s is not None and dt_padrao_s > 0) else _estimar_cadencia_segundos(df, padrao=10.0)
    dur_h = obter_duracao_horas(df, dt_padrao_s=dt_ciclo)

    paradas_zero = int((df[col_v] <= limiar_parada).sum()) if col_v in df.columns else 0
    min_parada = paradas_zero * (dt_ciclo / 60.0)
    micro_pct = (df[col_v] < limiar_rastejo).mean() * 100.0 if col_v in df.columns else 0.0
    min_rastejo_h = (micro_pct / 100.0) * 60.0

    ativo_mask = (df[col_v] > limiar_parada) if col_v in df.columns else pd.Series(False, index=df.index)
    tem_ativo = bool(col_v in df.columns and ativo_mask.any())
    v_med = _safe_float(df.loc[ativo_mask, col_v].mean(), 0.0) if tem_ativo else (_safe_float(df[col_v].mean(), 0.0) if col_v in df.columns else 0.0)

    # Compara V_SP vs V_Real (se houver setpoint V4), zerando paradas físicas (<= limiar_parada CPH)
    if col_sp and col_sp in df.columns:
        sp_med = _safe_float(df.loc[ativo_mask, col_sp].mean(), 0.0) if tem_ativo else _safe_float(df[col_sp].mean(), 0.0)
        deltas = (df[col_sp] - df[col_v]).where(ativo_mask, 0.0)
        tot_gf = float(_safe_float(deltas.mean(), 0.0) * dur_h) if len(df) > 0 else 0.0
        delta_m = _safe_float(deltas[ativo_mask].mean(), 0.0) if tem_ativo else 0.0
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
            "limiar_parada": limiar_parada,
            "tipo": "SP_VS_REAL"
        }

    # Compara V_Real vs V_Sem (se houver baseline sem controle), zerando paradas físicas (<= limiar_parada CPH)
    if col_sem and col_sem in df.columns:
        sem_med = _safe_float(df.loc[ativo_mask, col_sem].mean(), 0.0) if tem_ativo else _safe_float(df[col_sem].mean(), 0.0)
        deltas = (df[col_v] - df[col_sem]).where(ativo_mask, 0.0)
        tot_gf = float(_safe_float(deltas.mean(), 0.0) * dur_h) if len(df) > 0 else 0.0
        delta_m = _safe_float(deltas[ativo_mask].mean(), 0.0) if tem_ativo else 0.0
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
            "limiar_parada": limiar_parada,
            "tipo": "REAL_VS_SEM"
        }

    return None


def _recortar_pos_ligado(df, col_en=None):
    """Retorna a sequência contínua mais recente com Segue LIGADO até o último registro."""
    if df is None or df.empty:
        return pd.DataFrame()
    en_col = col_en if (col_en and col_en in df.columns) else obter_coluna_habilitado(df)
    if en_col not in df.columns:
        return df.iloc[0:0].copy()
    serie_en = df[en_col]
    if isinstance(serie_en, pd.DataFrame):
        serie_en = serie_en.iloc[:, 0]
    is_on = serie_en.map(_interpretar_bool).tolist()
    if not is_on or not is_on[-1]:
        return df.iloc[0:0].copy()
    pos_inicio = 0
    for idx in range(len(is_on) - 1, -1, -1):
        if not is_on[idx]:
            pos_inicio = idx + 1
            break
    return df.iloc[pos_inicio:].copy()


def _recortar_janelas_temporais(df, ts_referencia=None, ts_inicio_sessao=None, col_en=None, df_geral=None):
    """Recorta o DataFrame em Últimas 24h, Hora Atual, Daqui pra Frente e Pós-Ligado."""
    df_vazio = df.iloc[0:0].copy() if df is not None else pd.DataFrame()
    if df is None or df.empty:
        return {
            "df_24h": pd.DataFrame(),
            "df_hora_atual": pd.DataFrame(),
            "df_daqui_pra_frente": pd.DataFrame(),
            "df_pos_ligado": pd.DataFrame(),
            "df_acumulado": pd.DataFrame(),
            "rotulo_hora": "Hora Atual",
            "intervalo_hora": "",
            "hora_ligada": "",
            "intervalo_ligado": "",
            "ts_max": None,
        }

    ts = _obter_serie_tempo_local(df)
    hora_ligada = ""
    intervalo_ligado = ""
    df_pos_ligado = df_vazio

    df_origem_ligado = df_geral if (df_geral is not None and not df_geral.empty) else None
    if df_origem_ligado is not None:
        df_pos_geral = _recortar_pos_ligado(df_origem_ligado, col_en=col_en)
        if not df_pos_geral.empty:
            ts_lig_geral = _obter_serie_tempo_local(df_pos_geral).dropna()
            if len(ts_lig_geral) > 0:
                ts_ini_lig = ts_lig_geral.min()
                ts_fim_lig = ts_lig_geral.max()
                hora_ligada = ts_ini_lig.strftime("%H:%M")
                intervalo_ligado = f"{hora_ligada}-{ts_fim_lig.strftime('%H:%M')}"
                if ts is not None and len(ts.dropna()) > 0:
                    df_pos_ligado = df.loc[ts >= ts_ini_lig].copy()
                else:
                    df_pos_ligado = _recortar_pos_ligado(df, col_en=col_en)
    else:
        df_pos_ligado = _recortar_pos_ligado(df, col_en=col_en)
        if not df_pos_ligado.empty:
            ts_lig = _obter_serie_tempo_local(df_pos_ligado).dropna()
            if len(ts_lig) > 0:
                hora_ligada = ts_lig.min().strftime("%H:%M")
                intervalo_ligado = f"{hora_ligada}-{ts_lig.max().strftime('%H:%M')}"
    ts_valid = ts.dropna() if ts is not None else pd.Series(dtype="datetime64[ns]")
    ts_max = ts_referencia if ts_referencia is not None else (ts_valid.max() if len(ts_valid) > 0 else None)

    if ts_max is None or pd.isna(ts_max) or len(ts_valid) == 0:
        return {
            "df_24h": df.copy(),
            "df_hora_atual": df_vazio,
            "df_daqui_pra_frente": df_vazio,
            "df_pos_ligado": df_pos_ligado,
            "df_acumulado": df,
            "rotulo_hora": "Hora Atual",
            "intervalo_hora": "",
            "hora_ligada": hora_ligada,
            "intervalo_ligado": intervalo_ligado,
            "ts_max": None,
        }

    inicio_24h = ts_max - pd.Timedelta(hours=24)
    inicio_hora = ts_max.replace(minute=0, second=0, microsecond=0)

    df_24h = df.loc[ts >= inicio_24h].copy()
    df_hora_atual = df.loc[ts >= inicio_hora].copy()
    if ts_inicio_sessao is not None and not pd.isna(ts_inicio_sessao):
        df_daqui_pra_frente = df.loc[ts >= ts_inicio_sessao].copy()
    else:
        df_daqui_pra_frente = df_vazio

    rotulo_hora = ts_max.strftime("%Hh")
    intervalo_hora = f"{inicio_hora.strftime('%H:%M')}-{ts_max.strftime('%H:%M')}"

    return {
        "df_24h": df_24h,
        "df_hora_atual": df_hora_atual,
        "df_daqui_pra_frente": df_daqui_pra_frente,
        "df_pos_ligado": df_pos_ligado,
        "df_acumulado": df,
        "rotulo_hora": rotulo_hora,
        "intervalo_hora": intervalo_hora,
        "hora_ligada": hora_ligada,
        "intervalo_ligado": intervalo_ligado,
        "ts_max": ts_max,
    }


def _calcular_resumo_janela(
    df_janela,
    col_v=None,
    col_sp=None,
    col_sem=None,
    col_en=None,
    col_b_in=None,
    col_b_out=None,
    lim_rastejo=20000.0,
    lim_b_out=70.0,
    lim_b_in=30.0,
    h_turno=8.0,
    df_sem_externo=None,
    dt_padrao_s=10.0,
    lim_parada=1000.0
):
    """Calcula o resumo operacional (A/B, Segue ON ou Segue OFF) para uma janela temporal."""
    if df_janela is None or len(df_janela) == 0:
        return None

    v_col = col_v if (col_v and col_v in df_janela.columns) else obter_coluna_velocidade(df_janela)
    en_col = col_en if (col_en and col_en in df_janela.columns) else obter_coluna_habilitado(df_janela)
    sp_col = col_sp if (col_sp and col_sp in df_janela.columns) else obter_coluna_setpoint_v4(df_janela)
    sem_col = col_sem if (col_sem and col_sem in df_janela.columns) else obter_coluna_sem_controle(df_janela)

    if v_col not in df_janela.columns:
        return None

    segue_on = _interpretar_bool(df_janela.iloc[-1].get(en_col, False))
    df_com, df_sem_interno = filtrar_on_off(df_janela, col_en=en_col)
    df_sem = df_sem_externo if df_sem_externo is not None else df_sem_interno

    if df_com is not None and df_sem is not None and len(df_com) > 0 and len(df_sem) > 0:
        m_ab = calcular_metricas(
            df_com, df_sem,
            col_velocidade=v_col, col_b_in=col_b_in, col_b_out=col_b_out,
            limiar_rastejo=lim_rastejo, limiar_b_out_gargalo=lim_b_out,
            limiar_b_in_min=lim_b_in, horas_turno=h_turno,
            dt_padrao_s=dt_padrao_s, limiar_parada=lim_parada
        )
        if m_ab:
            return {
                "n": len(df_janela),
                "dur_h": m_ab["t_com_h"],
                "v_med": m_ab["taxa_com"],
                "ref_med": m_ab["taxa_sem"],
                "ref_label": "SemCtrl A/B",
                "delta_cph": m_ab["ganho_cph"],
                "tot_gf": m_ab["total_ganho_gf"],
                "pct": m_ab["ganho_pct"],
                "turno_gf": m_ab["ganho_turno_8h"],
                "segue_on": segue_on,
                "modo": "AB",
                "metricas_ab": m_ab,
                "metricas_unico": None,
            }

    dur_h = obter_duracao_horas(df_janela, dt_padrao_s=dt_padrao_s)
    paradas_zero = int((df_janela[v_col] <= lim_parada).sum())
    min_parada = paradas_zero * (dt_padrao_s / 60.0)
    micro_pct = float((df_janela[v_col] < lim_rastejo).mean() * 100.0)
    min_rastejo_h = (micro_pct / 100.0) * 60.0

    tem_sem = bool(sem_col and sem_col in df_janela.columns and df_janela[sem_col].notna().any())
    tem_sp = bool(sp_col and sp_col in df_janela.columns and df_janela[sp_col].notna().any())

    ativo_mask = df_janela[v_col] > lim_parada
    tem_ativo = bool(ativo_mask.any())
    v_med = _safe_float(df_janela.loc[ativo_mask, v_col].mean(), 0.0) if tem_ativo else _safe_float(df_janela[v_col].mean(), 0.0)

    if segue_on:
        if tem_sem:
            deltas = (df_janela[v_col] - df_janela[sem_col]).where(ativo_mask, 0.0)
            delta_cph = _safe_float(deltas[ativo_mask].mean(), 0.0) if tem_ativo else 0.0
            ref_med = _safe_float(df_janela.loc[ativo_mask, sem_col].mean(), 0.0) if tem_ativo else _safe_float(df_janela[sem_col].mean(), 0.0)
            pct = (delta_cph / ref_med * 100.0) if ref_med > 0 else 0.0
            modo, ref_label, tipo_unico = "ON_REAL", "SemCtrl", "REAL_VS_SEM"
        elif tem_sp:
            deltas = (df_janela[sp_col] - df_janela[v_col]).where(ativo_mask, 0.0)
            delta_cph = _safe_float(deltas[ativo_mask].mean(), 0.0) if tem_ativo else 0.0
            ref_med = _safe_float(df_janela.loc[ativo_mask, sp_col].mean(), 0.0) if tem_ativo else _safe_float(df_janela[sp_col].mean(), 0.0)
            pct = (delta_cph / v_med * 100.0) if v_med > 0 else 0.0
            modo, ref_label, tipo_unico = "ON_SP", "SP V4", "SP_VS_REAL"
        else:
            return None
    else:
        if tem_sp:
            deltas = (df_janela[sp_col] - df_janela[v_col]).where(ativo_mask, 0.0)
            delta_cph = _safe_float(deltas[ativo_mask].mean(), 0.0) if tem_ativo else 0.0
            ref_med = _safe_float(df_janela.loc[ativo_mask, sp_col].mean(), 0.0) if tem_ativo else _safe_float(df_janela[sp_col].mean(), 0.0)
            pct = (delta_cph / v_med * 100.0) if v_med > 0 else 0.0
            modo, ref_label, tipo_unico = "OFF_OPORT", "SP V4", "SP_VS_REAL"
        elif tem_sem:
            deltas = (df_janela[v_col] - df_janela[sem_col]).where(ativo_mask, 0.0)
            delta_cph = _safe_float(deltas[ativo_mask].mean(), 0.0) if tem_ativo else 0.0
            ref_med = _safe_float(df_janela.loc[ativo_mask, sem_col].mean(), 0.0) if tem_ativo else _safe_float(df_janela[sem_col].mean(), 0.0)
            pct = (delta_cph / ref_med * 100.0) if ref_med > 0 else 0.0
            modo, ref_label, tipo_unico = "REAL_VS_SEM", "SemCtrl", "REAL_VS_SEM"
        else:
            return None

    tot_gf = float(_safe_float(deltas.mean(), 0.0) * dur_h)
    turno_gf = delta_cph * h_turno
    m_unico = {
        "dur_h": dur_h,
        "n": len(df_janela),
        "v_med": v_med,
        "delta_m": delta_cph,
        "pct_m": pct,
        "tot_gf": tot_gf,
        "turno_gf": turno_gf,
        "paradas_zero": paradas_zero,
        "min_parada": min_parada,
        "min_rastejo_h": min_rastejo_h,
        "limiar_parada": lim_parada,
        "tipo": tipo_unico,
    }
    if tipo_unico == "SP_VS_REAL":
        m_unico["sp_med"] = ref_med
    else:
        m_unico["sem_med"] = ref_med

    return {
        "n": len(df_janela),
        "dur_h": dur_h,
        "v_med": v_med,
        "ref_med": ref_med,
        "ref_label": ref_label,
        "delta_cph": delta_cph,
        "tot_gf": tot_gf,
        "pct": pct,
        "turno_gf": turno_gf,
        "segue_on": segue_on,
        "modo": modo,
        "metricas_ab": None,
        "metricas_unico": m_unico,
    }


def _formatar_valor_janela(resumo, vazio="0 gf", incluir_pct=False):
    """Formata explicitamente se a janela está ganhando ou perdendo produção."""
    if not resumo:
        return vazio

    tot_gf = resumo["tot_gf"]
    delta_cph = resumo["delta_cph"]
    pct = resumo["pct"]
    modo = resumo["modo"]

    if modo == "OFF_OPORT":
        if tot_gf > 0:
            pct_txt = f" | Oport. V4: +{pct:.1f}%" if incluir_pct else ""
            return f"🔻 Sem Segue: -{abs(tot_gf):,.0f} gf (-{abs(delta_cph):,.0f} CPH{pct_txt})"
        if abs(tot_gf) < 0.5 and abs(delta_cph) < 0.5:
            return "0 gf (0 CPH)"
        pct_txt = f" | +{abs(pct):.1f}%" if incluir_pct else ""
        return f"🟢 Acima SP V4 +{abs(tot_gf):,.0f} gf (+{abs(delta_cph):,.0f} CPH{pct_txt})"

    if modo == "ON_SP":
        sinal_gf = "+" if tot_gf >= 0 else ""
        sinal_c = "+" if delta_cph >= 0 else ""
        pct_txt = f" | {pct:+.1f}%" if incluir_pct else ""
        return f"🎯 Delta SP {sinal_gf}{tot_gf:,.0f} gf ({sinal_c}{delta_cph:,.0f} CPH{pct_txt})"

    pct_txt = f" | {pct:+.1f}%" if incluir_pct else ""
    if tot_gf >= 0:
        sufixo_vale = " ✅ Vale a pena" if incluir_pct else ""
        return f"🟢 Segue Ganhando +{tot_gf:,.0f} gf (+{delta_cph:,.0f} CPH{pct_txt}){sufixo_vale}"
    sufixo_vale = " ⚠️ Abaixo do OFF" if incluir_pct else ""
    return f"🔴 Segue Perdendo -{abs(tot_gf):,.0f} gf (-{abs(delta_cph):,.0f} CPH{pct_txt}){sufixo_vale}"


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
    novas_amostras=None,
    df_sem_externo=None,
    df_geral=None,
    trava_filtro=None,
    lim_rastejo=20000.0,
    lim_b_out=70.0,
    lim_b_in=30.0,
    col_b_in=None,
    col_b_out=None,
    ts_inicio_sessao=None,
    novas_sessao=None,
    lim_parada=1000.0
):
    """
    Gera linha de status em tempo real exibindo claramente GANHANDO vs PERDENDO
    para Últimas 24h, Hora Atual e Daqui pra Frente / Pós-Ligado.
    """
    v_col_nome = col_v if (col_v and col_v in df_acumulado.columns) else obter_coluna_velocidade(df_acumulado)
    en_col_nome = col_en if (col_en and col_en in df_acumulado.columns) else obter_coluna_habilitado(df_acumulado)
    tr_col_nome = col_tr if (col_tr and col_tr in df_acumulado.columns) else obter_coluna_trava(df_acumulado)

    sp_col_nome = col_sp if (col_sp and col_sp in df_acumulado.columns) else obter_coluna_setpoint_v4(df_acumulado)
    sem_col_nome = col_sem if (col_sem and col_sem in df_acumulado.columns) else obter_coluna_sem_controle(df_acumulado)

    v_atual = _safe_float(ultima_linha.get(v_col_nome, 0.0), 0.0)
    segue_on = _interpretar_bool(ultima_linha.get(en_col_nome, False))

    trava_val = ultima_linha.get(tr_col_nome or "trava_entrada_int", "N/A")
    ts_raw = ultima_linha.get("Time", ultima_linha.get("Timestamp", None))
    ts_curto = _formatar_ts_local(ts_raw)

    v_sp = _safe_float(ultima_linha.get(sp_col_nome, v_atual), v_atual) if sp_col_nome else v_atual
    v_sem = _safe_float(ultima_linha.get(sem_col_nome, 0.0), 0.0) if sem_col_nome else None

    df_ref_tempo = df_geral if (df_geral is not None and not df_geral.empty) else df_acumulado
    ts_ref = _obter_ts_max(df_ref_tempo)
    dt_padrao_s = _estimar_cadencia_segundos(df_ref_tempo)

    excluida_por_trava = False
    if _trava_eh_restritiva(trava_filtro) and df_geral is not None and not df_geral.empty and tr_col_nome:
        df_ult_filt = filtrar_trava(pd.DataFrame([ultima_linha]), trava_filtro, col_trava=tr_col_nome)
        excluida_por_trava = (len(df_ult_filt) == 0)

    janelas = _recortar_janelas_temporais(
        df_acumulado,
        ts_referencia=ts_ref,
        ts_inicio_sessao=ts_inicio_sessao,
        col_en=en_col_nome,
        df_geral=df_geral,
    )
    _, df_sem_historico = filtrar_on_off(df_acumulado, col_en=en_col_nome)
    df_sem_ref = df_sem_externo
    if df_sem_ref is None and df_sem_historico is not None and len(df_sem_historico) > 0:
        df_sem_ref = df_sem_historico

    kw_base = dict(
        col_v=v_col_nome,
        col_sp=sp_col_nome,
        col_sem=sem_col_nome,
        col_en=en_col_nome,
        col_b_in=col_b_in,
        col_b_out=col_b_out,
        lim_rastejo=lim_rastejo,
        lim_b_out=lim_b_out,
        lim_b_in=lim_b_in,
        h_turno=h_turno,
        dt_padrao_s=dt_padrao_s,
        lim_parada=lim_parada,
    )
    kw_resumo = dict(**kw_base, df_sem_externo=df_sem_externo)
    kw_resumo_ligado = dict(**kw_base, df_sem_externo=df_sem_ref)

    res_hora = _calcular_resumo_janela(janelas["df_hora_atual"], **kw_resumo_ligado)
    res_acum = _calcular_resumo_janela(janelas["df_acumulado"], **kw_resumo)

    if res_acum is None and m_ab:
        res_acum = {
            "tot_gf": m_ab["total_ganho_gf"],
            "delta_cph": m_ab["ganho_cph"],
            "pct": m_ab["ganho_pct"],
            "modo": "AB",
        }

    df_pos_lig = janelas["df_pos_ligado"]
    hora_ligada = janelas["hora_ligada"]

    # Sempre que o Segue estiver ligado, destacar "Desde HH:MM"; quando desligado, "Desde Início"
    if segue_on and len(df_pos_lig) > 0:
        res_pos = _calcular_resumo_janela(df_pos_lig, **kw_resumo_ligado)
        rotulo_frente = f"🟢 Desde {hora_ligada}" if hora_ligada else "🟢 Desde Início"
        txt_frente = _formatar_valor_janela(res_pos, vazio="0 gf (0 CPH)", incluir_pct=True)
    elif segue_on and hora_ligada:
        rotulo_frente = f"🟢 Desde {hora_ligada}"
        if _trava_eh_restritiva(trava_filtro) and str(trava_filtro).strip() == "1":
            txt_frente = "0 gf (aguardando T:1 Aberta)"
        else:
            txt_frente = "0 gf (aguardando válidas)"
    else:
        rotulo_frente = "🚀 Desde Início"
        txt_frente = _formatar_valor_janela(res_acum, vazio="0 gf (0 CPH)", incluir_pct=True)

    status_txt = "🟢 Segue On" if segue_on else "🔴 Segue Off"
    if novas_amostras is not None and novas_amostras > 0:
        sufixo_novas = f" (+{novas_amostras})"
    elif excluida_por_trava:
        sufixo_novas = " (+0)" if novas_amostras == 0 else ""
    elif novas_sessao is not None and novas_sessao > 0:
        sufixo_novas = f" (+{novas_sessao}s)"
    else:
        sufixo_novas = ""

    if excluida_por_trava and df_geral is not None:
        amostras_txt = f"Am:{len(df_acumulado)}/{len(df_geral)}{sufixo_novas}"
    else:
        amostras_txt = f"Am:{len(df_acumulado)}{sufixo_novas}"

    txt_hora = _formatar_valor_janela(res_hora, vazio="0 gf (0 CPH)", incluir_pct=False)

    aviso_filtro = ""
    if excluida_por_trava:
        if str(trava_filtro).strip() == "1":
            aviso_filtro = " | ⏸️ Trava Fechada (acumula só c/ T:1 Aberta)"
        else:
            aviso_filtro = f" | ⏸️ Fora filtro Trava={trava_filtro} (atual T={trava_val})"

    rotulo_hora = janelas["rotulo_hora"]
    trava_curta = _formatar_tag_trava_curta(trava_val)

    if segue_on and df_sem_ref is not None and not df_sem_ref.empty and v_col_nome in df_sem_ref.columns:
        df_sem_ativ = df_sem_ref[df_sem_ref[v_col_nome] > lim_parada]
        serie_off_ref = df_sem_ativ[v_col_nome] if len(df_sem_ativ) > 0 else df_sem_ref[v_col_nome]
        v_off_med = _safe_float(serie_off_ref.mean(), 0.0)
        if sp_col_nome:
            ref_txt = f"V Controlador: {v_sp:,.0f} | OFF: {v_off_med:,.0f}"
        else:
            ref_txt = f"OFF: {v_off_med:,.0f}"
    elif segue_on and v_sem is not None and sem_col_nome:
        ref_txt = f"Sem: {v_sem:,.0f}"
    elif sp_col_nome:
        ref_txt = f"V Controlador: {v_sp:,.0f}"
    else:
        ref_txt = f"Vatual: {v_atual:,.0f}"

    # Se a máquina física estiver parada (<= lim_parada CPH)
    if v_atual <= lim_parada:
        v_parada_txt = f"Vatual: {v_atual:,.0f} ({ref_txt})" if sp_col_nome else f"Vatual: {v_atual:,.0f}"
        return (
            f"[{ts_curto}] 🛑 PARADA | {status_txt} | {trava_curta} | {v_parada_txt} | "
            f"🕒 {rotulo_hora}: {txt_hora} | "
            f"{rotulo_frente}: {txt_frente} | "
            f"{amostras_txt}{aviso_filtro}\n"
        )

    return (
        f"[{ts_curto}] {status_txt} | {trava_curta} | Vatual: {v_atual:,.0f} ({ref_txt}) | "
        f"🕒 {rotulo_hora}: {txt_hora} | "
        f"{rotulo_frente}: {txt_frente} | "
        f"{amostras_txt}{aviso_filtro}\n"
    )


def exibir_relatorio(m, titulo="RESUMO EXECUTIVO: GANHO REAL DO CONTROLE"):
    """Exibe o relatório formatado de forma limpa e executiva."""
    print("\n" + "═" * 70)
    print(f" {titulo:^68}")
    print("═" * 70)
    print(f" Tempo Analisado : {m['t_com_h']:.2f} h COM controle ({m['n_com']} amostras) vs {m['t_sem_h']:.2f} h SEM controle ({m['n_sem']} amostras)")
    print("─" * 70)
    if m["total_ganho_gf"] >= 0:
        print(" ✅ RESULTADO: LINHA GANHANDO PRODUÇÃO COM SEGUE LIGADO")
        print(f" 🏆 GANHO TOTAL ENTREGUE   : +{m['total_ganho_gf']:,.0f} GARRAFAS A MAIS ({m['ganho_pct']:+.2f}%)")
    else:
        print(" 🔻 RESULTADO: LINHA PERDENDO PRODUÇÃO COM SEGUE LIGADO")
        print(f" 🔻 PERDA TOTAL APURADA    : -{abs(m['total_ganho_gf']):,.0f} GARRAFAS ({m['ganho_pct']:+.2f}%)")
    sinal_c = "+" if m["ganho_cph"] >= 0 else ""
    sinal_t = "+" if m["ganho_turno_8h"] >= 0 else ""
    print(f" ⚡ Ritmo Médio da Linha   : Foi de {m['taxa_sem']:,.0f} para {m['taxa_com']:,.0f} garrafas/hora ({sinal_c}{m['ganho_cph']:,.0f} CPH)")
    print(f" 📦 Impacto no Turno (8h)  : {sinal_t}{m['ganho_turno_8h']:,.0f} garrafas por turno")
    if m["total_ganho_gf"] >= 0:
        print(" 💡 VEREDITO SEGUE         : ✅ VALE A PENA MANTER HABILITADO (saldo positivo vs operação sem Segue)")
    else:
        print(" 💡 VEREDITO SEGUE         : ⚠️ SALDO NEGATIVO VS OFF (avaliar ajuste/manter desabilitado se persistir)")
    print("─" * 70)
    print(" 🛑 ANÁLISE DE PARADAS E RASTEJOS:")
    print(f" • Redução do Tempo Lento : O rastejo (<20k CPH) caiu de {m['min_rastejo_sem_h']:.1f} para {m['min_rastejo_com_h']:.1f} min/h ({m['reducao_rastejo_pct']:+.1f}%)")
    print(f" • Tempo Salvo de Linha   : A enchedora economizou {m['minutos_salvos']:.1f} minutos de lentidão/rastejo.")

    if m["paradas_zero_sem"] > 0 or m["paradas_zero_com"] > 0:
        lbl_p = f"<= {m.get('limiar_parada', 0):,.0f} CPH" if m.get("limiar_parada", 0) > 0 else "0 CPH"
        print(f" • {f'Paradas ({lbl_p})':<23}: SEM controle: {m['min_parada_sem']:.1f} min | COM controle: {m['min_parada_com']:.1f} min")

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
        if m.get("tipo") == "REAL_VS_SEM":
            if m["tot_gf"] >= 0:
                print(" ✅ RESULTADO: LINHA GANHANDO PRODUÇÃO COM SEGUE LIGADO")
            else:
                print(" 🔻 RESULTADO: LINHA PERDENDO PRODUÇÃO COM SEGUE LIGADO")
        else:
            print(" 🟢 CENÁRIO: SEGUE LIGADO (OPERAÇÃO ATIVA NO CONTROLE V4)")
        rotulo_bal = "GANHO LÍQUIDO ENTREGUE" if m["delta_m"] >= 0 else "PERCA / DESACELERAÇÃO"
        ref_txt = f"{m.get('sem_med', 0.0):,.0f} CPH (Sem Controle)" if 'sem_med' in m else f"{m.get('sp_med', 0.0):,.0f} CPH (Setpoint V4)"
        print(f" 🏆 {rotulo_bal:<23}: {sinal}{m['tot_gf']:,.0f} GARRAFAS ({m['pct_m']:+.2f}%)")
        print(f" ⚡ Ritmo Médio da Máquina : {m['v_med']:,.0f} garrafas/hora (Referência: {ref_txt})")
        print(f" 📦 Projeção no Turno (8h) : {sinal_t}{m['turno_gf']:,.0f} garrafas por turno")
        if m.get("tipo") == "REAL_VS_SEM":
            if m["tot_gf"] >= 0:
                veredito_msg = "✅ VALE A PENA MANTER HABILITADO (acima da referência sem controle)"
            else:
                veredito_msg = "⚠️ ABAIXO DA REFERÊNCIA SEM CONTROLE (avaliar desempenho)"
        else:
            veredito_msg = "🟢 CONTROLE V4 ATIVO (acompanhando setpoint de oportunidade)"
        print(f" 💡 VEREDITO SEGUE         : {veredito_msg}")
    else:
        if m["delta_m"] > 0:
            print(" 🔻 RESULTADO: LINHA PERDENDO PRODUÇÃO POR ESTAR COM SEGUE DESLIGADO (OPORTUNIDADE V4)")
        else:
            print(" 🔴 CENÁRIO: SEGUE DESLIGADO (CLP NATIVO / MODO SOMBRA / BYPASS)")
        print(f" ⚡ Ritmo Médio da Máquina : {m['v_med']:,.0f} garrafas/hora")
        print(f" 🎯 Ritmo Recomendado V4   : {m.get('sp_med', 0.0):,.0f} garrafas/hora (Setpoint V4 em Modo Sombra)")
        if m["delta_m"] > 0:
            print(f" ⚡ OPORTUNIDADE NÃO GANHA : +{m['tot_gf']:,.0f} garrafas poderiam ter sido envasadas")
            print(f" 🔻 PERDA POR SEGUE OFF    : -{m['tot_gf']:,.0f} garrafas perdidas (-{m['delta_m']:,.0f} CPH | {m['pct_m']:+.2f}%)")
        else:
            print(f" 🛡️ MODULAÇÃO PREVENTIVA   : V4 teria reduzido {abs(m['delta_m']):,.0f} CPH para proteção de buffer")
        print(f" 📦 Impacto no Turno (8h)  : {sinal_t}{m['turno_gf']:,.0f} garrafas em 8h com Segue ativo")
        if m["delta_m"] > 0:
            veredito_msg = "🟢 VALE A PENA HABILITAR O SEGUE (oportunidade positiva identificada)"
        else:
            veredito_msg = "⏸️ SEM GANHO ADICIONAL ESPERADO NESTA JANELA (modulação/equilíbrio)"
        print(f" 💡 VEREDITO SEGUE         : {veredito_msg}")

    lbl_p = f"<= {m.get('limiar_parada', 0):,.0f} CPH" if m.get("limiar_parada", 0) > 0 else "0 CPH"
    print(f" • {f'Paradas ({lbl_p})':<23}: {m['min_parada']:.1f} min ({m['paradas_zero']} ocorrências)")
    print(f" • Tempo em Rastejo        : {m['min_rastejo_h']:.1f} min/h (< 20,000 CPH)")
    print("═" * 70 + "\n")


def _exibir_quadro_janela(titulo_quadro, resumo, trava_filtro=None, msg_vazio="0 amostras válidas"):
    """Exibe um quadro compacto com veredito explícito de ganho ou perda para uma janela."""
    sufixo_trava = f" [{_descrever_filtro_trava(trava_filtro, maiusculo=True)}]" if _trava_eh_restritiva(trava_filtro) else ""

    if not resumo:
        print("─" * 70)
        print(f" {titulo_quadro}{sufixo_trava} : {msg_vazio}")
        print("═" * 70 + "\n")
        return

    if resumo["modo"] == "AB":
        veredito = "✅ VALE A PENA MANTER HABILITADO (GANHANDO NO CONFRONTO A/B)" if resumo["tot_gf"] >= 0 else "🔻 NÃO ESTÁ COMPENSANDO NESTA JANELA (PERDENDO NO A/B)"
        rotulo = "🟢 Segue Ganhando" if resumo["tot_gf"] >= 0 else "🔴 Segue Perdendo"
        saldo_txt = f"{'+' if resumo['tot_gf'] >= 0 else '-'}{abs(resumo['tot_gf']):,.0f} garrafas ({'+' if resumo['delta_cph'] >= 0 else '-'}{abs(resumo['delta_cph']):,.0f} CPH | {resumo['pct']:+.2f}%)"
    elif resumo["modo"] == "OFF_OPORT":
        if resumo["tot_gf"] > 0:
            veredito = "🔻 VALE A PENA HABILITAR O SEGUE (PERDENDO PRODUÇÃO COM SEGUE OFF)"
            rotulo = "🔻 Perda Sem Segue"
            saldo_txt = f"-{abs(resumo['tot_gf']):,.0f} garrafas (-{abs(resumo['delta_cph']):,.0f} CPH | Oport. V4: +{resumo['pct']:.2f}%)"
        elif abs(resumo["tot_gf"]) < 0.5 and abs(resumo["delta_cph"]) < 0.5:
            veredito = "⏸️ SEM DIFERENÇA ACUMULADA (PARADA FÍSICA / EQUILÍBRIO)"
            rotulo = "⏸️ Saldo na Janela"
            saldo_txt = "0 garrafas (0 CPH)"
        else:
            veredito = "🟢 RODANDO ACIMA DO SETPOINT V4 (SEGUE DESLIGADO)"
            rotulo = "🟢 Acima SP V4"
            saldo_txt = f"+{abs(resumo['tot_gf']):,.0f} garrafas (+{abs(resumo['delta_cph']):,.0f} CPH | +{abs(resumo['pct']):.2f}%)"
    elif resumo["modo"] == "ON_SP":
        veredito = "🟢 SEGUE LIGADO (ACOMPANHAMENTO DE SETPOINT V4)"
        rotulo = "🎯 Delta SP"
        sinal = "+" if resumo["tot_gf"] >= 0 else ""
        sinal_c = "+" if resumo["delta_cph"] >= 0 else ""
        saldo_txt = f"{sinal}{resumo['tot_gf']:,.0f} garrafas ({sinal_c}{resumo['delta_cph']:,.0f} CPH | {resumo['pct']:+.2f}%)"
    else:
        veredito = "✅ VALE A PENA MANTER HABILITADO (SEGUE GANHANDO)" if resumo["tot_gf"] >= 0 else "🔻 ABAIXO DA REFERÊNCIA OFF (SEGUE PERDENDO)"
        rotulo = "🟢 Segue Ganhando" if resumo["tot_gf"] >= 0 else "🔴 Segue Perdendo"
        saldo_txt = f"{'+' if resumo['tot_gf'] >= 0 else '-'}{abs(resumo['tot_gf']):,.0f} garrafas ({'+' if resumo['delta_cph'] >= 0 else '-'}{abs(resumo['delta_cph']):,.0f} CPH | {resumo['pct']:+.2f}%)"

    print("─" * 70)
    print(f" {titulo_quadro} ({resumo['dur_h']:.2f} h | {resumo['n']} amostras){sufixo_trava}")
    print("─" * 70)
    print(f" • Veredito           : {veredito}")
    print(f" • Ritmo Médio Real   : {resumo['v_med']:,.0f} CPH ({resumo['ref_label']}: {resumo['ref_med']:,.0f} CPH)")
    print(f" • {rotulo:<18} : {saldo_txt}")
    print("═" * 70 + "\n")


def exibir_relatorio_hora_atual(resumo, rotulo_hora, intervalo_hora="", trava_filtro=None):
    """Exibe um quadro compacto com o desempenho acumulado apenas na Hora Atual."""
    info_tempo = f"{rotulo_hora} | {intervalo_hora}" if intervalo_hora else rotulo_hora
    _exibir_quadro_janela(f"🕒 HORA ATUAL ({info_tempo})", resumo, trava_filtro=trava_filtro)


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


def _verificar_transicao_segue_ligado(df_acumulado, col_en, ultimo_segue_on):
    """Detecta virada ao vivo de SEGUE OFF -> SEGUE ON e retorna o estado atual."""
    if df_acumulado is None or df_acumulado.empty:
        return ultimo_segue_on
    en_col = col_en if (col_en and col_en in df_acumulado.columns) else obter_coluna_habilitado(df_acumulado)
    if en_col not in df_acumulado.columns:
        return ultimo_segue_on
    segue_atual = _interpretar_bool(df_acumulado.iloc[-1].get(en_col, False))
    if ultimo_segue_on is False and segue_atual is True:
        df_pos = _recortar_pos_ligado(df_acumulado, col_en=en_col)
        ts_ref_row = df_pos.iloc[0] if not df_pos.empty else df_acumulado.iloc[-1]
        ts_lig_str = _formatar_ts_local(ts_ref_row.get("Time", ts_ref_row.get("Timestamp", None)))
        print("\n" + "─" * 70)
        print(f" 🟢 SEGUE LIGADO ÀS {ts_lig_str}! Iniciando contagem acumulada DA HORA LIGADA PARA FRENTE...")
        print("─" * 70)
    return segue_atual


def executar_modo_online(caminho_csv, trava_filtro=None, intervalo_s=2.0, caminho_sem=None, lim_parada=1000.0):
    """Monitora o CSV em tempo real e calcula ganho ou perca a cada novo dado que chega."""
    trava_desc = _descrever_filtro_trava(trava_filtro)
    print("\n" + "═" * 70)
    print("      MEDIDOR DE GANHO INDUSTRIAL - MODO ONLINE (TEMPO REAL)")
    print("═" * 70)
    print(f" 📂 Monitorando Arquivo : {caminho_csv}")
    print(f" 🔒 Filtro de Trava     : {trava_desc}")
    print(f" ⏱️ Intervalo de Varredura: {intervalo_s:.1f} segundos")
    print(f" 🛑 Velocidade Parada    : <= {lim_parada:,.0f} CPH")
    print(" Pressione [Ctrl+C] a qualquer momento para encerrar e ver o resumo final.")
    print("─" * 70)

    ultimo_tamanho = -1
    total_anterior = 0
    filtradas_anterior = 0
    ts_inicio_sessao = None
    novas_sessao = 0
    ultimo_segue_on = None
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
                df = _normalizar_df_telemetria(pd.read_csv(caminho_csv))
                total_linhas = len(df)

                if total_linhas > 0:
                    df_filtrado = filtrar_trava(df, trava_filtro)
                    total_filtradas = len(df_filtrado)
                    if ts_inicio_sessao is None:
                        ts_inicio_sessao = _obter_ts_max(df)
                        novas_amostras = 0
                    else:
                        novas_totais = max(0, total_linhas - total_anterior)
                        if novas_totais == 0:
                            continue
                        novas_amostras = (
                            max(0, total_filtradas - filtradas_anterior)
                            if _trava_eh_restritiva(trava_filtro)
                            else novas_totais
                        )
                        novas_sessao += novas_amostras
                    total_anterior = total_linhas
                    filtradas_anterior = total_filtradas
                    df_base = df_filtrado if total_filtradas > 0 else df

                    ultima_linha = df.iloc[-1]
                    col_v = obter_coluna_velocidade(df)
                    col_en = obter_coluna_habilitado(df)
                    col_tr = obter_coluna_trava(df)
                    col_sp = obter_coluna_setpoint_v4(df)
                    col_sem_c = obter_coluna_sem_controle(df)

                    ultimo_segue_on = _verificar_transicao_segue_ligado(df, col_en, ultimo_segue_on)

                    msg_linha = formatar_status_novo_dado(
                        ultima_linha=ultima_linha,
                        df_acumulado=df_base,
                        col_v=col_v,
                        col_sp=col_sp,
                        col_sem=col_sem_c,
                        col_en=col_en,
                        col_tr=col_tr,
                        novas_amostras=novas_amostras,
                        df_sem_externo=df_sem_externo,
                        df_geral=df,
                        trava_filtro=trava_filtro,
                        ts_inicio_sessao=ts_inicio_sessao,
                        novas_sessao=novas_sessao,
                        lim_parada=lim_parada,
                    )
                    sys.stdout.write(msg_linha)
                    sys.stdout.flush()

            time.sleep(intervalo_s)
    except KeyboardInterrupt:
        print("\n\n" + "─" * 70)
        print(" ⏹️ Monitoramento Online Interrompido. Consolidando relatório da sessão...")
        df_final = _normalizar_df_telemetria(carregar_dados(caminho_csv))
        if df_final is not None and not df_final.empty:
            _exibir_resumo_grafana(
                df_acumulado=df_final,
                trava_filtro=trava_filtro,
                col_tr=obter_coluna_trava(df_final),
                col_v=obter_coluna_velocidade(df_final),
                col_en=obter_coluna_habilitado(df_final),
                col_sp=obter_coluna_setpoint_v4(df_final),
                col_sem_cfg=obter_coluna_sem_controle(df_final),
                col_b_in=None,
                col_b_out=None,
                lim_rastejo=20000.0,
                lim_b_out=70.0,
                lim_b_in=30.0,
                h_turno=8.0,
                df_sem_externo=df_sem_externo,
                titulo_base="RESUMO DA SESSÃO ONLINE (CSV)",
                ts_inicio_sessao=ts_inicio_sessao,
                lim_parada=lim_parada,
            )


def exibir_resumo_auditoria_analise(
    df_acumulado,
    trava_filtro=None,
    col_tr=None,
    col_v=None,
    col_en=None,
    col_sp=None,
    col_sem_cfg=None,
    col_b_in=None,
    col_b_out=None,
    lim_parada=1000.0,
    lim_rastejo=20000.0,
    h_turno=8.0,
    df_sem_externo=None,
    dt_padrao_s=None,
    titulo="🔍 AUDITORIA DA ANÁLISE (RAIO-X PARA VERIFICAÇÃO)"
):
    """Exibe funil completo de amostras, filtros, estatísticas ativas e saldo por motivo."""
    if df_acumulado is None or len(df_acumulado) == 0:
        print("\n" + "─" * 70)
        print(f" {titulo}: sem amostras disponíveis.")
        print("═" * 70 + "\n")
        return

    v_col = col_v if (col_v and col_v in df_acumulado.columns) else obter_coluna_velocidade(df_acumulado)
    en_col = col_en if (col_en and col_en in df_acumulado.columns) else obter_coluna_habilitado(df_acumulado)
    tr_col = col_tr if (col_tr and col_tr in df_acumulado.columns) else obter_coluna_trava(df_acumulado)
    sp_col = col_sp if (col_sp and col_sp in df_acumulado.columns) else obter_coluna_setpoint_v4(df_acumulado)
    sem_col = col_sem_cfg if (col_sem_cfg and col_sem_cfg in df_acumulado.columns) else obter_coluna_sem_controle(df_acumulado)

    b2_col = col_b_in if (col_b_in and col_b_in in df_acumulado.columns) else (
        "b2_pct" if "b2_pct" in df_acumulado.columns else (
            "accumulation_percentage_uip_to_ech_null" if "accumulation_percentage_uip_to_ech_null" in df_acumulado.columns else None
        )
    )
    b3_col = col_b_out if (col_b_out and col_b_out in df_acumulado.columns) else (
        "b3_pct" if "b3_pct" in df_acumulado.columns else (
            "accumulation_percentage_ech_to_pz_null" if "accumulation_percentage_ech_to_pz_null" in df_acumulado.columns else None
        )
    )

    dt_ciclo = dt_padrao_s if (dt_padrao_s is not None and dt_padrao_s > 0) else _estimar_cadencia_segundos(df_acumulado, padrao=10.0)
    dt_h = dt_ciclo / 3600.0

    ts_serie = _obter_serie_tempo_local(df_acumulado).dropna()
    if len(ts_serie) > 0:
        periodo_txt = f"{ts_serie.min().strftime('%d/%m/%Y %H:%M:%S')} -> {ts_serie.max().strftime('%d/%m/%Y %H:%M:%S')}"
    else:
        periodo_txt = f"{len(df_acumulado)} amostras"

    n_bruto = len(df_acumulado)
    df_trava = filtrar_trava(df_acumulado, trava_filtro, col_trava=tr_col) if _trava_eh_restritiva(trava_filtro) else df_acumulado
    n_trava = len(df_trava)
    n_desc_trava = n_bruto - n_trava

    print("\n" + "═" * 70)
    print(f" {titulo:^68}")
    print("═" * 70)
    print(f" • Período Analisado     : {periodo_txt} (cadência: ~{dt_ciclo:.1f}s)")
    print(f" • Filtro de Trava       : {_descrever_filtro_trava(trava_filtro)}")
    print(f" • Corte de Parada       : <= {lim_parada:,.0f} CPH (rastejo < {lim_rastejo:,.0f} CPH)")
    print("─" * 70)
    print(" 📋 1. FUNIL DE AMOSTRAS E FILTROS:")
    print(f" • Amostras Lidas (Bruto): {n_bruto} ({n_bruto * dt_h:.2f} h)")
    print(f" • Passaram na Trava     : {n_trava} ({n_trava * dt_h:.2f} h) | Ignoradas p/ trava: {n_desc_trava}")

    if n_trava == 0 or v_col not in df_trava.columns:
        print(" ⚠️ Nenhuma amostra passou pelo filtro de trava neste período.")
        print("═" * 70 + "\n")
        return

    ativo_mask = df_trava[v_col] > lim_parada
    df_ativo = df_trava.loc[ativo_mask].copy()
    n_ativo = len(df_ativo)
    n_parada = n_trava - n_ativo

    df_on_filt, df_off_filt = filtrar_on_off(df_trava, col_en=en_col)
    n_on = len(df_on_filt) if df_on_filt is not None else 0
    n_off = len(df_off_filt) if df_off_filt is not None else 0

    df_on_at, df_off_at = filtrar_on_off(df_ativo, col_en=en_col)
    n_on_at = len(df_on_at) if df_on_at is not None else 0
    n_off_at = len(df_off_at) if df_off_at is not None else 0

    print(f" • Máquina Rodando (Ativo): {n_ativo} ({n_ativo * dt_h:.2f} h) [Entraram na soma] | Paradas: {n_parada} ({n_parada * dt_h:.2f} h) [Zeradas]")
    print(f" • Segue no Filtro       : Segue On: {n_on} ({n_on_at} rodando) | Segue Off: {n_off} ({n_off_at} rodando)")

    if n_ativo == 0:
        print("─" * 70)
        print(f" ⏸️ Nenhuma amostra com Vatual > {lim_parada:,.0f} CPH dentro do filtro de trava.")
        print("═" * 70 + "\n")
        return

    v_med = _safe_float(df_ativo[v_col].mean(), 0.0)
    v_mediana = _safe_float(df_ativo[v_col].median(), 0.0)
    v_max = _safe_float(df_ativo[v_col].max(), 0.0)
    prod_real_gf = float((df_ativo[v_col].fillna(0.0) * dt_h).sum())

    print("─" * 70)
    print(" 📊 2. BALANÇO E VELOCIDADES (SOMENTE AMOSTRAS RODANDO):")
    print(f" • Vatual (Rodando)      : Média: {v_med:,.0f} CPH | Mediana: {v_mediana:,.0f} CPH | Máx: {v_max:,.0f} CPH")

    tem_sp_ativo = bool(sp_col and sp_col in df_ativo.columns and df_ativo[sp_col].notna().any())
    if tem_sp_ativo:
        sp_med = _safe_float(df_ativo[sp_col].mean(), 0.0)
        print(f" • V Controlador (Média) : {sp_med:,.0f} CPH")

    df_sem_ext_at = None
    if df_sem_externo is not None and not df_sem_externo.empty and v_col in df_sem_externo.columns:
        df_s_filt = filtrar_trava(df_sem_externo, trava_filtro, col_trava=tr_col) if _trava_eh_restritiva(trava_filtro) else df_sem_externo
        df_s_at = df_s_filt[df_s_filt[v_col] > lim_parada]
        df_sem_ext_at = df_s_at if len(df_s_at) > 0 else df_s_filt

    v_off_base = None
    df_mot_base = df_ativo
    modo_auditoria = "OFF_OPORT"

    if n_on_at > 0 and (n_off_at > 0 or (df_sem_ext_at is not None and len(df_sem_ext_at) > 0)):
        df_ref_off = df_off_at if n_off_at > 0 else df_sem_ext_at
        v_off_base = _safe_float(df_ref_off[v_col].mean(), 0.0)
        v_on_med = _safe_float(df_on_at[v_col].mean(), 0.0)
        prod_on_gf = float((df_on_at[v_col].fillna(0.0) * dt_h).sum())
        prod_esp_off_gf = v_off_base * (n_on_at * dt_h)
        saldo_ab_gf = prod_on_gf - prod_esp_off_gf
        delta_ab_cph = v_on_med - v_off_base
        pct_ab = (delta_ab_cph / v_off_base * 100.0) if v_off_base > 0 else 0.0
        modo_auditoria = "AB_ON"
        df_mot_base = df_on_at
        print(f" • Referência Segue Off  : {v_off_base:,.0f} CPH ({len(df_ref_off)} amostras rodando)")
        print(f" • Produção Segue On     : Real: {prod_on_gf:,.0f} gf | Base OFF no mesmo tempo: {prod_esp_off_gf:,.0f} gf")
        if saldo_ab_gf >= 0:
            print(f" • Saldo Líquido         : 🟢 Segue Ganhando +{saldo_ab_gf:,.0f} gf (+{delta_ab_cph:,.0f} CPH | {pct_ab:+.2f}%)")
            conclusao_txt = f"✅ VALE A PENA MANTER HABILITADO (+{saldo_ab_gf:,.0f} gf reais | +{delta_ab_cph * h_turno:,.0f} gf/turno 8h)"
        else:
            print(f" • Saldo Líquido         : 🔴 Segue Perdendo -{abs(saldo_ab_gf):,.0f} gf (-{abs(delta_ab_cph):,.0f} CPH | {pct_ab:+.2f}%)")
            conclusao_txt = f"⚠️ SALDO NEGATIVO VS OFF (-{abs(saldo_ab_gf):,.0f} gf no período — avaliar ajuste)"
    elif n_on_at > 0 and sem_col and sem_col in df_ativo.columns and df_ativo[sem_col].notna().any():
        v_off_base = _safe_float(df_ativo[sem_col].mean(), 0.0)
        v_on_med = _safe_float(df_on_at[v_col].mean(), 0.0)
        prod_on_gf = float((df_on_at[v_col].fillna(0.0) * dt_h).sum())
        prod_esp_off_gf = float((df_on_at[sem_col].fillna(v_off_base) * dt_h).sum())
        saldo_ab_gf = prod_on_gf - prod_esp_off_gf
        delta_ab_cph = v_on_med - v_off_base
        pct_ab = (delta_ab_cph / v_off_base * 100.0) if v_off_base > 0 else 0.0
        modo_auditoria = "ON_SEM"
        df_mot_base = df_on_at
        print(f" • Base Sem Controle     : {v_off_base:,.0f} CPH")
        print(f" • Produção Segue On     : Real: {prod_on_gf:,.0f} gf | Sem Controle: {prod_esp_off_gf:,.0f} gf")
        if saldo_ab_gf >= 0:
            print(f" • Saldo Líquido         : 🟢 Segue Ganhando +{saldo_ab_gf:,.0f} gf (+{delta_ab_cph:,.0f} CPH | {pct_ab:+.2f}%)")
            conclusao_txt = f"✅ VALE A PENA MANTER HABILITADO (+{saldo_ab_gf:,.0f} gf sobre referência)"
        else:
            print(f" • Saldo Líquido         : 🔴 Segue Perdendo -{abs(saldo_ab_gf):,.0f} gf (-{abs(delta_ab_cph):,.0f} CPH | {pct_ab:+.2f}%)")
            conclusao_txt = f"⚠️ ABAIXO DA REFERÊNCIA SEM CONTROLE (-{abs(saldo_ab_gf):,.0f} gf)"
    elif tem_sp_ativo:
        gf_esp_v4 = float((df_ativo[sp_col].fillna(v_med) * dt_h).sum())
        oport_gf = gf_esp_v4 - prod_real_gf
        delta_cph = sp_med - v_med
        pct_s = (delta_cph / v_med * 100.0) if v_med > 0 else 0.0
        print(f" • Produção Tempo Ativo  : Real: {prod_real_gf:,.0f} gf | Esperada c/ V Controlador: {gf_esp_v4:,.0f} gf")
        if n_on_at > 0:
            modo_auditoria = "ON_SP"
            print(f" • Desvio p/ V Ctrl      : {prod_real_gf - gf_esp_v4:+,.0f} gf ({v_med - sp_med:+,.0f} CPH)")
            conclusao_txt = "🟢 SEGUE LIGADO ATIVO (sem histórico Segue Off no filtro para confronto A/B)"
        elif oport_gf > 0:
            print(f" • Saldo da Análise      : 🔻 Sem Segue deixou de produzir -{oport_gf:,.0f} gf (-{delta_cph:,.0f} CPH | Oport. V4: +{pct_s:.2f}%)")
            conclusao_txt = f"🟢 VALE A PENA HABILITAR O SEGUE (+{oport_gf:,.0f} gf de ganho estimado neste período)"
        else:
            print(f" • Saldo da Análise      : 🟢 Vatual ficou +{abs(oport_gf):,.0f} gf acima do V Controlador (+{abs(delta_cph):,.0f} CPH)")
            conclusao_txt = "⏸️ Linha já rodou acima do Setpoint V4 neste recorte"
    else:
        print(f" • Produção Tempo Ativo  : {prod_real_gf:,.0f} gf")
        conclusao_txt = "ℹ️ Sem coluna de referência (V Controlador / Sem Controle) para cálculo de saldo."

    buf_parts = []
    if b2_col and b2_col in df_ativo.columns and df_ativo[b2_col].notna().any():
        buf_parts.append(f"B2 Entrada: {_safe_float(df_ativo[b2_col].mean(), 0.0):.1f}%")
    if b3_col and b3_col in df_ativo.columns and df_ativo[b3_col].notna().any():
        buf_parts.append(f"B3 Saída: {_safe_float(df_ativo[b3_col].mean(), 0.0):.1f}%")
    if buf_parts:
        print(f" • Buffers Médios (Ativo): {' | '.join(buf_parts)}")
    print(f" • 💡 CONCLUSÃO          : {conclusao_txt}")

    col_motivo = "motivo_codigo" if "motivo_codigo" in df_mot_base.columns else (
        "status_modulacao" if "status_modulacao" in df_mot_base.columns else None
    )
    if col_motivo and df_mot_base[col_motivo].notna().any():
        print("─" * 70)
        lbl_raio = "Segue On vs OFF" if modo_auditoria == "AB_ON" else ("Segue On vs Sem" if modo_auditoria == "ON_SEM" else "Vatual vs V Controlador")
        print(f" 🔍 3. RAIO-X POR MOTIVO DO CONTROLADOR ({lbl_raio}):")
        linhas_mot = []
        serie_mot = df_mot_base[col_motivo].fillna("SEM_MOTIVO").astype(str)
        for mot, g in df_mot_base.groupby(serie_mot, sort=False):
            n_m = len(g)
            min_m = n_m * (dt_ciclo / 60.0)
            v_m = _safe_float(g[v_col].mean(), 0.0)
            sp_m = _safe_float(g[sp_col].mean(), v_m) if (sp_col and sp_col in g.columns and g[sp_col].notna().any()) else None
            b2_m = _safe_float(g[b2_col].mean(), float("nan")) if (b2_col and b2_col in g.columns and g[b2_col].notna().any()) else None
            b3_m = _safe_float(g[b3_col].mean(), float("nan")) if (b3_col and b3_col in g.columns and g[b3_col].notna().any()) else None

            if modo_auditoria == "AB_ON" and v_off_base is not None:
                gf_m = float(((g[v_col].fillna(0.0) - v_off_base) * dt_h).sum())
                cph_m = v_m - v_off_base
            elif modo_auditoria == "ON_SEM" and sem_col and sem_col in g.columns:
                gf_m = float(((g[v_col].fillna(0.0) - g[sem_col].fillna(v_off_base)) * dt_h).sum())
                cph_m = v_m - _safe_float(g[sem_col].mean(), v_off_base)
            elif sp_m is not None:
                # Em Segue Off: saldo positivo quando VCtrl > Vatual (oportunidade)
                gf_m = float(((g[sp_col].fillna(v_m) - g[v_col].fillna(0.0)) * dt_h).sum())
                cph_m = sp_m - v_m
            else:
                gf_m = 0.0
                cph_m = 0.0

            linhas_mot.append((abs(gf_m), mot, n_m, min_m, v_m, sp_m, gf_m, cph_m, b2_m, b3_m))

        linhas_mot.sort(key=lambda item: item[0], reverse=True)
        for _, mot, n_m, min_m, v_m, sp_m, gf_m, cph_m, b2_m, b3_m in linhas_mot:
            sp_str = f"{sp_m:,.0f}" if sp_m is not None else "--"
            buf_m_parts = []
            if b2_m is not None and not pd.isna(b2_m):
                buf_m_parts.append(f"B2:{b2_m:.0f}%")
            if b3_m is not None and not pd.isna(b3_m):
                buf_m_parts.append(f"B3:{b3_m:.0f}%")
            buf_m_txt = f" | {' '.join(buf_m_parts)}" if buf_m_parts else ""
            if modo_auditoria in ("AB_ON", "ON_SEM"):
                saldo_m_txt = f"{gf_m:+,.0f} gf ({cph_m:+,.0f} CPH)"
            else:
                lbl_s = "Oport" if gf_m >= 0 else "AcimaSP"
                saldo_m_txt = f"{lbl_s}: {gf_m:+,.0f} gf ({cph_m:+,.0f} CPH)"
            print(f"   • {mot:<25} | {n_m:4d}am ({min_m:5.1f}m) | Vat:{v_m:6,.0f} | VCtrl:{sp_str:>6} | {saldo_m_txt}{buf_m_txt}")

    print("═" * 70 + "\n")


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
    titulo_base,
    ts_inicio_sessao=None,
    lim_parada=1000.0
):
    """Calcula e exibe Últimas 24h, Hora Atual e Da Hora Ligada para Frente."""
    if df_acumulado is None or len(df_acumulado) == 0:
        return
    df_filtrado = filtrar_trava(df_acumulado, trava_filtro, col_trava=col_tr)
    df_alvo = df_filtrado if len(df_filtrado) > 0 else df_acumulado
    dt_padrao_s = _estimar_cadencia_segundos(df_acumulado)
    ts_ref = _obter_ts_max(df_acumulado)
    janelas = _recortar_janelas_temporais(
        df_alvo, ts_referencia=ts_ref, ts_inicio_sessao=ts_inicio_sessao, col_en=col_en, df_geral=df_acumulado
    )
    df_24h = janelas["df_24h"] if len(janelas["df_24h"]) > 0 else df_alvo

    _, df_sem_historico = filtrar_on_off(df_alvo, col_en=col_en)
    df_sem_ref = df_sem_externo
    if df_sem_ref is None and df_sem_historico is not None and len(df_sem_historico) > 0:
        df_sem_ref = df_sem_historico

    tit_24h = f"{titulo_base} - ÚLTIMAS 24H"
    if _trava_eh_restritiva(trava_filtro) and len(df_filtrado) > 0:
        tit_24h += f" [{_descrever_filtro_trava(trava_filtro, maiusculo=True)}]"
    elif _trava_eh_restritiva(trava_filtro):
        tit_24h += f" [SEM REGISTROS COM TRAVA == {trava_filtro} - TODAS AS CONDIÇÕES]"
    elif trava_filtro is not None:
        tit_24h += " [TODAS AS CONDIÇÕES]"

    kw_base = dict(
        col_v=col_v,
        col_sp=col_sp,
        col_sem=col_sem_cfg,
        col_en=col_en,
        col_b_in=col_b_in,
        col_b_out=col_b_out,
        lim_rastejo=lim_rastejo,
        lim_b_out=lim_b_out,
        lim_b_in=lim_b_in,
        h_turno=h_turno,
        dt_padrao_s=dt_padrao_s,
        lim_parada=lim_parada,
    )
    kw_resumo = dict(**kw_base, df_sem_externo=df_sem_externo)
    kw_resumo_ligado = dict(**kw_base, df_sem_externo=df_sem_ref)

    res_24h = _calcular_resumo_janela(df_24h, **kw_resumo)
    if res_24h and res_24h["metricas_ab"]:
        exibir_relatorio(res_24h["metricas_ab"], titulo=tit_24h)
    elif res_24h and res_24h["metricas_unico"]:
        exibir_relatorio_modo_unico(res_24h["metricas_unico"], segue_on=res_24h["segue_on"], titulo=tit_24h)

    res_hora = _calcular_resumo_janela(janelas["df_hora_atual"], **kw_resumo_ligado)
    exibir_relatorio_hora_atual(
        res_hora,
        rotulo_hora=janelas["rotulo_hora"],
        intervalo_hora=janelas["intervalo_hora"],
        trava_filtro=trava_filtro,
    )

    df_pos_lig = janelas["df_pos_ligado"]
    if len(df_pos_lig) > 0:
        hora_lig = janelas["hora_ligada"]
        int_lig = janelas["intervalo_ligado"]
        detalhe_lig = f"DESDE {hora_lig} | {int_lig}" if hora_lig else f"{len(df_pos_lig)} amostras"
        tit_lig = f"🟢 DA HORA LIGADA PARA FRENTE ({detalhe_lig})"
        res_pos = _calcular_resumo_janela(df_pos_lig, **kw_resumo_ligado)
        if res_pos and res_pos["metricas_ab"]:
            if _trava_eh_restritiva(trava_filtro):
                tit_lig += f" [{_descrever_filtro_trava(trava_filtro, maiusculo=True)}]"
            exibir_relatorio(res_pos["metricas_ab"], titulo=tit_lig)
        else:
            _exibir_quadro_janela(tit_lig, res_pos, trava_filtro=trava_filtro)

    df_daqui = janelas["df_daqui_pra_frente"]
    if len(df_daqui) > 0 and len(df_daqui) != len(df_pos_lig):
        res_daqui = _calcular_resumo_janela(df_daqui, **kw_resumo_ligado)
        _exibir_quadro_janela("🚀 DAQUI PRA FRENTE (SESSÃO AO VIVO)", res_daqui, trava_filtro=trava_filtro)

    if len(df_alvo) > len(df_24h):
        res_acum = _calcular_resumo_janela(df_alvo, **kw_resumo)
        _exibir_quadro_janela("📈 ACUMULADO TOTAL DA SESSÃO", res_acum, trava_filtro=trava_filtro)

    exibir_resumo_auditoria_analise(
        df_acumulado=df_acumulado,
        trava_filtro=trava_filtro,
        col_tr=col_tr,
        col_v=col_v,
        col_en=col_en,
        col_sp=col_sp,
        col_sem_cfg=col_sem_cfg,
        col_b_in=col_b_in,
        col_b_out=col_b_out,
        lim_parada=lim_parada,
        lim_rastejo=lim_rastejo,
        h_turno=h_turno,
        df_sem_externo=df_sem_externo,
        dt_padrao_s=dt_padrao_s,
    )


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
    novas_amostras=None,
    ts_inicio_sessao=None,
    novas_sessao=None,
    lim_parada=1000.0
):
    """Prepara e formata a linha de telemetria em tempo real para exibição imediata."""
    df_filtrado = filtrar_trava(df_acumulado, trava_filtro, col_trava=col_tr)
    df_base_status = df_filtrado if len(df_filtrado) > 0 else df_acumulado

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
        novas_amostras=novas_amostras,
        df_sem_externo=df_sem_externo,
        df_geral=df_acumulado,
        trava_filtro=trava_filtro,
        lim_rastejo=lim_rastejo,
        lim_b_out=lim_b_out,
        lim_b_in=lim_b_in,
        col_b_in=col_b_in,
        col_b_out=col_b_out,
        ts_inicio_sessao=ts_inicio_sessao,
        novas_sessao=novas_sessao,
        lim_parada=lim_parada,
    )
    if soda_ativo:
        cnt_soda = cliente.buscar_contador_soda(cfg_soda)
        if cnt_soda is not None:
            msg_linha = msg_linha.rstrip("\n") + f" | 🍾 SODA: {cnt_soda:,.0f} gf\n"
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
    janela_historico="24h",
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
    lim_parada = float(cfg_an.get("velocidade_parada_cph", cfg_an.get("limiar_parada_cph", 1000.0)))
    lim_b_out = float(cfg_an.get("limiar_buffer_saida_gargalo_pct", 70.0))
    lim_b_in = float(cfg_an.get("limiar_buffer_entrada_min_pct", 30.0))
    h_turno = float(cfg_an.get("horas_turno_projecao", 8.0))
    trava_desc = _descrever_filtro_trava(trava_filtro)

    print("\n" + "═" * 70)
    print("   MEDIDOR DE GANHO INDUSTRIAL - STREAMING DIRETO DA API DO GRAFANA")
    print("═" * 70)
    print(f" 🌐 URL Grafana       : {url}")
    print(f" 🏭 Measurement/Linha : {measurement} (Bucket: {bucket} | DS: {ds_selector})")
    print(f" 🔒 Filtro de Trava   : {trava_desc}")
    print(f" ⏱️ Ciclo de Varredura : {intervalo_s:.1f} segundos")
    print(f" ⏳ Janela Histórica  : {janela_historico}")
    print(f" 🛑 Velocidade Parada : <= {lim_parada:,.0f} CPH")
    print(f" 📊 Limiar Rastejo    : < {lim_rastejo:,.0f} CPH | Projeção Turno: {h_turno:.0f}h")
    if soda_ativo:
        print(f" 🍾 Auditoria SODA    : DB: {cfg_soda.get('database')} (DS: {cfg_soda.get('datasource')}) | Eq: {cfg_soda.get('equipment_name')}")
    if query_template:
        print(f" 📝 Query Raw InfluxQL : {query_template}")
    print(" Pressione [Ctrl+C] a qualquer momento para encerrar e ver o resumo consolidado.")
    print("─" * 70)

    df_acumulado = pd.DataFrame()
    df_sem_externo = None
    ts_inicio_sessao = None
    novas_sessao = 0
    ultimo_segue_on = None
    cliente = None

    try:
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
        limite_inicial = _calcular_limite_janela(janela_historico, minimo=10000)
        df_acumulado = buscar_dados_grafana_resiliente(
            cliente=cliente,
            measurement=cliente.measurement,
            bucket=cliente.bucket,
            limite=limite_inicial,
            tempo_inicio_str=f"-{janela_historico}",
            query_template=query_template
        )

        if caminho_sem:
            df_sem_externo = carregar_dados(caminho_sem)
            if df_sem_externo is not None:
                df_sem_externo = filtrar_trava(df_sem_externo, trava_filtro, col_trava=col_tr)

        if df_acumulado.empty:
            print(f"⚠ Nenhum ponto retornado para a medição '{cliente.measurement}' no intervalo inicial.")
            print("➔ Modo streaming ativo: aguardando chegada de novos pontos do CLP/Controlador...")
        else:
            ts_inicio_sessao = _obter_ts_max(df_acumulado)
            ultimo_segue_on = _verificar_transicao_segue_ligado(df_acumulado, col_en, None)
            extra_tr = ""
            if _trava_eh_restritiva(trava_filtro):
                col_tr_uso = col_tr if (col_tr and col_tr in df_acumulado.columns) else obter_coluna_trava(df_acumulado)
                n_filt_ini = len(filtrar_trava(df_acumulado, trava_filtro, col_trava=col_tr_uso))
                extra_tr = f" ({n_filt_ini} válidas no filtro {_descrever_filtro_trava(trava_filtro)})"
            print(f"✅ Telemetria conectada: {len(df_acumulado)} amostras carregadas de '{cliente.measurement}' (Bucket: '{cliente.bucket}'){extra_tr}.")
            # Exibe resumo parcial instantâneo (Últimas 24h + Hora Atual + Auditoria) e primeira linha ao vivo logo na partida
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
                titulo_base=f"RESUMO PARCIAL INICIAL (LINHA {cliente.measurement})",
                ts_inicio_sessao=ts_inicio_sessao,
                lim_parada=lim_parada,
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
                novas_amostras=0,
                ts_inicio_sessao=ts_inicio_sessao,
                novas_sessao=novas_sessao,
                lim_parada=lim_parada,
            )
            sys.stdout.write(msg_inicial)
            sys.stdout.flush()

        contador_loop = 0
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
            novas_totais = 0
            novas_amostras = 0
            if not df_recente.empty:
                df_recente = df_recente.loc[:, ~df_recente.columns.duplicated()]
                tam_antes = len(df_acumulado)
                if not df_acumulado.empty and _trava_eh_restritiva(trava_filtro):
                    col_tr_antes = col_tr if (col_tr and col_tr in df_acumulado.columns) else obter_coluna_trava(df_acumulado)
                    tam_filt_antes = len(filtrar_trava(df_acumulado, trava_filtro, col_trava=col_tr_antes))
                else:
                    tam_filt_antes = tam_antes

                if df_acumulado.empty:
                    df_acumulado = df_recente.copy()
                else:
                    df_acumulado = df_acumulado.loc[:, ~df_acumulado.columns.duplicated()]
                    df_acumulado = pd.concat([df_acumulado, df_recente], ignore_index=True)

                df_acumulado = _normalizar_df_telemetria(df_acumulado)
                novas_totais = max(0, len(df_acumulado) - tam_antes)
                if _trava_eh_restritiva(trava_filtro) and not df_acumulado.empty:
                    col_tr_depois = col_tr if (col_tr and col_tr in df_acumulado.columns) else obter_coluna_trava(df_acumulado)
                    tam_filt_depois = len(filtrar_trava(df_acumulado, trava_filtro, col_trava=col_tr_depois))
                    novas_amostras = max(0, tam_filt_depois - tam_filt_antes)
                else:
                    novas_amostras = novas_totais

                if ts_inicio_sessao is None and not df_acumulado.empty:
                    ts_valid_rec = _obter_serie_tempo_local(df_acumulado).dropna()
                    if len(ts_valid_rec) > 0:
                        ts_inicio_sessao = ts_valid_rec.min() - pd.Timedelta(seconds=1)
                novas_sessao += novas_amostras

            if len(df_acumulado) == 0:
                hora_agora = datetime.datetime.now().strftime("%H:%M:%S")
                sys.stdout.write(f"\r[{hora_agora}] ⏳ Aguardando telemetria em '{cliente.measurement}' (verificação #{contador_loop})...\033[K")
                sys.stdout.flush()
                continue

            if novas_totais == 0:
                continue

            ultimo_segue_on = _verificar_transicao_segue_ligado(df_acumulado, col_en, ultimo_segue_on)

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
                novas_amostras=novas_amostras,
                ts_inicio_sessao=ts_inicio_sessao,
                novas_sessao=novas_sessao,
                lim_parada=lim_parada,
            )
            sys.stdout.write(msg_linha)
            sys.stdout.flush()

    except KeyboardInterrupt:
        print("\n\n" + "─" * 70)
        print(" ⏹️ Streaming do Grafana Interrompido. Consolidando relatório da sessão...")
        if cliente is not None:
            cliente.desconectar()
        if df_acumulado is not None and not df_acumulado.empty:
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
                titulo_base=f"RESUMO DA SESSÃO ONLINE GRAFANA (LINHA {measurement})",
                ts_inicio_sessao=ts_inicio_sessao,
                lim_parada=lim_parada,
            )
        else:
            print(" ⚠️ Nenhuma amostra foi carregada antes da interrupção para consolidar o resumo.")
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
    parser.add_argument("--trava", type=str, default=None, help="Filtrar por trava de entrada: 1 (aberta / fluxo livre, padrão), 0 (fechada / bloqueada) ou 'all'")
    parser.add_argument("--velocidade-parada", "--limiar-parada", dest="velocidade_parada", type=float, default=None, help="Velocidade (CPH) abaixo ou igual à qual a máquina é considerada em PARADA (padrão: 1000 CPH)")
    parser.add_argument("--online", action="store_true", help="Executar em modo streaming/online monitorando arquivo CSV local")
    parser.add_argument("--intervalo", "--tempo-atualizacao", dest="intervalo", type=float, default=None, help="Tempo de atualização em segundos para varredura do modo online (padrão: 5.0s)")

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
    parser.add_argument("--janela", default=None, help="Janela de histórico inicial (ex: 2h, 4h, 8h, 24h; padrão: 24h)")
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

    trava_filtro = args.trava if args.trava is not None else extrair_campo(fontes_proc, "trava_filtro", padrao="1")
    janela = args.janela or extrair_campo(fontes_proc, "janela_historico", "janela", padrao="24h")

    intervalo_padrao = float(extrair_campo(
        fontes_proc,
        "tempo_atualizacao_segundos",
        "tempo_atualizacao",
        "intervalo_varredura_segundos",
        "intervalo_segundos",
        "intervalo",
        padrao=5.0
    ))
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
    lim_parada_cfg = float(extrair_campo(fontes_proc, "velocidade_parada_cph", "limiar_parada_cph", "velocidade_parada", padrao=1000.0))
    lim_parada = float(args.velocidade_parada) if args.velocidade_parada is not None else lim_parada_cfg
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
        "velocidade_parada_cph": lim_parada,
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
                        df_recente = cliente.buscar_dados(tempo_inicio_str="-1h")
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
        executar_modo_online(caminho_csv, trava_filtro=trava_filtro, intervalo_s=intervalo if args.intervalo is not None else 2.0, caminho_sem=csv_sem, lim_parada=lim_parada)
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

    df_principal = _normalizar_df_telemetria(carregar_dados(caminho_csv))
    if df_principal is None or df_principal.empty:
        return

    # Aplicar filtro de trava se especificado
    col_t = cfg_colunas_resolvido.get("coluna_trava_entrada")
    if not col_t or col_t not in df_principal.columns:
        col_t = obter_coluna_trava(df_principal)
    df_analise = filtrar_trava(df_principal, trava_filtro, col_t) if _trava_eh_restritiva(trava_filtro) else df_principal
    dt_padrao_batch = _estimar_cadencia_segundos(df_principal)

    def _exibir_hora_atual_batch(df_base_b, df_sem_ext=None):
        janelas_b = _recortar_janelas_temporais(
            df_base_b, ts_referencia=_obter_ts_max(df_principal), col_en=col_en, df_geral=df_principal
        )
        _, df_sem_hist = filtrar_on_off(df_base_b, col_en=col_en)
        df_sem_ref = df_sem_ext
        if df_sem_ref is None and df_sem_hist is not None and len(df_sem_hist) > 0:
            df_sem_ref = df_sem_hist

        if len(janelas_b["df_hora_atual"]) > 0:
            res_h = _calcular_resumo_janela(
                janelas_b["df_hora_atual"],
                col_v=col_v, col_sp=col_sp, col_sem=col_sem, col_en=col_en,
                col_b_in=col_b_in, col_b_out=col_b_out,
                lim_rastejo=lim_rastejo, lim_b_out=lim_b_out, lim_b_in=lim_b_in,
                h_turno=h_turno, df_sem_externo=df_sem_ref, dt_padrao_s=dt_padrao_batch, lim_parada=lim_parada
            )
            exibir_relatorio_hora_atual(
                res_h,
                rotulo_hora=janelas_b["rotulo_hora"],
                intervalo_hora=janelas_b["intervalo_hora"],
                trava_filtro=trava_filtro
            )

        df_pos_b = janelas_b["df_pos_ligado"]
        if len(df_pos_b) > 0:
            hora_lig = janelas_b["hora_ligada"]
            int_lig = janelas_b["intervalo_ligado"]
            detalhe_lig = f"DESDE {hora_lig} | {int_lig}" if hora_lig else f"{len(df_pos_b)} amostras"
            tit_lig = f"🟢 DA HORA LIGADA PARA FRENTE ({detalhe_lig})"
            res_pos = _calcular_resumo_janela(
                df_pos_b,
                col_v=col_v, col_sp=col_sp, col_sem=col_sem, col_en=col_en,
                col_b_in=col_b_in, col_b_out=col_b_out,
                lim_rastejo=lim_rastejo, lim_b_out=lim_b_out, lim_b_in=lim_b_in,
                h_turno=h_turno, df_sem_externo=df_sem_ref, dt_padrao_s=dt_padrao_batch, lim_parada=lim_parada
            )
            if res_pos and res_pos["metricas_ab"]:
                if _trava_eh_restritiva(trava_filtro):
                    tit_lig += f" [{_descrever_filtro_trava(trava_filtro, maiusculo=True)}]"
                exibir_relatorio(res_pos["metricas_ab"], titulo=tit_lig)
            else:
                _exibir_quadro_janela(tit_lig, res_pos, trava_filtro=trava_filtro)

    def _auditar_batch(df_sem_ext=None):
        exibir_resumo_auditoria_analise(
            df_acumulado=df_principal,
            trava_filtro=trava_filtro,
            col_tr=col_t,
            col_v=col_v,
            col_en=col_en,
            col_sp=col_sp,
            col_sem_cfg=col_sem,
            col_b_in=col_b_in,
            col_b_out=col_b_out,
            lim_parada=lim_parada,
            lim_rastejo=lim_rastejo,
            h_turno=h_turno,
            df_sem_externo=df_sem_ext,
            dt_padrao_s=dt_padrao_batch,
        )

    # Caso 1: Dois arquivos passados
    if args.csv_sem_controle:
        df_sem_raw = _normalizar_df_telemetria(carregar_dados(args.csv_sem_controle))
        if df_sem_raw is None or df_sem_raw.empty:
            return
        df_sem_raw = filtrar_trava(df_sem_raw, trava_filtro, col_t) if _trava_eh_restritiva(trava_filtro) else df_sem_raw
        _, df_sem = filtrar_on_off(df_sem_raw, col_en=col_en)
        if df_sem is None or len(df_sem) == 0:
            df_sem = df_sem_raw

        df_com, _ = filtrar_on_off(df_analise, col_en=col_en)
        if df_com is None or len(df_com) == 0:
            df_com = df_analise

        titulo = "RESUMO EXECUTIVO: GANHO REAL DO CONTROLE"
        if trava_filtro is not None:
            titulo += f" [{_descrever_filtro_trava(trava_filtro, maiusculo=True)}]"
        m = calcular_metricas(
            df_com, df_sem,
            col_velocidade=col_v, col_b_in=col_b_in, col_b_out=col_b_out,
            limiar_rastejo=lim_rastejo, limiar_b_out_gargalo=lim_b_out,
            limiar_b_in_min=lim_b_in, horas_turno=h_turno, dt_padrao_s=dt_padrao_batch,
            limiar_parada=lim_parada
        )
        if m:
            exibir_relatorio(m, titulo=titulo)
            _exibir_hora_atual_batch(df_analise, df_sem_ext=df_sem)
        _auditar_batch(df_sem_ext=df_sem)
        return

    # Caso 2: Um arquivo contendo ON e OFF
    df_com, df_sem = filtrar_on_off(df_analise, col_en=col_en)
    if df_com is not None and df_sem is not None and len(df_com) > 0 and len(df_sem) > 0:
        titulo = "RESUMO EXECUTIVO: GANHO REAL DO CONTROLE"
        if trava_filtro is not None:
            titulo += f" [{_descrever_filtro_trava(trava_filtro, maiusculo=True)}]"
        m = calcular_metricas(
            df_com, df_sem,
            col_velocidade=col_v, col_b_in=col_b_in, col_b_out=col_b_out,
            limiar_rastejo=lim_rastejo, limiar_b_out_gargalo=lim_b_out,
            limiar_b_in_min=lim_b_in, horas_turno=h_turno, dt_padrao_s=dt_padrao_batch,
            limiar_parada=lim_parada
        )
        if m:
            exibir_relatorio(m, titulo=titulo)
            _exibir_hora_atual_batch(df_analise)

        if not _trava_eh_restritiva(trava_filtro) and col_t is not None:
            df_com_t0 = filtrar_trava(df_com, 0, col_t)
            df_sem_t0 = filtrar_trava(df_sem, 0, col_t)
            if len(df_com_t0) > 0 and len(df_sem_t0) > 0:
                m_t0 = calcular_metricas(
                    df_com_t0, df_sem_t0,
                    col_velocidade=col_v, col_b_in=col_b_in, col_b_out=col_b_out,
                    limiar_rastejo=lim_rastejo, limiar_b_out_gargalo=lim_b_out,
                    limiar_b_in_min=lim_b_in, horas_turno=h_turno, dt_padrao_s=dt_padrao_batch,
                    limiar_parada=lim_parada
                )
                if m_t0:
                    exibir_relatorio(m_t0, titulo="AUDITORIA TÉCNICA: ISOLADO SOB FLUXO LIVRE (TRAVA ENTRADA == 0)")
        _auditar_batch()
        return

    # Caso 3: Arquivo contendo dados apenas de um modo (100% ON ou 100% OFF)
    if len(df_analise) > 0:
        res_unico = _calcular_resumo_janela(
            df_analise,
            col_v=col_v, col_sp=col_sp, col_sem=col_sem, col_en=col_en,
            col_b_in=col_b_in, col_b_out=col_b_out,
            lim_rastejo=lim_rastejo, lim_b_out=lim_b_out, lim_b_in=lim_b_in,
            h_turno=h_turno, dt_padrao_s=dt_padrao_batch, lim_parada=lim_parada
        )
        if res_unico and res_unico["metricas_unico"]:
            tit = "RESUMO EXECUTIVO: BALANÇO DE PRODUÇÃO"
            if trava_filtro is not None:
                tit += f" [{_descrever_filtro_trava(trava_filtro, maiusculo=True)}]"
            exibir_relatorio_modo_unico(res_unico["metricas_unico"], segue_on=res_unico["segue_on"], titulo=tit)
            _exibir_hora_atual_batch(df_analise)
            _auditar_batch()
            return

    _auditar_batch()
    print("⚠️ Este arquivo possui dados apenas de um modo de operação no filtro aplicado.")
    print(f'   Execute: .venv/bin/python medidor_ganho_controle/medir_ganho.py "{args.csv}" --csv-sem-controle "dados_sem_controle.csv"')


if __name__ == "__main__":
    main()
