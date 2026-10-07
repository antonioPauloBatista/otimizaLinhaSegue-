#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLIENTE OPC UA INDUSTRIAL EM TEMPO REAL - CONTROLADOR DE VELOCIDADE V4
Executa a leitura em modo SUBSCRIPTION (assinatura de eventos DataChange) para:
- Sensores discretos de esteiras (calculando acúmulo geométrico dos buffers B1, B2, B3 e B4).
- Velocidades das máquinas vizinhas (v_in e v_out).

Executa a escrita em tempo real para:
- Setpoint de velocidade calculado para a Enchedora (via ControladorVelocidadeV4).
- Pulso de Heartbeat (Watchdog industrial para o CLP).
"""

import os
import sys
import json
import asyncio
import logging
import argparse
import datetime
from typing import Dict, Any, Optional

# Garante importação dos módulos locais
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
if DIRETORIO_ATUAL not in sys.path:
    sys.path.insert(0, DIRETORIO_ATUAL)

from gerenciador_buffers import GerenciadorBuffers
from funcao_controle_v4 import ControladorVelocidadeV4
from gravador_grafana_v4 import GravadorGrafanaV4

try:
    from asyncua import Client, Node, ua
    from asyncua.common.subscription import Subscription
    TEM_ASYNCUA = True
except ImportError:
    TEM_ASYNCUA = False
    Client = Any
    Node = Any
    ua = Any
    Subscription = Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ClienteOPC_V4")

# Silencia logs internos e repetitivos de subscrição da biblioteca asyncua (só loga falhas)
logging.getLogger("asyncua").setLevel(logging.WARNING)
logging.getLogger("asyncua.common.subscription").setLevel(logging.WARNING)
logging.getLogger("asyncua.client.ua_client.UaClient").setLevel(logging.WARNING)


class EstadoLinha:
    """Cache de variáveis em memória alimentado instantaneamente pelas subscrições OPC UA."""
    def __init__(self, velocidade_nominal: float = 94500.0):
        self.v_nominal = float(velocidade_nominal)
        self.v_in = float(velocidade_nominal)
        self.v_atual = float(velocidade_nominal)
        self.v_out = float(velocidade_nominal)
        self.v_setpoint_calculado = float(velocidade_nominal)
        self.segue_habilitado = False
        self.status_maquina = True
        self.ultimo_motivo_id = 0
        self.heartbeat_val = False
        self.heartbeat_counter = 0
        self.total_eventos_recebidos = 0
        self.ultima_atualizacao = datetime.datetime.now()


class SubscricaoHandler:
    """
    Tratador de eventos DataChange do OPC UA.
    Disparado pelo servidor OPC UA sempre que o valor de uma tag assinada se altera.
    """
    def __init__(self, gerenciador_buffers: GerenciadorBuffers, estado: EstadoLinha, mapa_nos_para_tags: Dict[str, str], config_maquinas: Dict[str, str]):
        self.gerenciador_buffers = gerenciador_buffers
        self.estado = estado
        self.mapa_nos_para_tags = mapa_nos_para_tags
        self.cfg_maquinas = config_maquinas

        # Tags de máquinas normalizadas
        self.tag_vin = self.cfg_maquinas.get("tag_velocidade_montante", "").strip()
        self.tag_vatual = self.cfg_maquinas.get("tag_velocidade_atual", "").strip()
        self.tag_vout = self.cfg_maquinas.get("tag_velocidade_jusante", "").strip()
        self.tag_segue_hab = self.cfg_maquinas.get("tag_segue_habilitado", "").strip()
        self.tag_status_maq = self.cfg_maquinas.get("tag_status_maquina", "").strip()

    def datachange_notification(self, node: Node, val: Any, data: Any):
        """Callback assíncrono executado quando uma tag assinada comuta de valor."""
        try:
            node_str = node.nodeid.to_string()
            tag_original = self.mapa_nos_para_tags.get(node_str, node_str)
            self.estado.total_eventos_recebidos += 1
            self.estado.ultima_atualizacao = datetime.datetime.now()

            # 0. Verifica se é a tag de Habilitação do Segue no CLP
            if self.tag_segue_hab and (tag_original == self.tag_segue_hab or node_str == self.tag_segue_hab):
                self.estado.segue_habilitado = bool(val)
                logger.info(f"[CLP] Segue Habilitado atualizado para: {self.estado.segue_habilitado}")
                return

            # 0.1 Verifica se é a tag de Status Operacional da Máquina
            if self.tag_status_maq and (tag_original == self.tag_status_maq or node_str == self.tag_status_maq):
                self.estado.status_maquina = bool(val) if val is not None else True
                logger.info(f"[CLP] Status da Máquina atualizado para: {self.estado.status_maquina}")
                return

            # 1. Verifica se é tag de sensor de buffer
            if self.gerenciador_buffers.atualizar_valor_sensor(tag_original, val):
                return

            # 2. Verifica se é tag de velocidade de máquina
            if tag_original == self.tag_vin or node_str == self.tag_vin:
                self.estado.v_in = float(val) if val is not None else self.estado.v_nominal
            elif tag_original == self.tag_vatual or node_str == self.tag_vatual:
                self.estado.v_atual = float(val) if val is not None else self.estado.v_nominal
            elif tag_original == self.tag_vout or node_str == self.tag_vout:
                self.estado.v_out = float(val) if val is not None else self.estado.v_nominal

        except Exception as e:
            logger.error(f"Erro no processamento da notificação DataChange: {e}")

    def status_change_notification(self, status: Any):
        """Callback acionado se o status da subscrição mudar."""
        pass

    def event_notification(self, event: Any):
        """Callback acionado para eventos gerais OPC UA."""
        pass


def _barra_buffer(pct: float, largura: int = 5, tipo: str = "b2", existe: bool = True) -> str:
    """Retorna uma barra compacta colorida: [███░░] 60% ou [----] 0.0% se inexistente"""
    if not existe:
        return f"\033[2m[----]  0.0%\033[0m"

    pct = max(0.0, min(100.0, float(pct)))
    cheios = int(round((pct / 100.0) * largura))
    vazios = max(0, largura - cheios)
    barra = "█" * cheios + "░" * vazios

    # Cores conforme criticidade
    if tipo in ["b1", "b2"]:  # Buffers de entrada: perigo é secar
        if pct <= 20.0: cor = "\033[91m"     # Vermelho (falta crítica)
        elif pct <= 35.0: cor = "\033[93m"   # Amarelo (atenção)
        else: cor = "\033[92m"              # Verde (abundante)
    else:                     # Buffers de saída: perigo é transbordar
        if pct >= 80.0: cor = "\033[91m"     # Vermelho (acúmulo crítico)
        elif pct >= 65.0: cor = "\033[93m"   # Amarelo (atenção)
        else: cor = "\033[92m"              # Verde (escoamento livre)

    rst = "\033[0m"
    return f"{cor}[{barra}] {pct:4.1f}%{rst}"


def desenhar_fluxograma_terminal(
    timestamp: str,
    linha_info: Dict[str, str],
    b1: float, b2: float, b3: float, b4: float,
    v_in: float, v_atual: float, v_out: float,
    vel_calculada: float, vel_nom: float,
    motivo_info: Dict[str, Any],
    modo_sombra: bool,
    hb_status: str,
    segue_habilitado: bool = True,
    telemetria_status: Optional[str] = None,
    telemetria_motivo_falha: Optional[str] = None,
    buffers_ativos: Optional[Dict[str, bool]] = None
):
    """
    Renderiza um fluxograma sinótico completo no terminal simulando a interface supervisória da linha de envase.
    """
    rst = "\033[0m"
    bold = "\033[1m"
    cyan = "\033[96m"
    green = "\033[92m"
    yellow = "\033[93m"
    red = "\033[91m"
    dim = "\033[2m"

    linha = linha_info.get("linha", "512")
    fabrica = linha_info.get("fabrica", "Uberlândia")
    nome_dpl = linha_info.get("nome_montante", "DPL512001")
    nome_ech = linha_info.get("nome_principal", "ECH512001")
    nome_pz  = linha_info.get("nome_jusante", "PZ512001")
    nome_epc = linha_info.get("nome_pos_jusante", "EPC512001")

    perc = round((vel_calculada / vel_nom) * 100.0, 1)
    diff_cph = vel_calculada - v_atual

    # Status de Modulação
    if perc > 100.0:
        mod_status = f"{cyan}{bold}SOBREMARCHA (SPRINT){rst}"
        decisao_str = f"sobremarcha [ {perc:.1f}% ]"
    elif perc == 100.0:
        mod_status = f"{green}{bold}DESATIVADA (NOMINAL 100%){rst}"
        decisao_str = f"velocidade nominal [ 100% ]"
    else:
        mod_status = f"{red}{bold}ATIVA (MODULAÇÃO){rst}"
        decisao_str = f"velocidade modulada [ {perc:.1f}% ]"

    bloco_ativo = motivo_info.get("codigo", "NORMAL_FULL")
    bloco_desc = motivo_info.get("descricao", "Operação Normal")

    if not segue_habilitado:
        modo_banner = f"{red}{bold}⛔ SEGUE DESABILITADO NO CLP (MODULAÇÃO EM BYPASS){rst}"
    elif modo_sombra:
        modo_banner = f"{yellow}{bold}🛡️ MODO SOMBRA (APENAS LEITURA - SEM ESCRITA NO CLP){rst}"
    else:
        modo_banner = f"{green}{bold}⚡ MODO ATIVO (ESCRITA NO CLP HABILITADA){rst}"

    # Cores de velocidade das máquinas
    cor_dpl = green if v_in > 0 else red
    cor_ech = green if v_atual > 0 else red
    cor_pz  = green if v_out > 0 else red
    cor_epc = green

    # Determina existência física dos buffers
    b_atv = buffers_ativos or {}
    b1_bar = _barra_buffer(b1, largura=4, tipo="b1", existe=b_atv.get("b1", True))
    b2_bar = _barra_buffer(b2, largura=4, tipo="b2", existe=b_atv.get("b2", True))
    b3_bar = _barra_buffer(b3, largura=4, tipo="b3", existe=b_atv.get("b3", True))
    b4_bar = _barra_buffer(b4, largura=4, tipo="b4", existe=b_atv.get("b4", True))

    # Strings das caixas (largura 14 caracteres)
    box_dpl = [f"┌──────────────┐", f"│ {nome_dpl[:12]:^12} │", f"│ {cor_dpl}{v_in:>8,.0f} CPH{rst} │", f"└──────────────┘"]
    box_ech = [f"┌──────────────┐", f"│ {cyan}{nome_ech[:12]:^12}{rst} │", f"│ {cor_ech}{v_atual:>8,.0f} CPH{rst} │", f"└──────┬───────┘"]
    box_pz  = [f"┌──────────────┐", f"│ {nome_pz[:12]:^12} │", f"│ {cor_pz}{v_out:>8,.0f} CPH{rst} │", f"└──────────────┘"]
    box_epc = [f"┌──────────────┐", f"│ {nome_epc[:12]:^12} │", f"│ {cor_epc}{vel_nom:>8,.0f} CPH{rst} │", f"└──────────────┘"]

    # Largura total 106 caracteres
    sep = "=" * 106
    print("\n" + sep)
    print(f" {bold}LINHA {linha}{rst} | Fábrica: {fabrica} | Máquina: {cyan}{nome_ech}{rst} | Modulação: {mod_status} | Decisão: {bold}{vel_calculada:,.0f} CPH{rst} [ {perc:.1f}% ]")
    print(f" Bloco Ativo: {yellow}[ {bloco_ativo} ]{rst} {bloco_desc} | {modo_banner}")
    print("-" * 106)
    print(f" {dim}FLUXOGRAMA SINÓTICO DA LINHA EM TEMPO REAL:{rst}")
    print("")

    # Linha 1 das Caixas
    print(f"  {dim}[B1]{rst} {b1_bar} ─> {box_dpl[0]}          {cyan}{box_ech[0]}{rst}          {box_pz[0]}          {box_epc[0]}")
    # Linha 2 das Caixas (Nomes)
    print(f"               {box_dpl[1]}   ──B2─>   {cyan}{box_ech[1]}{rst}   ──B3─>   {box_pz[1]}   ──B4─>   {box_epc[1]}")
    # Linha 3 das Caixas (Velocidades e Barras)
    print(f"               {box_dpl[2]} {b2_bar} {cyan}{box_ech[2]}{rst} {b3_bar} {box_pz[2]} {b4_bar} {box_epc[2]}")
    # Linha 4 das Caixas (Bases)
    print(f"               {box_dpl[3]}          {cyan}{box_ech[3]}{rst}          {box_pz[3]}          {box_epc[3]}")

    # Setpoint Box apontando para baixo da Enchedora
    print(f"                                                │")
    print(f"                                                ▼")
    print(f"                                     ┌─────────────────────┐")
    print(f"                                     │ {bold}{cyan}SETPOINT V4 RECOM.{rst}   │")
    print(f"                                     │ {bold}{vel_calculada:>8,.0f} CPH ({perc:5.1f}%){rst} │")
    print(f"                                     └─────────────────────┘")

    cor_hab = green if segue_habilitado else red
    hab_txt = "HABILITADO" if segue_habilitado else "DESABILITADO (BYPASS)"

    print("-" * 106)
    print(f" 📊 {bold}COMPARAÇÃO:{rst} Setpoint V4: {bold}{vel_calculada:,.0f} CPH{rst}  vs  Real no CLP: {v_atual:,.0f} CPH  ({bold}Diferença:{rst} {diff_cph:+,.0f} CPH)")
    print(f" 🔍 {bold}CAUSA-RAIZ:{rst} Máquina: {motivo_info.get('maquina_causadora')} ({motivo_info.get('localizacao_linha')}) | Segue no CLP: {cor_hab}{hab_txt}{rst} | Watchdog HB: {hb_status}")
    if telemetria_status:
        print(f" 📡 {bold}TELEMETRIA INFLUXDB:{rst} {telemetria_status}")
    if telemetria_motivo_falha:
        print(f" ⚠️  {yellow}{bold}MOTIVO FALHA INFLUXDB:{rst} {telemetria_motivo_falha}")
    if not segue_habilitado:
        print(f" ⚠️  {red}{bold}AVISO:{rst} Setpoint NÃO gravado no CLP pois o Segue está DESABILITADO no CLP.")
    elif modo_sombra:
        print(f" ⚠️  {yellow}{bold}AVISO:{rst} Setpoint NÃO gravado no CLP pois o MODO SOMBRA está ativo.")
    print(sep + "\n")


class ClienteOPCV4:
    def __init__(
        self,
        caminho_config: str,
        modo_sombra: Optional[bool] = None,
        escrever_hb_sombra: Optional[bool] = None,
        telemetria_override: Optional[Dict[str, Any]] = None
    ):
        self.caminho_config = caminho_config
        self.config = self._carregar_config(caminho_config)
        
        # 1. Configuração do Gerenciador Geométrico de Buffers
        self.gerenciador_buffers = GerenciadorBuffers()
        self.gerenciador_buffers.configurar_a_partir_do_dict(self.config)

        # Suporte automático para carregar variáveis de arquivo .env local caso exista (zero dependências)
        for dir_busca in [DIRETORIO_ATUAL, os.getcwd(), os.path.dirname(DIRETORIO_ATUAL)]:
            caminho_env = os.path.join(dir_busca, ".env")
            if os.path.isfile(caminho_env):
                try:
                    with open(caminho_env, "r", encoding="utf-8") as fe:
                        for linha in fe:
                            linha = linha.strip()
                            if not linha or linha.startswith("#") or "=" not in linha:
                                continue
                            k, v_val = linha.split("=", 1)
                            k = k.strip()
                            v_val = v_val.strip().strip("'\"")
                            if k not in os.environ:
                                os.environ[k] = v_val
                    break
                except Exception:
                    pass

        # 2. Configuração do Controlador V4
        cfg_ctrl = dict(self.config.get("controle", {}))

        # Função auxiliar para buscar variável de ambiente (case-insensitive e múltiplos apelidos)
        def _get_env(*keys: str) -> Optional[str]:
            for key in keys:
                if key.upper() in os.environ:
                    return os.environ[key.upper()]
                if key.lower() in os.environ:
                    return os.environ[key.lower()]
                if key in os.environ:
                    return os.environ[key]
            return None

        # Prioridade 1: Suporte a JSON completo em ENV (CONFIG_CONTROLE_JSON ou CONTROLE_JSON)
        env_ctrl_json = _get_env("CONFIG_CONTROLE_JSON", "CONTROLE_JSON")
        if env_ctrl_json:
            try:
                override_ctrl = json.loads(env_ctrl_json)
                if isinstance(override_ctrl, dict):
                    # Normaliza as chaves do JSON para minúsculas
                    override_norm = {str(k).lower(): v for k, v in override_ctrl.items()}
                    cfg_ctrl.update(override_norm)
                    logger.info("⚙️ Bloco 'controle' sobrescrito via variável de ambiente JSON (ENV).")
            except Exception as e:
                logger.error(f"⚠️ Erro ao decodificar JSON da variável de ambiente: {e}. Mantendo config_opc_v4.json.")

        # Prioridade 2: Suporte a variáveis individuais (tanto MAIÚSCULAS quanto minúsculas, aceita sinônimos)
        v = _get_env("CICLO_CONTROLE_S")
        if v is not None:
            cfg_ctrl["ciclo_controle_s"] = float(v)
        v = _get_env("TEMPO_RAMPA_SUBIDA_S")
        if v is not None:
            cfg_ctrl["tempo_rampa_subida_s"] = float(v)
        v = _get_env("TEMPO_RAMPA_DESCIDA_S")
        if v is not None:
            cfg_ctrl["tempo_rampa_descida_s"] = float(v)
        v = _get_env("BANDA_MORTA_CPH")
        if v is not None:
            cfg_ctrl["banda_morta_cph"] = float(v)
        v = _get_env("FATOR_SPRINT")
        if v is not None:
            cfg_ctrl["fator_sprint"] = float(v)
        v = _get_env("MARGEM_SPRINT_B2_LIGA")
        if v is not None:
            cfg_ctrl["margem_sprint_b2_liga"] = float(v)
        v = _get_env("MARGEM_SPRINT_B2_DESLIGA")
        if v is not None:
            cfg_ctrl["margem_sprint_b2_desliga"] = float(v)
        v = _get_env("TEMPO_MINIMO_SPRINT_S")
        if v is not None:
            cfg_ctrl["tempo_minimo_sprint_s"] = float(v)
        v = _get_env("MODO_SOMBRA", "SOMBRA")
        if v is not None:
            cfg_ctrl["modo_sombra"] = v.strip().lower() in ["true", "1", "yes", "ativado", "sim"]
        v = _get_env(
            "ESCREVER_HEARTBEAT_MODO_SOMBRA",
            "ESCREVER_HB_MODO_SOMBRA",
            "HEARTBEAT_MODO_SOMBRA",
            "HB_MODO_SOMBRA",
            "ESCREVER_HEARTBEAT",
            "HABILITAR_HEARTBEAT"
        )
        if v is not None:
            cfg_ctrl["escrever_heartbeat_modo_sombra"] = v.strip().lower() in ["true", "1", "yes", "ativado", "sim"]

        cfg_maq = self.config.get("maquinas", {})

        # Herança automática do Otimizador já rodado (parametros_controle_v4.json)
        params_ia = {}
        caminho_params_otimizador = os.path.join(DIRETORIO_ATUAL, "parametros_controle_v4.json")
        if os.path.exists(caminho_params_otimizador):
            try:
                with open(caminho_params_otimizador, "r", encoding="utf-8") as fp:
                    params_ia = json.load(fp)
            except Exception as e:
                logger.warning(f"Não foi possível carregar {caminho_params_otimizador}: {e}")

        # Prioridade da Velocidade Nominal: 1) config_opc_v4.json; 2) Otimizador; 3) 94.500 padrão
        vel_config = cfg_maq.get("velocidade_nominal")
        vel_otimizador = params_ia.get("velocidade_nominal_calculada")
        if vel_config is not None and float(vel_config) > 0:
            self.vel_nom = float(vel_config)
        elif vel_otimizador is not None and float(vel_otimizador) > 0:
            self.vel_nom = float(vel_otimizador)
            logger.info(f"Velocidade nominal herdada do Otimizador: {self.vel_nom:,.0f} CPH")
        else:
            self.vel_nom = 94500.0

        # Herança de rampas e banda morta caso não estejam no config_opc_v4.json ou ENV
        rampa_sub_ia = params_ia.get("tempo_rampa_subida_s", 10.0)
        rampa_desc_ia = params_ia.get("tempo_rampa_descida_s", 8.0)
        banda_morta_ia = params_ia.get("banda_morta_cph", 300.0)

        self.ciclo_controle_s = float(cfg_ctrl.get("ciclo_controle_s", 10.0))
        self.arquivo_eventos = os.path.join(DIRETORIO_ATUAL, cfg_ctrl.get("arquivo_eventos_json", "eventos_motivos_live_v4.json"))

        # Modo Sombra (Segurança operacional Fail-Safe: True por padrão)
        cfg_sombra = bool(cfg_ctrl.get("modo_sombra", True))
        if modo_sombra is not None:
            self.modo_sombra = bool(modo_sombra)
        else:
            self.modo_sombra = cfg_sombra

        cfg_hb_sombra = bool(cfg_ctrl.get("escrever_heartbeat_modo_sombra", False))
        if escrever_hb_sombra is not None:
            self.escrever_hb_sombra = bool(escrever_hb_sombra)
        else:
            self.escrever_hb_sombra = cfg_hb_sombra

        fator_sprint_cfg = float(cfg_ctrl.get("fator_sprint", params_ia.get("fator_sprint", 1.038)))
        margem_liga = float(cfg_ctrl.get("margem_sprint_b2_liga", 15.0))
        margem_desliga = float(cfg_ctrl.get("margem_sprint_b2_desliga", 5.0))
        t_min_sprint = float(cfg_ctrl.get("tempo_minimo_sprint_s", 30.0))

        rampa_sub = float(cfg_ctrl.get("tempo_rampa_subida_s", rampa_sub_ia))
        rampa_desc = float(cfg_ctrl.get("tempo_rampa_descida_s", rampa_desc_ia))
        banda_morta = float(cfg_ctrl.get("banda_morta_cph", banda_morta_ia))

        self.controlador = ControladorVelocidadeV4(
            velocidade_nominal=self.vel_nom,
            tempo_rampa_subida_s=rampa_sub,
            tempo_rampa_descida_s=rampa_desc,
            banda_morta_cph=banda_morta,
            fator_sprint=fator_sprint_cfg,
            margem_sprint_b2_liga=margem_liga,
            margem_sprint_b2_desliga=margem_desliga,
            tempo_minimo_sprint_s=t_min_sprint
        )

        logger.info(
            f"⚙️ Parâmetros de controle ativos: ciclo={self.ciclo_controle_s}s, "
            f"rampa_sub={rampa_sub}s, rampa_desc={rampa_desc}s, banda_morta={banda_morta:.0f} CPH, "
            f"fator_sprint={fator_sprint_cfg:.3f}, b2_liga=+{margem_liga:.1f}%, b2_desliga=+{margem_desliga:.1f}%, "
            f"t_min_sprint={t_min_sprint:.1f}s, modo_sombra={self.modo_sombra}, hb_sombra={self.escrever_hb_sombra}"
        )

        # 3. Estado interno compartilhado
        self.estado = EstadoLinha(self.vel_nom)
        self.mapa_nos_para_tags: Dict[str, str] = {}
        self.client: Optional[Client] = None
        self.running = False

        # 4. Telemetria e Gravação no InfluxDB (Porta 8086 / localhost, substitui CSV)
        cfg_telemetria = dict(self.config.get("telemetria_influx", self.config.get("telemetria_grafana", {})))
        if telemetria_override:
            for k, v in telemetria_override.items():
                if v is not None:
                    cfg_telemetria[k] = v
        self.gravador_grafana = GravadorGrafanaV4(cfg_telemetria)
        if self.gravador_grafana.habilitado:
            alvo = f"Influx: {self.gravador_grafana.influx_url} (DB: {self.gravador_grafana.database})" if self.gravador_grafana.influx_url else f"Grafana: {self.gravador_grafana.grafana_url}"
            logger.info(
                f"[Telemetria InfluxDB] Ativa: Destino Medição='{self.gravador_grafana.measurement_destino}' "
                f"no DB='{self.gravador_grafana.database}' ({alvo})"
            )
        else:
            logger.info("[Telemetria InfluxDB] Desativada por configuração.")

    def _carregar_config(self, caminho: str) -> Dict[str, Any]:
        if not os.path.exists(caminho):
            raise FileNotFoundError(f"Arquivo de configuração não encontrado: {caminho}")
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)

    async def _conectar_e_inscrever(self):
        """Conecta ao servidor OPC UA e registra todas as assinaturas (Subscription)."""
        cfg_srv = self.config.get("servidor_opc", {})
        url = cfg_srv.get("url", "opc.tcp://127.0.0.1:4840/freeopcua/server/")
        timeout = float(cfg_srv.get("timeout_s", 5.0))
        pub_interval = float(cfg_srv.get("publishing_interval_ms", 500))

        logger.info(f"Conectando ao servidor OPC UA: {url} (Timeout: {timeout}s)...")
        self.client = Client(url=url, timeout=timeout)

        usuario = cfg_srv.get("usuario") or os.environ.get("OPC_USER")
        senha = cfg_srv.get("senha") or os.environ.get("OPC_PASSWORD")
        if usuario:
            self.client.set_user(usuario)
            if senha:
                self.client.set_password(senha)
            logger.info(f"Autenticação OPC UA: Usuário '{usuario}' configurado.")
        else:
            logger.info("Autenticação OPC UA: Anônima (None).")

        await self.client.connect()
        logger.info("Conexão OPC UA estabelecida com sucesso!")

        # Mapeamento e criação do Subscription
        handler = SubscricaoHandler(
            self.gerenciador_buffers,
            self.estado,
            self.mapa_nos_para_tags,
            self.config.get("maquinas", {})
        )
        subscription = await self.client.create_subscription(pub_interval, handler)

        nos_para_inscrever = []

        # 1. Tags dos sensores de buffer
        tags_sensores = self.gerenciador_buffers.obter_todas_as_tags_sensores()
        for tag in tags_sensores:
            try:
                node = self.client.get_node(tag)
                # Lê valor inicial síncrono
                val_ini = await node.read_value()
                self.gerenciador_buffers.atualizar_valor_sensor(tag, val_ini)
                self.mapa_nos_para_tags[node.nodeid.to_string()] = tag
                nos_para_inscrever.append(node)
            except Exception as e:
                logger.warning(f"Não foi possível ler/inscrever tag de sensor '{tag}': {e}")

        # 2. Tags de velocidades das máquinas
        cfg_maq = self.config.get("maquinas", {})
        for chave in ["tag_velocidade_montante", "tag_velocidade_atual", "tag_velocidade_jusante"]:
            tag_maq = cfg_maq.get(chave, "").strip()
            if tag_maq:
                try:
                    node = self.client.get_node(tag_maq)
                    val_ini = await node.read_value()
                    if chave == "tag_velocidade_montante": self.estado.v_in = float(val_ini)
                    elif chave == "tag_velocidade_atual": self.estado.v_atual = float(val_ini)
                    elif chave == "tag_velocidade_jusante": self.estado.v_out = float(val_ini)
                    self.mapa_nos_para_tags[node.nodeid.to_string()] = tag_maq
                    nos_para_inscrever.append(node)
                except Exception as e:
                    logger.warning(f"Não foi possível ler/inscrever tag de máquina '{tag_maq}': {e}")

        # 3. Tag de habilitação do Segue no CLP
        tag_hab = cfg_maq.get("tag_segue_habilitado", "").strip()
        if tag_hab:
            try:
                node = self.client.get_node(tag_hab)
                val_ini = await node.read_value()
                self.estado.segue_habilitado = bool(val_ini)
                self.mapa_nos_para_tags[node.nodeid.to_string()] = tag_hab
                nos_para_inscrever.append(node)
                logger.info(f"Status inicial de 'Segue Habilitado' no CLP: {self.estado.segue_habilitado}")
            except Exception as e:
                self.estado.segue_habilitado = False
                logger.warning(f"Não foi possível ler/inscrever tag_segue_habilitado '{tag_hab}': {e} -> Mantendo segue_habilitado=False")
        else:
            # Se a tag de intertravamento de habilitação não foi configurada, assume habilitado (governado por modo_sombra)
            self.estado.segue_habilitado = True
            logger.info("Tag 'tag_segue_habilitado' não configurada no JSON: modulação considerada habilitada (governada por modo_sombra).")

        # 4. Tag de status operacional da máquina no CLP
        tag_status = cfg_maq.get("tag_status_maquina", "").strip()
        if tag_status:
            try:
                node = self.client.get_node(tag_status)
                val_ini = await node.read_value()
                self.estado.status_maquina = bool(val_ini) if val_ini is not None else True
                self.mapa_nos_para_tags[node.nodeid.to_string()] = tag_status
                nos_para_inscrever.append(node)
                logger.info(f"Status inicial de 'Status da Máquina' no CLP: {self.estado.status_maquina}")
            except Exception as e:
                self.estado.status_maquina = True
                logger.warning(f"Não foi possível ler/inscrever tag_status_maquina '{tag_status}': {e} -> Mantendo status_maquina=True")
        else:
            self.estado.status_maquina = True

        if nos_para_inscrever:
            await subscription.subscribe_data_change(nos_para_inscrever)
            logger.info(f"Subscrição (DataChange) ativada para {len(nos_para_inscrever)} tags da linha.")
        else:
            logger.warning("Nenhuma tag válida encontrada para subscrição.")

    async def _escrever_valor_node(self, node, val: ua.Variant):
        """
        Escreve o valor no nó OPC UA de forma compatível com CLPs e servidores industriais.
        Evita o erro 'BadWriteNotSupported' enviando puramente o atributo Valor
        (sem timestamps nem StatusCode, já que o CLP não aceita timestamp de clientes).
        """
        try:
            dv = ua.DataValue(Value=val, StatusCode_=None, SourceTimestamp=None, ServerTimestamp=None)
            await node.write_attribute(ua.AttributeIds.Value, dv)
        except Exception as e:
            if "BadWriteNotSupported" in str(e) or "BadWrite" in str(e):
                await node.write_value(val)
            else:
                raise

    async def _loop_heartbeat(self):
        """Loop paralelo e independente para manter o watchdog do CLP vivo."""
        cfg_hb = self.config.get("heartbeat", {})
        tag_hb = cfg_hb.get("tag", "").strip()
        intervalo = max(0.2, float(cfg_hb.get("intervalo_s", 1.0)))
        modo = cfg_hb.get("modo", "pulse_one").lower()

        if not tag_hb:
            logger.info("Watchdog de Heartbeat desativado (tag não configurada).")
            return

        if self.modo_sombra and not self.escrever_hb_sombra:
            logger.info("Modo Sombra ativo: Escrita de Heartbeat no CLP desativada (Apenas Leitura).")
            while self.running:
                await asyncio.sleep(intervalo)
            return

        logger.info(f"Iniciando Watchdog Heartbeat na tag '{tag_hb}' a cada {intervalo}s (Modo: {modo}).")
        tipo_hb_cache = None
        falhas_consecutivas = 0

        while self.running:
            try:
                if self.client:
                    node_hb = self.client.get_node(tag_hb)
                    if tipo_hb_cache is None:
                        try:
                            dv = await node_hb.read_data_value()
                            if dv and dv.Value and dv.Value.VariantType:
                                tipo_hb_cache = dv.Value.VariantType
                        except Exception:
                            tipo_hb_cache = ua.VariantType.Int16

                    if modo == "counter":
                        self.estado.heartbeat_counter = (self.estado.heartbeat_counter + 1) % 32767
                        vtype = tipo_hb_cache if tipo_hb_cache in [ua.VariantType.Int16, ua.VariantType.Int32, ua.VariantType.UInt16, ua.VariantType.UInt32] else ua.VariantType.Int16
                        val_escrever = ua.Variant(self.estado.heartbeat_counter, vtype)
                    elif modo == "toggle":
                        self.estado.heartbeat_val = not self.estado.heartbeat_val
                        val_escrever = ua.Variant(bool(self.estado.heartbeat_val), ua.VariantType.Boolean)
                    else:
                        # Modo padrão industrial: 'pulse_one' (Sempre escreve 1 e o CLP zera)
                        self.estado.heartbeat_counter += 1
                        self.estado.heartbeat_val = 1
                        if tipo_hb_cache in [ua.VariantType.Int16, ua.VariantType.Int32, ua.VariantType.UInt16, ua.VariantType.UInt32]:
                            val_escrever = ua.Variant(1, tipo_hb_cache)
                        elif tipo_hb_cache == ua.VariantType.Boolean:
                            val_escrever = ua.Variant(True, ua.VariantType.Boolean)
                        else:
                            val_escrever = ua.Variant(1, ua.VariantType.Int16)

                    await self._escrever_valor_node(node_hb, val_escrever)
                    falhas_consecutivas = 0
            except (ConnectionError, BrokenPipeError, OSError, asyncio.TimeoutError) as e:
                logger.error(f"Conexão perdida durante envio do Heartbeat: {e}")
                raise
            except Exception as e:
                falhas_consecutivas += 1
                logger.warning(f"Falha na escrita do Heartbeat ({falhas_consecutivas}/3): {e}")
                if falhas_consecutivas >= 3:
                    raise ConnectionError(f"Heartbeat falhou 3 vezes consecutivas: {e}")
            await asyncio.sleep(intervalo)

    async def _escrever_setpoint_plc(self, velocidade_cph: float):
        """Escreve o setpoint otimizado no CLP adaptando automaticamente o tipo de dado."""
        if not self.estado.segue_habilitado:
            logger.debug("[SEGUE DESABILITADO] Modulação desativada no CLP. Escrita de setpoint ignorada.")
            return

        pct_calc = (velocidade_cph / max(1.0, self.vel_nom)) * 100.0
        if self.modo_sombra:
            logger.debug(f"[MODO SOMBRA] Setpoint {pct_calc:.1f}% ({velocidade_cph:.0f} CPH) calculado (Escrita no CLP ignorada).")
            return

        cfg_maq = self.config.get("maquinas", {})
        tag_sp = cfg_maq.get("tag_escrita_setpoint", "").strip()
        if not tag_sp or not self.client:
            return

        unidade_sp = str(cfg_maq.get("unidade_escrita_setpoint", "percentual")).strip().lower()
        if unidade_sp in ["percentual", "pct", "%"]:
            val_escrever_num = pct_calc
            texto_unidade = f"{val_escrever_num:.1f}% ({velocidade_cph:.0f} CPH)"
        else:
            val_escrever_num = velocidade_cph
            texto_unidade = f"{velocidade_cph:.0f} CPH"

        try:
            node_sp = self.client.get_node(tag_sp)
            if not hasattr(self, "_tipo_sp_cache") or self._tipo_sp_cache is None:
                try:
                    dv = await node_sp.read_data_value()
                    if dv and dv.Value and dv.Value.VariantType:
                        self._tipo_sp_cache = dv.Value.VariantType
                    else:
                        self._tipo_sp_cache = ua.VariantType.Double
                except Exception:
                    self._tipo_sp_cache = ua.VariantType.Double

            vtype = self._tipo_sp_cache
            if vtype in [ua.VariantType.Int16, ua.VariantType.Int32, ua.VariantType.Int64, ua.VariantType.UInt16, ua.VariantType.UInt32]:
                val_escrever = ua.Variant(int(round(val_escrever_num)), vtype)
            elif vtype == ua.VariantType.Float:
                val_escrever = ua.Variant(float(round(val_escrever_num, 2)), ua.VariantType.Float)
            else:
                val_escrever = ua.Variant(float(round(val_escrever_num, 2)), ua.VariantType.Double)

            await self._escrever_valor_node(node_sp, val_escrever)
            logger.info(f"[CLP] Setpoint escrito com sucesso: {texto_unidade} na tag '{tag_sp}'")
        except (ConnectionError, BrokenPipeError, OSError, asyncio.TimeoutError) as e:
            logger.error(f"Erro fatal de conexão ao escrever Setpoint de velocidade: {e}")
            raise
        except Exception as e:
            logger.error(f"Erro ao escrever Setpoint de velocidade '{texto_unidade}' na tag '{tag_sp}': {e}")
            raise

    async def _loop_controle(self):
        """Loop principal de controle: lê buffers acumulados, calcula velocidade e escreve setpoint."""
        logger.info(f"Iniciando Loop de Otimização e Controle V4 (Ciclo: {self.ciclo_controle_s}s)...")

        while self.running:
            try:
                inicio_ciclo = asyncio.get_event_loop().time()
                agora_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 1. Calcula o nível percentual consolidado de cada buffer a partir dos sensores
                niveis = self.gerenciador_buffers.calcular_todos_os_niveis()
                b1, b2, b3, b4 = niveis["b1"], niveis["b2"], niveis["b3"], niveis["b4"]

                # 2. Obtém velocidades atuais das máquinas vizinhas e da enchedora
                vin = self.estado.v_in
                vout = self.estado.v_out
                vatual = self.estado.v_atual

                # 3. Invoca o algoritmo e modelo do Controlador V4 (incluindo Trava de Segurança do Sprint por v_atual)
                vel_calculada, motivo_id = self.controlador.calcular_velocidade(
                    b1=b1, b2=b2, b3=b3, b4=b4,
                    v_in=vin, v_out=vout, v_atual=vatual,
                    delta_t_s=self.ciclo_controle_s,
                    retornar_motivo=True,
                    timestamp=agora_str,
                    registrar_evento=True,
                    arquivo_json=self.arquivo_eventos
                )
                self.estado.v_setpoint_calculado = vel_calculada
                self.estado.ultimo_motivo_id = motivo_id

                # Nota operacional: status_maquina é mantido estritamente para diagnóstico e telemetria (Grafana/InfluxDB).
                # O setpoint calculado permanece pronto e disponível no CLP para que a enchedora parta imediatamente sem atrasos.

                # 4. Escreve o setpoint de velocidade no CLP
                await self._escrever_setpoint_plc(vel_calculada)

                info_motivo = self.controlador.obter_motivo(motivo_id)

                # 4.1 Determina status do Heartbeat Watchdog
                if self.modo_sombra and not self.escrever_hb_sombra:
                    hb_status = "Desativado (Modo Sombra)"
                elif self.config.get("heartbeat", {}).get("modo", "pulse_one").lower() == "counter":
                    hb_status = f"{self.estado.heartbeat_counter}"
                elif self.config.get("heartbeat", {}).get("modo", "pulse_one").lower() == "toggle":
                    hb_status = f"{self.estado.heartbeat_val}"
                else:
                    hb_status = f"1 (Pulso #{self.estado.heartbeat_counter})"

                # 4.2 Gravação de Telemetria no Grafana / InfluxDB (em medição dedicada, substituindo CSV)
                def _nivel_para_telemetria(buf_id: str, val_calc: float) -> float:
                    buf = self.gerenciador_buffers.buffers.get(buf_id)
                    return val_calc if (buf and buf.setores) else 0.0

                b1_tel = _nivel_para_telemetria("b1", b1)
                b2_tel = _nivel_para_telemetria("b2", b2)
                b3_tel = _nivel_para_telemetria("b3", b3)
                b4_tel = _nivel_para_telemetria("b4", b4)

                if self.gravador_grafana.habilitado:
                    ponto_lp = self.gravador_grafana.preparar_ponto_ciclo(
                        linha_info=self.config.get("identificacao_linha", {}),
                        b1=b1_tel, b2=b2_tel, b3=b3_tel, b4=b4_tel,
                        v_in=vin, v_atual=self.estado.v_atual, v_out=vout,
                        v_setpoint=vel_calculada, vel_nom=self.vel_nom,
                        motivo_id=motivo_id, motivo_info=info_motivo,
                        modo_sombra=self.modo_sombra,
                        segue_habilitado=self.estado.segue_habilitado,
                        hb_status=hb_status,
                        heartbeat_counter=self.estado.heartbeat_counter,
                        total_eventos_opc=self.estado.total_eventos_recebidos,
                        status_maquina=self.estado.status_maquina
                    )
                    # Envio não-bloqueante em background: nunca atrasa o loop de controle nem o watchdog do CLP
                    asyncio.create_task(self.gravador_grafana.enviar_ponto_async(ponto_lp))

                # 5. Apresentação e diagnóstico operacional via Fluxograma Sinótico no Terminal

                motivo_falha = None
                if self.gravador_grafana.habilitado:
                    st_envio = self.gravador_grafana.ultimo_status_envio
                    alvo_host = self.gravador_grafana.influx_url or self.gravador_grafana.grafana_url
                    telemetria_info = (
                        f"Medição: '{self.gravador_grafana.measurement_destino}' ({self.gravador_grafana.database}) | "
                        f"Alvo: {alvo_host} | "
                        f"Status: {st_envio} | Gravados: {self.gravador_grafana.total_enviados} | "
                        f"Falhas: {self.gravador_grafana.total_falhas}"
                    )
                    if self.gravador_grafana.falhas_consecutivas > 0 and self.gravador_grafana.ultimo_motivo_falha:
                        motivo_falha = self.gravador_grafana.ultimo_motivo_falha
                else:
                    telemetria_info = "Desativada (Configuração)"

                buffers_ativos = {
                    "b1": bool(self.gerenciador_buffers.buffers.get("b1") and self.gerenciador_buffers.buffers["b1"].setores),
                    "b2": bool(self.gerenciador_buffers.buffers.get("b2") and self.gerenciador_buffers.buffers["b2"].setores),
                    "b3": bool(self.gerenciador_buffers.buffers.get("b3") and self.gerenciador_buffers.buffers["b3"].setores),
                    "b4": bool(self.gerenciador_buffers.buffers.get("b4") and self.gerenciador_buffers.buffers["b4"].setores),
                }

                linha_info = self.config.get("identificacao_linha", {})
                desenhar_fluxograma_terminal(
                    timestamp=agora_str,
                    linha_info=linha_info,
                    b1=b1_tel, b2=b2_tel, b3=b3_tel, b4=b4_tel,
                    v_in=vin, v_atual=self.estado.v_atual, v_out=vout,
                    vel_calculada=vel_calculada, vel_nom=self.vel_nom,
                    motivo_info=info_motivo,
                    modo_sombra=self.modo_sombra,
                    hb_status=hb_status,
                    segue_habilitado=self.estado.segue_habilitado,
                    telemetria_status=telemetria_info,
                    telemetria_motivo_falha=motivo_falha,
                    buffers_ativos=buffers_ativos
                )

                # Log formal estruturado (visível em docker logs e sistemas de monitoramento)
                status_hab = "SIM" if self.estado.segue_habilitado else "NAO_BYPASS"
                pct_calc = round((vel_calculada / self.vel_nom) * 100.0, 1)
                med_str = self.gravador_grafana.measurement_destino if self.gravador_grafana.habilitado else "N/A"
                logger.info(
                    f"[CICLO] SP={vel_calculada:,.0f} CPH ({pct_calc}%) | Real={self.estado.v_atual:,.0f} CPH | "
                    f"Segue_Hab={status_hab} | Sombra={self.modo_sombra} | Medicao_Influx={med_str} | Motivo={info_motivo.get('codigo', 'N/A')}"
                )

                tempo_gasto = asyncio.get_event_loop().time() - inicio_ciclo
                tempo_espera = max(0.1, self.ciclo_controle_s - tempo_gasto)
                await asyncio.sleep(tempo_espera)

            except (ConnectionError, BrokenPipeError, OSError, asyncio.TimeoutError) as e:
                logger.error(f"Conexão perdida durante ciclo de controle: {e}")
                raise
            except Exception as e:
                logger.error(f"Erro durante execução do ciclo de controle: {e}")
                raise

    async def executar(self):
        """Gerencia o ciclo de vida completo da aplicação, incluindo reconexão automática."""
        self.running = True
        cfg_srv = self.config.get("servidor_opc", {})
        reconectar_delay = float(cfg_srv.get("reconectar_delay_s", 3.0))

        if self.modo_sombra:
            logger.info("=" * 60)
            logger.info("   INICIANDO EM MODO SOMBRA (SHADOW MODE)")
            logger.info("   Leitura e cálculos ativos, escrita no CLP bloqueada.")
            logger.info("=" * 60)

        while self.running:
            try:
                self._tipo_sp_cache = None
                self.mapa_nos_para_tags.clear()
                await self._conectar_e_inscrever()

                # Dispara as duas tarefas concorrentes: Watchdog e Loop de Controle
                task_hb = asyncio.create_task(self._loop_heartbeat())
                task_ctrl = asyncio.create_task(self._loop_controle())

                done, pending = await asyncio.wait(
                    [task_hb, task_ctrl],
                    return_when=asyncio.FIRST_EXCEPTION
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    exc = task.exception()
                    if exc:
                        raise exc

            except (asyncio.CancelledError, KeyboardInterrupt):
                logger.info("Encerrando execução do cliente OPC UA...")
                break
            except Exception as e:
                logger.error(f"Queda na comunicação OPC UA: {e}. Tentando reconectar em {reconectar_delay}s...")
                try:
                    if self.client:
                        await self.client.disconnect()
                except Exception:
                    pass
                self.client = None
                await asyncio.sleep(reconectar_delay)

        self.parar()

    def parar(self):
        """Finalização segura do processo e gravação final de eventos."""
        self.running = False
        agora_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.controlador.finalizar_eventos(timestamp=agora_str, arquivo_json=self.arquivo_eventos)
        logger.info(f"Cliente finalizado. Eventos salvos em '{self.arquivo_eventos}'.")


def main():
    parser = argparse.ArgumentParser(description="Cliente OPC UA Subscription e Controle V4")
    parser.add_argument("--config", default=os.path.join(DIRETORIO_ATUAL, "config_opc_v4.json"), help="Caminho do arquivo config_opc_v4.json")
    parser.add_argument("--modo-sombra", "--sombra", "--shadow", "--dry-run", action="store_true", default=None, help="Força execução em modo sombra (apenas leitura, sem escrever no CLP)")
    parser.add_argument("--modo-ativo", "--ativo", action="store_true", default=False, help="Executa em modo ativo de produção (habilita escrita de setpoint no CLP)")
    parser.add_argument("--measurement", default=None, help="Sobrescreve a measurement de gravação no InfluxDB (ex: 512_v4)")
    parser.add_argument("--influx-url", default=None, help="Sobrescreve a URL base do InfluxDB direto (ex: http://localhost:8086)")
    parser.add_argument("--database", "--bucket", default=None, help="Sobrescreve o banco/database do InfluxDB (ex: Segue)")
    parser.add_argument("--grafana-url", default=None, help="Sobrescreve a URL base do Grafana (fallback secundário)")
    parser.add_argument("--escrever-hb-sombra", "--escrever-heartbeat-sombra", "--hb-sombra", "--habilitar-hb", action="store_true", default=None, help="Habilita escrita de watchdog heartbeat no CLP mesmo em modo sombra")
    parser.add_argument("--sem-influx", "--sem-grafana", "--sem-telemetria", dest="sem_telemetria", action="store_true", default=False, help="Desativa o envio de telemetria")
    args = parser.parse_args()

    if not TEM_ASYNCUA:
        print("\n❌ ERRO: A biblioteca 'asyncua' não está instalada no ambiente.")
        print("Instale executando:")
        print("   pip install asyncua\n")
        sys.exit(1)

    if args.modo_ativo:
        modo_sombra = False
    elif args.modo_sombra is True:
        modo_sombra = True
    else:
        modo_sombra = None  # Respeita ENV MODO_SOMBRA ou config_opc_v4.json (default True)

    telemetria_override = {}
    if args.measurement:
        telemetria_override["measurement_destino"] = args.measurement
    if args.influx_url:
        telemetria_override["influx_url"] = args.influx_url
    if args.database:
        telemetria_override["database"] = args.database
    if args.grafana_url:
        telemetria_override["grafana_url"] = args.grafana_url
    if getattr(args, "sem_telemetria", False):
        telemetria_override["habilitado"] = False

    cliente = ClienteOPCV4(
        caminho_config=args.config,
        modo_sombra=modo_sombra,
        escrever_hb_sombra=args.escrever_hb_sombra,
        telemetria_override=telemetria_override if telemetria_override else None
    )
    try:
        asyncio.run(cliente.executar())
    except KeyboardInterrupt:
        cliente.parar()
        print("\nSessão encerrada pelo operador.")


if __name__ == "__main__":
    main()
