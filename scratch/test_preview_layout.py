import os
os.environ['MPLCONFIGDIR'] = '/home/antonio/Projetos/OtimizadorSegue/scratch'
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

def draw_frame(ax, frame, total_frames=120):
    ax.clear()
    ax.set_xlim(0, 100)
    ax.set_ylim(100, 0) if False else ax.set_ylim(0, 100)
    ax.axis('off')
    
    # 0 a 45: Modo Baseline (CLP ativo, SEGUE inativo)
    # 45 a 65: Transição chaveando para SEGUE (lâmina vira de B para A, rampa de velocidade)
    # 65 a 110: SEGUE Ativo (SEGUE ativo, CLP cortado)
    # 110 a 120: Transição suave de retorno
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
    
    # 1. TÍTULO PRINCIPAL
    ax.text(50, 97.2, 'ARQUITETURA DE CONTROLE E MEDIÇÃO DE BENEFÍCIO', 
            fontsize=14, fontweight='bold', color='#FFFFFF', ha='center', va='center')
    
    # 2. STATUS BANNER SUPERIOR
    if t_prog < 0.2:
        b_color = '#78350F'
        b_txt = 'MODO BASELINE: Rota CLP selecionada (20.000 bph) | SEGUE em sombra (sem escrita no inversor)'
    elif t_prog > 0.8:
        b_color = '#065F46'
        b_txt = 'MODO OTIMIZADO: Rota SEGUE selecionada (25.000 bph) | Ganho Líquido: [SEGUE − SHADOW] = +5.000 bph'
    else:
        b_color = '#1E3A8A'
        b_txt = 'COMUTAÇÃO DE ROTA: Destravando estrela e transferindo controle para o SEGUE (APC)...'
        
    banner = patches.FancyBboxPatch((3, 90.5), 94, 4.3, boxstyle='round,pad=0.3', facecolor=b_color, edgecolor='none')
    ax.add_patch(banner)
    ax.text(50, 92.6, b_txt, fontsize=9.5, fontweight='bold', color='#FFFFFF', ha='center', va='center')
    
    # 3. COLUNA DA ESQUERDA: INTERTRAVAMENTOS E ESTRELA (X: 3 a 24)
    # Box de Condições de Controle
    b_cmd = patches.FancyBboxPatch((3, 56), 21, 32.5, boxstyle='round,pad=0.4',
                                  facecolor='#111827', edgecolor='#374151', lw=1.5)
    ax.add_patch(b_cmd)
    ax.text(13.5, 85.5, 'INTERTRAVAMENTOS', fontsize=9.5, fontweight='bold', color='#F3F4F6', ha='center')
    ax.text(13.5, 82.5, 'CONDIÇÕES DO SISTEMA', fontsize=7.5, color='#9CA3AF', ha='center')
    
    # Status Trava de Entrada
    is_trava_destravada = (t_prog > 0.3)
    t_box = patches.FancyBboxPatch((4.5, 71.5), 18, 8.5, boxstyle='round,pad=0.3',
                                  facecolor='#064E3B' if is_trava_destravada else '#451A03',
                                  edgecolor='#10B981' if is_trava_destravada else '#F59E0B', lw=1.5)
    ax.add_patch(t_box)
    ax.text(13.5, 77.2, 'Trava Entrada', fontsize=8, color='#D1D5DB', ha='center')
    ax.text(13.5, 73.5, 'DESTRAVADA (1)' if is_trava_destravada else 'DESTRAVADA (1)', 
            fontsize=9.5, fontweight='bold', color='#34D399' if is_trava_destravada else '#FBBF24', ha='center')
    
    # Status Habilitação SEGUE
    s_box = patches.FancyBboxPatch((4.5, 59), 18, 9.5, boxstyle='round,pad=0.3',
                                  facecolor='#064E3B' if is_segue_active else '#1E293B',
                                  edgecolor='#10B981' if is_segue_active else '#64748B', lw=1.5)
    ax.add_patch(s_box)
    ax.text(13.5, 66, 'SEGUE Habilitado', fontsize=8, color='#D1D5DB', ha='center')
    ax.text(13.5, 61.5, 'LIGADO (1)' if is_segue_active else 'DESLIGADO (0)', 
            fontsize=9.5, fontweight='bold', color='#34D399' if is_segue_active else '#F87171', ha='center')

    # Estrela de Entrada Alimentada (X: 3 a 24, Y: 10.5 a 53.5)
    b_star_box = patches.FancyBboxPatch((3, 10.5), 21, 43, boxstyle='round,pad=0.4',
                                       facecolor='#0F172A', edgecolor='#334155', lw=1.5)
    ax.add_patch(b_star_box)
    ax.text(13.5, 50.5, 'ESTRELA DE ENTRADA', fontsize=9, fontweight='bold', color='#60A5FA', ha='center')
    ax.text(13.5, 47.5, 'Alimentação de Garrafas', fontsize=7.5, color='#94A3B8', ha='center')
    
    # Circular aspect ratio correction: 14 x 8.5
    star_center = (13.5, 29.5)
    rx = 6.2
    ry = rx * (14.0 / 8.5)
    star_ellipse = patches.Ellipse(star_center, rx * 2, ry * 2, facecolor='#1E293B', edgecolor='#38BDF8', lw=2)
    ax.add_patch(star_ellipse)
    
    ang_offset = frame * (0.14 if is_segue_active else 0.06)
    for i in range(6):
        ang = ang_offset + i * (np.pi / 3)
        dx = rx * np.cos(ang)
        dy = ry * np.sin(ang)
        ax.plot([star_center[0], star_center[0] + dx], [star_center[1], star_center[1] + dy], color='#93C5FD', lw=1.5)
        ax.plot(star_center[0] + dx, star_center[1] + dy, marker='o', markersize=6, 
                color='#10B981' if is_segue_active else '#F59E0B')
    ax.plot(star_center[0], star_center[1], marker='o', markersize=6, color='#FFFFFF')
    
    ax.text(13.5, 15.5, 'GARRAFAS PRESENTES\nFluxo contínuo destravado', 
            fontsize=7.5, fontweight='bold', color='#6EE7B7' if is_segue_active else '#FDE68A', ha='center')
    
    # 4. ZONA CENTRAL: DOIS CAMINHOS LADO A LADO (OU 1 OU OUTRO) (X: 27 a 72)
    # Título do Módulo
    ax.text(49.5, 87, 'CAMINHOS PARALELOS DE CONTROLE (OU 1 OU OUTRO)', 
            fontsize=10.5, fontweight='bold', color='#E2E8F0', ha='center')
    
    # CAMINHO A: SEGUE (APC) (X: 27 a 47, Y: 67 a 84.5)
    c_segue_face = '#1E3A8A' if is_segue_active else '#1E293B'
    c_segue_edge = '#3B82F6' if is_segue_active else '#475569'
    b_path_a = patches.FancyBboxPatch((27, 67), 20, 17.5, boxstyle='round,pad=0.4',
                                     facecolor=c_segue_face, edgecolor=c_segue_edge, lw=2)
    ax.add_patch(b_path_a)
    ax.text(37, 81.5, 'CAMINHO A', fontsize=8.5, fontweight='bold', color='#93C5FD', ha='center')
    ax.text(37, 78, 'SEGUE (APC)', fontsize=11.5, fontweight='bold', color='#FFFFFF', ha='center')
    ax.text(37, 72, f'{v_segue:,} bph'.replace(',', '.'), fontsize=13, fontweight='bold', 
            color='#38BDF8' if is_segue_active else '#64748B', ha='center')
    ax.text(37, 68, '(Setpoint Otimizado)', fontsize=7.5, color='#CBD5E1', ha='center')

    # CAMINHO B: CLP TRADICIONAL / SHADOW (X: 52 a 72, Y: 67 a 84.5)
    c_clp_face = '#1E293B' if is_segue_active else '#78350F'
    c_clp_edge = '#475569' if is_segue_active else '#F59E0B'
    b_path_b = patches.FancyBboxPatch((52, 67), 20, 17.5, boxstyle='round,pad=0.4',
                                     facecolor=c_clp_face, edgecolor=c_clp_edge, lw=2)
    ax.add_patch(b_path_b)
    ax.text(62, 81.5, 'CAMINHO B', fontsize=8.5, fontweight='bold', color='#FDE68A', ha='center')
    ax.text(62, 78, 'CLP / SHADOW', fontsize=11.5, fontweight='bold', color='#FFFFFF', ha='center')
    ax.text(62, 72, f'{v_shadow:,} bph'.replace(',', '.'), fontsize=13, fontweight='bold', 
            color='#64748B' if is_segue_active else '#FBBF24', ha='center')
    ax.text(62, 68, '(Lógica Conservadora)', fontsize=7.5, color='#CBD5E1', ha='center')

    # CHAVE SELETORA SPDT (Single Pole Double Throw) (Y: 46 a 63, X: 31 a 68)
    b_sel = patches.FancyBboxPatch((31, 46.5), 37, 16.5, boxstyle='round,pad=0.3',
                                  facecolor='#0B1120', edgecolor='#38BDF8', lw=1.5)
    ax.add_patch(b_sel)
    ax.text(49.5, 61, 'CHAVE SELETORA AUTOMÁTICA ("OU 1 OU OUTRO")', 
            fontsize=8, fontweight='bold', color='#38BDF8', ha='center')
    
    # Coordenadas dos Terminais
    term_a = (37, 57.5)
    term_b = (62, 57.5)
    common_pole = (49.5, 48)
    
    # Linhas de alimentação dos blocos A e B até os terminais
    ax.plot([37, 37], [67, term_a[1]], color='#10B981' if is_segue_active else '#64748B', 
            lw=3 if is_segue_active else 1.5, linestyle='-' if is_segue_active else '--')
    ax.plot([62, 62], [67, term_b[1]], color='#64748B' if is_segue_active else '#F59E0B', 
            lw=1.5 if is_segue_active else 3, linestyle='--' if is_segue_active else '-')
    
    # Pontos de contato dos terminais
    ax.plot(term_a[0], term_a[1], marker='o', markersize=6, color='#10B981' if is_segue_active else '#64748B')
    ax.plot(term_b[0], term_b[1], marker='o', markersize=6, color='#64748B' if is_segue_active else '#F59E0B')
    ax.plot(common_pole[0], common_pole[1], marker='o', markersize=7, color='#FFFFFF')
    
    # Animação suave da Lâmina da Chave: interpola de term_b para term_a
    target_contact_x = term_b[0] + (term_a[0] - term_b[0]) * t_prog
    target_contact_y = term_b[1] + (term_a[1] - term_b[1]) * t_prog
    blade_color = '#10B981' if is_segue_active else '#F59E0B'
    ax.plot([common_pole[0], target_contact_x], [common_pole[1], target_contact_y], color=blade_color, lw=3.8)
    
    # Badges nos lados da chave seletora
    if is_segue_active:
        ax.text(37, 54, 'ROTA A CONECTADA', fontsize=7, fontweight='bold', color='#34D399', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#064E3B', edgecolor='#10B981', lw=0.8))
        ax.text(62, 54, '✂ ROTA B CORTADA', fontsize=7, fontweight='bold', color='#FCA5A5', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#450A0A', edgecolor='#EF4444', lw=0.8))
    else:
        ax.text(37, 54, '✖ ROTA A ABERTA', fontsize=7, fontweight='bold', color='#FCA5A5', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#450A0A', edgecolor='#EF4444', lw=0.8))
        ax.text(62, 54, 'ROTA B CONECTADA', fontsize=7, fontweight='bold', color='#FDE68A', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#78350F', edgecolor='#F59E0B', lw=0.8))
        
    # Seta descendo do polo comum para o Inversor
    ax.annotate('', xy=(49.5, 39.5), xytext=(49.5, common_pole[1]),
                arrowprops=dict(arrowstyle='->', color=blade_color, lw=4, mutation_scale=18))

    # 5. INVERSOR DE FREQUÊNCIA (X: 27 a 72, Y: 29 a 39.5)
    b_inv = patches.FancyBboxPatch((27, 28.5), 45, 11, boxstyle='round,pad=0.4',
                                  facecolor='#022C22' if is_segue_active else '#451A03',
                                  edgecolor='#10B981' if is_segue_active else '#F59E0B', lw=2)
    ax.add_patch(b_inv)
    ax.text(49.5, 36, f'SETPOINT NO INVERSOR = {v_inversor:,} bph'.replace(',', '.'), 
            fontsize=12, fontweight='bold', color='#34D399' if is_segue_active else '#FBBF24', ha='center')
    rot_orig = 'Executando Caminho A (SEGUE Otimizado)' if is_segue_active else 'Executando Caminho B (CLP Convencional)'
    ax.text(49.5, 31.5, rot_orig, fontsize=8.5, color='#E5E7EB', ha='center')

    # 6. PAINEL LATERAL DIREITO: CÁLCULO DE BENEFÍCIO CONTRAFACTUAL (X: 75 a 97, Y: 28.5 a 88)
    b_gain_panel = patches.FancyBboxPatch((75, 28.5), 22, 59.5, boxstyle='round,pad=0.4',
                                         facecolor='#0B132B' if is_segue_active else '#111827',
                                         edgecolor='#10B981' if is_segue_active else '#475569', lw=2)
    ax.add_patch(b_gain_panel)
    ax.text(86, 85, 'AVALIAÇÃO DE GANHO', fontsize=9.5, fontweight='bold', color='#6EE7B7' if is_segue_active else '#9CA3AF', ha='center')
    ax.text(86, 81.5, 'Cálculo Contrafactual', fontsize=7.5, color='#94A3B8', ha='center')
    
    # Caixa de Fórmula
    f_box = patches.FancyBboxPatch((76.5, 68), 19, 10, boxstyle='round,pad=0.3',
                                  facecolor='#1E293B', edgecolor='#334155', lw=1)
    ax.add_patch(f_box)
    ax.text(86, 75.5, 'FÓRMULA DO BENEFÍCIO:', fontsize=7, color='#93C5FD', ha='center')
    ax.text(86, 71, '[CAMINHO A] − [CAMINHO B]', fontsize=8, fontweight='bold', color='#FDE047', ha='center')

    # Valores Comparados
    ax.text(77, 63, 'Inversor (A):', fontsize=8, color='#94A3B8')
    ax.text(95, 63, f'{v_inversor:,} bph'.replace(',', '.'), fontsize=8.5, fontweight='bold', 
            color='#34D399' if is_segue_active else '#FBBF24', ha='right')
    
    ax.text(77, 58, 'Shadow (B):', fontsize=8, color='#94A3B8')
    ax.text(95, 58, f'{v_shadow:,} bph'.replace(',', '.'), fontsize=8.5, fontweight='bold', color='#9CA3AF', ha='right')

    ax.plot([77, 95], [55, 55], color='#475569', lw=1)

    # Benefício Medido
    ax.text(86, 50.5, 'BENEFÍCIO INSTANTÂNEO', fontsize=8, fontweight='bold', color='#D1D5DB', ha='center')
    txt_g = f'+{ganho_instantaneo:,} bph'.replace(',', '.') if is_segue_active else '0 bph'
    ax.text(86, 44, txt_g, fontsize=14, fontweight='bold', 
            color='#34D399' if is_segue_active else '#9CA3AF', ha='center')
    
    pct_g = f'+{(ganho_instantaneo/v_shadow)*100:.1f}%' if is_segue_active else '0.0%'
    ax.text(86, 38.5, f'Acréscimo: {pct_g}', fontsize=8.5, fontweight='bold', 
            color='#FDE047' if is_segue_active else '#64748B', ha='center')

    ax.text(86, 32.5, 'Ganho por escolher A em vez de B' if is_segue_active else 'Rodando em regime base', 
            fontsize=7, color='#A7F3D0' if is_segue_active else '#94A3B8', ha='center')

    # 7. ESTEIRA DE ENVASE E GARRAFAS NA SAÍDA (X: 27 a 97, Y: 10.5 a 25.5)
    ax.text(62, 26, 'FLUXO FÍSICO DE GARRAFAS ENCHIDAS NA SAÍDA DA LINHA', 
            fontsize=9.5, fontweight='bold', color='#CBD5E1', ha='center')
    
    conveyor = patches.FancyBboxPatch((27, 11), 70, 13, boxstyle='round,pad=0.2', 
                                     facecolor='#1E293B', edgecolor='#475569', lw=1.5)
    ax.add_patch(conveyor)
    
    speed_factor = 1.7 if is_segue_active else 1.0
    n_bottles = 13
    for b in range(n_bottles):
        bx = ((frame * speed_factor * 1.3) + b * (68 / n_bottles)) % 68 + 28
        is_bonus = is_segue_active and (b % 4 == 0)
        
        b_color = '#10B981' if is_bonus else ('#38BDF8' if is_segue_active else '#EAB308')
        
        b_body = patches.Rectangle((bx - 1.1, 12.5), 2.2, 6.5, facecolor=b_color, edgecolor='#0F172A', lw=1)
        ax.add_patch(b_body)
        b_neck = patches.Rectangle((bx - 0.55, 19), 1.1, 3.2, facecolor=b_color, edgecolor='#0F172A', lw=0.8)
        ax.add_patch(b_neck)
        
        if is_bonus:
            ax.text(bx, 15.5, '+', fontsize=11, fontweight='bold', color='#FFFFFF', ha='center', va='center')

    # 8. RODAPÉ DE AUDITORIA CONSOLIDADA (X: 3 a 97, Y: 1.5 a 8)
    if is_segue_active:
        b_footer = patches.FancyBboxPatch((3, 1.5), 94, 6.5, boxstyle='round,pad=0.3', 
                                         facecolor='#064E3B', edgecolor='#34D399', lw=1.5)
        ax.add_patch(b_footer)
        ax.text(50, 5.5, 'RESULTADO REAL AUDITADO (Trava Entrada == 1 & SEGUE Habilitado == 1):', 
                fontsize=8.5, fontweight='bold', color='#A7F3D0', ha='center')
        ax.text(50, 2.8, '+707 garrafas/hora  |  +4.890 garrafas líquidas capturadas  |  +3,70% sobre o CLP Shadow', 
                fontsize=10, fontweight='bold', color='#FFFFFF', ha='center')
    else:
        b_footer = patches.FancyBboxPatch((3, 1.5), 94, 6.5, boxstyle='round,pad=0.3', 
                                         facecolor='#451A03', edgecolor='#F59E0B', lw=1.5)
        ax.add_patch(b_footer)
        ax.text(50, 5.5, 'MODO DE SEGURANÇA BASELINE (CLP TRADICIONAL):', 
                fontsize=8.5, fontweight='bold', color='#FDE68A', ha='center')
        ax.text(50, 2.8, 'Inversor em velocidade reduzida conservadora  |  Potencial de otimização SEGUE em modo sombra', 
                fontsize=9.5, fontweight='bold', color='#FFFFFF', ha='center')

def generate_test_frames():
    fig, ax = plt.subplots(figsize=(14, 8.5), dpi=100)
    fig.patch.set_facecolor('#0a0e17')
    ax.set_facecolor('#0a0e17')
    
    # Frame 20 (Modo CLP)
    draw_frame(ax, 20)
    fig.savefig('/home/antonio/Projetos/OtimizadorSegue/scratch/preview_modo_clp.png', bbox_inches='tight')
    
    # Frame 80 (Modo SEGUE)
    draw_frame(ax, 80)
    fig.savefig('/home/antonio/Projetos/OtimizadorSegue/scratch/preview_modo_segue.png', bbox_inches='tight')
    plt.close()
    print("Preview frames generated in scratch/!")

if __name__ == '__main__':
    generate_test_frames()
