#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Controlador de Velocidade Live via Grafana (Baseado no Otimizador CMA-ES)
Lê dados em tempo real do Grafana (últimos 5 minutos) a cada 30 segundos,
aplica os parâmetros ótimos do CMA-ES de 'parametros_cma_es.json'
e compara com a velocidade real atual para estimar o ganho de garrafas.
"""

import os
import sys
import time
import datetime
import requests
import json
import base64
import pandas as pd
import numpy as np

# =====================================================================
# CONFIGURAÇÃO DE ACESSO AO GRAFANA (Busca por padrão as credenciais)
# =====================================================================
GRAFANA_URL = "http://10.91.7.221:3000"
GRAFANA_USER = "admin"
GRAFANA_PASSWORD = "!ambev2021"
DATASOURCE_SELECTOR = "17"  # ID do InfluxDB no Grafana
BUCKET = "Segue"
MEASUREMENT = "502"

ARQUIVO_CONFIG = "config_colunas.json"
ARQUIVO_PARAMETROS = "parametros_cma_es.json"

# Estado interno da histerese para o Live
restricao_b1 = False
restricao_b2 = False
restricao_b3 = False
restricao_b4 = False

ganho_acumulado_garrafas = 0.0
tempo_ultimo_ciclo = None

def carregar_configuracao():
    """Carrega config_colunas.json da pasta atual."""
    if not os.path.exists(ARQUIVO_CONFIG):
        print(f"❌ Erro: Arquivo de configuração '{ARQUIVO_CONFIG}' não encontrado.")
        print("Certifique-se de estar executando a partir da pasta 'Otimizador_CMA'.")
        sys.exit(1)
    
    with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)

def carregar_parametros_otimos():
    """Carrega parametros_cma_es.json gerados pelo otimizador."""
    if not os.path.exists(ARQUIVO_PARAMETROS):
        print(f"⚠ Aviso: Arquivo de parâmetros otimizados '{ARQUIVO_PARAMETROS}' não encontrado.")
        print("Por favor, execute 'otimizador_cma_es.py' primeiro para gerar os parâmetros.")
        print("Usando valores padrão de fallback...")
        return {
            "Velocidade_Nominal_ECH": 45000.0,
            "gatilho_b1_falta_extrema": 40.0,
            "vel_ech_falta_extrema": 90.0,
            "gatilho_b2_falta_critica": 30.0,
            "vel_ech_falta_critica": 80.0,
            "gatilho_b3_acumulo_critico": 70.0,
            "vel_ech_acumulo_critico": 80.0,
            "gatilho_b4_acumulo_extremo": 70.0,
            "vel_ech_acumulo_extremo": 90.0
        }
    
    with open(ARQUIVO_PARAMETROS, "r", encoding="utf-8") as f:
        params = json.load(f)
        print(f"➔ Parâmetros do CMA-ES carregados com sucesso (Otimizados em: {params.get('data_otimizacao', 'N/A')}).")
        return params

def obter_dados_tempo_real(session, config, ds_uid):
    """Busca os dados dos buffers e velocidades dos últimos 5 minutos no Grafana."""
    # Mapeamento de colunas do config
    b1_col = config.get("Col_Buffer_Antes_Entrada")
    b2_col = config.get("Col_Buffer_Entrada")
    b3_col = config.get("Col_Buffer_Saida")
    b4_col = config.get("Col_Buffer_Pos_Saida")
    v_ech_col = config.get("COL_V_ECH", "speed_actual_cph_null_filler_1")

    # Monta filtros dinâmicos baseados no config
    fields = ["accumulation_percentage", "speed_actual_cph"]
    
    # Query Flux para os últimos 5 minutos
    flux_query = f'''from(bucket: "{BUCKET}")
  |> range(start: -5m, stop: now())
  |> filter(fn: (r) =>
      r._measurement == "{MEASUREMENT}" and
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

    ds_query_url = f"{GRAFANA_URL.rstrip('/')}/api/ds/query"
    
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    from_ms = int((now_dt - datetime.timedelta(minutes=5)).timestamp() * 1000)
    to_ms   = int(now_dt.timestamp()  * 1000)
    
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
                "maxDataPoints": 100,
                "intervalMs":    30000
            }
        ]
    }
    
    usr_pass = f"{GRAFANA_USER}:{GRAFANA_PASSWORD}".encode("utf-8")
    b64_val = base64.b64encode(usr_pass).decode("utf-8")
    
    ds_headers = {
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "Authorization": f"Basic {b64_val}"
    }

    try:
        response = session.post(
            ds_query_url,
            headers=ds_headers,
            params={"ds_type": "influxdb"},
            json=ds_payload,
            timeout=15
        )
        if response.status_code != 200:
            print(f"❌ Erro na chamada do Grafana (Status: {response.status_code}): {response.text[:300]}")
            return None

        data = response.json()
        results = data.get("results", {})
        if not results:
            return None
        
        result = next(iter(results.values()))
        frames = result.get("frames", [])
        if not frames:
            return None

        all_dfs = []
        for frame in frames:
            schema = frame.get("schema", {})
            f_data   = frame.get("data", {})
            fields_schema = schema.get("fields", [])
            values_data = f_data.get("values", [])

            if not fields_schema or not values_data or len(fields_schema) != len(values_data):
                continue

            df_data = {}
            for field, vals in zip(fields_schema, values_data):
                fname = field.get("name", "value")
                ftype = field.get("type", "")
                if ftype == "time":
                    df_data["Timestamp"] = pd.to_datetime(vals, unit="ms")
                else:
                    df_data[fname] = vals

            if "Timestamp" in df_data:
                all_dfs.append(pd.DataFrame(df_data))

        if not all_dfs:
            return None

        if len(all_dfs) == 1:
            df_res = all_dfs[0]
        else:
            df_res = all_dfs[0]
            for other in all_dfs[1:]:
                df_res = df_res.merge(other, on="Timestamp", how="outer")

        # Limpeza
        metadados = ["result", "table", "_measurement", "_start", "_stop"]
        df_res = df_res.drop(columns=[col for col in metadados if col in df_res.columns], errors="ignore")
        
        # Resolve nomes das colunas
        df_res = df_res.ffill().bfill()
        return df_res

    except Exception as e:
        print(f"❌ Exceção ao buscar dados: {e}")
        return None

def obter_ds_uid(session):
    """Busca o UID do datasource selecionado no Grafana."""
    usr_pass = f"{GRAFANA_USER}:{GRAFANA_PASSWORD}".encode("utf-8")
    b64_val = base64.b64encode(usr_pass).decode("utf-8")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Basic {b64_val}"
    }
    
    try:
        ds_url = f"{GRAFANA_URL.rstrip('/')}/api/datasources"
        res = session.get(ds_url, headers=headers, timeout=10)
        if res.status_code == 200:
            for ds in res.json():
                if str(ds.get("id")) == DATASOURCE_SELECTOR or ds.get("name").lower() == DATASOURCE_SELECTOR.lower():
                    return ds.get("uid")
            # Se não achou por seletor, retorna o primeiro do tipo influxdb
            for ds in res.json():
                if ds.get("type") == "influxdb":
                    return ds.get("uid")
    except Exception as e:
        print(f"❌ Erro ao descobrir UID do Datasource: {e}")
    return None

def calcular_velocidade_cma(b1, b2, b3, b4, params, config):
    """Aplica o algoritmo de controle de histerese baseado nos parâmetros ótimos do CMA-ES."""
    global restricao_b1, restricao_b2, restricao_b3, restricao_b4
    
    # Flags de ativação dos buffers
    has_b1 = b1 is not None
    has_b4 = b4 is not None

    vel_nominal = params["Velocidade_Nominal_ECH"]
    fator_sobremarcha = params.get("Fator_Sobremarcha", 1.0)
    velocidades_sugeridas = []

    # --- BUFFER B1 (Antes Entrada - DPL-UIP) ---
    if has_b1:
        gatilho_start = params["gatilho_b1_falta_extrema"]
        gatilho_clear = gatilho_start + 10.0
        vel_reduzida = params["vel_ech_falta_extrema"]

        if restricao_b1:
            if b1 > gatilho_clear:
                restricao_b1 = False
        else:
            if b1 < gatilho_start:
                restricao_b1 = True
        
        if restricao_b1:
            velocidades_sugeridas.append(vel_reduzida)

    # --- BUFFER B2 (Entrada - UIP-ECH) ---
    gatilho_start_b2 = params["gatilho_b2_falta_critica"]
    gatilho_clear_b2 = gatilho_start_b2 + 10.0
    vel_reduzida_b2 = params["vel_ech_falta_critica"]

    if restricao_b2:
        if b2 > gatilho_clear_b2:
            restricao_b2 = False
    else:
        if b2 < gatilho_start_b2:
            restricao_b2 = True

    if restricao_b2:
        velocidades_sugeridas.append(vel_reduzida_b2)

    # --- BUFFER B3 (Saída - ECH-PZ) ---
    gatilho_start_b3 = params["gatilho_b3_acumulo_critico"]
    gatilho_clear_b3 = gatilho_start_b3 - 10.0
    vel_reduzida_b3 = params["vel_ech_acumulo_critico"]

    if restricao_b3:
        if b3 < gatilho_clear_b3:
            restricao_b3 = False
    else:
        if b3 > gatilho_start_b3:
            restricao_b3 = True

    if restricao_b3:
        velocidades_sugeridas.append(vel_reduzida_b3)

    # --- BUFFER B4 (Pós Saída - PZ-EPC) ---
    if has_b4:
        gatilho_start_b4 = params["gatilho_b4_acumulo_extremo"]
        gatilho_clear_b4 = gatilho_start_b4 - 15.0
        vel_reduzida_b4 = params["vel_ech_acumulo_extremo"]

        if restricao_b4:
            if b4 < gatilho_clear_b4:
                restricao_b4 = False
        else:
            if b4 > gatilho_start_b4:
                restricao_b4 = True

        if restricao_b4:
            velocidades_sugeridas.append(vel_reduzida_b4)

    # Decisão de Velocidade (Pega o gargalo)
    em_sprint = False
    if velocidades_sugeridas:
        fator_velocidade = min(velocidades_sugeridas) / 100.0
    else:
        fator_velocidade = 1.0  # 100% Base
        if fator_sobremarcha > 1.0:
            # Verifica condições de sprint (apenas 5% a mais de exigência que o 100%)
            condicao_b1 = (b1 > params["gatilho_b1_falta_extrema"] + 15.0) if has_b1 else True
            condicao_b2 = (b2 > params["gatilho_b2_falta_critica"] + 15.0)
            condicao_b3 = (b3 < params["gatilho_b3_acumulo_critico"] - 15.0)
            condicao_b4 = (b4 < params["gatilho_b4_acumulo_extremo"] - 20.0) if has_b4 else True
            
            if condicao_b1 and condicao_b2 and condicao_b3 and condicao_b4:
                fator_velocidade = fator_sobremarcha
                em_sprint = True

    velocidade_cph = vel_nominal * fator_velocidade
    return velocidade_cph, fator_velocidade * 100.0, em_sprint

def main():
    global ganho_acumulado_garrafas, tempo_ultimo_ciclo
    
    print("==================================================================")
    print("   CONTROLADOR LIVE CMA-ES (MODO SHADOW - ESTIMATIVA DE GANHOS)   ")
    print("==================================================================")
    
    config = carregar_configuracao()
    params = carregar_parametros_otimos()
    
    vel_atual_params = params.get('Velocidade_Nominal_ECH', 50000.0)
    vel_input = input(f"\n➔ Digite a Velocidade Nominal da Enchedora (CPH) para usar no Live [Enter para usar a do histórico: {vel_atual_params:.0f}]: ").strip()
    if vel_input:
        try:
            nova_vel = float(vel_input)
            params["Velocidade_Nominal_ECH"] = nova_vel
            print(f"➔ Velocidade Nominal definida para o Live: {nova_vel:.0f} CPH\n")
        except ValueError:
            print(f"⚠ Valor inválido. Mantendo a velocidade do histórico: {vel_atual_params:.0f} CPH\n")

    # Nomes das colunas reais nos DataFrames
    b1_col = config.get("Col_Buffer_Antes_Entrada")
    b2_col = config.get("Col_Buffer_Entrada")
    b3_col = config.get("Col_Buffer_Saida")
    b4_col = config.get("Col_Buffer_Pos_Saida")
    v_ech_col = config.get("COL_V_ECH", "speed_actual_cph_null_filler_1")

    session = requests.Session()
    
    print("➔ Conectando ao Grafana para descobrir UID do Datasource...")
    ds_uid = obter_ds_uid(session)
    if not ds_uid:
        print("❌ Não foi possível obter o UID do banco de dados no Grafana. Abortando.")
        sys.exit(1)
    print(f"➔ Conexão estabelecida. UID: {ds_uid}")
    print("➔ Iniciando monitoramento live a cada 30 segundos (Pressione Ctrl+C para parar)...\n")

    while True:
        try:
            ciclo_inicio = time.time()
            df = obter_dados_tempo_real(session, config, ds_uid)
            
            if df is not None and not df.empty:
                # Pega a linha mais recente (tempo real)
                last_row = df.iloc[-1]
                timestamp_real = last_row.get("Timestamp", datetime.datetime.now())
                
                # Resolução de valores das colunas
                b1_val = float(last_row[b1_col]) if (b1_col and b1_col in last_row) else None
                b2_val = float(last_row[b2_col]) if (b2_col and b2_col in last_row) else 0.0
                b3_val = float(last_row[b3_col]) if (b3_col and b3_col in last_row) else 0.0
                b4_val = float(last_row[b4_col]) if (b4_col and b4_col in last_row) else None
                
                # Velocidade atual da ECH
                v_real_ech = float(last_row[v_ech_col]) if (v_ech_col and v_ech_col in last_row) else 0.0
                
                # Calcula a velocidade que o CMA-ES sugere
                v_cma, pct_cma, em_sprint = calcular_velocidade_cma(b1_val, b2_val, b3_val, b4_val, params, config)
                
                # Cálculo de ganho/perda de produção no período
                # O período padrão é 30 segundos (0.5 minutos)
                segundos_decorridos = 30.0
                if tempo_ultimo_ciclo is not None:
                    segundos_decorridos = time.time() - tempo_ultimo_ciclo
                tempo_ultimo_ciclo = time.time()
                
                minutos_decorridos = segundos_decorridos / 60.0
                
                # Diferença de velocidade recomendada vs real (CPH)
                diferenca_cph = v_cma - v_real_ech
                
                # Ganho nesse ciclo só é contabilizado se a máquina estiver rodando na vida real
                if v_real_ech > 0:
                    ganho_ciclo = diferenca_cph * (segundos_decorridos / 3600.0)
                    ganho_acumulado_garrafas += ganho_ciclo
                else:
                    ganho_ciclo = 0.0
                
                # Imprime painel de monitoramento no console
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] --- Atualização via Grafana ---")
                
                # Mostra níveis dos buffers
                b1_str = f"B1 (DPL-UIP): {b1_val:.1f}% | " if b1_val is not None else ""
                b4_str = f"B4 (PZ-EPC): {b4_val:.1f}% | " if b4_val is not None else ""
                print(f"📊 Buffers: {b1_str}B2 (UIP-ECH): {b2_val:.1f}% | B3 (ECH-PZ): {b3_val:.1f}% | {b4_str}")
                
                # Mostra velocidades
                print(f"⚡ Velocidade ECH Real     : {int(v_real_ech):<5} CPH")
                print(f"🤖 Velocidade Sugerida CMA : {int(v_cma):<5} CPH ({pct_cma:.1f}%)")
                
                # Avisos de Restrições Ativas
                restricoes = []
                if restricao_b1: restricoes.append("Falta B1 (Crítico)")
                if restricao_b2: restricoes.append("Falta B2 (Crítico)")
                if restricao_b3: restricoes.append("Acúmulo B3 (Crítico)")
                if restricao_b4: restricoes.append("Acúmulo B4 (Crítico)")
                
                if restricoes:
                    print(f"⚠  Restrições CMA Ativas  : {', '.join(restricoes)}")
                else:
                    if em_sprint:
                        print(f"🚀 SPRINT ATIVO           : ECH em Sobremarcha Segura ({pct_cma:.1f}%)")
                    else:
                        print(f"🟢 Linha em Faixa Segura  : ECH em Velocidade Máxima")
                
                # Mostra Projeções de Ganho
                if v_cma > v_real_ech:
                    print(f"📈 Oportunidade de Ganho  : +{int(diferenca_cph)} CPH (+{int(ganho_ciclo)} garrafas neste ciclo)")
                elif v_cma < v_real_ech:
                    print(f"📉 Recomendação CMA-ES    : CMA-ES reduziria {int(v_real_ech - v_cma)} CPH para proteger buffers e evitar paradas futuras.")
                else:
                    print(f"✅ Status                 : Alinhado com a velocidade ótima do CMA-ES.")
                
                sinal_ganho = "+" if ganho_acumulado_garrafas >= 0 else ""
                print(f"🏆 GANHO DE PRODUTIVIDADE ACUMULADO (Shadow Mode): {sinal_ganho}{int(ganho_acumulado_garrafas)} garrafas")
                print("-" * 66)
            else:
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ⚠ Nenhum dado novo recebido do Grafana. Tentando novamente no próximo ciclo...")
            
        except Exception as e:
            print(f"⚠ Erro no ciclo de execução: {e}")
            
        # Aguarda completar os 30 segundos
        decorrido = time.time() - ciclo_inicio
        tempo_espera = max(1.0, 30.0 - decorrido)
        time.sleep(tempo_espera)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Execução do Controlador Live encerrada pelo usuário.")
        sys.exit(0)
