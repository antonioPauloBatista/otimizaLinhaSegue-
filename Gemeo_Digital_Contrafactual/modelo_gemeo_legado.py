# -*- coding: utf-8 -*-
"""
GÊMEO DIGITAL CONTRAFACTUAL DA LINHA LEGADA (PRÉ-V4)
Modelo Dinâmico Caixa-Cinza (Grey-Box) em Malha Fechada com Balanço de Massa,
Sensores Discretos de Esteira e Autômato Finito PackML do CLP Legado.
Compatível diretamente com o schema do config.json (idêntico ao Controle_Velocidade_4).

Autor: Equipe de Engenharia / Antigravity
Data: 2026-10-03
"""

import os
import json
from typing import Dict, Any, Optional, Tuple, List
from gerenciador_buffers import GerenciadorBuffers, BufferGeometrico, SetorEsteira


class GemeoDigitalLegado:
    """
    Simula em tempo real qual seria a velocidade da Enchedora e o estado de CADA SENSOR
    caso o CLP legado (política liga/desliga com histerese, temporizadores TON e sensores discretos)
    ainda estivesse no controle da linha, sob os mesmos distúrbios operacionais reais.
    """

    def __init__(
        self,
        config_dict: Optional[Dict[str, Any]] = None,
        caminho_config_json: Optional[str] = None,
        velocidade_nominal: float = 90000.0,
        capacidade_garrafas_b2: float = 2800.0,
        capacidade_garrafas_b3: float = 3500.0,
        limiar_corte_b3_pct: float = 85.0,
        limiar_retomada_b3_pct: float = 65.0,
        limiar_corte_b2_pct: float = 15.0,
        limiar_retomada_b2_pct: float = 35.0,
        ton_bloqueio_s: float = 2.0,
        ton_retomada_s: float = 2.0,
        tempo_rampa_subida_s: float = 15.0,
        tempo_rampa_descida_s: float = 8.0,
        tempo_ancoragem_parada_real_s: float = 300.0,
        volume_garrafa_litros: float = 0.355,
        b2_inicial_pct: float = 50.0,
        b3_inicial_pct: float = 50.0,
        v_legado_inicial: float = 0.0
    ):
        # 1. Carrega configuração caso fornecido config_dict ou caminho JSON
        cfg = {}
        if config_dict is not None:
            cfg = config_dict
        elif caminho_config_json is not None and os.path.exists(caminho_config_json):
            try:
                with open(caminho_config_json, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}

        # 2. Inicializa o Gerenciador de Buffers Geométrico (Mapeamento de Cada Sensor)
        self.gerenciador_buffers = GerenciadorBuffers()
        if cfg:
            self.gerenciador_buffers.configurar_a_partir_do_dict(cfg)

        cfg_maq = cfg.get("maquinas", {})
        cfg_leg = cfg.get("parametros_legado", {})
        cfg_buf = cfg.get("buffers_capacidade", {})
        cfg_aud = cfg.get("auditoria_envase", {})
        cfg_ctrl = cfg.get("controle", {})

        # Parâmetros de Projeto da Linha (prioriza config.json)
        self.vel_nominal = float(cfg_maq.get("velocidade_nominal", velocidade_nominal))
        self.cap_b2 = float(cfg_buf.get("capacidade_garrafas_b2", capacidade_garrafas_b2))
        self.cap_b3 = float(cfg_buf.get("capacidade_garrafas_b3", capacidade_garrafas_b3))
        self.volume_garrafa_l = float(cfg_aud.get("volume_garrafa_litros", volume_garrafa_litros))

        # Limiares de Intertravamento do CLP Legado
        self.limiar_corte_b3 = float(cfg_leg.get("limiar_corte_b3_pct", limiar_corte_b3_pct))
        self.limiar_retomada_b3 = float(cfg_leg.get("limiar_retomada_b3_pct", limiar_retomada_b3_pct))
        self.limiar_corte_b2 = float(cfg_leg.get("limiar_corte_b2_pct", limiar_corte_b2_pct))
        self.limiar_retomada_b2 = float(cfg_leg.get("limiar_retomada_b2_pct", limiar_retomada_b2_pct))

        # Temporizadores TON
        self.ton_bloqueio_s = float(cfg_leg.get("ton_bloqueio_s", ton_bloqueio_s))
        self.ton_retomada_s = float(cfg_leg.get("ton_retomada_s", ton_retomada_s))

        # Dinâmica Mecânica do Inversor Legado (prioriza parametros_legado)
        if "tempo_rampa_subida_s" in cfg_leg:
            self.tempo_rampa_subida_s = float(cfg_leg["tempo_rampa_subida_s"])
        elif tempo_rampa_subida_s is not None:
            self.tempo_rampa_subida_s = float(tempo_rampa_subida_s)
        elif "tempo_rampa_subida_s" in cfg_ctrl:
            self.tempo_rampa_subida_s = float(cfg_ctrl["tempo_rampa_subida_s"])
        else:
            self.tempo_rampa_subida_s = 15.0

        if "tempo_rampa_descida_s" in cfg_leg:
            self.tempo_rampa_descida_s = float(cfg_leg["tempo_rampa_descida_s"])
        elif tempo_rampa_descida_s is not None:
            self.tempo_rampa_descida_s = float(tempo_rampa_descida_s)
        elif "tempo_rampa_descida_s" in cfg_ctrl:
            self.tempo_rampa_descida_s = float(cfg_ctrl["tempo_rampa_descida_s"])
        else:
            self.tempo_rampa_descida_s = 8.0

        self.taxa_subida_cph_s = self.vel_nominal / max(0.1, self.tempo_rampa_subida_s)
        self.taxa_descida_cph_s = self.vel_nominal / max(0.1, self.tempo_rampa_descida_s)

        # Ancoragem Determinística (PackML) para Cancelamento de Drift
        self.tempo_ancoragem_parada_real_s = float(cfg_leg.get("tempo_ancoragem_parada_real_s", tempo_ancoragem_parada_real_s))

        # Estados Internos do Buffer Virtual
        self.b2_virt = float(b2_inicial_pct)
        self.b3_virt = float(b3_inicial_pct)
        self.v_legado = float(v_legado_inicial)
        self.v_alvo_legado = float(v_legado_inicial)
        self.estado_legado = "RODANDO"

        # Temporizadores de Condição (TON em software)
        self.timer_bloqueio_b3_s = 0.0
        self.timer_retomada_b3_s = 0.0
        self.timer_bloqueio_b2_s = 0.0
        self.timer_retomada_b2_s = 0.0

        # Rastreamento de Parada Real e Ancoragem
        self.tempo_parada_real_continua_s = 0.0
        self.ancoragem_ativa = False

        # Métricas de Auditoria Contrafactual Integrada
        self.garrafas_real_total = 0.0
        self.garrafas_legado_total = 0.0
        self.tempo_total_s = 0.0
        self.tempo_real_rodando_s = 0.0
        self.tempo_legado_rodando_s = 0.0
        self.tempo_legado_parado_s = 0.0

        # Rastreamento de Microparadas Evitadas (< 3 minutos)
        self.total_microparadas_evitadas = 0
        self.microparada_em_andamento = False
        self.duracao_microparada_atual_s = 0.0
        self.garrafas_salvas_microparada_atual = 0.0
        self.historico_microparadas_evitadas: List[Dict[str, Any]] = []

    def resetar_metricas(self):
        """Reinicia todos os acumuladores de auditoria."""
        self.garrafas_real_total = 0.0
        self.garrafas_legado_total = 0.0
        self.tempo_total_s = 0.0
        self.tempo_real_rodando_s = 0.0
        self.tempo_legado_rodando_s = 0.0
        self.tempo_legado_parado_s = 0.0
        self.total_microparadas_evitadas = 0
        self.microparada_em_andamento = False
        self.duracao_microparada_atual_s = 0.0
        self.garrafas_salvas_microparada_atual = 0.0
        self.historico_microparadas_evitadas.clear()

    def atualizar_sensor_opc(self, tag: str, valor: Any) -> bool:
        """Repassa a leitura de uma tag de sensor físico para o gerenciador de buffers."""
        return self.gerenciador_buffers.atualizar_valor_sensor(tag, valor)

    def atualizar(
        self,
        v_in: float,
        v_out: float,
        v_real: float,
        b2_real: Optional[float] = None,
        b3_real: Optional[float] = None,
        sensor_acumulo_b3: Optional[bool] = None,
        sensor_falta_b2: Optional[bool] = None,
        status_maquina_real: bool = True,
        delta_t_s: float = 1.0,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executa um ciclo da simulação contrafactual utilizando CADA SENSOR individual.
        """
        v_in = max(0.0, float(v_in))
        v_out = max(0.0, float(v_out))
        v_real = max(0.0, float(v_real))
        delta_t_s = max(0.001, float(delta_t_s))

        # -------------------------------------------------------------
        # BLOCO 3: ANCORAGEM DETERMINÍSTICA E CANCELAMENTO DE DRIFT
        # -------------------------------------------------------------
        real_parada = (v_real < 1000.0)
        falha_interna = (not bool(status_maquina_real))

        if real_parada or falha_interna:
            self.tempo_parada_real_continua_s += delta_t_s
        else:
            self.tempo_parada_real_continua_s = 0.0

        disparo_ancoragem = falha_interna or (self.tempo_parada_real_continua_s >= self.tempo_ancoragem_parada_real_s)

        if disparo_ancoragem:
            self.ancoragem_ativa = True
            self.estado_legado = "PARADA_FALHA_REAL"
            self.v_alvo_legado = 0.0
            self.v_legado = 0.0

            # Reseta os buffers virtuais aos valores reais físicos para neutralizar drift
            if b2_real is not None:
                self.b2_virt = float(b2_real)
            if b3_real is not None:
                self.b3_virt = float(b3_real)

            self.gerenciador_buffers.propagar_niveis_virtuais(self.b2_virt, self.b3_virt)

            self.timer_bloqueio_b3_s = 0.0
            self.timer_retomada_b3_s = 0.0
            self.timer_bloqueio_b2_s = 0.0
            self.timer_retomada_b2_s = 0.0
        else:
            self.ancoragem_ativa = False

            # -------------------------------------------------------------
            # BLOCO 1: DINÂMICA CONTÍNUA (BALANÇO DE MASSA DO BUFFER VIRTUAL)
            # -------------------------------------------------------------
            v_legado_ant = self.v_legado

            # Buffer B2 (Entrada): Alimentado por v_in, drenado por v_legado
            delta_b2_gf = (v_in - v_legado_ant) * (delta_t_s / 3600.0)
            delta_b2_pct = (delta_b2_gf / self.cap_b2) * 100.0
            self.b2_virt = min(100.0, max(0.0, self.b2_virt + delta_b2_pct))

            # Buffer B3 (Saída): Alimentado por v_legado, drenado por v_out
            delta_b3_gf = (v_legado_ant - v_out) * (delta_t_s / 3600.0)
            delta_b3_pct = (delta_b3_gf / self.cap_b3) * 100.0
            self.b3_virt = min(100.0, max(0.0, self.b3_virt + delta_b3_pct))

            # Propaga o estado virtual sobre CADA SENSOR físico de B2 e B3
            self.gerenciador_buffers.propagar_niveis_virtuais(self.b2_virt, self.b3_virt)

            # -------------------------------------------------------------
            # BLOCO 2: DINÂMICA DISCRETA (AUTÔMATO FINITO DO CLP LEGADO)
            # Avalia os Sensores Críticos de Descarga (B3) e Alimentação (B2)
            # -------------------------------------------------------------
            sensor_critico_b3 = self.gerenciador_buffers.buffers["b3"].obter_sensor_extremo_encher()
            sensor_critico_b2 = self.gerenciador_buffers.buffers["b2"].obter_sensor_extremo_encher()

            s_b3_ocupado_fisico = bool(sensor_critico_b3.ocupado_real) if (sensor_critico_b3 and sensor_critico_b3.valor_lido is not None) else False
            s_b3_param = bool(sensor_acumulo_b3) if sensor_acumulo_b3 is not None else False

            cond_bloqueio_b3 = (
                (self.b3_virt >= self.limiar_corte_b3) or
                s_b3_ocupado_fisico or
                s_b3_param
            )
            if cond_bloqueio_b3:
                self.timer_bloqueio_b3_s += delta_t_s
            else:
                self.timer_bloqueio_b3_s = 0.0

            cond_retomada_b3 = (
                (self.b3_virt <= self.limiar_retomada_b3) and
                (not s_b3_ocupado_fisico) and
                (not s_b3_param)
            )
            if cond_retomada_b3:
                self.timer_retomada_b3_s += delta_t_s
            else:
                self.timer_retomada_b3_s = 0.0

            s_b2_vazio_fisico = (not sensor_critico_b2.ocupado_real) if (sensor_critico_b2 and sensor_critico_b2.valor_lido is not None) else False
            s_b2_param = bool(sensor_falta_b2) if sensor_falta_b2 is not None else False

            cond_bloqueio_b2 = (
                (self.b2_virt <= self.limiar_corte_b2) or
                s_b2_vazio_fisico or
                s_b2_param
            )
            if cond_bloqueio_b2:
                self.timer_bloqueio_b2_s += delta_t_s
            else:
                self.timer_bloqueio_b2_s = 0.0

            cond_retomada_b2 = (
                (self.b2_virt >= self.limiar_retomada_b2) and
                (not s_b2_vazio_fisico) and
                (not s_b2_param)
            )
            if cond_retomada_b2:
                self.timer_retomada_b2_s += delta_t_s
            else:
                self.timer_retomada_b2_s = 0.0

            # Transição de Estados PackML
            if self.estado_legado in ("RODANDO", "PARADA_FALHA_REAL"):
                if self.timer_bloqueio_b3_s >= self.ton_bloqueio_s:
                    self.estado_legado = "BLOQUEADO_SAIDA_CHEIA"
                    self.timer_retomada_b3_s = 0.0
                elif self.timer_bloqueio_b2_s >= self.ton_bloqueio_s:
                    self.estado_legado = "BLOQUEADO_ENTRADA_VAZIA"
                    self.timer_retomada_b2_s = 0.0
                else:
                    self.estado_legado = "RODANDO"

            elif self.estado_legado == "BLOQUEADO_SAIDA_CHEIA":
                if (self.timer_retomada_b3_s >= self.ton_retomada_s) and not cond_bloqueio_b2:
                    self.estado_legado = "RODANDO"
                    self.timer_bloqueio_b3_s = 0.0

            elif self.estado_legado == "BLOQUEADO_ENTRADA_VAZIA":
                if (self.timer_retomada_b2_s >= self.ton_retomada_s) and not cond_bloqueio_b3:
                    self.estado_legado = "RODANDO"
                    self.timer_bloqueio_b2_s = 0.0

            # Setpoint Alvo do CLP Legado
            if self.estado_legado == "RODANDO":
                self.v_alvo_legado = self.vel_nominal
            else:
                self.v_alvo_legado = 0.0

            # Rampa Mecânica do Inversor de Frequência Legado
            degrau_max_subida = self.taxa_subida_cph_s * delta_t_s
            degrau_max_descida = self.taxa_descida_cph_s * delta_t_s
            delta_v = self.v_alvo_legado - self.v_legado

            if delta_v > 0.0:
                self.v_legado += min(delta_v, degrau_max_subida)
            elif delta_v < 0.0:
                self.v_legado -= min(abs(delta_v), degrau_max_descida)
            else:
                self.v_legado = self.v_alvo_legado

            self.v_legado = max(0.0, min(self.vel_nominal, round(self.v_legado, 1)))

        # -------------------------------------------------------------
        # BLOCO 4 & 5: CONTABILIDADE CONTRAFACTUAL E AUDITORIA DE GANHO
        # -------------------------------------------------------------
        g_real_ciclo = (v_real * delta_t_s) / 3600.0
        g_legado_ciclo = (self.v_legado * delta_t_s) / 3600.0
        delta_g_ciclo = g_real_ciclo - g_legado_ciclo

        self.garrafas_real_total += g_real_ciclo
        self.garrafas_legado_total += g_legado_ciclo
        self.tempo_total_s += delta_t_s

        if v_real >= 1000.0:
            self.tempo_real_rodando_s += delta_t_s

        if self.v_legado >= 1000.0:
            self.tempo_legado_rodando_s += delta_t_s
        else:
            self.tempo_legado_parado_s += delta_t_s

        microparada_ativa_neste_ciclo = (self.v_legado < 1000.0) and (v_real >= 10000.0) and (not self.ancoragem_ativa)

        if microparada_ativa_neste_ciclo:
            if not self.microparada_em_andamento:
                self.microparada_em_andamento = True
                self.total_microparadas_evitadas += 1
                self.duracao_microparada_atual_s = 0.0
                self.garrafas_salvas_microparada_atual = 0.0

            self.duracao_microparada_atual_s += delta_t_s
            self.garrafas_salvas_microparada_atual += delta_g_ciclo
        else:
            if self.microparada_em_andamento:
                self.microparada_em_andamento = False
                evento = {
                    "inicio": timestamp or "",
                    "duracao_segundos": round(self.duracao_microparada_atual_s, 1),
                    "motivo_bloqueio_legado": self.estado_legado,
                    "garrafas_salvas": round(self.garrafas_salvas_microparada_atual, 0)
                }
                self.historico_microparadas_evitadas.append(evento)
                self.duracao_microparada_atual_s = 0.0
                self.garrafas_salvas_microparada_atual = 0.0

        # Cálculos de KPI de Auditoria
        delta_garrafas_acum = self.garrafas_real_total - self.garrafas_legado_total
        delta_hl_acum = (delta_garrafas_acum * self.volume_garrafa_l) / 100.0
        capacidade_teorica_turno = (self.vel_nominal * (self.tempo_total_s / 3600.0))
        delta_oee_pct = (delta_garrafas_acum / capacidade_teorica_turno * 100.0) if capacidade_teorica_turno > 0 else 0.0

        return {
            "timestamp": timestamp,
            "v_real_cph": v_real,
            "v_legado_cph": self.v_legado,
            "v_alvo_legado_cph": self.v_alvo_legado,
            "estado_legado": self.estado_legado,
            "b2_virt_pct": round(self.b2_virt, 2),
            "b3_virt_pct": round(self.b3_virt, 2),
            "ancoragem_ativa": self.ancoragem_ativa,
            "microparada_evitada_ativa": microparada_ativa_neste_ciclo,
            "g_real_ciclo": round(g_real_ciclo, 2),
            "g_legado_ciclo": round(g_legado_ciclo, 2),
            "delta_garrafas_ciclo": round(delta_g_ciclo, 2),
            "delta_garrafas_acum": round(delta_garrafas_acum, 1),
            "delta_hl_acum": round(delta_hl_acum, 2),
            "delta_oee_pct": round(delta_oee_pct, 2),
            "total_microparadas_evitadas": self.total_microparadas_evitadas,
            "tempo_legado_parado_min": round(self.tempo_legado_parado_s / 60.0, 1),
            "tempo_real_rodando_min": round(self.tempo_real_rodando_s / 60.0, 1),
            "setores_b2": self.gerenciador_buffers.buffers["b2"].obter_tabela_resumo(),
            "setores_b3": self.gerenciador_buffers.buffers["b3"].obter_tabela_resumo()
        }

    @staticmethod
    def autocalibrar_capacidade(
        delta_tempo_s: float,
        v_ench_cph: float,
        v_past_cph: float,
        delta_buffer_pct: float
    ) -> Optional[float]:
        """
        Calcula a capacidade física em garrafas de uma esteira
        com base na variação percentual sob vazões conhecidas:
        Capacidade = [ (V_in - V_out) * (Delta_t / 3600) ] / (Delta_B_pct / 100)
        """
        if abs(delta_buffer_pct) < 1.0 or delta_tempo_s <= 0.0:
            return None
        vazao_liquida_cph = v_ench_cph - v_past_cph
        garrafas_acumuladas = vazao_liquida_cph * (delta_tempo_s / 3600.0)
        if (garrafas_acumuladas > 0 and delta_buffer_pct > 0) or (garrafas_acumuladas < 0 and delta_buffer_pct < 0):
            capacidade = (garrafas_acumuladas / (delta_buffer_pct / 100.0))
            return round(abs(capacidade), 1)
        return None
