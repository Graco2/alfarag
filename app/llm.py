"""Cliente mínimo do Ollama (embeddings e chat com streaming)."""
from __future__ import annotations

import json
from typing import Iterator

import httpx

from .config import MAX_RESPOSTA, MODELO_EMBED, NUM_CTX, OLLAMA_URL, TEMPERATURA

_TIMEOUT = httpx.Timeout(connect=10, read=600, write=60, pool=10)


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
        },
    }


def chat_stream(modelo: str, mensagens: list[dict], temperatura: float | None = None) -> Iterator[dict]:
    """Gera eventos {'delta': str} e, ao final, {'fim': {...métricas do Ollama...}}."""
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


def chat(modelo: str, mensagens: list[dict], temperatura: float | None = None, max_tokens: int | None = None, formato: dict | None = None) -> tuple[str, dict]:
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


def modelos_disponiveis() -> list[str]:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []
