"""Botão "Parar": quando o cliente desconecta no meio da resposta, o gerador tem de ser fechado.

Sem isso, o finally de gerar() em /api/perguntar não roda e a trava _GERACAO do modelo
local fica presa: o próximo usuário recebe "ocupado".
"""
import asyncio

import pytest
from starlette.requests import ClientDisconnect

from app.main import _StreamQueFecha


def _gerador(fechou: list):
    try:
        for i in range(10):
            yield f"{i}\n"
    finally:
        fechou.append(True)


async def _receive():
    await asyncio.sleep(3600)
    return {"type": "http.disconnect"}


def test_fecha_o_gerador_quando_o_cliente_desconecta():
    fechou, enviados = [], []

    async def send(msg):
        enviados.append(msg)
        if len(enviados) >= 3:  # cabeçalho + 2 pedaços; depois o cliente some
            raise OSError("cliente desconectou")

    async def cenario():
        resp = _StreamQueFecha(_gerador(fechou), media_type="application/x-ndjson")
        with pytest.raises(ClientDisconnect):
            await resp({"type": "http", "asgi": {"spec_version": "2.4"}}, _receive, send)
        # Verifica com o loop ainda rodando, como no servidor: ao fim do asyncio.run
        # o gerador seria fechado de qualquer jeito e o teste não detectaria o problema.
        return list(fechou)

    assert asyncio.run(cenario()) == [True]


def test_resposta_completa_continua_igual():
    fechou, corpo = [], []

    async def send(msg):
        if msg["type"] == "http.response.body":
            corpo.append(msg["body"])

    scope = {"type": "http", "asgi": {"spec_version": "2.4"}}
    asyncio.run(_StreamQueFecha(_gerador(fechou), media_type="application/x-ndjson")(scope, _receive, send))
    assert b"".join(corpo) == b"".join(f"{i}\n".encode() for i in range(10))
    assert fechou == [True]
