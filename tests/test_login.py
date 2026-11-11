"""Login com contas individuais na API (CONTAS_DB): allowlist, cookie, admin, limites e vazamento de segredo.

O cliente usa https://testserver porque o cookie de sessão é sempre Secure."""
import json
import os
import subprocess
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, conexoes, contas, main, pipeline
from .conftest import CHAVE, sse, transporte
from .test_api_e_traco import _Indice

ORIGEM = {"Origin": "https://testserver"}
ADMIN, SENHA_ADMIN = "admin", "senha-do-admin-1"
PROF, SENHA_PROF = "prof.ana", "senha-da-ana-1"


@pytest.fixture
def login(tmp_path, monkeypatch):
    db = tmp_path / "contas.db"
    monkeypatch.setattr(contas, "CONTAS_DB", str(db))
    monkeypatch.setattr(main, "_FALHAS_LOGIN", main._Limite(8, 300))
    monkeypatch.setattr(main, "_CADASTROS", main._Limite(5, 3600))
    monkeypatch.setattr(main, "modelos_disponiveis", lambda: [])
    contas.criar_admin(ADMIN, SENHA_ADMIN)
    return db


def cliente(ip="203.0.113.9"):
    return TestClient(main.app, base_url="https://testserver", client=(ip, 50000), follow_redirects=False)


@pytest.fixture
def cli():
    return cliente()


def entrar(c, usuario, senha, headers=ORIGEM):
    return c.post("/api/entrar", json={"usuario": usuario, "senha": senha}, headers=headers)


def cadastrar(c, usuario, senha, confirmacao=None):
    return c.post("/api/cadastrar", json={"usuario": usuario, "senha": senha, "confirmacao": confirmacao or senha}, headers=ORIGEM)


def acao(c, usuario, nome):
    return c.post("/api/ademir/acao", json={"usuario": usuario, "acao": nome}, headers=ORIGEM)


def prof_ativa():
    contas.cadastrar(PROF, SENHA_PROF)
    contas.aprovar(PROF)


# ---------- login desligado (uso local, HF Spaces) ----------
def test_sem_login_tudo_aberto(cli, monkeypatch):
    monkeypatch.setattr(main, "modelos_disponiveis", lambda: [])
    assert cli.get("/").status_code == 200
    s = cli.get("/api/status")
    assert s.status_code == 200 and s.json()["login_ativo"] is False and s.json()["conta"] is None
    assert cli.get("/api/docs").status_code == 200 and cli.get("/openapi.json").status_code == 200
    assert "content-security-policy" not in s.headers  # o HF Spaces mostra a página num iframe
    assert cli.get("/entrar").status_code == 303 and cli.get("/ademir").status_code == 303
    assert entrar(cli, ADMIN, SENHA_ADMIN).status_code == 404


# ---------- login ligado ----------
def test_sem_sessao_so_a_allowlist(login, cli):
    r = cli.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/entrar" and "Assistente" not in r.text
    for pagina in ("/ademir", "/app.js", "/index.html", "/ademir.html", "/entrar.js/../index.html"):
        assert cli.get(pagina).status_code == 303, pagina
    for rota in ("/api/status", "/api/exemplos", "/api/prompt", "/api/avaliacao", "/api/ademir/contas", "/api/traco/79904e4c3f98"):
        r = cli.get(rota)
        assert r.status_code == 401 and r.json()["login_necessario"] is True, rota
    assert cli.post("/api/perguntar", json={"pergunta": "oi"}).status_code == 401
    assert cli.post("/api/sair", json={}, headers=ORIGEM).status_code == 401
    for rota in ("/openapi.json", "/api/docs", "/redoc"):
        assert cli.get(rota).status_code == 404, rota
    assert cli.get("/entrar").status_code == 200 and 'id="form-entrar"' in cli.get("/entrar").text
    assert cli.get("/entrar.js?v=13").status_code == 200 and cli.get("/styles.css?v=13").status_code == 200
    cli.cookies.set(main._COOKIE, "token-inventado")
    assert cli.get("/api/status").status_code == 401


def test_cadastro_fica_pendente_ate_aprovar(login, cli):
    r = cadastrar(cli, "Prof.Ana", SENHA_PROF)
    assert r.status_code == 201 and r.json() == {"ok": True, "usuario": PROF, "estado": "pendente"}
    assert cadastrar(cli, PROF, "outra-senha-1").status_code == 409
    errada = entrar(cli, PROF, "senha-errada-1")
    assert errada.status_code == 401 and errada.json()["detail"] == "Usuário ou senha incorretos."
    assert entrar(cli, "ninguem", "senha-errada-1").json() == errada.json()  # não revela se a conta existe
    r = entrar(cli, PROF, SENHA_PROF)
    assert r.status_code == 403 and "aguardando" in r.json()["detail"] and "set-cookie" not in r.headers

    adm = cliente("198.51.100.1")
    assert entrar(adm, ADMIN, SENHA_ADMIN).status_code == 200
    lista = adm.get("/api/ademir/contas").json()
    assert lista["eu"] == ADMIN and [c["usuario"] for c in lista["contas"]] == [PROF, ADMIN]  # pendentes primeiro
    assert acao(adm, PROF, "aprovar").status_code == 200

    r = entrar(cli, PROF, SENHA_PROF)
    assert r.status_code == 200 and r.json()["conta"] == {"usuario": PROF, "admin": False}
    assert cli.get("/").status_code == 200
    s = cli.get("/api/status").json()
    assert s["login_ativo"] is True and s["conta"] == {"usuario": PROF, "admin": False}
    assert cli.get("/entrar").status_code == 303  # já entrou


def test_cookie_de_sessao_e_sair(login, cli):
    r = entrar(cli, ADMIN, SENHA_ADMIN)
    cookie = r.headers["set-cookie"]
    baixo = cookie.lower()
    assert cookie.startswith(f"{main._COOKIE}=") and "httponly" in baixo and "samesite=strict" in baixo and "secure" in baixo
    assert "path=/" in baixo and "max-age" not in baixo and "expires" not in baixo  # vale até fechar o navegador
    velho = cli.cookies.get(main._COOKIE)
    assert cli.post("/api/sair", json={}, headers=ORIGEM).status_code == 200
    outro = cliente()
    outro.cookies.set(main._COOKIE, velho)
    assert outro.get("/api/status").status_code == 401


def test_quem_nao_e_admin_recebe_403(login, cli):
    prof_ativa()
    entrar(cli, PROF, SENHA_PROF)
    assert cli.get("/api/ademir/contas").status_code == 403
    assert acao(cli, ADMIN, "excluir").status_code == 403
    r = cli.get("/ademir")
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_acoes_de_admin(login, cli):
    prof_ativa()
    prof = cliente("198.51.100.2")
    assert entrar(prof, PROF, SENHA_PROF).status_code == 200
    entrar(cli, ADMIN, SENHA_ADMIN)
    assert cli.get("/ademir").status_code == 200
    for nome in ("rebaixar", "desativar", "excluir"):
        r = acao(cli, ADMIN, nome)
        assert r.status_code == 409 and "último admin" in r.json()["detail"], nome
    assert acao(cli, "ninguem", "aprovar").status_code == 404
    assert acao(cli, PROF, "aprovar").status_code == 409  # já está ativa
    assert acao(cli, PROF, "voar").status_code == 422

    assert acao(cli, PROF, "desativar").status_code == 200
    assert prof.get("/api/status").status_code == 401  # a sessão aberta caiu na hora
    r = entrar(prof, PROF, SENHA_PROF)
    assert r.status_code == 403 and "desativada" in r.json()["detail"]
    assert entrar(prof, PROF, "senha-errada-1").json()["detail"] == "Usuário ou senha incorretos."

    assert acao(cli, PROF, "reativar").status_code == 200
    r = acao(cli, PROF, "redefinir")
    provisoria = r.json()["senha_provisoria"]
    assert entrar(prof, PROF, SENHA_PROF).status_code == 401 and entrar(prof, PROF, provisoria).status_code == 200

    assert acao(cli, PROF, "promover").status_code == 200
    assert prof.get("/api/ademir/contas").status_code == 200  # o papel vem do banco a cada requisição
    assert acao(cli, ADMIN, "rebaixar").status_code == 200  # agora há outro admin
    assert cli.get("/api/ademir/contas").status_code == 403
    assert acao(prof, ADMIN, "excluir").status_code == 200
    assert cli.get("/api/status").status_code == 401


def test_trocar_senha(login, cli):
    prof_ativa()
    entrar(cli, PROF, SENHA_PROF)
    outra_aba = cliente("198.51.100.3")
    entrar(outra_aba, PROF, SENHA_PROF)
    corpo = {"atual": "senha-errada-1", "nova": "senha-nova-123", "confirmacao": "senha-nova-123"}
    assert cli.post("/api/senha", json=corpo, headers=ORIGEM).status_code == 403
    assert cli.post("/api/senha", json={**corpo, "atual": SENHA_PROF, "confirmacao": "outra-coisa-1"}, headers=ORIGEM).status_code == 422
    r = cli.post("/api/senha", json={**corpo, "atual": SENHA_PROF}, headers=ORIGEM)
    assert r.status_code == 200 and main._COOKIE in r.headers["set-cookie"]
    assert cli.get("/api/status").status_code == 200  # esta sessão segue com o cookie novo
    assert outra_aba.get("/api/status").status_code == 401  # as outras caíram
    assert entrar(outra_aba, PROF, "senha-nova-123").status_code == 200


def test_bloqueio_por_tentativas_e_xff_forjado(login, cli):
    def tentar(senha, xff):
        return cli.post("/api/entrar", json={"usuario": ADMIN, "senha": senha}, headers={**ORIGEM, "X-Forwarded-For": xff}).status_code

    for i in range(7):
        assert tentar("senha-errada-1", f"10.0.0.{i}, 198.51.100.7") == 401  # a parte esquerda muda; o IP real não
    assert tentar(SENHA_ADMIN, "10.0.1.1, 198.51.100.7") == 200  # senha certa não conta como falha
    assert tentar("senha-errada-1", "10.0.1.2, 198.51.100.7") == 401  # 8ª falha
    assert tentar(SENHA_ADMIN, "10.9.9.9, 198.51.100.7") == 429  # travado, mesmo com a senha certa
    assert tentar(SENHA_ADMIN, "198.51.100.7, 198.51.100.8") == 200  # outro IP real (o último item, posto pelo Caddy)


def test_limite_de_cadastro(login, cli):
    for _ in range(10):  # erro de digitação não gasta tentativa
        assert cadastrar(cli, PROF, SENHA_PROF, "confirmacao-diferente").status_code == 422
    for i in range(5):
        assert cadastrar(cli, f"prof.{i:02d}", SENHA_PROF).status_code == 201
    assert cadastrar(cli, "prof.extra", SENHA_PROF).status_code == 429
    assert cliente("198.51.100.9").post("/api/cadastrar", json={"usuario": "prof.extra", "senha": SENHA_PROF, "confirmacao": SENHA_PROF},
                                        headers=ORIGEM).status_code == 201


def test_teto_de_pendentes(login, cli, monkeypatch):
    monkeypatch.setattr(contas, "MAX_PENDENTES", 1)
    assert cadastrar(cli, "prof.um", SENHA_PROF).status_code == 201
    r = cadastrar(cli, "prof.dois", SENHA_PROF)
    assert r.status_code == 503 and "aguardando" in r.json()["detail"]


def test_origem_diferente_e_content_type(login, cli):
    corpo = {"usuario": ADMIN, "senha": SENHA_ADMIN}
    assert cli.post("/api/entrar", json=corpo, headers={"Origin": "https://evil.example"}).status_code == 403
    assert cli.post("/api/entrar", json=corpo).status_code == 403  # sem Origin
    assert cli.post("/api/entrar", content=json.dumps(corpo), headers={**ORIGEM, "Content-Type": "text/plain"}).status_code == 415
    assert cli.post("/api/cadastrar", json={**corpo, "confirmacao": SENHA_ADMIN}, headers={"Origin": "https://evil.example"}).status_code == 403
    entrar(cli, ADMIN, SENHA_ADMIN)
    mal = {"Origin": "https://evil.example"}
    assert cli.post("/api/ademir/acao", json={"usuario": ADMIN, "acao": "rebaixar"}, headers=mal).status_code == 403
    assert cli.post("/api/sair", json={}, headers=mal).status_code == 403
    assert cli.post("/api/senha", json={"atual": SENHA_ADMIN, "nova": "x" * 10, "confirmacao": "x" * 10}, headers=mal).status_code == 403
    assert cli.get("/api/status").json()["conta"] == {"usuario": ADMIN, "admin": True}  # nada mudou


def test_traco_ao_vivo_nao_sai_com_login(login, cli, tmp_path, monkeypatch):
    pasta = tmp_path / "tracos_vivos"
    pasta.mkdir()
    (pasta / "tracos_2026-11-11.jsonl").write_text(json.dumps({"id": "abc123def456", "pergunta": "pergunta de outra pessoa",
                                                               "desfecho": "respondida", "resposta": "x"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "TRACOS_DIR", pasta)
    entrar(cli, ADMIN, SENHA_ADMIN)
    r = cli.get("/api/traco/abc123def456")
    assert r.status_code == 404 and "outra pessoa" not in r.text
    assert cli.get("/api/traco/79904e4c3f98").status_code == 200  # traço de demonstração versionado
    monkeypatch.setattr(contas, "CONTAS_DB", "")
    assert cli.get("/api/traco/abc123def456").status_code == 200  # sem login, como antes


def test_422_nao_ecoa_o_que_chegou(login, cli):
    segredo = "segredo-" + "x" * 300
    r = cli.post("/api/entrar", json={"usuario": ADMIN, "senha": segredo}, headers=ORIGEM)
    assert r.status_code == 422 and "segredo" not in r.text and r.json()["detail"][0]["loc"] == ["body", "senha"]
    r = cli.post("/api/entrar", content=b'{"senha": "segredo-quebrado', headers={**ORIGEM, "Content-Type": "application/json"})
    assert r.status_code == 422 and "segredo" not in r.text


def test_422_nao_ecoa_chave_de_conexao(monkeypatch):
    local = TestClient(main.app, client=("127.0.0.1", 50000))
    chave_longa = "sk-" + "y" * 400
    r = local.put("/api/conexoes/deepseek", json={"chave": chave_longa}, headers={"Origin": "http://testserver"})
    assert r.status_code == 422 and chave_longa not in r.text and "yyyy" not in r.text


def _rodar(codigo, **env):
    ambiente = {k: v for k, v in os.environ.items() if k not in ("ACESSO_SENHA", "CONTAS_DB")} | env
    return subprocess.run([sys.executable, "-c", codigo], cwd=config.RAIZ, env=ambiente, capture_output=True, text=True, timeout=120)


def test_acesso_senha_no_ambiente_impede_o_servidor_de_subir():
    r = _rodar("import app.main", ACESSO_SENHA="senha-antiga")
    assert r.returncode == 1 and "ACESSO_SENHA" in r.stderr and "CONTAS_DB" in r.stderr


def test_com_contas_db_a_documentacao_nem_existe(tmp_path):
    r = _rodar("from app.main import app; assert app.openapi_url is None and app.docs_url is None and app.redoc_url is None",
               CONTAS_DB=str(tmp_path / "c.db"))
    assert r.returncode == 0, r.stderr


def test_deploy_nao_expoe_ollama_nem_versao():
    docker = (config.RAIZ / "Dockerfile").read_text(encoding="utf-8")
    assert [l for l in docker.splitlines() if l.startswith("EXPOSE")] == ["EXPOSE 7860"]
    assert "--no-server-header" in (config.RAIZ / "start.sh").read_text(encoding="utf-8")


# ---------- vazamento por requisição ----------
def test_nenhuma_resposta_vaza_segredo(login, monkeypatch):
    """Percorre o fluxo inteiro (cadastrar, entrar, perguntar, admin, redefinir, trocar senha, sair) e confere
    cada resposta e cada URL: nenhum segredo sai, exceto a senha provisória na resposta do reset."""
    monkeypatch.setattr(conexoes, "CHAVE_DO_USUARIO", True)
    monkeypatch.setattr(main, "CHAVE_DO_USUARIO", True)
    monkeypatch.setattr(pipeline, "carregar", lambda exp: _Indice())
    vistas = transporte(lambda r: httpx.Response(200, content=sse("Use rimas [1].", usage={"prompt_tokens": 5, "completion_tokens": 3})))

    respostas: list[httpx.Response] = []

    def guardar(r):
        r.read()
        respostas.append(r)

    prof, adm = cliente("203.0.113.9"), cliente("198.51.100.1")
    for c in (prof, adm):
        c.event_hooks = {"response": [guardar]}
    NOVA_PROF = "senha-nova-da-ana-2"

    prof.get("/"), prof.get("/entrar"), prof.get("/entrar.js?v=13"), prof.get("/styles.css?v=13")
    assert cadastrar(prof, PROF, SENHA_PROF).status_code == 201
    assert entrar(prof, PROF, SENHA_PROF).status_code == 403
    assert entrar(adm, ADMIN, SENHA_ADMIN).status_code == 200
    adm.get("/ademir"), adm.get("/ademir.js?v=13")
    lista = adm.get("/api/ademir/contas").json()["contas"]
    assert all(set(c) == {"usuario", "estado", "admin", "criada_em", "ultimo_acesso"} for c in lista)
    assert acao(adm, PROF, "aprovar").status_code == 200
    assert entrar(prof, PROF, SENHA_PROF).status_code == 200
    for rota in ("/", "/app.js?v=13", "/api/status", "/api/exemplos", "/api/prompt", "/api/avaliacao", "/api/traco/79904e4c3f98"):
        assert prof.get(rota).status_code == 200, rota
    r = prof.post("/api/perguntar", json={"pergunta": "Como ensinar consciência fonológica?", "modelo": "deepseek:deepseek-flash"},
                  headers={"X-Chave-Remoto": CHAVE})
    assert r.status_code == 200 and '"respondida"' in r.text
    assert prof.post("/api/senha", json={"atual": SENHA_PROF, "nova": NOVA_PROF, "confirmacao": NOVA_PROF}, headers=ORIGEM).status_code == 200
    reset = acao(adm, PROF, "redefinir")
    provisoria = reset.json()["senha_provisoria"]
    assert entrar(prof, PROF, provisoria).status_code == 200
    assert prof.post("/api/sair", json={}, headers=ORIGEM).status_code == 200
    assert prof.get("/").status_code == 303
    assert adm.post("/api/sair", json={}, headers=ORIGEM).status_code == 200

    tokens = [v.split(";")[0].split("=", 1)[1] for r in respostas for k, v in r.headers.multi_items()
              if k == "set-cookie" and v.startswith(main._COOKIE + "=") and "Max-Age=0" not in v]
    assert len(tokens) == 4 and all(len(t) >= 40 for t in tokens)  # admin, prof, troca de senha, prof com a provisória
    segredos = [SENHA_ADMIN, SENHA_PROF, NOVA_PROF, CHAVE, "scrypt$", *tokens]
    for r in respostas:
        rotulo = f"{r.request.method} {r.request.url.path} -> {r.status_code}"
        assert r.headers.get("cache-control") == "no-store", rotulo
        assert r.headers.get("content-security-policy") == main._CSP, rotulo
        assert r.headers.get("x-content-type-options") == "nosniff" and r.headers.get("referrer-policy") == "no-referrer", rotulo
        cabecalhos = "\n".join(f"{k}: {v}" for k, v in r.headers.multi_items() if k != "set-cookie")
        for s in segredos:
            assert s not in r.text and s not in cabecalhos, f"{rotulo}: vazou {s[:6]}…"
            assert s not in str(r.request.url), f"{rotulo}: segredo na URL"
        if r is not reset:
            assert provisoria not in r.text and provisoria not in cabecalhos, rotulo
        assert provisoria not in str(r.request.url)

    # nada da pessoa no traço gravado nem no que foi ao provedor remoto
    gravado = "".join(p.read_text(encoding="utf-8") for p in pipeline.TRACOS_DIR.glob("tracos_*.jsonl"))
    assert gravado and PROF not in gravado and CHAVE not in gravado
    enviado = vistas[0].content.decode() + str(dict(vistas[0].headers))
    assert PROF not in enviado and "203.0.113.9" not in enviado and SENHA_PROF not in enviado
