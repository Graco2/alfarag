"""Mede o efeito da grafia (com e sem acento) no teste de cobertura do harness.

A mesma pergunta, escrita com e sem acentos, passa pela busca da demonstração (E2, C4)
e pelo mesmo teste de cobertura do pipeline. Não chama o modelo de linguagem.

Uso: python scripts/medir_grafia.py  -> resultados/grafia.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from app import harness  # noqa: E402
from app.config import CONDICOES, LIMIAR_COBERTURA  # noqa: E402
from app.indice import carregar  # noqa: E402

PARES = [
    ("pato e prato", "meu aluno lê pato mas não lê prato. como posso ajudar?",
     "meu aluno le pato mas nao le prato. como posso ajudar?"),
    ("letras no 2º ano", "aluno do 2º ano não reconhece as letras, o que fazer?",
     "aluno do 2 ano nao reconhece as letras, o que fazer"),
    ("lê e não entende", "meu aluno lê mas não entende o que lê. o que faço?",
     "meu aluno le mas nao entende o que le. o que faco?"),
]


def medir(idx, pergunta: str, cond: str) -> dict:
    cob = harness.checar_cobertura(idx.buscar(pergunta, CONDICOES[cond]))
    return {"pergunta": pergunta, "melhor_cos": cob.melhor_cos, "coberta": cob.coberta}


def main() -> None:
    idx = carregar("E2")
    saida = {"experimento": "E2", "condicao": "C4", "limiar": LIMIAR_COBERTURA, "pares": []}
    for rotulo, com, sem in PARES:
        par = {"rotulo": rotulo, "com_acento": medir(idx, com, "C4"), "sem_acento": medir(idx, sem, "C4")}
        saida["pares"].append(par)
        print(f"{rotulo:<18} com acento {par['com_acento']['melhor_cos']:.3f} ({'passa' if par['com_acento']['coberta'] else 'recusa'})"
              f" · sem acento {par['sem_acento']['melhor_cos']:.3f} ({'passa' if par['sem_acento']['coberta'] else 'recusa'})")
    (RAIZ / "resultados" / "grafia.json").write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
