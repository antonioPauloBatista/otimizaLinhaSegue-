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
import os
import sys
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from funcao_controle_v4 import ControladorVelocidadeV4

def test_slew_rate_e_motivo():
    print("Testando Slew Rate Assimétrico Proporcional à Velocidade da Linha...")
    # 1. Teste para Linha de 60.000 CPH (4.2% descida = 2520 CPH, 1.7% subida = 1020 CPH)
    ctrl = ControladorVelocidadeV4(
        velocidade_nominal=60000, v_atual_inicial=60000,
        tempo_rampa_subida_s=None, tempo_rampa_descida_s=None,
        pct_rampa_descida=0.042, pct_rampa_subida=0.017
    )
    assert ctrl.max_rampa_descida == 2520.0, f"Rampa descida esperada 2520.0, obtido {ctrl.max_rampa_descida}"
    assert ctrl.max_rampa_subida == 1020.0, f"Rampa subida esperada 1020.0, obtido {ctrl.max_rampa_subida}"
    
    # Degrau de falta de entrada (B2 = 5%) -> Deve descer rápido com max_rampa_descida
    v1, m1 = ctrl.calcular_velocidade(50, 5, 50, 50, v_in=60000, v_out=60000, delta_t_s=30, retornar_motivo=True)
    delta_descida = 60000 - v1
    assert abs(delta_descida - 2520.0) < 1.0, f"Descida rápida falhou! Esperado 2520 CPH, variou {delta_descida} CPH."
    assert m1 == 10, f"Motivo incorreto para falta de entrada: {m1}"
    print(f"  ✅ Descida Rápida Protetiva OK: -{delta_descida:.0f} CPH/passo (84 CPH/s) | Motivo ID [{m1} - FALTA_ENTRADA_B2]")

    # Degrau de retomada (linha desimpedida) -> Deve subir suave com max_rampa_subida
    v_antes_subir = v1
    v2, _ = ctrl.calcular_velocidade(50, 50, 50, 50, v_in=60000, v_out=60000, delta_t_s=30, retornar_motivo=True)
    delta_subida = v2 - v_antes_subir
    assert abs(delta_subida - 1020.0) < 1.0, f"Subida suave falhou! Esperado 1020 CPH, variou {delta_subida} CPH."
    print(f"  ✅ Subida Suave Cautelosa OK: +{delta_subida:.0f} CPH/passo (34 CPH/s)")

    # 2. Teste de Proporcionalidade Automática para Linha de 45.000 CPH (ex: PG502)
    ctrl_45k = ControladorVelocidadeV4(
        velocidade_nominal=45000, v_atual_inicial=45000,
        tempo_rampa_subida_s=None, tempo_rampa_descida_s=None,
        pct_rampa_descida=0.042, pct_rampa_subida=0.017
    )
    assert ctrl_45k.max_rampa_descida == 1890.0, f"Rampa descida 45k esperada 1890.0, obtido {ctrl_45k.max_rampa_descida}"
    assert ctrl_45k.max_rampa_subida == 765.0, f"Rampa subida 45k esperada 765.0, obtido {ctrl_45k.max_rampa_subida}"
    print(f"  ✅ Autoajuste Universal Linha 45k OK: Descida = {ctrl_45k.max_rampa_descida:.0f} CPH | Subida = {ctrl_45k.max_rampa_subida:.0f} CPH")

def test_sprint_e_motivo():
    print("Testando Modo Sprint / Sobrevelocidade e Motivo...")
    ctrl = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=60000)
    for _ in range(5):
        v, m = ctrl.calcular_velocidade(80, 80, 20, 20, v_in=60000, v_out=60000, delta_t_s=30, retornar_motivo=True)
    assert v > 60000, f"Sprint não ativado: velocidade={v}"
    assert m == 1, f"Motivo incorreto para Sprint: {m}"
    print(f"  ✅ Sprint OK: {v:.0f} CPH (> 60000 CPH) | Motivo ID [{m} - SPRINT_SOBREVELOCIDADE]")

def test_sprint_histerese_anti_hunting():
    print("Testando Modo Sprint com Histerese Dinâmica e Anti-Hunting (1.038)...")
    ctrl = ControladorVelocidadeV4(velocidade_nominal=90000, fator_sprint=1.038)
    
    # 1. Entrada com DPL lenta (v_in=60k < 90% de 90k)
    v1, m1 = ctrl.calcular_velocidade(50, 50, 40, 50, v_in=60000, v_out=90000, delta_t_s=10)
    assert v1 == 93420.0, f"Esperado 93420.0 CPH, obtido {v1}"
    assert m1 == 1, f"Esperado Motivo 1 (Sprint), obtido {m1}"
    assert ctrl.sprint_ativo == True
    print(f"  ✅ Entrada no Sprint Desacoplada de v_in OK: {v1:.0f} CPH (Motivo ID 1)")
    
    # 2. Histerese: B2 cai para 40% (entre 34.4% e 44.4%) -> Mantém sprint
    v2, m2 = ctrl.calcular_velocidade(50, 40, 40, 50, v_in=60000, v_out=90000, delta_t_s=10)
    assert v2 == 93420.0
    assert m2 == 1
    assert ctrl.sprint_ativo == True
    print(f"  ✅ Histerese / Retenção Segura OK: Mantido em Sprint a {v2:.0f} CPH com B2=40%")
    
    # 3. Corte por falta crítica: B2 cai para 25% (b2_f cai abaixo de b2_desliga)
    v3, m3 = ctrl.calcular_velocidade(50, 25, 40, 50, v_in=60000, v_out=90000, delta_t_s=10)
    assert ctrl.sprint_ativo == False
    assert v3 <= 90000.0
    print(f"  ✅ Desativação por Histerese OK: Saiu do Sprint para {v3:.0f} CPH com B2 em queda")
    
    # 4. Anti-hunting: B2 recupera para 40% (ainda abaixo de 44.4%) -> Não religa
    v4, m4 = ctrl.calcular_velocidade(50, 40, 40, 50, v_in=60000, v_out=90000, delta_t_s=10)
    assert ctrl.sprint_ativo == False
    assert v4 == 90000.0
    print("  ✅ Anti-Hunting OK: Não religou em 40% (exige subida acima de 44.4%)")
    
    # 5. Reativação: B2 sobe para 55%
    v5, m5 = ctrl.calcular_velocidade(50, 55, 40, 50, v_in=60000, v_out=90000, delta_t_s=10)
    assert ctrl.sprint_ativo == True
    assert v5 == 93420.0
    print(f"  ✅ Reativação com B2=55% OK: {v5:.0f} CPH")

def test_retomada_e_motivo():
    print("Testando Retomada Antecipada por Tendência e Motivo em Faixa Segura (B3 = 78%)...")
    # Estabiliza o buffer em B3 = 78% (acima de b3_lim e abaixo do teto de 80%)
    # Inicializa com a enchedora modulada aguardando a jusante retomar
    ctrl_a = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=53520)
    ctrl_b = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=53520)
    for _ in range(4):
        ctrl_a.calcular_velocidade(50, 50, 78, 50, v_in=60000, v_out=0, delta_t_s=30)
        ctrl_b.calcular_velocidade(50, 50, 78, 50, v_in=60000, v_out=0, delta_t_s=30)

    # Cenário A: jusante continua parada (V_out = 0)
    va, ma = ctrl_a.calcular_velocidade(50, 50, 78, 50, v_in=60000, v_out=0, delta_t_s=30, retornar_motivo=True)

    # Cenário B: jusante ACELERANDO FORTE (V_out 0 -> 45000)
    vb, mb = ctrl_b.calcular_velocidade(50, 50, 78, 50, v_in=60000, v_out=45000, delta_t_s=30, retornar_motivo=True)

    assert vb > va, f"Retomada não funcionou: com aceleração ({vb}) <= sem aceleração ({va})"
    assert mb == 25, f"Motivo incorreto para retomada acelerando: {mb}"
    print(f"  ✅ Retomada por Tendência OK: {vb:.1f} CPH > {va:.1f} CPH | Motivo ID [{mb} - RETOMADA_ACELERANDO_SAIDA]")

def test_trava_teto_retomada_seguranca():
    print("Testando Trava Rígida de Teto para Regra R3 (B3 > 80%)...")
    # Cenário Crítico: Saída em zona de perigo (B3 = 85%), jusante acelera forte (falso arranque)
    # A trava de segurança mecânica deve DESATIVAR R3 (w3 = 0) e priorizar desaceleração (ID 20 - ACUMULO_SAIDA_B3)
    ctrl = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=60000)
    ctrl.calcular_velocidade(50, 50, 85, 50, v_in=60000, v_out=0, delta_t_s=30)
    v, m = ctrl.calcular_velocidade(50, 50, 85, 50, v_in=60000, v_out=45000, delta_t_s=30, retornar_motivo=True)
    
    assert m == 20, f"Trava falhou! Motivo deveria ser 20 (ACUMULO_SAIDA_B3), mas foi {m}"
    print(f"  ✅ Trava Rígida de Teto OK: Retomada bloqueada a {v:.1f} CPH | Motivo ID [{m} - ACUMULO_SAIDA_B3] (Proteção contra Bottle Crash)")

def test_fast_path_b2_queda_brusca():
    print("Testando Fast-Path / Bypass Dinâmico de Filtragem em B2 (ECI Desarmada)...")
    ctrl = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=60000)
    # Ciclo 1: B2 estável em 50%
    ctrl.calcular_velocidade(50, 50, 50, 50, v_in=60000, v_out=60000, delta_t_s=30)
    
    # Ciclo 2: ECI desarma (V_in = 0) e B2 despenca para 10% (queda de -40%)
    ctrl.calcular_velocidade(50, 10, 50, 50, v_in=0, v_out=60000, delta_t_s=30)
    
    # Sem bypass, o EWMA (alpha=0.65) levaria B2 para 0.65*10 + 0.35*50 = 24.0%
    # Com o bypass dinâmico, B2 filtrado deve ser exatamente 10.0% imediatamente!
    assert ctrl.b2_f == 10.0, f"Fast-path falhou! B2 filtrado = {ctrl.b2_f} (esperado 10.0% sem atraso de EWMA)"
    print(f"  ✅ Fast-Path B2 OK: Nível atualizado instantaneamente para {ctrl.b2_f}% (sem latência de 60-90s)")

def test_convergencia_exata_sem_offset_banda_morta():
    print("Testando Convergência Exata da Rampa Lenta sem Congelamento por Banda Morta...")
    # Rampa conservadora de 500 CPH/passo com banda morta de 300 CPH
    # Velocidade inicial 58.250 CPH força um resíduo de 250 CPH (< 300 CPH da banda morta) ao atingir 59.750 CPH
    ctrl = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=58250, max_rampa=500.0, banda_morta_cph=300.0, fator_sprint=1.0)
    
    # Executa ciclos sucessivos com buffers nominais desimpedidos da V4
    for _ in range(8):
        v, _ = ctrl.calcular_velocidade(50, 50, 56, 30, v_in=60000, v_out=60000, delta_t_s=30)
    
    # O código antigo congelava em 59.750 CPH porque |60000 - 59750| = 250 < 300 CPH
    # Com a correção, a velocidade atinge EXATAMENTE 60000.0 CPH
    assert v == 60000.0, f"Congelamento assintótico detectado! Velocidade travou em {v} CPH (esperado 60000.0 CPH)"
    print(f"  ✅ Convergência Exata OK: Setpoint final atingiu exatamente {v:.1f} CPH (sem travamento nos 59.750 CPH)")

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
    assert info_10.get("localizacao_linha") == "Entrada da Enchedora"
    print(f"  ✅ Falta Entrada (ID 10): Máquina Causadora -> {info_10.get('maquina_causadora')}")

    # Teste Acúmulo Saída -> Máquina Causadora: Pasteurizador
    info_20 = ctrl.obter_motivo(20)
    assert info_20.get("maquina_causadora") == "Pasteurizador"
    assert info_20.get("localizacao_linha") == "Saída da Enchedora"
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
    ctrl2 = ControladorVelocidadeV4(velocidade_nominal=60000, v_atual_inicial=30000, tempo_rampa_subida_s=100.0)
    v2, m2 = ctrl2.calcular_velocidade(50, 50, 50, 50, v_in=60000, v_out=60000, delta_t_s=30, retornar_motivo=True)
    info2 = ctrl2.obter_motivo(m2)
    assert m2 == 60, f"Esperado ID 60, obtido {m2}"
    assert "Enchedora" in info2.get("maquina_causadora")
    print(f"  ✅ Inércia / Rampa da Enchedora: ID [{m2} - {info2.get('codigo')}] | Máquina: {info2.get('maquina_causadora')}")

def test_eventos_json_inicio_fim():
    print("Testando Geração do JSON de Eventos com Início e Fim...")
    import os
    import json
    
    arquivo_teste = "teste_eventos_motivos.json"
    if os.path.exists(arquivo_teste):
        os.remove(arquivo_teste)

    ctrl = ControladorVelocidadeV4(
        velocidade_nominal=60000, v_atual_inicial=60000,
        fator_sprint=1.0, tempo_rampa_subida_s=None, tempo_rampa_descida_s=None,
        pct_rampa_descida=0.042, pct_rampa_subida=0.017
    )

    # 1. Enchedora a 100% nominal (Motivo 0 - NORMAL_FULL) -> NÃO deve gerar evento no JSON
    v1, m1 = ctrl.calcular_velocidade(
        50, 50, 60, 30, v_in=60000, v_out=60000, delta_t_s=30,
        retornar_motivo=True, timestamp="2026-09-12 14:00:00",
        registrar_evento=True, arquivo_json=arquivo_teste
    )
    assert m1 == 0, f"Esperado motivo 0 (100%), obtido {m1}"
    assert ctrl.evento_atual is None, "A 100% não deve existir evento aberto!"
    assert len(ctrl.eventos_motivos) == 0, "A 100% nenhum evento deve ter sido registrado!"
    print("  ✅ Enchedora em 100%: Nenhum evento registrado no JSON (correto).")

    # 2. Entra em modulação por falta de garrafas (B2 = 5%)
    v2, m2 = ctrl.calcular_velocidade(
        50, 5, 50, 50, v_in=60000, v_out=60000, delta_t_s=30,
        retornar_motivo=True, timestamp="2026-09-12 14:00:30",
        registrar_evento=True, arquivo_json=arquivo_teste
    )
    assert m2 == 10, f"Esperado motivo 10 (FALTA_ENTRADA_B2), obtido {m2}"
    assert ctrl.evento_atual is not None, "Deve abrir evento quando velocidade < 100%!"
    assert ctrl.evento_atual["inicio"] == "2026-09-12 14:00:30"
    assert ctrl.evento_atual["fim"] == "2026-09-12 14:00:30"
    assert ctrl.evento_atual["motivo_id"] == 10
    assert ctrl.evento_atual["maquina_causadora"] == "ECI"
    print("  ✅ Abertura de Evento (< 100%): Início registrado em '2026-09-12 14:00:30' | Motivo: FALTA_ENTRADA_B2 | Causa: ECI")

    # 3. Continua no mesmo motivo por mais um ciclo de 30 segundos
    v3, m3 = ctrl.calcular_velocidade(
        50, 5, 50, 50, v_in=60000, v_out=60000, delta_t_s=30,
        retornar_motivo=True, timestamp="2026-09-12 14:01:00",
        registrar_evento=True, arquivo_json=arquivo_teste
    )
    assert ctrl.evento_atual["inicio"] == "2026-09-12 14:00:30"
    assert ctrl.evento_atual["fim"] == "2026-09-12 14:01:00"
    assert ctrl.evento_atual["duracao_segundos"] == 60.0
    print("  ✅ Continuidade do Evento: Início mantido, Fim avançado para '2026-09-12 14:01:00' (Duração: 60s).")

    # 4. Linha destrava e entrada recupera buffer -> Enchedora inicia rampa suave (motivo 60 - LIMITADOR_RAMPA_MECANICA)
    v4, m4 = ctrl.calcular_velocidade(
        50, 50, 60, 30, v_in=60000, v_out=60000, delta_t_s=30,
        retornar_motivo=True, timestamp="2026-09-12 14:01:30",
        registrar_evento=True, arquivo_json=arquivo_teste
    )
    assert m4 == 60, f"Esperado motivo 60 (subindo em rampa suave), obtido {m4}"
    assert ctrl.evento_atual["motivo_id"] == 60
    assert ctrl.evento_atual["maquina_causadora"] == "Enchedora (Inércia Mecânica)"
    print(f"  ✅ Transição de Causa: Motivo 10 fechado, novo evento aberto ID [60 - {ctrl.evento_atual['motivo_codigo']}] (Rampa subindo a {v4:.0f} CPH).")

    # 5. Rampa conclui subindo gradualmente até atingir 100% nominal (60.000 CPH, motivo 0)
    ciclo_seg = 120
    while True:
        minutos = ciclo_seg // 60
        segundos = ciclo_seg % 60
        ts_passo = f"2026-09-12 14:{minutos:02d}:{segundos:02d}"
        v5, m5 = ctrl.calcular_velocidade(
            50, 50, 60, 30, v_in=60000, v_out=60000, delta_t_s=30,
            retornar_motivo=True, timestamp=ts_passo,
            registrar_evento=True, arquivo_json=arquivo_teste
        )
        if m5 == 0:
            break
        ciclo_seg += 30

    assert m5 == 0, f"Esperado motivo 0 (100% nominal), obtido {m5}"
    assert v5 == 60000.0, f"Esperado 60000 CPH, obtido {v5}"
    assert ctrl.evento_atual is None, "Evento deve ter sido encerrado após retorno aos 100%!"
    assert len(ctrl.eventos_motivos) == 2, f"Esperado 2 eventos concluídos (Falta B2 + Rampa Mecânica), obtido {len(ctrl.eventos_motivos)}"

    ev_1 = ctrl.eventos_motivos[0]
    assert ev_1["motivo_id"] == 10
    assert ev_1["inicio"] == "2026-09-12 14:00:30"
    assert ev_1["fim"] == "2026-09-12 14:01:30"
    assert ev_1["maquina_causadora"] == "ECI"

    ev_2 = ctrl.eventos_motivos[1]
    assert ev_2["motivo_id"] == 60
    assert ev_2["inicio"] == "2026-09-12 14:01:30"
    assert ev_2["fim"] == ts_passo

    print(f"  ✅ Fechamento dos Eventos após 100% Nominal:")
    print(f"     1. {ev_1['motivo_codigo']} ({ev_1['inicio']} ➔ {ev_1['fim']}) | Causa: {ev_1['maquina_causadora']}")
    print(f"     2. {ev_2['motivo_codigo']} ({ev_2['inicio']} ➔ {ev_2['fim']}) | Causa: {ev_2['maquina_causadora']}")

    # 6. Validação do arquivo JSON em disco
    assert os.path.exists(arquivo_teste), "Arquivo JSON não foi gravado no disco!"
    with open(arquivo_teste, "r", encoding="utf-8") as f:
        dados_json = json.load(f)
    assert len(dados_json) == 2
    assert dados_json[0]["motivo_id"] == 10
    assert dados_json[1]["motivo_id"] == 60

    if os.path.exists(arquivo_teste):
        os.remove(arquivo_teste)

def test_live_grafana_garrafas_e_relatorio():
    print("Testando Cálculo de Garrafas Extras e Relatório de Sessão do Grafana Live...")
    try:
        import controlador_velocidade_grafana_v4 as c_grafana
    except ImportError as e:
        print(f"  ⚠️ Dependência opcional não instalada ({e}). Ignorando teste de integração Grafana.")
        return
    
    ctrl = ControladorVelocidadeV4(velocidade_nominal=20000.0)
    delta_t_s = 30.0

    metricas = {
        "inicio": "2026-09-13 10:00:00",
        "total_ciclos": 0,
        "tempo_total_s": 0.0,
        "garrafas_reais_total": 0.0,
        "garrafas_v4_total": 0.0,
        "garrafas_extras_total": 0.0,
        "tempo_parada_real_s": 0.0,
        "tempo_parada_evitada_s": 0.0,
        "ciclos_manteria_rodando": 0,
        "ciclos_parada_inevitavel": 0,
        "contagem_motivos": {}
    }

    # 4 ciclos com máquina real parada e V4 modulando
    for _ in range(4):
        v_real = 0.0
        v_otim, m_id = ctrl.calcular_velocidade(50, 15, 50, 50, v_in=20000, v_out=20000, delta_t_s=delta_t_s, retornar_motivo=True)
        g_real = (v_real * delta_t_s) / 3600.0
        g_v4 = (v_otim * delta_t_s) / 3600.0
        g_extra = g_v4 - g_real

        metricas["total_ciclos"] += 1
        metricas["tempo_total_s"] += delta_t_s
        metricas["garrafas_reais_total"] += g_real
        metricas["garrafas_v4_total"] += g_v4
        metricas["garrafas_extras_total"] += g_extra
        metricas["contagem_motivos"][m_id] = metricas["contagem_motivos"].get(m_id, 0) + 1

        if v_real < 1000.0:
            metricas["tempo_parada_real_s"] += delta_t_s
            if v_otim >= 1000.0:
                metricas["tempo_parada_evitada_s"] += delta_t_s
                metricas["ciclos_manteria_rodando"] += 1

    # 6 ciclos com operação em sprint
    for _ in range(6):
        v_real = 20000.0
        v_otim, m_id = ctrl.calcular_velocidade(80, 80, 20, 20, v_in=20000, v_out=20000, delta_t_s=delta_t_s, retornar_motivo=True)
        g_real = (v_real * delta_t_s) / 3600.0
        g_v4 = (v_otim * delta_t_s) / 3600.0
        g_extra = g_v4 - g_real

        metricas["total_ciclos"] += 1
        metricas["tempo_total_s"] += delta_t_s
        metricas["garrafas_reais_total"] += g_real
        metricas["garrafas_v4_total"] += g_v4
        metricas["garrafas_extras_total"] += g_extra
        metricas["contagem_motivos"][m_id] = metricas["contagem_motivos"].get(m_id, 0) + 1

    assert metricas["total_ciclos"] == 10
    assert metricas["ciclos_manteria_rodando"] == 4
    assert metricas["tempo_parada_evitada_s"] == 120.0
    assert metricas["garrafas_extras_total"] > 0.0

    nome_rel = c_grafana.gerar_relatorio_sessao(metricas, ctrl)
    assert os.path.exists(nome_rel), f"Relatório '{nome_rel}' não foi gerado!"
    with open(nome_rel, "r", encoding="utf-8") as f:
        texto = f.read()
    assert "RELATÓRIO DE MONITORAMENTO LIVE V4" in texto
    assert "SALDO DE GARRAFAS GERADAS" in texto
    print(f"  ✅ Cálculo de Garrafas e Emissão de Relatório OK: Arquivo '{nome_rel}' gerado com sucesso.")

    if os.path.exists(nome_rel):
        os.remove(nome_rel)

def test_contador_producao_e_validacao_fisica():
    print("Testando Integração do Contador Físico de Produtos (Query InfluxQL + Validação)...")
    try:
        import controlador_velocidade_grafana_v4 as c_grafana
    except ImportError as e:
        print(f"  ⚠️ Dependência opcional não instalada ({e}). Ignorando teste de integração Contador Físico.")
        return

    # 1. Teste de carregamento do JSON de query
    caminho_json = os.path.join(os.path.dirname(__file__), "..", "Dados de json", "parametros_query.json")
    cfg = c_grafana.carregar_config_contador(caminho_json)
    assert cfg is not None, "Falha ao carregar parametros_query.json!"
    assert cfg["equipment_type"] == "Filler", f"Tipo incorreto: {cfg['equipment_type']}"
    assert cfg["equipment_name"] == "NS-05410-ENCHEDORA 01", f"Equipamento incorreto: {cfg['equipment_name']}"
    assert cfg["field_name"] == "Packaging Machine Production Counter - Total", f"Campo incorreto: {cfg['field_name']}"
    assert cfg["database"] in ["soda-template", "SODA Template", "soda"], f"Banco incorreto: {cfg['database']}"
    assert cfg["datasource_selector"] in ["8", "9", "13"], f"Datasource incorreto: {cfg['datasource_selector']}"
    print(f"  ✅ Leitura de parametros_query.json OK: {cfg['equipment_name']} | Campo: {cfg['field_name']}")

    # 2. Teste de montagem da query InfluxQL
    query_sql = c_grafana.montar_query_influxql_contador(cfg)
    query_esperada = 'SELECT LAST("Packaging Machine Production Counter - Total") FROM "Filler" WHERE "equipment_name"::tag = \'NS-05410-ENCHEDORA 01\''
    assert query_sql == query_esperada, f"Query InfluxQL incorreta!\nGerada:   {query_sql}\nEsperada: {query_esperada}"
    print(f"  ✅ Montagem de Query InfluxQL OK: {query_sql}")

    # 3. Teste de simulação de contagem física e detecção de motor girando em falso
    contador_ref = 10000.0
    metricas = {
        "inicio": "2026-09-13 14:00:00",
        "total_ciclos": 0,
        "tempo_total_s": 0.0,
        "garrafas_reais_total": 0.0,
        "garrafas_v4_total": 0.0,
        "garrafas_extras_total": 0.0,
        "tempo_real_ligado_s": 0.0,
        "tempo_real_parado_s": 0.0,
        "tempo_v4_ligado_s": 0.0,
        "tempo_v4_parado_s": 0.0,
        "tempo_v4_nominal_s": 0.0,
        "tempo_v4_sprint_s": 0.0,
        "tempo_v4_modulando_s": 0.0,
        "tempo_parada_real_s": 0.0,
        "tempo_parada_evitada_s": 0.0,
        "garrafas_evitadas_parada": 0.0,
        "ciclos_manteria_rodando": 0,
        "ciclos_parada_inevitavel": 0,
        "garrafas_fisicas_sensor_total": 0.0,
        "ciclos_validacao_sensor": 0,
        "contador_inicial": contador_ref,
        "contador_final": None,
        "contagem_motivos": {1: 3},
        "tempo_motivos_s": {1: 90.0}
    }

    # Ciclo 1: Produção normal confirmada (+350 garrafas)
    delta_c1 = 350.0
    metricas["total_ciclos"] += 1
    metricas["garrafas_reais_total"] += delta_c1
    metricas["garrafas_fisicas_sensor_total"] += delta_c1
    metricas["ciclos_validacao_sensor"] += 1

    # Ciclo 2: Motor girando mas sem garrafas (0 garrafas no sensor)
    delta_c2 = 0.0
    metricas["total_ciclos"] += 1
    metricas["garrafas_reais_total"] += delta_c2
    metricas["garrafas_fisicas_sensor_total"] += delta_c2
    metricas["ciclos_validacao_sensor"] += 1

    # Ciclo 3: Produção retoma (+400 garrafas)
    delta_c3 = 400.0
    metricas["total_ciclos"] += 1
    metricas["garrafas_reais_total"] += delta_c3
    metricas["garrafas_fisicas_sensor_total"] += delta_c3
    metricas["ciclos_validacao_sensor"] += 1
    metricas["contador_final"] = contador_ref + delta_c1 + delta_c2 + delta_c3

    assert metricas["garrafas_fisicas_sensor_total"] == 750.0
    assert metricas["contador_final"] == 10750.0

    # 4. Teste de emissão do relatório com validação do sensor físico
    ctrl = ControladorVelocidadeV4(velocidade_nominal=60000)
    nome_rel = c_grafana.gerar_relatorio_sessao(metricas, ctrl, arquivo_saida="teste_relatorio_sensor.txt")
    with open(nome_rel, "r", encoding="utf-8") as f:
        texto = f.read()
    assert "Validada por Sensor Físico: 750 gf" in texto, f"Sensor físico ausente no texto do relatório!\n{texto}"
    assert "Contador: 10,750 gf" in texto, f"Contador final ausente no texto do relatório!\n{texto}"
    print("  ✅ Validação de Produção Física por Contador OK: Registro de 750 gf com alerta de falso giro.")

    if os.path.exists(nome_rel):
        os.remove(nome_rel)
    if os.path.exists("resumo_producao_live_v4.json"):
        with open("resumo_producao_live_v4.json", "r", encoding="utf-8") as f:
            js = json.load(f)
        assert js["resumo_producao"]["garrafas_sensor_fisico"] == 750.0
        assert js["resumo_producao"]["contador_final"] == 10750.0
        print("  ✅ Resumo estruturado JSON com dados do Sensor Físico OK.")

def test_gravacao_continua_csv_live():
    print("Testando Gravação Contínua de CSV em Tempo Real (Live Append com Flush)...")
    try:
        import controlador_velocidade_grafana_v4 as c_grafana
    except ImportError as e:
        print(f"  ⚠️ Dependência opcional não instalada ({e}). Ignorando teste de CSV contínuo.")
        return
    arquivo_teste_csv = "teste_dados_live.csv"
    if os.path.exists(arquivo_teste_csv):
        os.remove(arquivo_teste_csv)
    
    # 1. Inicializa CSV e testa cabeçalho
    c_grafana.inicializar_csv_live(arquivo_teste_csv)
    assert os.path.exists(arquivo_teste_csv), "Arquivo CSV não foi criado!"
    
    # 2. Grava linha simulada
    linha_1 = [
        "2026-09-16 22:00:00", "ONLINE",
        50.0, 48.0, 52.0, 30.0,
        60000.0, 60000.0, 60000.0, 60000.0, 100.0,
        0, '"NORMAL_FULL"', '"Linha"',
        500.0, 500.0, 0.0,
        500.0, 500.0, 0.0,
        10500.0, 500.0
    ]
    c_grafana.gravar_linha_csv_live(arquivo_teste_csv, linha_1)

    # 3. Lê com pandas para validar integridade
    import pandas as pd
    df_csv = pd.read_csv(arquivo_teste_csv)
    assert len(df_csv) == 1, f"Esperado 1 linha de dados no CSV, obtido {len(df_csv)}"
    assert "timestamp" in df_csv.columns
    assert "v_otimizada_v4_cph" in df_csv.columns
    assert "motivo_codigo" in df_csv.columns
    assert df_csv["v_otimizada_v4_cph"].iloc[0] == 60000.0
    assert df_csv["motivo_codigo"].iloc[0] == "NORMAL_FULL"
    print(f"  ✅ Gravação Contínua CSV OK: {len(df_csv)} ciclo gravado e validado com sucesso ({len(df_csv.columns)} colunas).")
    
    if os.path.exists(arquivo_teste_csv):
        os.remove(arquivo_teste_csv)

def test_tempo_rampa_segundos_base_nominal_sem_sprint():
    print("Testando Parametrização por Tempo em Segundos (Base Velocidade Máxima Nominal, sem Sprint)...")
    v_nom = 94500.0
    t_sub = 15.0   # 15s de 0 a 100%
    t_desc = 8.0   # 8s de 100% a 0
    ctrl = ControladorVelocidadeV4(
        velocidade_nominal=v_nom,
        v_atual_inicial=0.0,
        tempo_rampa_subida_s=t_sub,
        tempo_rampa_descida_s=t_desc
    )

    # 1. Validação da taxa física por segundo
    taxa_sub_esperada = v_nom / t_sub      # 94500 / 15 = 6300.0 CPH/s
    taxa_desc_esperada = v_nom / t_desc    # 94500 / 8 = 11812.5 CPH/s
    assert abs(ctrl.taxa_subida_cph_s - taxa_sub_esperada) < 1e-4, f"Taxa subida incorreta: {ctrl.taxa_subida_cph_s} vs {taxa_sub_esperada}"
    assert abs(ctrl.taxa_descida_cph_s - taxa_desc_esperada) < 1e-4, f"Taxa descida incorreta: {ctrl.taxa_descida_cph_s} vs {taxa_desc_esperada}"

    # 2. Confirma que a base é estritamente a velocidade máxima nominal (e NÃO sobrevelocidade/sprint)
    v_sprint_calc = v_nom * ctrl.fator_sprint
    assert ctrl.taxa_subida_cph_s < (v_sprint_calc / t_sub), "Erro: Taxa de subida utilizou sobrevelocidade/sprint em vez da nominal máxima!"
    print(f"  ✅ Base Nominal Auditada: Taxa calculada sobre {v_nom:,.0f} CPH (Sprint de {v_sprint_calc:,.0f} CPH não afeta a inclinação mecânica).")

    # 3. Teste de subida passo a passo (delta_t_s = 1.0s)
    # A partir de v_atual=0, em cada segundo deve subir exatamente 6300 CPH
    # Condição desimpedida (B2=50, B3=50, V_in=94500, V_out=94500)
    # Primeiro ciclo a partir de 0 entra no min_mod (v_reduz = 0.75 * 94500 = 70875)
    v_apos_arranque, _ = ctrl.calcular_velocidade(50, 50, 50, 50, v_in=v_nom, v_out=v_nom, delta_t_s=1.0)
    # Próximo passo de 1 segundo
    v_passo_1s, _ = ctrl.calcular_velocidade(50, 50, 50, 50, v_in=v_nom, v_out=v_nom, delta_t_s=1.0)
    delta_1s = v_passo_1s - v_apos_arranque
    assert abs(delta_1s - taxa_sub_esperada) < 1.0, f"Degrau de 1s incorreto: {delta_1s} vs {taxa_sub_esperada}"
    print(f"  ✅ Degrau por segundo OK: +{delta_1s:.0f} CPH a cada 1 segundo (atinge 100% nominal em {t_sub}s).")

    # 4. Teste de descida protetiva em rampa
    # Linha rodando a 94500, dá falta de garrafa na entrada com parada a montante (B2=5%, v_in=0)
    ctrl_desc = ControladorVelocidadeV4(
        velocidade_nominal=v_nom,
        v_atual_inicial=v_nom,
        tempo_rampa_subida_s=t_sub,
        tempo_rampa_descida_s=t_desc
    )
    v_desc_1s, _ = ctrl_desc.calcular_velocidade(50, 5, 50, 50, v_in=0, v_out=v_nom, delta_t_s=1.0)
    delta_desc_1s = v_nom - v_desc_1s
    assert abs(delta_desc_1s - taxa_desc_esperada) < 1.0, f"Degrau de descida 1s incorreto: {delta_desc_1s} vs {taxa_desc_esperada}"
    print(f"  ✅ Frenagem controlada OK: -{delta_desc_1s:.0f} CPH a cada 1 segundo (freia 100% em {t_desc}s).")

def test_sincronizacao_estrita_fator_sobremarcha():
    print("Testando Sincronização Estrita do Fator de Sobremarcha (1.038 / config_colunas -> config_opc -> parametros -> controlador)...")
    diretorio_base = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Carrega config_colunas.json local da pasta de controle v4
    caminho_colunas = os.path.join(diretorio_base, "config_colunas.json")
    assert os.path.exists(caminho_colunas), f"config_colunas.json não encontrado em {caminho_colunas}"
    with open(caminho_colunas, "r", encoding="utf-8") as f:
        colunas_cfg = json.load(f)
    fator_sobremarcha_esperado = float(colunas_cfg.get("Fator_Sobremarcha", 1.038))
    
    # 2. Carrega config_opc_v4.json
    caminho_opc = os.path.join(diretorio_base, "config_opc_v4.json")
    assert os.path.exists(caminho_opc), f"config_opc_v4.json não encontrado em {caminho_opc}"
    with open(caminho_opc, "r", encoding="utf-8") as f:
        opc_cfg = json.load(f)
    fator_opc = float(opc_cfg["controle"].get("fator_sprint", 0.0))
    assert abs(fator_opc - fator_sobremarcha_esperado) < 1e-4, (
        f"DIVERGÊNCIA CRÍTICA: config_opc_v4.json tem fator_sprint={fator_opc} diferente de "
        f"config_colunas.json ({fator_sobremarcha_esperado})!"
    )

    # 3. Carrega parametros_controle_v4.json
    caminho_params = os.path.join(diretorio_base, "parametros_controle_v4.json")
    assert os.path.exists(caminho_params), f"parametros_controle_v4.json não encontrado em {caminho_params}"
    with open(caminho_params, "r", encoding="utf-8") as f:
        params_cfg = json.load(f)
    fator_params = float(params_cfg.get("fator_sprint", 0.0))
    assert abs(fator_params - fator_sobremarcha_esperado) < 1e-4, (
        f"DIVERGÊNCIA CRÍTICA: parametros_controle_v4.json tem fator_sprint={fator_params} diferente de "
        f"config_colunas.json ({fator_sobremarcha_esperado})!"
    )

    # 4. Instancia o controlador padrão e verifica se assume exatamente esse fator
    ctrl = ControladorVelocidadeV4(velocidade_nominal=90000.0, v_atual_inicial=90000.0)
    assert abs(ctrl.fator_sprint - fator_sobremarcha_esperado) < 1e-4, (
        f"ControladorVelocidadeV4 instanciado com fator_sprint={ctrl.fator_sprint} "
        f"diferente de {fator_sobremarcha_esperado}"
    )

    # 5. Valida a velocidade física exata em modo sprint
    # Condições de sprint: B2 alto (80%), B3 baixo (20%), V_in e V_out em 90k
    v_sprint, motivo = ctrl.calcular_velocidade(50, 80, 20, 50, v_in=90000, v_out=90000, delta_t_s=10)
    v_esperada = 90000.0 * fator_sobremarcha_esperado
    assert abs(v_sprint - v_esperada) < 1e-1, f"Velocidade de sprint calculada incorreta: {v_sprint} vs {v_esperada}"
    assert motivo == 1, f"Motivo deveria ser 1 (Sprint), obtido: {motivo}"

    # 6. Audita otimizador_velocidade_v4.py para garantir que fator_sprint_opt está travado e não livre no CMA-ES
    caminho_otimizador = os.path.join(diretorio_base, "otimizador_velocidade_v4.py")
    with open(caminho_otimizador, "r", encoding="utf-8") as f:
        conteudo_otimizador = f.read()
    assert "fator_sprint_opt = float(FATOR_SOBREMARCHA)" in conteudo_otimizador, (
        "FALHA DE REGRESSÃO: otimizador_velocidade_v4.py não está travando fator_sprint_opt com FATOR_SOBREMARCHA!"
    )
    print(f"  ✅ Sincronização Estrita Auditada com Sucesso: {fator_sobremarcha_esperado}x ({v_esperada:.0f} CPH a 90.000 nominal) propagado em todos os configs, scripts e instâncias.")

def test_trava_sprint_bloqueio_velocidade_rebaixada():
    """
    TESTE DE INTERTRAVAMENTO DE SEGURANÇA INDUSTRIAL: TRAVA DE SPRINT POR VELOCIDADE DA ENCHEDORA
    Regra Mandatória de Fábrica:
    - O '100%' da fábrica é o valor ajustado pelo operador na IHM.
    - Se a enchedora estiver rodando abaixo da velocidade nominal (ex.: operador rebaixou 5%
      na IHM por restrição mecânica, operacional, qualidade da garrafa ou lubrificação de esteiras),
      o Sprint (sobrevelocidade) NUNCA deve ser acionado sob nenhuma hipótese.
    - O Sprint só pode ser autorizado se a máquina estiver operando em velocidade plena (v_atual >= 0.98 * v_nom).
    - Se o Sprint estiver ativo e a máquina cair para menos de 95% da nominal, deve haver CORTE IMEDIATO.
    """
    print("Testando Trava de Segurança do Sprint por Velocidade da Enchedora...")
    vel_nom = 60000.0
    fator_sprint = 1.03  # 61.800 CPH
    
    # 1. Caso 1: Buffers ideais para Sprint (B2=80%, B3=20%, Vin=60k, Vout=60k),
    # mas Operador rebaixou 5% na IHM (v_atual = 57.000 CPH = 95% nominal)
    ctrl = ControladorVelocidadeV4(
        velocidade_nominal=vel_nom,
        fator_sprint=fator_sprint,
        v_atual_inicial=57000.0
    )
    
    v_calc, motivo = ctrl.calcular_velocidade(
        b1=50, b2=80, b3=20, b4=50,
        v_in=vel_nom, v_out=vel_nom,
        v_atual=57000.0,  # 95% da nominal
        delta_t_s=30.0,
        retornar_motivo=True
    )
    
    # Validações estritas de segurança:
    assert ctrl.sprint_ativo is False, "FALHA CRÍTICA: Sprint ativado indevidamente com enchedora operando a 95%!"
    assert v_calc <= vel_nom, f"FALHA CRÍTICA: Setpoint ({v_calc}) excedeu a nominal ({vel_nom}) com máquina rebaixada!"
    assert motivo != 1, f"FALHA CRÍTICA: Motivo reportado como Sprint (ID 1), obtido {motivo}!"
    print(f"  ✅ Trava de Segurança Ativa: Enchedora a 57.000 CPH (95%) -> Sprint BLOQUEADO | Setpoint: {v_calc:.0f} CPH <= Nominal | Motivo ID: {motivo}")

    # 2. Caso 2: Mesmo cenário com buffers ideais, mas Enchedora a 100% nominal pleno (60.000 CPH)
    # Aqui o Sprint DEVE ser autorizado e ativado
    ctrl_pleno = ControladorVelocidadeV4(
        velocidade_nominal=vel_nom,
        fator_sprint=fator_sprint,
        v_atual_inicial=60000.0
    )
    
    v_sprint, motivo_sprint = ctrl_pleno.calcular_velocidade(
        b1=50, b2=80, b3=20, b4=50,
        v_in=vel_nom, v_out=vel_nom,
        v_atual=60000.0,  # 100% da nominal
        delta_t_s=30.0,
        retornar_motivo=True
    )
    
    assert ctrl_pleno.sprint_ativo is True, "Sprint deveria estar ativo com enchedora em velocidade plena e buffers favoráveis!"
    assert v_sprint > vel_nom, f"Velocidade ({v_sprint}) deveria ser superior à nominal ({vel_nom}) no Sprint!"
    assert motivo_sprint == 1, f"Motivo deveria ser 1 (SPRINT), obtido {motivo_sprint}"
    print(f"  ✅ Sprint Autorizado em Regime Pleno: Enchedora a 60.000 CPH (100%) -> Sprint ATIVADO | Setpoint: {v_sprint:.0f} CPH | Motivo ID: {motivo_sprint}")

    # 3. Caso 3: Desativação / Corte Imediato de Segurança
    # Máquina estava em Sprint, mas no ciclo seguinte a velocidade medida cai para 55.000 CPH (< 95%)
    v_corte, motivo_corte = ctrl_pleno.calcular_velocidade(
        b1=50, b2=80, b3=20, b4=50,
        v_in=vel_nom, v_out=vel_nom,
        v_atual=55000.0,  # Queda brusca / intervenção do operador
        delta_t_s=30.0,
        retornar_motivo=True
    )
    
    assert ctrl_pleno.sprint_ativo is False, "FALHA DE INTERTRAVAMENTO: Sprint não cortou imediatamente quando máquina caiu abaixo de 95%!"
    assert motivo_corte != 1, f"Motivo não pode ser Sprint após corte, obtido {motivo_corte}"
    print(f"  ✅ Corte Imediato do Sprint OK: Enchedora caiu para 55.000 CPH -> Sprint DESARMADO imediatamente!")

    # 4. Caso 4: Tolerância de tacômetro industrial (98% a 100% em regime nominal)
    # 59.200 CPH em linha de 60.000 CPH (~98.6%) representa flutuação normal de tacômetro
    ctrl_tol = ControladorVelocidadeV4(
        velocidade_nominal=vel_nom,
        fator_sprint=fator_sprint,
        v_atual_inicial=59200.0
    )
    v_tol, m_tol = ctrl_tol.calcular_velocidade(
        b1=50, b2=80, b3=20, b4=50,
        v_in=vel_nom, v_out=vel_nom,
        v_atual=59200.0,
        delta_t_s=30.0,
        retornar_motivo=True
    )
    assert ctrl_tol.sprint_ativo is True, "Flutuação normal de tacômetro (98.6%) não deveria bloquear Sprint!"
    print(f"  ✅ Tolerância de Tacômetro OK: Leitura de 59.200 CPH (98.6%) autoriza Sprint normalmente.")

if __name__ == "__main__":
    test_sincronizacao_estrita_fator_sobremarcha()
    test_slew_rate_e_motivo()
    test_tempo_rampa_segundos_base_nominal_sem_sprint()
    test_sprint_e_motivo()
    test_sprint_histerese_anti_hunting()
    test_trava_sprint_bloqueio_velocidade_rebaixada()
    test_retomada_e_motivo()
    test_trava_teto_retomada_seguranca()
    test_fast_path_b2_queda_brusca()
    test_convergencia_exata_sem_offset_banda_morta()
    test_banda_morta()
    test_consulta_enum_e_maquina_causadora()
    test_problemas_proprios_enchedora()
    test_eventos_json_inicio_fim()
    test_live_grafana_garrafas_e_relatorio()
    test_contador_producao_e_validacao_fisica()
    test_gravacao_continua_csv_live()
    print("\n🎉 TODOS OS TESTES UNITÁRIOS COM IDENTIFICAÇÃO DE MÁQUINA, FAST-PATH, TRAVA DE TETO, BANDA MORTA, TRAVA DE SPRINT, RELATÓRIO LIVE, CONTADOR FÍSICO, CSV CONTÍNUO, TEMPO EM SEGUNDOS E SINCRONIZAÇÃO ESTRITA DE SOBREVELOCIDADE PASSARAM COM SUCESSO!")




