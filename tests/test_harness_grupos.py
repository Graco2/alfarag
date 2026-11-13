"""Harness de saída nos modos da tabela de decisão (prompt v2.0).

Janela usada nos testes: [1] BNCC (documento oficial), [2] RAMLI (produção científica), [3] VID (relato).
"""
from app import harness

TRECHOS = [
    {"doc": "BNCC", "texto": "Habilidade EF02LP01: utilizar grafia correta."},
    {"doc": "RAMLI", "texto": "Estudo sobre consciência fonológica."},
    {"doc": "VID", "texto": "Relato de prática com rimas em sala."},
]
SO_RELATOS = [{"doc": "VID", "texto": "Relato A."}, {"doc": "VID", "texto": "Relato B."}]

MISTO_OK = """**Orientação**
Trabalhe a consciência fonológica [2].

**Atividade em sala**
Jogo de rimas [1].

**Acompanhamento**
Registro semanal [2].

**Relatos de experiência**
O canal Exemplo relata que usa rimas [3].
*Fundamentado nas referências: Sim — produção científica [2]*

**Fontes**
[1], [2], [3]"""


def _verificar(texto, trechos=TRECHOS, modo="referencia+experiencia", diag=False):
    return harness.verificar_saida(texto, trechos, diag, "stop", modo)


def test_misto_correto_nao_gera_alerta():
    final, v = _verificar(MISTO_OK)
    assert final == MISTO_OK
    assert v.alertas == [] and v.veredito == "ok"


def test_fundamentacao_que_cita_so_relato_vira_nao_encontrado():
    texto = MISTO_OK.replace("Sim — produção científica [2]", "Sim — documento oficial [3]")
    final, v = _verificar(texto)
    assert "*Fundamentado nas referências: Não encontrado nas referências*" in final
    assert v.fundamentacao_corrigida == 1 and v.veredito == "alertas"


def test_fundamentacao_sem_numero_vira_nao_encontrado():
    final, v = _verificar(MISTO_OK.replace("Sim — produção científica [2]", "Em parte — produção científica"))
    assert "Não encontrado nas referências*" in final and v.fundamentacao_corrigida == 1


def test_fundamentacao_nao_encontrado_passa_sem_mudanca():
    texto = MISTO_OK.replace("Sim — produção científica [2]", "Não encontrado nas referências")
    final, v = _verificar(texto)
    assert final == texto and v.fundamentacao_corrigida == 0


def test_tipo_de_referencia_divergente_gera_alerta_sem_reescrever():
    texto = MISTO_OK.replace("Sim — produção científica [2]", "Sim — documento oficial [2]")
    final, v = _verificar(texto)
    assert final == texto
    assert v.fundamentacao_tipo_divergente == 1 and v.fundamentacao_corrigida == 0


def test_dois_tipos_com_as_fontes_certas_nao_divergem():
    texto = MISTO_OK.replace("Sim — produção científica [2]", "Sim — documento oficial [1]; produção científica [2]")
    _, v = _verificar(texto)
    assert v.fundamentacao_tipo_divergente == 0 and v.alertas == []


def test_relato_citado_na_orientacao_gera_alerta():
    _, v = _verificar(MISTO_OK.replace("consciência fonológica [2]", "consciência fonológica [3]"))
    assert v.relatos_fora_da_secao == [3]


def test_secao_de_relatos_ausente_gera_alerta():
    texto = MISTO_OK.split("**Relatos de experiência**")[0]
    _, v = _verificar(texto)
    assert v.secao_relatos_ausente


def test_so_experiencia_com_aviso_do_modelo():
    texto = ("Esta orientação vem de relatos de experiência e não foi encontrada nas referências da base.\n\n"
             "**Relatos de experiência**\nO canal A relata [1].\n*Fundamentado nas referências: Não encontrado nas referências*")
    final, v = _verificar(texto, SO_RELATOS, "experiencia")
    assert final == texto and not v.aviso_experiencia_forcado and v.alertas == []


def test_so_experiencia_sem_aviso_o_sistema_insere():
    texto = "**Relatos de experiência**\nO canal A relata [1].\n*Fundamentado nas referências: Não encontrado nas referências*"
    final, v = _verificar(texto, SO_RELATOS, "experiencia")
    assert final.startswith(harness.FRASE_SO_EXPERIENCIA) and v.aviso_experiencia_forcado


def test_so_experiencia_nao_aceita_sim():
    texto = ("Esta orientação vem de relatos de experiência e não foi encontrada nas referências da base.\n\n"
             "O canal A relata [1].\n*Fundamentado nas referências: Sim — documento oficial [2]*")
    final, v = _verificar(texto, SO_RELATOS, "experiencia")
    assert "Fundamentado nas referências: Não encontrado nas referências" in final and v.fundamentacao_corrigida == 1


def test_aviso_de_diagnostico_continua_sendo_a_primeira_linha():
    texto = "**Relatos de experiência**\nO canal A relata [1]."
    final, v = _verificar(texto, SO_RELATOS, "experiencia", diag=True)
    assert final.startswith(harness.FRASE_DIAGNOSTICO) and v.ressalva_forcada and v.aviso_experiencia_forcado


def test_fluxo_antigo_nao_aplica_as_regras_novas():
    texto = "Resposta [3].\n*Fundamentado nas referências: Sim — documento oficial [3]*"
    for modo in (None, "unico"):
        final, v = _verificar(texto, modo=modo)
        assert final == texto and v.fundamentacao_corrigida == 0


def test_regras_antigas_continuam_valendo_nos_modos_novos():
    final, v = _verificar(MISTO_OK.replace("Jogo de rimas [1].", "Jogo de rimas [9]. EF99LP99"))
    assert v.citacoes_invalidas == [9] and v.codigos_removidos == ["EF99LP99"]
    assert "[9]" not in final and "EF99LP99" not in final
