#!/usr/bin/env bash
# Sobe o Ollama, espera ficar pronto, pré-carrega os modelos e inicia a API.
set -euo pipefail
ollama serve &
for i in $(seq 1 60); do
  curl -sf http://127.0.0.1:11434/api/tags >/dev/null && break
  sleep 1
done
# Aquecimento: carrega embeddings e LLM na RAM para a primeira pergunta não pagar o custo.
curl -sf http://127.0.0.1:11434/api/embed -d '{"model":"bge-m3","input":["aquecimento"]}' >/dev/null || true
curl -sf http://127.0.0.1:11434/api/generate -d "{\"model\":\"${MODELO_LLM:-qwen3.5:4b-q4_K_M}\",\"prompt\":\"ok\",\"think\":false,\"options\":{\"num_predict\":1}}" >/dev/null || true
exec /opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}" --log-level info --no-server-header
