#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Controlador de Velocidade Live Interativo V4 (Simulador de Bancada com Motivos e Exportação JSON)
Mostra o setpoint de velocidade e o motivo da modulação / parada em tempo real.
Gera arquivo JSON com início, fim e motivo de cada evento sempre que a enchedora
não estiver a 100% (a 100% nominal, nenhum evento de perda é gerado).
"""

import datetime
from funcao_controle_v4 import ControladorVelocidadeV4

ARQUIVO_JSON_LIVE = "eventos_motivos_live_v4.json"

def main():
    print("="*75)
    print("   SIMULADOR DE VELOCIDADE LIVE V4 COM MOTIVOS DE PARADA / MODULAÇÃO")
    print("="*75)
    print("Injetando parâmetros otimizados V4 com enum de causas-raiz...")
    print(f"Rastreamento de eventos ativo -> Arquivo JSON: '{ARQUIVO_JSON_LIVE}'\n")

    ctrl = ControladorVelocidadeV4(velocidade_nominal=__VEL_NOMINAL__)

    while True:
        try:
            print("Digite os valores das variáveis (ou Ctrl+C para sair):")
            b1 = float(input("  B1 - Extremo Entrada (LG/DPL) [%]     [50]: ") or "50")
            b2 = float(input("  B2 - Entrada Imediata (ECI/Filler) [%] [50]: ") or "50")
            b3 = float(input("  B3 - Saída Imediata (Filler/PZ) [%]   [50]: ") or "50")
            b4 = float(input("  B4 - Extremo Saída (PZ/Rotuladora) [%] [50]: ") or "50")
            vin = float(input("  Velocidade Máquina Entrada (ECI) [CPH] [60000]: ") or "60000")
            vout = float(input("  Velocidade Máquina Saída (PZ) [CPH]    [60000]: ") or "60000")

            agora_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            vel, motivo_id = ctrl.calcular_velocidade(
                b1, b2, b3, b4, v_in=vin, v_out=vout, delta_t_s=30.0,
                retornar_motivo=True, timestamp=agora_str,
                registrar_evento=True, arquivo_json=ARQUIVO_JSON_LIVE
            )
            info = ctrl.obter_motivo(motivo_id)
            perc = round((vel / float(__VEL_NOMINAL__)) * 100.0, 1)

            print("-" * 75)
            if perc > 100.0:
                print(f"➔ SETPOINT V4: {vel:.0f} CPH ({perc}%) 🚀 MODO SPRINT / SOBREVELOCIDADE")
            elif perc == 100.0:
                print(f"➔ SETPOINT V4: {vel:.0f} CPH ({perc}%) ✅ MÁQUINA NOMINAL (100% FULL)")
            else:
                print(f"➔ SETPOINT V4: {vel:.0f} CPH ({perc}%) ⚠️ MODULAÇÃO SUAVE ATIVA")
            
            print(f"➔ MOTIVO [ID {motivo_id} - {info.get('codigo')}]: {info.get('descricao')}")
            print(f"   ↳ Máquina Causadora: {info.get('maquina_causadora', 'N/A')} ({info.get('localizacao_linha', 'N/A')})")
            print(f"   ↳ Categoria: {info.get('categoria')}")
            print(f"   ↳ Ação Recomendada: {info.get('acao_recomendada')}")

            # Exibição do status do JSON de eventos
            if motivo_id == 0:
                print(f"   ↳ JSON de Eventos: Enchedora em 100% nominal (Nenhum evento registrado no JSON)")
            else:
                ev = ctrl.evento_atual
                if ev:
                    print(f"   ↳ JSON de Eventos ('{ARQUIVO_JSON_LIVE}'):")
                    print(f"      Início: {ev.get('inicio')} | Fim: {ev.get('fim')} | Duração: {ev.get('duracao_segundos', 0):.0f}s | Motivo: {ev.get('motivo_codigo')}")
            print("-" * 75)
            print("")
        except (KeyboardInterrupt, EOFError):
            agora_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ctrl.finalizar_eventos(timestamp=agora_str, arquivo_json=ARQUIVO_JSON_LIVE)
            print(f"\nSaindo do simulador live... Eventos salvos em '{ARQUIVO_JSON_LIVE}'.")
            break
        except ValueError:
            print("\n⚠️ Entrada inválida. Por favor, digite números válidos.\n")

if __name__ == "__main__":
    main()
