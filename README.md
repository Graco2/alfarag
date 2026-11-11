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

### Servidor aberto na web (contas individuais, chave de cada pessoa)

Para abrir o servidor do grupo direto na internet, pelo IP e com HTTPS. Sem `CONTAS_DB` (uso local, HF Spaces) nada
disto vale e tudo fica aberto, como antes.

**Container.** `/etc/alfarag.env` (permissão 600, fora do git):

```
CHAVE_DO_USUARIO=1
CONTAS_DB=/data/contas.db
```

```bash
docker run -d --name alfarag --restart unless-stopped -p 127.0.0.1:7860:7860 \
  -v alfarag-dados:/data --env-file /etc/alfarag.env alfarag
```

- `-p 127.0.0.1:7860:7860`, **nunca** `-p 7860:7860`: o Docker ignora o ufw nas portas que publica. Só o Caddy, no próprio host,
  fala com o container. A porta 11434 do Ollama não é publicada.
- `-v alfarag-dados:/data`: contas e sessões (SQLite) ficam no volume e sobrevivem à recriação do container.
- `CHAVE_DO_USUARIO=1`: o servidor **ignora** `DEEPSEEK_API_KEY` e `config/conexoes.json`. Cada pessoa cola a própria chave em
  **Conexões**; ela fica só no `localStorage` do navegador, sob o nome da conta (`alfarag:chave:<usuario>:<provedor>`), e segue
  no cabeçalho `X-Chave-Remoto` a cada pergunta. O servidor a repassa ao provedor naquela requisição e não a grava nem a põe em
  traço, log ou erro. Quem não tem chave só vê os modelos locais. A tela de Conexões do servidor fica desativada nesse modo.

**Primeiro admin** (na VPS; a senha é pedida no terminal):

```bash
docker exec -it alfarag /opt/venv/bin/python -m app.contas criar-admin <usuario>
docker exec -it alfarag /opt/venv/bin/python -m app.contas listar
docker exec -it alfarag /opt/venv/bin/python -m app.contas redefinir <usuario>   # senha provisória, se o admin esquecer a dele
```

**Fluxo.**
- Sem sessão, `/` redireciona para `/entrar` (o HTML do chat não é entregue) e todo `/api/*` responde 401. Só abrem sem login
  `/entrar`, `/entrar.js`, `/styles.css`, `POST /api/entrar` e `POST /api/cadastrar`.
- **Criar conta** pede usuário (3 a 32 caracteres: letras, números, ponto ou hífen; maiúsculas não contam), senha (8 a 200
  caracteres) e confirmação. A conta nasce **pendente** e só entra depois que um admin aprova.
- Em `/ademir` (menu da conta → **Administrar contas**) o admin aprova ou recusa, desativa ou reativa, exclui, redefine a senha
  (provisória, mostrada uma vez), promove ou rebaixa e vê o último acesso. O último admin ativo não pode ser rebaixado,
  desativado nem excluído. Desativar, excluir ou redefinir derruba na hora as sessões abertas da conta.
- Cada pessoa troca a própria senha em **Trocar senha**, no menu da conta; a troca encerra as outras sessões dela. **Sair** apaga a
  sessão no servidor e as chaves de API da conta neste navegador. Se a sessão cair no meio do uso, a página volta para `/entrar`
  (a conversa aberta se perde).
- A identidade serve só para acesso e revogação: o traço das respostas não grava o usuário e não há cota.

**O que o servidor faz para nenhuma requisição vazar segredo.**
- Senha guardada como scrypt com sal (`hashlib.scrypt`, n = 2¹⁴); sessão guardada só como SHA-256 do token. Cookie
  `alfarag_sessao` `HttpOnly`, `SameSite=Strict` e `Secure`, sem `Max-Age`: vale até fechar o navegador (o servidor corta em 7 dias).
- Resposta única para login errado ("Usuário ou senha incorretos"). "Aguardando liberação" e "desativada" só aparecem para quem
  acertou a senha. Conta inexistente passa por um hash fictício, para o tempo de resposta não denunciar o nome.
- Limites por IP antes do hash: 8 senhas erradas a cada 5 min e 5 cadastros por hora. No máximo 2 hashes ao mesmo tempo e 50
  cadastros pendentes, para não derrubar a CPU que também roda o Ollama. O IP é o **último** item do `X-Forwarded-For` (o que o
  Caddy põe); os da esquerda vêm do cliente.
- Toda resposta leva `Cache-Control: no-store` (nada no cache nem no "Voltar" depois do Sair), CSP sem script nem estilo inline,
  `X-Content-Type-Options: nosniff` e `Referrer-Policy: no-referrer`. `/api/docs` e `/openapi.json` respondem 404, e o uvicorn
  sobe com `--no-server-header`. O replay `/api/traco` só serve `resultados/tracos_demo.jsonl`.
- Formulários com `method="post"` e nenhum segredo em URL. As ações de admin levam o usuário no corpo, porque o access log grava o
  caminho. O erro 422 não devolve o valor recebido.

**HTTPS com Caddy, no host da VPS.** Caddy ≥ 2.11 (a correção de IP do issue caddyserver/caddy#7399 entrou depois da 2.10).
O certificado Let's Encrypt para IP usa o perfil `shortlived` (160 h) e o Caddy o renova sozinho. Modelo de `/etc/caddy/Caddyfile`
(o IP real fica só na VPS: `sudo systemctl edit caddy` → `[Service]` / `Environment=ALFARAG_IP=<IP da VPS>`):

```
{$ALFARAG_IP} {
    tls {
        issuer acme {
            profile shortlived
        }
    }
    header Strict-Transport-Security "max-age=31536000"
    reverse_proxy 127.0.0.1:7860 {
        flush_interval -1
    }
}
```

```bash
sudo ufw allow 80,443/tcp     # a 80 é obrigatória para o desafio HTTP-01; a 7860 continua fechada
sudo systemctl restart caddy
```

- `flush_interval -1` entrega a resposta do modelo em streaming, sem buffer.
- O navegador ignora HSTS quando o endereço é um IP (RFC 6797). Quem protege é o redirecionamento HTTP→HTTPS do Caddy e o cookie
  `Secure`; divulgue o link já com `https://`.
- Plano B, se o Caddy recusar o IP: `sudo certbot certonly --standalone --ip-address <IP> --required-profile shortlived`
  (com `--pre-hook "systemctl stop caddy" --post-hook "systemctl start caddy"`, porque o standalone precisa da porta 80),
  `tls <cert> <chave>` no Caddyfile e um `--deploy-hook "systemctl reload caddy"`. O usuário `caddy` precisa conseguir ler o
  certificado e a chave.

**Migração de `ACESSO_SENHA`.** A senha única saiu. Com `ACESSO_SENHA` no ambiente o servidor **não sobe** e explica por quê,
para um env antigo não deixar tudo aberto. Tire a linha do `/etc/alfarag.env`, acrescente `CONTAS_DB=/data/contas.db`, recrie o
container com o volume e crie o 1º admin. Quem usava a senha do grupo cria a própria conta em `/entrar`.

**Conferir de fora da VPS:**

```bash
curl -sI https://<IP>/ | grep -iE '^(HTTP|location|strict-transport)'   # 303 para /entrar, com HSTS
curl -s -o /dev/null -w '%{http_code}\n' https://<IP>/openapi.json        # 404
curl -m 5 http://<IP>:7860/                                               # tem de falhar: porta fechada
```

Ainda vale a privacidade: pergunta e trechos vão ao provedor de cada pessoa, e a CPU da VPS (Ollama e embeddings) é compartilhada.

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
