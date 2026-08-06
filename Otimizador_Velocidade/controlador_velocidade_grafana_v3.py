#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Controlador de Velocidade Live via Grafana (V3)
Lê dados diretamente do Grafana a cada 30 segundos usando as credenciais configuradas.
"""

import time
import datetime
import requests
import json
import base64
import pandas as pd
import sys
import os

# =====================================================================
# CONFIGURAÇÃO DE ACESSO AO GRAFANA
# =====================================================================
GRAFANA_URL = "http://172.23.224.145:3000"
GRAFANA_USER = "admin"
GRAFANA_PASSWORD = "!ambev2021"
GRAFANA_TOKEN = ""
DATASOURCE_SELECTOR = "13"
BUCKET = "Segue"
MEASUREMENT = "NS-512"

def rampa_trapezoidal(x, a, b, c, d):
    """Calcula o fator de transicao [0, 1]."""
    if x <= a or x >= d: return 0.0
    if a < x <= b: return (x - a) / (b - a) if b > a else 1.0
    if b < x <= c: return 1.0
    if c < x < d: return (d - x) / (d - c) if d > c else 1.0
    return 0.0

class ControladorVelocidadeEnchedoraV3:
    def __init__(self, min_modulacao=0.607, max_modulacao=1.0):
        self.min_modulacao = min_modulacao
        self.max_modulacao = max_modulacao
        
        # Parâmetros hardcoded (raw) otimizados
        self.b1_lim = 13.68
        self.b2_lim = 32.62
        self.b3_lim = 50.67
        self.b4_lim = 71.26
        self.rampa_b2 = 37.87
        self.rampa_b3 = 34.75
        self.antecip_b1 = 10.11
        self.antecip_b4 = 35.00
        self.fator_reducao_otimizado = 0.607
        
        self.vel_maxima = self.max_modulacao * 100.0
        self.vel_reduzida = self.fator_reducao_otimizado * 100.0

    def calcular_velocidade(self, b1, b2, b3, b4):
        b2_baixo  = rampa_trapezoidal(b2, -1, 0, self.b2_lim - self.rampa_b2, self.b2_lim)
        b2_normal = rampa_trapezoidal(b2, self.b2_lim - self.rampa_b2, self.b2_lim, 100, 101)
        b3_normal = rampa_trapezoidal(b3, -1, 0, self.b3_lim, self.b3_lim + self.rampa_b3)
        b3_alto   = rampa_trapezoidal(b3, self.b3_lim, self.b3_lim + self.rampa_b3, 100, 101)
        
        b1_tendencia = rampa_trapezoidal(b1, -1, 0, self.b1_lim, self.b1_lim + self.antecip_b1)
        b4_tendencia = rampa_trapezoidal(b4, self.b4_lim - self.antecip_b4, self.b4_lim, 100, 101)

        w1 = b2_baixo
        w2 = b3_alto
        w4 = b1_tendencia
        w5 = b4_tendencia
        w3 = min(b2_normal, b3_normal)

        num = (w1 * self.vel_reduzida) + (w2 * self.vel_reduzida) + (w4 * self.vel_reduzida) + (w5 * self.vel_reduzida) + (w3 * self.vel_maxima)
        den = w1 + w2 + w3 + w4 + w5

        v_base = self.vel_maxima if den == 0 else num / den
        v_final_perc = max(v_base, self.vel_reduzida)
        return round(v_final_perc, 1)

def obter_ds_uid(session, headers):
    ds_url = f"{GRAFANA_URL.rstrip('/')}/api/datasources"
    ds_response = session.get(ds_url, headers=headers, timeout=10)
    if ds_response.status_code == 200:
        ds_list = ds_response.json()
        influx_ds = [ds for ds in ds_list if ds.get("type") == "influxdb"]
        for ds in influx_ds:
            if str(ds.get("id")) == DATASOURCE_SELECTOR or ds.get("name").lower() == DATASOURCE_SELECTOR.lower():
                return ds.get("uid")
        if influx_ds:
            return influx_ds[0].get("uid")
    return None

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

def resolver_coluna(valor, default, opcional=False):
    if not valor or valor.strip() == "":
        return None if opcional else default
    return valor

def main():
    print("="*60)
    print("   SIMULADOR DE VELOCIDADE LIVE GRAFANA (V3)")
    print("="*60)
    
    # Valores padrão
    COL_B1_DPL_UIP = "accumulation_percentage_lgf_to_uip_null"
    COL_B2_UIP_ECH = "accumulation_percentage_uip_to_ech_null"
    COL_B3_ECH_PZ  = "accumulation_percentage_ech_to_pz_null"
    COL_B4_PZ_EPC  = "accumulation_percentage_pz_to_rot_null"
    COL_V_ECH      = "speed_actual_cph_null_filler_1"
    VELOCIDADE_NOMINAL_ECH = 63360.0

    if os.path.exists("config_colunas.json"):
        try:
            with open("config_colunas.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
                COL_B1_DPL_UIP = cfg.get("Col_Buffer_Antes_Entrada", COL_B1_DPL_UIP)
                COL_B2_UIP_ECH = cfg.get("Col_Buffer_Entrada", COL_B2_UIP_ECH)
                COL_B3_ECH_PZ  = cfg.get("Col_Buffer_Saida", COL_B3_ECH_PZ)
                COL_B4_PZ_EPC  = cfg.get("Col_Buffer_Pos_Saida", COL_B4_PZ_EPC)
                COL_V_ECH      = cfg.get("COL_V_ECH", COL_V_ECH)
                
                val_nominal = cfg.get("Velocidade_Nominal_ECH", None)
                if val_nominal is not None:
                    VELOCIDADE_NOMINAL_ECH = float(val_nominal)
        except Exception as e:
            print(f"⚠️ Erro ao ler 'config_colunas.json': {e}. Usando defaults.")

    COL_B1_DPL_UIP = resolver_coluna(COL_B1_DPL_UIP, "", opcional=True)
    COL_B2_UIP_ECH = resolver_coluna(COL_B2_UIP_ECH, "", opcional=False)
    COL_B3_ECH_PZ  = resolver_coluna(COL_B3_ECH_PZ, "", opcional=False)
    COL_B4_PZ_EPC  = resolver_coluna(COL_B4_PZ_EPC, "", opcional=True)
    COL_V_ECH      = resolver_coluna(COL_V_ECH, "", opcional=True)
    
    print(f"Colunas monitoradas:")
    print(f"  B1: {COL_B1_DPL_UIP if COL_B1_DPL_UIP else '(Não configurada)'}")
    print(f"  B2: {COL_B2_UIP_ECH}")
    print(f"  B3: {COL_B3_ECH_PZ}")
    print(f"  B4: {COL_B4_PZ_EPC if COL_B4_PZ_EPC else '(Não configurada)'}")
    print(f"  Velocidade Atual: {COL_V_ECH}")
    print(f"  Velocidade Nominal: {int(VELOCIDADE_NOMINAL_ECH)} CPH")
    print("-" * 60)
    print(f"Conectando ao Grafana em: {GRAFANA_URL} a cada 30 segundos...\n")

    # Auth
    session = requests.Session()
    usr_pass = f"{GRAFANA_USER}:{GRAFANA_PASSWORD}".encode("utf-8")
    b64_val = base64.b64encode(usr_pass).decode("utf-8")
    basic_auth_header = f"Basic {b64_val}"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": basic_auth_header
    }
    
    ds_uid = obter_ds_uid(session, headers)
    if not ds_uid:
        print("❌ Erro: Não foi possível obter UID do Datasource.")
        sys.exit(1)
        
    ds_query_url = f"{GRAFANA_URL.rstrip('/')}/api/ds/query"
    
    controlador = ControladorVelocidadeEnchedoraV3()
    
    while True:
        agora = datetime.datetime.now(datetime.timezone.utc)
        # Buscar na janela longa, mas validaremos o timestamp exato do último registro retornado
        t_start = agora - datetime.timedelta(days=30)
        t_stop = agora
        
        from_ms = int(t_start.timestamp() * 1000)
        to_ms   = int(t_stop.timestamp()  * 1000)
        
        t_start_str = t_start.strftime('%Y-%m-%dT%H:%M:%SZ')
        t_stop_str = t_stop.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Extrair os nomes dos buffers para o filtro Flux
        buffer_filters = []
        for col in [COL_B1_DPL_UIP, COL_B2_UIP_ECH, COL_B3_ECH_PZ, COL_B4_PZ_EPC]:
            if col:
                b_name = col.replace("accumulation_percentage_", "").replace("_null", "")
                buffer_filters.append(f'r["buffer_name_local"] == "{b_name}"')
        
        filter_buffers = ""
        if buffer_filters:
            filter_buffers = " and (" + " or ".join(buffer_filters) + ")"
            
        # Filtro consolidado (buffers + velocidade)
        filter_str = f'''(
          (r["_field"] == "accumulation_percentage"{filter_buffers}) or
          (r["_field"] == "speed_actual_cph")
        )'''
        
        flux_query = f'''from(bucket: "{BUCKET}")
  |> range(start: {t_start_str}, stop: {t_stop_str})
  |> filter(fn: (r) =>
      r["_measurement"] == "{MEASUREMENT}" and
      {filter_str}
  )
  |> last()
  |> map(fn: (r) => ({{
      r with _value: float(v: r._value)
  }}))
  |> group()
  |> pivot(
      rowKey: ["_measurement", "_time"],
      columnKey: ["_field", "buffer_name_local", "machine_name_generic"],
      valueColumn: "_value"
  )'''

        ds_payload = {
            "from": str(from_ms),
            "to":   str(to_ms),
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

        try:
            response = session.post(ds_query_url, headers=headers, json=ds_payload, timeout=20)
            if response.status_code == 200:
                df = parse_grafana_ds_response(response.json())
                if not df.empty:
                    # O Flux retorna timestamps diferentes para cada sensor, criando linhas separadas com NaNs.
                    # ffill() preenche esses NaNs para a frente, mesclando tudo na última linha.
                    linha = df.ffill().iloc[-1]
                    
                    # A pivotação do Flux com 3 chaves pode criar colunas como:
                    # accumulation_percentage_uip_to_ech_null
                    # speed_actual_cph_null_filler_1
                    # Vamos encontrar as colunas dinamicamente verificando se o nome contem as partes
                    
                    def find_col_val(df_line, target_col):
                        if not target_col: return None
                        # Tenta exato
                        if target_col in df_line: return df_line[target_col]
                        # Remove _null do target e procura parcial
                        target_clean = target_col.replace("_null", "")
                        for col_name in df_line.index:
                            if target_clean in str(col_name):
                                return df_line[col_name]
                        return None

                    b1 = find_col_val(linha, COL_B1_DPL_UIP) if COL_B1_DPL_UIP else 50.0
                    b2 = find_col_val(linha, COL_B2_UIP_ECH)
                    b3 = find_col_val(linha, COL_B3_ECH_PZ)
                    b4 = find_col_val(linha, COL_B4_PZ_EPC) if COL_B4_PZ_EPC else 50.0
                    
                    vel_atual = 0.0
                    if COL_V_ECH and not COL_V_ECH.isdigit():
                        v_val = find_col_val(linha, COL_V_ECH)
                        if pd.notna(v_val): vel_atual = float(v_val)
                    
                    if b2 is None or pd.isna(b2): b2 = 50.0
                    if b3 is None or pd.isna(b3): b3 = 50.0
                    if b1 is None or pd.isna(b1): b1 = 50.0
                    if b4 is None or pd.isna(b4): b4 = 50.0
                    
                    data_timestamp = linha.get("Timestamp")
                    delay_seconds = 0
                    if pd.notna(data_timestamp):
                        agora_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                        delay_seconds = (agora_utc - data_timestamp).total_seconds()
                    
                    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{timestamp_str}] Leituras: B1={b1:.1f}% | B2={b2:.1f}% | B3={b3:.1f}% | B4={b4:.1f}%")
                    print(f"   ➔ Velocidade Real Atual: {int(vel_atual)} CPH")
                    
                    # Trava de Segurança: Dados mais antigos que 5 minutos
                    if delay_seconds > 300:
                        vel = 0.0
                        cph_sugerido = 0
                        print(f"   ➔ AVISO: DADOS OBSOLETOS! Atraso de {delay_seconds:.0f}s detectado.")
                        print(f"   ➔ SETPOINT OTIMIZADO: {vel}% ({cph_sugerido} CPH) 🚨 PARADA DE SEGURANÇA 🚨")
                    else:
                        vel = controlador.calcular_velocidade(b1, b2, b3, b4)
                        cph_sugerido = int((vel / 100.0) * VELOCIDADE_NOMINAL_ECH)
                        
                        if vel == 0.0:
                            print(f"   ➔ SETPOINT OTIMIZADO: {vel}% ({cph_sugerido} CPH) 🚨 PARADA DE SEGURANÇA 🚨")
                        elif vel < 100.0:
                            print(f"   ➔ SETPOINT OTIMIZADO: {vel}% ({cph_sugerido} CPH) ⚠️ MODULAÇÃO ATIVA")
                        else:
                            print(f"   ➔ SETPOINT OTIMIZADO: {vel}% ({cph_sugerido} CPH) ✅ MÁQUINA FULL")
                    print("-" * 60)
                else:
                    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Nenhum dado recente encontrado.")
            else:
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Erro na consulta Grafana: Status {response.status_code}")
        except Exception as e:
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Erro ao conectar no Grafana: {e}")
            
        try:
            time.sleep(30)
        except KeyboardInterrupt:
            print("\nSaindo do simulador live Grafana...")
            break

if __name__ == "__main__":
    main()
