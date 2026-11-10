# AGENTS.md — regras para agentes de código neste repositório

Este arquivo orienta qualquer agente (Claude Code, Codex, Cursor etc.) que for
mexer no AlfaRAG. Ele faz parte do harness do projeto: define o que o agente
pode mudar sozinho e o que exige revisão humana.

## O que é o sistema
Assistente RAG de apoio pedagógico à alfabetização (Língua Portuguesa, 2º e 3º
anos). Responde **só** com base no corpus em `corpus/`, cita documento e página,
e **não faz diagnóstico** de transtornos. Modelo local via Ollama (CPU).

## Mapa
| Caminho | Papel |
|---|---|
| `app/config.py` | Única fonte de parâmetros (modelos, chunking, corpus, orçamento, limiar). |
| `app/prompts.py` | Prompt de sistema versionado (`VERSAO_PROMPT`). |
| `app/indice.py` | Busca híbrida BM25 + embeddings (bge-m3) com RRF. |
| `app/harness.py` | Regras determinísticas antes e depois do modelo. |
| `app/pipeline.py` | Orquestra um turno e grava o traço JSONL. |
| `scripts/` | Preparação do corpus e avaliação (retrieval, respostas, juiz). |
| `benchmark/` | 24 perguntas gold + casos-limite. |
| `resultados/` | Saídas das execuções. Nunca editar à mão. |

## Comandos
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt pymupdf
ollama pull qwen3.5:4b-q4_K_M && ollama pull bge-m3
.venv/bin/python scripts/preparar_corpus.py --exp E2 --embed
.venv/bin/uvicorn app.main:app --port 7860
```

## Regras (do / don't)
- **Mudou o texto do prompt de sistema → incremente `VERSAO_PROMPT`.** O traço de cada resposta guarda a versão; sem isso, resultados antigos e novos ficam indistinguíveis.
- **Mudou chunking, modelo de embedding ou corpus → regenere o índice e rode `scripts/avaliar_retrieval.py`** antes de abrir PR.
- **Nunca relaxe uma regra do `app/harness.py` para "fazer passar" um caso.** Recusa de diagnóstico, bloqueio de dado pessoal, verificação de citação e de código BNCC são requisitos, não testes frágeis.
- **Não invente métrica.** Números de README, artigo e slides vêm de `resultados/` gerados por script.
- **Não coloque dados de alunos** em benchmark, testes ou traços. Use casos fictícios sem nome.
- Respostas de referência (`gold_answer`) só mudam com revisão humana registrada na coluna `revisao_humana`.
- Corpus novo só entra com licença compatível anotada em `corpus/documentos.json`.

## Gate humano
Mudanças em `app/prompts.py`, `app/harness.py` e `benchmark/` exigem revisão de um
integrante do grupo antes do merge.
