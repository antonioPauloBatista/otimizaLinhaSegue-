# 🎯 Como Funciona a Otimização dos Buffers pelo CMA-ES?

Explicação técnica e intuitiva do funcionamento real do script [`otimizador_cma_es_free.py`](file:///home/antonio/Projetos/OtimizadorSegue/Otimizador_CMA/otimizador_cma_es_free.py), demonstrando o mapeamento da linha, a resolução dinâmica dos buffers, a matriz de busca 8D e a simulação de ganho em garrafas/OEE.

---

## 🖼️ Diagrama Mestre Completo: Arquitetura do Otimizador & Gêmeo Digital

![Arquitetura Completa do Otimizador CMA-ES](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/cma_es_busca_buffers.svg)

---

## 📌 Tudo o Que Está Contemplado no Módulo:

### 1. Arquitetura da Linha & Resolução Dinâmica
- **Resolução de Colunas (`resolver_coluna`):** Detecta automaticamente no CSV se a fábrica possui 2 ou 4 buffers.
- **Buffers B2 (Entrada) & B3 (Saída):** Obrigatórios para controle direto da Enchedora (ECH).
- **Buffers B1 & B4:** Opcionais (`HAS_B1` e `HAS_B4`). Se existirem na planta, entram na otimização de borda (*Modo Free*).

### 2. Matriz de Busca Vetorial 8D
- **Proteção Contra Falta (Desabastecimento):** Sintoniza os gatilhos (%) e velocidades (% ECH) para B1 e B2.
- **Proteção Contra Acúmulo (Afogamento):** Sintoniza os gatilhos (%) e velocidades (% ECH) para B3 e B4.

### 3. Processo de Adaptação da Covariância
- **Amostragem Vetorial (1):** População de combinações numéricas no espaço 8D.
- **Simulação Gêmeo Digital (2):** Avaliação linha a linha no dataset histórico real da fábrica.
- **Adaptação da Covariância (3):** Deformação estatística da elipse de busca na direção da menor perda e maior estabilidade.

### 4. Função Objetivo (Cálculo do Ganho de Benefício)
- **Maximiza a Produção Líquida (Δ Garrafas/Hora / OEE Líquido).**
- **Elimina Paradas Bruscas (Soco):** Reduz a rampa de velocidade antes dos buffers esvaziarem ou encherem por completo.
- **Suavização de Transição:** Evita sobressaltos e preserva o desgaste mecânico dos equipamentos.

---

## 🎬 Animação Interativa de Controle (2 Buffers B2 & B3)

![Animação CMA-ES Controle de 2 Buffers](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/animacao_cma_es.gif)

> 💡 **Para ver em formato interativo com controles de play/pause:** abra o arquivo HTML [`apresentacao/animacao_cma_es.html`](file:///home/antonio/Projetos/OtimizadorSegue/apresentacao/animacao_cma_es.html) no seu navegador!
