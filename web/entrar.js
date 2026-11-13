"use strict";
// Página de acesso: entrar e criar conta. Sem script inline: a CSP do servidor bloqueia.
const $ = (s) => document.querySelector(s);
const JSON_HDR = { "Content-Type": "application/json" };

async function postar(url, corpo) {
  const r = await fetch(url, { method: "POST", headers: JSON_HDR, body: JSON.stringify(corpo) });
  return { r, dados: await r.json().catch(() => ({})) };
}
const detalhe = (d, status) => (typeof d.detail === "string" ? d.detail : status === 422 ? "Confira os campos." : `Falha (${status}).`);
function aviso(el, cls, texto) { el.className = "res " + cls; el.textContent = texto; }

function modo(m) {
  for (const b of document.querySelectorAll(".aba")) {
    const on = b.dataset.modo === m;
    b.classList.toggle("ativa", on); b.setAttribute("aria-selected", String(on));
  }
  $("#form-entrar").hidden = m !== "entrar";
  $("#form-criar").hidden = m !== "criar";
  (m === "entrar" ? $("#e-usuario") : $("#c-usuario")).focus();
}
document.querySelectorAll(".aba").forEach((b) => b.addEventListener("click", () => modo(b.dataset.modo)));

$("#form-entrar").addEventListener("submit", async (e) => {
  e.preventDefault();
  const res = $("#e-res"), botao = $("#form-entrar button[type=submit]");
  botao.disabled = true; aviso(res, "", "Entrando…");
  try {
    const { r, dados } = await postar("api/entrar", { usuario: $("#e-usuario").value, senha: $("#e-senha").value });
    if (r.ok) { location.replace("./"); return; }
    $("#e-senha").value = "";
    aviso(res, "bad", detalhe(dados, r.status));
  } catch { aviso(res, "bad", "Sem conexão com o servidor."); }
  finally { botao.disabled = false; }
});

$("#form-criar").addEventListener("submit", async (e) => {
  e.preventDefault();
  const res = $("#c-res"), botao = $("#form-criar button[type=submit]");
  const senha = $("#c-senha").value, confirmacao = $("#c-conf").value;
  if (senha !== confirmacao) { aviso(res, "bad", "As senhas não conferem."); return; }
  botao.disabled = true; aviso(res, "", "Enviando…");
  try {
    const { r, dados } = await postar("api/cadastrar", { usuario: $("#c-usuario").value, senha, confirmacao });
    if (r.status === 201) {
      $("#form-criar").reset(); aviso(res, "", "");
      modo("entrar");
      $("#e-usuario").value = dados.usuario || "";
      aviso($("#e-res"), "ok", "Cadastro recebido: avise o admin para liberar o acesso.");
      return;
    }
    aviso(res, "bad", detalhe(dados, r.status));
  } catch { aviso(res, "bad", "Sem conexão com o servidor."); }
  finally { botao.disabled = false; }
});

$("#e-usuario").focus();
