# Um container só: Ollama (CPU) + API FastAPI + front-end estático.
# Pensado para o Hugging Face Spaces (Docker, CPU basic: 2 vCPU / 16 GB, gratuito),
# mas roda igual em qualquer host Docker (Railway, Render, máquina local).
FROM ollama/ollama:0.40.16

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv python3-pip curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Modelos baixados NA IMAGEM (versões fixas): o container acorda sem download.
ENV OLLAMA_MODELS=/opt/ollama-models \
    OLLAMA_NOPRUNE=1 \
    OLLAMA_KEEP_ALIVE=30m \
    OLLAMA_NUM_PARALLEL=1 \
    OLLAMA_MAX_LOADED_MODELS=2 \
    HOME=/tmp
RUN ollama serve > /tmp/pull.log 2>&1 & \
    for i in $(seq 1 30); do curl -sf http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 1; done; \
    ollama pull qwen3.5:4b-q4_K_M && ollama pull bge-m3 && chmod -R a+rX /opt/ollama-models

COPY app ./app
COPY web ./web
COPY corpus/documentos.json ./corpus/documentos.json
COPY index/chunks_E2.jsonl index/emb_E2_bge-m3.npy ./index/
COPY benchmark ./benchmark
COPY resultados/resumo.json resultados/tracos_demo.jsonl ./resultados/
COPY start.sh ./start.sh

ENV PORT=7860 \
    MODELO_LLM=qwen3.5:4b-q4_K_M \
    MODELOS_PERMITIDOS=qwen3.5:4b-q4_K_M \
    EXPERIMENTO=E2 \
    CONDICAO=C6 \
    TRACOS_DIR=/tmp/tracos
EXPOSE 7860
ENTRYPOINT []
CMD ["bash", "start.sh"]
