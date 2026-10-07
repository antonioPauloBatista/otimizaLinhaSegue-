# -*- coding: utf-8 -*-
"""
SUÍTE DE TESTES UNITÁRIOS - GÊMEO DIGITAL CONTRAFACTUAL DA LINHA LEGADA
Valida os 3 blocos matemáticos, dinâmica de esteiras, autômato PackML,
temporizadores TON, sensores discretos de esteira, integração com config.json,
rampa do inversor e métricas de OEE.
"""

import os
import unittest
from modelo_gemeo_legado import GemeoDigitalLegado


class TesteGemeoDigitalLegado(unittest.TestCase):

    def setUp(self):
        caminho_cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        self.gemeo = GemeoDigitalLegado(
            caminho_config_json=caminho_cfg,
            velocidade_nominal=90000.0,
            capacidade_garrafas_b2=2800.0,
            capacidade_garrafas_b3=3500.0,
            limiar_corte_b3_pct=85.0,
            limiar_retomada_b3_pct=65.0,
            limiar_corte_b2_pct=15.0,
            limiar_retomada_b2_pct=35.0,
            ton_bloqueio_s=2.0,
            ton_retomada_s=2.0,
            tempo_rampa_subida_s=15.0,
            tempo_rampa_descida_s=8.0,
            tempo_ancoragem_parada_real_s=300.0,
            volume_garrafa_litros=0.355,
            b2_inicial_pct=50.0,
            b3_inicial_pct=50.0,
            v_legado_inicial=90000.0
        )

    def test_balanco_massa_b2_e_b3(self):
        """Valida a conservação estrita de garrafas nos buffers virtuais B2 e B3."""
        res = self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.0)
        self.assertAlmostEqual(res["b2_virt_pct"], 50.0, places=1)
        self.assertAlmostEqual(res["b3_virt_pct"], 50.0, places=1)

        for _ in range(10):
            res = self.gemeo.atualizar(v_in=90000.0, v_out=0.0, v_real=90000.0, delta_t_s=1.0)
        self.assertAlmostEqual(res["b3_virt_pct"], 57.14, delta=0.2)

        for _ in range(10):
            res = self.gemeo.atualizar(v_in=0.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.0)
        self.assertAlmostEqual(res["b2_virt_pct"], 41.07, delta=0.2)

    def test_bloqueio_acumulo_b3_e_ton(self):
        """Valida que o CLP legado bloqueia em 85% de B3 apenas se TON for satisfeito."""
        self.gemeo.b3_virt = 86.0

        res = self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.0)
        self.assertEqual(res["estado_legado"], "RODANDO")

        res = self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.1)
        self.assertEqual(res["estado_legado"], "BLOQUEADO_SAIDA_CHEIA")
        self.assertEqual(res["v_alvo_legado_cph"], 0.0)

        self.gemeo.b3_virt = 75.0
        res = self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.0)
        self.assertEqual(res["estado_legado"], "BLOQUEADO_SAIDA_CHEIA")

        self.gemeo.b3_virt = 60.0
        self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.0)
        res = self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.5)
        self.assertEqual(res["estado_legado"], "RODANDO")
        self.assertEqual(res["v_alvo_legado_cph"], 90000.0)

    def test_bloqueio_falta_b2_e_ton(self):
        """Valida que o CLP legado bloqueia em 15% de B2 por falta de alimentação."""
        self.gemeo.b2_virt = 14.0

        res = self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.0)
        self.assertEqual(res["estado_legado"], "RODANDO")

        res = self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.5)
        self.assertEqual(res["estado_legado"], "BLOQUEADO_ENTRADA_VAZIA")
        self.assertEqual(res["v_alvo_legado_cph"], 0.0)

        self.gemeo.b2_virt = 40.0
        self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.0)
        res = self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.5)
        self.assertEqual(res["estado_legado"], "RODANDO")

    def test_bloqueio_por_sensor_discreto_fotocelula(self):
        """Valida que o CLP legado bloqueia diretamente pelo sinal da fotocélula (Sensor_Acumulo_TON == True)."""
        self.gemeo.b3_virt = 50.0

        res = self.gemeo.atualizar(
            v_in=90000.0, v_out=90000.0, v_real=90000.0,
            sensor_acumulo_b3=True, delta_t_s=1.0
        )
        self.assertEqual(res["estado_legado"], "RODANDO")

        res = self.gemeo.atualizar(
            v_in=90000.0, v_out=90000.0, v_real=90000.0,
            sensor_acumulo_b3=True, delta_t_s=1.5
        )
        self.assertEqual(res["estado_legado"], "BLOQUEADO_SAIDA_CHEIA")
        self.assertEqual(res["v_alvo_legado_cph"], 0.0)

        self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, sensor_acumulo_b3=False, delta_t_s=1.0)
        res = self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, sensor_acumulo_b3=False, delta_t_s=1.5)
        self.assertEqual(res["estado_legado"], "RODANDO")

    def test_rampa_mecanica_inversor_legado(self):
        """Valida que o inversor antigo acelera em rampa (slew rate) e não em degrau instantâneo."""
        self.gemeo.v_legado = 0.0
        self.gemeo.estado_legado = "RODANDO"

        res = self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.0)
        self.assertLessEqual(res["v_legado_cph"], 6005.0)
        self.assertGreater(res["v_legado_cph"], 0.0)

        for _ in range(5):
            res = self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=1.0)
        self.assertAlmostEqual(res["v_legado_cph"], 36000.0, delta=100.0)

    def test_ancoragem_deterministica_packml(self):
        """Valida o cancelamento de drift e reset de buffer em paradas reais longas ou falhas."""
        res = self.gemeo.atualizar(
            v_in=90000.0, v_out=90000.0, v_real=0.0,
            b2_real=78.5, b3_real=22.3,
            status_maquina_real=False, delta_t_s=1.0
        )
        self.assertTrue(res["ancoragem_ativa"])
        self.assertEqual(res["estado_legado"], "PARADA_FALHA_REAL")
        self.assertEqual(res["v_legado_cph"], 0.0)
        self.assertEqual(res["b2_virt_pct"], 78.5)
        self.assertEqual(res["b3_virt_pct"], 22.3)

        self.gemeo.ancoragem_ativa = False
        self.gemeo.estado_legado = "RODANDO"
        self.gemeo.tempo_parada_real_continua_s = 0.0

        res = self.gemeo.atualizar(
            v_in=0.0, v_out=0.0, v_real=0.0,
            b2_real=55.0, b3_real=55.0,
            status_maquina_real=True, delta_t_s=310.0
        )
        self.assertTrue(res["ancoragem_ativa"])
        self.assertEqual(res["estado_legado"], "PARADA_FALHA_REAL")
        self.assertEqual(res["v_legado_cph"], 0.0)
        self.assertEqual(res["b2_virt_pct"], 55.0)

    def test_contabilidade_e_microparadas_evitadas(self):
        """Valida a apuração de Garrafas, Hectolitros, Delta OEE e microparadas evitadas."""
        self.gemeo.b3_virt = 90.0
        self.gemeo.estado_legado = "BLOQUEADO_SAIDA_CHEIA"
        self.gemeo.v_legado = 0.0

        for _ in range(60):
            res = self.gemeo.atualizar(
                v_in=67500.0, v_out=45000.0, v_real=67500.0,
                delta_t_s=1.0
            )

        self.assertAlmostEqual(res["delta_garrafas_acum"], 1125.0, delta=5.0)
        self.assertAlmostEqual(res["delta_hl_acum"], 3.99, delta=0.1)
        self.assertEqual(res["total_microparadas_evitadas"], 1)

    def test_autocalibracao_capacidade(self):
        """Valida a fórmula estática de autocalibração da capacidade da esteira."""
        cap_calculada = GemeoDigitalLegado.autocalibrar_capacidade(
            delta_tempo_s=10.0,
            v_ench_cph=90000.0,
            v_past_cph=0.0,
            delta_buffer_pct=7.1428
        )
        self.assertIsNotNone(cap_calculada)
        self.assertAlmostEqual(cap_calculada, 3500.0, delta=5.0)

    def test_integracao_config_json_e_sensores_individuais(self):
        """Valida que o modelo carrega todos os setores do config.json idêntico ao V4 e atualiza cada sensor."""
        buf_b2 = self.gemeo.gerenciador_buffers.buffers["b2"]
        buf_b3 = self.gemeo.gerenciador_buffers.buffers["b3"]

        # Confirma que B2 possui os 10 setores físicos e B3 possui os 12 setores
        self.assertEqual(len(buf_b2.setores), 10)
        self.assertEqual(len(buf_b3.setores), 12)

        # Atualiza a tag do primeiro sensor de B3 (125B3 na descarga da enchedora)
        tag_125b3 = "ns=2;s=L512_TRP512002.TRP512001.SEGUE.ECH-PZ.125B3"
        # contato_ativo é False (False indica presença de garrafas / feixe cortado)
        self.gemeo.atualizar_sensor_opc(tag_125b3, False)

        setor_125b3 = buf_b3.obter_sensor_por_tag(tag_125b3)
        self.assertIsNotNone(setor_125b3)
        self.assertTrue(setor_125b3.ocupado_real)

        # Executa ciclo: o sensor físico bloqueado deve atuar no modelo
        res = self.gemeo.atualizar(v_in=90000.0, v_out=90000.0, v_real=90000.0, delta_t_s=2.5)
        self.assertEqual(res["estado_legado"], "BLOQUEADO_SAIDA_CHEIA")


if __name__ == "__main__":
    unittest.main()
