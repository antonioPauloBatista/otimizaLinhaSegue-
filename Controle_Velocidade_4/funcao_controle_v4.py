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
    def __init__(self, velocidade_nominal=90000, v_atual_inicial=None, 
                 tempo_rampa_subida_s=10.0,
                 tempo_rampa_descida_s=8.0,
                 max_rampa=None, max_rampa_subida=None, max_rampa_descida=None,
                 pct_rampa_subida=None, pct_rampa_descida=None,
                 banda_morta_cph=300.0,
                 fator_sprint=None,
                 margem_sprint_b2_liga=15.0,
                 margem_sprint_b2_desliga=5.0,
                 tempo_minimo_sprint_s=30.0):
        # A velocidade de referência para o tempo de rampa mecânica é a Velocidade Máxima Nominal (vel_nom).
        # Conforme diretriz de automação e segurança: NUNCA se utiliza a sobremarcha/sprint como base da rampa.
        self.vel_nom = float(velocidade_nominal)
        self.b1_lim = 19.25
        self.b2_lim = 32.50
        self.b3_lim = 71.20
        self.b4_lim = 90.00
        self.rampa_b2 = 24.14
        self.rampa_b3 = 19.22
        self.antecip_b1 = 20.96
        self.antecip_b4 = 11.49
        self.min_mod = 0.750
        self.peso_retomada = 0.100
        self.fator_sprint = float(fator_sprint) if fator_sprint is not None else float(1.030)
        self.margem_sprint_b2_liga = float(margem_sprint_b2_liga)
        self.margem_sprint_b2_desliga = float(margem_sprint_b2_desliga)
        self.tempo_minimo_sprint_s = float(tempo_minimo_sprint_s)
        self.banda_morta = float(banda_morta_cph)
        self.alpha_ewma = 0.65

        # Estado da Histerese e Anti-Hunting do Sprint
        self.sprint_ativo = False
        self.tempo_em_sprint_s = 0.0

        # Definição física das rampas mecânicas baseadas em TEMPO EM SEGUNDOS de 0 a 100% nominal:
        # taxa (CPH/s) = vel_nom / tempo_s
        if tempo_rampa_subida_s is not None:
            self.tempo_rampa_subida_s = float(tempo_rampa_subida_s)
            self.taxa_subida_cph_s = self.vel_nom / max(0.1, self.tempo_rampa_subida_s)
            self.max_rampa_subida = round(self.taxa_subida_cph_s * 30.0, 1)
            self.pct_rampa_subida = round(self.max_rampa_subida / self.vel_nom, 4)
        elif max_rampa_subida is not None:
            self.max_rampa_subida = float(max_rampa_subida)
            self.taxa_subida_cph_s = self.max_rampa_subida / 30.0
            self.tempo_rampa_subida_s = round(self.vel_nom / max(0.1, self.taxa_subida_cph_s), 1)
            self.pct_rampa_subida = round(self.max_rampa_subida / self.vel_nom, 4)
        elif pct_rampa_subida is not None:
            self.pct_rampa_subida = float(pct_rampa_subida)
            self.max_rampa_subida = round(self.vel_nom * self.pct_rampa_subida, 1)
            self.taxa_subida_cph_s = self.max_rampa_subida / 30.0
            self.tempo_rampa_subida_s = round(self.vel_nom / max(0.1, self.taxa_subida_cph_s), 1)
        elif max_rampa is not None:
            self.max_rampa_subida = float(max_rampa)
            self.taxa_subida_cph_s = self.max_rampa_subida / 30.0
            self.tempo_rampa_subida_s = round(self.vel_nom / max(0.1, self.taxa_subida_cph_s), 1)
            self.pct_rampa_subida = round(self.max_rampa_subida / self.vel_nom, 4)
        else:
            self.pct_rampa_subida = float(3.0000)
            self.max_rampa_subida = round(self.vel_nom * self.pct_rampa_subida, 1)
            self.taxa_subida_cph_s = self.max_rampa_subida / 30.0
            self.tempo_rampa_subida_s = round(self.vel_nom / max(0.1, self.taxa_subida_cph_s), 1)

        if tempo_rampa_descida_s is not None:
            self.tempo_rampa_descida_s = float(tempo_rampa_descida_s)
            self.taxa_descida_cph_s = self.vel_nom / max(0.1, self.tempo_rampa_descida_s)
            self.max_rampa_descida = round(self.taxa_descida_cph_s * 30.0, 1)
            self.pct_rampa_descida = round(self.max_rampa_descida / self.vel_nom, 4)
        elif max_rampa_descida is not None:
            self.max_rampa_descida = float(max_rampa_descida)
            self.taxa_descida_cph_s = self.max_rampa_descida / 30.0
            self.tempo_rampa_descida_s = round(self.vel_nom / max(0.1, self.taxa_descida_cph_s), 1)
            self.pct_rampa_descida = round(self.max_rampa_descida / self.vel_nom, 4)
        elif pct_rampa_descida is not None:
            self.pct_rampa_descida = float(pct_rampa_descida)
            self.max_rampa_descida = round(self.vel_nom * self.pct_rampa_descida, 1)
            self.taxa_descida_cph_s = self.max_rampa_descida / 30.0
            self.tempo_rampa_descida_s = round(self.vel_nom / max(0.1, self.taxa_descida_cph_s), 1)
        elif max_rampa is not None:
            self.max_rampa_descida = float(max_rampa) * 2.5
            self.taxa_descida_cph_s = self.max_rampa_descida / 30.0
            self.tempo_rampa_descida_s = round(self.vel_nom / max(0.1, self.taxa_descida_cph_s), 1)
            self.pct_rampa_descida = round(self.max_rampa_descida / self.vel_nom, 4)
        else:
            self.pct_rampa_descida = float(3.7500)
            self.max_rampa_descida = round(self.vel_nom * self.pct_rampa_descida, 1)
            self.taxa_descida_cph_s = self.max_rampa_descida / 30.0
            self.tempo_rampa_descida_s = round(self.vel_nom / max(0.1, self.taxa_descida_cph_s), 1)

        self.max_rampa = self.max_rampa_subida  # Campo legado para retrocompatibilidade

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
        caminho_enum = os.path.join(os.path.dirname(os.path.abspath(__file__)), "motivos_modulacao_enum.json")
        if not os.path.exists(caminho_enum):
            caminho_enum = "motivos_modulacao_enum.json"
        if os.path.exists(caminho_enum):
            try:
                with open(caminho_enum, "r", encoding="utf-8") as f:
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

    def calcular_velocidade(self, b1, b2, b3, b4, v_in=None, v_out=None, v_atual=None, delta_t_s=30.0, retornar_motivo=True, timestamp=None, registrar_evento=False, arquivo_json=None):
        v_in = float(v_in) if v_in is not None else self.vel_nom
        v_out = float(v_out) if v_out is not None else self.vel_nom

        # Referência de velocidade operacional da máquina (Enchedora):
        # Se v_atual medido do CLP não for informado, adota o valor interno atual (self.v_atual)
        v_maquina = float(v_atual) if v_atual is not None else float(self.v_atual)

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

        # Balanço de massa e capacidade de escoamento na saída:
        # Se o Pasteurizador (v_out) está puxando garrafas a plena carga (v_out >= 0.90 * v_nom),
        # a taxa de esvaziamento da esteira B3 compensa a produção da Enchedora.
        # A modulação preventiva só deve atuar se houver déficit de escoamento ou se B3 atingir nível crítico.
        deficit_escoamento_saida = max(0.0, min(1.0, (v_nom - v_out) / (0.25 * v_nom))) if v_out < v_nom else 0.0

        # Regra R3 com Trava Rígida de Teto mecânica (se B3 >= 80%, prioridade absoluta para desaceleração)
        if self.b3_f >= 80.0:
            w_saida_cheia = b3_alto
            w_retomada = 0.0
        else:
            urgencia_b3 = max(deficit_escoamento_saida, max(0.0, (self.b3_f - 75.0) / 10.0))
            w_saida_cheia = b3_alto * urgencia_b3 * (1.0 - self.peso_retomada * mu_acelerando)
            w_retomada = b3_alto * (self.peso_retomada * mu_acelerando)

        # Regra Feedforward B4 acoplada ao Pasteurizador:
        # B4 fica depois do Pasteurizador. Se o Pasteurizador não desacelerou, B4 não estrangula a Enchedora diretamente.
        w_ff_b4 = b4_alerta * deficit_escoamento_saida if self.b3_f < 75.0 else b4_alerta

        # Condição de Sprint / Sobrevelocidade com Histerese e Anti-Hunting (desacoplada de v_in):
        # 1. Limiares dinâmicos vinculados à calibração de b2_lim
        b2_liga = min(60.0, max(38.0, self.b2_lim + self.margem_sprint_b2_liga))
        b2_desliga = max(28.0, self.b2_lim + self.margem_sprint_b2_desliga)

        # TRAVA DE SEGURANÇA OPERACIONAL: INTERTRAVAMENTO DE SPRINT POR VELOCIDADE DA ENCHEDORA
        # Regra Inegociável de Fábrica:
        # O "100%" da operação é definido pelo operador na IHM. Se a enchedora estiver rodando
        # abaixo da velocidade nominal de projeto (ex.: operador rebaixou 5% na IHM por restrição
        # mecânica, qualidade ou embalagem, ou a máquina está em rampa de aceleração), o Sprint
        # é ESTRITAMENTE BLOQUEADO.
        # Condição obrigatória: enchedora em regime nominal pleno (v_maquina >= 0.98 * v_nom).
        trava_sprint_bloqueado = (v_maquina < 0.98 * v_nom)

        # Condição de entrada no Sprint (Buffer de entrada folgado, saída livre, pasteurizador pleno e enchedora a 100% nominal):
        cond_entrada_sprint = (
            (self.b2_f >= b2_liga) and
            (self.b3_f <= (self.b3_lim - 5.0)) and
            (v_out >= 0.85 * v_nom) and
            (not trava_sprint_bloqueado)
        )

        # Condição crítica de desativação imediata (segurança de processo):
        # Desliga se buffers entrarem em zona de perigo, saída desacelerar ou enchedora cair abaixo de 95% nominal
        cond_corte_imediato = (
            (self.b2_f <= self.b2_lim) or
            (self.b3_f >= self.b3_lim) or
            (v_out < 0.70 * v_nom) or
            (v_maquina < 0.95 * v_nom)
        )

        if not self.sprint_ativo:
            if cond_entrada_sprint:
                self.sprint_ativo = True
                self.tempo_em_sprint_s = 0.0
        else:
            self.tempo_em_sprint_s += float(delta_t_s)
            cond_saida_histerese = (
                (self.b2_f < b2_desliga) or
                (self.b3_f > (self.b3_lim - 5.0)) or
                (v_out < 0.85 * v_nom) or
                (v_maquina < 0.98 * v_nom)
            )
            if cond_corte_imediato or cond_saida_histerese:
                self.sprint_ativo = False
                self.tempo_em_sprint_s = 0.0

        w_sprint = 1.0 if self.sprint_ativo else 0.0
        w_normal = min(b2_normal, b3_normal) * (1.0 - w_sprint)

        num = (b2_baixo * v_reduz) + (w_saida_cheia * v_reduz) + (w_retomada * v_nom) + (b1_alerta * v_reduz) + (w_ff_b4 * v_reduz) + (w_normal * v_nom) + (w_sprint * v_sprint)
        den = b2_baixo + w_saida_cheia + w_retomada + b1_alerta + w_ff_b4 + w_normal + w_sprint
        v_alvo = v_nom if den == 0 else num / den
        v_teto_sprint = v_nom if trava_sprint_bloqueado else v_sprint
        v_alvo = max(v_reduz, min(v_teto_sprint, v_alvo))

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
            max_degrau_subida = self.taxa_subida_cph_s * max(0.1, float(delta_t_s))
            max_degrau_descida = self.taxa_descida_cph_s * max(0.1, float(delta_t_s))
            delta = alvo_execucao - self.v_atual
            if delta > 0:
                # Aceleração (subida suave cautelosa)
                self.v_atual += min(delta, max_degrau_subida)
            elif delta < 0:
                # Desaceleração (descida rápida protetiva)
                self.v_atual -= min(abs(delta), max_degrau_descida)
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
            elif self.b3_f > self.b3_lim and (deficit_escoamento_saida > 0 or self.b3_f >= 75.0):
                m_id = 20  # ACUMULO_SAIDA_B3
            elif self.b2_f < self.b2_lim:
                m_id = 10  # FALTA_ENTRADA_B2
            elif v_out < 0.85 * v_nom:
                m_id = 80  # MAQUINA_SAIDA_LENTA
            elif v_in < 0.85 * v_nom:
                m_id = 70  # MAQUINA_ENTRADA_LENTA
            elif w_ff_b4 > 0:
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
