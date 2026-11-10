#!/usr/bin/env bash
# Gera os entregáveis do Exame a partir de resultados/ (nenhum número é digitado à mão).
# Uso: bash docs/gerar_entregaveis.sh <dir-node_modules-com-pptxgenjs> <apply_theme.js>
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=entregaveis; mkdir -p "$OUT"
NOME=TE251_2026-2_Exame_Imeanos_no_ITA
.venv/bin/python scripts/figura_arquitetura.py
.venv/bin/python scripts/consolidar.py > /dev/null
.venv/bin/python docs/dados_slides.py > /dev/null
.venv/bin/python docs/artigo.py docs/modelo_artigo_sige_2026_v1.docx "$OUT/${NOME}_artigo.docx"
NODE_PATH="$1" node docs/slides.js "$OUT/${NOME}_slides.pptx" "$2"
(cd "$OUT" && soffice --headless --convert-to pdf "${NOME}_artigo.docx" >/dev/null 2>&1 && soffice --headless --convert-to pdf "${NOME}_slides.pptx" >/dev/null 2>&1)
ls -la "$OUT"
