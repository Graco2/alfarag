"""Conexões com provedores remotos de geração (OpenAI-compatíveis).

A chave nunca sai daqui em claro: a interface recebe só a versão mascarada, e toda mensagem de erro
passa por `sanitizar`. Prioridade da chave: variável de ambiente > config/conexoes.json (permissão 600)."""
from __future__ import annotations

import json
import os
import re
import threading
from urllib.parse import urlparse

import httpx

from .config import CHAVE_DO_USUARIO, CONEXOES_ARQ

# Provedores conhecidos. `extra` entra no corpo de cada requisição de chat.
PROVEDORES: dict[str, dict] = {
    "deepseek": {
        "rotulo": "DeepSeek",
        "url_base": "https://api.deepseek.com",
        "env": "DEEPSEEK_API_KEY",
        "modelos": ["deepseek-flash", "deepseek-v4-pro"],
        "extra": {"thinking": {"type": "disabled"}},  # sem raciocínio estendido (vem ligado por padrão na API)
        "pais": "fora do Brasil",
    },
}

_LOCK = threading.Lock()


class ErroConexao(Exception):
    """Erro já sanitizado, seguro para mostrar ao usuário e gravar no traço."""


def _ler() -> dict:
    try:
        return json.loads(CONEXOES_ARQ.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _gravar(dados: dict) -> None:
    CONEXOES_ARQ.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONEXOES_ARQ.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONEXOES_ARQ)


def _validar_url(url: str) -> str:
    u = urlparse(url.strip())
    loopback = u.hostname in ("127.0.0.1", "localhost", "::1")
    if u.scheme not in ("https", "http") or not u.hostname or (u.scheme == "http" and not loopback):
        raise ValueError("URL base inválida: use https:// (http só para localhost).")
    if u.username or u.password or u.query or u.fragment:
        raise ValueError("URL base não pode conter usuário, senha ou parâmetros.")
    return url.strip().rstrip("/")


def _chave_env(provedor: str) -> str:
    return os.getenv(PROVEDORES[provedor]["env"], "").strip()


def chave(provedor: str) -> str:
    """Chave do servidor (ambiente > arquivo). No modo CHAVE_DO_USUARIO o servidor não tem chave própria."""
    if CHAVE_DO_USUARIO:
        return ""
    return _chave_env(provedor) or str(_ler().get(provedor, {}).get("chave", "")).strip()


def url_base(provedor: str) -> str:
    return str(_ler().get(provedor, {}).get("url_base") or PROVEDORES[provedor]["url_base"]).rstrip("/")


def modelos_do_provedor(provedor: str) -> list[str]:
    ms = _ler().get(provedor, {}).get("modelos")
    if isinstance(ms, list) and ms and all(isinstance(m, str) and m.strip() for m in ms):
        return [m.strip() for m in ms]
    return list(PROVEDORES[provedor]["modelos"])


def configurada(provedor: str) -> bool:
    return bool(chave(provedor))


def mascarar(k: str) -> str:
    if not k:
        return ""
    return f"{k[:3]}…{k[-4:]}" if len(k) >= 16 else "••••••••"


def chave_valida(k: str | None) -> bool:
    return bool(k) and 8 <= len(k) <= 300 and not re.search(r"\s", k)


def sanitizar(texto: object, *extras: str | None) -> str:
    """Remove qualquer chave conhecida (e as passadas em `extras`) e padrões de credencial de um texto."""
    t = str(texto)
    for k in extras:
        if k:
            t = t.replace(k, "[chave]")
    for p in PROVEDORES:
        k = chave(p)
        if k:
            t = t.replace(k, "[chave]")
    t = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]+", "Bearer [chave]", t)
    return re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "[chave]", t)


def publico() -> list[dict]:
    """Estado das conexões para a interface: nunca inclui a chave."""
    out = []
    for p, cfg in PROVEDORES.items():
        k = chave(p)
        out.append({
            "provedor": p, "rotulo": cfg["rotulo"], "pais": cfg["pais"], "url_base": url_base(p),
            "configurada": bool(k), "chave_mascarada": mascarar(k),
            "origem": "ambiente" if _chave_env(p) else ("arquivo" if k else None),
            "modelos": modelos_do_provedor(p),
        })
    return out


def modelos_remotos() -> list[str]:
    """Ids com prefixo dos modelos remotos disponíveis (só provedores com chave; no modo CHAVE_DO_USUARIO, todos)."""
    return [f"{p}:{m}" for p in PROVEDORES if CHAVE_DO_USUARIO or configurada(p) for m in modelos_do_provedor(p)]


def salvar(provedor: str, url: str | None = None, nova_chave: str | None = None, modelos: list[str] | None = None) -> None:
    if provedor not in PROVEDORES:
        raise ValueError("Provedor desconhecido.")
    with _LOCK:
        dados = _ler()
        c = dict(dados.get(provedor, {}))
        if url is not None:
            c["url_base"] = _validar_url(url)
        if nova_chave:  # vazio = manter a chave atual
            nova_chave = nova_chave.strip()
            if len(nova_chave) < 8 or re.search(r"\s", nova_chave):
                raise ValueError("Chave inválida.")
            c["chave"] = nova_chave
        if modelos is not None:
            ms = [m.strip() for m in modelos if m.strip()]
            if not ms or not all(re.fullmatch(r"[A-Za-z0-9._\-/:]{1,80}", m) for m in ms):
                raise ValueError("Lista de modelos inválida.")
            c["modelos"] = ms
        dados[provedor] = c
        _gravar(dados)


def remover(provedor: str) -> None:
    if provedor not in PROVEDORES:
        raise ValueError("Provedor desconhecido.")
    with _LOCK:
        dados = _ler()
        dados.pop(provedor, None)
        _gravar(dados)


def cabecalhos(provedor: str, chave_usuario: str | None = None) -> dict:
    k = chave_usuario or chave(provedor)
    if not k:
        raise ErroConexao("Conexão sem chave. Informe sua chave em Conexões." if CHAVE_DO_USUARIO
                          else "Conexão sem chave. Configure em Conexões ou defina " + PROVEDORES[provedor]["env"] + ".")
    return {"Authorization": f"Bearer {k}"}


def mensagem_http(status: int) -> str:
    return {
        400: "Requisição recusada pelo provedor (400).",
        401: "Chave recusada pelo provedor (401). Confira a chave em Conexões.",
        402: "Saldo insuficiente no provedor (402). Recarregue o crédito.",
        403: "Acesso negado pelo provedor (403).",
        404: "Endereço ou modelo não encontrado no provedor (404).",
        422: "Parâmetros recusados pelo provedor (422).",
        429: "Limite de uso do provedor atingido (429). Tente de novo em instantes.",
    }.get(status, f"Provedor indisponível (HTTP {status}).")


def testar(provedor: str, cliente: httpx.Client | None = None, chave_usuario: str | None = None) -> dict:
    """GET {base}/models. Devolve {ok, mensagem, modelos?}; nunca levanta nem vaza a chave."""
    try:
        h = cabecalhos(provedor, chave_usuario)
    except ErroConexao as e:
        return {"ok": False, "mensagem": str(e)}
    c = cliente or httpx.Client(timeout=httpx.Timeout(15))
    try:
        r = c.get(f"{url_base(provedor)}/models", headers=h)
    except httpx.TimeoutException:
        return {"ok": False, "mensagem": "Tempo esgotado ao falar com o provedor."}
    except httpx.HTTPError as e:
        return {"ok": False, "mensagem": f"Não foi possível conectar ({type(e).__name__})."}
    finally:
        if cliente is None:
            c.close()
    if r.status_code != 200:
        return {"ok": False, "mensagem": mensagem_http(r.status_code)}
    try:
        ids = [m["id"] for m in r.json().get("data", []) if isinstance(m, dict) and "id" in m]
    except ValueError:
        ids = []
    return {"ok": True, "mensagem": "Conexão ok.", "modelos": ids[:50]}
