"use strict";
// Página de admin: lista as contas e aplica uma ação por vez. Sem script nem estilo inline (CSP).
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const JSON_HDR = { "Content-Type": "application/json" };

async function api(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) { location.replace("entrar"); throw new Error("sessão encerrada"); }
  if (r.status === 403) { location.replace("./"); throw new Error("só para admin"); }
  return r;
}
const detalhe = (d, status) => (typeof d.detail === "string" ? d.detail : `Falha (${status}).`);
function aviso(cls, texto) { const r = $("#res"); r.className = "res " + cls; r.textContent = texto; }

const quando = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "nunca");
const SELO = { pendente: "warn", ativa: "ok", desativada: "" };

function botoes(c) {
  const b = (acao, rotulo, perigo = false) => `<button type="button" class="btn-sec${perigo ? " btn-perigo" : ""}" data-acao="${acao}">${rotulo}</button>`;
  if (c.estado === "pendente") return b("aprovar", "Aprovar") + b("recusar", "Recusar", true);
  return [
    c.estado === "ativa" ? b("desativar", "Desativar") : b("reativar", "Reativar"),
    b("redefinir", "Redefinir senha"),
    c.estado === "ativa" ? (c.admin ? b("rebaixar", "Tirar admin") : b("promover", "Tornar admin")) : "",
    b("excluir", "Excluir", true),
  ].join("");
}

function render({ contas, eu }) {
  const pend = contas.filter((c) => c.estado === "pendente").length;
  $("#resumo").textContent = `${contas.length} conta(s)` + (pend ? ` · ${pend} aguardando liberação` : "");
  if (!contas.length) { $("#tabela").innerHTML = '<p class="vazio">Nenhuma conta.</p>'; return; }
  $("#tabela").innerHTML = `<table><thead><tr><th>Usuário</th><th>Estado</th><th>Criada em</th><th>Último acesso</th><th>Ações</th></tr></thead><tbody>${
    contas.map((c) => `<tr data-usuario="${esc(c.usuario)}">
      <td><b>${esc(c.usuario)}</b>${c.usuario === eu ? ' <span class="voce">(você)</span>' : ""}</td>
      <td><span class="selo ${SELO[c.estado] ?? ""}">${esc(c.estado)}</span>${c.admin ? ' <span class="selo info">admin</span>' : ""}</td>
      <td>${esc(quando(c.criada_em))}</td><td>${esc(quando(c.ultimo_acesso))}</td>
      <td><div class="acoes">${botoes(c)}</div></td></tr>`).join("")
  }</tbody></table>`;
}

async function carregar() {
  try {
    const r = await api("api/ademir/contas");
    const d = await r.json().catch(() => ({}));
    if (!r.ok) return aviso("bad", detalhe(d, r.status));
    render(d);
  } catch (err) { aviso("bad", `Falha de conexão com o servidor (${err.message}).`); }
}

function confirmar(titulo, texto, rotulo) {
  const d = $("#dlg-confirmar");
  $("#conf-titulo").textContent = titulo; $("#conf-texto").textContent = texto; $("#conf-ok").textContent = rotulo;
  d.returnValue = "";
  d.showModal();
  return new Promise((ok) => d.addEventListener("close", () => ok(d.returnValue === "ok"), { once: true }));
}

const CONFIRMA = {
  excluir: (u) => ["Excluir conta?", `A conta ${u} será apagada, com as sessões abertas. Não dá para desfazer.`, "Excluir"],
  recusar: (u) => ["Recusar cadastro?", `O cadastro pendente de ${u} será apagado.`, "Recusar"],
};
const FEITO = { aprovar: "aprovada", recusar: "recusada", desativar: "desativada", reativar: "reativada", promover: "agora é admin",
  rebaixar: "deixou de ser admin", excluir: "excluída", redefinir: "com senha provisória" };

$("#tabela").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-acao]");
  if (!b) return;
  const usuario = b.closest("tr").dataset.usuario, acao = b.dataset.acao;
  if (CONFIRMA[acao] && !(await confirmar(...CONFIRMA[acao](usuario)))) return;
  b.disabled = true;
  try {
    const r = await api("api/ademir/acao", { method: "POST", headers: JSON_HDR, body: JSON.stringify({ usuario, acao }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { aviso("bad", detalhe(d, r.status)); b.disabled = false; return; }
    render(d);
    aviso("ok", `${usuario}: ${FEITO[acao]}.`);
    if (d.senha_provisoria) mostrarProvisoria(usuario, d.senha_provisoria);
  } catch (err) { aviso("bad", `Falha de conexão com o servidor (${err.message}).`); b.disabled = false; }
});

function mostrarProvisoria(usuario, senha) {
  $("#prov-usuario").textContent = usuario;
  $("#prov-senha").textContent = senha;
  $("#prov-res").textContent = "";
  $("#dlg-provisoria").showModal();
}
$("#dlg-provisoria").addEventListener("close", () => { $("#prov-senha").textContent = ""; });  // não fica no DOM
$("#prov-copiar").addEventListener("click", async () => {
  const r = $("#prov-res");
  try { await navigator.clipboard.writeText($("#prov-senha").textContent); r.className = "res ok"; r.textContent = "Copiada."; }
  catch { r.className = "res bad"; r.textContent = "O navegador não deixou copiar: selecione e copie à mão."; }
});

carregar();
