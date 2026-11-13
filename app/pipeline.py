"""Orquestra um turno: entrada -> recuperação -> janela de contexto -> modelo -> verificação -> traço."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Iterator

from . import conexoes, harness
from .config import (CASCATA, CONDICAO, CONDICOES, EXPERIMENTO, EXPERIMENTOS, GRUPOS, LIMIAR_EXPERIENCIA,
                     LIMIAR_RESPALDO, MODELO_EMBED, MODELO_LLM, NUM_CTX, ORCAMENTO_CONTEXTO, RAIZ, REFERENCIAS,
                     TEMPERATURA, TOP_K_GRUPO, TRACOS_DIR, aprox_tokens)
from .indice import carregar, docs_do_grupo, grupo_do_doc, rotulo_pagina, vetor_pergunta
from .llm import chat_stream, digest, resolver
from .prompts import PROMPT_SISTEMA, VERSAO_PROMPT, montar_mensagens

ROTULOS = {d["id"]: d["rotulo"] for d in json.loads((RAIZ / "corpus" / "documentos.json").read_text(encoding="utf-8"))}


def selecionar_janela(candidatos: list[dict], top_k: int, orcamento: int) -> tuple[list[dict], list[dict]]:
    """Context engineering: decide o que entra e o que fica de fora (com o motivo)."""
    dentro: list[dict] = []
    fora: list[dict] = []
    usados = 0
    for c in candidatos:
        if len(dentro) >= top_k:
            fora.append({**c, "motivo": f"abaixo do top-{top_k}"})
            continue
        if usados + c["tokens"] > orcamento:
            fora.append({**c, "motivo": f"estouraria o orçamento de {orcamento} tokens"})
            continue
        dentro.append(c)
        usados += c["tokens"]
    return dentro, fora


def _cobertura(candidatos: list[dict], limiar: float) -> harness.Cobertura:
    """Mesmo critério de harness.checar_cobertura (melhor cosseno), com limiar próprio de cada grupo."""
    melhor = max((c["cos"] for c in candidatos), default=0.0)
    return harness.Cobertura(melhor >= limiar, round(melhor, 4), limiar)


def _cob_dict(cob: harness.Cobertura) -> dict:
    return {"melhor_cos": cob.melhor_cos, "limiar": cob.limiar, "coberta": cob.coberta}


def decidir_modo(ref_coberta: bool, exp_coberta: bool) -> str:
    """Tabela de decisão: as referências (documentos oficiais + produção científica) são a base quando existem;
    o relato de experiência entra junto ou sozinho."""
    if ref_coberta and exp_coberta:
        return "referencia+experiencia"
    if ref_coberta:
        return "referencia"
    if exp_coberta:
        return "experiencia"
    return "sem_cobertura"


def _resumo(c: dict, n: int | None = None) -> dict:
    grupo = grupo_do_doc(c["doc"])
    out = {
        "id": c["id"], "doc": c["doc"], "rotulo": ROTULOS.get(c["doc"], c["doc"]), "pagina": rotulo_pagina(c),
        "grupo": grupo, "rotulo_grupo": GRUPOS[grupo],
        "secao": c.get("secao", ""), "tokens": c["tokens"], "rrf": c.get("rrf"), "cos": c.get("cos"),
        "rank_denso": c.get("rank_denso"), "rank_bm25": c.get("rank_bm25"), "codigos_bncc": c.get("codigos_bncc", []),
    }
    if n is not None:
        out["n"] = n
        out["texto"] = c["texto"]
    else:
        out["motivo"] = c.get("motivo", "")
        out["trecho"] = c["texto"][:220]
    return out


def salvar_traco(traco: dict) -> None:
    try:
        TRACOS_DIR.mkdir(parents=True, exist_ok=True)
        dia = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with (TRACOS_DIR / f"tracos_{dia}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(traco, ensure_ascii=False) + "\n")
    except OSError:
        pass  # disco somente leitura (ex.: Space reiniciado): o traço ainda volta na resposta


def responder(pergunta: str, modelo: str = MODELO_LLM, exp: str = EXPERIMENTO, condicao: str = CONDICAO,
              temperatura: float | None = None, chave: str | None = None) -> Iterator[dict]:
    """`chave`: chave do usuário para modelo remoto (modo CHAVE_DO_USUARIO). Nunca vai para o traço."""
    t0 = time.time()
    provedor, modelo_id = resolver(modelo)
    traco: dict = {
        "id": uuid.uuid4().hex[:12], "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pergunta": pergunta, "modelo": modelo, "provedor": provedor, "modelo_id": modelo_id,
        "reprodutivel": provedor == "ollama",  # remoto: sem seed nem digest; a mesma pergunta pode dar outra resposta
        "modelo_digest": digest(modelo), "modelo_embed": MODELO_EMBED,
        "embed_digest": digest(MODELO_EMBED if ":" in MODELO_EMBED else MODELO_EMBED + ":latest"), "experimento": exp,
        "condicao": condicao, "docs": CONDICOES[condicao], "versao_prompt": VERSAO_PROMPT,
        "num_ctx": NUM_CTX, "temperatura": TEMPERATURA if temperatura is None else temperatura,
    }

    # 1) Harness de entrada
    ent = harness.checar_entrada(pergunta)
    traco["entrada"] = {"ok": ent.ok, "motivo": ent.motivo, "pede_diagnostico": ent.pede_diagnostico}
    if not ent.ok:
        traco.update({"desfecho": "bloqueada", "resposta": ent.mensagem, "latencia_s": round(time.time() - t0, 2)})
        salvar_traco(traco)
        yield {"tipo": "final", "desfecho": "bloqueada", "resposta": ent.mensagem, "traco": traco}
        return

    # 2) Recuperação híbrida por grupo + tabela de decisão
    cfg = EXPERIMENTOS[exp]
    indice = carregar(exp)
    ref_docs, exp_docs = docs_do_grupo(REFERENCIAS, condicao), docs_do_grupo("experiencia", condicao)
    por_grupo = CASCATA and bool(exp_docs)  # sem vídeos na condição (C1–C4) ou CASCATA=0: busca única, como antes
    confirmacao = None
    try:
        if por_grupo:
            q = vetor_pergunta(pergunta)  # um embedding só, reaproveitado nas duas buscas
            c_ref = indice.buscar(pergunta, ref_docs, q_vec=q)
            c_exp = indice.buscar(pergunta, exp_docs, q_vec=q)
        else:
            c_ref, c_exp = indice.buscar(pergunta, CONDICOES[condicao]), []
        cob_ref = harness.checar_cobertura(c_ref)
        cob_exp = _cobertura(c_exp, LIMIAR_EXPERIENCIA)
        if por_grupo and not cob_ref.coberta and cob_exp.coberta:
            # Busca de confirmação: antes de dizer "não encontrado nas referências", procura nelas a PRÁTICA do melhor relato.
            relato = max(c_exp, key=lambda c: c["cos"])
            c_conf = indice.buscar(pergunta + "\n" + relato["texto"][:600], ref_docs)
            cob_conf = _cobertura(c_conf, LIMIAR_RESPALDO)
            confirmacao = {**_cob_dict(cob_conf), "relato": relato["id"]}
            if cob_conf.coberta:
                c_ref, cob_ref = c_conf, cob_conf
    except Exception as e:  # embeddings são sempre locais (Ollama/bge-m3), mesmo com modelo de geração remoto
        msg = (f"A busca nos documentos falhou ({type(e).__name__}): o embedding da pergunta ({MODELO_EMBED}) "
               "roda no Ollama local, mesmo com modelo remoto. Verifique se o Ollama está rodando. Nenhuma resposta foi gerada.")
        traco.update({"desfecho": "erro", "erro": conexoes.sanitizar(e, chave)[:300], "resposta": msg, "latencia_s": round(time.time() - t0, 2)})
        salvar_traco(traco)
        yield {"tipo": "final", "desfecho": "erro", "resposta": msg, "traco": traco}
        return
    modo = decidir_modo(cob_ref.coberta, cob_exp.coberta) if por_grupo else ("unico" if cob_ref.coberta else "sem_cobertura")

    # Janela: referências primeiro (numeradas [1..k]), relatos depois.
    if modo == "referencia+experiencia":
        orc_ref = ORCAMENTO_CONTEXTO * 2 // 3  # as referências são a base; os relatos ficam com o restante
        d_ref, f_ref = selecionar_janela(c_ref, TOP_K_GRUPO["referencia"], orc_ref)
        d_exp, f_exp = selecionar_janela(c_exp, TOP_K_GRUPO["experiencia"],
                                         ORCAMENTO_CONTEXTO - sum(c["tokens"] for c in d_ref))
        dentro, fora = d_ref + d_exp, f_ref + f_exp
    elif modo == "experiencia":
        dentro, fora = selecionar_janela(c_exp, cfg["top_k"], ORCAMENTO_CONTEXTO)
    else:  # "referencia", "unico" (fluxo antigo) e "sem_cobertura" (só para mostrar o que ficou abaixo do limiar)
        dentro, fora = selecionar_janela(c_ref or c_exp, cfg["top_k"], ORCAMENTO_CONTEXTO)
    if por_grupo:  # numeração [n]: referências na ordem de relevância da busca, depois os relatos (ordem estável)
        dentro = sorted(dentro, key=lambda c: grupo_do_doc(c["doc"]) == "experiencia")
    coberta = modo != "sem_cobertura"
    melhor_cos = max(cob_ref.melhor_cos, cob_exp.melhor_cos)
    decisao = {
        "modo": modo,
        "referencia": _cob_dict(cob_ref),
        "experiencia": _cob_dict(cob_exp) if por_grupo else None,
        "confirmacao": confirmacao,
    }
    janela = {
        "sistema": {"versao": VERSAO_PROMPT, "tokens": aprox_tokens(PROMPT_SISTEMA)},
        "pergunta_tokens": aprox_tokens(pergunta),
        "trechos": [_resumo(c, i) for i, c in enumerate(dentro, 1)],
        "fora": [_resumo(c) for c in fora[:12]],
        "fora_total": len(fora),
        "orcamento": ORCAMENTO_CONTEXTO,
        "usados": sum(c["tokens"] for c in dentro),
        "top_k": cfg["top_k"],
        "nao_entra": [
            "histórico da conversa (cada pergunta é tratada de forma independente)",
            "documentos fora da condição de corpus " + condicao,
            "PDFs inteiros: só os trechos selecionados acima",
            "dados do aluno: o sistema bloqueia CPF, telefone e e-mail",
        ],
        "modo_ressalva": ent.pede_diagnostico,
        "cobertura": {"melhor_cos": melhor_cos, "limiar": cob_ref.limiar, "coberta": coberta},
        "decisao": decisao,
    }
    traco["janela"] = janela  # completo (inclui o texto dos trechos): o traço reabre a resposta inteira no modo replay
    traco["decisao"] = decisao
    yield {"tipo": "contexto", "janela": janela}

    if not coberta:
        traco.update({"desfecho": "sem_cobertura", "resposta": harness.FRASE_SEM_COBERTURA, "latencia_s": round(time.time() - t0, 2)})
        salvar_traco(traco)
        yield {"tipo": "final", "desfecho": "sem_cobertura", "resposta": harness.FRASE_SEM_COBERTURA, "traco": traco}
        return

    # 3) Modelo
    mensagens = montar_mensagens(pergunta, dentro, ROTULOS, ent.pede_diagnostico, modo)
    bruto = ""
    meta: dict = {}
    try:
        for ev in chat_stream(modelo, mensagens, temperatura, chave):
            if "delta" in ev:
                bruto += ev["delta"]
                yield {"tipo": "delta", "texto": ev["delta"]}
            else:
                meta = ev["fim"]
    except Exception as e:  # modelo indisponível, timeout etc.
        detalhe = conexoes.sanitizar(e, chave)[:300]
        if provedor == "ollama":
            msg = f"O modelo local não respondeu ({type(e).__name__}). Nenhuma resposta foi gerada."
        else:
            msg = f"O modelo remoto ({conexoes.PROVEDORES[provedor]['rotulo']}) não respondeu: {detalhe} Nenhuma resposta foi gerada."
        traco.update({"desfecho": "erro", "erro": detalhe, "resposta": msg, "latencia_s": round(time.time() - t0, 2)})
        salvar_traco(traco)
        yield {"tipo": "final", "desfecho": "erro", "resposta": msg, "traco": traco}
        return

    # 4) Harness de saída
    final, ver = harness.verificar_saida(bruto, dentro, ent.pede_diagnostico, meta.get("done_reason"))
    traco.update({
        "desfecho": "respondida", "resposta_bruta": bruto, "resposta": final, "verificacao": ver.dict(),
        ("ollama" if provedor == "ollama" else "remoto"): meta, "latencia_s": round(time.time() - t0, 2),
    })
    salvar_traco(traco)
    yield {"tipo": "final", "desfecho": "respondida", "resposta": final, "verificacao": ver.dict(), "traco": traco}


def responder_sync(pergunta: str, **kw) -> dict:
    """Versão não-streaming, usada pelos scripts de avaliação."""
    final: dict = {}
    janela: dict = {}
    for ev in responder(pergunta, **kw):
        if ev["tipo"] == "contexto":
            janela = ev["janela"]
        elif ev["tipo"] == "final":
            final = ev
    final["janela"] = janela
    return final
