"""API + front-end estático. Um processo só: serve /api e a página do chat."""
from __future__ import annotations

import csv
import json
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import (CONDICAO, CONDICOES, EXPERIMENTO, EXPERIMENTOS, LIMIAR_COBERTURA, MODELO_EMBED, MODELO_LLM,
                     MODELOS_PERMITIDOS, ORCAMENTO_CONTEXTO, RAIZ)
from .llm import modelos_disponiveis
from .pipeline import ROTULOS, responder
from .prompts import PROMPT_SISTEMA, VERSAO_PROMPT

app = FastAPI(title="AlfaRAG — assistente de alfabetização", docs_url="/api/docs")
WEB = RAIZ / "web"
RESULTADOS = RAIZ / "resultados"

# Harness de infraestrutura: em CPU só uma geração por vez; as demais esperam até 120 s.
_GERACAO = threading.Semaphore(1)


class Pergunta(BaseModel):
    pergunta: str = Field(..., max_length=4000)
    modelo: str | None = None


@app.get("/api/status")
def status():
    disp = modelos_disponiveis()
    return {
        "ollama": bool(disp),
        "modelo_padrao": MODELO_LLM,
        "modelos": [m for m in MODELOS_PERMITIDOS if m in disp],
        "modelo_embed": MODELO_EMBED,
        "experimento": EXPERIMENTO,
        "chunk": EXPERIMENTOS[EXPERIMENTO],
        "condicao": CONDICAO,
        "documentos": [{"id": d, "rotulo": ROTULOS[d]} for d in CONDICOES[CONDICAO]],
        "orcamento_contexto": ORCAMENTO_CONTEXTO,
        "limiar_cobertura": LIMIAR_COBERTURA,
        "versao_prompt": VERSAO_PROMPT,
    }


@app.get("/api/prompt")
def prompt():
    return {"versao": VERSAO_PROMPT, "sistema": PROMPT_SISTEMA}


@app.get("/api/exemplos")
def exemplos():
    out = []
    arq = RAIZ / "benchmark" / "perguntas_gold.csv"
    if arq.exists():
        with arq.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.append({"id": r["id"], "pergunta": r["question"], "categoria": r["category"], "esperado": r["expected_behavior"]})
    lim = RAIZ / "benchmark" / "casos_limite.csv"
    if lim.exists():
        with lim.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.append({"id": r["id"], "pergunta": r["question"], "categoria": r["category"], "esperado": r["expected_behavior"]})
    return out


@app.get("/api/avaliacao")
def avaliacao():
    arq = RESULTADOS / "resumo.json"
    if not arq.exists():
        return JSONResponse({"disponivel": False})
    return json.loads(arq.read_text(encoding="utf-8"))


@app.get("/api/traco/{tid}")
def traco(tid: str):
    """Modo replay: devolve uma resposta já gerada (traço JSONL), sem chamar o modelo."""
    if not tid.isalnum() or len(tid) > 32:
        raise HTTPException(400, "id inválido")
    from .config import TRACOS_DIR
    for arq in sorted(TRACOS_DIR.glob("tracos_*.jsonl"), reverse=True):
        for linha in arq.open(encoding="utf-8"):
            if f'"id": "{tid}"' in linha:
                t = json.loads(linha)
                return {"pergunta": t["pergunta"], "janela": t.get("janela"),
                        "final": {"tipo": "final", "desfecho": t["desfecho"], "resposta": t["resposta"],
                                  "verificacao": t.get("verificacao"), "traco": t}}
    raise HTTPException(404, "traço não encontrado")


@app.post("/api/perguntar")
def perguntar(p: Pergunta):
    modelo = p.modelo or MODELO_LLM
    if modelo not in MODELOS_PERMITIDOS:
        raise HTTPException(400, f"Modelo não permitido: {modelo}")

    def gerar():
        if not _GERACAO.acquire(timeout=120):
            yield json.dumps({"tipo": "final", "desfecho": "ocupado",
                              "resposta": "O servidor está atendendo outra pergunta (o modelo roda em CPU, uma por vez). Tente de novo em instantes."},
                             ensure_ascii=False) + "\n"
            return
        try:
            for ev in responder(p.pergunta, modelo=modelo):
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        finally:
            _GERACAO.release()

    return StreamingResponse(gerar(), media_type="application/x-ndjson", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
