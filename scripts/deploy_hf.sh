#!/usr/bin/env bash
# Publica o AlfaRAG no Hugging Face Spaces (Docker, hardware "CPU basic" gratuito: 2 vCPU, 16 GB).
# Pré-requisito (uma vez): hf auth login   (token com permissão de escrita)
# Uso: bash scripts/deploy_hf.sh <usuario-hf>/alfarag
set -euo pipefail
SPACE=${1:?"uso: deploy_hf.sh <usuario-hf>/alfarag"}
cd "$(dirname "$0")/.."
STAGE=$(mktemp -d)
cp -R Dockerfile start.sh requirements.txt README.md AGENTS.md SKILL.md app web benchmark "$STAGE"/
mkdir -p "$STAGE/index" "$STAGE/corpus" "$STAGE/resultados"
cp index/chunks_E2.jsonl index/emb_E2_bge-m3.npy "$STAGE/index/"
cp corpus/documentos.json "$STAGE/corpus/"
cp resultados/resumo.json "$STAGE/resultados/"
find "$STAGE" -name __pycache__ -prune -exec rm -rf {} +
hf repos create "$SPACE" --type space --space-sdk docker --public --exist-ok
hf upload "$SPACE" "$STAGE" . --repo-type space --commit-message "deploy AlfaRAG"
echo "Space: https://huggingface.co/spaces/$SPACE  (o build do Docker leva ~10–20 min na primeira vez)"
