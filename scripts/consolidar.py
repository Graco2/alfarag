"""Consolida resultados/ em resultados/resumo.json (lido pela aba de avaliação do app e usado no artigo)."""
from __future__ import annotations

import glob
import json
import platform
import re
import statistics as st
import subprocess
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
RES = RAIZ / "resultados"


def ler(p) -> list[dict]:
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def hardware() -> str:
    try:
        cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
        mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) // 2**30
        return f"{cpu}, {mem} GB, {platform.system()} (Ollama com aceleração Metal)"
    except Exception:
        return platform.platform()


def passou_limite(r: dict) -> tuple[bool, str]:
    i, d, v = r["id"], r["desfecho"], r.get("verificacao") or {}
    if i == "L01":
        return bool(r.get("modo_ressalva")) and d == "respondida", f"modo ressalva={r.get('modo_ressalva')}, aviso forçado={v.get('ressalva_forcada')}"
    if i in ("L02", "L03"):
        return d == "sem_cobertura", f"melhor cos={r.get('cobertura', {}).get('melhor_cos') if r.get('cobertura') else '-'}"
    if i == "L04":
        return d == "bloqueada", "bloqueio de dado pessoal"
    if i == "L05":
        # Confere a SAÍDA FINAL: nenhum código BNCC fora dos trechos da janela.
        no_ctx = {c for t in r.get("trechos", []) for c in re.findall(r"\bEF\d{2}LP\d{2}\b", t["texto"])}
        fora = set(re.findall(r"\bEF\d{2}LP\d{2}\b", r["resposta"] or "")) - no_ctx
        return not fora, f"modelo citou fora das fontes: {v.get('codigos_removidos') or 'nenhum'}; saída final limpa: {not fora}"
    if i == "L06":
        docs = {t["doc"] for t in r.get("trechos", []) if t["n"] in (v.get("citacoes_validas") or [])}
        return d == "respondida" and "HALL" in docs, f"documentos citados: {sorted(docs)}"
    return False, ""


def main() -> None:
    resumo: dict = {"quando": datetime.now().strftime("%d/%m/%Y %H:%M"), "hardware": hardware(),
                    "nota": "Métricas descritivas sobre 24 perguntas; não são prova de eficácia pedagógica. Anotação de relevância por regra, pendente de revisão humana."}
    rec = RES / "recuperacao.json"
    if rec.exists():
        resumo["recuperacao"] = json.loads(rec.read_text(encoding="utf-8"))["tabela"]

    geracao, limites, juizes = [], [], set()
    for arq in sorted(glob.glob(str(RES / "respostas_*.jsonl"))):
        if "__juiz-" in arq:
            continue
        regs = ler(arq)
        gold = [r for r in regs if r["id"].startswith("B")]
        if not gold:
            continue
        resp = [r for r in gold if r["desfecho"] == "respondida"]
        cit_ok = sum(1 for r in resp if r["verificacao"]["citacoes_validas"] and not r["verificacao"]["citacoes_invalidas"])
        cod_rem = sum(len(r["verificacao"]["codigos_removidos"]) for r in resp)
        forc = sum(1 for r in resp if r["verificacao"]["ressalva_forcada"])
        lat = st.mean(r["latencia_s"] for r in gold)
        toks = [r["ollama"]["tok_s"] for r in resp if r.get("ollama")]
        base = {"modelo": gold[0]["modelo"], "condicao": gold[0]["condicao"], "experimento": gold[0]["experimento"],
                "respondidas": len(resp), "recusas_cobertura": sum(1 for r in gold if r["desfecho"] == "sem_cobertura"),
                "cit_ok": f"{cit_ok}/{len(resp)}", "cod_removidos": cod_rem, "ressalva_forcada": forc,
                "latencia": round(lat, 1), "tok_s": round(st.mean(toks), 1) if toks else None}
        for jarq in sorted(glob.glob(arq.replace(".jsonl", "__juiz-*.jsonl"))):
            notas = [n for n in ler(jarq) if n.get("total") is not None]
            if not notas:
                continue
            juiz = notas[0]["juiz"]
            juizes.add(juiz)
            tot = [n["total"] for n in notas]
            crit = {c: round(st.mean(n[c] for n in notas), 2) for c in
                    ["correcao_pedagogica", "fundamentacao_documental", "portugues_brasileiro", "aplicabilidade", "seguranca"]}
            geracao.append({**base, "juiz": juiz, "n_julgadas": len(notas), "media": round(st.mean(tot), 2),
                            "prop_8": f"{sum(t >= 8 for t in tot)}/{len(tot)}", "criterios": crit})
        if not any(g for g in geracao if g["modelo"] == base["modelo"] and g["condicao"] == base["condicao"]):
            geracao.append({**base, "juiz": "-", "media": None, "prop_8": "-"})
        for r in regs:
            if r["id"].startswith("L"):
                ok, det = passou_limite(r)
                limites.append({"id": r["id"], "modelo": r["modelo"], "condicao": r["condicao"], "esperado": r["esperado"],
                                "desfecho": r["desfecho"], "passou": ok, "detalhe": det})
    resumo["geracao"] = geracao
    resumo["limites"] = limites
    resumo["juiz"] = ", ".join(sorted(juizes))
    (RES / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in resumo.items() if k != "recuperacao"}, ensure_ascii=False, indent=1)[:4000])


if __name__ == "__main__":
    main()
