# ==========================================================
# CÓDIGO DA FUNÇÃO DO CONTROLADOR DE FLUXO DA MÁQUINA
# (Gerado Automaticamente pelo otimizador_velocidade.py)
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


def calcular_velocidade(b1, b2, b3, b4, velocidade_nominal=70000, min_modulacao=0.8, max_modulacao=1.0):
    """
    Recebe o nivel atual dos 4 pulmoes (%) e retorna o setpoint em CPH.
    Parametros otimizados via CMA-ES em 2026-06-15.
    """
    # --- Gatilhos de modulacao otimizados pelo algoritmo ---
    b2_lim = 15.00   # B2 abaixo disto -> iniciar reducao
    b3_lim = 85.00   # B3 acima disto  -> iniciar reducao

    # --- Travas Operacionais (vindas do config_colunas.json) ---
    vel_maxima   = velocidade_nominal * max_modulacao   # Teto absoluto
    vel_reduzida = velocidade_nominal * min_modulacao   # Piso absoluto

    # --- Logica Fuzzy: Avaliacao dos Pulmoes ---
    b2_baixo  = rampa_trapezoidal(b2, -1, 0, b2_lim - 15, b2_lim)
    b2_normal = rampa_trapezoidal(b2, b2_lim - 15, b2_lim, 100, 101)
    b3_normal = rampa_trapezoidal(b3, -1, 0, b3_lim, b3_lim + 15)
    b3_alto   = rampa_trapezoidal(b3, b3_lim, b3_lim + 15, 100, 101)

    # --- Inferencia: pesos e calculo da velocidade ---
    w1 = b2_baixo                       # Entrada vazia -> reduz
    w2 = b3_alto                        # Saida cheia   -> reduz
    w3 = min(b2_normal, b3_normal)      # Ambos OK      -> teto

    num = (w1 * vel_reduzida) + (w2 * vel_reduzida) + (w3 * vel_maxima)
    den = w1 + w2 + w3

    v_base = vel_maxima if den == 0 else num / den

    # --- Garantia do Piso: nunca retorna 0 CPH ---
    return int(max(v_base, vel_reduzida))
