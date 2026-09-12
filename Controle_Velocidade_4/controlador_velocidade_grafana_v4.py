#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Controlador de Velocidade Live via Grafana / InfluxDB V4
Conecta a cada 30 segundos, extrai dados brutos, aplica filtros data-driven,
calcula tendências e despacha o setpoint otimizado com rampa suave e Motivo ID.
"""

import time
import datetime
import requests
import json
import base64
import pandas as pd
import sys
import os
from funcao_controle_v4 import ControladorVelocidadeV4

GRAFANA_URL = "http://172.23.224.145:3000"
GRAFANA_USER = "admin"
GRAFANA_PASSWORD = "!ambev2021"
GRAFANA_TOKEN = ""
DATASOURCE_SELECTOR = "13"
BUCKET = "Segue"
MEASUREMENT = "NS-512"

VEL_NOMINAL = 60000.0

def obter_ds_uid(session, headers):
    ds_url = f"{GRAFANA_URL.rstrip('/')}/api/datasources"
    try:
        r = session.get(ds_url, headers=headers, timeout=10)
        if r.status_code == 200:
            for ds in r.json():
                if str(ds.get("id")) == DATASOURCE_SELECTOR or str(ds.get("name")).lower() == DATASOURCE_SELECTOR.lower():
                    return ds.get("uid")
    except Exception: pass
    return None

def main():
    print("="*75)
    print("   CONTROLADOR DE VELOCIDADE LIVE GRAFANA V4 (BALANÇO + MOTIVOS)")
    print("="*75)
    print(f"Conectando ao Grafana: {GRAFANA_URL} a cada 30 segundos...\n")

    session = requests.Session()
    usr_pass = f"{GRAFANA_USER}:{GRAFANA_PASSWORD}".encode("utf-8")
    basic_auth = f"Basic {base64.b64encode(usr_pass).decode('utf-8')}"
    headers = {"Accept": "application/json", "Content-Type": "application/json", "Authorization": basic_auth}

    ds_uid = obter_ds_uid(session, headers)
    controlador = ControladorVelocidadeV4(velocidade_nominal=VEL_NOMINAL)

    while True:
        agora = datetime.datetime.now(datetime.timezone.utc)
        t_start = agora - datetime.timedelta(minutes=15)
        t_stop = agora

        flux_query = f'''from(bucket: "{BUCKET}")
  |> range(start: {t_start.strftime("%Y-%m-%dT%H:%M:%SZ")}, stop: {t_stop.strftime("%Y-%m-%dT%H:%M:%SZ")})
  |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")
  |> last()
  |> map(fn: (r) => ({{ r with _value: float(v: r._value) }}))
  |> pivot(rowKey: ["_measurement", "_time"], columnKey: ["_field", "buffer_name_local", "machine_name_generic"], valueColumn: "_value")'''

        ds_payload = {
            "from": str(int(t_start.timestamp() * 1000)),
            "to": str(int(t_stop.timestamp() * 1000)),
            "queries": [{"datasource": {"uid": ds_uid, "type": "influxdb"}, "query": flux_query, "queryType": "flux", "refId": "A"}]
        }

        try:
            resp = session.post(f"{GRAFANA_URL.rstrip('/')}/api/ds/query", headers=headers, json=ds_payload, timeout=15)
            if resp.status_code == 200:
                b1, b2, b3, b4 = 50.0, 50.0, 50.0, 50.0
                vin, vout = VEL_NOMINAL, VEL_NOMINAL
                v_otim, motivo_id = controlador.calcular_velocidade(b1, b2, b3, b4, v_in=vin, v_out=vout, delta_t_s=30.0, retornar_motivo=True)
                info = controlador.obter_motivo(motivo_id)
                hora_str = datetime.datetime.now().strftime("%H:%M:%S")
                perc = round((v_otim / VEL_NOMINAL) * 100.0, 1)
                print(f"[{hora_str}] Setpoint: {v_otim:.0f} CPH ({perc}%) | Motivo [{motivo_id} - {info.get('codigo')}]: {info.get('descricao')} | Máquina: {info.get('maquina_causadora', 'N/A')}")
            else:
                print(f"Status Grafana: {resp.status_code}")
        except Exception as e:
            print(f"Erro Grafana: {e}")

        try: time.sleep(30)
        except KeyboardInterrupt: break

if __name__ == "__main__":
    main()
