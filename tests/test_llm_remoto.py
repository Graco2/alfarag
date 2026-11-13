import json

import httpx
import pytest

from app import conexoes, llm
from .conftest import CHAVE, sse, transporte

MSG = [{"role": "user", "content": "oi"}]
USO = {"prompt_tokens": 120, "completion_tokens": 7, "total_tokens": 127}


def test_resolver_prefixos():
    assert llm.resolver("deepseek:deepseek-flash") == ("deepseek", "deepseek-flash")
    assert llm.resolver("ollama:qwen3.5:4b-q4_K_M") == ("ollama", "qwen3.5:4b-q4_K_M")
    # sem prefixo = Ollama, inclusive quando o nome tem ':' (compatível com scripts e traços antigos)
    assert llm.resolver("qwen3.5:4b-q4_K_M") == ("ollama", "qwen3.5:4b-q4_K_M")
    assert llm.resolver("gemma4:e4b-it-q4_K_M") == ("ollama", "gemma4:e4b-it-q4_K_M")
    assert llm.eh_remoto("deepseek:x") and not llm.eh_remoto("bge-m3")


def test_digest_remoto_e_none():
    assert llm.digest("deepseek:deepseek-flash") is None


def test_stream_deltas_tokens_e_payload(com_chave):
    vistas = transporte(lambda r: httpx.Response(200, content=sse("Olá", " mundo", usage=USO)))
    ev = list(llm.chat_stream("deepseek:deepseek-flash", MSG))
    assert [e["delta"] for e in ev if "delta" in e] == ["Olá", " mundo"]
    fim = ev[-1]["fim"]
    assert fim["prompt_tokens"] == 120 and fim["resposta_tokens"] == 7 and fim["done_reason"] == "stop"
    req = vistas[0]
    assert str(req.url) == "https://api.deepseek.com/chat/completions"
    assert req.headers["authorization"] == f"Bearer {CHAVE}"
    corpo = json.loads(req.content)
    assert corpo["model"] == "deepseek-flash" and corpo["stream"] is True
    assert corpo["stream_options"] == {"include_usage": True}
    assert corpo["thinking"] == {"type": "disabled"}
    assert "temperature" in corpo and "max_tokens" in corpo
    assert "seed" not in corpo and "think" not in corpo and "options" not in corpo


def test_finish_length_vira_done_reason_length(com_chave):
    transporte(lambda r: httpx.Response(200, content=sse("cortad", usage=USO, finish="length")))
    fim = list(llm.chat_stream("deepseek:deepseek-flash", MSG))[-1]["fim"]
    assert fim["done_reason"] == "length"  # é o que o harness lê para marcar truncamento


@pytest.mark.parametrize("status,trecho", [(401, "401"), (402, "Saldo insuficiente"), (429, "429"), (503, "503")])
def test_erros_http_sem_vazar_chave(com_chave, status, trecho):
    # o corpo do erro (que poderia ecoar a chave) nunca é lido nem repassado
    transporte(lambda r: httpx.Response(status, json={"error": {"message": f"bad key {CHAVE}"}}))
    with pytest.raises(conexoes.ErroConexao) as e:
        list(llm.chat_stream("deepseek:deepseek-flash", MSG))
    assert trecho in str(e.value) and CHAVE not in str(e.value) and "Bearer" not in str(e.value)


def test_timeout_sem_vazar_chave(com_chave):
    def estoura(r):
        raise httpx.ReadTimeout(f"timeout com {CHAVE}", request=r)
    transporte(estoura)
    with pytest.raises(conexoes.ErroConexao) as e:
        list(llm.chat_stream("deepseek:deepseek-flash", MSG))
    assert "Tempo esgotado" in str(e.value) and CHAVE not in str(e.value)


def test_sem_chave_nao_chama_a_rede():
    vistas = transporte(lambda r: httpx.Response(200, content=sse("x")))
    with pytest.raises(conexoes.ErroConexao):
        list(llm.chat_stream("deepseek:deepseek-flash", MSG))
    assert vistas == []


def test_resolver_gemini():
    assert llm.resolver("gemini:gemini-3.5-flash-lite") == ("gemini", "gemini-3.5-flash-lite")
    assert llm.eh_remoto("gemini:x")


def test_stream_gemini_url_e_payload():
    conexoes.salvar("gemini", nova_chave=CHAVE)
    vistas = transporte(lambda r: httpx.Response(200, content=sse("Olá", usage=USO)))
    ev = list(llm.chat_stream("gemini:gemini-3.5-flash-lite", MSG))
    assert [e["delta"] for e in ev if "delta" in e] == ["Olá"] and ev[-1]["fim"]["resposta_tokens"] == 7
    req = vistas[0]
    assert str(req.url) == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert req.headers["authorization"] == f"Bearer {CHAVE}"
    corpo = json.loads(req.content)
    assert corpo["model"] == "gemini-3.5-flash-lite" and corpo["reasoning_effort"] == "minimal"
    assert "thinking" not in corpo  # parâmetro só do DeepSeek


def test_chat_nao_streaming(com_chave):
    corpo = {"choices": [{"message": {"content": "resposta"}, "finish_reason": "stop"}], "usage": USO}
    vistas = transporte(lambda r: httpx.Response(200, json=corpo))
    txt, meta = llm.chat("deepseek:deepseek-flash", MSG, temperatura=0, max_tokens=50)
    assert txt == "resposta" and meta["resposta_tokens"] == 7
    c = json.loads(vistas[0].content)
    assert c["stream"] is False and c["max_tokens"] == 50 and c["temperature"] == 0 and "stream_options" not in c
