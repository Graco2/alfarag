"""Etapa 6a — Avaliação da recuperação: Recall@5 e MRR@10 por chunking (E1–E4) e corpus (C1–C4).

Relevância por regra (ver montar_benchmark.py): um trecho é relevante se
  * é da BNCC e contém literalmente um dos códigos esperados (ou qualquer trecho BNCC quando a regra é bncc:*);
  * é de Habilidades Essenciais do 2º ano e contém um dos códigos (he2:<códigos>), ou qualquer trecho dele (he2:*);
  * é do Manual ABC e está em um dos capítulos esperados.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from app.config import CONDICOES, EXPERIMENTOS  # noqa: E402
from app.indice import carregar  # noqa: E402

K_RECALL, K_MRR = 5, 10


def regra(gold: str) -> dict:
    # por_codigo: documento -> "*" (qualquer trecho) ou conjunto de códigos (BNCC e Habilidades Essenciais).
    r = {"por_codigo": {}, "abc": set()}
    for parte in gold.split("|"):
        tipo, _, val = parte.partition(":")
        if tipo == "abc":
            r["abc"] = {int(x) for x in val.split(",") if x}
        elif tipo:
            r["por_codigo"][tipo.upper()] = "*" if val == "*" else set(val.split(","))
    return r


def relevante(c: dict, r: dict) -> bool:
    alvo = r["por_codigo"].get(c["doc"])
    if alvo is not None:
        return alvo == "*" or bool(alvo & set(c["codigos_bncc"]))
    if c["doc"] == "ABC" and r["abc"]:
        m = re.search(r"Cap\. (\d+)", c.get("secao", ""))
        return bool(m and int(m.group(1)) in r["abc"])
    return False


def main() -> None:
    perguntas = list(csv.DictReader((RAIZ / "benchmark" / "perguntas_gold.csv").open(encoding="utf-8")))
    linhas, detalhe = [], []
    for exp in EXPERIMENTOS:
        idx = carregar(exp)
        for cond, docs in CONDICOES.items():
            hits, rr = 0, 0.0
            for q in perguntas:
                r = regra(q["gold_passages"])
                ranking = idx.buscar(q["question"], docs)[:K_MRR]
                rel = [relevante(c, r) for c in ranking]
                if any(rel[:K_RECALL]):
                    hits += 1
                pos = next((i + 1 for i, x in enumerate(rel) if x), None)
                rr += 1 / pos if pos else 0
                detalhe.append({"exp": exp, "cond": cond, "id": q["id"], "primeiro_relevante": pos,
                                "top5": [f"{c['doc']}:{c.get('pagina_ini')}" for c in ranking[:5]]})
            n = len(perguntas)
            linhas.append({"experimento": exp, "condicao": cond, "recall": round(hits / n, 3), "mrr": round(rr / n, 3),
                           "k": K_RECALL, "acertos": hits, "n": n})
            print(f"{exp} {cond}: Recall@{K_RECALL}={hits}/{n}={hits / n:.3f}  MRR@{K_MRR}={rr / n:.3f}")
    out = RAIZ / "resultados"
    out.mkdir(exist_ok=True)
    (out / "recuperacao.json").write_text(json.dumps({"tabela": linhas, "detalhe": detalhe}, ensure_ascii=False, indent=1), encoding="utf-8")
    with (out / "recuperacao.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]))
        w.writeheader()
        w.writerows(linhas)


if __name__ == "__main__":
    main()
