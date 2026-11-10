"""Harness — regras determinísticas em volta do modelo.

Antes do modelo (o que o sistema impede):
  * pergunta vazia/longa demais, dados pessoais (CPF, telefone, e-mail) -> bloqueio;
  * pedido de diagnóstico -> modo ressalva (instrução extra + verificação na saída);
  * fontes que não cobrem a pergunta -> recusa SEM chamar o modelo.
Depois do modelo (o que o sistema obriga):
  * citação [n] tem de apontar para um trecho que entrou na janela;
  * código BNCC citado tem de existir literalmente em um trecho recuperado;
  * em modo ressalva, a resposta tem de declarar que não faz diagnóstico.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .config import LIMIAR_COBERTURA, MAX_PERGUNTA_CHARS

BNCC_RE = re.compile(r"\b(EF\d{2}LP\d{2})\b")
CITA_RE = re.compile(r"\[(\d{1,2}(?:\s*[,;]\s*\d{1,2})*)\]")

_PII = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "CPF"),
    (re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b"), "telefone"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "e-mail"),
]

_TRANSTORNOS = r"(dislex\w*|tdah|tea\b|autis\w*|transtorno\w*|disgraf\w*|discalcul\w*|d[ée]fici\w* de aten)"
_PEDE_DIAG = [
    re.compile(r"\b(tem|teria|é|e|seria|será|sera|possui|apresenta|indica|significa|sinal de)\b[^?.!]{0,60}\b" + _TRANSTORNOS + r"[^.!]{0,40}\?", re.I),
    re.compile(r"\b(diagnostic\w*|laudo)\b[^.!]{0,60}\?", re.I),
    re.compile(r"\b(diagnosticar|dar (o |um )?diagn[óo]stico|fechar (o |um )?diagn[óo]stico)\b", re.I),
]
_NEGA_DIAG = re.compile(
    r"(n[ãa]o (faz|fa[çc]o|realiza|realizo|pode|posso|[ée] poss[ií]vel|cabe)\w*[^.]{0,80}diagn[óo]stic"
    r"|sem (fazer|realizar) diagn[óo]stic|n[ãa]o (confirmam?|permitem?|indicam?|significam?)[^.]{0,60}" + _TRANSTORNOS
    + r"|n[ãa]o [ée] (poss[ií]vel|adequado) (concluir|afirmar|atribuir)|avalia[çc][ãa]o (profissional|especializada))",
    re.I,
)
FRASE_DIAGNOSTICO = (
    "> **Aviso do sistema:** este assistente não faz diagnóstico de dislexia, TDAH, TEA ou outros transtornos. "
    "Só uma avaliação profissional especializada pode concluir isso; abaixo há apenas orientação pedagógica."
)
FRASE_SEM_COBERTURA = (
    "Os documentos da base não trazem evidência suficiente sobre isso. "
    "O assistente cobre alfabetização em Língua Portuguesa no 2º e 3º anos (BNCC, Manual ABC e artigos sobre dislexia). "
    "Reformule a pergunta dentro desse escopo ou consulte a coordenação pedagógica."
)


@dataclass
class Entrada:
    ok: bool
    motivo: str = ""
    mensagem: str = ""
    pede_diagnostico: bool = False


def checar_entrada(pergunta: str) -> Entrada:
    p = pergunta.strip()
    if len(p) < 8:
        return Entrada(False, "pergunta_vazia", "Escreva a pergunta com um pouco mais de contexto (ano, dificuldade observada).")
    if len(p) > MAX_PERGUNTA_CHARS:
        return Entrada(False, "pergunta_longa", f"A pergunta passou de {MAX_PERGUNTA_CHARS} caracteres. Resuma o caso.")
    for rx, nome in _PII:
        if rx.search(p):
            return Entrada(False, "dado_pessoal", f"A pergunta parece conter dado pessoal ({nome}). Remova-o: o assistente não precisa identificar o aluno (LGPD).")
    pede = any(rx.search(p) for rx in _PEDE_DIAG)
    return Entrada(True, pede_diagnostico=pede)


@dataclass
class Cobertura:
    coberta: bool
    melhor_cos: float
    limiar: float = LIMIAR_COBERTURA


def checar_cobertura(candidatos: list[dict]) -> Cobertura:
    melhor = max((c["cos"] for c in candidatos), default=0.0)
    return Cobertura(melhor >= LIMIAR_COBERTURA, round(melhor, 4))


@dataclass
class Verificacao:
    citacoes_validas: list[int] = field(default_factory=list)
    citacoes_invalidas: list[int] = field(default_factory=list)
    codigos_ok: list[str] = field(default_factory=list)
    codigos_removidos: list[str] = field(default_factory=list)
    sem_citacao: bool = False
    modo_ressalva: bool = False
    ressalva_forcada: bool = False
    truncada: bool = False
    veredito: str = "ok"
    alertas: list[str] = field(default_factory=list)

    def dict(self) -> dict:
        return asdict(self)


def verificar_saida(resposta: str, trechos: list[dict], pede_diagnostico: bool, done_reason: str | None) -> tuple[str, Verificacao]:
    v = Verificacao(modo_ressalva=pede_diagnostico, truncada=(done_reason == "length"))
    texto = resposta

    # 1) Citações [n] (ou [n, m]) precisam existir na janela.
    k = len(trechos)
    usadas = sorted({int(n) for g in CITA_RE.findall(texto) for n in re.split(r"\s*[,;]\s*", g)})
    v.citacoes_validas = [n for n in usadas if 1 <= n <= k]
    v.citacoes_invalidas = [n for n in usadas if not 1 <= n <= k]
    if v.citacoes_invalidas:
        def _filtra(m: re.Match) -> str:
            ok = [n for n in re.split(r"\s*[,;]\s*", m.group(1)) if 1 <= int(n) <= k]
            return f"[{', '.join(ok)}]" if ok else ""
        texto = CITA_RE.sub(_filtra, texto)
        v.alertas.append(f"Citação para fonte inexistente removida: {v.citacoes_invalidas}")
    if not v.citacoes_validas:
        v.sem_citacao = True
        v.alertas.append("A resposta não cita nenhuma fonte recuperada.")

    # 2) Códigos BNCC precisam aparecer literalmente em algum trecho recuperado.
    no_contexto = set()
    for c in trechos:
        no_contexto.update(BNCC_RE.findall(c["texto"]))
    citados = sorted(set(BNCC_RE.findall(texto)))
    v.codigos_ok = [c for c in citados if c in no_contexto]
    v.codigos_removidos = [c for c in citados if c not in no_contexto]
    if v.codigos_removidos:
        texto = BNCC_RE.sub(lambda m: m.group(1) if m.group(1) in no_contexto else "[código BNCC removido pelo sistema: não consta nas fontes]", texto)
        v.alertas.append(f"Código(s) BNCC fora das fontes removido(s): {', '.join(v.codigos_removidos)}")

    # 3) Modo ressalva: a resposta tem de negar o diagnóstico; se não negar, o sistema força o aviso.
    if pede_diagnostico and not _NEGA_DIAG.search(texto):
        texto = FRASE_DIAGNOSTICO + "\n\n" + texto
        v.ressalva_forcada = True
        v.alertas.append("O modelo não declarou o limite de diagnóstico; o sistema inseriu o aviso.")

    if v.truncada:
        v.alertas.append("Resposta cortada pelo limite de tokens.")

    v.veredito = "ok" if not v.alertas else "alertas"
    return texto, v
