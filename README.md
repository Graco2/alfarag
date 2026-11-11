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
quadros de Habilidades Essenciais do 1º ao 3º ano, Manual ABC do MEC e artigos sobre
dislexia), **cita documento e página** de cada
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
                                                     LLM local (Ollama, qwen3.5:4b-q4_K_M)
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

Com Docker (só CPU; ver latência medida em `resultados/latencia_cpu.json`):

```bash
docker build -t alfarag . && docker run -p 7860:7860 alfarag
```

## Modelos remotos (opcional)

Por padrão tudo roda local. Também é possível gerar a resposta com um modelo remoto
OpenAI-compatível; o primeiro provedor é o **DeepSeek** (`deepseek-flash`, `deepseek-v4-pro`).
A recuperação, o prompt (`VERSAO_PROMPT`) e o harness não mudam, e os **embeddings continuam locais** (bge-m3).

**Configuração (só no servidor local).** Botão **Conexões** na barra superior: URL base, chave, *Testar* e *Remover*.
A chave fica em `config/conexoes.json` (permissão 600, fora do git). A variável `DEEPSEEK_API_KEY` tem prioridade sobre o
arquivo. A interface só mostra a chave mascarada; ela não aparece em traço, log, erro nem em `/api/status`.
Sem chave, os modelos remotos nem aparecem no seletor.

**Privacidade.** Com um modelo remoto, a pergunta e os trechos recuperados são enviados a um terceiro (DeepSeek, servidor fora do Brasil).
A interface avisa isso ao escolher o modelo. Não escreva dados de alunos.

**Limites.**
- Sem fallback: se o provedor falhar (chave recusada, saldo, timeout), o desfecho é `erro` com a mensagem do motivo.
- Resposta **não reprodutível**: sem `seed` nem digest. O traço registra `provedor`, `modelo_id`, tokens e `reprodutivel: false`.
- Raciocínio estendido desligado (`thinking: disabled`); temperatura e limite de tokens vêm de `app/config.py`.
- O provedor vem do prefixo do modelo (`deepseek:deepseek-flash`); nome sem prefixo continua sendo Ollama.
- Os números de `resultados/` são todos do modelo local; nenhuma avaliação do modelo remoto foi executada.

**Deploy público e Docker.** O `Dockerfile` e o `start.sh` não mudam: o servidor público não permite editar conexões (403).
Num `docker run -p 7860:7860` o cliente chega como IP da ponte; para liberar a tela de Conexões no **seu** Docker local, use
`-e CONEXOES_LOCAL=1`. Nunca defina essa variável num deploy público.

Testes (HTTP simulado, sem chamar a API real): `.venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest`.

## Deploy (Railway ou qualquer host Docker)

O container precisa de **~5 GB de RAM** (Qwen3.5 4B Q4_K_M + bge-m3) — não cabe em
planos gratuitos de 0,5–1 GB. No Railway (plano pago, cobrança por uso):

```bash
railway login --browserless      # quem tem a conta
railway init                     # novo projeto, ou: railway link
railway up                       # usa o Dockerfile da raiz
railway variables --set PORT=7860 --set OLLAMA_KEEP_ALIVE=5m
railway domain                   # gera o link público
```

`OLLAMA_KEEP_ALIVE=5m` tira o modelo da memória após 5 min parado, o que reduz o custo
por uso. O primeiro build baixa os modelos para dentro da imagem (~10–15 min).

**Plano B sem rede:** `/?traco=79904e4c3f98` (caso que responde), `/?traco=6bb3588bdd49`
(recusa sem chamar o modelo) e `/?traco=33d3387af816` (pedido de diagnóstico) reabrem
respostas gravadas em `resultados/tracos_demo.jsonl`, sem chamar o modelo.

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
| HE1, HE2, HE3 | Habilidades Essenciais — Língua Portuguesa, 1º, 2º e 3º anos (quadros por bimestre, 2021) | Documento de rede de ensino; o arquivo não identifica a secretaria responsável |
| VID | 204 resumos de vídeos do YouTube (`corpus/videos/`), feitos pelo grupo a partir da legenda automática com IA | Material derivado, uso acadêmico; cada resumo traz canal, URL, data e minutagem |

**Condição C5 (experimento):** C4 + resumos de vídeo. Os vídeos são relatos de experiência de
profissionais e chegam ao modelo rotulados como "Relato em vídeo (resumo por IA)". Por serem fonte
secundária gerada por IA, ficam fora da base da demonstração (C4); a avaliação compara C4 e C5.

Os quadros de Habilidades Essenciais são lidos célula a célula (`scripts/preparar_corpus.py::extrair_habilidades`):
cada linha da tabela vira um registro com ano, bimestre, código, objeto de conhecimento e conteúdo. Alguns
códigos são desdobramentos da BNCC com uma letra (EF02LP01A); o harness também exige que eles apareçam no trecho.

Os textos são usados para fins acadêmicos e não comerciais.
