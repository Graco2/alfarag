"""Etapa 1 — Preparação do corpus.

Lê os PDFs (e o Markdown do PNEEI), extrai o texto POR PÁGINA, guarda o número
de página impresso quando ele existe, remove ruído (páginas iniciais do Manual
ABC, listas de referências) e corta em chunks com sobreposição.

Cada chunk carrega metadados suficientes para a citação: documento, página
inicial/final, seção (capítulo/parte do Manual ABC) e os códigos BNCC que
aparecem literalmente no texto.

Uso:
    python scripts/preparar_corpus.py --exp E2            # 512 tokens, 15 %
    python scripts/preparar_corpus.py --exp todos --embed # gera E1..E4 + embeddings
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.config import EXPERIMENTOS, INDEX_DIR, aprox_tokens  # noqa: E402

CORPUS = RAIZ / "corpus"
BNCC_RE = re.compile(r"\b(EF\d{2}LP\d{2})\b")

# Manual ABC: capítulo -> (página impressa inicial, título). Fonte: índice do manual (p. XIV–XVI).
ABC_CAPITULOS = {
    1: (1, "Introdução ao Manual"),
    2: (13, "Políticas de Leitura"),
    3: (40, "Do Som à Linguagem"),
    4: (63, "As Bases Neurobiológicas da Leitura"),
    5: (87, "Conhecimento da Língua: Fonologia e Ortografia do Português do Brasil"),
    6: (107, "Ensino e Aprendizagem da Leitura: Fundamentos e Aplicações"),
    7: (129, "Modelo RTI na Alfabetização"),
    8: (155, "Literacia Emergente em Contexto Familiar"),
    9: (173, "Literacia Emergente no Jardim de Infância"),
    10: (194, "O Desenvolvimento do Vocabulário"),
    11: (219, "Consciência Fonológica e Conhecimento das Letras"),
    12: (244, "Aprender a Escrever Palavras"),
    13: (257, "Compreendendo o Ato de Ler: o Modelo Simples de Leitura"),
    14: (288, "Métodos Fónicos Sistemáticos no Ensino da Leitura"),
    15: (317, "A Importância da Consciência Fonêmica"),
    16: (336, "Fluência na Leitura Oral"),
    17: (361, "A Compreensão na Leitura: Investigação e Ensino"),
    18: (378, "Aprendizagem da Ortografia"),
    19: (401, "A Caligrafia como Alavanca do Desenvolvimento da Escrita"),
    20: (417, "O Feitiço das Formas das Palavras"),
    21: (441, "Perturbação do Desenvolvimento da Linguagem (PDL)"),
    22: (472, "A Dislexia e a Alfabetização"),
    23: (501, "Compreendendo a Disgrafia"),
}
ABC_PARTES = {"A": range(2, 8), "B": range(8, 13), "C": range(13, 21), "D": range(21, 24)}
ABC_OFFSET_PDF = 26  # página impressa = página do PDF - 26
ABC_PRIMEIRA_PAGINA_PDF = 27  # antes disso: capa, notas, biografias
PAGINA_IMPRESSA = {"BNCC", "HALL", "RAMLI"}


def abc_capitulo(pagina_impressa: int) -> int:
    cap = 1
    for n, (ini, _) in ABC_CAPITULOS.items():
        if pagina_impressa >= ini:
            cap = n
    return cap


def abc_parte(cap: int) -> str:
    for p, r in ABC_PARTES.items():
        if cap in r:
            return p
    return "-"


@dataclass
class Pagina:
    doc: str
    pdf_page: int
    pagina: str  # número impresso (ou da página do PDF, quando não há)
    texto: str
    secao: str = ""
    meta: dict = field(default_factory=dict)


def limpar(texto: str) -> str:
    texto = unicodedata.normalize("NFC", texto)
    texto = texto.replace("­", "").replace("\t", " ").replace("\x07", " ")
    texto = re.sub(r"(\w)-\n(\w)", r"\1\2", texto)  # hifenização de fim de linha
    texto = re.sub(r"[  ]+", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def numero_impresso(texto: str) -> str | None:
    for linha in texto.splitlines()[:8]:
        linha = linha.strip()
        m = re.fullmatch(r"(?:Page\s+)?(\d{1,4})", linha)
        if m:
            return m.group(1)
    return None


INICIO_REFERENCIAS = re.compile(r"^\s*(Referências( Bibliográficas)?|REFERÊNCIAS|References|REFERENCES)\s*$", re.M)


def extrair_pdf(doc_id: str, arquivo: Path) -> list[Pagina]:
    d = pymupdf.open(arquivo)
    paginas: list[Pagina] = []
    em_referencias = False
    cap_atual = None
    for i, p in enumerate(d):
        bruto = p.get_text()
        n = numero_impresso(bruto)
        if doc_id == "ABC":
            if i + 1 < ABC_PRIMEIRA_PAGINA_PDF:
                continue
            impressa = i + 1 - ABC_OFFSET_PDF
            cap = abc_capitulo(impressa)
            if cap != cap_atual:  # novo capítulo: volta a aceitar texto
                em_referencias, cap_atual = False, cap
            secao = f"Parte {abc_parte(cap)}, Cap. {cap} — {ABC_CAPITULOS[cap][1]}"
            pagina = str(impressa)
        else:
            secao = ""
            # Paginação impressa confiável só nestes; nos demais usa a página do PDF.
            pagina = (n if doc_id in PAGINA_IMPRESSA else None) or str(i + 1)
        texto = limpar(bruto)
        if em_referencias:
            continue
        m = INICIO_REFERENCIAS.search(texto)
        if m:
            texto = texto[: m.start()].strip()
            em_referencias = True
        if len(texto) < 40:
            continue
        paginas.append(Pagina(doc_id, i + 1, pagina, texto, secao))
    return paginas


def extrair_markdown(doc_id: str, arquivo: Path) -> list[Pagina]:
    """Sem paginação: cada seção (#, ##) vira uma 'página' identificada pelo título."""
    bruto = arquivo.read_text(encoding="utf-8")
    partes = re.split(r"^(#{1,3} .+)$", bruto, flags=re.M)
    paginas: list[Pagina] = []
    titulo = "Introdução"
    for bloco in partes:
        if re.match(r"^#{1,3} ", bloco):
            titulo = bloco.lstrip("# ").strip()[:120]
            continue
        texto = limpar(bloco)
        if len(texto) < 40:
            continue
        paginas.append(Pagina(doc_id, 0, "s/p", texto, f"Seção: {titulo}"))
    return paginas


def paragrafos(pag: Pagina) -> list[str]:
    # Junta linhas quebradas pelo layout do PDF em parágrafos.
    blocos = re.split(r"\n\s*\n|(?<=[.:;!?])\n(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ(•\-])", pag.texto)
    out = []
    for b in blocos:
        b = re.sub(r"\s*\n\s*", " ", b).strip()
        if b:
            out.append(b)
    return out


def chunkar(paginas: list[Pagina], tam: int | None, sobreposicao: float, por_secao: bool = False) -> list[dict]:
    """Agrupa parágrafos até `tam` tokens (aprox.), mantendo a faixa de páginas.

    por_secao=True (E4): nunca atravessa a fronteira de seção/capítulo e usa o
    tamanho variável da própria seção (com teto de 1024 tokens para caber na janela).
    """
    chunks: list[dict] = []
    teto = tam or 1024
    buf: list[tuple[str, Pagina]] = []

    def emitir():
        if not buf:
            return
        texto = " ".join(t for t, _ in buf)
        pags = [p for _, p in buf]
        p0, p1 = pags[0], pags[-1]
        chunks.append({
            "doc": p0.doc,
            "pagina_ini": p0.pagina,
            "pagina_fim": p1.pagina,
            "pdf_page": p0.pdf_page,
            "secao": p0.secao,
            "codigos_bncc": sorted(set(BNCC_RE.findall(texto))),
            "tokens": aprox_tokens(texto),
            "texto": texto,
        })

    for doc in sorted({p.doc for p in paginas}, key=lambda d: [p.doc for p in paginas].index(d)):
        buf = []
        secao_atual = None
        for pag in (p for p in paginas if p.doc == doc):
            if por_secao and pag.secao != secao_atual and buf:
                emitir()
                buf = []
            secao_atual = pag.secao
            for par in paragrafos(pag):
                # parágrafo gigante: quebra por frases
                pedacos = [par] if aprox_tokens(par) <= teto else re.split(r"(?<=[.!?])\s+", par)
                for ped in pedacos:
                    atual = sum(aprox_tokens(t) for t, _ in buf)
                    if buf and atual + aprox_tokens(ped) > teto:
                        emitir()
                        if por_secao or sobreposicao <= 0:
                            buf = []
                        else:
                            # mantém o final do chunk anterior como sobreposição
                            alvo = int(teto * sobreposicao)
                            manter: list[tuple[str, Pagina]] = []
                            acum = 0
                            for t, p in reversed(buf):
                                if acum >= alvo:
                                    break
                                manter.insert(0, (t, p))
                                acum += aprox_tokens(t)
                            buf = manter
                    buf.append((ped, pag))
        emitir()
    for i, c in enumerate(chunks):
        c["id"] = f"{c['doc']}-{i:05d}"
    return chunks


def carregar_paginas() -> list[Pagina]:
    docs = json.loads((CORPUS / "documentos.json").read_text(encoding="utf-8"))
    paginas: list[Pagina] = []
    for d in docs:
        arq = CORPUS / d["arquivo"]
        if arq.suffix.lower() == ".pdf":
            ps = extrair_pdf(d["id"], arq)
        else:
            ps = extrair_markdown(d["id"], arq)
        print(f"  {d['id']:<6} {len(ps):>4} páginas/seções úteis")
        paginas.extend(ps)
    return paginas


def gerar(exp: str, paginas: list[Pagina], embed: bool) -> None:
    cfg = EXPERIMENTOS[exp]
    chunks = chunkar(paginas, cfg["tokens"], cfg["sobreposicao"], por_secao=cfg["tokens"] is None)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    destino = INDEX_DIR / f"chunks_{exp}.jsonl"
    with destino.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    por_doc: dict[str, int] = {}
    for c in chunks:
        por_doc[c["doc"]] = por_doc.get(c["doc"], 0) + 1
    print(f"{exp}: {len(chunks)} chunks -> {destino.name}  {por_doc}")
    if embed:
        from app.indice import gerar_embeddings
        gerar_embeddings(exp)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", default="E2", help="E1|E2|E3|E4|todos")
    ap.add_argument("--embed", action="store_true", help="também calcula os embeddings (Ollama)")
    a = ap.parse_args()
    print("Extraindo páginas…")
    paginas = carregar_paginas()
    exps = list(EXPERIMENTOS) if a.exp == "todos" else [a.exp]
    for e in exps:
        gerar(e, paginas, a.embed)


if __name__ == "__main__":
    main()
