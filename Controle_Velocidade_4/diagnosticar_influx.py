#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Diagnóstico de Conexão com InfluxDB - Controlador V4
Testa todas as rotas possíveis (localhost, docker, rede fabril),
verifica se o serviço InfluxDB responde ao /ping e se aceita escrita na base 'Segue'.
"""

import os
import sys
import json
import requests

DIR_ATUAL = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(DIR_ATUAL, "config_opc_v4.json")


def diagnosticar():
    print("=" * 75)
    print(" 🔍 DIAGNÓSTICO DE CONEXÃO COM O INFLUXDB (TELEMETRIA V4)")
    print("=" * 75)

    cfg_telemetria = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg_telemetria = data.get("telemetria_influx", data.get("telemetria_grafana", {}))
                print(f"📄 Arquivo config_opc_v4.json carregado com sucesso.")
        except Exception as e:
            print(f"⚠️ Erro ao ler config_opc_v4.json: {e}")
    else:
        print(f"⚠️ Arquivo config_opc_v4.json não encontrado em: {CONFIG_PATH}")

    influx_url_cfg = cfg_telemetria.get("influx_url", "http://localhost:8086")
    database_cfg = cfg_telemetria.get("database", "Segue")
    print(f"🎯 URL configurada: {influx_url_cfg}")
    print(f"📦 Database / Bucket: {database_cfg}\n")

    candidatos = [
        influx_url_cfg,
        "http://localhost:8086",
        "http://localhost:8089",
        "http://127.0.0.1:8086",
        "http://127.0.0.1:8089",
        "http://segue-influxdb:8086",
        "http://host.docker.internal:8086",
        "http://10.91.7.221:8086",
        "http://10.46.12.163:8086"
    ]
    vistos = set()
    urls_testar = []
    for u in candidatos:
        u_limpa = u.rstrip("/")
        if u_limpa not in vistos:
            vistos.add(u_limpa)
            urls_testar.append(u_limpa)

    print("--- 1. Testando conectividade de rede e ping no serviço ---")
    servidores_online = []
    for u in urls_testar:
        ping_url = f"{u}/ping"
        try:
            r = requests.get(ping_url, timeout=1.5)
            versao = r.headers.get("X-Influxdb-Version", r.headers.get("X-Influxdb-Build", "Detectado"))
            print(f" ✅ [ONLINE] {u} -> Status HTTP {r.status_code} (Versão: {versao})")
            servidores_online.append(u)
        except requests.exceptions.ConnectionError as e:
            err_str = str(e)
            if "Connection refused" in err_str or "Errno 111" in err_str:
                print(f" ❌ [FECHADO] {u} -> Conexão recusada (Nenhum serviço escutando nesta porta)")
            elif "Name or service not known" in err_str or "nodename nor servname" in err_str:
                print(f" ❌ [DNS]     {u} -> Hostname não resolvido")
            else:
                print(f" ❌ [FALHA]   {u} -> Erro de conexão: {type(e).__name__}")
        except requests.exceptions.Timeout:
            print(f" ⏳ [TIMEOUT] {u} -> Não respondeu em 1.5s")
        except Exception as e:
            print(f" ❌ [ERRO]    {u} -> {e}")

    print("\n--- 2. Testando gravação (Line Protocol) nos servidores online ---")
    if not servidores_online:
        print("⚠️  Nenhum servidor InfluxDB foi encontrado respondendo nas URLs testadas.")
        print("\n💡 DIAGNÓSTICO DO MOTIVO DE NÃO FUNCIONAR:")
        print(" 1. O InfluxDB NÃO está rodando nesta máquina/porta 8086.")
        print("    Para iniciar o InfluxDB via Docker:")
        print("       cd /home/antonio/Projetos/OtimizadorSegue/Controle_Velocidade_4")
        print("       docker compose -f docker-compose.segue-completo.yml up -d segue-influxdb")
        print(" 2. Se o controlador roda dentro de um container Docker:")
        print("    'localhost' dentro do container não enxerga a porta da máquina host, a menos que use:")
        print("       --network host")
        print(" 3. Se o InfluxDB está em outro IP/servidor da fábrica:")
        print("    Altere 'influx_url' no config_opc_v4.json para o IP correto (ex: http://IP_DO_SERVIDOR:8086).")
    else:
        for u in servidores_online:
            write_url = f"{u}/write?db={database_cfg}&precision=s"
            corpo_teste = f"teste_diagnostico,linha=512 status=\"OK\",valor=1i"
            try:
                r = requests.post(write_url, data=corpo_teste.encode("utf-8"), timeout=2.0)
                if r.status_code in [200, 204]:
                    print(f" 🎉 [SUCESSO DE ESCRITA] {u}: Ponto gravado no database '{database_cfg}' com sucesso!")
                elif r.status_code == 404:
                    print(f" ⚠️ [BANCO NÃO ENCONTRADO] {u}: HTTP 404. O database '{database_cfg}' não existe.")
                    print(f"    Crie o banco executando: influx -execute 'CREATE DATABASE {database_cfg}'")
                elif r.status_code in [401, 403]:
                    print(f" 🔒 [AUTENTICAÇÃO EXIGIDA] {u}: HTTP {r.status_code}. O InfluxDB exige credenciais.")
                else:
                    print(f" ⚠️ [RESPOSTA HTTP {r.status_code}] {u}: {r.text[:80]}")
            except Exception as e:
                print(f" ❌ Falha ao tentar gravar em {u}: {e}")

    print("=" * 75 + "\n")


if __name__ == "__main__":
    diagnosticar()
