import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import conexoes, llm, main, pipeline
from .conftest import CHAVE, sse, transporte

LOCAL = {"Origin": "http://testserver", "Content-Type": "application/json"}


@pytest.fixture
def local():
    return TestClient(main.app, client=("127.0.0.1", 50000))


@pytest.fixture
def remoto():
    return TestClient(main.app, client=("203.0.113.9", 50000))


def test_escrita_recusada_fora_do_local(remoto):
    r = remoto.put("/api/conexoes/deepseek", json={"chave": CHAVE}, headers=LOCAL)
    assert r.status_code == 403 and not conexoes.configurada("deepseek")
    assert remoto.get("/api/conexoes").status_code == 403
    assert remoto.delete("/api/conexoes/deepseek", headers=LOCAL).status_code == 403
    assert remoto.post("/api/conexoes/deepseek/testar", headers=LOCAL).status_code == 403


def test_proxy_na_frente_conta_como_publico(local):
    r = local.put("/api/conexoes/deepseek", json={"chave": CHAVE}, headers={**LOCAL, "X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 403


def test_conexoes_local_env_libera_ip_da_ponte(remoto, monkeypatch):
    monkeypatch.setattr(main, "CONEXOES_LOCAL", True)
    assert remoto.put("/api/conexoes/deepseek", json={"chave": CHAVE}, headers=LOCAL).status_code == 200


def test_csrf_origin_e_content_type(local):
    assert local.put("/api/conexoes/deepseek", json={"chave": CHAVE}, headers={"Origin": "http://evil.example"}).status_code == 403
    assert local.put("/api/conexoes/deepseek", json={"chave": CHAVE}).status_code == 403  # sem Origin
    r = local.put("/api/conexoes/deepseek", content=json.dumps({"chave": CHAVE}), headers={"Origin": "http://testserver", "Content-Type": "text/plain"})
    assert r.status_code == 415
    assert not conexoes.configurada("deepseek")


def test_salvar_nunca_devolve_a_chave(local):
    r = local.put("/api/conexoes/deepseek", json={"chave": CHAVE}, headers=LOCAL)
    assert r.status_code == 200 and CHAVE not in r.text
    assert CHAVE not in local.get("/api/conexoes").text
    assert local.put("/api/conexoes/deepseek", json={"chave": "x y"}, headers=LOCAL).status_code == 422
    assert local.put("/api/conexoes/inexistente", json={}, headers=LOCAL).status_code == 404
    assert local.delete("/api/conexoes/deepseek", headers=LOCAL).json()["conexoes"][0]["configurada"] is False


def test_status_sem_chave_e_modelos_remotos(local, monkeypatch):
    monkeypatch.setattr(main, "modelos_disponiveis", lambda: ["qwen3.5:4b-q4_K_M"])
    s = local.get("/api/status").json()
    assert not any("deepseek" in m for m in s["modelos"]) and s["remoto"][0]["configurada"] is False
    conexoes.salvar("deepseek", nova_chave=CHAVE)
    s = local.get("/api/status")
    assert CHAVE not in s.text and conexoes.mascarar(CHAVE) not in s.text
    assert "deepseek:deepseek-flash" in s.json()["modelos"] and s.json()["conexoes_editaveis"] is True


def test_status_publico_nao_edita(remoto, monkeypatch):
    monkeypatch.setattr(main, "modelos_disponiveis", lambda: [])
    assert remoto.get("/api/status").json()["conexoes_editaveis"] is False


def test_perguntar_valida_modelo(local):
    assert local.post("/api/perguntar", json={"pergunta": "oi", "modelo": "deepseek:deepseek-flash"}).status_code == 400  # sem chave
    conexoes.salvar("deepseek", nova_chave=CHAVE)
    assert local.post("/api/perguntar", json={"pergunta": "oi", "modelo": "deepseek:outro"}).status_code == 400
    assert local.post("/api/perguntar", json={"pergunta": "oi", "modelo": "modelo-que-nao-existe"}).status_code == 400


class _Indice:
    def buscar(self, pergunta, docs, **kw):
        if "BNCC" not in docs:  # busca no grupo de experiências: nenhum relato
            return []
        return [{"id": "c1", "doc": "BNCC", "texto": "A consciência fonológica é habilidade de base.", "tokens": 12, "secao": "",
                 "pagina_ini": 3, "pagina_fim": 3, "cos": 0.9, "rrf": 0.03, "bm25": 5.0, "rank_denso": 1, "rank_bm25": 1,
                 "codigos_bncc": []}]


@pytest.fixture
def pipeline_falso(monkeypatch):
    monkeypatch.setattr(pipeline, "carregar", lambda exp: _Indice())


def _final(modelo):
    return [e for e in pipeline.responder("Como ensinar consciência fonológica?", modelo=modelo) if e["tipo"] == "final"][0]


def test_traco_remoto_sem_chave(com_chave, pipeline_falso):
    transporte(lambda r: httpx.Response(200, content=sse("Use rimas [1].", usage={"prompt_tokens": 300, "completion_tokens": 9}, finish="length")))
    f = _final("deepseek:deepseek-flash")
    t = f["traco"]
    assert f["desfecho"] == "respondida" and t["provedor"] == "deepseek" and t["modelo_id"] == "deepseek-flash"
    assert t["reprodutivel"] is False and "ollama" not in t and t["remoto"]["resposta_tokens"] == 9
    assert t["modelo_digest"] is None and t["verificacao"]["truncada"] is True and t["verificacao"]["citacoes_validas"] == [1]
    gravado = "".join(p.read_text(encoding="utf-8") for p in pipeline.TRACOS_DIR.glob("tracos_*.jsonl"))
    assert gravado and CHAVE not in gravado and "Bearer" not in gravado


def test_erro_remoto_vira_desfecho_erro_sem_fallback(com_chave, pipeline_falso, monkeypatch):
    chamadas = []
    monkeypatch.setattr(llm, "_ollama_stream", lambda *a, **k: chamadas.append(a) or iter(()))
    transporte(lambda r: httpx.Response(402, json={"error": CHAVE}))
    f = _final("deepseek:deepseek-flash")
    assert f["desfecho"] == "erro" and "Saldo insuficiente" in f["resposta"] and "remoto" in f["resposta"]
    assert chamadas == []  # nada de fallback para o Ollama
    saida = json.dumps(f)
    assert CHAVE not in saida


def test_traco_local_mantem_formato(pipeline_falso, monkeypatch):
    monkeypatch.setattr(llm, "digest", lambda m: "abc123")
    monkeypatch.setattr(pipeline, "digest", lambda m: "abc123")
    fim = {"prompt_tokens": 1, "resposta_tokens": 2, "duracao_s": 1, "tok_s": 2, "done_reason": "stop"}
    monkeypatch.setattr(pipeline, "chat_stream", lambda *a, **k: iter([{"delta": "Rimas [1]."}, {"fim": fim}]))
    t = _final("qwen3.5:4b-q4_K_M")["traco"]
    assert t["provedor"] == "ollama" and t["reprodutivel"] is True and t["ollama"] == fim and "remoto" not in t
    assert t["modelo"] == "qwen3.5:4b-q4_K_M"


def test_semaforo_so_para_ollama(local, com_chave, monkeypatch):
    class Preso:
        def acquire(self, timeout=None):
            raise AssertionError("modelo remoto não deve usar o semáforo")
        def release(self):
            raise AssertionError
    monkeypatch.setattr(main, "_GERACAO", Preso())
    monkeypatch.setattr(main, "responder", lambda *a, **k: iter([{"tipo": "final", "desfecho": "respondida", "resposta": "ok"}]))
    r = local.post("/api/perguntar", json={"pergunta": "oi", "modelo": "deepseek:deepseek-flash"})
    assert r.status_code == 200 and '"respondida"' in r.text


def test_embedding_local_fora_do_ar_vira_erro_claro(com_chave, monkeypatch):
    class Quebrado:
        def buscar(self, pergunta, docs, **kw):
            raise httpx.ConnectError("[Errno 111] Connection refused")
    monkeypatch.setattr(pipeline, "carregar", lambda exp: Quebrado())
    vistas = transporte(lambda r: httpx.Response(200, content=sse("x")))
    f = _final("deepseek:deepseek-v4-pro")
    assert f["desfecho"] == "erro" and "Ollama" in f["resposta"] and "embedding" in f["resposta"]
    assert vistas == []  # o modelo remoto nem chega a ser chamado
