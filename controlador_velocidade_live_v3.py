import sys
import os

def rampa_trapezoidal(x, a, b, c, d):
    """Calcula o fator de transicao [0, 1]."""
    if x <= a or x >= d: return 0.0
    if a < x <= b: return (x - a) / (b - a) if b > a else 1.0
    if b < x <= c: return 1.0
    if c < x < d: return (d - x) / (d - c) if d > c else 1.0
    return 0.0

class ControladorVelocidadeEnchedoraV3:
    def __init__(self, velocidade_nominal=70000, min_modulacao=0.500, max_modulacao=1.0):
        self.velocidade_nominal = velocidade_nominal
        self.min_modulacao = min_modulacao
        self.max_modulacao = max_modulacao
        
        # Parâmetros hardcoded (raw) otimizados
        self.b1_lim = 30.00
        self.b2_lim = 18.68
        self.b3_lim = 79.39
        self.b4_lim = 86.10
        self.rampa_b2 = 39.94
        self.rampa_b3 = 40.00
        self.antecip_b1 = 35.00
        self.antecip_b4 = 35.00
        self.fator_reducao_otimizado = 0.500
            
        self.vel_maxima = self.velocidade_nominal * self.max_modulacao
        self.vel_reduzida = self.velocidade_nominal * self.fator_reducao_otimizado

    def calcular_velocidade(self, b1, b2, b3, b4):
        b2_baixo  = rampa_trapezoidal(b2, -1, 0, self.b2_lim - self.rampa_b2, self.b2_lim)
        b2_normal = rampa_trapezoidal(b2, self.b2_lim - self.rampa_b2, self.b2_lim, 100, 101)
        b3_normal = rampa_trapezoidal(b3, -1, 0, self.b3_lim, self.b3_lim + self.rampa_b3)
        b3_alto   = rampa_trapezoidal(b3, self.b3_lim, self.b3_lim + self.rampa_b3, 100, 101)
        
        b1_tendencia = rampa_trapezoidal(b1, -1, 0, self.b1_lim, self.b1_lim + self.antecip_b1)
        b4_tendencia = rampa_trapezoidal(b4, self.b4_lim - self.antecip_b4, self.b4_lim, 100, 101)

        w1 = b2_baixo
        w2 = b3_alto
        w4 = b1_tendencia
        w5 = b4_tendencia
        w3 = min(b2_normal, b3_normal)

        num = (w1 * self.vel_reduzida) + (w2 * self.vel_reduzida) + (w4 * self.vel_reduzida) + (w5 * self.vel_reduzida) + (w3 * self.vel_maxima)
        den = w1 + w2 + w3 + w4 + w5

        v_base = self.vel_maxima if den == 0 else num / den
        return int(max(v_base, self.vel_reduzida))

if __name__ == "__main__":
    print("="*60)
    print("   SIMULADOR DE VELOCIDADE DA MÁQUINA - TESTE LIVE (V3)")
    print("="*60)
    print("Injetando parâmetros otimizados de controle V3 (Feedforward)...\n")
    
    controlador = ControladorVelocidadeEnchedoraV3()
    
    while True:
        try:
            print("Digite os níveis dos buffers em % (ou pressione Ctrl+C para sair):")
            b1 = float(input("  B1 (DPL-UIP) - Extremo Entrada : "))
            b2 = float(input("  B2 (UIP-ECH) - Entrada Interna : "))
            b3 = float(input("  B3 (ECH-PZ)  - Saída Interna   : "))
            b4 = float(input("  B4 (PZ-EPC)  - Extremo Saída   : "))
            
            vel = controlador.calcular_velocidade(b1, b2, b3, b4)
            
            print("-" * 60)
            if vel == 0:
                print(f"➔ VELOCIDADE SUGERIDA OTIMIZADA: {vel} CPH 🚨 PARADA DE SEGURANÇA 🚨")
            elif vel < controlador.velocidade_nominal:
                print(f"➔ VELOCIDADE SUGERIDA OTIMIZADA: {vel} CPH ⚠️ MODULAÇÃO ATIVA")
            else:
                print(f"➔ VELOCIDADE SUGERIDA OTIMIZADA: {vel} CPH ✅ MÁQUINA FULL")
            print("-" * 60)
            print("")
            
        except KeyboardInterrupt:
            print("\nSaindo do simulador live...")
            break
        except ValueError:
            print("\n⚠️ Entrada inválida. Por favor, digite números (ex: 45.5)\n")
