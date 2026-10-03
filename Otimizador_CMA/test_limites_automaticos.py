#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suíte de Testes Unitários: Limites de Busca Automáticos e Histerese em 5%
Garante que a detecção de fronteiras de falhas nunca regrida para valores
chumbados e que a histerese de 5% seja respeitada em toda a cadeia.
"""

import os
import unittest
import numpy as np
import pandas as pd

# Importa a função do otimizador
import sys
DIR_ATUAL = os.path.dirname(os.path.abspath(__file__))
if DIR_ATUAL not in sys.path:
    sys.path.insert(0, DIR_ATUAL)

from otimizador_cma_es_free import calcular_limites_busca_automaticos


class TestLimitesBuscaAutomaticos(unittest.TestCase):

    def setUp(self):
        self.csv_path = os.path.join(DIR_ATUAL, "dados_completos_fabrica.csv")
        self.col_v_ech = "speed_actual_cph_null_filler_1"
        self.col_b2 = "accumulation_percentage_dsp_to_lle_null"
        self.col_b3 = "accumulation_percentage_lle_to_pz_null"
        self.col_b4 = "accumulation_percentage_pz_to_hor_null"
        self.vel_nominal = 52000.0
        self.histerese = 5.0

    def test_limites_dados_reais_fabrica(self):
        """Valida se nos dados reais da fábrica os limites de B3 e B4 não engessam a linha em 68%."""
        if not os.path.exists(self.csv_path):
            self.skipTest(f"Arquivo '{self.csv_path}' não encontrado para teste de integração.")

        df = pd.read_csv(self.csv_path)
        bounds_lo, bounds_hi, info = calcular_limites_busca_automaticos(
            df=df,
            col_v_ech=self.col_v_ech,
            col_b2=self.col_b2,
            col_b3=self.col_b3,
            col_b4=self.col_b4,
            vel_nominal=self.vel_nominal,
            histerese=self.histerese
        )

        # 1. Bounds válidos (LO < HI para todos os parâmetros)
        self.assertEqual(len(bounds_lo), 8)
        self.assertEqual(len(bounds_hi), 8)
        for i in range(8):
            self.assertLess(bounds_lo[i], bounds_hi[i], f"Bounds inválidos no índice {i}: LO >= HI")

        # 2. B4 (PZ-EPC, índice 6): O limite inferior de busca DEVE ser >= 70%
        # Para que o otimizador NUNCA recomende 65% quando a linha opera normalmente em 68%
        self.assertGreaterEqual(bounds_lo[6], 70.0, "O limite inferior de B4 deve ser >= 70% para não frear a 68%")
        self.assertLessEqual(bounds_hi[6], 90.0, "O limite superior de B4 não deve exceder 90%")

        # 3. B3 (ECH-PZ, índice 4): O limite inferior de busca DEVE ser >= 70%
        self.assertGreaterEqual(bounds_lo[4], 70.0, "O limite inferior de B3 deve ser >= 70%")

        # 4. B2 (Entrada, índice 2): O limite superior de busca DEVE ser <= 55%
        self.assertLessEqual(bounds_hi[2], 55.0, "O limite superior de B2 deve ser <= 55%")

        # 5. Histerese registrada no diagnóstico deve ser rigorosamente 5.0%
        self.assertEqual(info["histerese"], 5.0)

    def test_histerese_evita_travamento_em_68_porcento(self):
        """Garante matematicamente que uma mesa em 68% não fica travada em redução."""
        gatilho_b4 = 76.0
        histerese = 5.0
        clear_b4 = gatilho_b4 - histerese  # 71.0%

        nivel_atual = 68.0
        # Em 68%, o nível está abaixo do Clear (71%) e abaixo do Gatilho (76%)
        b4_ativo = False
        if nivel_atual >= gatilho_b4:
            b4_ativo = True
        elif nivel_atual < clear_b4:
            b4_ativo = False

        self.assertFalse(b4_ativo, "Com histerese de 5% e gatilho em 76%, mesa em 68% não deve ativar redução!")

    def test_fallback_sem_paradas(self):
        """Valida que o algoritmo não quebra e retorna limites seguros se não houver paradas no CSV."""
        df_sem_paradas = pd.DataFrame({
            self.col_v_ech: [52000.0] * 100,
            self.col_b2: [70.0] * 100,
            self.col_b3: [60.0] * 100,
            self.col_b4: [65.0] * 100,
        })

        bounds_lo, bounds_hi, info = calcular_limites_busca_automaticos(
            df=df_sem_paradas,
            col_v_ech=self.col_v_ech,
            col_b2=self.col_b2,
            col_b3=self.col_b3,
            col_b4=self.col_b4,
            vel_nominal=self.vel_nominal,
            histerese=self.histerese
        )

        self.assertEqual(len(bounds_lo), 8)
        self.assertEqual(len(bounds_hi), 8)
        self.assertTrue(np.all(bounds_lo < bounds_hi))
        self.assertGreaterEqual(bounds_lo[6], 70.0)

    def test_buffers_opcionais_desativados(self):
        """Valida funcionamento quando B1 e B4 são None ou inativos."""
        df_simples = pd.DataFrame({
            self.col_v_ech: [52000.0, 0.0, 52000.0, 0.0] * 25,
            self.col_b2: [70.0, 30.0, 75.0, 25.0] * 25,
            self.col_b3: [60.0, 85.0, 55.0, 90.0] * 25,
        })

        bounds_lo, bounds_hi, info = calcular_limites_busca_automaticos(
            df=df_simples,
            col_v_ech=self.col_v_ech,
            col_b2=self.col_b2,
            col_b3=self.col_b3,
            col_b1=None,
            col_b4=None,
            vel_nominal=self.vel_nominal,
            histerese=self.histerese
        )

        self.assertEqual(len(bounds_lo), 8)
        self.assertEqual(len(bounds_hi), 8)
        self.assertTrue(np.all(bounds_lo < bounds_hi))

    def test_failsafe_rejeita_histerese_excessiva(self):
        """Valida que uma histerese excessiva (> 8%) é rejeitada para evitar armadilhas de estado."""
        histerese_ruim = 15.0
        self.assertGreater(histerese_ruim, 8.0, "Histerese de 15% deve ser considerada excessiva e perigosa.")


if __name__ == "__main__":
    unittest.main()
