"""Etapa 6b — Gera as respostas do RAG para as 24 perguntas + casos-limite e grava o traço.

Uso:
    python scripts/avaliar_respostas.py --modelo qwen3.5:4b --condicao C4 --exp E2
Saída: resultados/respostas_<modelo>_<condicao>_<exp>.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from app.pipeline import responder_sync  # noqa: E402


def nome_saida(modelo: str, cond: str, exp: str) -> Path:
    return RAIZ / "resultados" / f"respostas_{modelo.replace(':', '-')}_{cond}_{exp}.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", default="qwen3.5:4b")
    ap.add_argument("--condicao", default="C4")
    ap.add_argument("--exp", default="E2")
    ap.add_argument("--sem-limites", action="store_true")
    a = ap.parse_args()

    itens = list(csv.DictReader((RAIZ / "benchmark" / "perguntas_gold.csv").open(encoding="utf-8")))
    if not a.sem_limites:
        itens += list(csv.DictReader((RAIZ / "benchmark" / "casos_limite.csv").open(encoding="utf-8")))
    saida = nome_saida(a.modelo, a.condicao, a.exp)
    saida.parent.mkdir(exist_ok=True)
    feitos = set()
    if saida.exists():
        feitos = {json.loads(l)["id"] for l in saida.open(encoding="utf-8")}
    with saida.open("a", encoding="utf-8") as f:
        for q in itens:
            if q["id"] in feitos:
                continue
            t0 = time.time()
            r = responder_sync(q["question"], modelo=a.modelo, exp=a.exp, condicao=a.condicao, temperatura=0.0)
            reg = {
                "id": q["id"], "pergunta": q["question"], "esperado": q["expected_behavior"], "categoria": q["category"],
                "modelo": a.modelo, "condicao": a.condicao, "experimento": a.exp,
                "desfecho": r.get("desfecho"), "resposta": r.get("resposta"), "verificacao": r.get("verificacao"),
                "trechos": [{k: t[k] for k in ("n", "id", "doc", "rotulo", "pagina", "secao", "cos", "texto")} for t in r.get("janela", {}).get("trechos", [])],
                "cobertura": r.get("janela", {}).get("cobertura"),
                "modo_ressalva": r.get("janela", {}).get("modo_ressalva"),
                "ollama": r.get("traco", {}).get("ollama"), "latencia_s": round(time.time() - t0, 2),
            }
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
            f.flush()
            v = reg["verificacao"] or {}
            print(f"{q['id']} {reg['desfecho']:<13} {reg['latencia_s']:>6}s  cit={v.get('citacoes_validas')} rem={v.get('codigos_removidos')} forc={v.get('ressalva_forcada')}")


if __name__ == "__main__":
    main()
