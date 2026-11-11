"""Contas e sessões (app/contas.py), direto no módulo, com CONTAS_DB em tmp_path."""
import hashlib
import os
import sqlite3
import stat
from datetime import timedelta

import pytest

from app import contas

PROF, SENHA = "prof.ana", "senha-da-ana-1"


@pytest.fixture
def db(tmp_path, monkeypatch):
    caminho = tmp_path / "dados" / "contas.db"
    monkeypatch.setattr(contas, "CONTAS_DB", str(caminho))
    return caminho


def _ativa(usuario=PROF, senha=SENHA):
    contas.cadastrar(usuario, senha)
    contas.aprovar(usuario)


def test_hash_scrypt_com_sal():
    h1, h2 = contas.gerar_hash("uma senha"), contas.gerar_hash("uma senha")
    assert h1 != h2 and h1.startswith("scrypt$16384$8$1$") and "uma senha" not in h1
    assert contas.conferir_hash("uma senha", h1) and not contas.conferir_hash("outra senha", h1)
    assert not contas.conferir_hash("uma senha", "lixo") and not contas.conferir_hash("uma senha", "md5$1$1$1$00$00")


def test_banco_nasce_com_permissao_600(db):
    _ativa()
    assert stat.S_IMODE(os.stat(db).st_mode) == 0o600


def test_nome_duplicado_sem_diferenciar_caixa(db):
    c = contas.cadastrar("  Prof.Ana ", SENHA)
    assert c["usuario"] == PROF and c["estado"] == "pendente" and c["admin"] is False
    with pytest.raises(contas.Conflito):
        contas.cadastrar("PROF.ANA", "outra-senha-1")
    assert contas.autenticar("PROF.ANA", SENHA)["usuario"] == PROF


@pytest.mark.parametrize("nome", ["ab", "-ana", ".ana", "ana silva", "ana@escola", "ana_b", "a" * 33, "ána"])
def test_nome_invalido(db, nome):
    with pytest.raises(contas.Invalido):
        contas.cadastrar(nome, SENHA)


def test_senha_fora_do_tamanho(db):
    for s in ("curta", "x" * 201):
        with pytest.raises(contas.Invalido):
            contas.cadastrar(PROF, s)
    assert contas.listar() == []


def test_ciclo_pendente_ativa_desativada(db):
    contas.cadastrar(PROF, SENHA)
    assert contas.autenticar(PROF, "errada-1234") is None
    assert contas.autenticar(PROF, SENHA)["estado"] == "pendente"  # o estado só sai com a senha certa
    with pytest.raises(contas.NaoEncontrada):
        contas.abrir_sessao(PROF)  # pendente não abre sessão
    contas.aprovar(PROF)
    with pytest.raises(contas.Conflito):
        contas.aprovar(PROF)
    token = contas.abrir_sessao(PROF)
    assert contas.conta_da_sessao(token) == {"usuario": PROF, "admin": False}
    assert contas.listar()[0]["ultimo_acesso"]
    contas.desativar(PROF)
    assert contas.conta_da_sessao(token) is None
    assert contas.autenticar(PROF, SENHA)["estado"] == "desativada"
    contas.reativar(PROF)
    assert contas.conta_da_sessao(token) is None  # a sessão derrubada não volta com a reativação
    assert contas.conta_da_sessao(contas.abrir_sessao(PROF))


def test_recusar_exclui_so_pendente(db):
    contas.cadastrar(PROF, SENHA)
    contas.recusar(PROF)
    assert contas.listar() == []
    _ativa()
    with pytest.raises(contas.Conflito):
        contas.recusar(PROF)
    with pytest.raises(contas.NaoEncontrada):
        contas.aprovar("ninguem")


def test_sessao_cai_ao_sair_redefinir_e_excluir(db):
    _ativa()
    t1 = contas.abrir_sessao(PROF)
    contas.encerrar_sessao(t1)
    assert contas.conta_da_sessao(t1) is None
    t2 = contas.abrir_sessao(PROF)
    provisoria = contas.redefinir_senha(PROF)
    assert contas.conta_da_sessao(t2) is None
    assert contas.autenticar(PROF, SENHA) is None and contas.autenticar(PROF, provisoria)
    t3 = contas.abrir_sessao(PROF)
    contas.excluir(PROF)
    assert contas.conta_da_sessao(t3) is None and contas.listar() == []
    assert contas.conta_da_sessao("") is None and contas.conta_da_sessao("x" * 500) is None


def test_sessao_vence_no_servidor(db, monkeypatch):
    _ativa()
    token = contas.abrir_sessao(PROF)
    monkeypatch.setattr(contas, "SESSAO_MAX", timedelta(seconds=-1))
    assert contas.conta_da_sessao(token) is None


def test_banco_guarda_so_o_hash_do_token_e_da_senha(db):
    _ativa()
    token = contas.abrir_sessao(PROF)
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT token_sha256 FROM sessoes").fetchall() == [(hashlib.sha256(token.encode()).hexdigest(),)]
    bruto = b"".join(p.read_bytes() for p in db.parent.iterdir())  # banco + -wal
    assert token.encode() not in bruto and SENHA.encode() not in bruto


def test_ultimo_admin_protegido(db):
    contas.criar_admin("admin", "senha-do-admin-1")
    for acao in (contas.desativar, contas.excluir, lambda u: contas.definir_admin(u, False)):
        with pytest.raises(contas.Conflito):
            acao("admin")
    _ativa()
    contas.definir_admin(PROF, True)
    contas.definir_admin("admin", False)  # agora existe outro admin
    with pytest.raises(contas.Conflito):
        contas.desativar(PROF)
    assert [(c["usuario"], c["admin"]) for c in contas.listar()] == [("admin", False), (PROF, True)]


def test_promover_so_conta_ativa(db):
    contas.cadastrar(PROF, SENHA)
    with pytest.raises(contas.Conflito):
        contas.definir_admin(PROF, True)


def test_trocar_senha_exige_a_atual(db):
    _ativa()
    t = contas.abrir_sessao(PROF)
    assert contas.trocar_senha(PROF, "errada-1234", "nova-senha-123") is False
    assert contas.conta_da_sessao(t)  # nada mudou
    with pytest.raises(contas.Invalido):
        contas.trocar_senha(PROF, SENHA, "curta")
    assert contas.trocar_senha(PROF, SENHA, "nova-senha-123") is True
    assert contas.conta_da_sessao(t) is None
    assert contas.autenticar(PROF, "nova-senha-123") and contas.autenticar(PROF, SENHA) is None


def test_teto_de_pendentes(db, monkeypatch):
    monkeypatch.setattr(contas, "MAX_PENDENTES", 2)
    contas.cadastrar("prof.um", SENHA)
    contas.cadastrar("prof.dois", SENHA)
    with pytest.raises(contas.Ocupado):
        contas.cadastrar("prof.tres", SENHA)
    contas.aprovar("prof.um")
    contas.cadastrar("prof.tres", SENHA)


def test_listar_tem_lista_branca_de_campos(db):
    _ativa()
    contas.cadastrar("prof.bia", SENHA)
    lista = contas.listar()
    assert [c["usuario"] for c in lista] == ["prof.bia", PROF]  # pendentes primeiro
    assert all(set(c) == {"usuario", "estado", "admin", "criada_em", "ultimo_acesso"} for c in lista)


def test_cli_criar_admin_listar_redefinir(db, monkeypatch, capsys):
    senhas = iter(["senha-do-admin-1", "senha-do-admin-1"])
    monkeypatch.setattr(contas.getpass, "getpass", lambda prompt="": next(senhas))
    assert contas.main(["criar-admin", "Admin"]) == 0
    c = contas.listar()[0]
    assert (c["usuario"], c["estado"], c["admin"]) == ("admin", "ativa", True)
    assert "senha-do-admin-1" not in capsys.readouterr().out
    assert contas.main(["listar"]) == 0 and "admin" in capsys.readouterr().out
    assert contas.main(["redefinir", "admin"]) == 0
    provisoria = capsys.readouterr().out.split(": ", 1)[1].split()[0]
    assert contas.autenticar("admin", provisoria)


def test_cli_senhas_diferentes_e_sem_banco(db, monkeypatch, capsys):
    senhas = iter(["senha-do-admin-1", "outra-senha-123"])
    monkeypatch.setattr(contas.getpass, "getpass", lambda prompt="": next(senhas))
    assert contas.main(["criar-admin", "admin"]) == 1 and contas.listar() == []
    assert contas.main(["redefinir", "ninguem"]) == 1
    monkeypatch.setattr(contas, "CONTAS_DB", "")
    assert contas.main(["listar"]) == 2 and "CONTAS_DB" in capsys.readouterr().err
