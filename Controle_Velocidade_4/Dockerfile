# Imagem industrial para o Controlador de Velocidade V4 OPC
FROM python:3.11-slim

# Metadados
LABEL maintainer="Brewtech Automation / Segue V4"
LABEL description="Controlador Avançado de Velocidade V4 com Comunicação OPC UA Subscription"

# Variáveis de ambiente para execução limpa e segura
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODO_SOMBRA=true

WORKDIR /app

# Instalação das bibliotecas necessárias
RUN pip install --no-cache-dir \
    asyncua==1.1.5 \
    cryptography \
    requests

# Cópia direta dos arquivos da aplicação para a imagem (sem necessidade de volumes de código)
COPY cliente_opc_v4.py /app/cliente_opc_v4.py
COPY gravador_grafana_v4.py /app/gravador_grafana_v4.py
COPY funcao_controle_v4.py /app/funcao_controle_v4.py
COPY gerenciador_buffers.py /app/gerenciador_buffers.py
COPY motivos_modulacao_enum.json /app/motivos_modulacao_enum.json
COPY config_opc_v4.json /app/config_opc_v4.json
COPY parametros_controle_v4.json* /app/

# Ponto de entrada padrão: Inicia garantido em Modo Sombra (shadow) a menos que explicitamente alterado via ENV MODO_SOMBRA=false
CMD ["python", "cliente_opc_v4.py"]
