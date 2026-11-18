#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASSISTENTE DE VISUALIZAÇÃO E VALIDAÇÃO DE BUFFERS E TAGS OPC UA V4
Permite ao operador e engenheiro de automação:
1. Visualizar a tabela de setores de cada buffer (comprimento, largura, área, % incremental, contato).
2. Validar se a soma das áreas e percentuais está coerente.
3. Testar conexão com o servidor OPC UA e ler os valores atuais em tempo real.
"""

import os
import sys
import json
import asyncio
import argparse

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
if DIRETORIO_ATUAL not in sys.path:
    sys.path.insert(0, DIRETORIO_ATUAL)

from gerenciador_buffers import GerenciadorBuffers

try:
    from asyncua import Client, ua
    TEM_ASYNCUA = True
except ImportError:
    TEM_ASYNCUA = False
    Client = None
    ua = None


def exibir_tabela_buffer(buf_id: str, buf):
    print("\n" + "=" * 95)
    print(f" MAPEAMENTO DE SENSORES DE ESTEIRA - {buf.nome} (ID: {buf_id.upper()})")
    print(f" Capacidade Total Considerada: {buf.area_total_habilitada_m2:.2f} m²")
    print("=" * 95)
    print(f"{'Ordem':<6} | {'Tag OPC UA':<46} | {'Comp (m)':<8} | {'Larg (m)':<8} | {'Área m²':<8} | {'Área Incr %':<11} | {'Contato':<7} | {'Hab.'}")
    print("-" * 95)

    soma_pct = 0.0
    soma_area = 0.0
    for s in buf.setores:
        pct = buf.obter_area_incremental_pct(s)
        if s.habilitado:
            soma_pct += pct
            soma_area += s.area_m2
        contato_str = "True" if s.contato_ativo else "False"
        hab_str = "Sim" if s.habilitado else "Não"
        tag_curta = s.tag if len(s.tag) <= 46 else "..." + s.tag[-43:]
        print(f"{s.ordem:<6} | {tag_curta:<46} | {s.comprimento_m:<8.2f} | {s.largura_m:<8.2f} | {s.area_m2:<8.2f} | {pct:>9.2f} % | {contato_str:<7} | {hab_str}")

    print("-" * 95)
    print(f"SOMA TOTAL DOS SETORES HABILITADOS: {soma_area:.2f} m²  |  ACÚMULO MÁXIMO TEÓRICO: {soma_pct:.2f}%")
    print("=" * 95)


async def testar_conexao_opc(url: str, tags: list, usuario: str = "", senha: str = ""):
    if not TEM_ASYNCUA:
        print("\n❌ Biblioteca 'asyncua' não encontrada. Instale com 'pip install asyncua'.")
        return

    print(f"\nTentando conectar a: {url} ...")
    if usuario:
        print(f"🔒 Autenticação configurada para o usuário: '{usuario}'")
    else:
        print("🔓 Autenticação: Anônima (None)")
    try:
        client = Client(url=url, timeout=3.0)
        if usuario:
            client.set_user(usuario)
            if senha:
                client.set_password(senha)
        async with client:
            print("✅ Conectado com sucesso ao Servidor OPC UA!")
            print("\nLeitura de teste das tags configuradas:")
            print("-" * 80)
            for tag in tags:
                try:
                    node = client.get_node(tag)
                    val = await node.read_value()
                    dv = await node.read_data_value()
                    tipo = dv.Value.VariantType.name if dv and dv.Value and dv.Value.VariantType else "Desconhecido"
                    print(f" ✔️ Tag: {tag:<45} | Valor: {str(val):<10} | Tipo: {tipo}")
                except Exception as e:
                    print(f" ⚠️ Tag: {tag:<45} | Falha na leitura: {e}")
            print("-" * 80)
    except Exception as e:
        print(f"❌ Erro ao conectar ao servidor OPC UA: {e}")


async def pulsar_habilitar_segue(url: str, tag: str, tempo_s: float = 15.0, usuario: str = "", senha: str = ""):
    """Executa o acionamento temporizado (15s) da tag de habilitação no CLP com garantia Fail-Safe."""
    if not TEM_ASYNCUA:
        print("\n❌ Biblioteca 'asyncua' não encontrada. Instale com 'pip install asyncua'.")
        return

    print(f"\n🔌 Conectando ao Servidor OPC UA: {url} ...")
    client = Client(url=url, timeout=5.0)
    if usuario:
        client.set_user(usuario)
        if senha:
            client.set_password(senha)
    try:
        async with client:
            node = client.get_node(tag)
            tipo_tag = ua.VariantType.Boolean
            try:
                dv = await node.read_data_value()
                if dv and dv.Value and dv.Value.VariantType:
                    tipo_tag = dv.Value.VariantType
            except Exception:
                pass

            if tipo_tag in [ua.VariantType.Int16, ua.VariantType.Int32, ua.VariantType.UInt16, ua.VariantType.UInt32]:
                val_on = ua.Variant(1, tipo_tag)
                val_off = ua.Variant(0, tipo_tag)
            elif tipo_tag == ua.VariantType.Boolean:
                val_on = ua.Variant(True, ua.VariantType.Boolean)
                val_off = ua.Variant(False, ua.VariantType.Boolean)
            else:
                val_on = ua.Variant(1, ua.VariantType.Int16)
                val_off = ua.Variant(0, ua.VariantType.Int16)

            print(f"⚡ [CLP] Pressionando tag 'habilitar_segue' ({tag}) -> LIGADO ({val_on.Value}) por {tempo_s:.1f}s...")
            dv_on = ua.DataValue(Value=val_on, StatusCode_=None, SourceTimestamp=None, ServerTimestamp=None)
            try:
                await node.write_attribute(ua.AttributeIds.Value, dv_on)
            except Exception:
                await node.write_value(val_on)

            try:
                for restante in range(int(tempo_s), 0, -1):
                    print(f"   ⏳ Mantendo pressionado... {restante}s restantes", end="\r", flush=True)
                    await asyncio.sleep(1.0)
                if tempo_s % 1.0 > 0:
                    await asyncio.sleep(tempo_s % 1.0)
            finally:
                print(f"\n⚡ [CLP] Liberando tag 'habilitar_segue' ({tag}) -> DESLIGADO ({val_off.Value}) [Fail-Safe]...")
                dv_off = ua.DataValue(Value=val_off, StatusCode_=None, SourceTimestamp=None, ServerTimestamp=None)
                try:
                    await node.write_attribute(ua.AttributeIds.Value, dv_off)
                except Exception:
                    await node.write_value(val_off)
                print("✅ [CLP] Operação de pulso concluída com sucesso!")
    except Exception as e:
        print(f"❌ Erro durante teste de pulso OPC UA: {e}")


def main():
    parser = argparse.ArgumentParser(description="Assistente e Validador de Buffers e Tags OPC UA")
    parser.add_argument("--config", default=os.path.join(DIRETORIO_ATUAL, "config_opc_v4.json"), help="Caminho do arquivo config_opc_v4.json")
    parser.add_argument("--testar-conexao", action="store_true", help="Tenta conectar ao servidor OPC UA e ler as tags configuradas")
    parser.add_argument("--habilitar-segue-pulsar", action="store_true", help="Aciona a tag de habilitar segue por um tempo determinado (padrão 15s) e desliga")
    parser.add_argument("--tag", default="", help="Tag customizada para pulsar")
    parser.add_argument("--tempo", type=float, default=15.0, help="Tempo em segundos para manter pressionado (padrão: 15s)")
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"❌ Arquivo de configuração não encontrado: {args.config}")
        return

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    gb = GerenciadorBuffers()
    gb.configurar_a_partir_do_dict(cfg)

    print("=" * 95)
    print("   RESUMO DA CONFIGURAÇÃO INDUSTRIAL DE BUFFERS E MÁQUINAS V4")
    print("=" * 95)
    for buf_id in ["b1", "b2", "b3", "b4"]:
        buf = gb.buffers[buf_id]
        if buf.setores:
            exibir_tabela_buffer(buf_id, buf)

    cfg_maq = cfg.get("maquinas", {})
    cfg_hb = cfg.get("heartbeat", {})
    cfg_hab = cfg.get("habilitar_segue", {})
    print("\n--- TAGS DE MÁQUINAS E WATCHDOG ---")
    print(f" • Velocidade Montante (V_in)  : {cfg_maq.get('tag_velocidade_montante')}")
    print(f" • Velocidade Atual Enchedora  : {cfg_maq.get('tag_velocidade_atual')}")
    print(f" • Velocidade Jusante (V_out)  : {cfg_maq.get('tag_velocidade_jusante')}")
    print(f" • Escrita Setpoint Enchedora  : {cfg_maq.get('tag_escrita_setpoint')}")
    print(f" • Watchdog Heartbeat CLP      : {cfg_hb.get('tag')} (Modo: {cfg_hb.get('modo')}, {cfg_hb.get('intervalo_s')}s)")
    print(f" • Habilitar Segue (Comando)   : {cfg_hab.get('tag')} (Modo: {cfg_hab.get('modo')}, {cfg_hab.get('tempo_s')}s, Ativo: {cfg_hab.get('ativo')})")
    print(f" • Trava Entrada de Garrafas   : {cfg_maq.get('tag_trava_entrada')}")

    if args.testar_conexao:
        cfg_srv = cfg.get("servidor_opc", {})
        url = cfg_srv.get("url", "")
        usuario = cfg_srv.get("usuario") or os.environ.get("OPC_USER", "")
        senha = cfg_srv.get("senha") or os.environ.get("OPC_PASSWORD", "")

        tags = gb.obter_todas_as_tags_sensores()
        for k in ["tag_velocidade_montante", "tag_velocidade_atual", "tag_velocidade_jusante", "tag_escrita_setpoint", "tag_segue_habilitado", "tag_trava_entrada"]:
            t = cfg_maq.get(k)
            if t and t not in tags:
                tags.append(t)
        if cfg_hb.get("tag") and cfg_hb.get("tag") not in tags:
            tags.append(cfg_hb.get("tag"))
        if cfg_hab.get("tag") and cfg_hab.get("tag") not in tags:
            tags.append(cfg_hab.get("tag"))

        asyncio.run(testar_conexao_opc(url, tags, usuario=usuario, senha=senha))

    if args.habilitar_segue_pulsar:
        cfg_srv = cfg.get("servidor_opc", {})
        url = cfg_srv.get("url", "")
        usuario = cfg_srv.get("usuario") or os.environ.get("OPC_USER", "")
        senha = cfg_srv.get("senha") or os.environ.get("OPC_PASSWORD", "")
        tag_alvo = args.tag or os.environ.get("HABILITAR_SEGUE_TAG_OPC") or os.environ.get("HABILITAR_SEGUE_TAG")
        if not tag_alvo:
            print("❌ Nenhuma tag especificada. Informe via --tag 'ns=2;s=...' ou via variável de ambiente HABILITAR_SEGUE_TAG_OPC.")
            return
        asyncio.run(pulsar_habilitar_segue(url, tag_alvo, tempo_s=args.tempo, usuario=usuario, senha=senha))


if __name__ == "__main__":
    main()
