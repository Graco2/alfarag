import json

import httpx
import pytest

from app import conexoes, contas, llm, pipeline

CHAVE = "sk-teste-0123456789abcdef"


@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    """Cada teste usa arquivo de conexões e pasta de traços próprios, nunca enxerga a chave real do ambiente
    e começa com o login desligado (os testes de contas ligam com CONTAS_DB em tmp_path)."""
    monkeypatch.setattr(conexoes, "CONEXOES_ARQ", tmp_path / "config" / "conexoes.json")
    monkeypatch.setattr(pipeline, "TRACOS_DIR", tmp_path / "tracos")
    monkeypatch.setattr(contas, "CONTAS_DB", "")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_TRANSPORT_REMOTO", None)


@pytest.fixture
def com_chave():
    conexoes.salvar("deepseek", nova_chave=CHAVE)


def sse(*eventos, usage=None, finish="stop"):
    """Monta um corpo SSE no formato do /chat/completions."""
    linhas = [f"data: {json.dumps({'choices': [{'index': 0, 'delta': {'content': t}, 'finish_reason': None}], 'usage': None})}\n" for t in eventos]
    final = {"choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": finish}], "usage": usage}
    linhas.append(f"data: {json.dumps(final)}\n")
    linhas.append("data: [DONE]\n")
    return "\n".join(linhas).encode()


def transporte(resposta_fn):
    """Instala um transporte simulado no cliente remoto e devolve a lista de requisições vistas."""
    vistas: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        return resposta_fn(req)

    llm._TRANSPORT_REMOTO = httpx.MockTransport(handler)
    return vistas
