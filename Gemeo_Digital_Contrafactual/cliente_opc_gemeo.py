# -*- coding: utf-8 -*-
"""
CLIENTE OPC UA - GÊMEO DIGITAL CONTRAFACTUAL DA LINHA LEGADA (PRÉ-V4)
Lê o config.json (idêntico ao Controle_Velocidade_4) e monitora via OPC UA
as velocidades das máquinas e CADA SENSOR individual de esteira (B2 e B3).
"""

import os
import sys
import json
import asyncio
import logging
import signal
from datetime import datetime
from typing import Dict, Any, Optional

try:
    from asyncua import Client, Node
except ImportError:
    Client = None
    Node = None

from modelo_gemeo_legado import GemeoDigitalLegado

# Configuração de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("GemeoDigitalOPC")


class SubscricaoHandler:
    """Recebe notificações assíncronas DataChange do servidor OPC UA para máquinas e sensores."""

    def __init__(self, estado_compartilhado: Dict[str, Any], modelo: GemeoDigitalLegado, mapa_tags: Dict[str, str]):
        self.estado = estado_compartilhado
        self.modelo = modelo
        self.mapa_tags = mapa_tags

    def datachange_notification(self, node: Any, val: Any, data: Any):
        try:
            node_id_str = node.nodeid.to_string()
            tipo_tag = self.mapa_tags.get(node_id_str, "")

            if tipo_tag == "v_in":
                self.estado["v_in"] = float(val) if val is not None else self.estado["v_in"]
            elif tipo_tag == "v_real":
                self.estado["v_real"] = float(val) if val is not None else self.estado["v_real"]
            elif tipo_tag == "v_out":
                self.estado["v_out"] = float(val) if val is not None else self.estado["v_out"]
            elif tipo_tag == "status_maquina":
                self.estado["status_maquina"] = bool(val) if val is not None else True
            elif tipo_tag == "sensor_esteira":
                # Atualiza diretamente o sensor específico dentro da geometria do buffer
                tag_original = self.mapa_tags.get(f"tag_orig_{node_id_str}", node_id_str)
                self.modelo.atualizar_sensor_opc(tag_original, val)

            self.estado["total_eventos_opc"] += 1
            self.estado["ultima_atualizacao"] = datetime.now()
        except Exception as e:
            logger.error(f"Erro no processamento DataChange OPC: {e}")


class ClienteOPCGemeoDigital:
    def __init__(self, caminho_config: str = "config.json"):
        self.caminho_config = caminho_config
        self.config = self._carregar_config(caminho_config)
        self.rodando = False
        self.client: Optional[Any] = None

        # Instanciação do Modelo usando diretamente o config.json
        self.modelo = GemeoDigitalLegado(config_dict=self.config)

        self.estado = {
            "v_in": 0.0,
            "v_real": 0.0,
            "v_out": 0.0,
            "status_maquina": True,
            "total_eventos_opc": 0,
            "ultima_atualizacao": None
        }

        self.mapa_nos_para_tags: Dict[str, str] = {}
        self.ciclo_s = float(self.config.get("controle", {}).get("ciclo_controle_s", 1.0))

    def _carregar_config(self, caminho: str) -> Dict[str, Any]:
        if not os.path.exists(caminho):
            dir_atual = os.path.dirname(os.path.abspath(__file__))
            caminho_alt = os.path.join(dir_atual, caminho)
            if os.path.exists(caminho_alt):
                caminho = caminho_alt
            else:
                caminho_v4 = os.path.join(dir_atual, "../Controle_Velocidade_4/config_opc_v4.json")
                if os.path.exists(caminho_v4):
                    caminho = caminho_v4
                else:
                    logger.warning(f"Arquivo {caminho} não encontrado. Usando defaults.")
                    return {}
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erro ao ler JSON {caminho}: {e}")
            return {}

    async def iniciar(self):
        """Conecta ao OPC UA e assina todas as máquinas e sensores individuais."""
        if Client is None:
            logger.error("Biblioteca 'asyncua' não está instalada no ambiente.")
            return

        url_opc = self.config.get("servidor_opc", {}).get("url", "opc.tcp://127.0.0.1:4840")
        timeout_s = float(self.config.get("servidor_opc", {}).get("timeout_s", 5.0))
        self.rodando = True

        logger.info(f"Conectando ao Servidor OPC UA: {url_opc}...")
        self.client = Client(url=url_opc, timeout=timeout_s)

        try:
            await self.client.connect()
            logger.info("✅ Conexão OPC UA estabelecida com sucesso!")

            cfg_maq = self.config.get("maquinas", {})
            tags_map = {
                cfg_maq.get("tag_velocidade_montante", ""): "v_in",
                cfg_maq.get("tag_velocidade_atual", ""): "v_real",
                cfg_maq.get("tag_velocidade_jusante", ""): "v_out",
                cfg_maq.get("tag_status_maquina", ""): "status_maquina"
            }

            # Mapeia CADA sensor individual de esteira existente no config.json
            tags_sensores = self.modelo.gerenciador_buffers.obter_todas_as_tags_sensores()
            for s_tag in tags_sensores:
                tags_map[s_tag] = "sensor_esteira"

            handler = SubscricaoHandler(self.estado, self.modelo, self.mapa_nos_para_tags)
            sub = await self.client.create_subscription(500, handler)

            nos_para_inscrever = []
            for tag_str, tipo_tag in tags_map.items():
                if tag_str and tag_str.strip():
                    try:
                        node = self.client.get_node(tag_str.strip())
                        node_str = node.nodeid.to_string()
                        self.mapa_nos_para_tags[node_str] = tipo_tag
                        self.mapa_nos_para_tags[f"tag_orig_{node_str}"] = tag_str.strip()

                        val_ini = await node.read_value()

                        if tipo_tag == "v_in": self.estado["v_in"] = float(val_ini or 0.0)
                        elif tipo_tag == "v_real": self.estado["v_real"] = float(val_ini or 0.0)
                        elif tipo_tag == "v_out": self.estado["v_out"] = float(val_ini or 0.0)
                        elif tipo_tag == "status_maquina": self.estado["status_maquina"] = bool(val_ini if val_ini is not None else True)
                        elif tipo_tag == "sensor_esteira": self.modelo.atualizar_sensor_opc(tag_str.strip(), val_ini)

                        nos_para_inscrever.append(node)
                    except Exception as e:
                        logger.warning(f"Não foi possível inscrever tag '{tag_str}': {e}")

            if nos_para_inscrever:
                await sub.subscribe_data_change(nos_para_inscrever)
                logger.info(f"Subscrição ativada para {len(nos_para_inscrever)} tags (Máquinas + Sensores Individuais de Esteira).")

            await self._loop_execucao()

        except Exception as e:
            logger.error(f"Falha de execução do Cliente OPC: {e}")
        finally:
            await self.parar()

    async def _loop_execucao(self):
        logger.info("Iniciando loop do Gêmeo Digital Contrafactual...")
        while self.rodando:
            try:
                t_inicio = asyncio.get_event_loop().time()
                agora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Obtém os níveis reais agregados dos sensores via gerenciador
                niveis_reais = self.modelo.gerenciador_buffers.calcular_todos_os_niveis_reais()

                res = self.modelo.atualizar(
                    v_in=self.estado["v_in"],
                    v_out=self.estado["v_out"],
                    v_real=self.estado["v_real"],
                    b2_real=niveis_reais.get("b2"),
                    b3_real=niveis_reais.get("b3"),
                    status_maquina_real=self.estado["status_maquina"],
                    delta_t_s=self.ciclo_s,
                    timestamp=agora_str
                )

                if int(self.modelo.tempo_total_s) % 5 == 0:
                    self._exibir_painel_sinotico(res, niveis_reais)

                tempo_gasto = asyncio.get_event_loop().time() - t_inicio
                espera = max(0.01, self.ciclo_s - tempo_gasto)
                await asyncio.sleep(espera)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no ciclo de simulação contrafactual: {e}")
                await asyncio.sleep(1.0)

    def _exibir_painel_sinotico(self, res: Dict[str, Any], niveis_reais: Dict[str, float]):
        status_cor = "🟢" if res["v_real_cph"] >= 10000 else "🔴"
        leg_cor = "🟢" if res["v_legado_cph"] >= 10000 else "🔴"
        ancora_txt = "⚓ ATIVA (Reset)" if res["ancoragem_ativa"] else "LIVRE (Simulação)"

        # Conta sensores ocupados reais e virtuais
        setores_b2 = res.get("setores_b2", [])
        setores_b3 = res.get("setores_b3", [])

        s_b2_real_ocup = sum(1 for s in setores_b2 if s.get("ocupado_real"))
        s_b2_virt_ocup = sum(1 for s in setores_b2 if s.get("ocupado_virtual"))
        s_b3_real_ocup = sum(1 for s in setores_b3 if s.get("ocupado_real"))
        s_b3_virt_ocup = sum(1 for s in setores_b3 if s.get("ocupado_virtual"))

        painel = (
            f"\n========================================================================================\n"
            f" 🏭 GÊMEO DIGITAL CONTRAFACTUAL DA LINHA LEGADA (PRÉ-V4) | {res['timestamp']}\n"
            f"----------------------------------------------------------------------------------------\n"
            f" {status_cor} REAL (V4 ATIVO):    {res['v_real_cph']:>8,0f} CPH | B2 Real: {niveis_reais.get('b2', 0):>5.1f}% | B3 Real: {niveis_reais.get('b3', 0):>5.1f}%\n"
            f" {leg_cor} LEGADO (SIMULADO): {res['v_legado_cph']:>8,0f} CPH | B2 Virt: {res['b2_virt_pct']:>5.1f}% | B3 Virt: {res['b3_virt_pct']:>5.1f}%\n"
            f" Estado CLP Legado: [{res['estado_legado']}] | Ancoragem: [{ancora_txt}]\n"
            f" Sensores B2 (Entrada): Real=[{s_b2_real_ocup}/{len(setores_b2)} ocupados] | Legado Virt=[{s_b2_virt_ocup}/{len(setores_b2)} ocupados]\n"
            f" Sensores B3 (Saída):   Real=[{s_b3_real_ocup}/{len(setores_b3)} ocupados] | Legado Virt=[{s_b3_virt_ocup}/{len(setores_b3)} ocupados]\n"
            f"----------------------------------------------------------------------------------------\n"
            f" 📊 AUDITORIA DE GANHO CONTRAFACTUAL DO V4:\n"
            f"   • Garrafas Incrementais Salvas:     {res['delta_garrafas_acum']:>+10,.0f} gf\n"
            f"   • Volume Incremental em Hectolitros:  {res['delta_hl_acum']:>+8.2f} hL\n"
            f"   • Ganho Real de OEE:                  {res['delta_oee_pct']:>+6.2f} %\n"
            f"   • Microparadas Evitadas pelo V4:          {res['total_microparadas_evitadas']:>4} ocorrências\n"
            f"========================================================================================"
        )
        print(painel)

    async def parar(self):
        self.rodando = False
        if self.client:
            try:
                await self.client.disconnect()
                logger.info("Cliente OPC UA desconectado.")
            except Exception:
                pass


def main():
    cliente = ClienteOPCGemeoDigital(caminho_config="config.json")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _tratar_sinal():
        logger.info("Sinal de interrupção recebido. Encerrando...")
        cliente.rodando = False
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _tratar_sinal)
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(cliente.iniciar())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        loop.run_until_complete(cliente.parar())
        loop.close()
        logger.info("Processo finalizado com sucesso.")


if __name__ == "__main__":
    main()
