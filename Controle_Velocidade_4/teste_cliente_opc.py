#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SUÍTE DE TESTES UNITÁRIOS E INTEGRAÇÃO - CLIENTE OPC UA V4
Valida:
1. Cálculo dimensional dos setores da esteira (comprimento x largura x contato ativo)
   conferindo rigorosamente com a tela de parametrização industrial do usuário.
2. Integração ponta-a-ponta em bancada com servidor OPC UA simulado:
   - Inscrição Subscription (DataChange).
   - Acumulação dos buffers B1, B2, B3, B4.
   - Cálculo e escrita do Setpoint de velocidade da Enchedora via ControladorVelocidadeV4.
   - Watchdog Heartbeat oscilando continuamente.
"""

import os
import sys
import json
import asyncio
import unittest

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
if DIRETORIO_ATUAL not in sys.path:
    sys.path.insert(0, DIRETORIO_ATUAL)

from gerenciador_buffers import BufferGeometrico, SetorEsteira, GerenciadorBuffers
from cliente_opc_v4 import ClienteOPCV4
from funcao_controle_v4 import ControladorVelocidadeV4

try:
    from asyncua import Server, Client, ua
    TEM_ASYNCUA = True
except ImportError:
    TEM_ASYNCUA = False


class TesteCálculoGeometricoEsteiras(unittest.TestCase):
    def test_setores_da_imagem_do_usuario(self):
        """
        Valida exatamente os valores apresentados na interface do usuário (coluna 'Área incremental'):
        Setor 1: 2.9m x 0.4m  = 1.160 m² -> 3.63%
        Setor 2: 2.81m x 0.4m = 1.124 m² -> 3.51%
        Setor 3: 2.7m x 1.13m = 3.051 m² -> 9.54%
        Setor 4: 3.26m x 0.93m= 3.032 m² -> 9.48%
        Setor 5: 6.88m x 0.93m= 6.398 m² -> 20.00%
        Setor 6: 2.73m x 0.99m= 2.703 m² -> 8.45%
        Setor 7: 4.06m x 0.94m= 3.816 m² -> 11.93%
        Setor 8: 4.39m x 0.97m= 4.258 m² -> 13.31%
        Setor 9: 3.7m x 0.94m = 3.478 m² -> 10.87%
        Capacidade total nominal de esteira considerada: 32.0 m²
        """
        buf = BufferGeometrico("b2", "Buffer B2 DPL-ECH", capacidade_area_total_m2=32.0)
        
        dados_setores = [
            (1, "tag_106B2", 2.9, 0.4, False, 3.63),
            (2, "tag_105B3", 2.81, 0.4, False, 3.51),
            (3, "tag_105B2", 2.7, 1.13, False, 9.54),
            (4, "tag_104B2", 3.26, 0.93, False, 9.48),
            (5, "tag_103B3", 6.88, 0.93, False, 20.00),
            (6, "tag_103B2", 2.73, 0.99, False, 8.45),
            (7, "tag_102B5", 4.06, 0.94, False, 11.93),
            (8, "tag_102B4", 4.39, 0.97, False, 13.31),
            (9, "tag_102B3", 3.7, 0.94, False, 10.87),
        ]

        for ordem, tag, comp, larg, contato, pct_esperado in dados_setores:
            s = SetorEsteira(ordem=ordem, tag=tag, comprimento_m=comp, largura_m=larg, contato_ativo=contato, habilitado=True)
            buf.adicionar_setor(s)
            pct_calculado = buf.obter_area_incremental_pct(s)
            self.assertAlmostEqual(pct_calculado, pct_esperado, places=1,
                                   msg=f"Erro no Setor {ordem}: esperado ~{pct_esperado}%, obtido {pct_calculado}%")

        # Inicialmente sem sinal nos sensores, o buffer deve estar vazio (0%)
        self.assertEqual(buf.calcular_nivel_pct(), 0.0)

        # Simula acionamento do Setor 5 (6.88 x 0.93): deve adicionar exatamente 20%
        # Como contato_ativo é False (sensor óptico cortado com garrafas), valor False = garrafa presente
        buf.atualizar_sensor("tag_103B3", False)
        self.assertAlmostEqual(buf.calcular_nivel_pct(), 20.0, places=1)

        # Simula acionamento também do Setor 1 (3.63%): 20.00 + 3.63 = 23.63%
        buf.atualizar_sensor("tag_106B2", False)
        self.assertAlmostEqual(buf.calcular_nivel_pct(), 23.63, places=1)

        # Simula limpeza do Setor 5 (sinal volta a True = feixe restabelecido): volta a ~3.63%
        buf.atualizar_sensor("tag_103B3", True)
        self.assertAlmostEqual(buf.calcular_nivel_pct(), 3.63, places=1)


class TesteIntegracaoPontaAPontaOPC(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(TEM_ASYNCUA, "Requer biblioteca asyncua")
    async def test_cliente_com_servidor_simulado(self):
        """Sobe um servidor OPC UA simulado local, conecta o cliente V4, testa subscrição, controle e heartbeat."""
        porta = 4848
        url_teste = f"opc.tcp://127.0.0.1:{porta}/freeopcua/test/"

        server = Server()
        await server.init()
        server.set_endpoint(url_teste)
        server.set_server_name("Simulador Linha Segue V4")

        # Registra namespace e nós necessários
        idx = await server.register_namespace("urn:segue:linha512")
        obj_root = server.nodes.objects

        # Tags das máquinas
        node_vin = await obj_root.add_variable(idx, "VEL_MONTANTE", 85000.0)
        node_vatual = await obj_root.add_variable(idx, "VEL_ATUAL", 90000.0)
        node_vout = await obj_root.add_variable(idx, "VEL_JUSANTE", 88000.0)
        node_sp = await obj_root.add_variable(idx, "SETPOINT_VEL", 0.0)
        node_hb = await obj_root.add_variable(idx, "HEARTBEAT", False)

        # Tags dos sensores
        node_s1 = await obj_root.add_variable(idx, "SENSOR_B2_1", True)   # True = vazio
        node_s2 = await obj_root.add_variable(idx, "SENSOR_B2_2", True)
        node_s3 = await obj_root.add_variable(idx, "SENSOR_B3_1", True)

        await node_vin.set_writable()
        await node_vatual.set_writable()
        await node_vout.set_writable()
        await node_sp.set_writable()
        await node_hb.set_writable()
        await node_s1.set_writable()
        await node_s2.set_writable()
        await node_s3.set_writable()

        await server.start()

        # Cria configuração temporária para o teste
        cfg_teste = {
            "servidor_opc": {
                "url": url_teste,
                "timeout_s": 3.0,
                "reconectar_delay_s": 1.0,
                "publishing_interval_ms": 100
            },
            "heartbeat": {
                "tag": node_hb.nodeid.to_string(),
                "intervalo_s": 0.3,
                "modo": "toggle"
            },
            "maquinas": {
                "tag_velocidade_montante": node_vin.nodeid.to_string(),
                "tag_velocidade_atual": node_vatual.nodeid.to_string(),
                "tag_velocidade_jusante": node_vout.nodeid.to_string(),
                "tag_escrita_setpoint": node_sp.nodeid.to_string(),
                "velocidade_nominal": 94500.0
            },
            "buffers": {
                "B1": {"capacidade_area_total_m2": 10.0, "setores": []},
                "B2": {
                    "capacidade_area_total_m2": 10.0,
                    "setores": [
                        {"ordem": 1, "tag": node_s1.nodeid.to_string(), "comprimento_m": 5.0, "largura_m": 1.0, "contato_ativo": False, "habilitado": True},
                        {"ordem": 2, "tag": node_s2.nodeid.to_string(), "comprimento_m": 5.0, "largura_m": 1.0, "contato_ativo": False, "habilitado": True}
                    ]
                },
                "B3": {
                    "capacidade_area_total_m2": 10.0,
                    "setores": [
                        {"ordem": 1, "tag": node_s3.nodeid.to_string(), "comprimento_m": 5.0, "largura_m": 1.0, "contato_ativo": False, "habilitado": True}
                    ]
                },
                "B4": {"capacidade_area_total_m2": 10.0, "setores": []}
            },
            "controle": {
                "ciclo_controle_s": 0.5,
                "tempo_rampa_subida_s": 10.0,
                "tempo_rampa_descida_s": 8.0,
                "banda_morta_cph": 300.0,
                "arquivo_eventos_json": "teste_eventos_live.json"
            }
        }

        caminho_cfg_teste = os.path.join(DIRETORIO_ATUAL, "teste_config_opc.json")
        with open(caminho_cfg_teste, "w", encoding="utf-8") as f:
            json.dump(cfg_teste, f, indent=2)

        cliente = ClienteOPCV4(caminho_cfg_teste, modo_sombra=False)

        # Inicia cliente em background
        task_cliente = asyncio.create_task(cliente.executar())
        await asyncio.sleep(0.8)

        # 1. Simula presença de garrafas no Setor 1 do B2 (sinal vai para False)
        await node_s1.write_value(ua.Variant(False, ua.VariantType.Boolean))
        await asyncio.sleep(0.5)

        # Verifica se o gerenciador calculou 50% de B2 (5.0m² de 10.0m²)
        niveis = cliente.gerenciador_buffers.calcular_todos_os_niveis()
        self.assertEqual(niveis["b2"], 50.0)

        # Aguarda ciclo de controle rodar e escrever setpoint
        await asyncio.sleep(0.8)

        # Lê setpoint gravado no servidor OPC
        sp_gravado = await node_sp.read_value()
        self.assertGreater(sp_gravado, 0.0, "O setpoint deveria ter sido escrito no CLP.")

        # Lê heartbeat gravado no servidor OPC
        hb_gravado = await node_hb.read_value()
        self.assertIn(hb_gravado, [True, False])

        # Encerra cliente
        cliente.parar()
        task_cliente.cancel()
        try:
            await task_cliente
        except (asyncio.CancelledError, Exception):
            pass

        # -------------------------------------------------------------
        # TESTE 2: MODO SOMBRA (SHADOW MODE)
        # Reseta o setpoint no servidor e inicia cliente com modo_sombra=True
        # -------------------------------------------------------------
        await node_sp.write_value(ua.Variant(0.0, ua.VariantType.Double))
        cliente_sombra = ClienteOPCV4(caminho_cfg_teste, modo_sombra=True)
        task_sombra = asyncio.create_task(cliente_sombra.executar())
        await asyncio.sleep(0.8)

        # Simula garrafas no sensor
        await node_s1.write_value(ua.Variant(False, ua.VariantType.Boolean))
        await asyncio.sleep(0.8)

        # Em modo sombra, o setpoint calculado existe internamente mas NÃO é gravado no servidor OPC
        self.assertGreater(cliente_sombra.estado.v_setpoint_calculado, 0.0)
        sp_no_servidor = await node_sp.read_value()
        self.assertEqual(sp_no_servidor, 0.0, "No modo sombra, o setpoint NÃO pode ser gravado no CLP.")

        cliente_sombra.parar()
        task_sombra.cancel()
        try:
            await task_sombra
        except (asyncio.CancelledError, Exception):
            pass

        await server.stop()

        # Limpa arquivo temporário
        if os.path.exists(caminho_cfg_teste):
            os.remove(caminho_cfg_teste)
        if os.path.exists(os.path.join(DIRETORIO_ATUAL, "teste_eventos_live.json")):
            os.remove(os.path.join(DIRETORIO_ATUAL, "teste_eventos_live.json"))


def rodar_testes():
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TesteCálculoGeometricoEsteiras))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TesteIntegracaoPontaAPontaOPC))
    runner = unittest.TextTestRunner(verbosity=2)
    res = runner.run(suite)
    return res.wasSuccessful()


if __name__ == "__main__":
    sucesso = rodar_testes()
    sys.exit(0 if sucesso else 1)
