"use strict";
// Front-end sem dependências: funciona offline na apresentação.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const estado = { status: null, ocupado: false, respostas: [], selecionada: null };

// Preferências do navegador (só conveniência; a página funciona sem elas).
const pref = {
  get(k, d) { try { const v = localStorage.getItem("alfarag:" + k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("alfarag:" + k, v); } catch { /* sem armazenamento */ } },
};

// ---------- Markdown mínimo + citações ----------
function inline(t) {
  let h = esc(t);
  h = h.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  h = h.replace(/\[código BNCC removido pelo sistema: não consta nas fontes\]/g, '<span class="removido" title="O harness removeu um código que não aparece em nenhum trecho recuperado">código removido pelo sistema</span>');
  h = h.replace(/\[(\d{1,2}(?:\s*[,;]\s*\d{1,2})*)\]/g, (_, g) =>
    g.split(/\s*[,;]\s*/).map((n) => `<button type="button" class="cita" data-n="${n}" title="Ver a fonte ${n}">${n}</button>`).join(""));
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
  $$(".aba").forEach((b) => b.addEventListener("click", () => trocarAba(b.dataset.aba)));
  $("#form").addEventListener("submit", (e) => { e.preventDefault(); enviar(); });
  const campo = $("#entrada");
  campo.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); enviar(); } });
  campo.addEventListener("input", ajustarAltura);
  $("#btn-painel").addEventListener("click", () => mostrarPainel(document.body.classList.contains("sem-painel")));
  $("#modelo").addEventListener("change", atualizarAvisoRemoto);
  $("#btn-conexoes").addEventListener("click", abrirConexoes);
  $("#btn-senha").addEventListener("click", abrirTrocaSenha);
  $("#form-senha").addEventListener("submit", trocarSenha);
  $("#btn-sair").addEventListener("click", sair);
  document.addEventListener("click", (e) => { const m = $("#menu-conta"); if (m.open && !m.contains(e.target)) m.open = false; });

  const params = new URLSearchParams(location.search);
  mostrarPainel(params.has("painel") ? params.get("painel") !== "0" : pref.get("painel", "1") === "1", false);

  try {
    const s = await (await api("api/status")).json();
    estado.status = s;
    if (s.login_ativo) chaveLocal.limparSemDono();
    montarConta(s);
    montarSeletor(s);
    // Servidor público: a tela nem aparece. No compartilhado (chave por usuário) ela é onde cada pessoa cola a própria chave.
    $("#btn-conexoes").hidden = !(s.conexoes_editaveis || s.chave_do_usuario);
    status(s.ollama ? "on" : "off", s.ollama ? `Modelo local pronto · ${s.condicao}` : "Modelo offline");
    if (s.documentos?.length) $("#base").innerHTML = `<b>Base consultada:</b> ${s.documentos.map((d) => esc(d.rotulo)).join(" · ")}`;
  } catch { status("off", "API offline"); }
  try {
    const ex = await (await api("api/exemplos")).json();
    const exemplo = (e) => `<button type="button" class="exemplo" data-q="${esc(e.pergunta)}"><span class="tag">${esc(e.categoria)}</span>${esc(e.pergunta)}</button>`;
    const bench = ["B02", "B03", "B08", "B14", "B16", "B23"], lim = ["L01", "L02", "L03", "L04"];
    $("#exemplos").innerHTML = ex.filter((e) => bench.includes(e.id)).map(exemplo).join("");
    $("#limites").innerHTML = ex.filter((e) => lim.includes(e.id)).map(exemplo).join("");
    $("#boasvindas").addEventListener("click", (e) => { const b = e.target.closest(".exemplo"); if (b) { $("#entrada").value = b.dataset.q; enviar(); } });
  } catch { /* sem exemplos */ }
  // Modo replay: /?traco=<id> reabre uma resposta gravada, sem chamar o modelo (plano B da apresentação).
  for (const id of (params.get("traco") || "").split(",").filter(Boolean)) await replay(id);
  if (params.get("aba")) trocarAba(params.get("aba"));
  if (params.get("rolar") === "topo") setTimeout(() => { $("#mensagens").scrollTop = 0; }, 50);
}

// ---------- Conta (servidor aberto na web, login ativo) ----------
// Com login, qualquer 401 quer dizer sessão encerrada (Sair em outra aba, conta desativada, senha redefinida).
async function api(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) { location.replace("entrar"); throw new Error("sessão encerrada: entre de novo"); }
  return r;
}
const detalhe = (d, status) => (typeof d?.detail === "string" ? d.detail : `Falha (${status}).`);

function montarConta(s) {
  const c = s.conta;
  $("#menu-conta").hidden = !c;
  if (!c) return;
  $("#conta-nome").textContent = c.usuario;
  $("#link-admin").hidden = !c.admin;
  $("#senha-usuario").defaultValue = c.usuario;  // para o gerenciador de senhas saber de qual conta é
}

async function sair() {
  chaveLocal.limparConta();  // antes da rede: mesmo se a requisição falhar, a chave não fica neste navegador
  try { await fetch("api/sair", { method: "POST", headers: JSON_HDR, body: "{}" }); } catch { /* a sessão vence no servidor */ }
  location.replace("entrar");
}

function abrirTrocaSenha() {
  $("#menu-conta").open = false;
  $("#form-senha").reset();
  avisoSenha("", "");
  $("#dlg-senha").showModal(); $("#senha-atual").focus();
}
function avisoSenha(cls, texto) { const r = $("#senha-res"); r.className = "res " + cls; r.textContent = texto; }

async function trocarSenha(e) {
  e.preventDefault();
  const nova = $("#senha-nova").value, confirmacao = $("#senha-conf").value;
  if (nova !== confirmacao) return avisoSenha("bad", "As senhas novas não conferem.");
  const b = $("#form-senha button[type=submit]"); b.disabled = true;
  try {
    const r = await api("api/senha", { method: "POST", headers: JSON_HDR, body: JSON.stringify({ atual: $("#senha-atual").value, nova, confirmacao }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) return avisoSenha("bad", detalhe(d, r.status));
    $("#form-senha").reset();
    avisoSenha("ok", "Senha alterada. As outras sessões desta conta foram encerradas.");
  } catch (err) { avisoSenha("bad", `Falha de conexão com o servidor (${err.message}).`); }
  finally { b.disabled = false; }
}

// ---------- Chave do usuário (servidor compartilhado): fica só neste navegador ----------
// Com login, a chave fica sob o nome da conta (alfarag:chave:<usuario>:<provedor>) e o Sair a apaga.
const PREFIXO_CHAVE = "alfarag:chave:";
const chaveLocal = {
  prefixo() { const u = estado.status?.conta?.usuario; return u ? `${PREFIXO_CHAVE}${u}:` : PREFIXO_CHAVE; },
  get(p) { try { return localStorage.getItem(this.prefixo() + p) || ""; } catch { return ""; } },
  set(p, k) { try { localStorage.setItem(this.prefixo() + p, k); return true; } catch { return false; } },
  del(p) { try { localStorage.removeItem(this.prefixo() + p); } catch { /* sem armazenamento */ } },
  limpar(filtro) {  // filtro recebe o que vem depois de "alfarag:chave:"
    try { Object.keys(localStorage).filter((n) => n.startsWith(PREFIXO_CHAVE) && filtro(n.slice(PREFIXO_CHAVE.length))).forEach((n) => localStorage.removeItem(n)); } catch { /* sem armazenamento */ }
  },
  limparConta() { const u = estado.status?.conta?.usuario; if (u) this.limpar((resto) => resto.startsWith(u + ":")); },
  limparSemDono() { this.limpar((resto) => !resto.includes(":")); },  // chaves de antes do login (alfarag:chave:<provedor>)
};
const mascara = (k) => (k.length >= 16 ? `${k.slice(0, 3)}…${k.slice(-4)}` : "••••••••");
const provedorDe = (m) => m.split(":")[0];
function cabecalhoChave(modelo) {
  const k = estado.status?.chave_do_usuario && ehRemoto(modelo) ? chaveLocal.get(provedorDe(modelo)) : "";
  return k ? { "X-Chave-Remoto": k } : {};
}

// ---------- Modelos locais e remotos ----------
const ehRemoto = (m) => /^[a-z0-9_-]+:/.test(m || "") && (estado.status?.modelos_remotos || []).includes(m);
const rotuloProvedor = (m) => (estado.status?.remoto || []).find((r) => m.startsWith(r.provedor + ":"));

function montarSeletor(s) {
  const sel = $("#modelo"), atual = sel.value;
  // servidor compartilhado: o modelo remoto só aparece para quem já guardou a própria chave
  const remotos = (s.modelos_remotos || []).filter((m) => !s.chave_do_usuario || chaveLocal.get(provedorDe(m)));
  const locais = s.modelos.filter((m) => !(s.modelos_remotos || []).includes(m));
  const opt = (m, rot) => `<option value="${esc(m)}" ${m === (atual || s.modelo_padrao) ? "selected" : ""}>${esc(rot || m)}</option>`;
  const locaisHtml = (locais.length ? locais : [s.modelo_padrao]).map((m) => opt(m)).join("");
  sel.innerHTML = remotos.length
    ? `<optgroup label="Local (Ollama)">${locaisHtml}</optgroup><optgroup label="Remoto">${remotos.map((m) => opt(m, m.replace(":", " · "))).join("")}</optgroup>`
    : locaisHtml;
  atualizarAvisoRemoto();
}

function atualizarAvisoRemoto() {
  const m = $("#modelo").value, remoto = ehRemoto(m), p = remoto ? rotuloProvedor(m) : null;
  const av = $("#aviso-remoto");
  av.hidden = !remoto;
  if (remoto) av.textContent = `Modelo remoto: a pergunta e os trechos recuperados serão enviados à ${p?.rotulo || "um terceiro"} (${p?.pais || "fora do seu controle"}), com a sua chave.`
    + (estado.status?.chave_do_usuario ? " A chave fica só neste navegador e passa pelo servidor sem ser gravada." : "")
    + " Não escreva dados de alunos. A resposta pode variar entre execuções.";
  const g = $("#garantia-local span:last-child");
  if (g) g.textContent = remoto ? "Modelo remoto: dados saem desta máquina" : "Roda localmente, sem internet";
}

// ---------- Diálogo de conexões (somente servidor local) ----------
const JSON_HDR = { "Content-Type": "application/json" };

async function abrirConexoes() {
  await renderConexoes();
  $("#dlg-conexoes").showModal();
}

function renderChavesUsuario(msg) {
  const box = $("#lista-conexoes");
  box.innerHTML = (estado.status.remoto || []).map((c) => {
    const k = chaveLocal.get(c.provedor), m = msg?.p === c.provedor ? msg : null;
    return `<section class="conexao" data-p="${esc(c.provedor)}" data-usuario="1">
      <h3>${esc(c.rotulo)} <span class="selo ${k ? "ok" : "info"}">${k ? "chave neste navegador" : "sem chave"}</span></h3>
      <label for="chave-${esc(c.provedor)}">Sua chave de API</label>
      <input id="chave-${esc(c.provedor)}" class="f-chave" type="password" autocomplete="off" spellcheck="false" placeholder="${k ? esc(mascara(k)) : "cole a sua chave aqui"}">
      <p class="dica-chave">A chave fica só no armazenamento deste navegador. A cada pergunta ela é enviada ao servidor (use HTTPS) e repassada à ${esc(c.rotulo)}; o servidor não a grava. Servidor da ${esc(c.rotulo)}: ${esc(c.pais)}.</p>
      <div class="linha">
        <button type="button" class="btn-sec a-salvar">Salvar</button>
        <button type="button" class="btn-sec a-testar" ${k ? "" : "disabled"}>Testar</button>
        <button type="button" class="btn-sec btn-perigo a-remover" ${k ? "" : "disabled"}>Remover</button>
      </div>
      <p class="res ${m ? m.cls : ""}" role="status">${m ? esc(m.texto) : ""}</p></section>`;
  }).join("");
}

async function renderConexoes(msg) {
  const box = $("#lista-conexoes");
  if (estado.status?.chave_do_usuario) return renderChavesUsuario(msg);
  try {
    const r = await api("api/conexoes");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const { conexoes } = await r.json();
    box.innerHTML = conexoes.map((c) => `
      <section class="conexao" data-p="${esc(c.provedor)}">
        <h3>${esc(c.rotulo)} <span class="selo ${c.configurada ? "ok" : "info"}">${c.configurada ? "configurada" : "desligada"}</span></h3>
        <label for="url-${esc(c.provedor)}">URL base</label>
        <input id="url-${esc(c.provedor)}" class="f-url" value="${esc(c.url_base)}" autocomplete="off" spellcheck="false">
        <label for="chave-${esc(c.provedor)}">Chave de API</label>
        <input id="chave-${esc(c.provedor)}" class="f-chave" type="password" autocomplete="off" spellcheck="false"
               placeholder="${c.configurada ? esc(c.chave_mascarada) : "cole a chave aqui"}">
        <p class="dica-chave">${c.origem === "ambiente" ? "Chave vinda da variável de ambiente (tem prioridade sobre a salva)." : c.configurada ? "Chave salva neste computador (config/conexoes.json). Deixe em branco para manter." : "Fica salva só neste computador, fora do repositório."}</p>
        <p class="dica-chave">Modelos: ${c.modelos.map(esc).join(", ")} · servidor ${esc(c.pais)}</p>
        <div class="linha">
          <button type="button" class="btn-sec a-salvar">Salvar</button>
          <button type="button" class="btn-sec a-testar" ${c.configurada ? "" : "disabled"}>Testar</button>
          <button type="button" class="btn-sec btn-perigo a-remover" ${c.configurada || c.origem ? "" : "disabled"}>Remover</button>
        </div>
        <p class="res ${msg?.p === c.provedor ? msg.cls : ""}" role="status">${msg?.p === c.provedor ? esc(msg.texto) : ""}</p>
      </section>`).join("");
  } catch (e) { box.innerHTML = `<p class="vazio">Conexões indisponíveis neste servidor (${esc(e.message)}).</p>`; }
}

$("#lista-conexoes").addEventListener("click", async (e) => {
  const sec = e.target.closest(".conexao"), b = e.target.closest("button");
  if (!sec || !b) return;
  const p = sec.dataset.p, aviso = (cls, texto) => renderConexoes({ p, cls, texto });
  b.disabled = true;
  try {
    if (sec.dataset.usuario) {  // servidor compartilhado: tudo acontece neste navegador
      if (b.classList.contains("a-salvar")) {
        const k = $(".f-chave", sec).value.trim();
        if (!k) { await aviso("bad", "Cole a chave para salvar."); return; }
        if (k.length < 8 || /\s/.test(k)) { await aviso("bad", "Chave inválida."); return; }
        if (!chaveLocal.set(p, k)) { await aviso("bad", "O navegador bloqueou o armazenamento: a chave não foi salva."); return; }
        montarSeletor(estado.status);
        await aviso("ok", "Salva neste navegador.");
      } else if (b.classList.contains("a-testar")) {
        const t = await (await api(`api/remoto/${p}/testar`, { method: "POST", headers: { "X-Chave-Remoto": chaveLocal.get(p) } })).json();
        await aviso(t.ok ? "ok" : "bad", t.mensagem);
      } else if (b.classList.contains("a-remover")) {
        chaveLocal.del(p); montarSeletor(estado.status);
        await aviso("ok", "Chave removida deste navegador.");
      }
      return;
    }
    if (b.classList.contains("a-salvar")) {
      const corpo = { url_base: $(".f-url", sec).value };
      const k = $(".f-chave", sec).value.trim(); if (k) corpo.chave = k;
      const r = await api(`api/conexoes/${p}`, { method: "PUT", headers: JSON_HDR, body: JSON.stringify(corpo) });
      if (!r.ok) { await aviso("bad", (await r.json().catch(() => ({}))).detail || `Falha (${r.status}).`); return; }
      await aviso("ok", "Salvo.");
    } else if (b.classList.contains("a-testar")) {
      const t = await (await api(`api/conexoes/${p}/testar`, { method: "POST", headers: JSON_HDR, body: "{}" })).json();
      await aviso(t.ok ? "ok" : "bad", t.mensagem);
    } else if (b.classList.contains("a-remover")) {
      await api(`api/conexoes/${p}`, { method: "DELETE", headers: JSON_HDR });
      await aviso("ok", "Conexão removida.");
    }
  } catch (err) { await aviso("bad", `Falha de conexão com o servidor (${err.message}).`); }
  // o seletor de modelos depende de quais conexões estão configuradas
  try { const s = await (await api("api/status")).json(); estado.status = s; montarSeletor(s); } catch { /* mantém o seletor atual */ }
});

function status(cls, texto) {
  const p = $("#pill");
  p.className = "status " + cls;
  p.innerHTML = `<i aria-hidden="true"></i><span>${esc(texto)}</span>`;
}

function mostrarPainel(sim, salvar = true) {
  document.body.classList.toggle("sem-painel", !sim);
  $("#btn-painel").setAttribute("aria-pressed", String(sim));
  if (salvar) pref.set("painel", sim ? "1" : "0");
}

function ajustarAltura() {
  const t = $("#entrada");
  t.style.height = "auto";
  t.style.height = `${Math.min(t.scrollHeight, 160)}px`;
}

function trocarAba(aba) {
  $$(".aba").forEach((b) => { const on = b.dataset.aba === aba; b.classList.toggle("ativa", on); b.setAttribute("aria-selected", on); });
  $("#aba-chat").hidden = aba !== "chat";
  $("#aba-aval").hidden = aba !== "aval";
  $("#btn-painel").hidden = aba !== "chat";
  if (aba === "aval") carregarAvaliacao();
}

// ---------- Conversa ----------
function adicionar(tpl) {
  const n = $(tpl).content.firstElementChild.cloneNode(true);
  $("#boasvindas")?.remove();
  $("#mensagens").appendChild(n);
  rolar(true);
  return n;
}

function rolar(forcar = false) {
  const m = $("#mensagens");
  if (forcar || m.scrollHeight - m.scrollTop - m.clientHeight < 180) m.scrollTop = m.scrollHeight;
}

function novaResposta(pergunta) {
  const a = adicionar("#tpl-msg-assistente");
  const reg = { pergunta, janela: null, final: null, el: a, bruto: "", timer: null, modelo: $("#modelo").value };
  estado.respostas.push(reg);
  a.addEventListener("click", (e) => {
    const c = e.target.closest(".cita");
    const f = e.target.closest(".fonte-cab");
    if (estado.selecionada !== reg) selecionar(reg);
    if (c) destacarFonte(reg, +c.dataset.n);
    else if (f) f.parentElement.classList.toggle("aberto");
  });
  selecionar(reg);
  return reg;
}

async function replay(id) {
  try {
    const r = await api(`api/traco/${encodeURIComponent(id)}`);
    if (!r.ok) return;
    const t = await r.json();
    const u = adicionar("#tpl-msg-usuario"); $(".bolha", u).textContent = t.pergunta;
    const reg = novaResposta(t.pergunta);
    if (t.janela) tratar(reg, { tipo: "contexto", janela: t.janela });
    tratar(reg, t.final);
  } catch { /* traço indisponível */ }
}

async function enviar() {
  const campo = $("#entrada");
  const pergunta = campo.value.trim();
  if (!pergunta || estado.ocupado) return;
  estado.ocupado = true; $("#enviar").disabled = true; campo.value = ""; ajustarAltura();
  const u = adicionar("#tpl-msg-usuario"); $(".bolha", u).textContent = pergunta;
  const reg = novaResposta(pergunta);
  const t0 = performance.now();
  // O harness de entrada é instantâneo: se não houve bloqueio, a espera seguinte é a busca.
  setTimeout(() => { if (!reg.janela && !reg.final) { etapa(reg, "entrada", "feita", "Pergunta verificada"); etapa(reg, "busca", "ativa"); } }, 500);
  reg.timer = setInterval(() => { const t = $(".tempo", reg.el); if (t) t.textContent = `${Math.round((performance.now() - t0) / 1000)} s`; }, 500);
  try {
    const modelo = $("#modelo").value;
    const r = await api("api/perguntar", { method: "POST", headers: { "Content-Type": "application/json", ...cabecalhoChave(modelo) }, body: JSON.stringify({ pergunta, modelo }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
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
    $(".progresso", reg.el)?.remove();
    reg.el.classList.add("erro");
    $(".texto", reg.el).innerHTML = `<p>Falha de conexão com o servidor (${esc(err.message)}).</p>`;
  } finally {
    clearInterval(reg.timer);
    estado.ocupado = false; $("#enviar").disabled = false; campo.focus();
    const m = $(".meta", reg.el);
    if (!m.textContent) m.textContent = `${((performance.now() - t0) / 1000).toFixed(1)} s`;
  }
}

function etapa(reg, nome, classe, rotulo) {
  const li = $(`.etapas li[data-etapa="${nome}"]`, reg.el);
  if (!li) return;
  li.className = classe;
  if (rotulo) $(".rot", li).textContent = rotulo;
}

function tratar(reg, ev) {
  const a = reg.el;
  if (ev.tipo === "contexto") {
    reg.janela = ev.janela;
    const j = ev.janela;
    etapa(reg, "entrada", "feita", j.modo_ressalva ? "Pergunta verificada · modo ressalva ligado" : "Pergunta verificada");
    if (j.cobertura.coberta) {
      etapa(reg, "busca", "feita", `${j.trechos.length} trechos selecionados nos documentos`);
      etapa(reg, "modelo", "ativa", ehRemoto(reg.modelo) ? `Escrevendo a resposta com ${reg.modelo.split(":")[0]} (remoto)` : "Escrevendo a resposta com o modelo local");
    } else {
      etapa(reg, "busca", "feita", "Documentos consultados");
      etapa(reg, "modelo", "pulada", "Modelo não chamado: as fontes não cobrem a pergunta");
    }
    if (estado.selecionada === reg) renderPainel(reg);
  } else if (ev.tipo === "delta") {
    reg.bruto += ev.texto;
    $(".texto", a).innerHTML = markdown(reg.bruto) + '<span class="cursor"></span>';
  } else if (ev.tipo === "final") {
    reg.final = ev;
    clearInterval(reg.timer);
    $(".progresso", a)?.remove();
    a.classList.toggle("recusa", ev.desfecho === "sem_cobertura");
    a.classList.toggle("bloqueada", ev.desfecho === "bloqueada");
    a.classList.toggle("erro", ev.desfecho === "erro" || ev.desfecho === "ocupado");
    $(".texto", a).innerHTML = markdown(ev.resposta) + dica(ev, reg.pergunta);
    renderSelos(reg); renderFontes(reg);
    const o = ev.traco?.ollama, rm = ev.traco?.remoto;
    $(".meta", a).textContent = [
      ev.desfecho === "respondida" ? ev.traco?.modelo : "modelo não chamado",
      o ? `${o.resposta_tokens} tokens · ${o.tok_s} tok/s` : null,
      rm ? `${rm.resposta_tokens ?? "?"} tokens (remoto, não reprodutível)` : null,
      ev.traco?.latencia_s != null ? `${ev.traco.latencia_s} s` : null,
      ev.traco?.id ? `traço ${ev.traco.id}` : null,
    ].filter(Boolean).join(" · ");
    if (estado.selecionada === reg) renderPainel(reg);
  }
  rolar();
}

function dica(ev, pergunta = "") {
  if (ev.desfecho !== "sem_cobertura") return "";
  // Sem acentos, a similaridade cai e pode ficar abaixo do limiar (resultados/grafia.json).
  const semAcento = !/[áàâãéêíóôõúüç]/i.test(pergunta);
  return `<div class="dica"><b>Como reformular</b><ul>
    ${semAcento ? "<li>Escreva com acentos: “lê” e “não” aproximam a pergunta dos documentos mais do que “le” e “nao”.</li>" : ""}
    <li>Diga a série e o que o aluno faz ou não faz (ex.: “aluno do 2º ano troca letras ao escrever”).</li>
    <li>Use os termos da sala de aula: leitura, escrita, sílabas, compreensão.</li></ul></div>`;
}

function renderSelos(reg) {
  const f = reg.final, v = f.verificacao, s = [];
  const d = f.desfecho;
  if (d === "bloqueada") s.push(["bad", "bloqueada antes da busca"]);
  if (d === "sem_cobertura") s.push(["warn", "recusa sem chamar o modelo"]);
  if (d === "erro" || d === "ocupado") s.push(["bad", d === "erro" ? "erro do modelo" : "servidor ocupado"]);
  if (f.traco?.provedor && f.traco.provedor !== "ollama") s.push(["warn", `modelo remoto (${f.traco.provedor})`]);
  if (v) {
    if (v.citacoes_validas.length) s.push(["ok", `${v.citacoes_validas.length} fonte(s) citada(s) e conferida(s)`]);
    if (v.sem_citacao) s.push(["warn", "sem citação"]);
    if (v.citacoes_invalidas.length) s.push(["bad", `citação inexistente removida: ${v.citacoes_invalidas.join(", ")}`]);
    if (v.codigos_ok.length) s.push(["ok", `BNCC conferida: ${v.codigos_ok.join(", ")}`]);
    if (v.codigos_removidos.length) s.push(["bad", `código removido: ${v.codigos_removidos.join(", ")}`]);
    if (v.modo_ressalva) s.push([v.ressalva_forcada ? "warn" : "info", v.ressalva_forcada ? "aviso de diagnóstico inserido pelo sistema" : "limite de diagnóstico declarado"]);
    if (v.truncada) s.push(["warn", "resposta cortada"]);
  }
  $(".selos", reg.el).innerHTML = s.map(([c, t]) => `<span class="selo ${c}">${esc(t)}</span>`).join("");
}

function renderFontes(reg) {
  const j = reg.janela; const sec = $(".fontes", reg.el);
  if (!j || !j.trechos.length || reg.final.desfecho !== "respondida") return;
  const usadas = new Set(reg.final.verificacao?.citacoes_validas || []);
  const item = (t) => `<li data-n="${t.n}"><button type="button" class="fonte-cab"><span class="n">${t.n}</span><span class="doc">${esc(t.rotulo)}</span><span class="pag">${esc(t.pagina)}</span></button>
    <div class="exc">${t.secao ? `<span class="sec">${esc(t.secao)}</span>` : ""}${esc(t.texto.slice(0, 480))}${t.texto.length > 480 ? "…" : ""}</div></li>`;
  const cit = j.trechos.filter((t) => usadas.has(t.n)), nao = j.trechos.filter((t) => !usadas.has(t.n));
  sec.innerHTML = `<h4>Fontes citadas <span>${cit.length} de ${j.trechos.length} trechos da janela · clique para ler</span></h4>`
    + (cit.length ? `<ol>${cit.map(item).join("")}</ol>` : "")
    + (nao.length ? `<details><summary>Trechos que o modelo recebeu e não citou (${nao.length})</summary><ol>${nao.map(item).join("")}</ol></details>` : "");
  sec.hidden = false;
}

function destacarFonte(reg, n) {
  const sec = $(".fontes", reg.el);
  if (!sec.hidden) {
    $$("li", sec).forEach((li) => li.classList.toggle("destaque", +li.dataset.n === n));
    const li = $(`li[data-n="${n}"]`, sec);
    if (li) {
      li.classList.add("aberto");
      const d = li.closest("details"); if (d) d.open = true;
      li.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }
  $$("#painel .trecho").forEach((t) => t.classList.toggle("destaque", +t.dataset.n === n));
  $(`#painel .trecho[data-n="${n}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function selecionar(reg) {
  estado.respostas.forEach((r) => r.el.classList.toggle("selecionada", r === reg));
  estado.selecionada = reg; renderPainel(reg);
}

// ---------- Painel: janela de contexto ----------
const ICONE = { ok: "✓", warn: "!", bad: "✕" };
const chk = (cls, tit, det = "") => `<li class="chk ${cls}"><span class="dot" aria-hidden="true">${ICONE[cls]}</span><div><b>${esc(tit)}</b>${det ? `<small>${esc(det)}</small>` : ""}</div></li>`;

function renderPainel(reg) {
  const p = $("#painel");
  const j = reg.janela, f = reg.final;
  if (!j) {
    p.innerHTML = f
      ? `<div class="bloco"><h3>Harness de entrada</h3><ul class="checks">${chk("bad", "Pergunta bloqueada antes da busca", f.resposta)}</ul><p class="vazio nada-enviado">Nada foi recuperado nem enviado ao modelo.</p></div>`
      : `<div class="vazio-painel"><p>Verificando a pergunta…</p></div>`;
    return;
  }
  const enviado = j.cobertura.coberta;
  const sis = j.sistema.tokens, q = j.pergunta_tokens, t = enviado ? j.usados : 0, tot = Math.max(sis + q + j.orcamento, 1);
  const pct = (x) => `${(100 * x / tot).toFixed(1)}%`;
  const v = f?.verificacao;
  const checks = [
    chk("ok", "Entrada aceita", "sem dado pessoal na pergunta"),
    j.modo_ressalva ? chk("warn", "Pedido de diagnóstico detectado", "modo ressalva ligado") : chk("ok", "Sem pedido de diagnóstico"),
    enviado
      ? chk("ok", "Fontes cobrem a pergunta", `melhor similaridade ${j.cobertura.melhor_cos} ≥ limiar ${j.cobertura.limiar}`)
      : chk("bad", "Fontes não cobrem a pergunta", `melhor similaridade ${j.cobertura.melhor_cos} < limiar ${j.cobertura.limiar}: recusa sem chamar o modelo`),
  ];
  if (v) {
    checks.push(v.citacoes_invalidas.length ? chk("bad", "Citação inexistente removida", `[${v.citacoes_invalidas.join("], [")}] não estava na janela`)
      : v.sem_citacao ? chk("warn", "Resposta sem citação") : chk("ok", "Citações conferidas", `[${v.citacoes_validas.join("], [")}] existem na janela`));
    checks.push(v.codigos_removidos.length ? chk("bad", "Código BNCC removido", `fora das fontes: ${v.codigos_removidos.join(", ")}`)
      : chk("ok", "Códigos BNCC conferidos", v.codigos_ok.join(", ") || "nenhum citado"));
    if (v.modo_ressalva) checks.push(v.ressalva_forcada ? chk("warn", "Aviso de diagnóstico inserido pelo sistema", "o modelo não declarou o limite") : chk("ok", "Limite de diagnóstico declarado", "pelo próprio modelo"));
    if (v.truncada) checks.push(chk("warn", "Resposta cortada", "limite de tokens"));
  }
  const cartao = (c) => `
    <div class="trecho${enviado ? "" : " fora"}" data-n="${c.n}">
      <div class="cab"><span class="tit"><span class="num">${c.n}</span>${esc(c.rotulo)} · ${esc(c.pagina)}</span><span class="pts" title="posição na busca vetorial / lexical e similaridade">D${c.rank_denso ?? "–"} · L${c.rank_bm25 ?? "–"} · cos ${c.cos}</span></div>
      ${c.secao ? `<div class="sec">${esc(c.secao)}</div>` : ""}
      <details><summary>ver trecho (~${c.tokens} tokens)</summary><p>${esc(c.texto)}</p></details>
    </div>`;
  p.innerHTML = `
    <div class="bloco"><h3>Orçamento da janela</h3>
      <div class="barra" title="tokens aproximados"><span class="s"></span><span class="q"></span><span class="t"></span></div>
      <div class="legenda"><span><i class="s"></i>prompt ${esc(j.sistema.versao)} · ~${sis}</span><span><i class="q"></i>pergunta · ~${q}</span><span><i class="t"></i>trechos · ~${t} de ${j.orcamento}</span></div>
    </div>
    <div class="bloco"><h3>Verificações do harness</h3><ul class="checks">${checks.join("")}</ul></div>
    <div class="bloco"><h3>${enviado ? `Entrou na janela · top-${j.top_k}` : "Recuperados, mas não enviados"}</h3>
      ${enviado ? "" : '<p class="aviso-fora">O modelo não foi chamado: estes trechos ficaram abaixo do limiar de similaridade.</p>'}
      <div class="trechos">${j.trechos.length ? j.trechos.map(cartao).join("") : '<p class="vazio">Nenhum trecho.</p>'}</div>
    </div>
    <details class="bloco"><summary>Ficou de fora · ${j.fora_total} candidatos</summary>
      <div class="trechos">${j.fora.slice(0, 6).map((c) => `
        <div class="trecho fora"><div class="cab"><span class="tit">${esc(c.rotulo)} · ${esc(c.pagina)}</span><span class="pts">cos ${c.cos}</span></div><span class="mot">${esc(c.motivo)}</span></div>`).join("")}</div>
    </details>
    <details class="bloco"><summary>Nunca entra na janela</summary><ul class="lista-simples">${j.nao_entra.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details>`;
  // Largura pelo CSSOM: a CSP do servidor aberto na web bloqueia atributo style="" vindo de HTML.
  for (const [cls, x] of [["s", sis], ["q", q], ["t", t]]) $(`.barra .${cls}`, p).style.width = pct(x);
}

// ---------- Aba de avaliação ----------
let avaliacaoCarregada = false;
async function carregarAvaliacao() {
  if (avaliacaoCarregada) return; avaliacaoCarregada = true;
  try {
    const pr = await (await api("api/prompt")).json();
    $("#prompt").textContent = `[${pr.versao}]\n\n${pr.sistema}`;
  } catch { $("#prompt").textContent = "indisponível"; }
  const s = estado.status;
  if (s) $("#config").innerHTML = [
    `LLM: ${s.modelo_padrao}`, `embeddings: ${s.modelo_embed}`, `chunk: ${s.experimento} (${s.chunk.tokens ?? "seção"} tokens, ${Math.round(s.chunk.sobreposicao * 100)}%, top-${s.chunk.top_k})`,
    `corpus ${s.condicao}: ${s.documentos.map((d) => d.id).join(", ")}`, `orçamento: ${s.orcamento_contexto} tokens`, `limiar de cobertura: ${s.limiar_cobertura}`,
  ].map((x) => `<span>${esc(x)}</span>`).join("");
  try {
    const a = await (await api("api/avaliacao")).json();
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
  if (a.geracao) h += `<h3>Geração (rubrica 0–10, juiz: ${esc(a.juiz || "")})</h3>` + tabela(["Modelo", "Corpus", "Juiz", "Média", "≥ 8", "Citação válida", "Código removido", "Latência média (s)"], a.geracao.map((r) => [r.modelo, r.condicao, r.juiz, r.media, r.prop_8, r.cit_ok, r.cod_removidos, r.latencia]));
  if (a.limites) h += `<h3>Casos-limite</h3>` + tabela(["Caso", "Modelo", "Corpus", "Esperado", "Desfecho", "Passou"], a.limites.map((r) => [r.id, r.modelo, r.condicao, r.esperado, r.desfecho, r.passou ? "sim" : "não"]));
  return h;
}

init();
