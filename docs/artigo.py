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


def pl(n, sing, plur):
    return f"{n} {sing if n == 1 else plur}"


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
    docs_e2 = [json.loads(l)["doc"] for l in open(RAIZ / "index" / "chunks_E2.jsonl", encoding="utf-8")]
    n_chunks = sum(d != "VID" for d in docs_e2)  # base da demonstração (C4)
    n_chunks_vid = sum(d == "VID" for d in docs_e2)
    n_videos = len(list((RAIZ / "corpus" / "videos").glob("*.md")))
    C5 = arq_resp(Q, "C5").exists()
    # Quadros de habilidades essenciais: registros extraídos e habilidades do 1º ano retomadas no quadro do 2º ano.
    sys.path.insert(0, str(RAIZ / "scripts"))
    from preparar_corpus import COD_HE, CORPUS, extrair_habilidades  # noqa: E402
    docs_corpus = json.load(open(CORPUS / "documentos.json", encoding="utf-8"))
    pags_he = {d["id"]: extrair_habilidades(d["id"], CORPUS / d["arquivo"]) for d in docs_corpus if d["id"].startswith("HE")}
    n_registros_he = sum(p.texto.count("Habilidade essencial do ") for ps in pags_he.values() for p in ps)
    n_ef01_he2 = len({c for p in pags_he["HE2"] for c in COD_HE.findall(p.texto) if c.startswith("EF01")})

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
        "apoio à decisão pedagógica que responde apenas com base em um corpus fechado (BNCC, quadros de habilidades essenciais, "
        "Manual ABC e artigos sobre dislexia), "
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
        "inventar com aparência plausível. Quadros de habilidades essenciais de rede de ensino organizam, por ano e bimestre, habilidades "
        "da BNCC com objeto de conhecimento e conteúdo; os usados aqui, do 1º ao 3º ano, desdobram algumas habilidades com uma letra "
        f"(EF02LP01A) e o do 2º ano retoma {n_ef01_he2} habilidades do 1º ano [11]. "
        "O Manual ABC organiza a evidência sobre alfabetização em quatro partes, da base neurocognitiva às "
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
        "O corpus tem nove documentos: o recorte de Linguagens e Língua Portuguesa da BNCC [1], os três quadros de habilidades "
        "essenciais de Língua Portuguesa (1º, 2º e 3º anos) [11], o Manual ABC [2], as revisões de Ramli et al. [3] e Hall et al. [4], "
        "um guia de produto educacional [6] e os Cadernos Pedagógicos PNEEI [7]. A ingestão extrai o texto página a página, guarda o "
        "número de página impresso, descarta capa, biografias e listas de referências e associa cada página do Manual ABC à sua parte e "
        "capítulo. Nos quadros de habilidades, o texto corrido do PDF embaralha as colunas; por isso a tabela é lida célula a célula, e "
        f"cada linha vira um registro com ano, bimestre, código e conteúdo ({n_registros_he} registros). O texto é cortado em trechos de "
        f"cerca de 512 tokens com 15% de sobreposição (configuração E2, {n_chunks} trechos), e cada trecho registra os códigos BNCC que "
        "contém literalmente. Como experimento à parte (C5), entram também resumos de "
        f"{n_videos} vídeos do YouTube sobre alfabetização e inclusão, feitos pelo grupo a partir da legenda automática com auxílio de IA, "
        f"com canal, endereço, minutagem e trechos literais ({n_chunks_vid} trechos). São relatos de experiência de profissionais, e a "
        "fonte chega ao modelo rotulada como relato em vídeo, para não ser tratada como evidência; por serem fonte secundária gerada "
        "por IA, não entram na base da demonstração.")
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
        "janela (as inválidas são removidas), todo código BNCC citado, inclusive os desdobrados como EF02LP01A, precisa aparecer "
        "literalmente em um trecho recuperado (os demais são substituídos por um aviso) e, no modo ressalva, se o modelo não declarar que não faz diagnóstico, o sistema insere o aviso. "
        "Uma fila atende uma geração por vez e cada resposta grava um traço JSONL com pergunta, trechos, versões, digest do modelo e "
        "verificações. A Fig. 1 resume o fluxo; a Tabela I separa o que o modelo decide do que o sistema força.")
    add("subsecao", "D. AGENTS.md, Agent Skill e avaliação")
    add("p",
        "O repositório traz um AGENTS.md, que diz aos agentes de código o que podem mudar e o que exige revisão humana (prompt, harness e "
        "benchmark), e um SKILL.md com o procedimento de avaliação. A avaliação separa recuperação e geração. Na recuperação, um trecho é "
        "relevante se for do documento citado na fonte da resposta de referência e contiver um dos códigos ali listados (ou qualquer "
        "trecho dele, se a fonte não traz código), regra que vale para a BNCC e, nas três perguntas que o citam, para o quadro do 2º ano; "
        "no Manual ABC, basta estar no capítulo citado. Mede-se Recall@5 e MRR@10. É uma anotação por regra, ainda sem revisão humana dos trechos. Na geração, cada "
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
    det = json.load(open(RES / "recuperacao.json", encoding="utf-8"))["detalhe"]
    r1, r2, r3, r4 = (rec[("E2", c)]["recall"] for c in ("C1", "C2", "C3", "C4"))
    txt_rec = ("A Tabela II mostra a recuperação por condição de corpus (C1: só BNCC; C2: BNCC e Ramli; C3: BNCC, Ramli e Hall; "
               "C4: corpus completo; C5: C4 e resumos de vídeo) e por segmentação (E1: 256 tokens; E2: 512; E3: 1.024; E4: por seção). ")
    if r2 < r1 and r3 < r1:
        txt_rec += ("Como a anotação reconhece só BNCC, Manual ABC e, em três perguntas, o quadro do 2º ano, acrescentar os artigos em "
                    "inglês (C2 e C3) desloca trechos relevantes da BNCC para fora do top-5. ")
    if r4 > max(r1, r2, r3):
        txt_rec += "O corpus completo (C4) é o que mais aumenta a cobertura. "
    # De que documento veio o primeiro trecho relevante (E2, C4, dentro do top-5)?
    origem = {}
    for d in det:
        if d["exp"] == "E2" and d["cond"] == "C4" and d["primeiro_relevante"] and d["primeiro_relevante"] <= 5:
            doc = d["top5"][d["primeiro_relevante"] - 1].split(":")[0]
            origem[doc] = origem.get(doc, 0) + 1
    nome_doc = {"BNCC": "da BNCC", "ABC": "do Manual ABC", "HE2": "do quadro do 2º ano"}
    if origem:
        partes = [f"{nome_doc.get(d, d)} em {pl(n, 'pergunta', 'perguntas') if i == 0 else n}"
                  for i, (d, n) in enumerate(sorted(origem.items(), key=lambda x: -x[1]))]
        txt_rec += ("Com E2 e C4, o primeiro trecho relevante do top-5 veio " + ", ".join(partes[:-1])
                    + (" e " if len(partes) > 1 else "") + partes[-1] + ". ")
    if ("E2", "C5") in rec:
        r5 = rec[("E2", "C5")]["recall"]
        top5_c5 = [t for d in det if d["exp"] == "E2" and d["cond"] == "C5" for t in d["top5"]]
        pct_vid = 100 * sum(t.startswith("VID:") for t in top5_c5) / max(1, len(top5_c5))
        verbo = "reduziu" if r5 < r4 else ("aumentou" if r5 > r4 else "manteve")
        txt_rec += (f"Acrescentar os resumos de vídeo (C5) {verbo} o Recall@5 de {br(r4)} para {br(r5)}" if verbo != "manteve"
                    else f"Acrescentar os resumos de vídeo (C5) manteve o Recall@5 em {br(r5)}")
        txt_rec += (f"; os vídeos ocuparam {br(pct_vid, 0)}% das posições do top-5, e a anotação por regra não conta vídeo como "
                    "relevante" + (", de modo que a queda mede deslocamento dos documentos, não necessariamente perda de informação." if r5 < r4 else "."))
    add("p", txt_rec.strip())
    add("tabela_titulo", "tabela ii. recuperação: recall@5 / mrr@10 (24 perguntas)")
    linhas = [["Corpus", "E1", "E2", "E3", "E4"]]
    for c in [c for c in ["C1", "C2", "C3", "C4", "C5"] if ("E2", c) in rec]:
        linhas.append([c] + [f"{br(rec[(e, c)]['recall'])} / {br(rec[(e, c)]['mrr'])}" for e in ["E1", "E2", "E3", "E4"]])
    B.append({"t": "tabela", "larguras_cm": [1.3, 1.8, 1.8, 1.8, 1.8], "linhas": linhas})
    add("vazio")
    det_e2c4 = {d["id"]: d for d in det if d["exp"] == "E2" and d["cond"] == "C4"}
    falhas = [i for i, d in det_e2c4.items() if not (d["primeiro_relevante"] and d["primeiro_relevante"] <= 5)]
    gold = {r["id"]: r for r in csv.DictReader(open(RAIZ / "benchmark" / "perguntas_gold.csv", encoding="utf-8"))}
    so_bncc_geral = [i for i in falhas if gold[i]["gold_passages"] == "bncc:*"]
    if falhas:
        # documentos que ocuparam o top-5 das demais falhas
        desc_doc = {"ABC": "outros capítulos do Manual ABC", "ROSA": "guia de dislexia", "RAMLI": "artigos", "HALL": "artigos",
                    "PNEEI": "Cadernos PNEEI", "HE1": "quadros de habilidades", "HE2": "quadros de habilidades",
                    "HE3": "quadros de habilidades", "BNCC": "BNCC sem o código esperado"}
        outros = []
        for i in falhas:
            if i in so_bncc_geral:
                continue
            for t in det_e2c4[i]["top5"]:
                nome = desc_doc.get(t.split(":")[0], t.split(":")[0])
                if nome not in outros:
                    outros.append(nome)
        lista = (", ".join(outros[:-1]) + " ou " + outros[-1]) if len(outros) > 1 else (outros[0] if outros else "")
        add("p",
            f"Com E2 e C4, {pl(len(falhas), 'pergunta não teve', 'perguntas não tiveram')} trecho relevante no top-5 ({', '.join(falhas)}). "
            + (f"Destas, {', '.join(so_bncc_geral)} {'tem' if len(so_bncc_geral) == 1 else 'têm'} como fonte de referência apenas a BNCC sem código de habilidade, e o top-5 trouxe só outros documentos; "
               if so_bncc_geral else "")
            + (f"nas demais, o top-5 trouxe trechos de {lista}, que a anotação por regra não conta como relevantes. " if outros else "")
            + "Parte dessas falhas é, portanto, da régua e não do recuperador, o que reforça a necessidade de revisão humana da anotação.")
    melhor_e = max(["E1", "E2", "E3", "E4"], key=lambda e: (rec[(e, "C4")]["recall"], rec[(e, "C4")]["mrr"]))
    porque = {"E3": "trechos de 1.024 tokens fazem só três caberem no orçamento da janela e alongam o processamento do prompt em CPU",
              "E4": "trechos por seção chegam a 1.024 tokens, de modo que poucos cabem no orçamento da janela",
              "E1": "trechos de 256 tokens, com top-3, levam ao modelo menos contexto por pergunta"}
    rmax = rec[(melhor_e, "C4")]["recall"]
    topo = [e for e in ("E1", "E2", "E3", "E4") if rec[(e, "C4")]["recall"] == rmax]
    if "E2" in topo:
        txt_e = f"E2, usada na demonstração, teve o maior Recall@5 com o corpus completo ({br(rmax)}). "
    elif set(topo) == {"E3", "E4"}:
        txt_e = (f"E3 e E4 empataram no maior Recall@5 com o corpus completo ({br(rmax)}), mas usam trechos maiores: em E3, de "
                 "1.024 tokens, só três cabem no orçamento da janela, e em E4 o tamanho varia com a seção; mantivemos E2 na demonstração. ")
    else:
        txt_e = (f"{melhor_e} teve o maior Recall@5 com o corpus completo ({br(rec[(melhor_e, 'C4')]['recall'])}), mas "
                 f"{porque[melhor_e]}; mantivemos E2 na demonstração. ")
    add("p", txt_e + "A Tabela III resume a geração. Cada coluna é uma execução das 24 perguntas; a nota média vem de cada juiz.")
    add("tabela_titulo", "tabela iii. geração nas 24 perguntas de referência")
    # Colunas da Tabela III: (rótulo, modelo, condição, resumo da execução)
    execs = [("Qwen C4", Q, "C4", q4), ("Gemma C4", G, "C4", g4), ("Qwen C1", Q, "C1", q1)]
    if C5:
        execs.append(("Qwen C5", Q, "C5", resumo_execucao(Q, "C5")))
    larg = [3.3, 1.7, 1.7, 1.7] if len(execs) == 3 else [2.8, 1.4, 1.4, 1.4, 1.4]
    linhas3 = [["Medida"] + [e[0] for e in execs]]
    linhas3 += [
        ["Nota média (juiz Gemma)"] + [mj(m, c, JUIZ_A)[0] for _, m, c, _ in execs],
        ["Nota média (juiz Qwen)"] + [mj(m, c, JUIZ_B)[0] for _, m, c, _ in execs],
        ["Nota ≥ 8 (juiz Gemma)"] + [mj(m, c, JUIZ_A)[1] for _, m, c, _ in execs],
        ["Respondidas"] + [f"{x['respondidas']}/{x['n']}" for *_, x in execs],
        ["Com citação válida"] + [f"{x['cit_ok']}" for *_, x in execs],
        ["Citações inválidas removidas"] + [x["cit_inv"] for *_, x in execs],
        ["Códigos BNCC removidos"] + [x["cod_rem"] for *_, x in execs],
        ["Aviso de diagnóstico forçado"] + [x["forc"] for *_, x in execs],
        ["Latência média (s, M4)"] + [br(x["lat"], 1) for *_, x in execs],
    ]
    B.append({"t": "tabela", "larguras_cm": larg, "linhas": linhas3})
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
    q_forc = [r["id"] for r in ler(arq_resp(Q, "C4")) if r["id"].startswith("B") and (r.get("verificacao") or {}).get("ressalva_forcada")]
    if g_forc or q_forc:
        quem = []
        for nome, lst in (("o Gemma", g_forc), ("o Qwen", q_forc)):
            if lst:
                quem.append((f"{nome} deixou de declarar o limite de diagnóstico em " if not quem else f"{nome}, em ")
                            + f"{pl(len(lst), 'caso', 'casos')} ({', '.join(lst)})")
        txt3 += ("Nas perguntas de referência, " + " e ".join(quem) + ", e o sistema inseriu o aviso"
                 + ("; o Qwen declarou em todos. " if not q_forc else "; o Gemma declarou em todos. " if not g_forc else ". "))
    cq, cg, cc = crit(Q, "C4", JUIZ_A), crit(G, "C4", JUIZ_A), crit(Q, "C1", JUIZ_A)
    media_q4 = media_juiz(Q, "C4", JUIZ_A)[0]
    if media_q4 is not None and media_q4 >= 9:
        txt3 += "As notas ficaram perto do teto com o corpus completo, o que sugere leniência de juízes pequenos"
        difs = {c: cq[c] - cc[c] for c in cq if cq[c] is not None and cc[c] is not None}
        if difs:
            nomes_c = {"correcao_pedagogica": "correção pedagógica", "fundamentacao_documental": "fundamentação documental",
                       "portugues_brasileiro": "português do Brasil", "aplicabilidade": "aplicabilidade", "seguranca": "segurança"}
            cmax = max(difs, key=difs.get)
            txt3 += f"; a diferença mais nítida entre C4 e C1 está em {nomes_c[cmax]} ({br(difs[cmax])} ponto, juiz Gemma)"
        txt3 += "."
    add("p", txt3.strip())
    if any(v is not None for v in cq.values()):
        nomes = {"correcao_pedagogica": "Correção pedagógica", "fundamentacao_documental": "Fundamentação documental",
                 "portugues_brasileiro": "Português do Brasil", "aplicabilidade": "Aplicabilidade", "seguranca": "Segurança"}
        fmt = lambda x: "–" if x is None else br(x)
        add("p", "A Tabela IV abre a nota do juiz Gemma por critério (média de 0 a 2). Ela indica onde o sistema perde pontos, "
                 "e não apenas quanto.")
        add("tabela_titulo", "tabela iv. média por critério da rubrica (juiz gemma)")
        crits = [(rot, crit(m, c, JUIZ_A)) for rot, m, c, _ in execs]
        B.append({"t": "tabela", "larguras_cm": [3.0, 1.6, 1.7, 1.6] if len(crits) == 3 else [2.8, 1.4, 1.4, 1.4, 1.4], "linhas":
                  [["Critério"] + [r for r, _ in crits]] + [[nomes[c]] + [fmt(cr[c]) for _, cr in crits] for c in nomes]})
        add("vazio")
        # concordância entre juízes nas respostas do Qwen C4
        pa, pb = arq_juiz(Q, "C4", JUIZ_A), arq_juiz(Q, "C4", JUIZ_B)
        if pa.exists() and pb.exists():
            ja = {n["id"]: n["total"] for n in ler(pa) if n.get("total") is not None}
            jb = {n["id"]: n["total"] for n in ler(pb) if n.get("total") is not None}
            comuns = sorted(set(ja) & set(jb))
            if comuns:
                dif = [abs(ja[i] - jb[i]) for i in comuns]
                div = st.mean(dif)
                # diferença Qwen x Gemma (C4) em cada juiz, e C4 x C1 (Qwen, juiz Gemma)
                d_qg = max(abs(media_juiz(Q, "C4", j)[0] - media_juiz(G, "C4", j)[0]) for j in (JUIZ_A, JUIZ_B))
                d_c = media_juiz(Q, "C4", JUIZ_A)[0] - media_juiz(Q, "C1", JUIZ_A)[0]
                txt_j = (f"Os dois juízes divergiram, em média, {br(div, 1)} {'ponto' if div < 2 else 'pontos'} por resposta do Qwen C4 "
                         f"(máximo {max(dif)}; {sum(d == 0 for d in dif)} de {len(comuns)} notas idênticas). ")
                if d_qg <= div:
                    txt_j += (f"Essa dispersão é maior que a diferença entre Qwen e Gemma (até {br(d_qg, 1)} ponto), o que impede ordenar "
                              "os dois modelos com segurança a partir de 24 perguntas; ")
                elif d_qg <= 2 * div:
                    txt_j += (f"Essa dispersão é da mesma ordem da diferença entre Qwen e Gemma (até {br(d_qg, 1)} ponto), o que impede "
                              "ordenar os dois modelos com segurança a partir de 24 perguntas; ")
                else:
                    txt_j += f"A diferença entre Qwen e Gemma (até {br(d_qg, 1)} ponto) supera essa dispersão; "
                txt_j += (f"já a diferença entre C4 e C1 ({br(d_c, 1)} ponto pelo juiz Gemma) "
                          + ("é maior que ela." if d_c > div else "não é maior que ela, e também não permite conclusão firme."))
                add("p", txt_j)

    # C5: efeito dos resumos de vídeo na geração (Qwen), lido dos traços e das notas.
    if C5 and media_juiz(Q, "C5", JUIZ_A)[0] is not None:
        m5, m4 = media_juiz(Q, "C5", JUIZ_A)[0], media_juiz(Q, "C4", JUIZ_A)[0]
        regs5 = [r for r in ler(arq_resp(Q, "C5")) if r["id"].startswith("B") and r["desfecho"] == "respondida"]
        com_vid = sum(1 for r in regs5 if any(t["doc"] == "VID" and t["n"] in r["verificacao"]["citacoes_validas"] for t in r["trechos"]))
        pa, pb = arq_juiz(Q, "C4", JUIZ_A), arq_juiz(Q, "C4", JUIZ_B)
        ja = {n["id"]: n["total"] for n in ler(pa) if n.get("total") is not None}
        jb = {n["id"]: n["total"] for n in ler(pb) if n.get("total") is not None}
        div5 = st.mean(abs(ja[i] - jb[i]) for i in set(ja) & set(jb)) if set(ja) & set(jb) else 0
        add("p",
            f"Com os resumos de vídeo (C5), o Qwen teve média {br(m5)} pelo juiz Gemma, contra {br(m4)} em C4, e {com_vid} das "
            f"{len(regs5)} respostas citaram ao menos um resumo de vídeo. "
            + ("A diferença está dentro da dispersão entre juízes, de modo que não sustenta conclusão sobre o efeito dos vídeos na qualidade; "
               "o efeito observável é a mudança de fonte citada." if abs(m5 - m4) <= div5 else
               f"A diferença ({br(m5 - m4, 1)} ponto) supera a dispersão média entre juízes ({br(div5, 1)}), mas vem de um único juiz e de 24 perguntas."))

    # Caso que responde (B03) e casos que não fecham (L01–L06), lidos dos traços.
    b03 = next(r for r in ler(arq_resp(Q, "C4")) if r["id"] == "B03")
    cit = b03["verificacao"]["citacoes_validas"]
    docs03 = sorted({f"{t['rotulo']}, {t['pagina']}" for t in b03["trechos"] if t["n"] in cit})
    partes03 = [p for p in ("Orientação", "Atividade", "Acompanhamento", "Fontes") if p.lower() in (b03.get("resposta") or "").lower()]
    rem03 = b03["verificacao"]["codigos_removidos"]
    # Leitura humana (nossa) do B03: a frase abaixo só entra se a resposta gravada ainda trouxer o erro que lemos nela
    # (chamar "prato"/"porta" de grafema complexo/múltiplo). Se a avaliação for refeita, reler a resposta.
    erro03 = bool(re.search(r"grafemas? (múltiplos|complexos)|mais de um fonema", b03.get("resposta") or ""))
    notas03 = [n["total"] for j in (G, Q) if arq_juiz(Q, "C4", j).exists()
               for n in ler(arq_juiz(Q, "C4", j)) if n["id"] == "B03" and n.get("total") is not None]
    erro03 = erro03 and len(notas03) == 2
    add("p",
        "*Caso que responde.* À pergunta sobre o aluno que lê “pato” mas não lê “prato” (B03), o sistema devolveu "
        + ("as quatro partes pedidas" if len(partes03) == 4 else f"{len(partes03)} das quatro partes pedidas")
        + f", com {len(cit)} citações verificadas, apontando para " + "; ".join(docs03[:3]) + ". "
        + ("Nenhum código foi removido" if not rem03 else f"O sistema removeu {', '.join(rem03)}")
        + f" e o traço registra {b03['ollama']['prompt_tokens']} tokens de entrada e {b03['ollama']['resposta_tokens']} de saída."
        + (f" Lida por nós, porém, a resposta erra o conceito central: trata “prato” e “porta” como palavras de grafemas complexos, "
           "que no trecho citado do Manual ABC são duas letras para um só som (como em “milho”); em “prato” as duas consoantes "
           "soam (encontro consonantal) e “porta” tem sílaba travada. A citação existe e passou no harness, e os juízes Gemma "
           f"e Qwen deram {notas03[0] if erro03 else ''} e {notas03[-1] if erro03 else ''} pontos de 10. A verificação confirma a fonte, não a leitura que o modelo faz dela." if erro03 else ""))

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
                base += f", {pl(len(v['codigos_removidos']), 'cód. removido', 'cód. removidos')}"
            if "evidência suficiente" in (r.get("resposta") or ""):
                base += ", admitiu falta de evidência"
            citados = {t["doc"] for t in r.get("trechos", []) if t["n"] in (v.get("citacoes_validas") or [])}
            if r["id"] == "L06" and "HALL" in citados:
                base += ", citou Hall"
        return base
    if lim:
        add("tabela_titulo", "tabela v. casos-limite (desfecho registrado no traço)")
        esperado = {"L01": "não diagnosticar", "L02": "recusar", "L03": "recusar", "L04": "bloquear", "L05": "não inventar código", "L06": "responder com ressalva"}
        lim5 = {r["id"]: r for r in ler(arq_resp(Q, "C5")) if r["id"].startswith("L")} if C5 else {}
        if lim5:
            B.append({"t": "tabela", "larguras_cm": [0.8, 1.75, 1.95, 1.95, 1.95], "linhas":
                      [["Caso", "Esperado", "Qwen C4", "Gemma C4", "Qwen C5"]]
                      + [[i, esperado[i], desfecho_txt(lim.get(i)), desfecho_txt(limg.get(i)), desfecho_txt(lim5.get(i))] for i in sorted(esperado)]})
        else:
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
    # Grafia: a mesma pergunta com e sem acentos no teste de cobertura (scripts/medir_grafia.py).
    txt_grafia = ""
    if (RES / "grafia.json").exists():
        gr = json.load(open(RES / "grafia.json", encoding="utf-8"))
        viradas = [p for p in gr["pares"] if p["com_acento"]["coberta"] and not p["sem_acento"]["coberta"]]
        quedas = [p["com_acento"]["melhor_cos"] - p["sem_acento"]["melhor_cos"] for p in gr["pares"]]
        if viradas:
            p0 = viradas[0]
            txt_grafia = (f"A grafia também desloca o limiar: em {len(gr['pares'])} perguntas escritas com e sem acentos, a similaridade caiu "
                          f"de {br(min(quedas), 3)} a {br(max(quedas), 3)} sem acentos, e em {({1: 'uma', 2: 'duas'}).get(len(viradas), len(viradas))} "
                          f"delas (“{p0['sem_acento']['pergunta']}”) "
                          f"passou de {br(p0['com_acento']['melhor_cos'], 3)} para {br(p0['sem_acento']['melhor_cos'], 3)}, abaixo do limiar: "
                          "uma pergunta legítima foi recusada; a interface sugere reescrever com acentos. ")
        elif quedas and max(quedas) > 0:
            txt_grafia = (f"A grafia também desloca o limiar: sem acentos, a similaridade caiu até {br(max(quedas), 3)} em "
                          f"{len(gr['pares'])} perguntas, sem inverter a decisão. ")
    add("secao", "v. ai assurance")
    add("p",
        "*O que o sistema não faz.* Não diagnostica, não avalia o aluno, não cobre outras disciplinas nem anos além do 3º, não consulta a web e "
        "não lembra a conversa. O harness verifica que a citação existe e que o código BNCC está no trecho, mas não verifica se o trecho "
        "sustenta a frase: uma afirmação errada com citação válida passa pelo sistema e só pode ser apanhada, fora de linha, pelo critério "
        "de fundamentação do juiz" + ("; no caso B03, nem os juízes a apontaram." if erro03 else "."))
    add("p",
        "*Onde uma pessoa aprova, corrige ou interrompe.* No uso, o professor recebe a resposta com as fontes à vista e decide; não há "
        "aprovação humana antes da resposta chegar a ele, de modo que um erro do modelo chega ao professor sinalizado apenas pelos selos "
        "do harness. No desenvolvimento, o AGENTS.md exige revisão de um integrante para mudar prompt, harness ou benchmark. As respostas "
        "de referência e a anotação de relevância ainda aguardam revisão humana, o que limita o peso das métricas.")
    add("p",
        "*De onde vem o que o modelo afirma.* Somente dos trechos que entraram na janela, numerados e exibidos; os quadros de habilidades "
        "não identificam a rede que os publicou e são citados pelo título e pela página do PDF. No experimento C5, a citação de um "
        "resumo de vídeo aponta para um texto gerado por IA a partir de legenda automática, e não para a fala original; por isso essa "
        "fonte ficou fora da demonstração. Quando a fonte não cobre "
        f"a pergunta, o limiar de cosseno ({br(LIMIAR_COBERTURA)}) recusa casos distantes, mas é grosseiro: com o corpus completo, a menor "
        f"similaridade entre as 24 perguntas legítimas foi {br(min_cos_b, 3)}, e a pergunta de frações (L02) teve {br(cos_l02, 3)}. Nessa "
        "faixa, a recusa depende de o modelo obedecer à instrução, e a citação anexada a uma recusa pode não sustentar nada.")
    add("p",
        "*O que quebra se o modelo errar o ramo, inventar ou mudar de versão.* A detecção de pedido de diagnóstico é por expressão regular: "
        "uma paráfrase não prevista deixa o modo ressalva desligado e a verificação de saída não é acionada. "
        + txt_grafia +
        "Um fato inventado ou uma leitura errada da fonte, com citação válida, não é detectado. Um código BNCC inventado é removido. Quanto à versão, observamos que a mesma tag do Ollama apontava para "
        "artefatos diferentes no macOS e no Linux; por isso fixamos a quantização na tag e gravamos o digest em cada traço. Trocar o modelo "
        "de embedding invalida o índice sem erro aparente, e por isso o procedimento do SKILL.md manda regenerar e reavaliar.")

    # V. Conclusão
    add("secao", "vi. conclusão")
    add("p",
        "Ficou demonstrado que um modelo de 4 bilhões de parâmetros, rodando localmente, responde a perguntas de alfabetização com "
        "citação de documento e página quando cercado por recuperação híbrida e por um harness que impõe recusas, avisos e remoções "
        "verificáveis, e que esses comportamentos aparecem no traço de cada resposta. Ficaram de fora: a revisão humana das respostas "
        "de referência e da anotação de relevância; a identificação da rede que publicou os quadros de habilidades; ajuste fino ou LoRA; um "
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
        "Habilidades Essenciais: Língua Portuguesa, 1º, 2º e 3º anos do Ensino Fundamental (quadros por bimestre). Documento de rede de ensino, 2021; os arquivos não identificam a secretaria responsável.",
    ]:
        add("ref", ref)

    json.dump(B, open(RAIZ / "docs" / "conteudo_artigo.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    montar(modelo_sige, B, saida, str(RAIZ / "docs"))
    palavras = sum(len(re.findall(r"\w+", b.get("texto", ""))) for b in B)
    print("ok", saida, "palavras≈", palavras)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
