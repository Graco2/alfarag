"""Monta o artigo no modelo SIGE 2026 clonando os parágrafos-protótipo do próprio modelo.

Uso: python docs/build_docx.py <modelo.docx> <conteudo.json> <saida.docx>
O conteúdo é uma lista de blocos {"t": tipo, ...}. Tipos:
  titulo, autores, instituicao, resumo, palavras, secao, subsecao, p, nota, fig, legenda,
  tabela_titulo, tabela, refs_titulo, ref, vazio
Formatação inline em "p": **negrito**, *itálico*.
"""
from __future__ import annotations

import copy
import json
import re
import sys

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

# Protótipos localizados pelo texto do próprio modelo SIGE (robusto a índices).
PROTO_TEXTO = {
    "titulo": lambda t: t.startswith("Preparação de um Artigo"),
    "autores": lambda t: t.startswith("Primeiro Autor"),
    "instituicao": lambda t: t.startswith("1Instituto Tecnológico"),
    "resumo": lambda t: t.startswith("Resumo"),
    "palavras": lambda t: t.startswith("Palavras-Chave"),
    "secao": lambda t: t == "i. introdução",
    "p": lambda t: t.startswith("Este formato apresenta"),
    "subsecao": lambda t: t.startswith("A. Preparação do artigo"),
    "nota": lambda t: t.startswith("P. Autor"),
    "tabela_titulo": lambda t: t.startswith("tabela i."),
    "legenda": lambda t: t.startswith("Fig. 1."),
    "refs_titulo": lambda t: t == "referências",
    "ref": lambda t: t.startswith("G. Eason"),
}


def _limpar_runs(p):
    for r in list(p.findall(qn("w:r"))):
        p.remove(r)


def _run(rpr_modelo, texto, negrito=None, italico=None, sobrescrito=False):
    r = copy.deepcopy(rpr_modelo)  # um <w:r> modelo
    for t in r.findall(qn("w:t")):
        r.remove(t)
    for el in list(r):
        if el.tag in (qn("w:drawing"), qn("w:tab"), qn("w:br")):
            r.remove(el)
    rpr = r.find(qn("w:rPr"))
    if rpr is None:
        rpr = r.makeelement(qn("w:rPr"), {})
        r.insert(0, rpr)
    for tag, val in ((qn("w:b"), negrito), (qn("w:i"), italico)):
        if val is None:
            continue
        el = rpr.find(tag)
        if val and el is None:
            rpr.insert(0, rpr.makeelement(tag, {}))
        if not val and el is not None:
            rpr.remove(el)
    for va in rpr.findall(qn("w:vertAlign")):
        rpr.remove(va)
    if sobrescrito:
        v = rpr.makeelement(qn("w:vertAlign"), {qn("w:val"): "superscript"})
        rpr.append(v)
    t = r.makeelement(qn("w:t"), {qn("xml:space"): "preserve"})
    t.text = texto
    r.append(t)
    return r


def _segmentos(texto):
    """**negrito**, *itálico*, ^sobrescrito^"""
    out = []
    for parte in re.split(r"(\*\*.+?\*\*|\*[^*]+?\*|\^[^^]+?\^)", texto):
        if not parte:
            continue
        if parte.startswith("**"):
            out.append((parte[2:-2], True, None, False))
        elif parte.startswith("*"):
            out.append((parte[1:-1], None, True, False))
        elif parte.startswith("^"):
            out.append((parte[1:-1], None, None, True))
        else:
            out.append((parte, None, None, False))
    return out


class Montador:
    def __init__(self, modelo):
        self.doc = Document(modelo)
        corpo = self.doc.element.body
        ps = corpo.findall(qn("w:p"))
        def texto(p):
            return "".join(x.text or "" for x in p.iter(qn("w:t"))).strip()
        self.proto = {}
        for k, f in PROTO_TEXTO.items():
            self.proto[k] = copy.deepcopy(next(p for p in ps if f(texto(p))))
        self.proto["vazio"] = copy.deepcopy(ps[2])
        i_sec = next(i for i, p in enumerate(ps) if texto(p) == "i. introdução")
        self.proto["vazio_col"] = copy.deepcopy(ps[i_sec + 1])  # linha em branco do corpo em 2 colunas
        self.run_proto = {}
        for k, p in self.proto.items():
            rs = p.findall(qn("w:r"))
            self.run_proto[k] = rs[-1] if k in ("resumo", "palavras") and len(rs) > 2 else (rs[0] if rs else None)
        self.rotulo_proto = {k: copy.deepcopy(self.proto[k].findall(qn("w:r"))[0]) for k in ("resumo", "palavras")}
        self.tabela_proto = copy.deepcopy(corpo.findall(qn("w:tbl"))[0])
        # separa: mantém o parágrafo com a quebra de seção (cabeçalho em 1 coluna) e o sectPr final
        self.quebra = next(p for p in ps if p.find(qn("w:pPr")) is not None and p.find(qn("w:pPr")).find(qn("w:sectPr")) is not None)
        for el in list(corpo):
            if el.tag == qn("w:sectPr") or el is self.quebra:
                continue
            corpo.remove(el)
        self.corpo = corpo
        self.antes_quebra = True
        self._ultimo = "inicio"

    def _inserir(self, el):
        if self.antes_quebra:
            self.quebra.addprevious(el)
        else:
            self.corpo.find(qn("w:sectPr")).addprevious(el)

    def par(self, tipo, texto=""):
        if tipo == "vazio" and not self.antes_quebra:
            tipo = "vazio_col"
        if tipo in ("secao", "subsecao", "refs_titulo") and not self.antes_quebra and self._ultimo not in ("inicio", "vazio_col"):
            self._branco()
        p = copy.deepcopy(self.proto[tipo])
        _limpar_runs(p)
        rp = self.run_proto[tipo]
        if tipo in ("resumo", "palavras"):
            rot = copy.deepcopy(self.rotulo_proto[tipo])
            p.append(rot)
            p.append(_run(rp, " — "))
            for seg, b, i, s in _segmentos(texto):
                p.append(_run(rp, seg, b, i, s))
        elif tipo == "instituicao":
            for seg, b, i, s in _segmentos(texto):
                p.append(_run(rp, seg, b, i, s))
        elif rp is not None:
            for seg, b, i, s in _segmentos(texto):
                p.append(_run(rp, seg, b, i, s))
        self._inserir(p)
        self._ultimo = tipo
        if tipo in ("secao", "subsecao", "refs_titulo"):
            self._branco()
        return p

    def _branco(self):
        b = copy.deepcopy(self.proto["vazio_col"])
        _limpar_runs(b)
        self._inserir(b)
        self._ultimo = "vazio_col"

    def coluna_dupla(self):
        self.antes_quebra = False
        self._ultimo = "inicio"

    def figura(self, caminho, largura_cm):
        p = copy.deepcopy(self.proto["legenda"])
        _limpar_runs(p)
        self._inserir(p)
        from docx.text.paragraph import Paragraph
        par = Paragraph(p, self.doc._body)
        par.add_run().add_picture(caminho, width=Cm(largura_cm))
        return p

    def tabela(self, linhas, larguras_cm):
        """linhas[0] = cabeçalho. Constrói tabela simples 8 pt com bordas superior/inferior."""
        from docx.oxml import parse_xml
        ncol = len(linhas[0])
        grid = "".join(f'<w:gridCol w:w="{int(w * 567)}"/>' for w in larguras_cm)
        def cel(txt, w, neg=False, alinha="left"):
            b = "<w:b/>" if neg else ""
            return (f'<w:tc><w:tcPr><w:tcW w:w="{int(w * 567)}" w:type="dxa"/></w:tcPr><w:p><w:pPr><w:jc w:val="{alinha}"/><w:spacing w:before="0" w:after="0"/></w:pPr>'
                    f'<w:r><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>{b}<w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr><w:t xml:space="preserve">{_esc(txt)}</w:t></w:r></w:p></w:tc>')
        rows = []
        for k, linha in enumerate(linhas):
            cells = "".join(cel(str(x), larguras_cm[j], neg=(k == 0), alinha=("left" if j == 0 else "center")) for j, x in enumerate(linha))
            borda = '<w:trPr><w:tblHeader/></w:trPr>' if k == 0 else ""
            rows.append(f"<w:tr>{borda}{cells}</w:tr>")
        xml = (f'<w:tbl xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:tblPr><w:jc w:val="center"/>'
               f'<w:tblW w:w="{int(sum(larguras_cm) * 567)}" w:type="dxa"/>'
               '<w:tblBorders><w:top w:val="single" w:sz="6" w:space="0" w:color="000000"/><w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000"/>'
               '<w:insideH w:val="single" w:sz="2" w:space="0" w:color="999999"/></w:tblBorders>'
               '<w:tblCellMar><w:left w:w="57" w:type="dxa"/><w:right w:w="57" w:type="dxa"/></w:tblCellMar><w:tblLayout w:type="fixed"/></w:tblPr>'
               f'<w:tblGrid>{grid}</w:tblGrid>{"".join(rows)}</w:tbl>')
        tbl = parse_xml(xml)
        self._inserir(tbl)


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def montar(modelo, conteudo, saida, imagens_base="."):
    m = Montador(modelo)
    for b in conteudo:
        t = b["t"]
        if t == "colunas":
            m.coluna_dupla()
        elif t == "fig":
            m.figura(f"{imagens_base}/{b['arquivo']}", b.get("largura_cm", 8.4))
        elif t == "tabela":
            m.tabela(b["linhas"], b["larguras_cm"])
        else:
            m.par(t, b.get("texto", ""))
    # Quebra de seção contínua no fim: o Word (e o LibreOffice) equilibram as duas colunas da última página.
    final = m.corpo.find(qn("w:sectPr"))
    quebra = copy.deepcopy(final)
    for t in quebra.findall(qn("w:type")):
        quebra.remove(t)
    tipo = quebra.makeelement(qn("w:type"), {qn("w:val"): "continuous"})
    quebra.insert(0, tipo)
    p = m.corpo.makeelement(qn("w:p"), {})
    ppr = p.makeelement(qn("w:pPr"), {})
    ppr.append(quebra)
    p.append(ppr)
    final.addprevious(p)
    # metadados
    cp = m.doc.core_properties
    cp.title = conteudo[0].get("texto", "")
    cp.author = "Grupo Imeanos no ITA"
    m.doc.save(saida)


if __name__ == "__main__":
    modelo, conteudo, saida = sys.argv[1:4]
    import os
    montar(modelo, json.load(open(conteudo, encoding="utf-8")), saida, os.path.dirname(os.path.abspath(conteudo)))
    print("ok", saida)
