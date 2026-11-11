"""API + front-end estático. Um processo só: serve /api e a página do chat."""
from __future__ import annotations

import csv
import json
import threading
import time
from typing import Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import conexoes, contas
from .config import (CHAVE_DO_USUARIO, CONDICAO, CONDICOES, CONEXOES_LOCAL, CONTAS_DB, EXPERIMENTO, EXPERIMENTOS, LIMIAR_COBERTURA,
                     MODELO_EMBED, MODELO_LLM, MODELOS_PERMITIDOS, ORCAMENTO_CONTEXTO, RAIZ)
from .llm import modelos_disponiveis, resolver
from .pipeline import ROTULOS, responder
from .prompts import PROMPT_SISTEMA, VERSAO_PROMPT

# Com login (CONTAS_DB), a documentação da API nem é publicada; o middleware ainda responde 404 a esses caminhos.
app = FastAPI(title="AlfaRAG — assistente de alfabetização", docs_url=None if CONTAS_DB else "/api/docs",
              redoc_url=None if CONTAS_DB else "/redoc", openapi_url=None if CONTAS_DB else "/openapi.json")
WEB = RAIZ / "web"
RESULTADOS = RAIZ / "resultados"

# Harness de infraestrutura: em CPU só uma geração por vez; as demais esperam até 120 s.
_GERACAO = threading.Semaphore(1)


class Pergunta(BaseModel):
    pergunta: str = Field(..., max_length=4000)
    modelo: str | None = None


# ---------- Contas individuais (servidor aberto na web, CONTAS_DB) ----------
_COOKIE = "alfarag_sessao"
_PUBLICAS = {"/entrar", "/entrar.js", "/styles.css", "/api/entrar", "/api/cadastrar"}  # abrem sem sessão
_DOCS = {"/openapi.json", "/api/docs", "/api/docs/oauth2-redirect", "/redoc"}
_CSP = "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"


class _Limite:
    """Janela deslizante por chave, na memória do processo: no máximo `maximo` eventos a cada `janela_s` segundos."""

    def __init__(self, maximo: int, janela_s: float):
        self.maximo, self.janela_s = maximo, janela_s
        self._eventos: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def consumir(self, chave: str) -> bool:
        """Reserva um evento antes do trabalho caro (hash). False se a chave já atingiu o limite."""
        agora = time.time()
        with self._lock:
            if len(self._eventos) > 10_000:  # poda chaves paradas
                self._eventos = {k: v for k, v in self._eventos.items() if v and agora - v[-1] < self.janela_s}
            recentes = [t for t in self._eventos.get(chave, []) if agora - t < self.janela_s]
            if len(recentes) >= self.maximo:
                self._eventos[chave] = recentes
                return False
            self._eventos[chave] = recentes + [agora]
            return True

    def devolver(self, chave: str) -> None:
        """Desfaz uma reserva: a senha estava certa, então a tentativa não conta como falha."""
        with self._lock:
            if self._eventos.get(chave):
                self._eventos[chave].pop()


_FALHAS_LOGIN = _Limite(8, 300)  # senha errada (login ou troca de senha), por IP
_CADASTROS = _Limite(5, 3600)  # tentativas de cadastro, por IP


def ip_cliente(request: Request) -> str:
    """Atrás do Caddy, o IP real é o ÚLTIMO item do X-Forwarded-For (o que o próprio Caddy põe). Os itens à esquerda
    vêm do cliente e podem ser forjados para furar o bloqueio por tentativas."""
    ultimo = ",".join(request.headers.getlist("x-forwarded-for")).split(",")[-1].strip()
    return ultimo or (request.client.host if request.client else "?")


@app.middleware("http")
async def exigir_sessao(request: Request, call_next):
    """Com login ativo, só a allowlist (_PUBLICAS) abre sem sessão: /api/* recebe 401 e as páginas vão para /entrar.
    A conta da sessão fica em request.state.conta ({usuario, admin} ou None)."""
    request.state.conta = None
    if not contas.ativo():
        return await call_next(request)
    caminho = request.url.path
    if caminho in _DOCS:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    request.state.conta = contas.conta_da_sessao(request.cookies.get(_COOKIE))
    if request.state.conta is None and caminho not in _PUBLICAS:
        if caminho.startswith("/api/"):
            return JSONResponse({"detail": "Entre com a sua conta para continuar.", "login_necessario": True}, status_code=401)
        return RedirectResponse("/entrar", status_code=303)
    return await call_next(request)


@app.middleware("http")
async def cabecalhos_seguros(request: Request, call_next):
    """Com login ativo: CSP sem script nem estilo inline, nada em cache (nem no bfcache depois do Sair) e sem Referer.
    Registrado depois de exigir_sessao, envolve também os 401/303 que ele devolve."""
    resposta = await call_next(request)
    if contas.ativo():
        resposta.headers["Content-Security-Policy"] = _CSP
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["Referrer-Policy"] = "no-referrer"
        resposta.headers["Cache-Control"] = "no-store"
    return resposta


@app.exception_handler(RequestValidationError)
async def erro_de_validacao(request: Request, exc: RequestValidationError):
    """O 422 padrão do Pydantic devolve o `input` recebido, que pode ser uma senha ou uma chave: saem só tipo, local e motivo."""
    return JSONResponse({"detail": [{k: e[k] for k in ("type", "loc", "msg") if k in e} for e in exc.errors()]}, status_code=422)


_STATUS_CONTA = {contas.Invalido: 422, contas.Conflito: 409, contas.NaoEncontrada: 404, contas.Ocupado: 503}


@app.exception_handler(contas.ErroConta)
async def erro_de_conta(request: Request, exc: contas.ErroConta):
    return JSONResponse({"detail": str(exc)}, status_code=_STATUS_CONTA.get(type(exc), 400))


def exigir_login_ativo() -> None:
    if not contas.ativo():
        raise HTTPException(404, "Login não configurado neste servidor.")


def exigir_mesma_origem(request: Request) -> None:
    """Contra CSRF de outra página aberta no navegador: JSON explícito e Origin igual ao Host."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "Use Content-Type: application/json.")
    origem = request.headers.get("origin")
    if not origem or urlparse(origem).netloc != request.headers.get("host", ""):
        raise HTTPException(403, "Origem não permitida.")


def exigir_admin(request: Request) -> None:
    conta = request.state.conta
    if not conta or not conta["admin"]:
        raise HTTPException(403, "Só para admin.")


class Credenciais(BaseModel):
    usuario: str = Field(..., max_length=64)
    senha: str = Field(..., max_length=contas.SENHA_MAX)


class Cadastro(Credenciais):
    confirmacao: str = Field(..., max_length=contas.SENHA_MAX)


class TrocaSenha(BaseModel):
    atual: str = Field(..., max_length=contas.SENHA_MAX)
    nova: str = Field(..., max_length=contas.SENHA_MAX)
    confirmacao: str = Field(..., max_length=contas.SENHA_MAX)


class AcaoAdmin(BaseModel):
    usuario: str = Field(..., max_length=64)
    acao: Literal["aprovar", "recusar", "desativar", "reativar", "redefinir", "promover", "rebaixar", "excluir"]


def _abrir_cookie(request: Request, response: Response, usuario: str) -> None:
    """Sem max_age/expires: o cookie vale até o navegador fechar. Secure sempre (o navegador também aceita em localhost)."""
    contas.encerrar_sessao(request.cookies.get(_COOKIE))  # não deixa a sessão anterior viva
    response.set_cookie(_COOKIE, contas.abrir_sessao(usuario), httponly=True, samesite="strict", secure=True, path="/")


_CONTA = [Depends(exigir_login_ativo), Depends(exigir_mesma_origem)]


@app.post("/api/entrar", dependencies=_CONTA)
def entrar(c: Credenciais, request: Request, response: Response):
    ip = ip_cliente(request)
    if not _FALHAS_LOGIN.consumir(ip):  # antes do hash
        raise HTTPException(429, "Tentativas demais. Espere alguns minutos.")
    conta = contas.autenticar(c.usuario, c.senha)
    if conta is None:
        raise HTTPException(401, "Usuário ou senha incorretos.")
    _FALHAS_LOGIN.devolver(ip)
    # O estado da conta só aparece para quem acertou a senha.
    if conta["estado"] == "pendente":
        raise HTTPException(403, "Cadastro aguardando liberação. Avise o admin.")
    if conta["estado"] == "desativada":
        raise HTTPException(403, "Conta desativada. Fale com o admin.")
    _abrir_cookie(request, response, conta["usuario"])
    return {"ok": True, "conta": {"usuario": conta["usuario"], "admin": conta["admin"]}}


@app.post("/api/cadastrar", status_code=201, dependencies=_CONTA)
def cadastrar(c: Cadastro, request: Request):
    usuario = contas.validar_usuario(c.usuario)
    contas.validar_senha(c.senha)
    if c.senha != c.confirmacao:
        raise HTTPException(422, "As senhas não conferem.")
    if not _CADASTROS.consumir(ip_cliente(request)):  # erro de digitação acima não gasta tentativa
        raise HTTPException(429, "Cadastros demais a partir deste endereço. Tente mais tarde.")
    contas.cadastrar(usuario, c.senha)
    return {"ok": True, "usuario": usuario, "estado": "pendente"}


@app.post("/api/sair", dependencies=_CONTA)
def sair(request: Request, response: Response):
    contas.encerrar_sessao(request.cookies.get(_COOKIE))
    response.delete_cookie(_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return {"ok": True}


@app.post("/api/senha", dependencies=_CONTA)
def trocar_senha(t: TrocaSenha, request: Request, response: Response):
    contas.validar_senha(t.nova)
    if t.nova != t.confirmacao:
        raise HTTPException(422, "As senhas novas não conferem.")
    ip = ip_cliente(request)
    if not _FALHAS_LOGIN.consumir(ip):
        raise HTTPException(429, "Tentativas demais. Espere alguns minutos.")
    usuario = request.state.conta["usuario"]
    if not contas.trocar_senha(usuario, t.atual, t.nova):
        raise HTTPException(403, "Senha atual incorreta.")
    _FALHAS_LOGIN.devolver(ip)
    _abrir_cookie(request, response, usuario)  # a troca derrubou todas as sessões da conta; esta segue com cookie novo
    return {"ok": True}


@app.get("/api/ademir/contas", dependencies=[Depends(exigir_login_ativo), Depends(exigir_admin)])
def ademir_contas(request: Request):
    return {"contas": contas.listar(), "eu": request.state.conta["usuario"]}


_ACOES = {"aprovar": contas.aprovar, "recusar": contas.recusar, "desativar": contas.desativar, "reativar": contas.reativar,
          "excluir": contas.excluir, "promover": lambda u: contas.definir_admin(u, True),
          "rebaixar": lambda u: contas.definir_admin(u, False)}


@app.post("/api/ademir/acao", dependencies=[Depends(exigir_login_ativo), Depends(exigir_admin), Depends(exigir_mesma_origem)])
def ademir_acao(a: AcaoAdmin, request: Request):
    """O usuário-alvo vai no corpo, não no caminho: o access log do uvicorn grava o caminho."""
    extra = {}
    if a.acao == "redefinir":
        extra["senha_provisoria"] = contas.redefinir_senha(a.usuario)  # só nesta resposta (no-store), nunca em log
    else:
        _ACOES[a.acao](a.usuario)
    return {**extra, "contas": contas.listar(), "eu": request.state.conta["usuario"]}


def chave_do_cabecalho(x_chave_remoto: str | None = Header(None)) -> str | None:
    """Chave do usuário (modo CHAVE_DO_USUARIO). Só vive nesta requisição: não é gravada, logada nem posta no traço."""
    if x_chave_remoto is None:
        return None
    k = x_chave_remoto.strip()
    if not conexoes.chave_valida(k):
        raise HTTPException(400, "Chave inválida no cabeçalho X-Chave-Remoto.")
    return k


_PROXY_HDRS = ("x-forwarded-for", "forwarded", "x-real-ip", "x-forwarded-host")


def servidor_local(request: Request) -> bool:
    """A tela de Conexões só vale quando o servidor é do próprio usuário: cliente loopback e sem proxy na frente,
    ou CONEXOES_LOCAL=1 (docker run -p, onde o cliente chega como IP da ponte)."""
    if CHAVE_DO_USUARIO:  # servidor compartilhado: ninguém grava chave no servidor
        return False
    if CONEXOES_LOCAL:
        return True
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1") and not any(h in request.headers for h in _PROXY_HDRS)


def exigir_local(request: Request) -> None:
    if not servidor_local(request):
        raise HTTPException(403, "Conexões só podem ser configuradas no servidor local.")


def exigir_escrita_segura(request: Request) -> None:
    exigir_local(request)
    exigir_mesma_origem(request)


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


@app.post("/api/remoto/{provedor}/testar")
def remoto_testar(provedor: str, chave: str | None = Depends(chave_do_cabecalho)):
    """Testa a chave do próprio usuário (cabeçalho). Usa sempre a URL padrão do provedor, nunca uma enviada pelo cliente."""
    if not CHAVE_DO_USUARIO:
        raise HTTPException(404, "Disponível só no modo de chave por usuário.")
    return conexoes.testar(_provedor(provedor), chave_usuario=chave)


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
        "chave_do_usuario": CHAVE_DO_USUARIO,
        "login_ativo": contas.ativo(),
        "conta": request.state.conta,
        "remoto": [{"provedor": c["provedor"], "rotulo": c["rotulo"], "pais": c["pais"], "configurada": c["configurada"] or CHAVE_DO_USUARIO}
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
    # Traços de demonstração versionados no repositório. Sem login, também os desta instalação. Com login, só os de
    # demonstração: o traço ao vivo traz a pergunta de outra pessoa e o id não é segredo.
    arquivos = [RESULTADOS / "tracos_demo.jsonl"]
    if not contas.ativo():
        arquivos = sorted(TRACOS_DIR.glob("tracos_*.jsonl"), reverse=True) + arquivos
    for arq in (a for a in arquivos if a.exists()):
        for linha in arq.open(encoding="utf-8"):
            if f'"id": "{tid}"' in linha:
                t = json.loads(linha)
                return {"pergunta": t["pergunta"], "janela": t.get("janela"),
                        "final": {"tipo": "final", "desfecho": t["desfecho"], "resposta": t["resposta"],
                                  "verificacao": t.get("verificacao"), "traco": t}}
    raise HTTPException(404, "traço não encontrado")


@app.post("/api/perguntar")
def perguntar(p: Pergunta, chave: str | None = Depends(chave_do_cabecalho)):
    modelo = p.modelo or MODELO_LLM
    provedor, nome = resolver(modelo)
    if provedor == "ollama":
        if nome not in MODELOS_PERMITIDOS:
            raise HTTPException(400, f"Modelo não permitido: {modelo}")
    elif modelo not in conexoes.modelos_remotos():
        raise HTTPException(400, f"Modelo remoto indisponível: {modelo}. Configure a conexão em Conexões.")
    elif CHAVE_DO_USUARIO and not chave:
        raise HTTPException(400, "Informe a sua chave em Conexões para usar o modelo remoto.")
    if provedor == "ollama":
        chave = None  # modelo local não usa chave

    def gerar():
        if provedor != "ollama":  # o semáforo protege a CPU local; modelo remoto não disputa a máquina
            for ev in responder(p.pergunta, modelo=modelo, chave=chave):
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


@app.get("/entrar")
def pagina_entrar(request: Request):
    if not contas.ativo() or request.state.conta:
        return RedirectResponse("/", status_code=303)
    return FileResponse(WEB / "entrar.html")


@app.get("/ademir")
def pagina_ademir(request: Request):
    conta = request.state.conta
    if not conta or not conta["admin"]:
        return RedirectResponse("/", status_code=303)
    return FileResponse(WEB / "ademir.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
