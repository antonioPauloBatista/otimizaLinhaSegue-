#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testes Unitários do Módulo GravadorGrafanaV4
Valida formatação do InfluxDB Line Protocol, resiliência de envio,
comportamento offline e despacho assíncrono.
"""

import os
import sys
import time
import asyncio
import unittest

DIR_ATUAL = os.path.dirname(os.path.abspath(__file__))
if DIR_ATUAL not in sys.path:
    sys.path.insert(0, DIR_ATUAL)

from gravador_grafana_v4 import GravadorGrafanaV4


class TestGravadorGrafanaV4(unittest.TestCase):

    def setUp(self):
        self.config_padrao = {
            "habilitado": True,
            "grafana_url": "http://127.0.0.1:9999",  # Porta simulada/fechada para testar resiliência
            "grafana_user": "admin",
            "grafana_password": "fake_password",
            "datasource_selector": "17",
            "bucket": "Segue",
            "org": "ABinbev",
            "measurement_destino": "512_v4",
            "timeout_envio_s": 0.5
        }
        self.gravador = GravadorGrafanaV4(self.config_padrao)

    def tearDown(self):
        pass

    def test_formatacao_line_protocol_basica(self):
        """Verifica a conformidade da sintaxe do InfluxDB Line Protocol."""
        tags = {"linha": "512", "maquina": "ECH512001", "fabrica": "Uberlandia"}
        fields = {
            "b1": 50.0,
            "v_setpoint": 94500.0,
            "motivo_id": 0,
            "motivo_codigo": "NORMAL_FULL",
            "ativo": True
        }
        ts = 1727500000

        linha = self.gravador.formatar_line_protocol(
            measurement="512_v4",
            tags=tags,
            fields=fields,
            timestamp_s=ts
        )

        # 1. Medição e tags no início
        self.assertTrue(linha.startswith("512_v4,fabrica=Uberlandia,linha=512,maquina=ECH512001 "))
        # 2. Inteiro com sufixo 'i'
        self.assertIn("motivo_id=0i", linha)
        # 3. String de campo com aspas duplas
        self.assertIn('motivo_codigo="NORMAL_FULL"', linha)
        # 4. Booleano como 't'
        self.assertIn("ativo=t", linha)
        # 5. Floats formatados
        self.assertIn("b1=50.0000", linha)
        self.assertIn("v_setpoint=94500.0000", linha)
        # 6. Timestamp correto no final
        self.assertTrue(linha.endswith(" 1727500000"))

    def test_escape_caracteres_especiais(self):
        """Verifica se caracteres especiais em tags e medições são escapados corretamente."""
        tags = {"motivo": "ALERTA, B2 = CRITICO", "espaco teste": "com espaco"}
        fields = {"msg": 'Texto com "aspas" e barra \\'}

        linha = self.gravador.formatar_line_protocol(
            measurement="Medicao 512,V4",
            tags=tags,
            fields=fields,
            timestamp_s=1000
        )

        self.assertTrue(linha.startswith("Medicao\\ 512\\,V4"))
        self.assertIn("motivo=ALERTA\\,\\ B2\\ \\=\\ CRITICO", linha)
        self.assertIn('msg="Texto com \\"aspas\\" e barra \\\\"', linha)

    def test_preparar_ponto_ciclo(self):
        """Verifica a montagem de um ponto de ciclo completo do controlador V4."""
        linha_info = {"linha": "512", "fabrica": "Uberlandia", "nome_principal": "ECH512001"}
        motivo_info = {
            "codigo": "FEEDFORWARD_ALERTA_B4",
            "descricao": "Alerta Saida",
            "maquina_causadora": "Rotuladora",
            "acao_recomendada": "Modulando"
        }

        linha_lp = self.gravador.preparar_ponto_ciclo(
            linha_info=linha_info,
            b1=50.0, b2=60.0, b3=70.0, b4=92.0,
            v_in=90000.0, v_atual=91481.0, v_out=91481.0,
            v_setpoint=92547.0, vel_nom=94500.0,
            motivo_id=4, motivo_info=motivo_info,
            modo_sombra=True,
            segue_habilitado=True,
            timestamp_s=1700000000
        )

        self.assertIn("512_v4", linha_lp)
        self.assertIn("linha=512", linha_lp)
        self.assertIn("modo_sombra=true", linha_lp)
        self.assertIn("b4_pct=92.0000", linha_lp)
        self.assertIn("v_setpoint_cph=92547.0000", linha_lp)
        self.assertIn("motivo_id=4i", linha_lp)

    def test_resiliencia_offline_sem_gerar_csv(self):
        """Testa o comportamento seguro quando o servidor Grafana estiver inacessível, sem gerar CSV."""
        linha = "512_v4,linha=512 b1=50.0 1700000000"
        sucesso = self.gravador.enviar_ponto_sync(linha)

        # O envio deve falhar graciosamente sem lançar exceção não capturada
        self.assertFalse(sucesso)
        self.assertEqual(self.gravador.total_falhas, 1)
        self.assertEqual(self.gravador.falhas_consecutivas, 1)
        # O ponto deve ter sido colocado no buffer de contingência em memória
        self.assertEqual(len(self.gravador._buffer_contingencia), 1)

        # Nenhum arquivo CSV deve existir ou ter sido criado
        self.assertFalse(hasattr(self.gravador, "caminho_csv_backup"))

    def test_envio_assincrono_nao_bloqueante(self):
        """Verifica que o envio assíncrono executa em background e retorna normalmente."""
        async def run_async():
            linha = "512_v4,linha=512 b2=45.0 1700000010"
            t0 = time.time()
            res = await self.gravador.enviar_ponto_async(linha)
            tempo_decorrido = time.time() - t0
            # Deve ser rápido e não travar o loop
            self.assertFalse(res)  # Servidor falso offline
            self.assertLess(tempo_decorrido, 1.5)

        asyncio.run(run_async())

    def test_configuracao_direta_influxdb_sem_grafana(self):
        """Verifica que com telemetria_influx não há tentativa de consultar Grafana e prioriza localhost:8086."""
        cfg_influx = {
            "habilitado": True,
            "influx_url": "http://localhost:8086",
            "database": "Segue",
            "measurement_destino": "512_v4",
            "timeout_envio_s": 0.2
        }
        gravador_influx = GravadorGrafanaV4(cfg_influx)
        self.assertEqual(gravador_influx.influx_url, "http://localhost:8086")
        self.assertEqual(gravador_influx.database, "Segue")
        self.assertEqual(gravador_influx.grafana_url, "")
        self.assertIsNone(gravador_influx.ds_uid)
        
        # Teste de envio com servidor offline não deve lançar exceção
        res = gravador_influx.enviar_ponto_sync("512_v4,linha=512 b1=50.0 1700000000")
        self.assertFalse(res)
        self.assertEqual(gravador_influx.total_falhas, 1)


if __name__ == "__main__":
    unittest.main()
