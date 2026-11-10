---
title: AlfaRAG
emoji: 📚
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 7860
pinned: false
short_description: RAG local de apoio à alfabetização (2º e 3º anos)
---

# AlfaRAG — Alfabetização Inclusiva com RAG local

Assistente de **apoio à decisão pedagógica** para professores de Língua Portuguesa do
**2º e 3º anos do Ensino Fundamental**, com foco em alfabetização e dificuldades
persistentes de leitura. Ele responde **apenas** com base num corpus fechado (BNCC,
Manual ABC do MEC e artigos sobre dislexia), **cita documento e página** de cada
afirmação e **não faz diagnóstico** de dislexia, TDAH, TEA ou outros transtornos.

Projeto do Exame de TE-251 (ITA, 2026/2) — Grupo **Imeanos no ITA**: Neuton Severo,
Beatriz Luberiaga, Murilo Narciso, Priscila e Ricardo Graco de Souza Lima Castellano.

> Não é instrumento de triagem nem substitui avaliação profissional. A decisão
> pedagógica final é do professor e da equipe escolar.

## Técnicas da disciplina, onde aparecem no código

| Técnica | Onde |
|---|---|
| **Prompt Engineering** | `app/prompts.py` — prompt de sistema versionado (`VERSAO_PROMPT`), formato em 4 partes, regras de citação. |
| **Context Engineering** | `app/pipeline.py::selecionar_janela` — top-k + orçamento de tokens; o painel do app mostra o que entrou, o que ficou de fora e por quê. Histórico da conversa **não** entra. |
| **RAG com corpus, recuperação e citação** | `scripts/preparar_corpus.py` (página impressa + seção), `app/indice.py` (BM25 + bge-m3 + RRF), citações `[n]` com documento e página. |
| **RAG com avaliação** | `scripts/avaliar_retrieval.py` (Recall@5, MRR), `scripts/julgar_respostas.py` (outro modelo julga com rubrica 0–2), traço JSONL por resposta. |
| **Harness** | `app/harness.py` — bloqueio de dado pessoal, modo ressalva para pedido de diagnóstico, recusa sem chamar o modelo quando as fontes não cobrem, verificação de citação e de código BNCC na saída, fila de uma geração por vez. |
| **AGENTS.md + Agent Skill** | `AGENTS.md` (regras para agentes de código) e `SKILL.md` (skill de avaliação). |

## Arquitetura

```
pergunta ──► harness de entrada ──► busca híbrida (BM25 + bge-m3, RRF) ──► cobertura? ──não──► recusa (sem LLM)
               │ dado pessoal → bloqueia                                     │sim
               │ diagnóstico → modo ressalva                                 ▼
                                                     janela: prompt v1.2 + top-k trechos [n] (≤ orçamento)
                                                                             ▼
                                                     LLM local (Ollama, qwen3.5:4b-q4_K_M, CPU)
                                                                             ▼
                              harness de saída: [n] existe? código BNCC está no trecho? ressalva presente?
                                                                             ▼
                                                     resposta + fontes + traço JSONL
```

## Rodar localmente

Requer [Ollama](https://ollama.com) e Python 3.11+.

```bash
ollama pull qwen3.5:4b-q4_K_M && ollama pull bge-m3
python -m venv .venv && .venv/bin/pip install -r requirements.txt pymupdf
# o índice E2 já vem no repositório; para regenerar:
.venv/bin/python scripts/preparar_corpus.py --exp E2 --embed
.venv/bin/uvicorn app.main:app --port 7860
# abra http://localhost:7860
```

Com Docker (CPU, igual ao deploy):

```bash
docker build -t alfarag . && docker run -p 7860:7860 alfarag
```

## Avaliação

Ver `SKILL.md`. Resumo executado em `resultados/resumo.json` e na aba
**Como funciona e avaliação** do app.

## Corpus e licenças

| Id | Documento | Licença |
|---|---|---|
| BNCC | Base Nacional Comum Curricular (MEC, 2018), recorte Linguagens/LP, p. 63–111 | Documento público |
| ABC | Alfabetização Baseada na Ciência — Manual do Curso ABC (MEC/CAPES, 2021) | Documento público |
| RAMLI | Ramli et al. (2026), IJRISS — revisão narrativa sobre dislexia | Acesso aberto |
| HALL | Hall et al. (2023), Reading Research Quarterly 58(2) — meta-análise | CC BY-NC-ND |
| ROSA | Guia de orientação (produto educacional de mestrado) | Acesso público |
| PNEEI | Cadernos Pedagógicos PNEEI, v. 10 | Documento público |

Os textos são usados para fins acadêmicos e não comerciais.
