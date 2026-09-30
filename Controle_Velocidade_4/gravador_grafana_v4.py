#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Telemetria e Gravação no Grafana / InfluxDB - Controlador V4
Envia métricas de processo e controle de cada ciclo para uma medição (measurement)
dedicada no InfluxDB via proxy da API do Grafana (ou direto no InfluxDB),
substituindo o uso de arquivos CSV locais e permitindo visualização em tempo real.
"""

import os
import sys
import time
import datetime
import logging
import base64
from typing import Dict, Any, Optional, List
import requests

logger = logging.getLogger("GravadorGrafanaV4")


class GravadorGrafanaV4:
    """
    Cliente de envio de telemetria industrial para o InfluxDB via API do Grafana.
    Suporta:
    - Gravação em medição (measurement) dedicada para isolar métricas de controle V4.
    - Autenticação via Grafana Service Account Token (Bearer) ou Basic Auth.
    - Formatação estrita em InfluxDB Line Protocol (com suporte a v1 e v2).
    - Modo assíncrono / não-bloqueante para não afetar o ciclo de controle do CLP.
    - Ring buffer local para reenvio caso haja oscilações transitórias de rede.
    - Gravação opcional de CSV de contingência caso configurado pelo operador.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}

        self.habilitado = bool(cfg.get("habilitado", True))
        
        # 1. Configuração Direta do InfluxDB (Prioridade Máxima - porta 8086 / localhost / InfluxQL)
        self.influx_url = str(cfg.get("influx_url", cfg.get("influx_url_direta", "http://localhost:8086"))).rstrip("/")
        self.database = str(cfg.get("database", cfg.get("bucket", "Segue"))).strip()
        self.bucket = self.database
        self.usuario = str(cfg.get("usuario", cfg.get("grafana_user", ""))).strip()
        self.senha = str(cfg.get("senha", cfg.get("grafana_password", ""))).strip()
        self.influx_token = str(cfg.get("influx_token", cfg.get("influx_token_direto", ""))).strip()
        self.org = str(cfg.get("org", "ABinbev")).strip()
        self.measurement_destino = str(cfg.get("measurement_destino", "512_v4")).strip()
        self.timeout_envio_s = float(cfg.get("timeout_envio_s", 2.0))

        # 2. Configuração do Grafana (Fallback secundário caso InfluxDB direto não responda)
        self.grafana_url = str(cfg.get("grafana_url", "")).rstrip("/")
        self.grafana_user = self.usuario
        self.grafana_password = self.senha
        self.grafana_token = str(cfg.get("grafana_token", "")).strip()
        self.datasource_selector = str(cfg.get("datasource_selector", "17")).strip()

        # Sessão HTTP dedicada sem proxy do sistema
        self.session = requests.Session()
        self.session.trust_env = False

        # Cache de metadados do Datasource Grafana
        self.ds_id: Optional[str] = self.datasource_selector if self.datasource_selector.isdigit() else None
        self.ds_uid: Optional[str] = self.datasource_selector if (self.datasource_selector and not self.datasource_selector.isdigit()) else None
        self.ds_database: Optional[str] = self.bucket
        self.bearer_token: Optional[str] = self.grafana_token if self.grafana_token else None
        self.basic_auth_header: str = ""
        self._tempo_ultima_descoberta: float = 0.0

        # Estatísticas operacionais
        self.total_enviados = 0
        self.total_falhas = 0
        self.falhas_consecutivas = 0
        self.ultimo_status_envio = "Não inicializado"

        # Buffer de contingência em memória (até 120 pontos = ~20 min em ciclo de 10s)
        self._buffer_contingencia: List[str] = []
        self._max_buffer = 120
        self._url_direta_sucesso: Optional[str] = None
        self.ultimo_motivo_falha: str = ""

        self._configurar_autenticacao()
        if self.habilitado:
            self._descobrir_datasource()

    def _configurar_autenticacao(self):
        """Prepara os cabeçalhos de autenticação para o Grafana."""
        if self.grafana_user and self.grafana_password:
            usr_pass = f"{self.grafana_user}:{self.grafana_password}".encode("utf-8")
            b64_val = base64.b64encode(usr_pass).decode("utf-8")
            self.basic_auth_header = f"Basic {b64_val}"

    def _obter_headers_grafana(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Accept": "application/json"
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        elif self.basic_auth_header:
            headers["Authorization"] = self.basic_auth_header
        return headers

    def _descobrir_datasource(self):
        """Descobre o UID e ID do datasource InfluxDB no Grafana."""
        if not self.grafana_url:
            return
        self._tempo_ultima_descoberta = time.time()

        headers = self._obter_headers_grafana()
        ds_url = f"{self.grafana_url}/api/datasources"
        try:
            r = self.session.get(ds_url, headers=headers, timeout=self.timeout_envio_s)
            if r.status_code == 200:
                ds_list = r.json()
                influx_ds = [ds for ds in ds_list if ds.get("type") == "influxdb"]

                target_ds = None
                if self.datasource_selector:
                    for ds in influx_ds:
                        if str(ds.get("id")) == self.datasource_selector or str(ds.get("name", "")).lower() == self.datasource_selector.lower():
                            target_ds = ds
                            break
                        if str(ds.get("uid", "")).lower() == self.datasource_selector.lower():
                            target_ds = ds
                            break

                if target_ds is None and influx_ds:
                    target_ds = influx_ds[0]

                if target_ds:
                    self.ds_id = str(target_ds.get("id"))
                    self.ds_uid = str(target_ds.get("uid", ""))
                    db_name = target_ds.get("database")
                    if db_name:
                        self.ds_database = str(db_name)
                    logger.info(
                        f"[Telemetria Grafana] Datasource InfluxDB selecionado: "
                        f"Nome='{target_ds.get('name')}', ID={self.ds_id}, UID={self.ds_uid}, DB='{self.ds_database}'"
                    )
            else:
                logger.warning(
                    f"[Telemetria Grafana] Não foi possível consultar datasources (Status {r.status_code}): {r.text[:100]}"
                )
        except Exception as e:
            logger.warning(f"[Telemetria Grafana] Falha ao conectar ao Grafana para listar datasources: {e}")

    @staticmethod
    def _escapar_tag(val: Any) -> str:
        """Escapa caracteres reservados em tags e measurement do InfluxDB Line Protocol."""
        s = str(val).replace("\\", "\\\\").replace(",", "\\,").replace(" ", "\\ ").replace("=", "\\=")
        return s if s else "desconhecido"

    @staticmethod
    def _escapar_campo_string(val: Any) -> str:
        """Escapa strings para valores de campos (fields) no Line Protocol."""
        s = str(val).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'

    def formatar_line_protocol(
        self,
        measurement: str,
        tags: Dict[str, Any],
        fields: Dict[str, Any],
        timestamp_s: Optional[int] = None
    ) -> str:
        """
        Gera uma linha válida no formato InfluxDB Line Protocol.
        Exemplo:
        512_v4,fabrica=Uberlandia,linha=512,maquina=ECH512001 b1=50.0,b2=55.2,v_sp=94500.0,motivo_id=0i 1727500000
        """
        medicao_esc = self._escapar_tag(measurement or self.measurement_destino)

        # Tags ordenadas alfabeticamente (recomendação de performance do InfluxDB)
        tags_formatadas = []
        for k in sorted(tags.keys()):
            v = tags[k]
            if v is not None and str(v).strip() != "":
                k_esc = self._escapar_tag(k)
                v_esc = self._escapar_tag(v)
                tags_formatadas.append(f"{k_esc}={v_esc}")

        tag_str = f",{','.join(tags_formatadas)}" if tags_formatadas else ""

        # Fields
        fields_formatados = []
        for k, v in fields.items():
            if v is None:
                continue
            k_esc = self._escapar_tag(k)
            if isinstance(v, bool):
                fields_formatados.append(f"{k_esc}={'t' if v else 'f'}")
            elif isinstance(v, int):
                fields_formatados.append(f"{k_esc}={v}i")
            elif isinstance(v, float):
                # Proteção contra NaN / Inf
                if v != v or v == float('inf') or v == float('-inf'):
                    continue
                fields_formatados.append(f"{k_esc}={v:.4f}")
            else:
                fields_formatados.append(f"{k_esc}={self._escapar_campo_string(v)}")

        if not fields_formatados:
            return ""

        field_str = ",".join(fields_formatados)

        # Timestamp em segundos UTC
        ts = int(timestamp_s) if timestamp_s is not None else int(time.time())
        return f"{medicao_esc}{tag_str} {field_str} {ts}"

    def preparar_ponto_ciclo(
        self,
        linha_info: Dict[str, str],
        b1: float, b2: float, b3: float, b4: float,
        v_in: float, v_atual: float, v_out: float,
        v_setpoint: float, vel_nom: float,
        motivo_id: int, motivo_info: Dict[str, Any],
        modo_sombra: bool,
        segue_habilitado: bool,
        hb_status: str = "N/A",
        heartbeat_counter: int = 0,
        total_eventos_opc: int = 0,
        limiar_parada_cph: float = 10000.0,
        timestamp_s: Optional[int] = None,
        status_maquina: bool = True
    ) -> str:
        """Monta o registro completo do ciclo do Controlador V4 no Line Protocol."""
        linha = linha_info.get("linha", "512")
        fabrica = linha_info.get("fabrica", "Uberlandia")
        maquina = linha_info.get("nome_principal", "ECH512001")

        pct_nominal = round((v_setpoint / vel_nom) * 100.0, 2) if vel_nom > 0 else 0.0
        delta_cph = round(v_setpoint - v_atual, 1)

        # Determina status operacional da linha
        if pct_nominal > 100.0:
            status_mod = "SOBREMARCHA_SPRINT"
        elif pct_nominal == 100.0:
            status_mod = "DESATIVADA_NOMINAL"
        else:
            status_mod = "ATIVA_MODULACAO"

        maquina_rodando = bool(v_atual >= limiar_parada_cph)

        tags = {
            "linha": linha,
            "fabrica": fabrica,
            "maquina": maquina,
            "modo_sombra": "true" if modo_sombra else "false",
            "segue_habilitado": "true" if segue_habilitado else "false",
            "motivo_codigo": motivo_info.get("codigo", "NORMAL_FULL"),
            "maquina_causadora": motivo_info.get("maquina_causadora", "Nenhuma"),
            "status_modulacao": status_mod,
            "status_operacional": "RODANDO" if maquina_rodando else "PARADA"
        }

        fields = {
            "b1_pct": float(b1),
            "b2_pct": float(b2),
            "b3_pct": float(b3),
            "b4_pct": float(b4),
            "v_in_cph": float(v_in),
            "v_atual_cph": float(v_atual),
            "v_out_cph": float(v_out),
            "v_setpoint_cph": float(v_setpoint),
            "v_nominal_cph": float(vel_nom),
            "percentual_nominal": float(pct_nominal),
            "setpoint_percentual": float(pct_nominal),
            "delta_setpoint_real_cph": float(delta_cph),
            "velocidade_real_cph": float(v_atual),
            "velocidade_v4_cph": float(v_setpoint),
            "motivo_id": int(motivo_id),
            "motivo_descricao": str(motivo_info.get("descricao", "")),
            "acao_recomendada": str(motivo_info.get("acao_recomendada", "")),
            "maquina_ligada": maquina_rodando,
            "status_maquina": bool(status_maquina),
            "heartbeat_counter": int(heartbeat_counter),
            "total_eventos_opc": int(total_eventos_opc),
            "hb_status": str(hb_status)
        }

        return self.formatar_line_protocol(
            measurement=self.measurement_destino,
            tags=tags,
            fields=fields,
            timestamp_s=timestamp_s
        )

    def enviar_ponto_sync(self, linha_protocolo: str) -> bool:
        """
        Executa o envio síncrono de uma ou mais linhas no InfluxDB via Grafana Proxy ou direto.
        Retorna True em caso de sucesso, False caso contrário.
        """
        if not self.habilitado:
            return False

        if not linha_protocolo.strip():
            return False

        # Adiciona ponto atual à lista de linhas a enviar (incluindo buffer de contingência)
        linhas_a_enviar = list(self._buffer_contingencia)
        linhas_a_enviar.append(linha_protocolo.strip())
        corpo_envio = "\n".join(linhas_a_enviar)

        enviado = False
        ultimo_erro = None

        # 1. Tentativa Direta no InfluxDB (Prioridade Máxima: porta 8086 / localhost / InfluxQL)
        urls_influx_direto = []
        if self._url_direta_sucesso:
            urls_influx_direto.append(self._url_direta_sucesso)

        if self.influx_url:
            from urllib.parse import urlparse
            parsed = urlparse(self.influx_url)
            scheme = parsed.scheme or "http"
            host = parsed.hostname or "localhost"
            porta_cfg = parsed.port or 8086
            
            # Testa a porta configurada e automaticamente a porta irmã (8089 <-> 8086)
            portas_a_testar = [porta_cfg]
            if porta_cfg == 8086 and 8089 not in portas_a_testar:
                portas_a_testar.append(8089)
            elif porta_cfg == 8089 and 8086 not in portas_a_testar:
                portas_a_testar.append(8086)

            for p in portas_a_testar:
                u_v1 = f"{scheme}://{host}:{p}/write?db={self.database}&precision=s"
                u_v2 = f"{scheme}://{host}:{p}/api/v2/write?bucket={self.database}&org={self.org}&precision=s"
                # Na porta 8086 prioriza InfluxQL (SQL / v1); na porta 8089 prioriza Flux (v2)
                ordem_port = [u_v1, u_v2] if p == 8086 else [u_v2, u_v1]
                for u_cand in ordem_port:
                    if u_cand not in urls_influx_direto:
                        urls_influx_direto.append(u_cand)

            # Se a URL for loopback ou container interno, adiciona alternativas de rede
            if any(h in self.influx_url for h in ["localhost", "127.0.0.1", "segue-influxdb", "influxdb"]):
                for host_alt in ["localhost", "127.0.0.1", "influxdb", "segue-influxdb", "host.docker.internal"]:
                    for porta_alt in [8086, 8089]:
                        u_v1_alt = f"http://{host_alt}:{porta_alt}/write?db={self.database}&precision=s"
                        u_v2_alt = f"http://{host_alt}:{porta_alt}/api/v2/write?bucket={self.database}&org={self.org}&precision=s"
                        ordem_alt = [u_v1_alt, u_v2_alt] if porta_alt == 8086 else [u_v2_alt, u_v1_alt]
                        for u_cand_alt in ordem_alt:
                            if u_cand_alt not in urls_influx_direto:
                                urls_influx_direto.append(u_cand_alt)

        erro_principal = None
        for i, u_dir in enumerate(urls_influx_direto):
            headers_dir = {"Content-Type": "text/plain; charset=utf-8"}
            if self.influx_token:
                headers_dir["Authorization"] = f"Token {self.influx_token}"

            # Tenta envio (primeiro sem autenticação ou com credenciais básicas se configuradas)
            auth_tuple = (self.usuario, self.senha) if (self.usuario and self.senha) else None
            try:
                r = self.session.post(u_dir, data=corpo_envio.encode("utf-8"), headers=headers_dir, auth=auth_tuple, timeout=self.timeout_envio_s)
                if r.status_code in [200, 204]:
                    enviado = True
                    self._url_direta_sucesso = u_dir
                    break
                elif auth_tuple and r.status_code in [401, 403]:
                    # Tenta sem auth caso a instância local não utilize autenticação
                    r_noauth = self.session.post(u_dir, data=corpo_envio.encode("utf-8"), headers=headers_dir, timeout=self.timeout_envio_s)
                    if r_noauth.status_code in [200, 204]:
                        enviado = True
                        self._url_direta_sucesso = u_dir
                        break
                    else:
                        ultimo_erro = f"HTTP {r_noauth.status_code} em {u_dir.split('?')[0]}"
                elif r.status_code == 404:
                    # 1. Tenta auto-criar o banco via query (recurso nativo do InfluxDB v1)
                    try:
                        base_host = "/".join(u_dir.split('/')[:3])
                        q_url = f"{base_host}/query"
                        r_create = self.session.post(
                            q_url,
                            data={"q": f'CREATE DATABASE "{self.database}"'},
                            headers={"Accept": "application/json"},
                            auth=auth_tuple,
                            timeout=self.timeout_envio_s
                        )
                        if r_create.status_code in [200, 204]:
                            r_retry = self.session.post(u_dir, data=corpo_envio.encode("utf-8"), headers=headers_dir, auth=auth_tuple, timeout=self.timeout_envio_s)
                            if r_retry.status_code in [200, 204]:
                                enviado = True
                                self._url_direta_sucesso = u_dir
                                logger.info(f"[Telemetria InfluxDB] Banco '{self.database}' criado com sucesso e ponto gravado!")
                                break
                    except Exception:
                        pass

                    # 2. Tenta variação em minúsculo (ex: 'segue' vs 'Segue')
                    if self.database != self.database.lower():
                        u_lower = u_dir.replace(f"db={self.database}", f"db={self.database.lower()}")
                        try:
                            r_lower = self.session.post(u_lower, data=corpo_envio.encode("utf-8"), headers=headers_dir, auth=auth_tuple, timeout=self.timeout_envio_s)
                            if r_lower.status_code in [200, 204]:
                                enviado = True
                                self.database = self.database.lower()
                                self._url_direta_sucesso = u_lower
                                logger.info(f"[Telemetria InfluxDB] Banco localizado em minúsculo: '{self.database}'. Ajustado automaticamente.")
                                break
                        except Exception:
                            pass

                    ultimo_erro = f"HTTP 404 (Banco/Bucket '{self.database}' não encontrado) em {u_dir.split('?')[0]}"
                elif r.status_code in [401, 403]:
                    ultimo_erro = f"HTTP {r.status_code} (Autenticação rejeitada) em {u_dir.split('?')[0]}"
                else:
                    resp_snip = r.text.strip().replace('\n', ' ')[:50] if r.text else ''
                    ultimo_erro = f"HTTP {r.status_code} ({resp_snip}) em {u_dir.split('?')[0]}"
            except requests.exceptions.ConnectionError as e:
                err_msg = str(e)
                if "Connection refused" in err_msg or "Errno 111" in err_msg:
                    partes = u_dir.split('/')
                    host_porta = partes[2] if len(partes) > 2 else "localhost:8086"
                    ultimo_erro = f"Conexão recusada em {host_porta} (Porta fechada ou InfluxDB offline)"
                elif "Name or service not known" in err_msg or "nodename nor servname" in err_msg:
                    host_str = u_dir.split('/')[2].split(':')[0]
                    ultimo_erro = f"Host '{host_str}' não encontrado (DNS/Rede)"
                else:
                    ultimo_erro = f"Falha de conexão em {u_dir.split('?')[0]}: {type(e).__name__}"
            except requests.exceptions.Timeout:
                ultimo_erro = f"Timeout ({self.timeout_envio_s}s) ao contatar {u_dir.split('?')[0]}"
            except Exception as e:
                ultimo_erro = f"Erro em {u_dir.split('?')[0]}: {e}"

            if i == 0 and ultimo_erro:
                erro_principal = ultimo_erro

        if not enviado and erro_principal:
            ultimo_erro = erro_principal

        # 2. Tentativa via Proxy do Grafana (Fallback caso InfluxDB direto não responda)
        if not enviado and self.grafana_url:
            agora_ts = time.time()
            if self.ds_uid is None and (agora_ts - self._tempo_ultima_descoberta) > 30.0:
                self._descobrir_datasource()

            headers = self._obter_headers_grafana()
            bucket_usar = self.ds_database or self.bucket

            # Candidatos de endpoints de escrita através do Grafana
            urls_candidatas = []

            # 2.1 Por UID descoberto ou do seletor
            uids = [self.ds_uid] if self.ds_uid else []
            if self.datasource_selector and not self.datasource_selector.isdigit() and self.datasource_selector not in uids:
                uids.append(self.datasource_selector)

            for uid in uids:
                urls_candidatas.append(
                    f"{self.grafana_url}/api/datasources/uid/{uid}/resources/api/v2/write?bucket={bucket_usar}&org={self.org}&precision=s"
                )
                urls_candidatas.append(
                    f"{self.grafana_url}/api/datasources/uid/{uid}/resources/write?db={bucket_usar}&precision=s"
                )

            # 2.2 Por ID numérico descoberto ou do seletor
            ids = [self.ds_id] if self.ds_id else []
            if self.datasource_selector and self.datasource_selector.isdigit() and self.datasource_selector not in ids:
                ids.append(self.datasource_selector)

            for did in ids:
                urls_candidatas.append(
                    f"{self.grafana_url}/api/datasources/proxy/{did}/api/v2/write?bucket={bucket_usar}&org={self.org}&precision=s"
                )
                urls_candidatas.append(
                    f"{self.grafana_url}/api/datasources/proxy/{did}/write?db={bucket_usar}&precision=s"
                )

            # 2.3 Fallback direto no InfluxDB no mesmo host (portas 8086 / 8089)
            try:
                from urllib.parse import urlparse
                host = urlparse(self.grafana_url).hostname
                if host and host not in ["localhost", "127.0.0.1"]:
                    for porta in [8086, 8089]:
                        urls_candidatas.append(f"http://{host}:{porta}/api/v2/write?bucket={bucket_usar}&org={self.org}&precision=s")
                        urls_candidatas.append(f"http://{host}:{porta}/write?db={bucket_usar}&precision=s")
            except Exception:
                pass

            if not urls_candidatas:
                ultimo_erro = f"Nenhum datasource disponível (selector: '{self.datasource_selector}')"

            for url in urls_candidatas:
                try:
                    r = self.session.post(url, data=corpo_envio.encode("utf-8"), headers=headers, timeout=self.timeout_envio_s)
                    if r.status_code in [200, 204]:
                        enviado = True
                        break
                    else:
                        resp_txt = r.text.strip().replace('\n', ' ')[:40] if r.text else ''
                        ultimo_erro = f"HTTP {r.status_code} ({resp_txt})"
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                    ultimo_erro = f"Conexão/Timeout ({type(e).__name__})"
                except Exception as e:
                    ultimo_erro = f"Erro ({e})"

        if enviado:
            qtd_enviada = len(linhas_a_enviar)
            self.total_enviados += qtd_enviada
            self.falhas_consecutivas = 0
            self.ultimo_motivo_falha = ""
            endpoint_usado = self._url_direta_sucesso or "HTTP"
            proto = "SQL" if "/write?" in endpoint_usado else "Flux"
            self.ultimo_status_envio = f"OK [{proto}] ({self.measurement_destino} - {qtd_enviada} pt)"
            logger.debug(f"[Telemetria InfluxDB] {qtd_enviada} ponto(s) gravado(s) com sucesso na medição '{self.measurement_destino}' via {endpoint_usado.split('?')[0]}.")
            return True
        else:
            self.total_falhas += 1
            self.falhas_consecutivas += 1
            if not ultimo_erro:
                ultimo_erro = "Nenhum endpoint InfluxDB acessível ou respondendo"
            self.ultimo_motivo_falha = ultimo_erro
            self.ultimo_status_envio = f"Falha: {ultimo_erro}"

            # Armazena linha no ring buffer de contingência para reenvio posterior
            if len(self._buffer_contingencia) < self._max_buffer:
                self._buffer_contingencia.append(linha_protocolo.strip())

            # Loga aviso apenas em falhas pontuais para não inundar o log industrial
            if self.falhas_consecutivas in [1, 5, 20, 50]:
                logger.warning(
                    f"[Telemetria Grafana] Falha ao gravar na medição '{self.measurement_destino}' "
                    f"(Falhas consecutivas: {self.falhas_consecutivas}): {ultimo_erro}"
                )
            return False

    async def enviar_ponto_async(self, linha_protocolo: str) -> bool:
        """
        Despacha o envio síncrono para uma thread separada do event loop.
        Garante que o loop de controle e o Heartbeat do CLP nunca sejam bloqueados.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self.enviar_ponto_sync, linha_protocolo)
        except Exception as e:
            logger.error(f"[Telemetria Grafana] Erro na execução assíncrona: {e}")
            return False
