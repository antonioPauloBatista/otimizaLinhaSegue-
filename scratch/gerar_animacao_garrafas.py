import matplotlib.pyplot as plt
import matplotlib.animation as animation
import matplotlib.patches as patches
import numpy as np

fig, ax = plt.subplots(figsize=(13, 8), dpi=100)
fig.patch.set_facecolor('#0b0f19')
ax.set_facecolor('#0b0f19')

out_dir = '/home/antonio/Projetos/OtimizadorSegue/relatorio_trava1_segue1'
total_frames = 120

def draw_frame(frame):
    ax.clear()
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')
    
    # Fases:
    # 0 a 48: Cenário B (Shadow conservador, trava de entrada bloqueando/fechada, sem SEGUE)
    # 48 a 60: Transição - Estrela destrava, SEGUE assume o inversor
    # 60 a 110: Cenário A (SEGUE ativo, estrela destravada, fluxo acelerado de garrafas, ganho)
    # 110 a 120: Transição suave
    if frame < 48:
        t_prog = 0.0
    elif frame < 60:
        t_prog = (frame - 48) / 12.0
    elif frame < 110:
        t_prog = 1.0
    else:
        t_prog = 1.0 - (frame - 110) / 10.0
        
    vel_atual = int(20000 + (25000 - 20000) * t_prog)
    
    # 1. TÍTULO E CABEÇALHO
    ax.text(50, 96, 'DINÂMICA DE CONTROLE: ESTRELA DE ENTRADA & GANHO DE GARRAFAS', 
            fontsize=14, fontweight='bold', color='#FFFFFF', ha='center', va='center')
    
    # 2. STATUS BANNER
    if t_prog < 0.5:
        b_color = '#B45309'
        b_text = 'CENÁRIO CONSERVADOR: Estrela com restrição operacional | Velocidade Shadow: 20.000 bph'
    else:
        b_color = '#047857'
        b_text = 'ESTRELA DE ENTRADA DESTRAVADA! SEGUE no comando do inversor: 25.000 bph (+707 garrafas/hora)'
        
    banner = patches.FancyBboxPatch((4, 88), 92, 4.5, boxstyle='round,pad=0.4', facecolor=b_color, edgecolor='none')
    ax.add_patch(banner)
    ax.text(50, 90.2, b_text, fontsize=10.5, fontweight='bold', color='#FFFFFF', ha='center', va='center')
    
    # 3. ESTRELA DE ENTRADA (MECÂNICA E SENSOR DE TRAVA)
    # Desenho da Estrela / Carrossel de Entrada
    ax.text(22, 82, 'ESTRELA DE ENTRADA (INLET STARWHEEL)', fontsize=11, fontweight='bold', color='#60A5FA', ha='center')
    
    # Desenho circular da Estrela
    star_center = (22, 63)
    radius = 9
    circle = patches.Circle(star_center, radius, facecolor='#1E293B', edgecolor='#3B82F6', lw=2)
    ax.add_patch(circle)
    
    # Dentes da estrela rotacionando
    angle_offset = frame * (0.12 if t_prog > 0.5 else 0.06)
    n_teeth = 6
    for i in range(n_teeth):
        ang = angle_offset + i * (2 * np.pi / n_teeth)
        dx = radius * np.cos(ang)
        dy = radius * np.sin(ang)
        ax.plot([star_center[0], star_center[0] + dx], [star_center[1], star_center[1] + dy], color='#93C5FD', lw=2)
        # Bolsão da garrafa no dente
        ax.plot(star_center[0] + dx, star_center[1] + dy, marker='o', markersize=6, color='#60A5FA')
        
    ax.plot(star_center[0], star_center[1], marker='o', markersize=8, color='#FFFFFF')
    
    # Indicador de Status da Trava da Estrela
    if t_prog < 0.5:
        trava_box = patches.FancyBboxPatch((8, 48), 28, 4.5, boxstyle='round,pad=0.3', facecolor='#7F1D1D', edgecolor='#EF4444', lw=1.5)
        ax.add_patch(trava_box)
        ax.text(22, 50.2, '🔒 TRAVA ENTRADA: 0 (RESTRITA)', fontsize=9, fontweight='bold', color='#FCA5A5', ha='center')
    else:
        trava_box = patches.FancyBboxPatch((8, 48), 28, 4.5, boxstyle='round,pad=0.3', facecolor='#064E3B', edgecolor='#10B981', lw=1.5)
        ax.add_patch(trava_box)
        ax.text(22, 50.2, '🔓 ESTRELA DESTRAVADA (TRAVA = 1)', fontsize=9, fontweight='bold', color='#6EE7B7', ha='center')
        
    # 4. CHAVEAMENTO DE CONTROLE (CENTRO / DIREITA)
    # Caixa SEGUE
    segue_bg = '#1E3A8A' if t_prog > 0.5 else '#1E293B'
    segue_border = '#3B82F6' if t_prog > 0.5 else '#475569'
    b_segue = patches.FancyBboxPatch((42, 57), 24, 23, boxstyle='round,pad=0.5', facecolor=segue_bg, edgecolor=segue_border, lw=2)
    ax.add_patch(b_segue)
    ax.text(54, 75.5, 'SEGUE (APC)', fontsize=11, fontweight='bold', color='#93C5FD', ha='center')
    ax.text(54, 71.5, 'Setpoint Otimizado', fontsize=8.5, color='#CBD5E1', ha='center')
    ax.text(54, 64, '25.000 bph', fontsize=13, fontweight='bold', color='#38BDF8', ha='center')
    
    # Caixa SHADOW
    shadow_bg = '#1E293B' if t_prog > 0.5 else '#78350F'
    shadow_border = '#475569' if t_prog > 0.5 else '#F59E0B'
    b_shadow = patches.FancyBboxPatch((70, 57), 25, 23, boxstyle='round,pad=0.5', facecolor=shadow_bg, edgecolor=shadow_border, lw=2)
    ax.add_patch(b_shadow)
    ax.text(82.5, 75.5, 'CLP / SHADOW', fontsize=11, fontweight='bold', color='#FDE68A', ha='center')
    ax.text(82.5, 71.5, 'Velocidade a Menos', fontsize=8.5, color='#CBD5E1', ha='center')
    ax.text(82.5, 64, '20.000 bph', fontsize=13, fontweight='bold', color='#FBBF24', ha='center')
    
    # Linha e status do chaveamento
    if t_prog > 0.5:
        # SEGUE conectado ao inversor
        ax.plot([54, 54], [57, 43], color='#10B981', lw=3.5)
        ax.annotate('', xy=(54, 43), xytext=(54, 48), arrowprops=dict(arrowstyle='->', color='#10B981', lw=3.5))
        # Shadow Cortado
        ax.text(82.5, 49, '✂ CORTADO', fontsize=10, fontweight='bold', color='#EF4444', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#450A0A', edgecolor='#EF4444'))
    else:
        # Shadow conectado ao inversor
        ax.plot([82.5, 82.5], [57, 43], color='#F59E0B', lw=3.5)
        ax.annotate('', xy=(82.5, 43), xytext=(82.5, 48), arrowprops=dict(arrowstyle='->', color='#F59E0B', lw=3.5))
        # SEGUE sem escrita
        ax.text(54, 49, '✖ SEM ESCRITA', fontsize=9.5, fontweight='bold', color='#EF4444', ha='center')

    # 5. INVERSOR E VELOCIDADE EXECUTADA
    inv_box = patches.FancyBboxPatch((46, 29), 48, 12, boxstyle='round,pad=0.5', 
                                    facecolor='#064E3B' if t_prog > 0.5 else '#78350F', 
                                    edgecolor='#10B981' if t_prog > 0.5 else '#F59E0B', lw=2)
    ax.add_patch(inv_box)
    ax.text(70, 36.5, f'INVERSOR: {vel_atual:,} bph'.replace(',', '.'), fontsize=13, fontweight='bold', 
            color='#34D399' if t_prog > 0.5 else '#FBBF24', ha='center')
    ax.text(70, 31.5, 'Velocidade Real Executada na Linha', fontsize=8.5, color='#E2E8F0', ha='center')

    # 6. ESTEIRA DE ENVASE COM AS GARRAFAS EM MOVIMENTO
    ax.text(50, 23.5, 'FLUXO REAL DE GARRAFAS ENCHIDAS NA ESTEIRA', fontsize=11, fontweight='bold', color='#94A3B8', ha='center')
    
    # Desenho da Esteira (Conveyor)
    conveyor = patches.FancyBboxPatch((4, 8), 92, 12, boxstyle='round,pad=0.2', facecolor='#1E293B', edgecolor='#475569', lw=1.5)
    ax.add_patch(conveyor)
    
    # Garrafas animadas passando na esteira
    speed_factor = 1.6 if t_prog > 0.5 else 1.0
    n_bottles = 14
    for b in range(n_bottles):
        bx = ((frame * speed_factor * 1.5) + b * (90 / n_bottles)) % 90 + 5
        # Corpo da garrafa
        bottle_body = patches.Rectangle((bx - 1.2, 10), 2.4, 5.5, facecolor='#22C55E' if t_prog > 0.5 else '#EAB308', edgecolor='#0F172A', lw=1)
        ax.add_patch(bottle_body)
        # Gargalo da garrafa
        bottle_neck = patches.Rectangle((bx - 0.6, 15.5), 1.2, 2.5, facecolor='#22C55E' if t_prog > 0.5 else '#EAB308', edgecolor='#0F172A', lw=0.8)
        ax.add_patch(bottle_neck)
        
    # 7. PLACAR DE GANHO DE GARRAFAS
    if t_prog > 0.5:
        placar = patches.FancyBboxPatch((15, 1), 70, 5.5, boxstyle='round,pad=0.3', facecolor='#065F46', edgecolor='#34D399', lw=1.5)
        ax.add_patch(placar)
        ax.text(50, 3.8, 'GANHO DE GARRAFAS: +707 garrafas/hora  |  +4.890 garrafas líquidas no turno (+3,70%)', 
                fontsize=9.5, fontweight='bold', color='#A7F3D0', ha='center')
    else:
        placar = patches.FancyBboxPatch((15, 1), 70, 5.5, boxstyle='round,pad=0.3', facecolor='#451A03', edgecolor='#F59E0B', lw=1.5)
        ax.add_patch(placar)
        ax.text(50, 3.8, 'Operando no limite Shadow: -707 garrafas/hora a menos produzidas', 
                fontsize=9.5, fontweight='bold', color='#FDE68A', ha='center')

anim = animation.FuncAnimation(fig, draw_frame, frames=total_frames, interval=80)
gif_file = f'{out_dir}/animacao_estrela_garrafas_ganho.gif'
anim.save(gif_file, writer='pillow', fps=12)
plt.close()
print(f'Animação gerada: {gif_file}')
