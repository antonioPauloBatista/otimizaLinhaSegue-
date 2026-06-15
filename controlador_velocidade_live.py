import sys
import json
import os

def rampa_trapezoidal(x, a, b, c, d):
    """Calcula o fator de transicao [0, 1]."""
    if x <= a or x >= d: return 0.0
    if a < x <= b: return (x - a) / (b - a) if b > a else 1.0
    if b < x <= c: return 1.0
    if c < x < d: return (d - x) / (d - c) if d > c else 1.0
    return 0.0

class ControladorVelocidadeEnchedora:
    def __init__(self, velocidade_nominal=63360, min_modulacao=0.80, max_modulacao=1.00):
        """
        Inicia o controlador lendo o 'modelo' de parâmetros salvo pelo Otimizador.
        Permite ao operador forçar um teto e um piso para a velocidade de modulação.
        """
        self.velocidade_nominal = velocidade_nominal
        self.min_modulacao = min_modulacao
        self.max_modulacao = max_modulacao
        
        # Parâmetros padrão (fallback)
        self.b1_lim = 19.6
        self.b2_lim = 15.0
        self.b3_lim = 79.0
        self.b4_lim = 90.0
        self.fator_reducao_otimizado = 0.90
        
        # Carrega o "modelo" gerado pelo otimizador
        ARQUIVO_MODELO = "parametros_controle.json"
        if os.path.exists(ARQUIVO_MODELO):
            try:
                with open(ARQUIVO_MODELO, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.b1_lim = cfg.get("b1_lim", self.b1_lim)
                    self.b2_lim = cfg.get("b2_lim", self.b2_lim)
                    self.b3_lim = cfg.get("b3_lim", self.b3_lim)
                    self.b4_lim = cfg.get("b4_lim", self.b4_lim)
                    self.fator_reducao_otimizado = cfg.get("fator_reducao", self.fator_reducao_otimizado)
            except Exception:
                pass
                
        # Tenta carregar a velocidade máxima do config global se existir
        if os.path.exists("config_colunas.json"):
            try:
                with open("config_colunas.json", "r", encoding="utf-8") as f:
                    cfg_colunas = json.load(f)
                    self.velocidade_nominal = float(cfg_colunas.get("Velocidade_Nominal_ECH", self.velocidade_nominal))
            except Exception:
                pass
            
        # Travas Operacionais Inegociáveis (Direto da inicialização ou JSON)
        self.vel_maxima = self.velocidade_nominal * self.max_modulacao
        self.vel_reduzida = self.velocidade_nominal * self.min_modulacao
        
    def func_baixo_b1(self, x): return rampa_trapezoidal(x, -1, 0, self.b1_lim - 10, self.b1_lim)
    def func_baixo_b2(self, x): return rampa_trapezoidal(x, -1, 0, self.b2_lim - 15, self.b2_lim)
    def func_normal_b2(self, x): return rampa_trapezoidal(x, self.b2_lim - 15, self.b2_lim, 100, 101)
    
    def func_normal_b3(self, x): return rampa_trapezoidal(x, -1, 0, self.b3_lim, self.b3_lim + 15)
    def func_alto_b3(self, x): return rampa_trapezoidal(x, self.b3_lim, self.b3_lim + 15, 100, 101)
    def func_alto_b4(self, x): return rampa_trapezoidal(x, self.b4_lim, self.b4_lim + 10, 100, 101)

    def calcular_velocidade(self, b1, b2, b3, b4):
        """
        Recebe o nível atual dos 4 pulmões e devolve a velocidade ideal da máquina.
        """
        # 1. Rampas Base B2 e B3
        w1 = self.func_baixo_b2(b2)
        w2 = self.func_alto_b3(b3)
        w3 = min(self.func_normal_b2(b2), self.func_normal_b3(b3))
        
        num_base = (w1 * self.vel_reduzida) + (w2 * self.vel_reduzida) + (w3 * self.vel_maxima)
        den_base = w1 + w2 + w3
        
        if den_base == 0:
            v_base = self.vel_maxima
        else:
            v_base = num_base / den_base
            
        # O Controlador NÃO PODE comandar parada (0 CPH). O setpoint mínimo absoluto é a velocidade reduzida.
        return int(max(v_base, self.vel_reduzida))

if __name__ == "__main__":
    print("="*60)
    print("      SIMULADOR DE VELOCIDADE DA MÁQUINA - TESTE LIVE")
    print("="*60)
    print("Injetando parâmetros otimizados de controle...\n")
    
    controlador = ControladorVelocidadeEnchedora()
    
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
