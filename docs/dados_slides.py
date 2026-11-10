"""Extrai de resultados/ os números e trechos usados nos slides -> docs/slides_data.json."""
from __future__ import annotations

import json
import re
import statistics as st
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from app.config import LIMIAR_COBERTURA, MODELO_LLM, ORCAMENTO_CONTEXTO  # noqa: E402
from app.prompts import VERSAO_PROMPT  # noqa: E402

RES = RAIZ / "resultados"
G = "gemma4:e4b-it-q4_K_M"


def ler(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def resp(modelo, cond):
    return RES / f"respostas_{modelo.replace(':', '-')}_{cond}_E2.jsonl"


def juiz_arq(modelo, cond, j):
    return RES / f"respostas_{modelo.replace(':', '-')}_{cond}_E2__juiz-{j.replace(':', '-')}.jsonl"


def juiz(modelo, cond, j):
    p = juiz_arq(modelo, cond, j)
    if not p.exists():
        return None
    t = [n["total"] for n in ler(p) if n.get("total") is not None]
    return {"media": round(st.mean(t), 2), "ge8": sum(x >= 8 for x in t), "n": len(t)} if t else None


def execucao(modelo, cond):
    regs = [r for r in ler(resp(modelo, cond)) if r["id"].startswith("B")] if resp(modelo, cond).exists() else []
    ok = [r for r in regs if r["desfecho"] == "respondida"]
    return {
        "n": len(regs), "respondidas": len(ok),
        "cit_ok": sum(1 for r in ok if r["verificacao"]["citacoes_validas"] and not r["verificacao"]["citacoes_invalidas"]),
        "cod_rem": sum(len(r["verificacao"]["codigos_removidos"]) for r in ok),
        "forc": sum(r["verificacao"]["ressalva_forcada"] for r in ok),
        "lat": round(st.mean(r["latencia_s"] for r in ok), 1) if ok else None,
        "digest": next((r.get("modelo_digest") for r in regs if r.get("modelo_digest")), None),
        "juiz_gemma": juiz(modelo, cond, G), "juiz_qwen": juiz(modelo, cond, MODELO_LLM),
    }


def main():
    rec = json.load(open(RES / "recuperacao.json", encoding="utf-8"))["tabela"]
    regs = {r["id"]: r for r in ler(resp(MODELO_LLM, "C4"))}
    b03 = regs["B03"]
    # O slide 6 mostra a captura do traço de demonstração: usa os números DESSE traço.
    demo = (RAIZ / "docs" / "screens" / "tracos_demo.txt")
    if demo.exists():
        tid = demo.read_text().split()[0]
        for arq in sorted((RES / "tracos").glob("tracos_*.jsonl")):
            for l in arq.open(encoding="utf-8"):
                if f'"id": "{tid}"' in l:
                    t = json.loads(l)
                    b03 = {"pergunta": t["pergunta"], "resposta": t["resposta"], "verificacao": t["verificacao"],
                           "trechos": t["janela"]["trechos"], "latencia_s": t["latencia_s"], "ollama": t["ollama"], "traco": tid}
    lim = {k: {"desfecho": v["desfecho"], "cos": (v.get("cobertura") or {}).get("melhor_cos"),
               "verificacao": v.get("verificacao"), "resposta": (v.get("resposta") or "")[:600]} for k, v in regs.items() if k.startswith("L")}
    cpu = json.load(open(RES / "latencia_cpu.json", encoding="utf-8")) if (RES / "latencia_cpu.json").exists() else None
    dados = {
        "modelo": MODELO_LLM, "gemma": G, "versao_prompt": VERSAO_PROMPT, "orcamento": ORCAMENTO_CONTEXTO,
        "limiar": LIMIAR_COBERTURA,
        "recuperacao": {f"{r['experimento']}_{r['condicao']}": {"recall": r["recall"], "mrr": r["mrr"]} for r in rec},
        "qwen_c4": execucao(MODELO_LLM, "C4"), "gemma_c4": execucao(G, "C4"), "qwen_c1": execucao(MODELO_LLM, "C1"),
        "qwen_c5": execucao(MODELO_LLM, "C5") if resp(MODELO_LLM, "C5").exists() else None,
        "b03": {"pergunta": b03["pergunta"], "resposta": b03["resposta"], "verificacao": b03["verificacao"],
                "trechos": [{k: t[k] for k in ("n", "rotulo", "pagina", "secao")} for t in b03["trechos"]],
                "latencia": b03["latencia_s"], "tokens": b03["ollama"], "traco": b03.get("traco")},
        "limites": lim, "cpu": cpu,
        # Leitura humana (nossa) do B03: a resposta chama “prato”/“porta” de grafema complexo. O slide 6 só mostra a nota
        # se o texto gravado ainda trouxer esse erro; se a demo for refeita, reler a resposta.
        "b03_erro": bool(re.search(r"grafemas? (múltiplos|complexos)|mais de um fonema", b03["resposta"] or "")),
        "b03_juizes": [n["total"] for j in (G, MODELO_LLM) if juiz_arq(MODELO_LLM, "C4", j).exists()
                       for n in ler(juiz_arq(MODELO_LLM, "C4", j)) if n["id"] == "B03"],
    }
    json.dump(dados, open(RAIZ / "docs" / "slides_data.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in dados.items() if k not in ("b03", "recuperacao")}, ensure_ascii=False, indent=1)[:3000])


if __name__ == "__main__":
    main()
