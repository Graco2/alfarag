#!/usr/bin/env bash
# Executa a avaliação completa descrita em SKILL.md, em sequência (o Ollama atende uma geração por vez).
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
echo "== $(date '+%H:%M:%S') recuperação"; $PY scripts/avaliar_retrieval.py
echo "== $(date '+%H:%M:%S') respostas qwen3.5:4b-q4_K_M C4"; $PY scripts/avaliar_respostas.py --modelo qwen3.5:4b-q4_K_M --condicao C4 --exp E2
echo "== $(date '+%H:%M:%S') respostas gemma4:e4b-it-q4_K_M C4"; $PY scripts/avaliar_respostas.py --modelo gemma4:e4b-it-q4_K_M --condicao C4 --exp E2
echo "== $(date '+%H:%M:%S') respostas qwen3.5:4b-q4_K_M C1"; $PY scripts/avaliar_respostas.py --modelo qwen3.5:4b-q4_K_M --condicao C1 --exp E2 --sem-limites
for f in resultados/respostas_*_E2.jsonl; do
  case "$f" in *__juiz-*) continue;; esac
  echo "== $(date '+%H:%M:%S') juiz gemma4:e4b-it-q4_K_M em $f"; $PY scripts/julgar_respostas.py --respostas "$f" --juiz gemma4:e4b-it-q4_K_M
  echo "== $(date '+%H:%M:%S') juiz qwen3.5:4b-q4_K_M em $f"; $PY scripts/julgar_respostas.py --respostas "$f" --juiz qwen3.5:4b-q4_K_M
done
echo "== $(date '+%H:%M:%S') consolidar"; $PY scripts/consolidar.py
echo "== $(date '+%H:%M:%S') FIM"
