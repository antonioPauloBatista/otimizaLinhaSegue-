import matplotlib.pyplot as plt
import matplotlib.animation as animation
import matplotlib.patches as patches
import numpy as np

fig, ax = plt.subplots(figsize=(14, 8.5), dpi=100)
fig.patch.set_facecolor('#0a0e17')
ax.set_facecolor('#0a0e17')

out_dir = '/home/antonio/Projetos/OtimizadorSegue/relatorio_trava1_segue1'
total_frames = 120

def draw_frame(frame):
    ax.clear()
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')
    
    # 0 a 45: Modo Shadow
    # 45 a 60: Transição destrava estrela e liga SEGUE
    # 60 a 110: Modo SEGUE Ativo com destaque explícito da DIFERENÇA (SEGUE - SHADOW)
    # 110 a 120: Retorno/Loop
    if frame < 45:
        t_prog = 0.0
    elif frame < 60:
        t_prog = (frame - 45) / 15.0
    elif frame < 110:
        t_prog = 1.0
    else:
        t_prog = 1.0 - (frame - 110) / 10.0
        
    v_shadow = 20000
    v_segue = 25000
    v_inversor = int(v_shadow + (v_segue - v_shadow) * t_prog)
    ganho_instantaneo = v_inversor - v_shadow
    
    # 1. TÍTULO PRINCIPAL
    ax.text(50, 96.5, 'GANHO EFETIVO: DIFERENÇA LÍQUIDA [SEGUE - SHADOW]', 
            fontsize=15, fontweight='bold', color='#FFFFFF', ha='center', va='center')
    
    # 2. STATUS BANNER
    if t_prog < 0.5:
        b_color = '#92400E'
        b_txt = 'MODO CONSERVADOR (SHADOW): Produzindo apenas 20.000 bph | Ganho adicional = 0 garrafas'
    else:
        b_txt = 'MODO SEGUE ATIVO COM ESTRELA DESTRAVADA! O ganho capturado é exatamente: SEGUE - SHADOW'
        b_color = '#065F46'
        
    banner = patches.FancyBboxPatch((4, 89), 92, 4.5, boxstyle='round,pad=0.3', facecolor=b_color, edgecolor='none')
    ax.add_patch(banner)
    ax.text(50, 91.2, b_txt, fontsize=10.5, fontweight='bold', color='#FFFFFF', ha='center', va='center')
    
    # 3. ESTRELA DE ENTRADA (CANTO SUPERIOR ESQUERDO)
    star_center = (14, 71)
    radius = 7.5
    circle = patches.Circle(star_center, radius, facecolor='#1E293B', edgecolor='#38BDF8', lw=2)
    ax.add_patch(circle)
    
    ang_offset = frame * (0.12 if t_prog > 0.5 else 0.05)
    for i in range(6):
        ang = ang_offset + i * (np.pi / 3)
        dx = radius * np.cos(ang)
        dy = radius * np.sin(ang)
        ax.plot([star_center[0], star_center[0] + dx], [star_center[1], star_center[1] + dy], color='#93C5FD', lw=1.8)
        ax.plot(star_center[0] + dx, star_center[1] + dy, marker='o', markersize=5, color='#38BDF8')
        
    ax.plot(star_center[0], star_center[1], marker='o', markersize=7, color='#FFFFFF')
    
    # Box da Trava da Estrela
    if t_prog > 0.5:
        box_trava = patches.FancyBboxPatch((4, 57), 20, 4.5, boxstyle='round,pad=0.2', facecolor='#064E3B', edgecolor='#34D399', lw=1.5)
        ax.add_patch(box_trava)
        ax.text(14, 59.2, 'ESTRELA DESTRAVADA\n(Trava Entrada = 1)', fontsize=8, fontweight='bold', color='#A7F3D0', ha='center')
    else:
        box_trava = patches.FancyBboxPatch((4, 57), 20, 4.5, boxstyle='round,pad=0.2', facecolor='#7F1D1D', edgecolor='#F87171', lw=1.5)
        ax.add_patch(box_trava)
        ax.text(14, 59.2, 'ESTRELA RESTRITA\n(Trava Entrada = 0)', fontsize=8, fontweight='bold', color='#FECACA', ha='center')

    # 4. OS DOIS MODELOS: SEGUE e SHADOW
    # SEGUE
    b_segue = patches.FancyBboxPatch((28, 59), 20, 25, boxstyle='round,pad=0.4', 
                                     facecolor='#1E3A8A' if t_prog > 0.5 else '#1E293B', 
                                     edgecolor='#3B82F6' if t_prog > 0.5 else '#475569', lw=2)
    ax.add_patch(b_segue)
    ax.text(38, 80, 'SEGUE (APC)', fontsize=11, fontweight='bold', color='#60A5FA', ha='center')
    ax.text(38, 76, 'Oportunidade', fontsize=8.5, color='#CBD5E1', ha='center')
    ax.text(38, 68, f'{v_segue:,} bph'.replace(',', '.'), fontsize=13, fontweight='bold', color='#38BDF8', ha='center')
    ax.text(38, 62, '(Setpoing Otimizado)', fontsize=7.5, color='#94A3B8', ha='center')
    
    # SINAL DE SUBTRAÇÃO (-)
    ax.text(50.5, 71, '−', fontsize=26, fontweight='bold', color='#F59E0B', ha='center', va='center')
    
    # SHADOW
    b_shadow = patches.FancyBboxPatch((53, 59), 20, 25, boxstyle='round,pad=0.4', 
                                      facecolor='#1E293B' if t_prog > 0.5 else '#78350F', 
                                      edgecolor='#475569' if t_prog > 0.5 else '#F59E0B', lw=2)
    ax.add_patch(b_shadow)
    ax.text(63, 80, 'CLP / SHADOW', fontsize=11, fontweight='bold', color='#FBBF24', ha='center')
    ax.text(63, 76, 'Linha Base', fontsize=8.5, color='#CBD5E1', ha='center')
    ax.text(63, 68, f'{v_shadow:,} bph'.replace(',', '.'), fontsize=13, fontweight='bold', color='#FBBF24', ha='center')
    ax.text(63, 62, '(Velocidade a Menos)', fontsize=7.5, color='#94A3B8', ha='center')
    
    # SINAL DE IGUAL (=)
    ax.text(75.5, 71, '=', fontsize=26, fontweight='bold', color='#10B981', ha='center', va='center')
    
    # CAIXA DESTAQUE DO GANHO LÍQUIDO: SEGUE - SHADOW
    b_diff = patches.FancyBboxPatch((78, 59), 19, 25, boxstyle='round,pad=0.4', 
                                    facecolor='#064E3B' if t_prog > 0.5 else '#1E293B', 
                                    edgecolor='#34D399' if t_prog > 0.5 else '#64748B', lw=2.5)
    ax.add_patch(b_diff)
    ax.text(87.5, 80, 'GANHO LÍQUIDO', fontsize=10.5, fontweight='bold', color='#A7F3D0' if t_prog > 0.5 else '#94A3B8', ha='center')
    ax.text(87.5, 76, '[SEGUE − SHADOW]', fontsize=8, fontweight='bold', color='#FDE047' if t_prog > 0.5 else '#64748B', ha='center')
    
    txt_ganho = f'+{ganho_instantaneo:,} bph'.replace(',', '.') if t_prog > 0.5 else '0 bph'
    ax.text(87.5, 68, txt_ganho, fontsize=13, fontweight='bold', color='#34D399' if t_prog > 0.5 else '#94A3B8', ha='center')
    pct_ganho = f'+{(ganho_instantaneo/v_shadow)*100:.1f}%' if t_prog > 0.5 else '0.0%'
    ax.text(87.5, 62, f'({pct_ganho} de Vazão)', fontsize=8, fontweight='bold', color='#FDE047' if t_prog > 0.5 else '#64748B', ha='center')

    # 5. LINHA DE INJEÇÃO NO INVERSOR
    if t_prog > 0.5:
        # Seta do SEGUE descendo para o inversor
        ax.annotate('', xy=(38, 43), xytext=(38, 58), arrowprops=dict(arrowstyle='->', color='#34D399', lw=4, mutation_scale=20))
        ax.text(38, 50, 'ESCRITA DIRETA NO INVERSOR', fontsize=8.5, fontweight='bold', color='#34D399', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#064E3B', edgecolor='#34D399'))
        # Shadow Cortado
        ax.text(63, 50, '✂ CORTADO', fontsize=10, fontweight='bold', color='#EF4444', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#450A0A', edgecolor='#EF4444'))
    else:
        # Seta do SHADOW descendo para o inversor
        ax.annotate('', xy=(63, 43), xytext=(63, 58), arrowprops=dict(arrowstyle='->', color='#F59E0B', lw=4, mutation_scale=20))
        ax.text(63, 50, 'ESCRITA DA VELOCIDADE A MENOS', fontsize=8.5, fontweight='bold', color='#F59E0B', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', facecolor='#78350F', edgecolor='#F59E0B'))
        # SEGUE Cortado
        ax.text(38, 50, '✖ SEM ESCRITA', fontsize=9.5, fontweight='bold', color='#EF4444', ha='center')

    # 6. INVERSOR DE FREQUÊNCIA
    box_inv = patches.FancyBboxPatch((22, 31), 58, 11, boxstyle='round,pad=0.4', 
                                    facecolor='#022C22' if t_prog > 0.5 else '#451A03', 
                                    edgecolor='#34D399' if t_prog > 0.5 else '#F59E0B', lw=2)
    ax.add_patch(box_inv)
    ax.text(51, 38.5, f'SETPOINT NO INVERSOR = {v_inversor:,} bph'.replace(',', '.'), 
            fontsize=13, fontweight='bold', color='#34D399' if t_prog > 0.5 else '#FBBF24', ha='center')
    ax.text(51, 33.5, 'Velocidade com que os motores e carrosséis da linha estão efetivamente girando', 
            fontsize=8, color='#D1D5DB', ha='center')

    # 7. ESTEIRA DE ENVASE E GARRAFAS FÍSICAS
    ax.text(50, 24, 'FLUXO FÍSICO DE GARRAFAS ENCHIDAS NA SAÍDA DA LINHA', fontsize=10, fontweight='bold', color='#94A3B8', ha='center')
    
    conveyor = patches.FancyBboxPatch((4, 9), 92, 12, boxstyle='round,pad=0.2', facecolor='#1E293B', edgecolor='#475569', lw=1.5)
    ax.add_patch(conveyor)
    
    # Garrafas base (Shadow) = 20k bph
    # Garrafas ganho (SEGUE - Shadow) = destacadas em verde brilhante com selo "+"
    speed_factor = 1.7 if t_prog > 0.5 else 1.0
    n_bottles = 16
    for b in range(n_bottles):
        bx = ((frame * speed_factor * 1.4) + b * (90 / n_bottles)) % 90 + 5
        # 1 a cada 5 garrafas no modo SEGUE representa o ganho puro (25k vs 20k = 1/5 adicional!)
        is_bonus = (t_prog > 0.5) and (b % 5 == 0)
        
        b_color = '#10B981' if is_bonus else ('#38BDF8' if t_prog > 0.5 else '#EAB308')
        
        # Corpo
        b_body = patches.Rectangle((bx - 1.1, 10.5), 2.2, 5.5, facecolor=b_color, edgecolor='#0F172A', lw=1)
        ax.add_patch(b_body)
        # Gargalo
        b_neck = patches.Rectangle((bx - 0.55, 16), 1.1, 2.5, facecolor=b_color, edgecolor='#0F172A', lw=0.8)
        ax.add_patch(b_neck)
        
        if is_bonus:
            ax.text(bx, 13, '+', fontsize=10, fontweight='bold', color='#FFFFFF', ha='center', va='center')

    # 8. PLACAR INFERIOR
    if t_prog > 0.5:
        box_resumo = patches.FancyBboxPatch((8, 1.5), 84, 5.5, boxstyle='round,pad=0.3', facecolor='#064E3B', edgecolor='#34D399', lw=1.5)
        ax.add_patch(box_resumo)
        ax.text(50, 4.2, '★ PRODUZINDO O GANHO [SEGUE − SHADOW]: +707 garrafas/hora a mais  |  +4.890 garrafas adicionais no período', 
                fontsize=9.5, fontweight='bold', color='#6EE7B7', ha='center')
    else:
        box_resumo = patches.FancyBboxPatch((8, 1.5), 84, 5.5, boxstyle='round,pad=0.3', facecolor='#451A03', edgecolor='#F59E0B', lw=1.5)
        ax.add_patch(box_resumo)
        ax.text(50, 4.2, 'Linha restrita pelo Shadow: Perdendo o potencial de +707 garrafas/hora do SEGUE', 
                fontsize=9.5, fontweight='bold', color='#FDE68A', ha='center')

anim = animation.FuncAnimation(fig, draw_frame, frames=total_frames, interval=80)
gif_file = f'{out_dir}/animacao_diferenca_segue_shadow.gif'
anim.save(gif_file, writer='pillow', fps=12)
plt.close()
print(f'Animação com cálculo de diferença gerada: {gif_file}')
