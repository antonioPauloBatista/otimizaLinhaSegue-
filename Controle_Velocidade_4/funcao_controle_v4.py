# -*- coding: utf-8 -*-
"""
FUNÇÃO DE CONTROLE DE VELOCIDADE DA ENCHEDORA V4 COM DIAGNÓSTICO DE CAUSA-RAIZ
Gerado automaticamente pelo otimizador_velocidade_v4.py em 2026-09-12 09:13:55.

Retorna:
    (velocidade_cph, motivo_id)
    Onde motivo_id mapeia diretamente para 'motivos_modulacao_enum.json'.
"""

import os
import json

def rampa_trapezoidal(x, a, b, c, d):
    if x <= a or x >= d: return 0.0
    if a < x <= b: return (x - a) / (b - a) if b > a else 1.0
    if b < x <= c: return 1.0
    if c < x < d: return (d - x) / (d - c) if d > c else 1.0
    return 0.0

class ControladorVelocidadeV4:
    def __init__(self, velocidade_nominal=60000, v_atual_inicial=None, max_rampa=3000.0, banda_morta_cph=300.0):
        self.vel_nom = float(velocidade_nominal)
        self.b1_lim = 24.00
        self.b2_lim = 31.47
        self.b3_lim = 69.24
        self.b4_lim = 70.15
        self.rampa_b2 = 19.25
        self.rampa_b3 = 18.48
        self.antecip_b1 = 21.93
        self.antecip_b4 = 16.50
        self.min_mod = 0.892
        self.peso_retomada = 0.100
        self.fator_sprint = 1.010
        self.max_rampa = float(max_rampa)
        self.banda_morta = float(banda_morta_cph)
        self.alpha_ewma = 0.65

        # Estado interno dos filtros e rampa mecânica
        self.b1_f = 50.0
        self.b2_f = 50.0
        self.b3_f = 50.0
        self.b4_f = 50.0
        self.v_saida_anterior = None
        self.v_atual = float(v_atual_inicial) if v_atual_inicial is not None else self.vel_nom
        self.ultimo_motivo_id = 0

        # Carregar descrições de motivo se o json estiver presente
        self.mapa_motivos = {}
        if os.path.exists("motivos_modulacao_enum.json"):
            try:
                with open("motivos_modulacao_enum.json", "r", encoding="utf-8") as f:
                    self.mapa_motivos = json.load(f)
            except Exception: pass

    def filtrar_buffer(self, b_val, b_antigo):
        return self.alpha_ewma * float(b_val) + (1.0 - self.alpha_ewma) * float(b_antigo)

    def obter_motivo(self, motivo_id=None):
        m_id = str(self.ultimo_motivo_id if motivo_id is None else motivo_id)
        return self.mapa_motivos.get(m_id, {
            "codigo": "DESCONHECIDO",
            "descricao": "Modulação de fluxo",
            "categoria": "DESCONHECIDO",
            "maquina_causadora": "Não identificada",
            "localizacao_linha": "Não identificada",
            "acao_recomendada": "Inspecionar linha de envase."
        })

    def calcular_velocidade(self, b1, b2, b3, b4, v_in=None, v_out=None, delta_t_s=30.0, retornar_motivo=True):
        # 1. Filtro EWMA contínuo
        self.b1_f = self.filtrar_buffer(b1, self.b1_f)
        self.b2_f = self.filtrar_buffer(b2, self.b2_f)
        self.b3_f = self.filtrar_buffer(b3, self.b3_f)
        self.b4_f = self.filtrar_buffer(b4, self.b4_f)

        v_in = float(v_in) if v_in is not None else self.vel_nom
        v_out = float(v_out) if v_out is not None else self.vel_nom

        # 2. Tendência de Aceleração da Máquina da Frente
        trend_vout = 0.0
        if self.v_saida_anterior is not None and delta_t_s > 0:
            trend_vout = (v_out - self.v_saida_anterior) / float(delta_t_s)
        self.v_saida_anterior = v_out

        mu_acelerando = max(0.0, min(1.0, (trend_vout - 20.0) / 100.0))

        # 3. Lógica Fuzzy Takagi-Sugeno
        v_nom = self.vel_nom
        v_sprint = self.vel_nom * self.fator_sprint
        v_reduz = self.vel_nom * self.min_mod

        b2_baixo  = rampa_trapezoidal(self.b2_f, -1, 0, self.b2_lim - self.rampa_b2, self.b2_lim)
        b2_normal = rampa_trapezoidal(self.b2_f, self.b2_lim - self.rampa_b2, self.b2_lim, 100, 101)
        b3_normal = rampa_trapezoidal(self.b3_f, -1, 0, self.b3_lim, self.b3_lim + self.rampa_b3)
        b3_alto   = rampa_trapezoidal(self.b3_f, self.b3_lim, self.b3_lim + self.rampa_b3, 100, 101)

        b1_alerta = rampa_trapezoidal(self.b1_f, -1, 0, self.b1_lim, self.b1_lim + self.antecip_b1)
        b4_alerta = rampa_trapezoidal(self.b4_f, self.b4_lim - self.antecip_b4, self.b4_lim, 100, 101)

        w_saida_cheia = b3_alto * (1.0 - self.peso_retomada * mu_acelerando)
        w_retomada = b3_alto * (self.peso_retomada * mu_acelerando)

        cond_sprint = (self.b2_f >= (self.b2_lim + 10.0)) and (self.b3_f <= (self.b3_lim - 10.0)) and (v_in >= 0.90 * v_nom) and (v_out >= 0.90 * v_nom)
        w_sprint = 1.0 if cond_sprint else 0.0
        w_normal = min(b2_normal, b3_normal) * (1.0 - w_sprint)

        num = (b2_baixo * v_reduz) + (w_saida_cheia * v_reduz) + (w_retomada * v_nom) + (b1_alerta * v_reduz) + (b4_alerta * v_reduz) + (w_normal * v_nom) + (w_sprint * v_sprint)
        den = b2_baixo + w_saida_cheia + w_retomada + b1_alerta + b4_alerta + w_normal + w_sprint
        v_alvo = v_nom if den == 0 else num / den
        v_alvo = max(v_reduz, min(v_sprint, v_alvo))

        # 4. Limitador de Rampa Mecânica (Slew Rate) com Banda Morta para Máquinas Antigas
        v_ant = self.v_atual
        if self.v_atual <= 0.0:
            self.v_atual = min(v_alvo, v_reduz)
        else:
            # Banda morta: variações menores que 300 CPH não alteram o setpoint (protege atuadores antigos)
            if abs(v_alvo - self.v_atual) < self.banda_morta:
                v_alvo = self.v_atual

            # Escala dinâmica da rampa pelo tempo de ciclo delta_t_s (padrão: max_rampa em 30s)
            max_degrau = (self.max_rampa / 30.0) * max(1.0, float(delta_t_s))
            delta = v_alvo - self.v_atual
            if delta > max_degrau:
                self.v_atual += max_degrau
            elif delta < -max_degrau:
                self.v_atual -= max_degrau
            else:
                self.v_atual = v_alvo

        v_final = round(self.v_atual, 1)

        # 5. Identificação do Motivo e da Máquina Causadora (Reason Code)
        if v_final == 0.0:
            if self.b2_f <= 10.0 and self.b3_f >= 90.0:
                m_id = 90  # PARADA_SEGURANCA_BUFFER (Conflito Crítico Duplo)
            elif self.b2_f <= 10.0:
                m_id = 91  # PARADA_INTERTRAV_ENTRADA_ECI (Causador: ECI)
            elif self.b3_f >= 90.0:
                m_id = 92  # PARADA_INTERTRAV_SAIDA_PASTEURIZADOR (Causador: Pasteurizador)
            else:
                m_id = 99  # PARADA_PROPRIA_ENCHEDORA (Causador: Própria Enchedora)
        elif v_final > v_nom + 10.0:
            m_id = 1   # SPRINT_SOBREVELOCIDADE
        elif v_final >= v_nom - 10.0:
            m_id = 0   # NORMAL_FULL
        else:
            # Modulação ativa abaixo da nominal
            if v_alvo > v_final + 150.0:
                m_id = 60  # LIMITADOR_RAMPA_MECANICA (rampa subindo gradualmente - inércia enchedora)
            elif self.b2_f < self.b2_lim and self.b3_f > self.b3_lim:
                m_id = 30  # CONFLITO_ENTRADA_SAIDA
            elif self.b3_f > self.b3_lim and trend_vout > 20.0:
                m_id = 25  # RETOMADA_ACELERANDO_JUSANTE
            elif self.b3_f > self.b3_lim:
                m_id = 20  # ACUMULO_SAIDA_B3
            elif self.b2_f < self.b2_lim:
                m_id = 10  # FALTA_ENTRADA_B2
            elif v_out < 0.85 * v_nom:
                m_id = 80  # MAQUINA_JUSANTE_LENTA
            elif v_in < 0.85 * v_nom:
                m_id = 70  # MAQUINA_MONTANTE_LENTA
            elif self.b4_f > self.b4_lim:
                m_id = 50  # FEEDFORWARD_ALERTA_B4
            elif self.b1_f < self.b1_lim:
                m_id = 40  # FEEDFORWARD_ALERTA_B1
            elif self.b2_f >= self.b2_lim and self.b3_f <= self.b3_lim and v_in >= 0.85 * v_nom and v_out >= 0.85 * v_nom:
                m_id = 65  # ENCHEDORA_LIMITADA_INTERNAMENTE (linha livre mas enchedora com restrição local)
            else:
                m_id = 20 if (self.b3_f - self.b3_lim) > (self.b2_lim - self.b2_f) else 10

        self.ultimo_motivo_id = m_id
        if retornar_motivo:
            return v_final, m_id
        return v_final
