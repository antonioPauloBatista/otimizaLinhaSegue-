# ==========================================================
# CÓDIGO DA FUNÇÃO DO CONTROLADOR DE FLUXO DA MÁQUINA V3 (FEEDFORWARD)
# (Gerado Automaticamente pelo otimizador_velocidade_v3.py)
#
# REGRAS INEGOCIÁVEIS:
#   - Piso  : min_modulacao  (ex: 0.80 = 56000 CPH)
#   - Teto  : max_modulacao  (ex: 1.00 = 70000 CPH)
#   - NUNCA retorna 0 CPH (parada é responsabilidade do CLP físico)
# ==========================================================

def rampa_trapezoidal(x, a, b, c, d):
    """Calcula o fator de pertinencia fuzzy [0, 1]."""
    if x <= a or x >= d: return 0.0
    if a < x <= b: return (x - a) / (b - a) if b > a else 1.0
    if b < x <= c: return 1.0
    if c < x < d: return (d - x) / (d - c) if d > c else 1.0
    return 0.0

def calcular_velocidade(b1, b2, b3, b4, velocidade_nominal=70000, min_modulacao=0.766, max_modulacao=1.0):
    """
    Recebe o nivel atual dos 4 pulmoes (%) e retorna o setpoint em CPH.
    Parametros otimizados via CMA-ES em 2026-06-17.
    """
    # --- Gatilhos de modulacao otimizados pelo algoritmo ---
    b2_lim = 27.92   # B2 abaixo disto -> iniciar reducao
    b3_lim = 71.50   # B3 acima disto  -> iniciar reducao
    b1_lim = 20.61   # B1 aproximando do corte -> reducao feedforward
    b4_lim = 86.88   # B4 aproximando do corte -> reducao feedforward

    # --- Travas Operacionais ---
    vel_maxima   = velocidade_nominal * max_modulacao   # Teto absoluto
    vel_reduzida = velocidade_nominal * min_modulacao   # Piso otimizado

    # --- Logica Fuzzy: Avaliacao dos Pulmoes Principais ---
    b2_baixo  = rampa_trapezoidal(b2, -1, 0, b2_lim - 15.00, b2_lim)
    b2_normal = rampa_trapezoidal(b2, b2_lim - 15.00, b2_lim, 100, 101)
    b3_normal = rampa_trapezoidal(b3, -1, 0, b3_lim, b3_lim + 15.00)
    b3_alto   = rampa_trapezoidal(b3, b3_lim, b3_lim + 15.00, 100, 101)
    
    # --- Feedforward: Alerta antecipado dos Pulmoes Extremos ---
    b1_tendencia = rampa_trapezoidal(b1, -1, 0, b1_lim, b1_lim + 10.26)
    b4_tendencia = rampa_trapezoidal(b4, b4_lim - 10.00, b4_lim, 100, 101)

    # --- Inferencia: pesos e calculo da velocidade ---
    w1 = b2_baixo                       # Entrada vazia -> reduz
    w2 = b3_alto                        # Saida cheia   -> reduz
    w4 = b1_tendencia                   # Falta Extrema detectada longe -> reduz antecipadamente
    w5 = b4_tendencia                   # Gargalo Extremo detectado longe -> reduz antecipadamente
    
    w3 = min(b2_normal, b3_normal)      # Ambos OK -> teto

    num = (w1 * vel_reduzida) + (w2 * vel_reduzida) + (w4 * vel_reduzida) + (w5 * vel_reduzida) + (w3 * vel_maxima)
    den = w1 + w2 + w3 + w4 + w5

    v_base = vel_maxima if den == 0 else num / den

    # --- Garantia do Piso: nunca retorna 0 CPH ---
    return int(max(v_base, vel_reduzida))
