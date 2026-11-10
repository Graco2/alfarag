"""Mede a latência da geração SÓ EM CPU (Ollama com num_gpu=0) em algumas perguntas do benchmark.

Uso: FORCAR_CPU=1 python scripts/medir_cpu.py  -> resultados/latencia_cpu.json
"""
from __future__ import annotations

import csv
import json
import os
import platform
import statistics as st
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("FORCAR_CPU", "1")
from app.pipeline import responder_sync  # noqa: E402
from app.config import MODELO_LLM  # noqa: E402

IDS = ["B03", "B08", "B16"]


def main() -> None:
    qs = {r["id"]: r["question"] for r in csv.DictReader((RAIZ / "benchmark" / "perguntas_gold.csv").open(encoding="utf-8"))}
    linhas = []
    for i in IDS:
        r = responder_sync(qs[i], modelo=MODELO_LLM, temperatura=0.0)
        o = r.get("traco", {}).get("ollama") or {}
        linhas.append({"id": i, "desfecho": r.get("desfecho"), "latencia_s": r.get("traco", {}).get("latencia_s"),
                       "prompt_tokens": o.get("prompt_tokens"), "resposta_tokens": o.get("resposta_tokens"), "tok_s": o.get("tok_s")})
        print(linhas[-1])
    ok = [l for l in linhas if l["desfecho"] == "respondida"]
    out = {"modelo": MODELO_LLM, "modo": "CPU (num_gpu=0)", "maquina": platform.machine(), "n": len(ok),
           "latencia_media_s": st.mean(l["latencia_s"] for l in ok), "tok_s_medio": st.mean(l["tok_s"] for l in ok), "linhas": linhas}
    (RAIZ / "resultados" / "latencia_cpu.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
