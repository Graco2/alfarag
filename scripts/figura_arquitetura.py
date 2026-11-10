"""Gera docs/fig1_arquitetura.png (Fig. 1 do artigo e slide de arquitetura)."""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from app.config import EXPERIMENTOS, LIMIAR_COBERTURA, MODELO_EMBED, MODELO_LLM, ORCAMENTO_CONTEXTO  # noqa: E402
from app.prompts import VERSAO_PROMPT  # noqa: E402

LARANJA, TINTA, CINZA, VERDE, VERMELHO, AZUL = "#E86600", "#1A1310", "#58514A", "#007B53", "#B3261E", "#2C4AA8"


def caixa(ax, x, y, w, h, titulo, sub, cor, fundo="#FFFFFF"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fundo, ec=cor, lw=1.6))
    ax.text(x + w / 2, y + h * 0.66, titulo, ha="center", va="center", fontsize=8.6, fontweight="bold", color=TINTA, family="DejaVu Sans")
    ax.text(x + w / 2, y + h * 0.28, sub, ha="center", va="center", fontsize=6.3, color=CINZA, family="DejaVu Sans")


def seta(ax, x1, y1, x2, y2, cor=CINZA, txt=None, dx=0.05):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="-|>", color=cor, lw=1.2))
    if txt:
        ax.text((x1 + x2) / 2 + dx, (y1 + y2) / 2, txt, fontsize=6.4, color=cor, va="center", fontweight="bold")


def main():
    k = EXPERIMENTOS["E2"]["top_k"]
    fig, ax = plt.subplots(figsize=(4.3, 4.9), dpi=300)
    ax.set_xlim(0, 4.3)
    ax.set_ylim(0, 4.9)
    ax.axis("off")
    W, H, X = 3.0, 0.44, 0.05
    ys = [4.38, 3.78, 3.18, 2.58, 1.98, 1.38, 0.78, 0.18]
    caixa(ax, X, ys[0], W, H, "Pergunta do professor", "texto livre, sem identificação do aluno", CINZA, "#FCFAF7")
    caixa(ax, X, ys[1], W, H, "Harness de entrada", "dado pessoal → bloqueia · diagnóstico → ressalva", VERMELHO, "#FDE2DF")
    caixa(ax, X, ys[2], W, H, "Recuperação híbrida", f"BM25 + {MODELO_EMBED} → fusão RRF (k=60)", LARANJA, "#FFEBD4")
    caixa(ax, X, ys[3], W, H, "Teste de cobertura", f"melhor cosseno ≥ {str(LIMIAR_COBERTURA).replace(".", ",")}?", VERMELHO, "#FDE2DF")
    caixa(ax, X, ys[4], W, H, "Janela de contexto", f"prompt {VERSAO_PROMPT} + top-{k} trechos [n] ≤ {ORCAMENTO_CONTEXTO} tokens", AZUL, "#EAF0FF")
    caixa(ax, X, ys[5], W, H, "LLM local (Ollama, CPU)", f"{MODELO_LLM}, temperatura 0,2, sem raciocínio", LARANJA, "#FFEBD4")
    caixa(ax, X, ys[6], W, H, "Harness de saída", "[n] existe? · código BNCC no trecho? · ressalva?", VERMELHO, "#FDE2DF")
    caixa(ax, X, ys[7], W, H, "Resposta + fontes + traço", "documento e página · JSONL por resposta", VERDE, "#DDF5EA")
    for a, b in zip(ys[:-1], ys[1:]):
        seta(ax, X + W / 2, a, X + W / 2, b + H)
    # Saídas laterais do harness
    xr = X + W + 0.08
    ax.text(xr, ys[1] + H / 2, "bloqueio", fontsize=6.6, color=VERMELHO, va="center", fontweight="bold")
    ax.annotate("", xy=(xr - 0.02, ys[1] + H / 2), xytext=(X + W, ys[1] + H / 2), arrowprops=dict(arrowstyle="-|>", color=VERMELHO, lw=1))
    ax.text(xr, ys[3] + H / 2, "não: recusa\nsem chamar\no LLM", fontsize=6.4, color=VERMELHO, va="center", fontweight="bold")
    ax.annotate("", xy=(xr - 0.02, ys[3] + H / 2), xytext=(X + W, ys[3] + H / 2), arrowprops=dict(arrowstyle="-|>", color=VERMELHO, lw=1))
    ax.text(xr, ys[6] + H / 2, "remove /\ninsere aviso", fontsize=6.4, color=VERMELHO, va="center", fontweight="bold")
    ax.text(xr, ys[2] + H / 2, "corpus C4:\n6 documentos", fontsize=6.4, color=CINZA, va="center")
    ax.text(xr, ys[5] + H / 2, "modelo\ndecide o texto", fontsize=6.4, color=CINZA, va="center")
    out = RAIZ / "docs"
    out.mkdir(exist_ok=True)
    fig.savefig(out / "fig1_arquitetura.png", bbox_inches="tight", facecolor="white")
    print("ok", out / "fig1_arquitetura.png")


if __name__ == "__main__":
    main()
