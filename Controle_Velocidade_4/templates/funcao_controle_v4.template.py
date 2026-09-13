# -*- coding: utf-8 -*-
"""
FUNÇÃO DE CONTROLE DE VELOCIDADE DA ENCHEDORA V4 COM DIAGNÓSTICO DE CAUSA-RAIZ
Gerado automaticamente pelo otimizador_velocidade_v4.py em 2026-09-13 13:27:48.

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
    def __init__(self, velocidade_nominal=__VEL_NOMINAL__, v_atual_inicial=None, max_rampa=__MAX_RAMPA__, banda_morta_cph=300.0):
        self.vel_nom = float(velocidade_nominal)
        self.b1_lim = __B1_OPT__
        self.b2_lim = __B2_OPT__
        self.b3_lim = __B3_OPT__
        self.b4_lim = __B4_OPT__
        self.rampa_b2 = __RAMPA_B2_OPT__
        self.rampa_b3 = __RAMPA_B3_OPT__
        self.antecip_b1 = __ANTECIP_B1_OPT__
        self.antecip_b4 = __ANTECIP_B4_OPT__
        self.min_mod = __MIN_MOD_OPT__
        self.peso_retomada = __PESO_RETOMADA_OPT__
        self.fator_sprint = __FATOR_SPRINT_OPT__
        self.max_rampa = float(max_rampa)
        self.banda_morta = float(banda_morta_cph)
        self.alpha_ewma = __ALPHA_EWMA__

        # Estado interno dos filtros e rampa mecânica
        self.b1_f = 50.0
        self.b2_f = 50.0
        self.b3_f = 50.0
        self.b4_f = 50.0
        self.b2_raw_anterior = None
        self.v_saida_anterior = None
        self.v_atual = float(v_atual_inicial) if v_atual_inicial is not None else self.vel_nom
        self.v_alvo_estabilizado = self.v_atual
        self.ultimo_motivo_id = 0

        # Rastreamento de eventos de parada e modulação (JSON com início e fim)
        self.eventos_motivos = []
        self.evento_atual = None

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

    def registrar_evento(self, timestamp=None, delta_t_s=30.0, arquivo_json=None, salvar=True):
        """
        Rastreia os períodos de modulação e parada em JSON com início e término ('fim').
        Regra Estrita de Processo:
        - Se a enchedora estiver a 100% (motivo_id == 0 - NORMAL_FULL):
          NÃO registra evento (operação nominal sem perdas). Se havia evento anterior aberto,
          ele é finalizado registrando o timestamp de 'fim' e gravado.
        - Se a enchedora NÃO estiver a 100% (motivo_id != 0):
          Registra no JSON o período completo contendo:
          * inicio: timestamp de início da ocorrência
          * fim: timestamp de encerramento
          * motivo_id, motivo_codigo, motivo_descricao, maquina_causadora
          * duracao_segundos e velocidade_cph
        """
        if timestamp is None:
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp = str(timestamp)

        m_id = self.ultimo_motivo_id
        v_atual = self.v_atual

        if m_id == 0:
            # Enchedora a 100% nominal -> Não gera evento de perda
            if self.evento_atual is not None:
                self.evento_atual["fim"] = timestamp
                self.evento_atual["duracao_segundos"] = round(self.evento_atual.get("duracao_segundos", float(delta_t_s)), 1)
                self.eventos_motivos.append(self.evento_atual)
                self.evento_atual = None
                if salvar and arquivo_json:
                    self.salvar_eventos_json(arquivo_json)
        else:
            # Enchedora fora de 100% -> Registra motivo no JSON
            info = self.obter_motivo(m_id)
            if self.evento_atual is None:
                self.evento_atual = {
                    "inicio": timestamp,
                    "fim": timestamp,
                    "duracao_segundos": float(delta_t_s),
                    "motivo_id": int(m_id),
                    "motivo_codigo": info.get("codigo", "MODULACAO"),
                    "motivo_descricao": info.get("descricao", "Modulação de velocidade"),
                    "maquina_causadora": info.get("maquina_causadora", "Não identificada"),
                    "localizacao_linha": info.get("localizacao_linha", "Linha"),
                    "categoria": info.get("categoria", "OPERACIONAL"),
                    "velocidade_cph": round(v_atual, 1)
                }
                if salvar and arquivo_json:
                    self.salvar_eventos_json(arquivo_json)
            else:
                if self.evento_atual["motivo_id"] == m_id:
                    self.evento_atual["fim"] = timestamp
                    self.evento_atual["duracao_segundos"] = round(self.evento_atual.get("duracao_segundos", 0.0) + float(delta_t_s), 1)
                    self.evento_atual["velocidade_cph"] = round(v_atual, 1)
                    if salvar and arquivo_json:
                        self.salvar_eventos_json(arquivo_json)
                else:
                    self.evento_atual["fim"] = timestamp
                    self.eventos_motivos.append(self.evento_atual)
                    self.evento_atual = {
                        "inicio": timestamp,
                        "fim": timestamp,
                        "duracao_segundos": float(delta_t_s),
                        "motivo_id": int(m_id),
                        "motivo_codigo": info.get("codigo", "MODULACAO"),
                        "motivo_descricao": info.get("descricao", "Modulação de velocidade"),
                        "maquina_causadora": info.get("maquina_causadora", "Não identificada"),
                        "localizacao_linha": info.get("localizacao_linha", "Linha"),
                        "categoria": info.get("categoria", "OPERACIONAL"),
                        "velocidade_cph": round(v_atual, 1)
                    }
                    if salvar and arquivo_json:
                        self.salvar_eventos_json(arquivo_json)
        return self.evento_atual

    def finalizar_eventos(self, timestamp=None, arquivo_json=None):
        """Encerra qualquer evento em aberto e salva no JSON."""
        if self.evento_atual is not None:
            if timestamp is not None:
                self.evento_atual["fim"] = str(timestamp)
            self.eventos_motivos.append(self.evento_atual)
            self.evento_atual = None
            if arquivo_json:
                self.salvar_eventos_json(arquivo_json)

    def salvar_eventos_json(self, caminho_arquivo="eventos_motivos_live_v4.json"):
        """Grava a lista de eventos concluídos e o evento atual em JSON."""
        lista = list(self.eventos_motivos)
        if self.evento_atual is not None:
            lista.append(self.evento_atual)
        try:
            with open(caminho_arquivo, "w", encoding="utf-8") as f:
                json.dump(lista, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def obter_eventos(self):
        """Retorna todos os eventos registrados."""
        lista = list(self.eventos_motivos)
        if self.evento_atual is not None:
            lista.append(self.evento_atual)
        return lista

    def calcular_velocidade(self, b1, b2, b3, b4, v_in=None, v_out=None, delta_t_s=30.0, retornar_motivo=True, timestamp=None, registrar_evento=False, arquivo_json=None):
        v_in = float(v_in) if v_in is not None else self.vel_nom
        v_out = float(v_out) if v_out is not None else self.vel_nom

        # 1. Filtro EWMA contínuo com Fast-Path / Bypass Dinâmico para B2
        delta_b2_raw = 0.0
        if self.b2_raw_anterior is not None:
            delta_b2_raw = float(b2) - self.b2_raw_anterior
        self.b2_raw_anterior = float(b2)

        bypass_b2 = (v_in < 0.20 * self.vel_nom) and (delta_b2_raw <= -15.0 or float(b2) <= 15.0)
        if bypass_b2:
            self.b2_f = float(b2)
        else:
            self.b2_f = self.filtrar_buffer(b2, self.b2_f)

        self.b1_f = self.filtrar_buffer(b1, self.b1_f)
        self.b3_f = self.filtrar_buffer(b3, self.b3_f)
        self.b4_f = self.filtrar_buffer(b4, self.b4_f)

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

        # Regra R3 com Trava Rígida de Teto mecânica (se B3 > 80%, desativa retomada antecipada)
        if self.b3_f > 80.0:
            w_saida_cheia = b3_alto
            w_retomada = 0.0
        else:
            w_saida_cheia = b3_alto * (1.0 - self.peso_retomada * mu_acelerando)
            w_retomada = b3_alto * (self.peso_retomada * mu_acelerando)

        cond_sprint = (self.b2_f >= (self.b2_lim + 10.0)) and (self.b3_f <= (self.b3_lim - 10.0)) and (v_in >= 0.90 * v_nom) and (v_out >= 0.90 * v_nom)
        w_sprint = 1.0 if cond_sprint else 0.0
        w_normal = min(b2_normal, b3_normal) * (1.0 - w_sprint)

        num = (b2_baixo * v_reduz) + (w_saida_cheia * v_reduz) + (w_retomada * v_nom) + (b1_alerta * v_reduz) + (b4_alerta * v_reduz) + (w_normal * v_nom) + (w_sprint * v_sprint)
        den = b2_baixo + w_saida_cheia + w_retomada + b1_alerta + b4_alerta + w_normal + w_sprint
        v_alvo = v_nom if den == 0 else num / den
        v_alvo = max(v_reduz, min(v_sprint, v_alvo))

        # 4. Limitador de Rampa Mecânica (Slew Rate) com Banda Morta na Entrada (sem congelamento assintótico)
        v_ant = self.v_atual
        if self.v_atual <= 0.0:
            self.v_atual = min(v_alvo, v_reduz)
            self.v_alvo_estabilizado = self.v_atual
        else:
            if self.v_alvo_estabilizado is None:
                self.v_alvo_estabilizado = v_alvo
            else:
                if abs(v_alvo - self.v_alvo_estabilizado) >= self.banda_morta or v_alvo >= v_nom - 1.0 or v_alvo <= v_reduz + 1.0 or mu_acelerando > 0.0:
                    self.v_alvo_estabilizado = v_alvo

            alvo_execucao = self.v_alvo_estabilizado
            max_degrau = (self.max_rampa / 30.0) * max(1.0, float(delta_t_s))
            delta = alvo_execucao - self.v_atual
            if delta > max_degrau:
                self.v_atual += max_degrau
            elif delta < -max_degrau:
                self.v_atual -= max_degrau
            else:
                self.v_atual = alvo_execucao

        v_final = round(self.v_atual, 1)

        # 5. Identificação do Motivo e da Máquina Causadora (Reason Code)
        if v_final == 0.0:
            if self.b2_f <= 10.0 and self.b3_f >= 90.0:
                m_id = 90  # PARADA_SEGURANCA_BUFFER
            elif self.b2_f <= 10.0:
                m_id = 91  # PARADA_INTERTRAV_ENTRADA_ECI
            elif self.b3_f >= 90.0:
                m_id = 92  # PARADA_INTERTRAV_SAIDA_PASTEURIZADOR
            else:
                m_id = 99  # PARADA_PROPRIA_ENCHEDORA
        elif v_final > v_nom + 10.0:
            m_id = 1   # SPRINT_SOBREVELOCIDADE
        elif v_final >= v_nom - 10.0:
            m_id = 0   # NORMAL_FULL
        else:
            # Modulação ativa abaixo da nominal
            if self.b2_f < self.b2_lim and self.b3_f > self.b3_lim:
                m_id = 30  # CONFLITO_ENTRADA_SAIDA
            elif self.b3_f > self.b3_lim and trend_vout > 20.0 and self.b3_f <= 80.0:
                m_id = 25  # RETOMADA_ACELERANDO_SAIDA
            elif v_alvo > v_final + 150.0:
                m_id = 60  # LIMITADOR_RAMPA_MECANICA (rampa subindo gradualmente)
            elif self.b3_f > self.b3_lim:
                m_id = 20  # ACUMULO_SAIDA_B3
            elif self.b2_f < self.b2_lim:
                m_id = 10  # FALTA_ENTRADA_B2
            elif v_out < 0.85 * v_nom:
                m_id = 80  # MAQUINA_SAIDA_LENTA
            elif v_in < 0.85 * v_nom:
                m_id = 70  # MAQUINA_ENTRADA_LENTA
            elif self.b4_f > self.b4_lim:
                m_id = 50  # FEEDFORWARD_ALERTA_B4
            elif self.b1_f < self.b1_lim:
                m_id = 40  # FEEDFORWARD_ALERTA_B1
            elif self.b2_f >= self.b2_lim and self.b3_f <= self.b3_lim and v_in >= 0.85 * v_nom and v_out >= 0.85 * v_nom:
                m_id = 65  # ENCHEDORA_LIMITADA_INTERNAMENTE
            else:
                m_id = 20 if (self.b3_f - self.b3_lim) > (self.b2_lim - self.b2_f) else 10

        self.ultimo_motivo_id = m_id

        if registrar_evento:
            self.registrar_evento(timestamp=timestamp, delta_t_s=delta_t_s, arquivo_json=arquivo_json, salvar=True)

        if retornar_motivo:
            return v_final, m_id
        return v_final
