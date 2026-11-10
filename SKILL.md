---
name: avaliar-rag-alfabetizacao
description: Executa a avaliação completa do AlfaRAG (recuperação com Recall@5/MRR, geração das respostas das 24 perguntas gold e casos-limite, julgamento por outro modelo com a rubrica 0–2 e consolidação do resumo). Use quando mudar prompt, chunking, corpus ou modelo, ou quando pedirem "rodar o benchmark" / "atualizar os resultados".
---

# Skill: avaliar o RAG de alfabetização

## Quando usar
- Depois de qualquer mudança em `app/prompts.py`, `app/config.py`, `corpus/` ou no modelo.
- Para gerar os números do artigo e dos slides (nunca escreva números à mão).

## Pré-requisitos
- Ollama rodando em `OLLAMA_URL` (padrão `http://127.0.0.1:11434`) com `bge-m3`, `qwen3.5:4b` e `gemma4:e4b`.
- Índices em `index/` (gerar com `scripts/preparar_corpus.py --exp todos --embed`).

## Passos
1. **Recuperação** (rápido, sem LLM):
   `python scripts/avaliar_retrieval.py` → `resultados/recuperacao.{csv,json}`
2. **Respostas** (uma execução por configuração; retoma de onde parou):
   ```bash
   python scripts/avaliar_respostas.py --modelo qwen3.5:4b --condicao C4 --exp E2
   python scripts/avaliar_respostas.py --modelo qwen3.5:4b --condicao C1 --exp E2
   python scripts/avaliar_respostas.py --modelo gemma4:e4b --condicao C4 --exp E2
   ```
3. **Juiz cruzado** (o juiz nunca é só o próprio modelo avaliado):
   ```bash
   for f in resultados/respostas_*_E2.jsonl; do
     python scripts/julgar_respostas.py --respostas "$f" --juiz gemma4:e4b
     python scripts/julgar_respostas.py --respostas "$f" --juiz qwen3.5:4b
   done
   ```
4. **Consolidar**: `python scripts/consolidar.py` → `resultados/resumo.json` (lido pela aba "Avaliação" do app).

## Como ler
- Recall@5 e MRR usam **anotação por regra** (código BNCC literal ou capítulo do Manual ABC); é um proxy até a revisão humana dos trechos.
- A nota do juiz é **descritiva**, não prova de eficácia pedagógica. Reporte sempre qual modelo julgou.
- Casos-limite (L01–L06) são conferidos por regra: o desfecho tem de ser o esperado.

## Não faça
- Não altere `benchmark/perguntas_gold.csv` para melhorar nota.
- Não apague resultados antigos: crie arquivos novos com outra configuração.
