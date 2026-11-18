import os
os.environ['MPLCONFIGDIR'] = '/home/antonio/Projetos/OtimizadorSegue/scratch'
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import matplotlib.patches as patches
import numpy as np
import subprocess

out_dir = '/home/antonio/Projetos/OtimizadorSegue/relatorio_trava1_segue1'
total_frames = 120

fig, ax = plt.subplots(figsize=(14, 8.5), dpi=100)
fig.patch.set_facecolor('#050811')
ax.set_facecolor('#050811')

def draw_futuristic_frame(frame):
    ax.clear()
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')
    
    # Timeline
    if frame < 45:
        t_prog = 0.0
    elif frame < 65:
        t_prog = (frame - 45) / 20.0
    elif frame < 110:
        t_prog = 1.0
    else:
        t_prog = 1.0 - (frame - 110) / 10.0
        
    v_shadow = 20000
    v_segue = 25000
    v_inversor = int(v_shadow + (v_segue - v_shadow) * t_prog)
    ganho_instantaneo = v_inversor - v_shadow
    is_segue_active = (t_prog > 0.5)
    
    # --- 1. CYBERNETIC BACKGROUND GRID ---
    for gx in np.linspace(0, 100, 21):
        ax.axvline(gx, color='#0ea5e9', alpha=0.04, lw=0.6, ls=':')
    for gy in np.linspace(0, 100, 21):
        ax.axhline(gy, color='#0ea5e9', alpha=0.04, lw=0.6, ls=':')
        
    def add_neon_box(xy, width, height, base_color, glow_color, bg_color='#060d1a', alpha_bg=0.88, title=None, sub=None):
        x, y = xy
        # Glowing shadow layers
        for w_offset, a in [(3.5, 0.08), (2.0, 0.18)]:
            ax.add_patch(patches.FancyBboxPatch(
                (x - w_offset*0.1, y - w_offset*0.1), width + w_offset*0.2, height + w_offset*0.2,
                boxstyle='round,pad=0.2', facecolor='none', edgecolor=glow_color, lw=w_offset, alpha=a
            ))
        # Main Box
        box = patches.FancyBboxPatch(
            (x, y), width, height, boxstyle='round,pad=0.2',
            facecolor=bg_color, edgecolor=base_color, lw=1.6, alpha=alpha_bg
        )
        ax.add_patch(box)
        # Tech corner accents
        c_len = 2.0
        ax.plot([x + 0.5, x + 0.5 + c_len], [y + height - 0.5, y + height - 0.5], color=glow_color, lw=1.5)
        ax.plot([x + 0.5, x + 0.5], [y + height - 0.5 - c_len, y + height - 0.5], color=glow_color, lw=1.5)
        ax.plot([x + width - 0.5 - c_len, x + width - 0.5], [y + height - 0.5, y + height - 0.5], color=glow_color, lw=1.5)
        ax.plot([x + width - 0.5, x + width - 0.5], [y + height - 0.5 - c_len, y + height - 0.5], color=glow_color, lw=1.5)
        
        # Bottom corners
        ax.plot([x + 0.5, x + 0.5 + c_len], [y + 0.5, y + 0.5], color=glow_color, lw=1.5)
        ax.plot([x + 0.5, x + 0.5], [y + 0.5 + c_len, y + 0.5], color=glow_color, lw=1.5)
        ax.plot([x + width - 0.5 - c_len, x + width - 0.5], [y + 0.5, y + 0.5], color=glow_color, lw=1.5)
        ax.plot([x + width - 0.5, x + width - 0.5], [y + 0.5 + c_len, y + 0.5], color=glow_color, lw=1.5)
        
        if title:
            ax.text(x + width/2, y + height - 2.8, title, fontsize=8.2, fontweight='bold', color=glow_color, ha='center')
        if sub:
            ax.text(x + width/2, y + height - 5.5, sub, fontsize=6.8, color='#64748B', ha='center')

    # --- 2. HEADER: FUTURISTIC INDUSTRIAL HUD ---
    ax.text(3, 97.2, '◆ SEGUE-APC // ARCHITECTURE MATRIX', fontsize=12.5, fontweight='black', color='#38BDF8', ha='left')
    ax.text(97, 97.2, f'FRAME [{frame:03d}/120]  ● LIVE TELEMETRY', fontsize=9, fontweight='bold', color='#00F0FF', ha='right', family='monospace')
    
    # Status Banner
    if t_prog < 0.2:
        top_glow = '#F59E0B'
        top_txt = 'STATUS: [ BASELINE ACTIVE ] ➔ ROTA B (CLP TRADICIONAL) NO INVERSOR | SEGUE EM MODO SOMBRA'
    elif t_prog > 0.8:
        top_glow = '#00FF88'
        top_txt = 'STATUS: [ OTIMIZAÇÃO AVANÇADA ] ➔ ROTA A (SEGUE APC) NO INVERSOR | GANHO: +5.000 BPH'
    else:
        top_glow = '#38BDF8'
        top_txt = 'STATUS: [ COMUTAÇÃO DINÂMICA ] ➔ DESTRAVANDO ESTRELA E TRANSFERINDO COMANDO AO SEGUE...'
        
    add_neon_box((3, 90.5), 94, 4.8, '#1E293B', top_glow, bg_color='#030712', alpha_bg=0.95)
    ax.text(50, 92.9, top_txt, fontsize=9.2, fontweight='bold', color='#FFFFFF', ha='center', va='center', family='sans-serif')
    
    # Pulse dot
    p_alpha = 0.5 + 0.5 * np.sin(frame * 0.4)
    ax.plot([6.5], [92.9], marker='o', markersize=6, color=top_glow, alpha=p_alpha)

    # --- 3. LEFT HUD: INTERLOCKS & OPTICAL STARWHEEL (X: 3 a 24) ---
    add_neon_box((3, 56.5), 21, 31.8, '#1E293B', '#38BDF8', title='SYS_INTERLOCKS', sub='// TELEMETRIA DE CAMPO')
    
    # Trava Entrada
    is_destravada = True
    add_neon_box((4.5, 71.5), 18, 8.5, '#064E3B' if is_destravada else '#451A03',
                 '#00FF88' if is_destravada else '#F59E0B', bg_color='#021b14', alpha_bg=0.9)
    ax.text(13.5, 77.2, 'TRAVA DE ENTRADA', fontsize=7.5, color='#94A3B8', ha='center', fontweight='bold')
    ax.text(13.5, 73.5, 'DESTRAVADA (1)', fontsize=9.5, fontweight='black', color='#00FF88', ha='center')
    
    # SEGUE Habilitado
    add_neon_box((4.5, 59), 18, 9.5, '#064E3B' if is_segue_active else '#1E293B',
                 '#00FF88' if is_segue_active else '#EF4444', bg_color='#021b14' if is_segue_active else '#180a0a')
    ax.text(13.5, 66, 'SEGUE HABILITADO', fontsize=7.5, color='#94A3B8', ha='center', fontweight='bold')
    st_txt = 'ATIVO [1]' if is_segue_active else 'STANDBY [0]'
    ax.text(13.5, 61.5, st_txt, fontsize=9.5, fontweight='black', 
            color='#00FF88' if is_segue_active else '#EF4444', ha='center')

    # Estrela de Entrada Holográfica (X: 3 a 24, Y: 10.5 a 53.5)
    add_neon_box((3, 10.5), 21, 43.5, '#1E293B', '#00F0FF', title='ALIMENTADOR ROTATIVO', sub='// SENSOR ÓPTICO DE BOCA')
    
    star_center = (13.5, 29.5)
    rx = 6.4
    ry = rx * (14.0 / 8.5)
    
    # Outer HUD reticle rings
    for ring_r, ring_alpha in [(1.08, 0.2), (1.0, 0.8), (0.4, 0.4)]:
        el = patches.Ellipse(star_center, rx * 2 * ring_r, ry * 2 * ring_r, 
                             facecolor='none', edgecolor='#00F0FF', lw=1.2, ls=':' if ring_r > 1 else '-', alpha=ring_alpha)
        ax.add_patch(el)
        
    ang_offset = frame * (0.16 if is_segue_active else 0.07)
    for i in range(6):
        ang = ang_offset + i * (np.pi / 3)
        dx = rx * np.cos(ang)
        dy = ry * np.sin(ang)
        ax.plot([star_center[0], star_center[0] + dx], [star_center[1], star_center[1] + dy], 
                color='#38BDF8', lw=1.6, alpha=0.8)
        # Laser sensor blip at bottle holder
        ax.plot(star_center[0] + dx, star_center[1] + dy, marker='o', markersize=6.5, 
                color='#00FF88' if is_segue_active else '#F59E0B')
        # Pocket glow
        ax.plot(star_center[0] + dx, star_center[1] + dy, marker='o', markersize=11, 
                color='#00FF88' if is_segue_active else '#F59E0B', alpha=0.25)
        
    ax.plot(star_center[0], star_center[1], marker='o', markersize=8, color='#FFFFFF')
    
    # Laser scanning line across feeder
    scan_y = star_center[1] + ry * np.sin(frame * 0.25) * 0.8
    ax.plot([star_center[0] - rx*0.9, star_center[0] + rx*0.9], [scan_y, scan_y], color='#00F0FF', lw=1.2, alpha=0.45, ls='--')
    
    ax.text(13.5, 15.5, 'FLUXO NOMINAL DETECTADO\n100% dos Pockets Cheios', 
            fontsize=7.2, fontweight='bold', color='#6EE7B7' if is_segue_active else '#FDE68A', ha='center')

    # --- 4. CENTRAL ZONE: SIDE-BY-SIDE PARALLEL CHANNELS (X: 27 a 72) ---
    ax.text(49.5, 87.2, 'ROTAS PARALELAS DE CONTROLE (OU 1 OU OUTRO)', 
            fontsize=10.5, fontweight='black', color='#F1F5F9', ha='center', family='sans-serif')
    
    # CAMINHO A: SEGUE (APC) (X: 27 a 47)
    c_a_glow = '#00F0FF' if is_segue_active else '#334155'
    c_a_bg = '#02182B' if is_segue_active else '#0a0f1d'
    add_neon_box((27, 67), 20, 17.5, '#1E3A8A' if is_segue_active else '#1E293B', c_a_glow, bg_color=c_a_bg)
    ax.text(37, 81.5, 'CANAL A [APC]', fontsize=8, fontweight='black', color='#00F0FF', ha='center')
    ax.text(37, 77.8, 'SEGUE (APC)', fontsize=12, fontweight='black', color='#FFFFFF', ha='center')
    ax.text(37, 71.8, f'{v_segue:,} bph'.replace(',', '.'), fontsize=13.5, fontweight='black', 
            color='#00F0FF' if is_segue_active else '#475569', ha='center', family='monospace')
    ax.text(37, 68, 'SETPOINT OTIMIZADO', fontsize=7, fontweight='bold', color='#93C5FD' if is_segue_active else '#475569', ha='center')

    # CAMINHO B: CLP TRADICIONAL / SHADOW (X: 52 a 72)
    c_b_glow = '#F59E0B' if not is_segue_active else '#334155'
    c_b_bg = '#221504' if not is_segue_active else '#0a0f1d'
    add_neon_box((52, 67), 20, 17.5, '#78350F' if not is_segue_active else '#1E293B', c_b_glow, bg_color=c_b_bg)
    ax.text(62, 81.5, 'CANAL B [BASE]', fontsize=8, fontweight='black', color='#F59E0B', ha='center')
    ax.text(62, 77.8, 'CLP / SHADOW', fontsize=12, fontweight='black', color='#FFFFFF', ha='center')
    ax.text(62, 71.8, f'{v_shadow:,} bph'.replace(',', '.'), fontsize=13.5, fontweight='black', 
            color='#F59E0B' if not is_segue_active else '#475569', ha='center', family='monospace')
    ax.text(62, 68, 'LÓGICA CONSERVADORA', fontsize=7, fontweight='bold', color='#FDE68A' if not is_segue_active else '#475569', ha='center')

    # CHAVE SELETORA SPDT HIGH-TECH (X: 31 a 68, Y: 46 a 63)
    add_neon_box((31, 46.2), 37, 17.0, '#1E293B', '#00F0FF', 
                 title='COMUTADOR AUTOMÁTICO DE SETPOINT ("1 OU OUTRO")', bg_color='#050B16')
    
    term_a = (37, 57.5)
    term_b = (62, 57.5)
    common_pole = (49.5, 48)
    
    # Connecting conduits from channels to switch terminals
    ax.plot([37, 37], [67, term_a[1]], color='#00FF88' if is_segue_active else '#334155', 
            lw=3 if is_segue_active else 1.5, ls='-' if is_segue_active else ':')
    ax.plot([62, 62], [67, term_b[1]], color='#334155' if is_segue_active else '#F59E0B', 
            lw=1.5 if is_segue_active else 3, ls=':' if is_segue_active else '-')
    
    # Terminal contact nodes
    ax.plot(term_a[0], term_a[1], marker='o', markersize=7, color='#00FF88' if is_segue_active else '#475569')
    ax.plot(term_b[0], term_b[1], marker='o', markersize=7, color='#475569' if is_segue_active else '#F59E0B')
    ax.plot(common_pole[0], common_pole[1], marker='o', markersize=8, color='#FFFFFF')
    
    # Dynamic Blade Position & Laser Plasma Beam
    target_contact_x = term_b[0] + (term_a[0] - term_b[0]) * t_prog
    target_contact_y = term_b[1] + (term_a[1] - term_b[1]) * t_prog
    beam_color = '#00FF88' if is_segue_active else '#F59E0B'
    
    # Plasma Glow of the Switch Blade
    for w_glow, a_glow in [(8, 0.15), (4, 0.4), (2.2, 0.9)]:
        ax.plot([common_pole[0], target_contact_x], [common_pole[1], target_contact_y], 
                color=beam_color, lw=w_glow, alpha=a_glow)
    
    # High-Tech Status Badges
    if is_segue_active:
        ax.text(37, 53.8, '✔ ROTA A: CONECTADA', fontsize=7.2, fontweight='black', color='#00FF88', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#022619', edgecolor='#00FF88', lw=1))
        ax.text(62, 53.8, '✖ ROTA B: CORTADA', fontsize=7.2, fontweight='black', color='#EF4444', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#250808', edgecolor='#EF4444', lw=1))
    else:
        ax.text(37, 53.8, '✖ ROTA A: DESCONECTADA', fontsize=7.2, fontweight='black', color='#EF4444', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#250808', edgecolor='#EF4444', lw=1))
        ax.text(62, 53.8, '✔ ROTA B: CONECTADA', fontsize=7.2, fontweight='black', color='#F59E0B', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#291603', edgecolor='#F59E0B', lw=1))
        
    # Laser conduit to Inverter
    for w_glow, a_glow in [(7, 0.15), (3.5, 0.4), (2, 0.9)]:
        ax.plot([49.5, 49.5], [common_pole[1], 39.5], color=beam_color, lw=w_glow, alpha=a_glow)
    ax.plot([49.5], [39.5], marker='v', markersize=8, color=beam_color)

    # Multi-pulse photon packets streaming along active conduits
    for p_offset in [0.0, 0.5]:
        pulse_phase = ((frame * 0.08) + p_offset) % 1.0
        if is_segue_active:
            # Down Channel A
            py1 = 67 - pulse_phase * (67 - term_a[1])
            ax.plot([37], [py1], marker='o', markersize=4.5, color='#FFFFFF')
            ax.plot([37], [py1], marker='o', markersize=9, color='#00FF88', alpha=0.5)
            # Down to Inverter
            py2 = common_pole[1] - pulse_phase * (common_pole[1] - 39.5)
            ax.plot([49.5], [py2], marker='o', markersize=4.5, color='#FFFFFF')
            ax.plot([49.5], [py2], marker='o', markersize=9, color='#00FF88', alpha=0.5)
        else:
            # Down Channel B
            py1 = 67 - pulse_phase * (67 - term_b[1])
            ax.plot([62], [py1], marker='o', markersize=4.5, color='#FFFFFF')
            ax.plot([62], [py1], marker='o', markersize=9, color='#F59E0B', alpha=0.5)
            # Down to Inverter
            py2 = common_pole[1] - pulse_phase * (common_pole[1] - 39.5)
            ax.plot([49.5], [py2], marker='o', markersize=4.5, color='#FFFFFF')
            ax.plot([49.5], [py2], marker='o', markersize=9, color='#F59E0B', alpha=0.5)

    # --- 5. INVERSOR DE FREQUÊNCIA (SMART DRIVE) (X: 27 a 72, Y: 28.5 a 39.5) ---
    inv_glow = '#00FF88' if is_segue_active else '#F59E0B'
    inv_bg = '#021e14' if is_segue_active else '#241303'
    add_neon_box((27, 28.5), 45, 11, '#1E293B', inv_glow, bg_color=inv_bg)
    
    # Mini digital frequency waveform
    t_wave = np.linspace(29, 69, 50)
    w_freq = 0.8 if is_segue_active else 0.4
    y_wave = 34 + 1.2 * np.sin(t_wave * w_freq + frame * 0.3)
    ax.plot(t_wave, y_wave, color=inv_glow, alpha=0.3, lw=1.2)
    
    ax.text(49.5, 36.2, f'INVERSOR // SETPOINT = {v_inversor:,} bph'.replace(',', '.'), 
            fontsize=12.5, fontweight='black', color='#FFFFFF', ha='center', family='monospace')
    rot_orig = 'FONTE ATIVA: CANAL A (SEGUE APC EM MALHA FECHADA)' if is_segue_active else 'FONTE ATIVA: CANAL B (CLP TRADICIONAL)'
    ax.text(49.5, 31.5, rot_orig, fontsize=8, fontweight='bold', color=inv_glow, ha='center')

    # --- 6. RIGHT HUD: CONTRAFACTUAL BENEFIT TELEMETRY (X: 75 a 97, Y: 28.5 a 88) ---
    add_neon_box((75, 28.5), 22, 59.8, '#1E293B', '#00FF88' if is_segue_active else '#64748B', 
                 title='BENEFÍCIO CONTRAFACTUAL', sub='// REAL-TIME AUDIT', bg_color='#050c18')
    
    # Fórmula HUD
    add_neon_box((76.5, 68), 19, 9.8, '#1E293B', '#38BDF8', bg_color='#021224', alpha_bg=0.9)
    ax.text(86, 75.2, 'EQUAÇÃO DE GANHO', fontsize=7, fontweight='bold', color='#38BDF8', ha='center')
    ax.text(86, 71, 'Δ = [ROTA A] − [ROTA B]', fontsize=8, fontweight='black', color='#FDE047', ha='center', family='monospace')

    # Readouts digitais
    ax.text(77, 63, 'Inversor (A):', fontsize=8, color='#94A3B8', fontweight='bold')
    ax.text(95, 63, f'{v_inversor:,} bph'.replace(',', '.'), fontsize=8.5, fontweight='bold', 
            color='#00FF88' if is_segue_active else '#F59E0B', ha='right', family='monospace')
    
    ax.text(77, 58, 'Shadow (B):', fontsize=8, color='#94A3B8', fontweight='bold')
    ax.text(95, 58, f'{v_shadow:,} bph'.replace(',', '.'), fontsize=8.5, fontweight='bold', 
            color='#64748B', ha='right', family='monospace')

    ax.plot([77, 95], [55, 55], color='#334155', lw=1, ls='--')

    # Benefício capturado grande
    ax.text(86, 51, 'GANHO CAPTURADO', fontsize=8, fontweight='black', color='#CBD5E1', ha='center')
    txt_g = f'+{ganho_instantaneo:,} bph'.replace(',', '.') if is_segue_active else '0 bph'
    ax.text(86, 44.5, txt_g, fontsize=14.5, fontweight='black', 
            color='#00FF88' if is_segue_active else '#64748B', ha='center', family='monospace')
    
    pct_g = f'+{(ganho_instantaneo/v_shadow)*100:.1f}%' if is_segue_active else '0.0%'
    ax.text(86, 38.5, f'PRODUTIVIDADE: {pct_g}', fontsize=8, fontweight='black', 
            color='#FDE047' if is_segue_active else '#475569', ha='center')

    # Telemetria inferior do painel
    telemetry_tag = '✔ CAPTURA DE VAZÃO ATIVA' if is_segue_active else 'STANDBY // SEM ESCRITA'
    ax.text(86, 32.5, telemetry_tag, fontsize=7.2, fontweight='bold', 
            color='#00FF88' if is_segue_active else '#94A3B8', ha='center')

    # --- 7. CONVEYOR & NEON HOLOGRAPHIC BOTTLES (X: 27 a 97, Y: 10.5 a 25.5) ---
    ax.text(62, 26, 'ESTEIRA DE ENVASE // SAÍDA FÍSICA DE PRODUÇÃO', 
            fontsize=9.2, fontweight='black', color='#94A3B8', ha='center')
    
    add_neon_box((27, 10.8), 70, 13.5, '#1E293B', '#38BDF8', bg_color='#030712', alpha_bg=0.95)
    
    # Neon Guide rails
    ax.plot([28, 96], [12, 12], color='#00F0FF', lw=1.2, alpha=0.4)
    ax.plot([28, 96], [23, 23], color='#00F0FF', lw=1.2, alpha=0.4)
    
    speed_factor = 1.7 if is_segue_active else 1.0
    n_bottles = 13
    for b in range(n_bottles):
        bx = ((frame * speed_factor * 1.3) + b * (68 / n_bottles)) % 68 + 28
        is_bonus = is_segue_active and (b % 4 == 0)
        
        b_color = '#00FF88' if is_bonus else ('#00F0FF' if is_segue_active else '#EAB308')
        
        # Futuristic holographic bottle body
        b_body = patches.Rectangle((bx - 1.1, 12.5), 2.2, 6.5, facecolor=b_color, edgecolor='#FFFFFF', lw=0.6, alpha=0.85)
        ax.add_patch(b_body)
        b_neck = patches.Rectangle((bx - 0.55, 19), 1.1, 3.2, facecolor=b_color, edgecolor='#FFFFFF', lw=0.5, alpha=0.85)
        ax.add_patch(b_neck)
        
        # High-tech boost symbol on bonus bottles
        if is_bonus:
            ax.text(bx, 15.5, '⚡', fontsize=8.5, fontweight='bold', color='#FFFFFF', ha='center', va='center')

    # --- 8. BOTTOM AUDIT BAR: INDUSTRIAL CONSOLIDATED METRICS ---
    if is_segue_active:
        add_neon_box((3, 1.5), 94, 6.8, '#064E3B', '#00FF88', bg_color='#021c14')
        ax.text(50, 5.7, 'DADOS AUDITADOS EM CAMPO // PERÍODO RIGOROSO (Trava Entrada == 1 & SEGUE Habilitado == 1):', 
                fontsize=8.2, fontweight='black', color='#6EE7B7', ha='center')
        ax.text(50, 3.0, 'GANHO LÍQUIDO: +707 GARRAFAS/HORA  |  +4.890 GARRAFAS NO PERÍODO  |  +3,70% SOBRE O SHADOW', 
                fontsize=9.8, fontweight='black', color='#FFFFFF', ha='center', family='monospace')
    else:
        add_neon_box((3, 1.5), 94, 6.8, '#451A03', '#F59E0B', bg_color='#241202')
        ax.text(50, 5.7, 'MODO DE SEGURANÇA BASELINE // MÁQUINA OPERANDO POR LÓGICA PADRÃO CONSERVADORA:', 
                fontsize=8.2, fontweight='black', color='#FDE68A', ha='center')
        ax.text(50, 3.0, 'INVERSOR LIMITADO A 20.000 BPH  |  POTENCIAL DO SEGUE MONITORADO EM MODO SOMBRA', 
                fontsize=9.8, fontweight='black', color='#FFFFFF', ha='center', family='monospace')

print("Gerando FuncAnimation futurista...")
anim = animation.FuncAnimation(fig, draw_futuristic_frame, frames=total_frames, interval=80)
gif_file = f'{out_dir}/animacao_segue_habilitado_estrela_garrafas.gif'
mp4_file = f'{out_dir}/animacao_segue_habilitado_estrela_garrafas.mp4'

print(f"Salvando GIF em {gif_file}...")
anim.save(gif_file, writer='pillow', fps=12)
plt.close()
print("GIF futurista gerado com sucesso!")

# Converter GIF para MP4 otimizado com ffmpeg
print(f"Gerando MP4 em {mp4_file} via ffmpeg...")
cmd = [
    'ffmpeg', '-y',
    '-i', gif_file,
    '-movflags', 'faststart',
    '-pix_fmt', 'yuv420p',
    '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
    mp4_file
]
subprocess.run(cmd, check=True)
print(f"MP4 futurista gerado com sucesso em: {mp4_file}")
