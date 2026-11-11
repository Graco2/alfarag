"""API + front-end estático. Um processo só: serve /api e a página do chat."""
from __future__ import annotations

import csv
import json
import threading

from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import conexoes
from .config import (CONDICAO, CONDICOES, CONEXOES_LOCAL, EXPERIMENTO, EXPERIMENTOS, LIMIAR_COBERTURA, MODELO_EMBED,
                     MODELO_LLM, MODELOS_PERMITIDOS, ORCAMENTO_CONTEXTO, RAIZ)
from .llm import modelos_disponiveis, resolver
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


_PROXY_HDRS = ("x-forwarded-for", "forwarded", "x-real-ip", "x-forwarded-host")


def servidor_local(request: Request) -> bool:
    """A tela de Conexões só vale quando o servidor é do próprio usuário: cliente loopback e sem proxy na frente,
    ou CONEXOES_LOCAL=1 (docker run -p, onde o cliente chega como IP da ponte)."""
    if CONEXOES_LOCAL:
        return True
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1") and not any(h in request.headers for h in _PROXY_HDRS)


def exigir_local(request: Request) -> None:
    if not servidor_local(request):
        raise HTTPException(403, "Conexões só podem ser configuradas no servidor local.")


def exigir_escrita_segura(request: Request) -> None:
    """Contra CSRF de outra página aberta no navegador: JSON explícito e Origin igual ao Host."""
    exigir_local(request)
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "Use Content-Type: application/json.")
    origem = request.headers.get("origin")
    if not origem or urlparse(origem).netloc != request.headers.get("host", ""):
        raise HTTPException(403, "Origem não permitida.")


def _provedor(nome: str) -> str:
    if nome not in conexoes.PROVEDORES:
        raise HTTPException(404, "Provedor desconhecido.")
    return nome


class ConexaoIn(BaseModel):
    url_base: str | None = Field(None, max_length=300)
    chave: str | None = Field(None, max_length=300)
    modelos: list[str] | None = Field(None, max_length=20)


@app.get("/api/conexoes", dependencies=[Depends(exigir_local)])
def conexoes_listar():
    return {"conexoes": conexoes.publico()}


@app.put("/api/conexoes/{provedor}", dependencies=[Depends(exigir_escrita_segura)])
def conexoes_salvar(provedor: str, c: ConexaoIn):
    try:
        conexoes.salvar(_provedor(provedor), c.url_base, c.chave, c.modelos)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"conexoes": conexoes.publico()}


@app.delete("/api/conexoes/{provedor}", dependencies=[Depends(exigir_escrita_segura)])
def conexoes_remover(provedor: str):
    conexoes.remover(_provedor(provedor))
    return {"conexoes": conexoes.publico()}


@app.post("/api/conexoes/{provedor}/testar", dependencies=[Depends(exigir_escrita_segura)])
def conexoes_testar(provedor: str):
    return conexoes.testar(_provedor(provedor))


@app.get("/api/status")
def status(request: Request):
    disp = modelos_disponiveis()
    remotos = conexoes.modelos_remotos()
    return {
        "ollama": bool(disp),
        "modelo_padrao": MODELO_LLM,
        "modelos": [m for m in MODELOS_PERMITIDOS if m in disp] + remotos,
        "modelos_remotos": remotos,
        "conexoes_editaveis": servidor_local(request),
        "remoto": [{"provedor": c["provedor"], "rotulo": c["rotulo"], "pais": c["pais"], "configurada": c["configurada"]}
                   for c in conexoes.publico()],
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
    # Traços desta instalação + os traços de demonstração versionados no repositório.
    arquivos = sorted(TRACOS_DIR.glob("tracos_*.jsonl"), reverse=True) + [RESULTADOS / "tracos_demo.jsonl"]
    for arq in (a for a in arquivos if a.exists()):
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
    provedor, nome = resolver(modelo)
    if provedor == "ollama":
        if nome not in MODELOS_PERMITIDOS:
            raise HTTPException(400, f"Modelo não permitido: {modelo}")
    elif modelo not in conexoes.modelos_remotos():
        raise HTTPException(400, f"Modelo remoto indisponível: {modelo}. Configure a conexão em Conexões.")

    def gerar():
        if provedor != "ollama":  # o semáforo protege a CPU local; modelo remoto não disputa a máquina
            for ev in responder(p.pergunta, modelo=modelo):
                yield json.dumps(ev, ensure_ascii=False) + "\n"
            return
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
