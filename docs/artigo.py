"""Gera o Artigo (modelo SIGE 2026) a partir do texto abaixo + números de resultados/.

Uso: python docs/artigo.py <modelo_sige.docx> <saida.docx>
Todos os números da seção de resultados são lidos de resultados/*.json(l): nada é digitado à mão.
"""
from __future__ import annotations

import csv
import glob
import json
import re
import statistics as st
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "docs"))
sys.path.insert(0, str(RAIZ))
from build_docx import montar  # noqa: E402
from app.config import (EXPERIMENTOS, LIMIAR_COBERTURA, MODELO_EMBED, MODELO_LLM,  # noqa: E402
                        ORCAMENTO_CONTEXTO)
from app.prompts import VERSAO_PROMPT  # noqa: E402

RES = RAIZ / "resultados"
JUIZ_A, JUIZ_B = "gemma4:e4b-it-q4_K_M", "qwen3.5:4b-q4_K_M"


def br(x, casas=2):
    return f"{x:.{casas}f}".replace(".", ",")


def ler(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def arq_resp(modelo, cond):
    return RES / f"respostas_{modelo.replace(':', '-')}_{cond}_E2.jsonl"


def arq_juiz(modelo, cond, juiz):
    return RES / f"respostas_{modelo.replace(':', '-')}_{cond}_E2__juiz-{juiz.replace(':', '-')}.jsonl"


def media_juiz(modelo, cond, juiz):
    p = arq_juiz(modelo, cond, juiz)
    if not p.exists():
        return None, None, 0
    tot = [n["total"] for n in ler(p) if n.get("total") is not None]
    if not tot:
        return None, None, 0
    return st.mean(tot), sum(t >= 8 for t in tot), len(tot)


def resumo_execucao(modelo, cond):
    regs = [r for r in ler(arq_resp(modelo, cond)) if r["id"].startswith("B")] if arq_resp(modelo, cond).exists() else []
    resp = [r for r in regs if r["desfecho"] == "respondida"]
    return {
        "n": len(regs),
        "respondidas": len(resp),
        "sem_cob": sum(r["desfecho"] == "sem_cobertura" for r in regs),
        "cit_ok": sum(1 for r in resp if r["verificacao"]["citacoes_validas"] and not r["verificacao"]["citacoes_invalidas"]),
        "cit_inv": sum(len(r["verificacao"]["citacoes_invalidas"]) for r in resp),
        "cod_rem": sum(len(r["verificacao"]["codigos_removidos"]) for r in resp),
        "cod_ok": sum(len(r["verificacao"]["codigos_ok"]) for r in resp),
        "forc": sum(r["verificacao"]["ressalva_forcada"] for r in resp),
        "ressalva": sum(bool(r.get("modo_ressalva")) for r in regs),
        "lat": st.mean(r["latencia_s"] for r in resp) if resp else 0,
        "tok_s": st.mean(r["ollama"]["tok_s"] for r in resp if r.get("ollama")) if resp else 0,
        "digest": next((r.get("modelo_digest") for r in regs if r.get("modelo_digest")), "?"),
    }


def main(modelo_sige, saida):
    rec = {(r["experimento"], r["condicao"]): r for r in json.load(open(RES / "recuperacao.json", encoding="utf-8"))["tabela"]}
    Q, G = MODELO_LLM, "gemma4:e4b-it-q4_K_M"
    q4, g4, q1 = resumo_execucao(Q, "C4"), resumo_execucao(G, "C4"), resumo_execucao(Q, "C1")
    lim = {r["id"]: r for r in ler(arq_resp(Q, "C4")) if r["id"].startswith("L")}
    limg = {r["id"]: r for r in ler(arq_resp(G, "C4")) if r["id"].startswith("L")} if arq_resp(G, "C4").exists() else {}
    cpu = json.load(open(RES / "latencia_cpu.json", encoding="utf-8")) if (RES / "latencia_cpu.json").exists() else None
    k = EXPERIMENTOS["E2"]["top_k"]
    n_chunks = sum(1 for _ in open(RAIZ / "index" / "chunks_E2.jsonl", encoding="utf-8"))

    def mj(modelo, cond, juiz):
        m, n8, n = media_juiz(modelo, cond, juiz)
        return ("–", "–") if m is None else (br(m), f"{n8}/{n}")

    # ---------------- TEXTO ----------------
    B = []
    add = lambda t, texto="", **kw: B.append({"t": t, "texto": texto, **kw})

    add("titulo", "AlfaRAG: Assistente RAG Local com Citação Verificável para Apoio à Alfabetização no 2º e 3º Anos")
    add("vazio")
    add("autores", "Neuton Severo, Beatriz Luberiaga, Murilo Narciso, Priscila e Ricardo Graco de Souza Lima Castellano")
    add("instituicao", "Instituto Tecnológico de Aeronáutica (ITA), São José dos Campos/SP – Brasil")
    add("vazio")
    add("colunas")

    melhor_cob = rec[("E2", "C4")]
    add("resumo",
        "Professores do 2º e 3º anos do Ensino Fundamental lidam com alunos que não consolidaram a alfabetização, "
        "e as orientações oficiais estão espalhadas em documentos longos. Este trabalho apresenta o AlfaRAG, um assistente de "
        "apoio à decisão pedagógica que responde apenas com base em um corpus fechado (BNCC, Manual ABC e artigos sobre dislexia), "
        "cita documento e página e não faz diagnóstico. O sistema roda localmente com Ollama e um modelo de 4 bilhões de parâmetros "
        "quantizado, combina busca lexical e vetorial e envolve o modelo com um harness determinístico: bloqueio de dado pessoal, "
        "modo ressalva para pedidos de diagnóstico, recusa sem chamar o modelo quando as fontes não cobrem a pergunta e verificação "
        "das citações e dos códigos da BNCC na saída. Em 24 perguntas de referência, a recuperação com o corpus completo atingiu "
        f"Recall@5 de {br(melhor_cob['recall'])}; julgadas por outro modelo com uma rubrica de 0 a 10, as respostas tiveram média "
        f"{br(media_juiz(Q, 'C4', JUIZ_A)[0], 1)} com o corpus completo e {br(media_juiz(Q, 'C1', JUIZ_A)[0], 1)} só com a BNCC. "
        "Discutimos o que o sistema força, o que fica a cargo do modelo e os limites de verificabilidade que permanecem.")
    add("palavras", "Geração aumentada por recuperação, alfabetização, garantia de IA.")

    # I. Introdução
    add("secao", "i. introdução")
    add("p",
        "A alfabetização nos anos iniciais é organizada, no Brasil, pela Base Nacional Comum Curricular (BNCC) [1], que lista as "
        "habilidades de Língua Portuguesa por ano escolar. Para o professor que tem em sala um aluno do 3º ano que ainda não "
        "reconhece todas as letras, porém, a orientação útil não está em um único lugar: está na BNCC, em manuais de formação "
        "como o Manual do Curso ABC [2], com mais de 500 páginas, e em revisões científicas sobre dislexia escritas em inglês [3], [4].")
    add("p",
        "Uma consulta exploratória feita pelo grupo com sete professoras indicou o tamanho do problema: todas relataram alunos com "
        "dificuldades persistentes de alfabetização sem avaliação concluída, todas apontaram dificuldade de compreensão do que se lê "
        "e duas declararam não dispor de apoio regular. O que as professoras pediam era o que fazer em sala com o aluno que não "
        "acompanha a atividade. Um modelo de linguagem entra aqui porque consegue ler a pergunta em linguagem natural, localizar os "
        "trechos pertinentes em documentos longos e redigir uma orientação aplicável. Sozinho, porém, ele inventa códigos curriculares, "
        "referências e diagnósticos, o que é inaceitável neste domínio.")
    add("p",
        "A geração aumentada por recuperação (RAG) [5] reduz esse risco ao condicionar a resposta a trechos recuperados, mas não "
        "o elimina: o modelo ainda pode citar uma fonte que não sustenta a afirmação ou responder fora do escopo. O que o grupo fez "
        "foi construir e executar um assistente RAG local, com front-end próprio, cujo comportamento crítico não depende só da "
        "instrução ao modelo: um harness determinístico impede ou força comportamentos antes e depois da geração, e cada resposta "
        "deixa um traço auditável. O sistema foi avaliado em 24 perguntas de referência elaboradas pelo grupo e em seis casos-limite.")

    # II. Referencial
    add("secao", "ii. referencial")
    add("p",
        "Na BNCC, cada habilidade de Língua Portuguesa tem um código que indica etapa, anos e componente: EF01LP05, por exemplo, é do "
        "1º ano, e EF12LP07 vale para o 1º e o 2º anos [1]. Esses códigos são justamente o tipo de dado que um modelo de linguagem tende a "
        "inventar com aparência plausível. O Manual ABC organiza a evidência sobre alfabetização em quatro partes, da base neurocognitiva às "
        "dificuldades de aprendizagem, com capítulos sobre métodos fônicos sistemáticos, consciência fonêmica, fluência e dislexia [2].")
    add("p",
        "Na literatura em inglês, a meta-análise de Hall et al. reuniu 53 estudos experimentais ou quase-experimentais, de 1980 a 2020, com "
        "alunos da educação infantil ao 5º ano com dislexia ou em risco, e encontrou efeito médio de g = 0,33 das intervenções sobre medidas "
        "padronizadas de leitura, maior com mais horas de intervenção e menor para compreensão do que para leitura de palavras [4]. A revisão "
        "narrativa de Ramli et al., com 19 referências, aponta treino de consciência fonológica, programas de literacia estruturada e métodos "
        "multissensoriais como intervenções acadêmicas eficazes [3]. Por virem de estudos em inglês, essas evidências não se transferem "
        "automaticamente ao português, e o prompt do sistema exige esse aviso.")
    add("p",
        "Do lado técnico, a RAG combina um recuperador com um gerador condicionado aos trechos recuperados [5]. Buscas lexicais e vetoriais "
        "erram de formas diferentes, e a fusão por posição (RRF) é um modo simples de combiná-las sem calibrar escalas [9]. Modelos de linguagem "
        "usados como juízes concordam razoavelmente com avaliadores humanos, mas têm vieses conhecidos, entre eles favorecer respostas do "
        "próprio modelo [10], o que motivou o uso de juízes cruzados neste trabalho. O plano inicial do grupo usava o Open WebUI com busca na "
        "web desligada; optamos por um front-end próprio porque a interface pronta não expõe a janela de contexto nem as verificações.")

    # III. Método
    add("secao", "iii. método")
    add("subsecao", "A. Corpus e recuperação (RAG)")
    add("p",
        "O corpus tem seis documentos: o recorte de Linguagens e Língua Portuguesa da BNCC [1], o Manual ABC [2], as revisões de "
        "Ramli et al. [3] e Hall et al. [4], um guia de produto educacional [6] e os Cadernos Pedagógicos PNEEI [7]. A ingestão extrai "
        "o texto página a página, guarda o número de página impresso, descarta capa, biografias e listas de referências e associa cada "
        "página do Manual ABC à sua parte e capítulo. O texto é cortado em trechos de cerca de 512 tokens com 15% de sobreposição "
        f"(configuração E2, {n_chunks} trechos), e cada trecho registra os códigos BNCC que contém literalmente.")
    add("p",
        f"A busca é híbrida: BM25 sobre o texto normalizado e similaridade de cosseno com embeddings {MODELO_EMBED} [8], 20 candidatos de "
        "cada, fundidos pela posição com Reciprocal Rank Fusion (k = 60) [9]. A citação mostra documento, página e seção de cada trecho.")
    add("subsecao", "B. Engenharia de contexto e de prompt")
    add("p",
        f"A cada pergunta, a janela recebe: o prompt de sistema versionado ({VERSAO_PROMPT}), os {k} primeiros trechos da fusão numerados "
        f"de [1] a [{k}], desde que caibam em {ORCAMENTO_CONTEXTO} tokens, e a pergunta. Ficam de fora o histórico da conversa (cada pergunta é "
        "independente), os documentos fora da condição de corpus, o restante dos PDFs e qualquer dado do aluno. O front-end exibe, ao lado "
        "de cada resposta, os trechos que entraram, os candidatos que ficaram de fora e o motivo (abaixo do top-k ou acima do orçamento).")
    add("p",
        "O prompt, derivado do projeto do grupo, pede a resposta em quatro partes (orientação, atividade em sala, acompanhamento e fontes) "
        "e impõe seis regras: citar [n] em cada afirmação, não inventar códigos BNCC nem referências, não transferir exemplos do inglês "
        "sem aviso, não diagnosticar, declarar falta de evidência e lembrar que a decisão final é do professor.")
    add("subsecao", "C. Harness")
    add("p",
        "Antes do modelo, regras determinísticas bloqueiam CPF, telefone e e-mail na pergunta e detectam, por expressões regulares, "
        "pedidos de diagnóstico, que ligam um modo ressalva com instrução adicional. Se o melhor trecho recuperado tiver cosseno abaixo de "
        f"{br(LIMIAR_COBERTURA)}, o sistema recusa sem chamar o modelo. Depois da geração, toda citação [n] precisa apontar para um trecho da "
        "janela (as inválidas são removidas), todo código BNCC citado precisa aparecer literalmente em um trecho recuperado (os demais são "
        "substituídos por um aviso) e, no modo ressalva, se o modelo não declarar que não faz diagnóstico, o sistema insere o aviso. "
        "Uma fila atende uma geração por vez e cada resposta grava um traço JSONL com pergunta, trechos, versões, digest do modelo e "
        "verificações. A Fig. 1 resume o fluxo; a Tabela I separa o que o modelo decide do que o sistema força.")
    add("subsecao", "D. AGENTS.md, Agent Skill e avaliação")
    add("p",
        "O repositório traz um AGENTS.md, que diz aos agentes de código o que podem mudar e o que exige revisão humana (prompt, harness e "
        "benchmark), e um SKILL.md com o procedimento de avaliação. A avaliação separa recuperação e geração. Na recuperação, um trecho é "
        "relevante se for da BNCC e contiver um dos códigos citados na fonte da resposta de referência, ou se for do Manual ABC e estiver no "
        "capítulo citado; mede-se Recall@5 e MRR@10. É uma anotação por regra, ainda sem revisão humana dos trechos. Na geração, cada "
        "resposta é julgada por outro modelo [10] com a rubrica do projeto (correção pedagógica, fundamentação documental, português do "
        "Brasil, aplicabilidade e segurança, de 0 a 2 cada), com juízes cruzados para que nenhum modelo seja avaliado apenas por si mesmo.")
    add("fig", arquivo="fig1_arquitetura.png", largura_cm=8.3)
    add("legenda", "Fig. 1. Arquitetura do AlfaRAG: em vermelho, as etapas determinísticas do harness.")
    add("tabela_titulo", "tabela i. o que o modelo decide e o que o sistema força")
    B.append({"t": "tabela", "larguras_cm": [4.1, 4.4], "linhas": [
        ["Modelo decide", "Sistema força"],
        ["Texto, ordem e ênfase da resposta", "Só trechos do corpus entram na janela"],
        ["Quais trechos citar", "Citação [n] inexistente é removida"],
        ["Qual atividade sugerir", "Código BNCC fora das fontes é removido"],
        ["Como formular a ressalva", "Aviso de não diagnóstico, se faltar"],
        ["Admitir falta de evidência", "Recusa sem LLM abaixo do limiar"],
        ["–", "Bloqueio de CPF, telefone e e-mail"],
    ]})
    add("vazio")
    add("p",
        f"O modelo principal é {Q} (Qwen3.5, 4,5 bilhões de parâmetros, quantização Q4_K_M, digest {q4['digest']}), comparado a {G} "
        f"(Gemma 4 E4B, digest {g4['digest']}), ambos servidos pelo Ollama 0.40.16 com temperatura 0 na avaliação e raciocínio estendido "
        "desligado. A avaliação rodou em um Apple M4 com 16 GB, com aceleração Metal; a latência só em CPU foi medida à parte.")

    # IV. Resultados
    add("secao", "iv. resultados")
    add("p",
        "A Tabela II mostra a recuperação por condição de corpus (C1: só BNCC; C2: BNCC e Ramli; C3: BNCC, Ramli e Hall; C4: corpus completo) "
        "e por segmentação (E1: 256 tokens; E2: 512; E3: 1.024; E4: por seção). Como a anotação só reconhece BNCC e Manual ABC, acrescentar "
        "os artigos em inglês (C2 e C3) desloca trechos relevantes da BNCC para fora do top-5; o Manual ABC (C4) é o que mais aumenta a cobertura.")
    add("tabela_titulo", "tabela ii. recuperação: recall@5 / mrr@10 (24 perguntas)")
    linhas = [["Corpus", "E1", "E2", "E3", "E4"]]
    for c in ["C1", "C2", "C3", "C4"]:
        linhas.append([c] + [f"{br(rec[(e, c)]['recall'])} / {br(rec[(e, c)]['mrr'])}" for e in ["E1", "E2", "E3", "E4"]])
    B.append({"t": "tabela", "larguras_cm": [1.3, 1.8, 1.8, 1.8, 1.8], "linhas": linhas})
    add("vazio")
    det = json.load(open(RES / "recuperacao.json", encoding="utf-8"))["detalhe"]
    falhas = [d["id"] for d in det if d["exp"] == "E2" and d["cond"] == "C4" and not (d["primeiro_relevante"] and d["primeiro_relevante"] <= 5)]
    gold = {r["id"]: r for r in csv.DictReader(open(RAIZ / "benchmark" / "perguntas_gold.csv", encoding="utf-8"))}
    so_bncc_geral = [i for i in falhas if gold[i]["gold_passages"].startswith("bncc:*") and "abc:" not in gold[i]["gold_passages"]]
    if falhas:
        add("p",
            f"Com E2 e C4, {len(falhas)} perguntas não tiveram trecho relevante no top-5 ({', '.join(falhas)}). "
            + (f"Destas, {', '.join(so_bncc_geral)} {'tem' if len(so_bncc_geral) == 1 else 'têm'} como fonte de referência apenas a BNCC sem código de habilidade, e o top-5 trouxe só outros documentos; "
               if so_bncc_geral else "")
            + "nas demais, o top-5 trouxe trechos de outros capítulos do Manual ABC, do guia de dislexia ou dos artigos, que a anotação por regra não conta como relevantes. "
              "Parte dessas falhas é, portanto, da régua e não do recuperador, o que reforça a necessidade de revisão humana da anotação.")
    e3 = rec[("E3", "C4")]
    add("p",
        f"E3 teve o maior Recall@5 com o corpus completo ({br(e3['recall'])}), mas trechos de 1.024 tokens fazem só três caberem no orçamento "
        "da janela e alongam o processamento do prompt em CPU; mantivemos E2 na demonstração. A Tabela III resume a geração. Cada linha é "
        "uma execução das 24 perguntas; a nota média vem de cada juiz.")
    add("tabela_titulo", "tabela iii. geração nas 24 perguntas de referência")
    a1, a2 = mj(Q, "C4", JUIZ_A), mj(Q, "C4", JUIZ_B)
    b1, b2 = mj(G, "C4", JUIZ_A), mj(G, "C4", JUIZ_B)
    c1, c2 = mj(Q, "C1", JUIZ_A), mj(Q, "C1", JUIZ_B)
    B.append({"t": "tabela", "larguras_cm": [3.3, 1.7, 1.7, 1.7], "linhas": [
        ["Medida", "Qwen C4", "Gemma C4", "Qwen C1"],
        ["Nota média (juiz Gemma)", a1[0], b1[0], c1[0]],
        ["Nota média (juiz Qwen)", a2[0], b2[0], c2[0]],
        ["Nota ≥ 8 (juiz Gemma)", a1[1], b1[1], c1[1]],
        ["Respondidas", f"{q4['respondidas']}/{q4['n']}", f"{g4['respondidas']}/{g4['n']}", f"{q1['respondidas']}/{q1['n']}"],
        ["Com citação válida", f"{q4['cit_ok']}", f"{g4['cit_ok']}", f"{q1['cit_ok']}"],
        ["Citações inválidas removidas", q4["cit_inv"], g4["cit_inv"], q1["cit_inv"]],
        ["Códigos BNCC removidos", q4["cod_rem"], g4["cod_rem"], q1["cod_rem"]],
        ["Aviso de diagnóstico forçado", q4["forc"], g4["forc"], q1["forc"]],
        ["Latência média (s, M4)", br(q4["lat"], 1), br(g4["lat"], 1), br(q1["lat"], 1)],
    ]})
    add("vazio")

    def crit(modelo, cond, juiz):
        pth = arq_juiz(modelo, cond, juiz)
        ns = [n for n in ler(pth) if n.get("total") is not None] if pth.exists() else []
        return {c: (st.mean(n[c] for n in ns) if ns else None) for c in
                ["correcao_pedagogica", "fundamentacao_documental", "portugues_brasileiro", "aplicabilidade", "seguranca"]}
    c1_recusas = [r for r in ler(arq_resp(Q, "C1")) if r["desfecho"] == "sem_cobertura"]
    g_forc = [r["id"] for r in ler(arq_resp(G, "C4")) if r["id"].startswith("B") and (r.get("verificacao") or {}).get("ressalva_forcada")]
    txt3 = ""
    if c1_recusas:
        cs = [r["cobertura"]["melhor_cos"] for r in c1_recusas]
        txt3 += (f"Só com a BNCC (C1), {len(c1_recusas)} das 24 perguntas foram recusadas pelo teste de cobertura sem chamar o modelo "
                 f"(cosseno entre {br(min(cs), 3)} e {br(max(cs), 3)}): o recorte curricular não traz orientação de intervenção, e o "
                 "sistema preferiu recusar a responder com trechos impróprios. ")
    if g_forc:
        txt3 += (f"Nas perguntas de referência, o Gemma deixou de declarar o limite de diagnóstico em {len(g_forc)} casos ({', '.join(g_forc)}), "
                 "e o sistema inseriu o aviso; o Qwen declarou em todos. ")
    txt3 += ("As notas ficaram perto do teto com o corpus completo, o que sugere leniência de juízes pequenos; a diferença mais nítida "
             "entre C4 e C1 está na fundamentação documental.")
    add("p", txt3)
    cq, cg, cc = crit(Q, "C4", JUIZ_A), crit(G, "C4", JUIZ_A), crit(Q, "C1", JUIZ_A)
    if any(v is not None for v in cq.values()):
        nomes = {"correcao_pedagogica": "Correção pedagógica", "fundamentacao_documental": "Fundamentação documental",
                 "portugues_brasileiro": "Português do Brasil", "aplicabilidade": "Aplicabilidade", "seguranca": "Segurança"}
        fmt = lambda x: "–" if x is None else br(x)
        add("p", "A Tabela IV abre a nota do juiz Gemma por critério (média de 0 a 2). Ela indica onde o sistema perde pontos, "
                 "e não apenas quanto.")
        add("tabela_titulo", "tabela iv. média por critério da rubrica (juiz gemma)")
        B.append({"t": "tabela", "larguras_cm": [3.0, 1.6, 1.7, 1.6], "linhas":
                  [["Critério", "Qwen C4", "Gemma C4", "Qwen C1"]] + [[nomes[c], fmt(cq[c]), fmt(cg[c]), fmt(cc[c])] for c in nomes]})
        add("vazio")
        # concordância entre juízes nas respostas do Qwen C4
        pa, pb = arq_juiz(Q, "C4", JUIZ_A), arq_juiz(Q, "C4", JUIZ_B)
        if pa.exists() and pb.exists():
            ja = {n["id"]: n["total"] for n in ler(pa) if n.get("total") is not None}
            jb = {n["id"]: n["total"] for n in ler(pb) if n.get("total") is not None}
            comuns = sorted(set(ja) & set(jb))
            if comuns:
                dif = [abs(ja[i] - jb[i]) for i in comuns]
                add("p", f"Os dois juízes divergiram, em média, {br(st.mean(dif), 1)} ponto(s) por resposta do Qwen C4 "
                         f"(máximo {max(dif)}; {sum(d == 0 for d in dif)} de {len(comuns)} notas idênticas). Essa dispersão é da mesma ordem "
                         "da diferença entre Qwen e Gemma, o que impede ordenar os dois modelos com segurança a partir de 24 perguntas; "
                         f"já a diferença entre C4 e C1 ({br(media_juiz(Q, 'C4', JUIZ_A)[0] - media_juiz(Q, 'C1', JUIZ_A)[0], 1)} ponto pelo juiz Gemma) é maior que ela.")

    # Caso que responde (B03) e casos que não fecham (L01–L06), lidos dos traços.
    b03 = next(r for r in ler(arq_resp(Q, "C4")) if r["id"] == "B03")
    cit = b03["verificacao"]["citacoes_validas"]
    docs03 = sorted({f"{t['rotulo']}, {t['pagina']}" for t in b03["trechos"] if t["n"] in cit})
    add("p",
        "*Caso que responde.* À pergunta sobre o aluno que lê “pato” mas não lê “prato” (B03), o sistema devolveu as quatro partes pedidas, "
        f"com {len(cit)} citações verificadas, apontando para " + "; ".join(docs03[:3]) + ". Nenhum código foi removido e o traço registra "
        f"{b03['ollama']['prompt_tokens']} tokens de entrada e {b03['ollama']['resposta_tokens']} de saída.")

    def desc(r):
        return {"sem_cobertura": "recusa sem chamar o modelo", "bloqueada": "bloqueio na entrada",
                "respondida": "resposta"}.get(r["desfecho"], r["desfecho"])
    l02, l03, l01, l04, l05 = lim.get("L02"), lim.get("L03"), lim.get("L01"), lim.get("L04"), lim.get("L05")
    txt = "*Casos que não fecham.* "
    if l03:
        txt += (f"A receita de bolo (L03) teve cosseno máximo {br(l03['cobertura']['melhor_cos'], 3)} e foi recusada sem chamar o modelo. ")
    if l04:
        txt += "A pergunta com CPF (L04) foi bloqueada na entrada. "
    if l01:
        v = l01["verificacao"] or {}
        txt += ("O pedido explícito de diagnóstico (L01) ligou o modo ressalva; "
                + ("o modelo não declarou o limite e o sistema inseriu o aviso. " if v.get("ressalva_forcada") else "o próprio modelo declarou que não diagnostica. "))
    if l02:
        cob = l02["cobertura"]["melhor_cos"] if l02.get("cobertura") else None
        if l02["desfecho"] == "sem_cobertura":
            txt += f"A pergunta sobre frações no 5º ano (L02) ficou em {br(cob, 3)} e foi recusada. "
        else:
            admitiu = "evidência suficiente" in (l02.get("resposta") or "")
            txt += (f"Já a pergunta sobre frações no 5º ano (L02) teve cosseno {br(cob, 3)}, acima do limiar, e chegou ao modelo: "
                    "é o caso que o filtro de similaridade não fecha, e a recusa passa a depender da regra 5 do prompt; "
                    + ("nesta execução, o modelo declarou que os documentos não trazem evidência suficiente" if admitiu
                       else "nesta execução, o modelo respondeu mesmo assim, apoiado em trechos sobre alfabetização")
                    + (f", mas anexou à frase as citações {', '.join('[' + str(n) + ']' for n in l02['verificacao']['citacoes_validas'])}, "
                       "que o harness aceita por existirem na janela, embora nenhuma trate de frações. "
                       if admitiu and (l02.get("verificacao") or {}).get("citacoes_validas") else ". "))
    if l05:
        v = l05["verificacao"] or {}
        rem = v.get("codigos_removidos") or []
        txt += (f"No pedido de um código BNCC para inglês (L05), " + (f"o modelo citou {', '.join(rem)}, que o sistema removeu por não constar nas fontes." if rem
                else "nenhum código fora das fontes chegou à saída."))
    add("p", txt)

    def desfecho_txt(r):
        if not r:
            return "–"
        v = r.get("verificacao") or {}
        base = {"sem_cobertura": "recusa sem LLM", "bloqueada": "bloqueio", "respondida": "respondeu", "erro": "erro"}.get(r["desfecho"], r["desfecho"])
        if r["desfecho"] == "respondida":
            if r.get("modo_ressalva"):
                base += ", ressalva" + (" forçada" if v.get("ressalva_forcada") else " do modelo")
            if v.get("codigos_removidos"):
                base += f", {len(v['codigos_removidos'])} cód. removido(s)"
            if "evidência suficiente" in (r.get("resposta") or ""):
                base += ", admitiu falta de evidência"
            citados = {t["doc"] for t in r.get("trechos", []) if t["n"] in (v.get("citacoes_validas") or [])}
            if r["id"] == "L06" and "HALL" in citados:
                base += ", citou Hall"
        return base
    if lim:
        add("tabela_titulo", "tabela v. casos-limite (desfecho registrado no traço)")
        esperado = {"L01": "não diagnosticar", "L02": "recusar", "L03": "recusar", "L04": "bloquear", "L05": "não inventar código", "L06": "responder com ressalva"}
        B.append({"t": "tabela", "larguras_cm": [0.9, 2.3, 2.6, 2.6], "linhas":
                  [["Caso", "Esperado", "Qwen C4", "Gemma C4"]] + [[i, esperado[i], desfecho_txt(lim.get(i)), desfecho_txt(limg.get(i))] for i in sorted(esperado)]})
        add("vazio")
    add("fig", arquivo="screens/fig2_app.png", largura_cm=8.4)
    tid_l01 = (RAIZ / "docs" / "screens" / "tracos_demo.txt").read_text().split("\n")[2].split()[0]
    add("legenda", f"Fig. 2. Tela do AlfaRAG com a pergunta L01 (traço {tid_l01}): modo ressalva, citações conferidas e painel da janela de contexto.")
    if cpu:
        add("p",
            f"Em CPU, sem aceleração (Ollama com num_gpu = 0, mesmo M4), {cpu['n']} perguntas levaram em média {br(cpu['latencia_media_s'], 0)} s, "
            f"a {br(cpu['tok_s_medio'], 1)} tokens/s na geração; esse é o custo de dispensar aceleração, e é o que um servidor sem GPU entregaria.")

    # V. AI Assurance
    regs_q4 = ler(arq_resp(Q, "C4"))
    min_cos_b = min(r["cobertura"]["melhor_cos"] for r in regs_q4 if r["id"].startswith("B") and r.get("cobertura"))
    cos_l02 = next((r["cobertura"]["melhor_cos"] for r in regs_q4 if r["id"] == "L02" and r.get("cobertura")), float("nan"))
    add("secao", "v. ai assurance")
    add("p",
        "*O que o sistema não faz.* Não diagnostica, não avalia o aluno, não cobre outras disciplinas nem outros anos, não consulta a web e "
        "não lembra a conversa. O harness verifica que a citação existe e que o código BNCC está no trecho, mas não verifica se o trecho "
        "sustenta a frase: uma afirmação errada com citação válida passa pelo sistema e só é medida, fora de linha, pelo critério de "
        "fundamentação do juiz.")
    add("p",
        "*Onde uma pessoa aprova, corrige ou interrompe.* No uso, o professor recebe a resposta com as fontes à vista e decide; não há "
        "aprovação humana antes da resposta chegar a ele, de modo que um erro do modelo chega ao professor sinalizado apenas pelos selos "
        "do harness. No desenvolvimento, o AGENTS.md exige revisão de um integrante para mudar prompt, harness ou benchmark. As respostas "
        "de referência e a anotação de relevância ainda aguardam revisão humana, o que limita o peso das métricas.")
    add("p",
        "*De onde vem o que o modelo afirma.* Somente dos trechos que entraram na janela, numerados e exibidos. Quando a fonte não cobre "
        f"a pergunta, o limiar de cosseno ({br(LIMIAR_COBERTURA)}) recusa casos distantes, mas é grosseiro: com o corpus completo, a menor "
        f"similaridade entre as 24 perguntas legítimas foi {br(min_cos_b, 3)}, e a pergunta de frações (L02) teve {br(cos_l02, 3)}. Nessa "
        "faixa, a recusa depende de o modelo obedecer à instrução, e a citação anexada a uma recusa pode não sustentar nada.")
    add("p",
        "*O que quebra se o modelo errar o ramo, inventar ou mudar de versão.* A detecção de pedido de diagnóstico é por expressão regular: "
        "uma paráfrase não prevista deixa o modo ressalva desligado e a verificação de saída não é acionada. Um fato inventado com citação "
        "válida não é detectado. Um código BNCC inventado é removido. Quanto à versão, observamos que a mesma tag do Ollama apontava para "
        "artefatos diferentes no macOS e no Linux; por isso fixamos a quantização na tag e gravamos o digest em cada traço. Trocar o modelo "
        "de embedding invalida o índice sem erro aparente, e por isso o procedimento do SKILL.md manda regenerar e reavaliar.")

    # V. Conclusão
    add("secao", "vi. conclusão")
    add("p",
        "Ficou demonstrado que um modelo de 4 bilhões de parâmetros, rodando localmente, responde a perguntas de alfabetização com "
        "citação de documento e página quando cercado por recuperação híbrida e por um harness que impõe recusas, avisos e remoções "
        "verificáveis, e que esses comportamentos aparecem no traço de cada resposta. Ficaram de fora: o documento Habilidades Essenciais "
        "do 2º ano, citado no benchmark e ainda ausente do corpus; a revisão humana das respostas de referência; ajuste fino ou LoRA; um "
        "fluxo em n8n; a verificação de que o trecho citado sustenta a frase; e qualquer medida de efeito em sala de aula. As notas "
        "do juiz são indicadores descritivos de 24 perguntas, não prova de eficácia pedagógica.")

    # Referências
    add("refs_titulo", "referências")
    for ref in [
        "Brasil, Ministério da Educação, Base Nacional Comum Curricular. Brasília: MEC, 2018.",
        "R. A. Alves, I. Leite, Eds., Alfabetização Baseada na Ciência: Manual do Curso ABC. Brasília: MEC/CAPES, 2021.",
        "S. Ramli, R. S. M. K. Nizam, S. N. S. Mohamad, S. Surat, A. R. M. Gobil, “Developmental dyslexia in children: a narrative review of evidence-based interventions, parenting approaches, and assistive technologies”, Int. J. Res. Innov. Soc. Sci., vol. X, no. XXVI, pp. 4223–4232, Maio 2026.",
        "C. Hall et al., “Forty years of reading intervention research for elementary students with or at risk for dyslexia: a systematic review and meta-analysis”, Reading Research Quarterly, vol. 58, no. 2, pp. 285–312, 2023.",
        "P. Lewis et al., “Retrieval-augmented generation for knowledge-intensive NLP tasks”, in Proc. 34th Conf. Neural Information Processing Systems (NeurIPS), Vancouver, Canada, 2020.",
        "A. R. R. da Silva, C. C. da Silva, Guia de Orientação para o Trabalho com o Estudante Disléxico (produto educacional, mestrado profissional). Urutaí/GO, 2024.",
        "Brasil, Ministério da Educação, Práticas Inclusivas em Alfabetização e Letramento, Cadernos Pedagógicos da Política Nacional de Educação Especial Inclusiva (PNEEI), vol. 10. Brasília: MEC, 2025.",
        "J. Chen, S. Xiao, P. Zhang, K. Luo, D. Lian, Z. Liu, “BGE M3-Embedding: multi-lingual, multi-functionality, multi-granularity text embeddings through self-knowledge distillation”, 2024, arXiv:2402.03216.",
        "G. V. Cormack, C. L. A. Clarke, S. Buettcher, “Reciprocal rank fusion outperforms Condorcet and individual rank learning methods”, in Proc. 32nd ACM SIGIR Conf., Boston, USA, 2009, pp. 758–759.",
        "L. Zheng et al., “Judging LLM-as-a-judge with MT-Bench and Chatbot Arena”, in Proc. 37th Conf. Neural Information Processing Systems (NeurIPS), New Orleans, USA, 2023.",
    ]:
        add("ref", ref)

    json.dump(B, open(RAIZ / "docs" / "conteudo_artigo.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    montar(modelo_sige, B, saida, str(RAIZ / "docs"))
    palavras = sum(len(re.findall(r"\w+", b.get("texto", ""))) for b in B)
    print("ok", saida, "palavras≈", palavras)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
