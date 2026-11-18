#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Conexão e Coleta Online via Grafana / InfluxDB API
Utiliza exatamente a mesma lógica de conexão e autenticação do obter_dados_grafana.py:
- requests.Session com trust_env=False (evita timeouts por proxy de sistema)
- Suporte a Bearer Token (Service Account), API Key temporária e Basic Auth
- Auto-descoberta dinâmica de Datasources InfluxDB (/api/datasources)
- Suporte a queries Flux (/api/ds/query) e InfluxQL (/api/datasources/proxy/<ds_id>/query)
"""

import os
import sys
import base64
import datetime
import requests
import pandas as pd
from typing import Optional, Tuple, Dict, Any


class ClienteGrafana:
    """Cliente para extração contínua de telemetria diretamente da API do Grafana."""

    def __init__(
        self,
        url: str = "http://10.91.7.221:3000",
        user: str = "admin",
        password: str = "!ambev2021",
        token: str = "",
        ds_selector: str = "17",
        bucket: str = "Segue",
        measurement: str = "512",
        org: str = "ABinbev",
        timeout: int = 15,
        query_template: Optional[str] = None
    ):
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"http://{url}"
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self.token = token
        self.ds_selector = str(ds_selector).strip()
        self.bucket = bucket
        self.measurement = measurement
        self.org = org
        self.timeout = timeout
        self.query_template = query_template

        self.session = requests.Session()
        self.session.trust_env = False

        self.bearer_token: Optional[str] = token if token else None
        self.basic_auth_header: str = ""
        self.api_key_id: Optional[int] = None
        self.ds_id: Optional[int] = None
        self.ds_uid: Optional[str] = None
        self.headers: Dict[str, str] = {}
        self.conectado: bool = False

    def conectar(self) -> bool:
        """Autentica e detecta o Datasource InfluxDB no Grafana."""
        if not (self.user and self.password) and not self.token:
            print("❌ Erro: Forneça usuário/senha ou token do Grafana.")
            return False

        usr_pass = f"{self.user}:{self.password}".encode("utf-8") if (self.user and self.password) else b""
        b64_val = base64.b64encode(usr_pass).decode("utf-8") if usr_pass else ""
        self.basic_auth_header = f"Basic {b64_val}" if b64_val else ""

        # Prioridade de autenticação idêntica ao obter_dados_grafana.py
        if not self.bearer_token and self.basic_auth_header:
            api_key_name = "medidor-tmp-key"
            try:
                key_url = f"{self.url}/api/auth/keys"
                key_res = self.session.post(
                    key_url,
                    headers={"Authorization": self.basic_auth_header, "Content-Type": "application/json"},
                    json={"name": api_key_name, "role": "Viewer"},
                    timeout=self.timeout
                )
                if key_res.status_code == 200:
                    key_data = key_res.json()
                    self.bearer_token = key_data.get("key")
                    self.api_key_id = key_data.get("id")
                elif key_res.status_code == 409:
                    list_res = self.session.get(key_url, headers={"Authorization": self.basic_auth_header}, timeout=self.timeout)
                    if list_res.status_code == 200:
                        for k in list_res.json():
                            if k.get("name") == api_key_name:
                                self.session.delete(f"{key_url}/{k['id']}", headers={"Authorization": self.basic_auth_header}, timeout=self.timeout)
                                break
                    key_res2 = self.session.post(
                        key_url,
                        headers={"Authorization": self.basic_auth_header, "Content-Type": "application/json"},
                        json={"name": api_key_name, "role": "Viewer"},
                        timeout=self.timeout
                    )
                    if key_res2.status_code == 200:
                        key_data = key_res2.json()
                        self.bearer_token = key_data.get("key")
                        self.api_key_id = key_data.get("id")
            except Exception:
                pass

        self.headers = {
            "Accept": "application/json"
        }
        if self.bearer_token:
            self.headers["Authorization"] = f"Bearer {self.bearer_token}"
        elif self.basic_auth_header:
            self.headers["Authorization"] = self.basic_auth_header

        # Auto-descoberta de Datasource
        try:
            ds_url = f"{self.url}/api/datasources"
            ds_res = self.session.get(ds_url, headers=self.headers, timeout=self.timeout)
            if ds_res.status_code == 200:
                ds_list = ds_res.json()
                influx_ds = [ds for ds in ds_list if ds.get("type") == "influxdb"]
                if not influx_ds:
                    print("❌ Erro: Nenhuma fonte de dados do tipo 'influxdb' foi encontrada no Grafana.")
                    return False

                target_ds = None
                if self.ds_selector:
                    for ds in influx_ds:
                        if str(ds.get("id")) == self.ds_selector or ds.get("name", "").lower() == self.ds_selector.lower():
                            target_ds = ds
                            break
                if target_ds is None:
                    target_ds = influx_ds[0]

                self.ds_id = target_ds.get("id")
                self.ds_uid = target_ds.get("uid", "")
                ds_db = target_ds.get("database")
                if not self.bucket and ds_db:
                    self.bucket = ds_db

                self.conectado = True
                print(f"✅ Conectado ao Grafana ({self.url}) | Datasource: '{target_ds.get('name')}' (ID: {self.ds_id})")
                return True
            else:
                print(f"❌ Erro ao autenticar no Grafana (Status {ds_res.status_code}): {ds_res.text[:200]}")
                return False
        except Exception as e:
            print(f"❌ Falha de rede ao conectar ao Grafana em '{self.url}': {e}")
            return False

    def desconectar(self):
        """Limpa API Key temporária caso criada."""
        if self.api_key_id and self.basic_auth_header:
            try:
                del_url = f"{self.url}/api/auth/keys/{self.api_key_id}"
                self.session.delete(del_url, headers={"Authorization": self.basic_auth_header}, timeout=5)
            except Exception:
                pass

    def listar_todos_datasources(self) -> list:
        """Lista todas as fontes de dados cadastradas no Grafana."""
        if not self.conectado:
            if not self.conectar():
                return []
        try:
            ds_url = f"{self.url}/api/datasources"
            ds_res = self.session.get(ds_url, headers=self.headers, timeout=self.timeout)
            if ds_res.status_code == 200:
                return ds_res.json()
        except Exception:
            pass
        return []

    @staticmethod
    def _deduplicar_colunas(cols: list) -> list:
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

    @classmethod
    def _parsear_resposta_influxql(cls, data: dict) -> pd.DataFrame:
        """Converte resposta JSON InfluxQL em DataFrame padronizado com colunas únicas e ordenado por Time."""
        results = data.get("results", [])
        if not results or "series" not in results[0]:
            return pd.DataFrame()

        dfs = []
        for series in results[0].get("series", []):
            cols = series.get("columns", [])
            vals = series.get("values", [])
            if not cols or not vals:
                continue
            cols_unicas = cls._deduplicar_colunas(cols)
            df_s = pd.DataFrame(vals, columns=cols_unicas)
            if "time" in df_s.columns:
                df_s = df_s.rename(columns={"time": "Time"})
            # Inclui eventuais tags retornadas no cabeçalho da série caso ausentes nas colunas
            for tag_k, tag_v in (series.get("tags") or {}).items():
                if tag_k not in df_s.columns:
                    df_s[tag_k] = tag_v
            dfs.append(df_s)

        if not dfs:
            return pd.DataFrame()

        df = dfs[0] if len(dfs) == 1 else pd.concat(dfs, ignore_index=True)
        if "Time" in df.columns:
            df = df.drop_duplicates(subset=["Time"]).sort_values("Time").reset_index(drop=True)
        return df

    @classmethod
    def _parsear_resposta_ds_query(cls, data: dict) -> pd.DataFrame:
        """Converte resposta JSON do endpoint /api/ds/query (Data Frames do Grafana) em DataFrame."""
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
            nomes = cls._deduplicar_colunas([f.get("name", "valor") for f in fields])
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
        df = dfs[0] if len(dfs) == 1 else pd.concat(dfs, ignore_index=True)
        if "Time" in df.columns:
            df = df.drop_duplicates(subset=["Time"]).sort_values("Time").reset_index(drop=True)
        return df

    def _executar_query_influxql(self, query_sql: str, bucket: str) -> pd.DataFrame:
        """Executa consulta InfluxQL via proxy (POST e GET) com fallback para /api/ds/query."""
        proxy_url = f"{self.url}/api/datasources/proxy/{self.ds_id}/query"
        headers_post = dict(self.headers)
        headers_post["Content-Type"] = "application/x-www-form-urlencoded"
        headers_post["Accept"] = "application/json"
        params = {"db": bucket, "q": query_sql}

        # 1. Proxy InfluxQL via POST (data=params) e GET (params=params)
        for metodo in ("post", "get"):
            try:
                if metodo == "post":
                    res = self.session.post(proxy_url, headers=headers_post, data=params, timeout=self.timeout)
                else:
                    res = self.session.get(proxy_url, headers=self.headers, params=params, timeout=self.timeout)
                if res.status_code == 200:
                    df = self._parsear_resposta_influxql(res.json())
                    if not df.empty:
                        return df
            except Exception:
                pass

        # 2. Proxy por UID caso configurado (Grafana 8+)
        if self.ds_uid:
            uid_url = f"{self.url}/api/datasources/uid/{self.ds_uid}/resources/query"
            for metodo in ("post", "get"):
                try:
                    if metodo == "post":
                        res = self.session.post(uid_url, headers=headers_post, data=params, timeout=self.timeout)
                    else:
                        res = self.session.get(uid_url, headers=self.headers, params=params, timeout=self.timeout)
                    if res.status_code == 200:
                        df = self._parsear_resposta_influxql(res.json())
                        if not df.empty:
                            return df
                except Exception:
                    pass

        # 3. Fallback via API nativa /api/ds/query do Grafana
        try:
            ds_query_url = f"{self.url}/api/ds/query"
            ds_headers = dict(self.headers)
            ds_headers["Content-Type"] = "application/json"
            ds_headers["Accept"] = "application/json"
            ds_ref = {"uid": self.ds_uid} if self.ds_uid else {"id": self.ds_id}
            payload = {
                "from": "now-6h",
                "to": "now",
                "queries": [{
                    "datasource": {"type": "influxdb", **ds_ref},
                    "rawQuery": True,
                    "query": query_sql,
                    "refId": "A",
                    "resultFormat": "table"
                }]
            }
            res_ds = self.session.post(ds_query_url, headers=ds_headers, json=payload, timeout=self.timeout)
            if res_ds.status_code == 200:
                df = self._parsear_resposta_ds_query(res_ds.json())
                if not df.empty:
                    return df
        except Exception:
            pass

        return pd.DataFrame()

    def buscar_dados_recentes(self, limite: int = 50) -> pd.DataFrame:
        """
        Busca os N pontos mais recentes gravados na medição de forma imune a problemas de timezone/now().
        Retorna os dados ordenados cronologicamente (Time ASC).
        """
        if not self.conectado:
            if not self.conectar():
                return pd.DataFrame()

        meds_candidatas = [self.measurement]
        alt_med = self.measurement[:-3] if self.measurement.endswith("_v4") else f"{self.measurement}_v4"
        if alt_med not in meds_candidatas:
            meds_candidatas.append(alt_med)

        buckets_candidatos = [self.bucket]
        for b_alt in ["soda", "Segue"]:
            if b_alt and b_alt not in buckets_candidatos:
                buckets_candidatos.append(b_alt)

        for b_cand in buckets_candidatos:
            for med in meds_candidatas:
                query_sql = f'SELECT * FROM "{med}" ORDER BY time DESC LIMIT {limite}'
                df = self._executar_query_influxql(query_sql, b_cand)
                if not df.empty:
                    self.bucket = b_cand
                    self.measurement = med
                    return df

        return pd.DataFrame()

    def buscar_dados(self, tempo_inicio_str: str = "-1h", tempo_fim_str: str = "now()") -> pd.DataFrame:
        """
        Busca dados da medição via proxy InfluxQL / /api/ds/query.
        Caso o filtro de tempo falhe (por exemplo, relógio do servidor descompassado),
        executa automaticamente fallback para buscar os pontos mais recentes.
        """
        if not self.conectado:
            if not self.conectar():
                return pd.DataFrame()

        t_inicio = tempo_inicio_str
        if t_inicio.startswith("-"):
            t_inicio = f"now() - {t_inicio[1:]}"

        meds_candidatas = [self.measurement]
        alt_med = self.measurement[:-3] if self.measurement.endswith("_v4") else f"{self.measurement}_v4"
        if alt_med not in meds_candidatas:
            meds_candidatas.append(alt_med)

        buckets_candidatos = [self.bucket]
        for b_alt in ["soda", "Segue"]:
            if b_alt and b_alt not in buckets_candidatos:
                buckets_candidatos.append(b_alt)

        for b_cand in buckets_candidatos:
            for med in meds_candidatas:
                if self.query_template:
                    query_sql = self.query_template.replace("$timeFilter", f"time >= {t_inicio}").replace("{tempo_inicio}", t_inicio).replace("{tempo_fim}", tempo_fim_str)
                else:
                    query_sql = f'SELECT * FROM "{med}" WHERE time >= {t_inicio} ORDER BY time ASC'

                df = self._executar_query_influxql(query_sql, b_cand)
                if not df.empty:
                    self.bucket = b_cand
                    self.measurement = med
                    return df

        # Fallback automático: busca os últimos 1000 pontos gravados fisicamente no InfluxDB
        return self.buscar_dados_recentes(limite=1000)

    def buscar_contador_soda(self, cfg_soda: dict) -> Optional[float]:
        """Consulta o totalizador físico de garrafas no banco soda-template."""
        if not self.conectado:
            if not self.conectar():
                return None

        ds_soda = str(cfg_soda.get("datasource", "8")).strip()
        db_soda = str(cfg_soda.get("database", "soda-template")).strip()
        eq_type = str(cfg_soda.get("equipment_type", "Filler")).strip()
        field_name = str(cfg_soda.get("field_name", "Packaging Machine Production Counter - Total")).strip()
        tags = cfg_soda.get("tag_filtro", {})

        where_parts = []
        for k, v in tags.items():
            if str(v).strip():
                where_parts.append(f'"{k}" = \'{v}\'')
        where_str = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
        query_sql = f'SELECT LAST("{field_name}") FROM "{eq_type}"{where_str}'

        proxy_url = f"{self.url}/api/datasources/proxy/{ds_soda}/query"
        headers_sql = dict(self.headers)
        headers_sql["Content-Type"] = "application/x-www-form-urlencoded"
        headers_sql["Accept"] = "application/json"
        params = {"db": db_soda, "q": query_sql}

        try:
            res = self.session.post(proxy_url, headers=headers_sql, data=params, timeout=self.timeout)
            if res.status_code == 200:
                data = res.json()
                results = data.get("results", [])
                if results and "series" in results[0]:
                    vals = results[0]["series"][0].get("values", [])
                    if vals and len(vals[0]) > 1:
                        return float(vals[0][1])
        except Exception:
            pass
        return None

    def listar_colunas_disponiveis(self) -> list:
        """Consulta o InfluxDB para retornar os nomes de todas as colunas/campos existentes."""
        if not self.conectado:
            if not self.conectar():
                return []

        proxy_url = f"{self.url}/api/datasources/proxy/{self.ds_id}/query"
        headers_sql = dict(self.headers)
        headers_sql["Content-Type"] = "application/x-www-form-urlencoded"
        headers_sql["Accept"] = "application/json"

        # 1. Determina lista de medições candidatas (ex: '512_v4', '512', etc.)
        meds_candidatas = [self.measurement]
        if self.measurement.endswith("_v4"):
            meds_candidatas.append(self.measurement[:-3])
        else:
            meds_candidatas.append(f"{self.measurement}_v4")

        # 2. Descobrir measurements do InfluxDB caso as candidatas não respondam
        try:
            res_m = self.session.post(proxy_url, headers=headers_sql, data={"db": self.bucket, "q": "SHOW MEASUREMENTS"}, timeout=self.timeout)
            if res_m.status_code == 200:
                data_m = res_m.json().get("results", [])
                if data_m and "series" in data_m[0]:
                    vals_m = data_m[0]["series"][0].get("values", [])
                    for vm in vals_m:
                        if vm and vm[0] and str(vm[0]) not in meds_candidatas:
                            meds_candidatas.append(str(vm[0]))
        except Exception:
            pass

        # 3. Descobrir databases do InfluxDB caso o bucket configurado esteja vazio
        buckets_candidatos = [self.bucket]
        try:
            res_db = self.session.post(proxy_url, headers=headers_sql, data={"q": "SHOW DATABASES"}, timeout=self.timeout)
            if res_db.status_code == 200:
                data_db = res_db.json().get("results", [])
                if data_db and "series" in data_db[0]:
                    for v_db in data_db[0]["series"][0].get("values", []):
                        if v_db and v_db[0] and str(v_db[0]) not in buckets_candidatos and str(v_db[0]) != "_internal":
                            buckets_candidatos.append(str(v_db[0]))
        except Exception:
            pass

        cols_encontradas = set()

        for b_cand in buckets_candidatos:
            for med in meds_candidatas:
                # 3.1. SHOW FIELD KEYS e SHOW TAG KEYS
                for q_cmd in [f'SHOW FIELD KEYS FROM "{med}"', f'SHOW TAG KEYS FROM "{med}"']:
                    try:
                        res = self.session.post(proxy_url, headers=headers_sql, data={"db": b_cand, "q": q_cmd}, timeout=self.timeout)
                        if res.status_code == 200:
                            results = res.json().get("results", [])
                            if results and "series" in results[0]:
                                vals = results[0]["series"][0].get("values", [])
                                for v in vals:
                                    if v and v[0] and str(v[0]).lower() != "time":
                                        cols_encontradas.add(str(v[0]))
                    except Exception:
                        pass

                if cols_encontradas:
                    self.bucket = b_cand
                    self.measurement = med
                    return sorted(list(cols_encontradas))

                # 3.2. SELECT ORDER BY time DESC LIMIT 1 (pega o ponto mais recente real)
                for q_sel in [
                    f'SELECT * FROM "{med}" ORDER BY time DESC LIMIT 1',
                    f'SELECT * FROM "{med}" WHERE time >= now() - 24h LIMIT 1',
                    f'SELECT * FROM "{med}" WHERE time >= now() - 7d LIMIT 1',
                    f'SELECT * FROM "{med}" LIMIT 1'
                ]:
                    try:
                        res = self.session.post(proxy_url, headers=headers_sql, data={"db": b_cand, "q": q_sel}, timeout=self.timeout)
                        if res.status_code == 200:
                            results = res.json().get("results", [])
                            if results and "series" in results[0]:
                                cols = results[0]["series"][0].get("columns", [])
                                if cols:
                                    self.bucket = b_cand
                                    self.measurement = med
                                    return sorted([c for c in cols if c.lower() != "time"])
                    except Exception:
                        pass

        # 4. Fallback final: tentar buscar dataframe recente pelo cliente
        try:
            df_rec = self.buscar_dados(tempo_inicio_str="-24h")
            if not df_rec.empty:
                cols_df = [c for c in df_rec.columns if c.lower() != "time"]
                if cols_df:
                    return sorted(cols_df)
        except Exception:
            pass

        return []
