"""Contas individuais e sessões do servidor aberto na web. Só valem com CONTAS_DB definida.

Armazenamento: SQLite em CONTAS_DB, com as tabelas `contas` e `sessoes`. A senha fica como scrypt com sal. A sessão
fica só como SHA-256 do token: o token em claro existe apenas no cookie do navegador. A identidade serve para acesso e
revogação e não vai para o traço das respostas.

Linha de comando (na VPS: docker exec -it alfarag /opt/venv/bin/python -m app.contas ...):
    python -m app.contas criar-admin <usuario>    cria o 1º admin (pede a senha)
    python -m app.contas listar                   lista as contas
    python -m app.contas redefinir <usuario>      gera uma senha provisória e derruba as sessões
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import CONTAS_DB

USUARIO_RE = re.compile(r"[a-z0-9][a-z0-9.-]{2,31}")
SENHA_MIN, SENHA_MAX = 8, 200
MAX_PENDENTES = 50  # teto de cadastros aguardando liberação (cadastro aberto não pode encher o disco)
SESSAO_MAX = timedelta(days=7)  # teto no servidor; o cookie em si vale até o navegador fechar

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32
_HASHES = threading.BoundedSemaphore(2)  # o scrypt pesa na CPU que também roda o Ollama
_ESPERA_HASH_S = 15

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS contas (
    usuario       TEXT PRIMARY KEY COLLATE NOCASE,
    hash          TEXT NOT NULL,
    estado        TEXT NOT NULL CHECK (estado IN ('pendente', 'ativa', 'desativada')),
    admin         INTEGER NOT NULL DEFAULT 0 CHECK (admin IN (0, 1)),
    criada_em     TEXT NOT NULL,
    ultimo_acesso TEXT
);
CREATE TABLE IF NOT EXISTS sessoes (
    token_sha256 TEXT PRIMARY KEY,
    usuario      TEXT NOT NULL REFERENCES contas(usuario) ON DELETE CASCADE,
    criada_em    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessoes_usuario ON sessoes(usuario);
"""


class ErroConta(Exception):
    """Mensagem segura para mostrar à pessoa: nunca contém senha, hash nem token."""


class Invalido(ErroConta):
    pass


class Conflito(ErroConta):
    pass


class NaoEncontrada(ErroConta):
    pass


class Ocupado(ErroConta):
    pass


def ativo() -> bool:
    return bool(CONTAS_DB)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _limite_sessao() -> str:
    return (datetime.now(timezone.utc) - SESSAO_MAX).isoformat(timespec="seconds")


def normalizar(usuario: str) -> str:
    return str(usuario).strip().lower()


def validar_usuario(usuario: str) -> str:
    u = normalizar(usuario)
    if not USUARIO_RE.fullmatch(u):
        raise Invalido("Nome de usuário inválido: use de 3 a 32 caracteres (letras, números, ponto ou hífen), "
                       "começando por letra ou número.")
    return u


def validar_senha(senha: str) -> str:
    if not SENHA_MIN <= len(senha) <= SENHA_MAX:
        raise Invalido(f"A senha precisa ter de {SENHA_MIN} a {SENHA_MAX} caracteres.")
    return senha


# ---------- Hash de senha ----------
def _scrypt(senha: str, sal: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    if not _HASHES.acquire(timeout=_ESPERA_HASH_S):
        raise Ocupado("Servidor ocupado. Tente de novo em instantes.")
    try:
        return hashlib.scrypt(senha.encode(), salt=sal, n=n, r=r, p=p, dklen=dklen, maxmem=64 * 1024 * 1024)
    finally:
        _HASHES.release()


def gerar_hash(senha: str) -> str:
    """Formato scrypt$n$r$p$sal$hash (hex)."""
    sal = secrets.token_bytes(16)
    return f"scrypt${_N}${_R}${_P}${sal.hex()}${_scrypt(senha, sal, _N, _R, _P, _DKLEN).hex()}"


def conferir_hash(senha: str, codificado: str) -> bool:
    try:
        nome, n, r, p, sal, h = codificado.split("$")
        esperado, sal_b, n, r, p = bytes.fromhex(h), bytes.fromhex(sal), int(n), int(r), int(p)
    except ValueError:
        return False
    if nome != "scrypt":
        return False
    return hmac.compare_digest(_scrypt(senha, sal_b, n, r, p, len(esperado)), esperado)


_FICTICIO: str | None = None


def _hash_ficticio() -> str:
    """Hash conferido quando a conta não existe: o tempo de resposta não revela se o nome está cadastrado."""
    global _FICTICIO
    if _FICTICIO is None:
        _FICTICIO = gerar_hash(secrets.token_urlsafe(16))
    return _FICTICIO


# ---------- Banco ----------
_PRONTOS: set[str] = set()


def _abrir() -> sqlite3.Connection:
    if not CONTAS_DB:
        raise RuntimeError("CONTAS_DB não definida.")
    caminho = Path(CONTAS_DB)
    if CONTAS_DB not in _PRONTOS:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        os.close(os.open(caminho, os.O_CREAT | os.O_RDWR, 0o600))  # nasce 600; o SQLite copia a permissão no -wal
        os.chmod(caminho, 0o600)
        con = sqlite3.connect(caminho, isolation_level=None)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_ESQUEMA)
        finally:
            con.close()
        _PRONTOS.add(CONTAS_DB)
    con = sqlite3.connect(caminho, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def _db(escrita: bool = False):
    """Uma conexão por chamada, numa transação. Escrita usa BEGIN IMMEDIATE: duas ações de admin ao mesmo tempo
    não conseguem, por exemplo, rebaixar uma à outra e deixar o servidor sem admin."""
    con = _abrir()
    try:
        con.execute("BEGIN IMMEDIATE" if escrita else "BEGIN")
        yield con
        con.execute("COMMIT")
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def _publica(row: sqlite3.Row) -> dict:
    """Lista branca de campos: hash e sessões nunca saem daqui."""
    return {"usuario": row["usuario"], "estado": row["estado"], "admin": bool(row["admin"]),
            "criada_em": row["criada_em"], "ultimo_acesso": row["ultimo_acesso"]}


# ---------- Cadastro e login ----------
def _checar_novo(con: sqlite3.Connection, u: str, estado: str) -> None:
    if con.execute("SELECT 1 FROM contas WHERE usuario = ?", (u,)).fetchone():
        raise Conflito("Esse nome de usuário já está em uso.")
    if estado == "pendente" and con.execute("SELECT COUNT(*) FROM contas WHERE estado = 'pendente'").fetchone()[0] >= MAX_PENDENTES:
        raise Ocupado("Há cadastros demais aguardando liberação. Tente mais tarde.")


def _inserir(usuario: str, senha: str, estado: str, admin: bool) -> dict:
    u, s = validar_usuario(usuario), validar_senha(senha)
    with _db() as con:
        _checar_novo(con, u, estado)
    h = gerar_hash(s)  # fora da transação: o scrypt leva dezenas de ms
    with _db(escrita=True) as con:
        _checar_novo(con, u, estado)
        con.execute("INSERT INTO contas (usuario, hash, estado, admin, criada_em) VALUES (?, ?, ?, ?, ?)",
                    (u, h, estado, int(admin), _agora()))
        return _publica(con.execute("SELECT * FROM contas WHERE usuario = ?", (u,)).fetchone())


def cadastrar(usuario: str, senha: str) -> dict:
    """Cadastro pela tela: a conta nasce pendente e só entra depois que um admin aprova."""
    return _inserir(usuario, senha, "pendente", admin=False)


def criar_admin(usuario: str, senha: str) -> dict:
    """1º admin, pela linha de comando na VPS."""
    return _inserir(usuario, senha, "ativa", admin=True)


def autenticar(usuario: str, senha: str) -> dict | None:
    """A conta (campos públicos, em qualquer estado) se a senha confere; None caso contrário.
    Quem chama só fica sabendo o estado da conta quando acertou a senha."""
    u, row = normalizar(usuario), None
    if USUARIO_RE.fullmatch(u):
        with _db() as con:
            row = con.execute("SELECT * FROM contas WHERE usuario = ?", (u,)).fetchone()
    ok = conferir_hash(senha, row["hash"] if row else _hash_ficticio())
    return _publica(row) if ok and row else None


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def abrir_sessao(usuario: str) -> str:
    """Token novo para o cookie. Só para conta ativa. Atualiza o último acesso e apaga sessões vencidas."""
    token, agora, u = secrets.token_urlsafe(32), _agora(), normalizar(usuario)
    with _db(escrita=True) as con:
        con.execute("DELETE FROM sessoes WHERE criada_em <= ?", (_limite_sessao(),))
        cur = con.execute("INSERT INTO sessoes (token_sha256, usuario, criada_em) "
                          "SELECT ?, usuario, ? FROM contas WHERE usuario = ? AND estado = 'ativa'", (_sha(token), agora, u))
        if cur.rowcount != 1:
            raise NaoEncontrada("Conta inexistente ou inativa.")
        con.execute("UPDATE contas SET ultimo_acesso = ? WHERE usuario = ?", (agora, u))
    return token


def conta_da_sessao(token: str | None) -> dict | None:
    """{usuario, admin} da sessão válida (conta ativa e sessão dentro do prazo), ou None."""
    if not token or len(token) > 128:
        return None
    with _db() as con:
        row = con.execute("SELECT c.usuario, c.admin FROM sessoes s JOIN contas c ON c.usuario = s.usuario "
                          "WHERE s.token_sha256 = ? AND s.criada_em > ? AND c.estado = 'ativa'",
                          (_sha(token), _limite_sessao())).fetchone()
    return {"usuario": row["usuario"], "admin": bool(row["admin"])} if row else None


def encerrar_sessao(token: str | None) -> None:
    if token:
        with _db(escrita=True) as con:
            con.execute("DELETE FROM sessoes WHERE token_sha256 = ?", (_sha(token),))


def trocar_senha(usuario: str, atual: str, nova: str) -> bool:
    """False se a senha atual não confere. Se trocar, derruba todas as sessões da conta."""
    validar_senha(nova)
    u = normalizar(usuario)
    with _db() as con:
        row = con.execute("SELECT hash FROM contas WHERE usuario = ? AND estado = 'ativa'", (u,)).fetchone()
    if not conferir_hash(atual, row["hash"] if row else _hash_ficticio()) or not row:
        return False
    h = gerar_hash(nova)
    with _db(escrita=True) as con:
        con.execute("UPDATE contas SET hash = ? WHERE usuario = ?", (h, u))
        con.execute("DELETE FROM sessoes WHERE usuario = ?", (u,))
    return True


# ---------- Administração ----------
def listar() -> list[dict]:
    """Pendentes primeiro. Seleciona só os campos públicos (nunca o hash)."""
    with _db() as con:
        rows = con.execute("SELECT usuario, estado, admin, criada_em, ultimo_acesso FROM contas "
                           "ORDER BY estado != 'pendente', usuario").fetchall()
    return [_publica(r) for r in rows]


def _conta(con: sqlite3.Connection, usuario: str) -> sqlite3.Row:
    row = con.execute("SELECT usuario, estado, admin FROM contas WHERE usuario = ?", (normalizar(usuario),)).fetchone()
    if not row:
        raise NaoEncontrada("Conta não encontrada.")
    return row


def _exigir_estado(row: sqlite3.Row, *estados: str) -> None:
    if row["estado"] not in estados:
        raise Conflito(f"A conta está {row['estado']}: essa ação não se aplica.")


def _proteger_ultimo_admin(con: sqlite3.Connection, row: sqlite3.Row) -> None:
    if row["admin"] and row["estado"] == "ativa":
        outros = con.execute("SELECT COUNT(*) FROM contas WHERE admin = 1 AND estado = 'ativa' AND usuario != ?",
                             (row["usuario"],)).fetchone()[0]
        if not outros:
            raise Conflito("Não é possível: é o último admin ativo.")


def aprovar(usuario: str) -> None:
    with _db(escrita=True) as con:
        row = _conta(con, usuario)
        _exigir_estado(row, "pendente")
        con.execute("UPDATE contas SET estado = 'ativa' WHERE usuario = ?", (row["usuario"],))


def recusar(usuario: str) -> None:
    """Recusar um cadastro pendente exclui a conta."""
    with _db(escrita=True) as con:
        row = _conta(con, usuario)
        _exigir_estado(row, "pendente")
        con.execute("DELETE FROM contas WHERE usuario = ?", (row["usuario"],))


def desativar(usuario: str) -> None:
    with _db(escrita=True) as con:
        row = _conta(con, usuario)
        _exigir_estado(row, "ativa")
        _proteger_ultimo_admin(con, row)
        con.execute("UPDATE contas SET estado = 'desativada' WHERE usuario = ?", (row["usuario"],))
        con.execute("DELETE FROM sessoes WHERE usuario = ?", (row["usuario"],))


def reativar(usuario: str) -> None:
    with _db(escrita=True) as con:
        row = _conta(con, usuario)
        _exigir_estado(row, "desativada")
        con.execute("UPDATE contas SET estado = 'ativa' WHERE usuario = ?", (row["usuario"],))


def excluir(usuario: str) -> None:
    with _db(escrita=True) as con:
        row = _conta(con, usuario)
        _proteger_ultimo_admin(con, row)
        con.execute("DELETE FROM contas WHERE usuario = ?", (row["usuario"],))  # as sessões caem em cascata


def redefinir_senha(usuario: str) -> str:
    """Senha provisória (só no retorno; nunca em log) e todas as sessões da conta derrubadas."""
    provisoria = secrets.token_urlsafe(9)
    h = gerar_hash(provisoria)
    with _db(escrita=True) as con:
        row = _conta(con, usuario)
        con.execute("UPDATE contas SET hash = ? WHERE usuario = ?", (h, row["usuario"]))
        con.execute("DELETE FROM sessoes WHERE usuario = ?", (row["usuario"],))
    return provisoria


def definir_admin(usuario: str, admin: bool) -> None:
    with _db(escrita=True) as con:
        row = _conta(con, usuario)
        if admin:
            _exigir_estado(row, "ativa")
        elif row["admin"]:
            _proteger_ultimo_admin(con, row)
        con.execute("UPDATE contas SET admin = ? WHERE usuario = ?", (int(admin), row["usuario"]))


# ---------- Linha de comando ----------
def _pedir_senha() -> str:
    senha = getpass.getpass(f"Senha ({SENHA_MIN} a {SENHA_MAX} caracteres): ")
    if senha != getpass.getpass("Repita a senha: "):
        raise Invalido("As senhas não conferem.")
    return senha


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.contas", description="Contas do servidor aberto na web (usa CONTAS_DB).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("criar-admin", help="cria uma conta ativa de admin").add_argument("usuario")
    sub.add_parser("listar", help="lista as contas")
    sub.add_parser("redefinir", help="gera uma senha provisória e derruba as sessões").add_argument("usuario")
    a = ap.parse_args(argv)
    if not ativo():
        print("ERRO: defina CONTAS_DB (ex.: CONTAS_DB=/data/contas.db).", file=sys.stderr)
        return 2
    try:
        if a.cmd == "criar-admin":
            c = criar_admin(a.usuario, _pedir_senha())
            print(f"Admin criado: {c['usuario']}")
        elif a.cmd == "listar":
            for c in listar():
                print(f"{c['usuario']:<32} {c['estado']:<10} {'admin' if c['admin'] else '-':<5} "
                      f"criada {c['criada_em']}  último acesso {c['ultimo_acesso'] or 'nunca'}")
        else:
            provisoria = redefinir_senha(a.usuario)
            print(f"Senha provisória de {normalizar(a.usuario)}: {provisoria}")
            print("Passe à pessoa por um canal seguro. As sessões abertas dessa conta foram encerradas.")
    except ErroConta as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
