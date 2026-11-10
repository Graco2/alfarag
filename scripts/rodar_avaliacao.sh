#!/usr/bin/env bash
# Executa a avaliação completa descrita em SKILL.md, em sequência (o Ollama atende uma geração por vez).
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
# Avaliação completa = execução nova. Os scripts de respostas e de juiz retomam de onde pararam
# (pulam ids já gravados); por isso as saídas anteriores vão para resultados/anterior/<data>/.
ARQ="resultados/anterior/$(date '+%Y%m%d-%H%M%S')"
if ls resultados/respostas_*.jsonl >/dev/null 2>&1; then
  mkdir -p "$ARQ" && mv resultados/respostas_*.jsonl "$ARQ"/ && echo "== saídas anteriores arquivadas em $ARQ"
fi
echo "== $(date '+%H:%M:%S') recuperação"; $PY scripts/avaliar_retrieval.py
echo "== $(date '+%H:%M:%S') grafia (com e sem acento) no teste de cobertura"; $PY scripts/medir_grafia.py
echo "== $(date '+%H:%M:%S') respostas qwen3.5:4b-q4_K_M C4"; $PY scripts/avaliar_respostas.py --modelo qwen3.5:4b-q4_K_M --condicao C4 --exp E2
echo "== $(date '+%H:%M:%S') respostas gemma4:e4b-it-q4_K_M C4"; $PY scripts/avaliar_respostas.py --modelo gemma4:e4b-it-q4_K_M --condicao C4 --exp E2
echo "== $(date '+%H:%M:%S') respostas qwen3.5:4b-q4_K_M C1"; $PY scripts/avaliar_respostas.py --modelo qwen3.5:4b-q4_K_M --condicao C1 --exp E2 --sem-limites
# C5 = C4 + resumos de vídeo (experimento à parte; a demonstração usa C4).
echo "== $(date '+%H:%M:%S') respostas qwen3.5:4b-q4_K_M C5"; $PY scripts/avaliar_respostas.py --modelo qwen3.5:4b-q4_K_M --condicao C5 --exp E2
for f in resultados/respostas_*_E2.jsonl; do
  case "$f" in *__juiz-*) continue;; esac
  echo "== $(date '+%H:%M:%S') juiz gemma4:e4b-it-q4_K_M em $f"; $PY scripts/julgar_respostas.py --respostas "$f" --juiz gemma4:e4b-it-q4_K_M
  echo "== $(date '+%H:%M:%S') juiz qwen3.5:4b-q4_K_M em $f"; $PY scripts/julgar_respostas.py --respostas "$f" --juiz qwen3.5:4b-q4_K_M
done
echo "== $(date '+%H:%M:%S') consolidar"; $PY scripts/consolidar.py
echo "== $(date '+%H:%M:%S') FIM"
