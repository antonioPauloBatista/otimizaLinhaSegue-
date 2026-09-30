#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste de Validação de Sincronização entre config_colunas.json e config_opc_v4.json
Executa em milissegundos e garante que qualquer alteração feita no config_colunas.json
reflete e está perfeitamente sincronizada em config_opc_v4.json e parametros_controle_v4.json.
"""

import os
import sys
import json
import unittest

DIR_ATUAL = os.path.dirname(os.path.abspath(__file__))
if DIR_ATUAL not in sys.path:
    sys.path.insert(0, DIR_ATUAL)

from funcao_controle_v4 import ControladorVelocidadeV4

class TesteSincronizacaoConfigParaOPC(unittest.TestCase):
    def setUp(self):
        self.caminho_colunas = os.path.join(DIR_ATUAL, "config_colunas.json")
        self.caminho_opc = os.path.join(DIR_ATUAL, "config_opc_v4.json")
        self.caminho_params = os.path.join(DIR_ATUAL, "parametros_controle_v4.json")

        self.assertTrue(os.path.exists(self.caminho_colunas), f"Arquivo não encontrado: {self.caminho_colunas}")
        self.assertTrue(os.path.exists(self.caminho_opc), f"Arquivo não encontrado: {self.caminho_opc}")

        with open(self.caminho_colunas, "r", encoding="utf-8") as f:
            self.cfg_colunas = json.load(f)

        with open(self.caminho_opc, "r", encoding="utf-8") as f:
            self.cfg_opc = json.load(f)

        self.cfg_params = {}
        if os.path.exists(self.caminho_params):
            with open(self.caminho_params, "r", encoding="utf-8") as f:
                self.cfg_params = json.load(f)

    def test_sincronizacao_velocidade_nominal(self):
        """Valida se Velocidade_Nominal_ECH de config_colunas.json bate com config_opc_v4.json."""
        vel_colunas = float(self.cfg_colunas.get("Velocidade_Nominal_ECH", 90000.0))
        vel_opc = float(self.cfg_opc["maquinas"].get("velocidade_nominal", 0.0))
        self.assertAlmostEqual(
            vel_opc, vel_colunas, places=1,
            msg=f"DIVERGÊNCIA: velocidade_nominal no config_opc ({vel_opc}) != config_colunas ({vel_colunas})"
        )

    def test_sincronizacao_fator_sobremarcha_sprint(self):
        """Valida se Fator_Sobremarcha bate com fator_sprint no config_opc_v4.json e parametros."""
        fator_colunas = float(self.cfg_colunas.get("Fator_Sobremarcha", 1.038))
        fator_opc = float(self.cfg_opc["controle"].get("fator_sprint", 0.0))
        self.assertAlmostEqual(
            fator_opc, fator_colunas, places=4,
            msg=f"DIVERGÊNCIA: fator_sprint no config_opc ({fator_opc}) != config_colunas ({fator_colunas})"
        )

        if self.cfg_params:
            fator_params = float(self.cfg_params.get("fator_sprint", 0.0))
            self.assertAlmostEqual(
                fator_params, fator_colunas, places=4,
                msg=f"DIVERGÊNCIA: fator_sprint no parametros_controle_v4 ({fator_params}) != config_colunas ({fator_colunas})"
            )

    def test_sincronizacao_tempos_rampa(self):
        """Valida se Tempo_Rampa_Subida_s e Tempo_Rampa_Descida_s batem com config_opc_v4.json."""
        t_sub_col = float(self.cfg_colunas.get("Tempo_Rampa_Subida_s", 10.0))
        t_desc_col = float(self.cfg_colunas.get("Tempo_Rampa_Descida_s", 8.0))

        t_sub_opc = float(self.cfg_opc["controle"].get("tempo_rampa_subida_s", 0.0))
        t_desc_opc = float(self.cfg_opc["controle"].get("tempo_rampa_descida_s", 0.0))

        self.assertAlmostEqual(t_sub_opc, t_sub_col, places=2, msg=f"tempo_rampa_subida_s diverge: OPC={t_sub_opc} vs Colunas={t_sub_col}")
        self.assertAlmostEqual(t_desc_opc, t_desc_col, places=2, msg=f"tempo_rampa_descida_s diverge: OPC={t_desc_opc} vs Colunas={t_desc_col}")

    def test_sincronizacao_tag_status_maquina(self):
        """Valida se Col_Status_Maquina quando preenchido está refletido em tag_status_maquina."""
        col_status = self.cfg_colunas.get("Col_Status_Maquina", "").strip()
        tag_status = self.cfg_opc["maquinas"].get("tag_status_maquina", "").strip()
        if col_status:
            self.assertEqual(tag_status, col_status, msg=f"tag_status_maquina diverge: OPC={tag_status} vs Colunas={col_status}")

    def test_instanciacao_controlador_com_config_sincronizado(self):
        """Instancia ControladorVelocidadeV4 com os parâmetros sincronizados e audita o cálculo físico."""
        vel_nom = float(self.cfg_opc["maquinas"]["velocidade_nominal"])
        fator_sprint = float(self.cfg_opc["controle"]["fator_sprint"])
        t_sub = float(self.cfg_opc["controle"]["tempo_rampa_subida_s"])
        t_desc = float(self.cfg_opc["controle"]["tempo_rampa_descida_s"])

        ctrl = ControladorVelocidadeV4(
            velocidade_nominal=vel_nom,
            fator_sprint=fator_sprint,
            tempo_rampa_subida_s=t_sub,
            tempo_rampa_descida_s=t_desc
        )

        v_sprint_esperado = vel_nom * fator_sprint
        v_calc, motivo = ctrl.calcular_velocidade(50, 80, 20, 50, v_in=vel_nom, v_out=vel_nom, delta_t_s=10)
        self.assertAlmostEqual(v_calc, v_sprint_esperado, delta=0.5, msg=f"Velocidade em sprint {v_calc} diferente de {v_sprint_esperado}")
        self.assertEqual(motivo, 1, f"Motivo deveria ser 1 (Sprint), obtido: {motivo}")

def executar_teste():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TesteSincronizacaoConfigParaOPC)
    runner = unittest.TextTestRunner(verbosity=2)
    resultado = runner.run(suite)
    return resultado.wasSuccessful()

if __name__ == "__main__":
    sucesso = executar_teste()
    sys.exit(0 if sucesso else 1)
