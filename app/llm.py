"""Clientes de modelo: Ollama (local; também embeddings) e provedores OpenAI-compatíveis (remotos, só geração).

O provedor vem do prefixo do modelo (`ollama:...`, `deepseek:...`); nome sem prefixo é Ollama."""
from __future__ import annotations

import json
import os
import time
from typing import Iterator

import httpx

from . import conexoes
from .config import MAX_RESPOSTA, MODELO_EMBED, NUM_CTX, OLLAMA_URL, TEMPERATURA, TIMEOUT_REMOTO_S

_TIMEOUT = httpx.Timeout(connect=10, read=600, write=60, pool=10)
_TIMEOUT_REMOTO = httpx.Timeout(connect=10, read=TIMEOUT_REMOTO_S, write=30, pool=10)
FORCAR_CPU = os.getenv("FORCAR_CPU") == "1"
_TRANSPORT_REMOTO: httpx.BaseTransport | None = None  # só os testes trocam (httpx.MockTransport)


def resolver(modelo: str) -> tuple[str, str]:
    """'deepseek:deepseek-flash' -> ('deepseek', 'deepseek-flash'). Sem prefixo conhecido -> Ollama."""
    prefixo, sep, resto = modelo.partition(":")
    if sep and prefixo == "ollama":
        return "ollama", resto
    if sep and prefixo in conexoes.PROVEDORES:
        return prefixo, resto
    return "ollama", modelo


def eh_remoto(modelo: str) -> bool:
    return resolver(modelo)[0] != "ollama"


def embed(textos: list[str], modelo: str = MODELO_EMBED) -> list[list[float]]:
    r = httpx.post(f"{OLLAMA_URL}/api/embed", json={"model": modelo, "input": textos}, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()["embeddings"]


def _payload(modelo: str, mensagens: list[dict], stream: bool, temperatura: float | None, max_tokens: int | None) -> dict:
    return {
        "model": modelo,
        "messages": mensagens,
        "stream": stream,
        "think": False,  # raciocínio estendido desligado: em CPU ele multiplica a latência
        "keep_alive": "10m",
        "options": {
            "temperature": TEMPERATURA if temperatura is None else temperatura,
            "num_ctx": NUM_CTX,
            "num_predict": max_tokens or MAX_RESPOSTA,
            "seed": 42,
            **({"num_gpu": 0} if FORCAR_CPU else {}),  # FORCAR_CPU=1: nenhuma camada na GPU (medição só em CPU)
        },
    }


def _ollama_stream(modelo: str, mensagens: list[dict], temperatura: float | None = None) -> Iterator[dict]:
    with httpx.stream("POST", f"{OLLAMA_URL}/api/chat", json=_payload(modelo, mensagens, True, temperatura, None), timeout=_TIMEOUT) as r:
        r.raise_for_status()
        for linha in r.iter_lines():
            if not linha:
                continue
            ev = json.loads(linha)
            if ev.get("error"):
                raise RuntimeError(ev["error"])
            delta = ev.get("message", {}).get("content", "")
            if delta:
                yield {"delta": delta}
            if ev.get("done"):
                yield {"fim": {
                    "prompt_tokens": ev.get("prompt_eval_count"),
                    "resposta_tokens": ev.get("eval_count"),
                    "duracao_s": round((ev.get("total_duration") or 0) / 1e9, 2),
                    "tok_s": round((ev.get("eval_count") or 0) / max((ev.get("eval_duration") or 1) / 1e9, 1e-6), 2),
                    "done_reason": ev.get("done_reason"),
                }}


def _ollama_chat(modelo: str, mensagens: list[dict], temperatura: float | None = None, max_tokens: int | None = None, formato: dict | None = None) -> tuple[str, dict]:
    p = _payload(modelo, mensagens, False, temperatura, max_tokens)
    if formato is not None:
        p["format"] = formato
    r = httpx.post(f"{OLLAMA_URL}/api/chat", json=p, timeout=_TIMEOUT)
    r.raise_for_status()
    ev = r.json()
    meta = {
        "prompt_tokens": ev.get("prompt_eval_count"),
        "resposta_tokens": ev.get("eval_count"),
        "duracao_s": round((ev.get("total_duration") or 0) / 1e9, 2),
        "tok_s": round((ev.get("eval_count") or 0) / max((ev.get("eval_duration") or 1) / 1e9, 1e-6), 2),
        "done_reason": ev.get("done_reason"),
    }
    return ev["message"]["content"], meta


# ---------- Provedores OpenAI-compatíveis ----------
def _payload_remoto(provedor: str, nome: str, mensagens: list[dict], stream: bool, temperatura: float | None, max_tokens: int | None) -> dict:
    # Sem seed (a API remota não garante reprodutibilidade) e sem 'think' (parâmetro do Ollama).
    p = {
        "model": nome, "messages": mensagens, "stream": stream,
        "temperature": TEMPERATURA if temperatura is None else temperatura,
        "max_tokens": max_tokens or MAX_RESPOSTA,
        **conexoes.PROVEDORES[provedor]["extra"],
    }
    if stream:
        p["stream_options"] = {"include_usage": True}
    return p


def _erro_remoto(e: Exception) -> conexoes.ErroConexao:
    if isinstance(e, conexoes.ErroConexao):
        return e
    if isinstance(e, httpx.HTTPStatusError):
        return conexoes.ErroConexao(conexoes.mensagem_http(e.response.status_code))
    if isinstance(e, httpx.TimeoutException):
        return conexoes.ErroConexao("Tempo esgotado ao esperar o modelo remoto.")
    if isinstance(e, httpx.HTTPError):
        return conexoes.ErroConexao(f"Falha de rede ao falar com o modelo remoto ({type(e).__name__}).")
    return conexoes.ErroConexao(f"Resposta inesperada do modelo remoto ({type(e).__name__}).")


def _meta_remoto(uso: dict | None, finish: str | None, t0: float, n_delta: int) -> dict:
    uso = uso or {}
    dur = time.monotonic() - t0
    saida = uso.get("completion_tokens")
    return {
        "prompt_tokens": uso.get("prompt_tokens"), "resposta_tokens": saida,
        "duracao_s": round(dur, 2), "tok_s": round((saida or n_delta) / max(dur, 1e-6), 2),
        "done_reason": finish,  # 'length' continua sinalizando truncamento para o harness
    }


def _remoto_stream(provedor: str, nome: str, mensagens: list[dict], temperatura: float | None) -> Iterator[dict]:
    t0 = time.monotonic()
    uso: dict | None = None
    finish: str | None = None
    n = 0
    try:
        url = f"{conexoes.url_base(provedor)}/chat/completions"
        with httpx.Client(timeout=_TIMEOUT_REMOTO, transport=_TRANSPORT_REMOTO) as c:
            with c.stream("POST", url, headers=conexoes.cabecalhos(provedor),
                          json=_payload_remoto(provedor, nome, mensagens, True, temperatura, None)) as r:
                r.raise_for_status()
                for linha in r.iter_lines():
                    if not linha.startswith("data:"):
                        continue
                    dados = linha[5:].strip()
                    if dados == "[DONE]":
                        break
                    ev = json.loads(dados)
                    if ev.get("error"):
                        raise conexoes.ErroConexao("O provedor devolveu um erro durante a resposta.")
                    if ev.get("usage"):
                        uso = ev["usage"]
                    for ch in ev.get("choices") or []:
                        delta = (ch.get("delta") or {}).get("content") or ""
                        if delta:
                            n += 1
                            yield {"delta": delta}
                        if ch.get("finish_reason"):
                            finish = ch["finish_reason"]
    except Exception as e:
        raise _erro_remoto(e) from None
    yield {"fim": _meta_remoto(uso, finish, t0, n)}


def _remoto_chat(provedor: str, nome: str, mensagens: list[dict], temperatura: float | None, max_tokens: int | None) -> tuple[str, dict]:
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=_TIMEOUT_REMOTO, transport=_TRANSPORT_REMOTO) as c:
            r = c.post(f"{conexoes.url_base(provedor)}/chat/completions", headers=conexoes.cabecalhos(provedor),
                       json=_payload_remoto(provedor, nome, mensagens, False, temperatura, max_tokens))
            r.raise_for_status()
            ev = r.json()
            ch = ev["choices"][0]
            return ch["message"]["content"] or "", _meta_remoto(ev.get("usage"), ch.get("finish_reason"), t0, 0)
    except Exception as e:
        raise _erro_remoto(e) from None


def chat_stream(modelo: str, mensagens: list[dict], temperatura: float | None = None) -> Iterator[dict]:
    """Gera eventos {'delta': str} e, ao final, {'fim': {...métricas...}} (mesmo formato nos dois provedores)."""
    provedor, nome = resolver(modelo)
    if provedor == "ollama":
        yield from _ollama_stream(nome, mensagens, temperatura)
    else:
        yield from _remoto_stream(provedor, nome, mensagens, temperatura)


def chat(modelo: str, mensagens: list[dict], temperatura: float | None = None, max_tokens: int | None = None, formato: dict | None = None) -> tuple[str, dict]:
    provedor, nome = resolver(modelo)
    if provedor == "ollama":
        return _ollama_chat(nome, mensagens, temperatura, max_tokens, formato)
    return _remoto_chat(provedor, nome, mensagens, temperatura, max_tokens)  # 'formato' é recurso do Ollama


def digest(modelo: str) -> str | None:
    """Digest do artefato no Ollama: a mesma tag pode apontar para arquivos diferentes por plataforma.
    Modelo remoto não tem digest verificável: devolve None."""
    provedor, modelo = resolver(modelo)
    if provedor != "ollama":
        return None
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        for m in r.json().get("models", []):
            if m["name"] == modelo or m.get("model") == modelo:
                return m.get("digest", "")[:12]
    except Exception:
        pass
    return None


def modelos_disponiveis() -> list[str]:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []
