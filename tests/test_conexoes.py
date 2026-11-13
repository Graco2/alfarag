import json
import os
import stat

import httpx
import pytest

from app import conexoes
from .conftest import CHAVE


def test_arquivo_600_e_chave_mascarada():
    conexoes.salvar("deepseek", nova_chave=CHAVE)
    assert stat.S_IMODE(os.stat(conexoes.CONEXOES_ARQ).st_mode) == 0o600
    pub = conexoes.publico()[0]
    assert pub["configurada"] and pub["origem"] == "arquivo"
    assert CHAVE not in json.dumps(pub) and pub["chave_mascarada"].startswith("sk-")
    assert pub["url_base"] == "https://api.deepseek.com"


def test_env_tem_prioridade(monkeypatch):
    conexoes.salvar("deepseek", nova_chave=CHAVE)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-do-ambiente-xxxxxxxx")
    assert conexoes.chave("deepseek") == "sk-do-ambiente-xxxxxxxx"
    assert conexoes.publico()[0]["origem"] == "ambiente"


def test_salvar_sem_chave_mantem_a_atual():
    conexoes.salvar("deepseek", nova_chave=CHAVE)
    conexoes.salvar("deepseek", url="https://api.deepseek.com/")
    assert conexoes.chave("deepseek") == CHAVE and conexoes.url_base("deepseek") == "https://api.deepseek.com"


@pytest.mark.parametrize("url", ["ftp://x.com", "http://api.exemplo.com", "https://u:p@x.com", "https://x.com/?k=1", "x"])
def test_url_invalida(url):
    with pytest.raises(ValueError):
        conexoes.salvar("deepseek", url=url)


def test_http_so_para_localhost():
    conexoes.salvar("deepseek", url="http://127.0.0.1:9999/v1")
    assert conexoes.url_base("deepseek") == "http://127.0.0.1:9999/v1"


def test_remover_e_modelos_so_se_configurado():
    assert conexoes.modelos_remotos() == []
    conexoes.salvar("deepseek", nova_chave=CHAVE)
    assert conexoes.modelos_remotos() == ["deepseek:deepseek-flash", "deepseek:deepseek-v4-pro"]
    conexoes.remover("deepseek")
    assert conexoes.modelos_remotos() == [] and not conexoes.configurada("deepseek")


def test_sanitizar():
    conexoes.salvar("deepseek", nova_chave=CHAVE)
    t = conexoes.sanitizar(f"falhou com {CHAVE} e Bearer abc.def-123 e sk-outraChave123456")
    assert CHAVE not in t and "abc.def" not in t and "outraChave" not in t


def _cliente(fn):
    return httpx.Client(transport=httpx.MockTransport(fn))


def test_testar_ok_e_erros():
    assert conexoes.testar("deepseek")["ok"] is False  # sem chave
    conexoes.salvar("deepseek", nova_chave=CHAVE)
    vistos = []

    def ok(r):
        vistos.append(r)
        return httpx.Response(200, json={"data": [{"id": "deepseek-flash"}]})

    r = conexoes.testar("deepseek", _cliente(ok))
    assert r["ok"] and r["modelos"] == ["deepseek-flash"] and str(vistos[0].url) == "https://api.deepseek.com/models"
    r = conexoes.testar("deepseek", _cliente(lambda q: httpx.Response(401, text=CHAVE)))
    assert not r["ok"] and "401" in r["mensagem"] and CHAVE not in json.dumps(r)
