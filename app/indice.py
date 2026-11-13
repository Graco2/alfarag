"""Índice híbrido: BM25 (lexical) + embeddings densos (bge-m3 via Ollama), fundidos por RRF."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi

from .config import CANDIDATOS, CONDICOES, INDEX_DIR, MODELO_EMBED, RAIZ, RRF_K
from .llm import embed

STOP = set("""a o as os um uma uns umas de do da dos das no na nos nas em por para com sem que se e ou
ao aos à às é são ser ter tem como mais mas ele ela eles elas seu sua seus suas meu minha isso este esta
esse essa não sim já foi era há pelo pela pelos pelas lhe the of and to in for is on with as by an be are
this that it or from at was were which""".split())


def normalizar(texto: str) -> list[str]:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    toks = re.findall(r"[a-z0-9]+", t)
    return [w for w in toks if w not in STOP and len(w) > 1]


@dataclass
class Indice:
    exp: str
    chunks: list[dict]
    emb: np.ndarray  # (n, d), normalizado
    bm25: BM25Okapi

    def buscar(self, pergunta: str, docs_permitidos: list[str], candidatos: int = CANDIDATOS,
               q_vec: np.ndarray | None = None) -> list[dict]:
        """Retorna a lista fundida (RRF) com as duas pontuações originais em cada item.

        `q_vec`: vetor da pergunta já calculado por `vetor_pergunta`. Permite fazer várias buscas (uma por grupo)
        com um único embedding. Sem ele, o vetor é calculado aqui, como antes."""
        mascara = np.array([c["doc"] in docs_permitidos for c in self.chunks])
        if not mascara.any():
            return []
        # Densa
        q = vetor_pergunta(pergunta) if q_vec is None else q_vec
        cos = self.emb @ q
        cos_m = np.where(mascara, cos, -np.inf)
        ordem_densa = [int(i) for i in np.argsort(-cos_m)[:candidatos] if np.isfinite(cos_m[i])]
        # Lexical
        bm = self.bm25.get_scores(normalizar(pergunta))
        bm_m = np.where(mascara, bm, -np.inf)
        ordem_bm = [int(i) for i in np.argsort(-bm_m)[:candidatos] if np.isfinite(bm_m[i]) and bm_m[i] > 0]
        # Fusão por posição (Reciprocal Rank Fusion)
        rrf: dict[int, float] = {}
        for lista in (ordem_densa, ordem_bm):
            for pos, i in enumerate(lista):
                rrf[i] = rrf.get(i, 0.0) + 1.0 / (RRF_K + pos + 1)
        rank_d = {i: p + 1 for p, i in enumerate(ordem_densa)}
        rank_b = {i: p + 1 for p, i in enumerate(ordem_bm)}
        saida = []
        for i, s in sorted(rrf.items(), key=lambda kv: -kv[1]):
            c = dict(self.chunks[i])
            c.update({
                "rrf": round(s, 5),
                "cos": round(float(cos[i]), 4),
                "bm25": round(float(bm[i]), 3),
                "rank_denso": rank_d.get(i),
                "rank_bm25": rank_b.get(i),
            })
            saida.append(c)
        return saida


def vetor_pergunta(pergunta: str) -> np.ndarray:
    """Embedding normalizado da pergunta (bge-m3 no Ollama local). Calculado uma vez e reaproveitado nas buscas."""
    q = np.array(embed([pergunta])[0], dtype=np.float32)
    q /= np.linalg.norm(q) + 1e-9
    return q


@lru_cache(maxsize=1)
def _grupo_por_doc() -> dict[str, str]:
    """Lê o campo 'grupo' de corpus/documentos.json: id do documento -> 'oficial' | 'experiencia'."""
    docs = json.loads((RAIZ / "corpus" / "documentos.json").read_text(encoding="utf-8"))
    return {d["id"]: d["grupo"] for d in docs}


def grupo_do_doc(doc: str) -> str:
    return _grupo_por_doc()[doc]


def docs_do_grupo(grupos: str | tuple[str, ...], condicao: str) -> list[str]:
    """Documentos da condição que pertencem ao(s) grupo(s), na ordem da condição.
    Ex.: docs_do_grupo('experiencia', 'C6') -> ['VID'];
         docs_do_grupo(('oficial', 'cientifico'), 'C6') -> as referências."""
    grupos = (grupos,) if isinstance(grupos, str) else tuple(grupos)
    return [d for d in CONDICOES[condicao] if grupo_do_doc(d) in grupos]


def _arq_emb(exp: str) -> str:
    return str(INDEX_DIR / f"emb_{exp}_{MODELO_EMBED.replace(':', '-')}.npy")


def gerar_embeddings(exp: str, lote: int = 32) -> None:
    chunks = [json.loads(l) for l in (INDEX_DIR / f"chunks_{exp}.jsonl").open(encoding="utf-8")]
    vetores: list[list[float]] = []
    for i in range(0, len(chunks), lote):
        textos = [f"{c['secao']} {c['texto']}".strip()[:6000] for c in chunks[i : i + lote]]
        vetores.extend(embed(textos))
        print(f"\r  embeddings {exp}: {min(i + lote, len(chunks))}/{len(chunks)}", end="", flush=True)
    print()
    m = np.array(vetores, dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    np.save(_arq_emb(exp), m.astype(np.float16))


@lru_cache(maxsize=4)
def carregar(exp: str) -> Indice:
    chunks = [json.loads(l) for l in (INDEX_DIR / f"chunks_{exp}.jsonl").open(encoding="utf-8")]
    emb = np.load(_arq_emb(exp)).astype(np.float32)
    if len(emb) != len(chunks):
        raise RuntimeError(f"Índice {exp} inconsistente: {len(chunks)} chunks, {len(emb)} vetores")
    bm25 = BM25Okapi([normalizar(f"{c['secao']} {c['texto']}") for c in chunks])
    return Indice(exp, chunks, emb, bm25)


def rotulo_pagina(c: dict) -> str:
    if c["pagina_ini"] == "s/p":
        return "s/p"
    if c["pagina_ini"] == c["pagina_fim"]:
        return f"p. {c['pagina_ini']}"
    return f"p. {c['pagina_ini']}–{c['pagina_fim']}"
