"use strict";
// Front-end sem dependências: funciona offline na apresentação.
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const estado = { status: null, ocupado: false, respostas: [], selecionada: null };

// ---------- Markdown mínimo + citações ----------
function inline(t) {
  let h = esc(t);
  h = h.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  h = h.replace(/\[código BNCC removido pelo sistema: não consta nas fontes\]/g, '<span class="removido" title="O harness removeu um código que não aparece em nenhum trecho recuperado">código removido pelo sistema</span>');
  h = h.replace(/\[(\d{1,2}(?:\s*[,;]\s*\d{1,2})*)\]/g, (_, g) =>
    g.split(/\s*[,;]\s*/).map((n) => `<button type="button" class="cita" data-n="${n}" title="Ver fonte ${n}">${n}</button>`).join(""));
  return h;
}
function markdown(md) {
  const linhas = String(md).replace(/\r/g, "").split("\n");
  let html = "", lista = null, quote = [];
  const fechaLista = () => { if (lista) { html += `</${lista}>`; lista = null; } };
  const fechaQuote = () => { if (quote.length) { html += `<blockquote>${quote.map(inline).join("<br>")}</blockquote>`; quote = []; } };
  for (const bruta of linhas) {
    const l = bruta.trimEnd();
    if (/^\s*>/.test(l)) { fechaLista(); quote.push(l.replace(/^\s*>\s?/, "")); continue; }
    fechaQuote();
    let m;
    if ((m = l.match(/^\s*[-*•]\s+(.*)$/))) { if (lista !== "ul") { fechaLista(); html += "<ul>"; lista = "ul"; } html += `<li>${inline(m[1])}</li>`; continue; }
    if ((m = l.match(/^\s*\d+[.)]\s+(.*)$/))) { if (lista !== "ol") { fechaLista(); html += "<ol>"; lista = "ol"; } html += `<li>${inline(m[1])}</li>`; continue; }
    fechaLista();
    if (!l.trim()) continue;
    if ((m = l.match(/^#{1,6}\s+(.*)$/))) { html += `<p><strong>${inline(m[1])}</strong></p>`; continue; }
    html += `<p>${inline(l)}</p>`;
  }
  fechaLista(); fechaQuote();
  return html;
}

// ---------- Inicialização ----------
async function init() {
  document.querySelectorAll(".aba").forEach((b) => b.addEventListener("click", () => trocarAba(b.dataset.aba)));
  $("#form").addEventListener("submit", (e) => { e.preventDefault(); enviar(); });
  $("#entrada").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(); } });
  try {
    const s = await (await fetch("api/status")).json();
    estado.status = s;
    const sel = $("#modelo");
    const modelos = s.modelos.length ? s.modelos : [s.modelo_padrao];
    sel.innerHTML = modelos.map((m) => `<option ${m === s.modelo_padrao ? "selected" : ""}>${esc(m)}</option>`).join("");
    const pill = $("#pill");
    pill.textContent = s.ollama ? `Ollama online · ${s.condicao}/${s.experimento}` : "modelo offline";
    pill.className = "pill " + (s.ollama ? "on" : "off");
  } catch { $("#pill").textContent = "API offline"; $("#pill").className = "pill off"; }
  try {
    const ex = await (await fetch("api/exemplos")).json();
    const escolhidos = ["B03", "B08", "B14", "B16", "B23", "L01", "L02", "L04"];
    $("#exemplos").innerHTML = ex.filter((e) => escolhidos.includes(e.id)).map((e) =>
      `<button type="button" class="exemplo ${e.id.startsWith("L") ? "limite" : ""}" data-q="${esc(e.pergunta)}"><span class="tag">${esc(e.id.startsWith("L") ? "limite" : e.categoria)}</span>${esc(e.pergunta)}</button>`).join("");
    $("#exemplos").addEventListener("click", (e) => { const b = e.target.closest(".exemplo"); if (b) { $("#entrada").value = b.dataset.q; enviar(); } });
  } catch { /* sem exemplos */ }
  // Modo replay: /?traco=<id> reabre uma resposta gravada, sem chamar o modelo (plano B da apresentação).
  const params = new URLSearchParams(location.search);
  for (const id of (params.get("traco") || "").split(",").filter(Boolean)) await replay(id);
  if (params.get("aba")) trocarAba(params.get("aba"));
  if (params.get("rolar") === "topo") setTimeout(() => { $("#mensagens").scrollTop = 0; }, 50);
}

async function replay(id) {
  try {
    const r = await fetch(`api/traco/${encodeURIComponent(id)}`);
    if (!r.ok) return;
    const t = await r.json();
    const u = adicionar("#tpl-msg-usuario"); $(".bolha", u).textContent = t.pergunta;
    const a = adicionar("#tpl-msg-assistente");
    const reg = { pergunta: t.pergunta, janela: null, final: null, el: a, bruto: "" };
    estado.respostas.push(reg);
    a.addEventListener("click", (e) => { const c = e.target.closest(".cita"); selecionar(reg); if (c) destacarFonte(reg, +c.dataset.n); });
    if (t.janela) tratar(reg, { tipo: "contexto", janela: t.janela });
    tratar(reg, t.final);
    selecionar(reg);
  } catch { /* traço indisponível */ }
}

function trocarAba(aba) {
  document.querySelectorAll(".aba").forEach((b) => { const on = b.dataset.aba === aba; b.classList.toggle("ativa", on); b.setAttribute("aria-selected", on); });
  $("#aba-chat").hidden = aba !== "chat";
  $("#aba-aval").hidden = aba !== "aval";
  if (aba === "aval") carregarAvaliacao();
}

// ---------- Conversa ----------
function adicionar(tpl) {
  const n = $(tpl).content.firstElementChild.cloneNode(true);
  $("#boasvindas")?.remove();
  $("#mensagens").appendChild(n);
  n.scrollIntoView({ behavior: "smooth", block: "end" });
  return n;
}

async function enviar() {
  const pergunta = $("#entrada").value.trim();
  if (!pergunta || estado.ocupado) return;
  estado.ocupado = true; $("#enviar").disabled = true; $("#entrada").value = "";
  const u = adicionar("#tpl-msg-usuario"); $(".bolha", u).textContent = pergunta;
  const a = adicionar("#tpl-msg-assistente");
  const reg = { pergunta, janela: null, final: null, el: a, bruto: "" };
  estado.respostas.push(reg);
  a.addEventListener("click", (e) => {
    const c = e.target.closest(".cita");
    selecionar(reg);
    if (c) destacarFonte(reg, +c.dataset.n);
  });
  selecionar(reg);
  const t0 = performance.now();
  try {
    const r = await fetch("api/perguntar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pergunta, modelo: $("#modelo").value }) });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const leitor = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await leitor.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) { const linha = buf.slice(0, i); buf = buf.slice(i + 1); if (linha.trim()) tratar(reg, JSON.parse(linha)); }
    }
    if (buf.trim()) tratar(reg, JSON.parse(buf));
  } catch (err) {
    $(".texto", a).innerHTML = `<p>Falha de conexão com o servidor (${esc(err.message)}).</p>`;
  } finally {
    estado.ocupado = false; $("#enviar").disabled = false;
    const seg = ((performance.now() - t0) / 1000).toFixed(1);
    const m = $(".meta", a); if (!m.textContent) m.textContent = `${seg} s`;
  }
}

function tratar(reg, ev) {
  const a = reg.el;
  if (ev.tipo === "contexto") {
    reg.janela = ev.janela;
    $(".texto", a).innerHTML = `<span class="digitando">${ev.janela.cobertura.coberta ? `${ev.janela.trechos.length} trechos recuperados — o modelo está escrevendo` : "verificando cobertura"}</span>`;
    if (estado.selecionada === reg) renderPainel(reg);
  } else if (ev.tipo === "delta") {
    reg.bruto += ev.texto;
    $(".texto", a).innerHTML = markdown(reg.bruto) + '<span class="digitando"></span>';
  } else if (ev.tipo === "final") {
    reg.final = ev;
    $(".texto", a).innerHTML = markdown(ev.resposta);
    renderSelos(reg); renderFontes(reg);
    const o = ev.traco?.ollama;
    $(".meta", a).textContent = [ev.desfecho === "respondida" ? ev.traco?.modelo : "modelo não chamado", o ? `${o.resposta_tokens} tokens · ${o.tok_s} tok/s` : null, ev.traco?.latencia_s != null ? `${ev.traco.latencia_s} s` : null, ev.traco?.id ? `traço ${ev.traco.id}` : null].filter(Boolean).join(" · ");
    if (estado.selecionada === reg) renderPainel(reg);
  }
  a.scrollIntoView({ block: "end" });
}

function renderSelos(reg) {
  const f = reg.final, v = f.verificacao, s = [];
  const d = f.desfecho;
  if (d === "bloqueada") s.push(["bad", "bloqueada pelo harness de entrada"]);
  if (d === "sem_cobertura") s.push(["warn", "recusa: fontes não cobrem a pergunta (modelo não foi chamado)"]);
  if (d === "erro" || d === "ocupado") s.push(["bad", d === "erro" ? "erro do modelo" : "servidor ocupado"]);
  if (v) {
    if (v.citacoes_validas.length) s.push(["ok", `${v.citacoes_validas.length} fonte(s) citada(s) e conferida(s)`]);
    if (v.sem_citacao) s.push(["warn", "sem citação"]);
    if (v.citacoes_invalidas.length) s.push(["bad", `citação inexistente removida: ${v.citacoes_invalidas.join(", ")}`]);
    if (v.codigos_ok.length) s.push(["ok", `BNCC conferida: ${v.codigos_ok.join(", ")}`]);
    if (v.codigos_removidos.length) s.push(["bad", `código BNCC removido: ${v.codigos_removidos.join(", ")}`]);
    if (v.modo_ressalva) s.push([v.ressalva_forcada ? "warn" : "info", v.ressalva_forcada ? "modo ressalva: aviso de diagnóstico inserido pelo sistema" : "modo ressalva: limite de diagnóstico declarado"]);
    if (v.truncada) s.push(["warn", "resposta cortada"]);
  }
  $(".selos", reg.el).innerHTML = s.map(([c, t]) => `<span class="selo ${c}">${esc(t)}</span>`).join("");
}

function renderFontes(reg) {
  const j = reg.janela; const det = $(".fontes", reg.el);
  if (!j || !j.trechos.length || reg.final.desfecho !== "respondida") return;
  const usadas = new Set(reg.final.verificacao?.citacoes_validas || []);
  $("summary", det).textContent = `${j.trechos.length} trechos na janela · ${usadas.size} citados`;
  $("ol", det).innerHTML = j.trechos.map((t) => `<li data-n="${t.n}"><span class="n">[${t.n}]</span><div><span class="doc">${esc(t.rotulo)}</span><span class="pag">${esc(t.pagina)}${usadas.has(t.n) ? " · citado" : ""}</span><span class="exc">${esc(t.secao ? t.secao + " — " : "")}${esc(t.texto.slice(0, 260))}…</span></div></li>`).join("");
  det.hidden = false;
}

function destacarFonte(reg, n) {
  const det = $(".fontes", reg.el); if (det.hidden) return;
  det.open = true;
  det.querySelectorAll("li").forEach((li) => li.classList.toggle("destaque", +li.dataset.n === n));
  det.querySelector(`li[data-n="${n}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  document.querySelector(`#painel .trecho[data-n="${n}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function selecionar(reg) {
  estado.respostas.forEach((r) => r.el.classList.toggle("selecionada", r === reg));
  estado.selecionada = reg; renderPainel(reg);
}

// ---------- Painel: janela de contexto ----------
function renderPainel(reg) {
  const p = $("#painel");
  const j = reg.janela, f = reg.final;
  if (!j) {
    p.innerHTML = f ? `<div class="bloco"><h3>Harness de entrada</h3><div class="check"><b>⛔</b><span>${esc(f.resposta)}</span></div><p class="vazio">Nada foi recuperado nem enviado ao modelo.</p></div>` : `<p class="vazio">Aguardando…</p>`;
    return;
  }
  const enviado = j.cobertura.coberta;
  const sis = j.sistema.tokens, q = j.pergunta_tokens, t = enviado ? j.usados : 0, tot = Math.max(sis + q + j.orcamento, 1);
  const pct = (x) => `${(100 * x / tot).toFixed(1)}%`;
  const v = f?.verificacao;
  const checks = [
    ["✅", "Entrada aceita (sem dado pessoal)"],
    [j.modo_ressalva ? "⚠️" : "✅", j.modo_ressalva ? "Pedido de diagnóstico detectado → modo ressalva" : "Sem pedido de diagnóstico"],
    [j.cobertura.coberta ? "✅" : "⛔", `Cobertura: melhor similaridade ${j.cobertura.melhor_cos} (limiar ${j.cobertura.limiar})${j.cobertura.coberta ? "" : " → recusa sem chamar o modelo"}`],
  ];
  if (v) {
    checks.push([v.citacoes_invalidas.length ? "⛔" : v.sem_citacao ? "⚠️" : "✅", `Citações válidas: ${v.citacoes_validas.join(", ") || "nenhuma"}${v.citacoes_invalidas.length ? ` · inválidas removidas: ${v.citacoes_invalidas.join(", ")}` : ""}`]);
    checks.push([v.codigos_removidos.length ? "⛔" : "✅", `Códigos BNCC: ${v.codigos_ok.join(", ") || "nenhum citado"}${v.codigos_removidos.length ? ` · removidos: ${v.codigos_removidos.join(", ")}` : ""}`]);
    if (v.modo_ressalva) checks.push([v.ressalva_forcada ? "⚠️" : "✅", v.ressalva_forcada ? "Modelo não declarou o limite → aviso inserido pelo sistema" : "Modelo declarou que não diagnostica"]);
  }
  p.innerHTML = `
    <div class="bloco"><h3>Orçamento da janela</h3>
      <div class="barra" title="tokens aproximados"><span class="s" style="width:${pct(sis)}"></span><span class="q" style="width:${pct(q)}"></span><span class="t" style="width:${pct(t)}"></span></div>
      <div class="legenda"><span><i style="background:var(--muted-2)"></i>prompt de sistema ${j.sistema.versao} · ~${sis}</span><span><i style="background:var(--info)"></i>pergunta ~${q}</span><span><i style="background:var(--brand)"></i>trechos ~${t} / ${j.orcamento}</span></div>
    </div>
    <div class="bloco"><h3>Harness</h3>${checks.map(([i, txt]) => `<div class="check"><b>${i}</b><span>${esc(txt)}</span></div>`).join("")}</div>
    <div class="bloco"><h3>${enviado ? `Entrou na janela (top-${j.top_k})` : "Recuperados, mas NÃO enviados (modelo não chamado)"}</h3>${j.trechos.length ? j.trechos.map((c) => `
      <div class="trecho${enviado ? "" : " fora"}" data-n="${c.n}"><div class="cab"><span><span class="num">[${c.n}]</span>${esc(c.rotulo)} · ${esc(c.pagina)}</span><span class="pts" title="rank denso / rank BM25 / similaridade">D${c.rank_denso ?? "–"} · L${c.rank_bm25 ?? "–"} · cos ${c.cos}</span></div>
      ${c.secao ? `<div class="sec">${esc(c.secao)}</div>` : ""}<details><summary>ver trecho (~${c.tokens} tokens)</summary><p>${esc(c.texto)}</p></details></div>`).join("") : '<p class="vazio">Nenhum trecho.</p>'}
    </div>
    <div class="bloco"><h3>Ficou de fora (${j.fora_total} candidatos)</h3>${j.fora.slice(0, 6).map((c) => `
      <div class="trecho fora"><div class="cab"><span>${esc(c.rotulo)} · ${esc(c.pagina)}</span><span class="pts">cos ${c.cos}</span></div><div class="mot">${esc(c.motivo)}</div></div>`).join("")}
      <h3 style="margin-top:10px">Nunca entra</h3><ul class="lista-simples">${j.nao_entra.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    </div>`;
}

// ---------- Aba de avaliação ----------
let avaliacaoCarregada = false;
async function carregarAvaliacao() {
  if (avaliacaoCarregada) return; avaliacaoCarregada = true;
  try {
    const pr = await (await fetch("api/prompt")).json();
    $("#prompt").textContent = `[${pr.versao}]\n\n${pr.sistema}`;
  } catch { $("#prompt").textContent = "indisponível"; }
  const s = estado.status;
  if (s) $("#config").innerHTML = [
    `LLM: ${s.modelo_padrao}`, `embeddings: ${s.modelo_embed}`, `chunk: ${s.experimento} (${s.chunk.tokens ?? "seção"} tokens, ${Math.round(s.chunk.sobreposicao * 100)}%, top-${s.chunk.top_k})`,
    `corpus ${s.condicao}: ${s.documentos.map((d) => d.id).join(", ")}`, `orçamento: ${s.orcamento_contexto} tokens`, `limiar de cobertura: ${s.limiar_cobertura}`,
  ].map((x) => `<span>${esc(x)}</span>`).join("");
  try {
    const a = await (await fetch("api/avaliacao")).json();
    if (a.disponivel === false) { $("#avaliacao").innerHTML = '<p class="vazio">A avaliação ainda não foi executada neste servidor.</p>'; return; }
    $("#avaliacao").innerHTML = renderAvaliacao(a);
  } catch { $("#avaliacao").innerHTML = '<p class="vazio">indisponível</p>'; }
}

function tabela(cab, linhas) {
  return `<table><thead><tr>${cab.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${linhas.map((l) => `<tr>${l.map((x) => `<td class="${typeof x === "number" ? "num" : ""}">${esc(x)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
function renderAvaliacao(a) {
  let h = `<p class="nota">Executada em ${esc(a.quando)} · ${esc(a.hardware || "")}. ${esc(a.nota || "")}</p>`;
  if (a.recuperacao) h += `<h3>Recuperação (24 perguntas, anotação por regra)</h3>` + tabela(["Chunking", "Corpus", "Recall@k", "MRR", "k"], a.recuperacao.map((r) => [r.experimento, r.condicao, r.recall, r.mrr, r.k]));
  if (a.geracao) h += `<h3>Geração (rubrica 0–10, juiz: ${esc(a.juiz || "")})</h3>` + tabela(["Modelo", "Corpus", "Média", "≥ 8", "Citação válida", "Código removido", "Latência média (s)"], a.geracao.map((r) => [r.modelo, r.condicao, r.media, r.prop_8, r.cit_ok, r.cod_removidos, r.latencia]));
  if (a.limites) h += `<h3>Casos-limite</h3>` + tabela(["Caso", "Esperado", "Desfecho", "Passou"], a.limites.map((r) => [r.id, r.esperado, r.desfecho, r.passou ? "sim" : "não"]));
  return h;
}

init();
