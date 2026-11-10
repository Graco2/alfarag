"""Etapa 1 — Preparação do corpus.

Lê os PDFs (e o Markdown do PNEEI), extrai o texto POR PÁGINA, guarda o número
de página impresso quando ele existe, remove ruído (páginas iniciais do Manual
ABC, listas de referências) e corta em chunks com sobreposição. Os quadros de
Habilidades Essenciais (HE1–HE3) são lidos célula a célula: cada linha da
tabela vira um registro com ano, bimestre e código da habilidade.

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
# Código BNCC; os quadros de Habilidades Essenciais desdobram alguns com uma letra (EF02LP01A).
BNCC_RE = re.compile(r"\b(EF\d{2}LP\d{2}[A-Z]?)\b")
COD_HE = re.compile(r"\(\s*(E[FI]\d{2}LP\d{2}[A-Z]?)\s*\)")


def codigos(texto: str) -> list[str]:
    """Códigos citados no texto; um código desdobrado (EF02LP01A) também registra o código BNCC de origem."""
    achados = set(BNCC_RE.findall(texto))
    return sorted(achados | {c[:8] for c in achados})

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


def _celula(texto: str | None) -> str:
    t = unicodedata.normalize("NFC", texto or "")
    t = t.replace("", "•").replace("AnáliseAnálise", "Análise")
    t = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1-\2", t)
    return re.sub(r"\s+", " ", t).strip()


def extrair_habilidades(doc_id: str, arquivo: Path) -> list[Pagina]:
    """Quadros de Habilidades Essenciais: cada linha da tabela vira um registro autocontido.

    O texto corrido do PDF embaralha as colunas, então lemos célula por célula (recorte pela
    caixa da célula). Linha sem código na coluna de habilidades é continuação da anterior
    (a tabela atravessou a página). A seção registra o bimestre; o ano vai no rótulo do documento.
    """
    ano = doc_id[-1]
    d = pymupdf.open(arquivo)
    registros: list[dict] = []
    bimestre = None
    for i, p in enumerate(d):
        for tab in p.find_tables().tables:
            for row in tab.rows:
                c = [_celula(p.get_text("text", clip=pymupdf.Rect(bb))) if bb else "" for bb in row.cells]
                junto = " ".join(x for x in c if x)
                m = re.search(r"(\d)º\s*BIMESTRE", junto, re.I)
                if m and len(junto) < 40:
                    bimestre = m.group(1)
                    continue
                if not junto or (re.search(r"ENSINO FUNDAMENTAL|L[IÍ]NGUA ?PORTUGUESA", junto) and len(junto) < 60):
                    continue
                if c[0].upper().startswith("CAMPOS"):  # cabeçalho repetido
                    continue
                cols = [c[0], c[1] if len(c) > 1 else "", c[2] if len(c) > 2 else "", c[3] if len(c) > 3 else "",
                        " ".join(x for x in c[4:] if x)]
                if COD_HE.search(cols[2]) or not registros:
                    registros.append({"pdf_page": i + 1, "bimestre": bimestre, "cols": cols})
                else:
                    r = registros[-1]
                    r["cols"] = [f"{a} {b}".strip() for a, b in zip(r["cols"], cols)]
    paginas: list[Pagina] = []
    chave = None
    for r in registros:
        campo, pratica, hab, objeto, conteudo = r["cols"]
        texto = (f"Habilidade essencial do {ano}º ano, {r['bimestre']}º bimestre: {hab} Campo de atuação: {campo}. "
                 f"Prática de linguagem: {pratica}. Objeto de conhecimento: {objeto}."
                 + (f" Conteúdo: {conteudo}" if conteudo else ""))
        k = (r["pdf_page"], r["bimestre"])
        if k != chave:  # uma "página" por (página do PDF, bimestre): registros separados por linha em branco
            paginas.append(Pagina(doc_id, r["pdf_page"], str(r["pdf_page"]), "", f"{r['bimestre']}º bimestre"))
            chave = k
        paginas[-1].texto = (paginas[-1].texto + "\n\n" + texto).strip()
    return paginas


def extrair_videos(doc_id: str, pasta: Path) -> list[Pagina]:
    """Resumos de vídeo do grupo (um .md por vídeo, com front matter). Cada seção (##) vira uma 'página';
    a seção do trecho identifica vídeo, canal e título, e a minutagem [mm:ss] fica no próprio texto."""
    paginas: list[Pagina] = []
    for arq in sorted(pasta.glob("*.md")):
        bruto = arq.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", bruto, re.S)
        fm = {k: v.strip().strip('"') for k, v in re.findall(r"^(\w+):\s*(.*)$", m.group(1), re.M)} if m else {}
        corpo = bruto[m.end():] if m else bruto
        secao = f"vídeo {fm.get('id', arq.stem[:4])}, {fm.get('canal', '?')}, “{fm.get('titulo', '?')}”"
        for bloco in re.split(r"^## ", corpo, flags=re.M):
            if not bloco.strip():
                continue
            titulo, _, texto = bloco.partition("\n")
            titulo = re.sub(r"\s*\(.*?\)\s*$", "", titulo).strip()
            texto = limpar(texto)
            if len(texto) < 40:
                continue
            paginas.append(Pagina(doc_id, 0, "s/p", f"{titulo}: {texto}", secao,
                                  {"url": fm.get("url"), "relevancia": fm.get("relevancia")}))
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
            "codigos_bncc": codigos(texto),
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
        if d["id"].startswith("HE"):
            ps = extrair_habilidades(d["id"], arq)
        elif d["id"] == "VID":
            ps = extrair_videos(d["id"], arq)
        elif arq.suffix.lower() == ".pdf":
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
