"""Servidor compartilhado: chave por usuário (CHAVE_DO_USUARIO) e senha de acesso (ACESSO_SENHA)."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import conexoes, main, pipeline
from .conftest import sse, transporte
from .test_api_e_traco import _Indice

CHAVE_A = "sk-colega-A-0123456789"
CHAVE_SERVIDOR = "sk-do-servidor-9876543210"


@pytest.fixture
def byok(monkeypatch):
    monkeypatch.setattr(conexoes, "CHAVE_DO_USUARIO", True)
    monkeypatch.setattr(main, "CHAVE_DO_USUARIO", True)
    monkeypatch.setattr(main, "modelos_disponiveis", lambda: ["qwen3.5:4b-q4_K_M"])
    monkeypatch.setattr(pipeline, "carregar", lambda exp: _Indice())


@pytest.fixture
def cli():
    return TestClient(main.app, client=("203.0.113.9", 50000))


def perguntar(cli, chave=None, modelo="deepseek:deepseek-flash"):
    h = {"X-Chave-Remoto": chave} if chave else {}
    return cli.post("/api/perguntar", json={"pergunta": "Como ensinar consciência fonológica?", "modelo": modelo}, headers=h)


def test_status_lista_remotos_sem_chave_no_servidor(byok, cli):
    s = cli.get("/api/status").json()
    assert s["chave_do_usuario"] is True and "deepseek:deepseek-flash" in s["modelos_remotos"]
    assert s["conexoes_editaveis"] is False  # ninguém grava chave no servidor compartilhado


def test_pergunta_exige_chave_do_usuario(byok, cli):
    r = perguntar(cli)
    assert r.status_code == 400 and "sua chave" in r.json()["detail"]
    assert perguntar(cli, "curta").status_code == 400  # chave malformada


def test_usa_a_chave_do_usuario_e_ignora_a_do_servidor(byok, cli, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", CHAVE_SERVIDOR)
    conexoes.salvar("deepseek", nova_chave=CHAVE_SERVIDOR)  # arquivo também existe, mas deve ser ignorado
    vistas = transporte(lambda r: httpx.Response(200, content=sse("Use rimas [1].", usage={"prompt_tokens": 5, "completion_tokens": 3})))
    r = perguntar(cli, CHAVE_A)
    assert r.status_code == 200
    assert vistas[0].headers["authorization"] == f"Bearer {CHAVE_A}"
    final = [json.loads(l) for l in r.text.splitlines() if l][-1]
    assert final["desfecho"] == "respondida"
    # a chave não aparece na resposta, no traço gravado nem no status
    gravado = "".join(p.read_text(encoding="utf-8") for p in pipeline.TRACOS_DIR.glob("tracos_*.jsonl"))
    assert CHAVE_A not in r.text and CHAVE_A not in gravado and CHAVE_A not in cli.get("/api/status").text


def test_chave_errada_vira_erro_sem_vazar(byok, cli):
    transporte(lambda r: httpx.Response(401, json={"error": CHAVE_A}))
    r = perguntar(cli, CHAVE_A)
    assert CHAVE_A not in r.text and "401" in r.text
    gravado = "".join(p.read_text(encoding="utf-8") for p in pipeline.TRACOS_DIR.glob("tracos_*.jsonl"))
    assert CHAVE_A not in gravado


def test_servidor_sem_chave_propria_nao_cai_no_fallback(byok, cli, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", CHAVE_SERVIDOR)
    assert conexoes.chave("deepseek") == ""
    with pytest.raises(conexoes.ErroConexao):
        conexoes.cabecalhos("deepseek")


def test_testar_chave_do_usuario(byok, cli):
    vistas = []

    def ok(r):
        vistas.append(r)
        return httpx.Response(200, json={"data": [{"id": "deepseek-flash"}]})

    real = httpx.Client
    monkey = pytest.MonkeyPatch()
    monkey.setattr(conexoes.httpx, "Client", lambda **k: real(transport=httpx.MockTransport(ok)))
    try:
        r = cli.post("/api/remoto/deepseek/testar", headers={"X-Chave-Remoto": CHAVE_A})
    finally:
        monkey.undo()
    assert r.json()["ok"] is True and vistas[0].headers["authorization"] == f"Bearer {CHAVE_A}"
    assert str(vistas[0].url) == "https://api.deepseek.com/models"
    assert cli.post("/api/remoto/deepseek/testar").json()["ok"] is False  # sem chave


def test_testar_do_usuario_nao_existe_fora_do_modo(cli):
    assert cli.post("/api/remoto/deepseek/testar", headers={"X-Chave-Remoto": CHAVE_A}).status_code == 404


# ---------- senha de acesso ----------
@pytest.fixture
def com_senha(monkeypatch):
    monkeypatch.setattr(main, "ACESSO_SENHA", "senha-do-grupo")
    monkeypatch.setattr(main, "_FALHAS", {})
    monkeypatch.setattr(main, "modelos_disponiveis", lambda: [])


def test_api_bloqueada_sem_senha(com_senha, cli):
    for rota in ("/api/status", "/api/exemplos", "/api/prompt", "/api/avaliacao"):
        r = cli.get(rota)
        assert r.status_code == 401 and r.json()["acesso_necessario"] is True
    assert cli.post("/api/perguntar", json={"pergunta": "oi"}).status_code == 401
    assert cli.get("/").status_code == 200  # a página abre e mostra o pedido de senha


def test_entrar_com_senha_certa_libera(com_senha, cli):
    r = cli.post("/api/entrar", json={"senha": "senha-do-grupo"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    assert "senha-do-grupo" not in r.headers["set-cookie"]
    assert cli.get("/api/status").status_code == 200


def test_cookie_falso_nao_passa(com_senha, cli):
    assert cli.get("/api/status", cookies={"alfarag_acesso": "qualquer"}).status_code == 401


def test_senha_errada_e_bloqueio_por_tentativas(com_senha, cli):
    for _ in range(8):
        assert cli.post("/api/entrar", json={"senha": "errada"}).status_code == 401
    assert cli.post("/api/entrar", json={"senha": "senha-do-grupo"}).status_code == 429  # travado até a janela passar


def test_sem_senha_configurada_tudo_aberto(cli, monkeypatch):
    monkeypatch.setattr(main, "modelos_disponiveis", lambda: [])
    assert cli.get("/api/status").status_code == 200
    assert cli.get("/api/status").json()["acesso_protegido"] is False
