# Explicação de Conceitos: Otimizador de Velocidade da Enchedora

Este documento detalha o funcionamento físico da linha de envase, o papel de cada buffer, a velocidade nominal e como o simulador do Python modela a realidade da fábrica.

---

## 1. Buffers (Pulmões) de Controle

A linha de envase usa 4 buffers (sensores de acúmulo em %) dispostos em duas cadeias (entrada e saída) em relação à Enchedora (ECH), que é o gargalo e coração do processo.

```
       [ CADEIA DE ENTRADA ]                    [ CADEIA DE SAÍDA ]
DPL ──> [ B1: DPL-UIP ] ──> UIP ──> [ B2: UIP-ECH ] ──> ECH ──> [ B3: ECH-PZ ] ──> PZ ──> [ B4: PZ-EPC ] ──> EPC
```

### A. Cadeia de Entrada (Prevenção de Falta de Garrafas)
*   **B2 (Pulmão Interno UIP-ECH):** 
    *   *Função:* Buffer crítico imediatamente anterior à enchedora.
    *   *Parada:* Se o nível cair a zero, a enchedora para por **falta de produto**.
    *   *Otimização:* Se o nível cair abaixo do gatilho crítico de falta, a enchedora reduz drasticamente a velocidade para esticar o tempo de esvaziamento, esperando as garrafas chegarem.
*   **B1 (Pulmão Extremo DPL-UIP):**
    *   *Função:* Buffer preventivo inicial (entre Despaletizadora e Inspetora).
    *   *Otimização:* Se o nível estiver baixo **e** a Despaletizadora (DPL) estiver lenta, a enchedora reduz suavemente a velocidade para evitar que o buffer crítico B2 esvazie em seguida.

### B. Cadeia de Saída (Prevenção de Acúmulo/Engarrafamento)
*   **B3 (Pulmão Interno ECH-PZ):**
    *   *Função:* Buffer crítico imediatamente posterior à enchedora.
    *   *Parada:* Se o nível atingir 100%, a enchedora para por **acúmulo na saída** (travamento físico).
    *   *Otimização:* Se o nível subir acima do gatilho crítico de acúmulo, a enchedora reduz drasticamente a velocidade para evitar encher as esteiras restantes.
*   **B4 (Pulmão Extremo PZ-EPC):**
    *   *Função:* Buffer preventivo final (saída do Pasteurizador).
    *   *Otimização:* Se o nível subir demais **e** as máquinas finais (Encaxotadora/Rotuladora) estiverem lentas, a enchedora reduz suavemente a velocidade de forma antecipada.

---

## 2. A Importância da Histerese (Banda Morta)

A histerese é o que impede a enchedora de oscilar e "tremer" a velocidade a cada segundo. Ela é composta por dois limites por buffer:
1.  **Gatilho para REDUZIR (Start):** Nível onde a enchedora diminui a marcha (ex: B2 < 20% ou B3 > 75%).
2.  **Gatilho para LIGAR (Clear):** Nível onde a restrição é desfeita e a enchedora volta a acelerar a 100% (ex: B2 > 30% ou B3 < 65%).

Se o simulador Python não modelar essa folga (histerese), as velocidades recomendadas pela IA não funcionarão perfeitamente na fábrica real, pois o CLP real possui essa memória física de estado.

---

## 3. Parâmetros Físicos Finais

*   **`VELOCIDADE_NOMINAL_ECH` (ex: 52.700 CPH):** É a velocidade máxima de projeto (100% de capacidade). Ela traduz as porcentagens em volumes reais de produção (Garrafas por Hora).
*   **`CAPACIDADE_ESTEIRAS_INTERNAS / EXTREMAS`:** Capacidades estáticas estimadas de garrafas físicas que as esteiras conseguem acumular. Como o controle usa a medição direta em porcentagem (%) dos sensores, esses parâmetros são puramente informativos e não interferem na matemática da otimização de velocidade.
