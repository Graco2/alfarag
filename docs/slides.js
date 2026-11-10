// Gera a apresentação do Exame (10 min) a partir de docs/slides_data.json.
// Uso: NODE_PATH=<node_modules> node docs/slides.js <saida.pptx> <apply_theme.js>
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa6");

const DIR = __dirname;
const D = JSON.parse(fs.readFileSync(path.join(DIR, "slides_data.json"), "utf8"));
const SAIDA = process.argv[2];
const { applyTheme } = require(process.argv[3]);

const THEME = {
  name: "AlfaRAG Brasa",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1A1310", lt1: "FFFFFF", dk2: "58514A", lt2: "FFF6EA",
    accent1: "E86600", accent2: "A2370F", accent3: "007B53", accent4: "B3261E", accent5: "2C4AA8", accent6: "B08400",
    hlink: "A2370F", folHlink: "7F2B10",
  },
};
const HEX = { tinta: "1A1310", cinza: "58514A", cinza2: "716B63", borda: "EBE6E2", laranja: "E86600", laranjaSoft: "FFEBD4",
  verde: "007B53", verdeSoft: "DDF5EA", vermelho: "B3261E", vermelhoSoft: "FDE2DF", azul: "2C4AA8", azulSoft: "EAF0FF", creme: "FFF6EA" };

const br = (x, c = 2) => (x == null ? "–" : Number(x).toFixed(c).replace(".", ","));

async function icone(nome, cor) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(fa[nome], { color: "#" + cor, size: 256 }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9"; // 10 x 5.625 in
  pres.title = "AlfaRAG — Exame TE-251";
  pres.author = "Grupo Imeanos no ITA";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;

  pres.defineSlideMaster({
    title: "ESCURO",
    background: { color: HEX.tinta },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 1.05, w: 6.6, h: 1.5, fontSize: 36, bold: true, color: "FFFFFF", fontFace: "Cambria", valign: "bottom", align: "left", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: 0.6, y: 2.65, w: 6.6, h: 1.1, fontSize: 18, color: "F2D9C2", valign: "top", align: "left", margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "CONTEUDO",
    background: { color: "FFFFFF" },
    margin: [0.5, 0.5, 0.5, 0.5],
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.28, w: 9.0, h: 0.7, fontSize: 28, bold: true, color: HEX.tinta, fontFace: "Cambria", valign: "middle", margin: 0 }, text: "" } },
      { text: { text: "AlfaRAG · TE-251 · Grupo Imeanos no ITA", options: { x: 0.5, y: 5.2, w: 6, h: 0.3, fontSize: 9, color: HEX.cinza2, margin: 0 } } },
    ],
    slideNumber: { x: 9.1, y: 5.2, w: 0.4, h: 0.3, fontSize: 9, color: HEX.cinza2, align: "right" },
  });

  const ICON = {};
  for (const [k, n, c] of [
    ["prompt", "FaPenNib", HEX.laranja], ["contexto", "FaWindowMaximize", HEX.azul], ["rag", "FaBookOpen", HEX.laranja],
    ["aval", "FaScaleBalanced", HEX.verde], ["harness", "FaShieldHalved", HEX.vermelho], ["agents", "FaFileLines", HEX.cinza],
    ["ok", "FaCircleCheck", HEX.verde], ["stop", "FaBan", HEX.vermelho], ["warn", "FaTriangleExclamation", "B08400"],
    ["user", "FaChalkboardUser", HEX.laranja], ["cpu", "FaMicrochip", HEX.cinza], ["lock", "FaLock", HEX.vermelho],
    ["robo", "FaRobot", HEX.azul], ["gear", "FaGears", HEX.vermelho], ["log", "FaReceipt", HEX.verde], ["book", "FaBook", "FFFFFF"],
  ]) ICON[k] = await icone(n, c);

  const card = (s, x, y, w, h, fill, nome) => s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: HEX.borda, width: 0.75 }, objectName: nome });
  const txt = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, fontSize: 14, color: HEX.tinta, valign: "top", ...o });

  // 1. Título --------------------------------------------------------------
  pres.addSection({ title: "Abertura" });
  let s = pres.addSlide({ masterName: "ESCURO", sectionTitle: "Abertura" });
  s.addText("AlfaRAG", { placeholder: "title" });
  s.addText("Assistente RAG local, com citação verificável, para apoio à alfabetização no 2º e 3º anos", { placeholder: "body" });
  txt(s, "Neuton Severo · Beatriz Luberiaga · Murilo Narciso · Priscila · Ricardo Graco de Souza Lima Castellano", { x: 0.6, y: 3.95, w: 6.4, h: 0.5, fontSize: 13, color: "FFFFFF" });
  txt(s, "Grupo Imeanos no ITA · TE-251 · ITA 2026/2 · github.com/Graco2/alfarag", { x: 0.6, y: 4.5, w: 6.4, h: 0.35, fontSize: 12, color: "D9C7B8" });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 7.35, y: 1.35, w: 2.1, h: 2.1, rectRadius: 0.35, fill: { color: HEX.laranja }, line: { type: "none" }, objectName: "logo" });
  txt(s, "Aa", { x: 7.35, y: 1.35, w: 2.1, h: 2.1, fontSize: 64, bold: true, color: "FFFFFF", align: "center", valign: "middle", fontFace: "Cambria" });
  txt(s, "Ollama local · Qwen3.5 4B", { x: 7.0, y: 3.6, w: 2.8, h: 0.35, fontSize: 12, color: "D9C7B8", align: "center" });
  s.addNotes("Abertura (20 s). Somos o grupo Imeanos no ITA. Construímos e executamos o AlfaRAG: um assistente para professoras de alfabetização que responde só com base em documentos oficiais e científicos, cita página e não faz diagnóstico.");

  // 2. Problema ------------------------------------------------------------
  pres.addSection({ title: "Problema" });
  s = pres.addSlide({ masterName: "CONTEUDO", sectionTitle: "Problema" });
  s.addText("O problema: o aluno que não acompanha", { placeholder: "title" });
  const stats = [["7 de 7", "professoras têm alunos com dificuldade persistente sem avaliação concluída"],
    ["7 de 7", "apontam dificuldade de compreender o que se lê"], ["2 de 7", "não dispõem de apoio regular"]];
  stats.forEach(([n, l], i) => {
    const y = 1.2 + i * 1.22;
    txt(s, n, { x: 0.5, y, w: 1.75, h: 0.75, fontSize: 36, bold: true, color: HEX.laranja, fontFace: "Cambria", valign: "middle" });
    txt(s, l, { x: 2.3, y: y + 0.05, w: 2.6, h: 0.75, fontSize: 14, color: HEX.tinta, valign: "middle" });
  });
  txt(s, "Consulta exploratória do grupo (n = 7)", { x: 0.5, y: 4.85, w: 4.4, h: 0.3, fontSize: 10, color: HEX.cinza2, italic: true });
  card(s, 5.25, 1.15, 4.25, 1.75, HEX.creme, "por_que");
  s.addImage({ data: ICON.robo, x: 5.45, y: 1.32, w: 0.34, h: 0.34 });
  txt(s, "Por que um modelo", { x: 5.9, y: 1.3, w: 3.4, h: 0.4, fontSize: 16, bold: true });
  txt(s, [
    { text: "Lê a pergunta em linguagem livre", options: { bullet: true, breakLine: true } },
    { text: "Acha o trecho em centenas de páginas (BNCC, Manual ABC, artigos)", options: { bullet: true, breakLine: true } },
    { text: "Redige uma orientação aplicável", options: { bullet: true } },
  ], { x: 5.45, y: 1.75, w: 3.9, h: 1.1, fontSize: 13, paraSpaceAfter: 3 });
  card(s, 5.25, 3.1, 4.25, 1.75, HEX.vermelhoSoft, "risco");
  s.addImage({ data: ICON.warn, x: 5.45, y: 3.27, w: 0.34, h: 0.34 });
  txt(s, "Por que só o modelo não basta", { x: 5.9, y: 3.25, w: 3.5, h: 0.4, fontSize: 16, bold: true });
  txt(s, [
    { text: "Inventa código da BNCC e referências", options: { bullet: true, breakLine: true } },
    { text: "Cita fonte que não diz aquilo", options: { bullet: true, breakLine: true } },
    { text: "Arrisca “diagnóstico” de dislexia ou TDAH", options: { bullet: true } },
  ], { x: 5.45, y: 3.7, w: 3.9, h: 1.1, fontSize: 13, paraSpaceAfter: 3 });
  s.addNotes("Problema (1 min). Na consulta com sete professoras, todas têm alunos com dificuldade persistente sem avaliação concluída. Elas pedem: o que faço amanhã em sala? A resposta existe, mas está espalhada na BNCC, num manual de mais de 500 páginas e em artigos em inglês. O modelo entra para ler a pergunta e achar o trecho; mas, sozinho, inventa código da BNCC e arrisca diagnóstico. Por isso o sistema não confia só no modelo.");

  // 3. Arquitetura ---------------------------------------------------------
  pres.addSection({ title: "Sistema" });
  s = pres.addSlide({ masterName: "CONTEUDO", sectionTitle: "Sistema" });
  s.addText("O modelo no meio, regras verificáveis em volta", { placeholder: "title" });
  s.addImage({ path: path.join(DIR, "fig1_arquitetura.png"), x: 0.5, y: 1.05, w: 3.75, h: 4.27, altText: "Fluxo do AlfaRAG: pergunta, harness de entrada, recuperação híbrida, cobertura, janela, LLM, harness de saída, resposta" });
  const linhas3 = [
    [ICON.lock, "Antes do modelo", `Bloqueia CPF, telefone e e-mail. Pedido de diagnóstico liga o modo ressalva. Cosseno abaixo de ${br(D.limiar)}: recusa sem chamar o modelo.`],
    [ICON.cpu, "O modelo", `${D.modelo} no Ollama, local, sem internet. Recebe prompt ${D.versao_prompt} + 5 trechos numerados.`],
    [ICON.gear, "Depois do modelo", "Citação [n] tem de existir. Código BNCC tem de estar no trecho. Sem a ressalva, o sistema insere o aviso."],
    [ICON.log, "Traço", "Cada resposta grava pergunta, trechos, versões, digest do modelo e verificações (JSONL)."],
  ];
  linhas3.forEach(([ic, t, d], i) => {
    const y = 1.12 + i * 1.02;
    s.addShape(pres.shapes.OVAL, { x: 4.6, y: y + 0.05, w: 0.5, h: 0.5, fill: { color: HEX.creme }, line: { type: "none" }, objectName: "ic_" + i });
    s.addImage({ data: ic, x: 4.71, y: y + 0.16, w: 0.28, h: 0.28 });
    txt(s, t, { x: 5.3, y, w: 4.2, h: 0.32, fontSize: 15, bold: true });
    txt(s, d, { x: 5.3, y: y + 0.33, w: 4.2, h: 0.62, fontSize: 12, color: HEX.cinza });
  });
  s.addNotes("Arquitetura (1 min). Em vermelho, o que é determinístico. Antes do modelo: bloqueio de dado pessoal, modo ressalva para pedido de diagnóstico e recusa sem chamar o modelo quando nada no corpus se parece com a pergunta. O modelo, um Qwen de 4 bilhões rodando local no Ollama, só vê o prompt e cinco trechos numerados. Depois, o sistema confere citações e códigos BNCC e grava um traço de cada resposta.");

  // 4. Técnicas ------------------------------------------------------------
  s = pres.addSlide({ masterName: "CONTEUDO", sectionTitle: "Sistema" });
  s.addText("Técnicas da disciplina, onde aparecem no sistema", { placeholder: "title" });
  const tec = [
    [ICON.prompt, "Prompt Engineering", `Prompt de sistema versionado (${D.versao_prompt}): 4 partes e 6 regras — app/prompts.py`],
    [ICON.contexto, "Context Engineering", `Top-5 trechos dentro de ${D.orcamento} tokens; histórico fora; o painel mostra o que ficou de fora`],
    [ICON.rag, "RAG com citação", "BM25 + embeddings bge-m3, fusão RRF; cada trecho com documento e página impressa"],
    [ICON.aval, "RAG com avaliação", "Recall@5 e MRR nas 24 perguntas; outro modelo julga com rubrica 0–10; traço JSONL"],
    [ICON.harness, "Harness", "Regras antes e depois do modelo: bloqueio, recusa, remoção de citação e código, aviso forçado"],
    [ICON.agents, "AGENTS.md + Agent Skill", "Regras para agentes de código e SKILL.md com o procedimento de avaliação"],
  ];
  tec.forEach(([ic, t, d], i) => {
    const x = 0.5 + (i % 3) * 3.05, y = 1.15 + Math.floor(i / 3) * 2.0;
    card(s, x, y, 2.85, 1.8, i % 2 ? "FFFFFF" : HEX.creme, "tec_" + i);
    s.addImage({ data: ic, x: x + 0.2, y: y + 0.2, w: 0.38, h: 0.38 });
    txt(s, t, { x: x + 0.7, y: y + 0.18, w: 2.05, h: 0.45, fontSize: 15, bold: true, valign: "middle" });
    txt(s, d, { x: x + 0.2, y: y + 0.75, w: 2.5, h: 0.95, fontSize: 12, color: HEX.cinza });
  });
  s.addNotes("Técnicas (1 min). Seis técnicas da disciplina, cada uma num arquivo: prompt versionado, engenharia de contexto com orçamento de tokens, RAG com citação por página, avaliação com métricas e juiz, harness determinístico e AGENTS.md mais uma Skill de avaliação.");

  // 5. Janela de contexto --------------------------------------------------
  s = pres.addSlide({ masterName: "CONTEUDO", sectionTitle: "Sistema" });
  s.addText("Janela de contexto: o que entra e o que fica de fora", { placeholder: "title" });
  const painel = path.join(DIR, "screens", "painel.png");
  const temPainel = fs.existsSync(painel);
  card(s, 0.5, 1.15, 4.3, 1.85, HEX.verdeSoft, "entra");
  s.addImage({ data: ICON.ok, x: 0.7, y: 1.3, w: 0.32, h: 0.32 });
  txt(s, "Entra", { x: 1.12, y: 1.28, w: 3, h: 0.36, fontSize: 16, bold: true, color: HEX.verde });
  txt(s, [
    { text: `Prompt de sistema ${D.versao_prompt}`, options: { bullet: true, breakLine: true } },
    { text: "A pergunta, sem dados do aluno", options: { bullet: true, breakLine: true } },
    { text: `5 trechos numerados [1]–[5], até ${D.orcamento} tokens`, options: { bullet: true } },
  ], { x: 0.7, y: 1.72, w: 4.0, h: 1.2, fontSize: 13, paraSpaceAfter: 3 });
  card(s, 0.5, 3.2, 4.3, 1.85, HEX.vermelhoSoft, "fora");
  s.addImage({ data: ICON.stop, x: 0.7, y: 3.35, w: 0.32, h: 0.32 });
  txt(s, "Fica de fora", { x: 1.12, y: 3.33, w: 3, h: 0.36, fontSize: 16, bold: true, color: HEX.vermelho });
  txt(s, [
    { text: "Candidatos abaixo do top-5 (com o motivo)", options: { bullet: true, breakLine: true } },
    { text: "Histórico da conversa e o resto dos PDFs", options: { bullet: true, breakLine: true } },
    { text: "Documentos fora da condição de corpus", options: { bullet: true } },
  ], { x: 0.7, y: 3.77, w: 4.0, h: 1.2, fontSize: 13, paraSpaceAfter: 3 });
  if (temPainel) {
    const m = await sharp(painel).metadata();
    const h = 4.0, w = Math.min(4.4, h * m.width / m.height);
    s.addImage({ path: painel, x: 5.1 + (4.4 - w) / 2, y: 1.12, w, h, altText: "Painel da janela de contexto no app" });
  }
  s.addNotes("Contexto (1 min). A cada pergunta, o modelo recebe só o prompt, a pergunta e cinco trechos numerados que cabem no orçamento. O painel à direita, no próprio app, mostra o orçamento, as verificações e os candidatos que ficaram de fora com o motivo. O histórico não entra: cada pergunta é independente.");

  // 6. Caso que responde ---------------------------------------------------
  pres.addSection({ title: "Execução" });
  s = pres.addSlide({ masterName: "CONTEUDO", sectionTitle: "Execução" });
  s.addText("Execução: um caso que responde", { placeholder: "title" });
  const resp = path.join(DIR, "screens", "resposta_chat.png");
  if (fs.existsSync(resp)) {
    const m = await sharp(resp).metadata();
    const w = 5.0, h = Math.min(4.05, w * m.height / m.width);
    s.addImage({ path: resp, x: 0.5, y: 1.1, w, h, altText: "Resposta do AlfaRAG à pergunta B03 com citações" });
  }
  const v = D.b03.verificacao;
  card(s, 5.75, 1.1, 3.75, 4.05, HEX.creme, "b03");
  txt(s, "B03 · “lê pato, mas não lê prato”", { x: 5.95, y: 1.25, w: 3.4, h: 0.4, fontSize: 15, bold: true });
  const usados = D.b03.trechos.filter((t) => v.citacoes_validas.includes(t.n));
  txt(s, [
    { text: `${v.citacoes_validas.length} citações conferidas pelo harness`, options: { bullet: true, breakLine: true } },
    { text: `${v.codigos_removidos.length} código(s) BNCC removido(s)`, options: { bullet: true, breakLine: true } },
    { text: `${D.b03.tokens.prompt_tokens} tokens de entrada, ${D.b03.tokens.resposta_tokens} de saída`, options: { bullet: true, breakLine: true } },
    { text: `${br(D.b03.latencia, 0)} s no M4 · traço ${D.b03.traco || "-"}`, options: { bullet: true } },
  ], { x: 5.95, y: 1.7, w: 3.4, h: 1.35, fontSize: 13, paraSpaceAfter: 3 });
  txt(s, "Fontes citadas", { x: 5.95, y: 3.1, w: 3.4, h: 0.32, fontSize: 13, bold: true, color: HEX.laranja });
  txt(s, usados.slice(0, 4).map((t, i, a) => ({ text: `[${t.n}] ${t.rotulo}, ${t.pagina}`, options: { breakLine: i < a.length - 1 } })),
    { x: 5.95, y: 3.45, w: 3.4, h: 1.5, fontSize: 12, color: HEX.cinza, paraSpaceAfter: 2 });
  s.addNotes("Caso que responde (1 min 30). Pergunta real do benchmark: o aluno lê pato mas não lê prato. A resposta vem em quatro partes, cada afirmação com [n]; clicando no número, o app mostra o trecho e a página. O harness conferiu as citações e não precisou remover nada. Se a rede falhar na demo, seguimos com esta captura.");

  // 7. Casos que não fecham ------------------------------------------------
  s = pres.addSlide({ masterName: "CONTEUDO", sectionTitle: "Execução" });
  s.addText("Casos que não fecham — e quem decidiu", { placeholder: "title" });
  const L = D.limites;
  const cos = (id) => (L[id] && L[id].cos != null ? br(L[id].cos, 3) : "–");
  const l01 = L.L01 || {}, l02 = L.L02 || {}, l05 = L.L05 || {};
  const rem05 = (l05.verificacao && l05.verificacao.codigos_removidos) || [];
  const casos = [
    [ICON.stop, "Receita de bolo (L03)", `Cosseno ${cos("L03")} < ${br(D.limiar)}: recusa sem chamar o modelo.`, "Sistema"],
    [ICON.lock, "Pergunta com CPF (L04)", `${L.L04 && L.L04.desfecho === "bloqueada" ? "Bloqueada na entrada; nada é recuperado nem enviado." : "Desfecho: " + (L.L04 || {}).desfecho}`, "Sistema"],
    [ICON.harness, "“Ele tem dislexia, sim ou não?” (L01)", `Modo ressalva ligado; ${l01.verificacao && l01.verificacao.ressalva_forcada ? "o modelo não declarou o limite e o sistema inseriu o aviso." : "o modelo declarou que não diagnostica."}`, l01.verificacao && l01.verificacao.ressalva_forcada ? "Sistema" : "Modelo + sistema"],
    [ICON.warn, "Frações no 5º ano (L02)", l02.desfecho === "sem_cobertura" ? `Cosseno ${cos("L02")}: recusada.` : `Cosseno ${cos("L02")}, acima do limiar: chega ao modelo.${(l02.resposta || "").includes("evidência suficiente") ? " Admite que não há evidência, mas anexa [1]–[5], e o harness aceita." : " A recusa depende do prompt."}`, l02.desfecho === "sem_cobertura" ? "Sistema" : "Modelo"],
  ];
  casos.forEach(([ic, t, d, quem], i) => {
    const x = 0.5 + (i % 2) * 4.6, y = 1.15 + Math.floor(i / 2) * 1.95;
    card(s, x, y, 4.4, 1.75, i === 3 ? "FFF2CC" : (i % 3 ? "FFFFFF" : HEX.creme), "caso_" + i);
    s.addImage({ data: ic, x: x + 0.2, y: y + 0.22, w: 0.34, h: 0.34 });
    txt(s, t, { x: x + 0.7, y: y + 0.18, w: 3.55, h: 0.45, fontSize: 14, bold: true, valign: "middle" });
    txt(s, d, { x: x + 0.2, y: y + 0.72, w: 4.0, h: 0.68, fontSize: 12, color: HEX.cinza });
    txt(s, "Quem decidiu: " + quem, { x: x + 0.2, y: y + 1.42, w: 4.0, h: 0.28, fontSize: 11, bold: true, color: quem === "Modelo" ? "8A5A00" : HEX.verde });
  });
  s.addNotes(`Casos que não fecham (1 min 30). Receita de bolo: o sistema recusa sem gastar o modelo. CPF: bloqueado na entrada. Pedido de diagnóstico: modo ressalva. E o caso honesto: frações no 5º ano tem similaridade ${cos("L02")}, acima do limiar, porque o corpus fala de ensino; aí quem segura é o prompt, não o sistema. ${rem05.length ? "No pedido de código BNCC para inglês, o modelo inventou " + rem05.join(", ") + " e o sistema removeu." : ""}`);

  // 8. Resultados ----------------------------------------------------------
  pres.addSection({ title: "Resultados" });
  s = pres.addSlide({ masterName: "CONTEUDO", sectionTitle: "Resultados" });
  s.addText("Resultados nas 24 perguntas do grupo", { placeholder: "title" });
  const R = D.recuperacao;
  s.addChart(pres.charts.BAR, [
    { name: "Recall@5", labels: ["C1 BNCC", "C2 +Ramli", "C3 +Hall", "C4 completo"], values: ["C1", "C2", "C3", "C4"].map((c) => R["E2_" + c].recall) },
    { name: "MRR@10", labels: ["C1 BNCC", "C2 +Ramli", "C3 +Hall", "C4 completo"], values: ["C1", "C2", "C3", "C4"].map((c) => R["E2_" + c].mrr) },
  ], {
    x: 0.5, y: 1.1, w: 4.5, h: 3.9, barDir: "col", barGrouping: "clustered", chartColors: [HEX.laranja, "D9B48F"],
    showTitle: true, title: "Recuperação (chunks de 512 tokens)", titleFontSize: 13, titleColor: HEX.tinta, titleFontFace: "+mn-lt",
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 10, dataLabelFormatCode: "0.00", dataLabelColor: HEX.cinza, dataLabelFontFace: "+mn-lt",
    valAxisMinVal: 0, valAxisMaxVal: 1, valAxisLabelColor: HEX.cinza2, catAxisLabelColor: HEX.cinza, valAxisLabelFontSize: 10, catAxisLabelFontSize: 10,
    catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
    valGridLine: { color: HEX.borda, size: 0.5 }, catGridLine: { style: "none" }, showLegend: true, legendPos: "b", legendFontSize: 10, legendFontFace: "+mn-lt",
  });
  const q = D.qwen_c4, g = D.gemma_c4, q1 = D.qwen_c1;
  const jm = (e, k) => (e[k] ? br(e[k].media) : "–");
  const j8 = (e, k) => (e[k] ? `${e[k].ge8}/${e[k].n}` : "–");
  const cab = { bold: true, color: "FFFFFF", fill: { color: HEX.tinta }, fontSize: 11, align: "center" };
  const cel = (t, o = {}) => ({ text: String(t), options: { fontSize: 11, color: HEX.tinta, align: "center", ...o } });
  s.addTable([
    [{ text: "Geração", options: { ...cab, align: "left" } }, { text: "Qwen C4", options: cab }, { text: "Gemma C4", options: cab }, { text: "Qwen C1", options: cab }],
    [cel("Nota média (juiz Gemma)", { align: "left" }), cel(jm(q, "juiz_gemma")), cel(jm(g, "juiz_gemma")), cel(jm(q1, "juiz_gemma"))],
    [cel("Nota média (juiz Qwen)", { align: "left" }), cel(jm(q, "juiz_qwen")), cel(jm(g, "juiz_qwen")), cel(jm(q1, "juiz_qwen"))],
    [cel("Nota ≥ 8 (juiz Gemma)", { align: "left" }), cel(j8(q, "juiz_gemma")), cel(j8(g, "juiz_gemma")), cel(j8(q1, "juiz_gemma"))],
    [cel("Respondidas (resto: recusa)", { align: "left" }), cel(`${q.respondidas}/${q.n}`), cel(`${g.respondidas}/${g.n}`), cel(`${q1.respondidas}/${q1.n}`)],
    [cel("Com citação válida", { align: "left" }), cel(`${q.cit_ok}/${q.respondidas}`), cel(`${g.cit_ok}/${g.respondidas}`), cel(`${q1.cit_ok}/${q1.respondidas}`)],
    [cel("Códigos BNCC removidos", { align: "left" }), cel(q.cod_rem), cel(g.cod_rem), cel(q1.cod_rem)],
    [cel("Latência média (s, M4)", { align: "left" }), cel(br(q.lat, 1)), cel(br(g.lat, 1)), cel(br(q1.lat, 1))],
  ], { x: 5.25, y: 1.15, w: 4.25, colW: [1.9, 0.78, 0.79, 0.78], rowH: 0.38, border: { type: "solid", pt: 0.5, color: HEX.borda }, fill: { color: "FFFFFF" }, fontFace: "Calibri" });
  txt(s, "Nota de 0 a 10 dada por outro modelo (rubrica do projeto). Indicador descritivo, não prova de eficácia pedagógica."
    + (D.cpu ? ` Só em CPU (sem GPU): ${br(D.cpu.latencia_media_s / 60, 1)} min por resposta (n = ${D.cpu.n}).` : ""),
    { x: 5.25, y: 4.45, w: 4.25, h: 0.65, fontSize: 10, italic: true, color: HEX.cinza2 });
  s.addNotes(`Resultados (1 min 30). Recuperação: com só a BNCC, Recall@5 de ${br(R.E2_C1.recall)}; com o corpus completo, ${br(R.E2_C4.recall)}. Os artigos em inglês sozinhos não ajudam a achar o trecho da BNCC. Na geração, a nota é dada por outro modelo com a rubrica do projeto; usamos dois juízes cruzados para nenhum modelo se julgar sozinho. Não são medidas clínicas.`);

  // 9. Modelo decide x sistema força --------------------------------------
  s = pres.addSlide({ masterName: "CONTEUDO", sectionTitle: "Resultados" });
  s.addText("O que o modelo decide e o que o sistema força", { placeholder: "title" });
  const col = (x, titulo, ic, cor, fill, itens) => {
    card(s, x, 1.15, 4.4, 3.3, fill, "col_" + titulo);
    s.addImage({ data: ic, x: x + 0.25, y: 1.35, w: 0.38, h: 0.38 });
    txt(s, titulo, { x: x + 0.8, y: 1.33, w: 3.4, h: 0.42, fontSize: 18, bold: true, color: cor, valign: "middle" });
    txt(s, itens.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < itens.length - 1 } })), { x: x + 0.3, y: 1.95, w: 3.9, h: 2.9, fontSize: 14, paraSpaceAfter: 6 });
  };
  col(0.5, "O modelo decide", ICON.robo, HEX.azul, HEX.azulSoft, ["O texto e a ênfase da resposta", "Quais trechos citar", "Qual atividade sugerir", "Como formular a ressalva", "Se admite falta de evidência (acima do limiar)"]);
  col(5.1, "O sistema força", ICON.harness, HEX.vermelho, HEX.vermelhoSoft, ["Só trechos do corpus entram na janela", "Citação [n] inexistente é removida", "Código BNCC fora das fontes é removido", "Aviso de não diagnóstico, se faltar", "Recusa sem modelo abaixo do limiar; CPF bloqueado"]);
  s.addNotes("Divisão de responsabilidade (1 min). À esquerda, o que depende do modelo; à direita, o que o código garante, independentemente do modelo. Tudo o que está à direita aparece no traço e pode ser auditado.");

  // 10. Limites ------------------------------------------------------------
  pres.addSection({ title: "Limites" });
  s = pres.addSlide({ masterName: "CONTEUDO", sectionTitle: "Limites" });
  s.addText("O limite que o Artigo escreve em AI Assurance", { placeholder: "title" });
  const lims = [
    ["Não faz", "Não diagnostica, não avalia aluno, não cobre outras disciplinas, não usa web nem memória."],
    ["Pessoa no fluxo", "O professor decide com as fontes à vista; não há aprovação humana antes da resposta. Revisão das respostas de referência: pendente."],
    ["De onde vem", `Só dos 5 trechos na janela. O limiar ${br(D.limiar)} é grosseiro: “frações” passa e a recusa fica com o prompt.`],
    ["O que quebra", "Citação válida com afirmação errada não é detectada. Paráfrase de pedido de diagnóstico escapa da regra. A mesma tag do Ollama mudou de artefato entre macOS e Linux: fixamos a quantização e gravamos o digest."],
  ];
  lims.forEach(([t, d], i) => {
    const y = 1.12 + i * 1.0;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.5, y, w: 2.0, h: 0.85, rectRadius: 0.08, fill: { color: i === 3 ? HEX.vermelho : HEX.tinta }, line: { type: "none" }, objectName: "lim_" + i });
    txt(s, t, { x: 0.5, y, w: 2.0, h: 0.85, fontSize: 15, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
    txt(s, d, { x: 2.75, y: y + 0.02, w: 6.75, h: 0.85, fontSize: 13, color: HEX.tinta, valign: "middle" });
  });
  s.addNotes("Limites (1 min). O que o sistema não faz; onde a pessoa entra; de onde vem cada afirmação e o que acontece quando a fonte não cobre; e o que quebra se o modelo errar. O ponto mais importante: o harness verifica que a citação existe, não que ela sustenta a frase. Isso só o juiz mede, fora de linha.");

  // 11. Conclusão ----------------------------------------------------------
  pres.addSection({ title: "Conclusão" });
  s = pres.addSlide({ masterName: "ESCURO", sectionTitle: "Conclusão" });
  s.addText("O que ficou demonstrado", { placeholder: "title" });
  s.addText("Um modelo de 4B local responde com documento e página quando cercado por recuperação híbrida e por regras que recusam, avisam e removem — e cada resposta deixa traço.", { placeholder: "body" });
  txt(s, [
    { text: "Ficou de fora: ", options: { bold: true, color: HEX.laranja } },
    { text: "Habilidades Essenciais do 2º ano no corpus, revisão humana do gabarito, LoRA, n8n e verificação de que o trecho sustenta a frase.", options: { color: "F2D9C2" } },
  ], { x: 0.6, y: 3.85, w: 8.8, h: 0.7, fontSize: 13 });
  txt(s, "Código: github.com/Graco2/alfarag", { x: 0.6, y: 4.7, w: 8.8, h: 0.35, fontSize: 13, color: "FFFFFF", bold: true });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 7.6, y: 1.35, w: 1.8, h: 1.8, rectRadius: 0.3, fill: { color: HEX.laranja }, line: { type: "none" }, objectName: "logo2" });
  txt(s, "Aa", { x: 7.6, y: 1.35, w: 1.8, h: 1.8, fontSize: 54, bold: true, color: "FFFFFF", align: "center", valign: "middle", fontFace: "Cambria" });
  s.addNotes("Conclusão (40 s). Demonstramos que o modelo pequeno e local funciona quando o sistema em volta faz a parte verificável. Ficou de fora o que está listado; não afirmamos efeito em sala. Obrigado; abrimos para perguntas.");

  await pres.writeFile({ fileName: SAIDA });
  await applyTheme(SAIDA, THEME);
  console.log("ok", SAIDA);
})();
