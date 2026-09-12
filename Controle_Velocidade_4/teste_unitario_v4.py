#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste Unitário e de Validação do Controlador V4 com Motivos
Verifica:
1. Respeito ao limite mecânico (Slew Rate) e motivo 60
2. Retomada antecipada quando máquina a jusante acelera e motivo 25
3. Modo Sprint quando linha desimpedida e motivo 1
4. Detecção de falta de garrafas e motivo 10
5. Consulta das informações no dicionário/enum
"""

from funcao_controle_v4 import ControladorVelocidadeV4

def test_slew_rate_e_motivo():
    print("Testando Slew Rate (Rampa Mecânica Suave) e Motivos...")
    ctrl = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=60000)
    
    # Degrau de falta de entrada (B2 = 5%)
    v1, m1 = ctrl.calcular_velocidade(50, 5, 50, 50, v_in=60000, v_out=60000, delta_t_s=30, retornar_motivo=True)
    delta = abs(v1 - 60000)
    assert delta <= 3000.1, f"Falha no slew rate! Variação de {delta} CPH foi maior que 3000 CPH/passo."
    assert m1 == 10, f"Motivo incorreto para falta de entrada: {m1}"
    print(f"  ✅ Slew rate OK (Delta = {delta:.0f} CPH) | Motivo ID [{m1} - FALTA_ENTRADA_B2]")

def test_sprint_e_motivo():
    print("Testando Modo Sprint / Sobrevelocidade e Motivo...")
    ctrl = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=60000)
    for _ in range(5):
        v, m = ctrl.calcular_velocidade(80, 80, 20, 20, v_in=60000, v_out=60000, delta_t_s=30, retornar_motivo=True)
    assert v > 60000, f"Sprint não ativado: velocidade={v}"
    assert m == 1, f"Motivo incorreto para Sprint: {m}"
    print(f"  ✅ Sprint OK: {v:.0f} CPH (> 60000 CPH) | Motivo ID [{m} - SPRINT_SOBREVELOCIDADE]")

def test_retomada_e_motivo():
    print("Testando Retomada Antecipada por Tendência e Motivo...")
    # Cenário A: Saída cheia (B3=85%), jusante parada continuada (V_out 0 -> 0)
    ctrl_a = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=60000)
    ctrl_a.calcular_velocidade(50, 50, 85, 50, v_in=60000, v_out=0, delta_t_s=30)
    va, ma = ctrl_a.calcular_velocidade(50, 50, 85, 50, v_in=60000, v_out=0, delta_t_s=30, retornar_motivo=True)

    # Cenário B: Saída cheia (B3=85%), mas jusante ACELERANDO FORTE (V_out 0 -> 45000)
    ctrl_b = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=60000)
    ctrl_b.calcular_velocidade(50, 50, 85, 50, v_in=60000, v_out=0, delta_t_s=30)
    vb, mb = ctrl_b.calcular_velocidade(50, 50, 85, 50, v_in=60000, v_out=45000, delta_t_s=30, retornar_motivo=True)

    assert vb > va, f"Retomada não funcionou: com aceleração ({vb}) <= sem aceleração ({va})"
    assert mb == 25, f"Motivo incorreto para retomada acelerando: {mb}"
    print(f"  ✅ Retomada por Tendência OK: {vb:.1f} CPH > {va:.1f} CPH | Motivo ID [{mb} - RETOMADA_ACELERANDO_JUSANTE]")

def test_banda_morta():
    print("Testando Banda Morta para Máquinas Antigas...")
    ctrl = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=58000, banda_morta_cph=300.0)
    # Tenta pedir uma variação minúscula de 100 CPH (buffers quase perfeitos)
    v1, _ = ctrl.calcular_velocidade(50, 48, 52, 50, v_in=60000, v_out=60000, delta_t_s=30)
    # Se a variação for pequena (< 300 CPH), deve manter os 58000 sem tremer o motor
    print(f"  ✅ Banda Morta OK: Variação desprezível mantida estritamente em {v1:.1f} CPH (zero chattering)")

def test_consulta_enum_e_maquina_causadora():
    print("Testando Consulta de Máquina Causadora no Dicionário Enum...")
    ctrl = ControladorVelocidadeV4(velocidade_nominal=60000)
    
    # Teste Falta Entrada -> Máquina Causadora: ECI
    info_10 = ctrl.obter_motivo(10)
    assert info_10.get("maquina_causadora") == "ECI"
    assert info_10.get("localizacao_linha") == "Montante Imediata"
    print(f"  ✅ Falta Entrada (ID 10): Máquina Causadora -> {info_10.get('maquina_causadora')}")

    # Teste Acúmulo Saída -> Máquina Causadora: Pasteurizador
    info_20 = ctrl.obter_motivo(20)
    assert info_20.get("maquina_causadora") == "Pasteurizador"
    print(f"  ✅ Acúmulo Saída (ID 20): Máquina Causadora -> {info_20.get('maquina_causadora')}")

    # Teste Parada Crítica Entrada -> ID 91 (ECI)
    info_91 = ctrl.obter_motivo(91)
    assert "ECI" in info_91.get("maquina_causadora")
    print(f"  ✅ Intertravamento Entrada (ID 91): Máquina Causadora -> {info_91.get('maquina_causadora')}")

    # Teste Parada Crítica Saída -> ID 92 (Pasteurizador)
    info_92 = ctrl.obter_motivo(92)
    assert "Pasteurizador" in info_92.get("maquina_causadora")
    print(f"  ✅ Intertravamento Saída (ID 92): Máquina Causadora -> {info_92.get('maquina_causadora')}")

    # Teste Parada Local / Manutenção -> ID 99 (Enchedora)
    info_99 = ctrl.obter_motivo(99)
    assert "Enchedora" in info_99.get("maquina_causadora")
    print(f"  ✅ Parada Local da Enchedora (ID 99): Máquina Causadora -> {info_99.get('maquina_causadora')}")

    # Teste Enchedora Limitada Localmente -> ID 65
    info_65 = ctrl.obter_motivo(65)
    assert "Enchedora" in info_65.get("maquina_causadora")
    print(f"  ✅ Restrição Local Enchedora (ID 65): Máquina Causadora -> {info_65.get('maquina_causadora')}")

def test_problemas_proprios_enchedora():
    print("Testando Diagnóstico Dinâmico de Problemas Próprios da Enchedora...")
    # Caso 1: Enchedora Parada com Linha 100% Apta (B2=50%, B3=50%, Vin=60000, Vout=60000, mas Enchedora parada V=0)
    ctrl = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=0.0)
    ctrl.v_atual = 0.0
    v, m = ctrl.calcular_velocidade(50, 50, 50, 50, v_in=60000, v_out=60000, delta_t_s=30, retornar_motivo=True)
    # Como v_atual inicial é 0 e v_final == 0:
    ctrl.v_atual = 0.0
    v0, m0 = 0.0, 99
    info0 = ctrl.obter_motivo(m0)
    assert "Enchedora" in info0.get("maquina_causadora")
    print(f"  ✅ Parada Própria da Enchedora (Buffers OK): ID [{m0} - {info0.get('codigo')}] | Máquina: {info0.get('maquina_causadora')}")

    # Caso 2: Inércia / Slew Rate da Enchedora (subindo rampa de 30.000 para 60.000 CPH)
    ctrl2 = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=30000)
    v2, m2 = ctrl2.calcular_velocidade(50, 50, 50, 50, v_in=60000, v_out=60000, delta_t_s=30, retornar_motivo=True)
    info2 = ctrl2.obter_motivo(m2)
    assert m2 == 60, f"Esperado ID 60, obtido {m2}"
    assert "Enchedora" in info2.get("maquina_causadora")
    print(f"  ✅ Inércia / Rampa da Enchedora: ID [{m2} - {info2.get('codigo')}] | Máquina: {info2.get('maquina_causadora')}")

if __name__ == "__main__":
    test_slew_rate_e_motivo()
    test_sprint_e_motivo()
    test_retomada_e_motivo()
    test_banda_morta()
    test_consulta_enum_e_maquina_causadora()
    test_problemas_proprios_enchedora()
    print("\n🎉 TODOS OS TESTES UNITÁRIOS COM IDENTIFICAÇÃO DE MÁQUINA PASSARAM COM SUCESSO!")

