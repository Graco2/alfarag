"""Captura as telas do app para o artigo e os slides, em modo replay (sem chamar o modelo).

Requer o servidor em http://localhost:7860 e o Google Chrome instalado.
Lê os ids de docs/screens/tracos_demo.txt (linha 1: resposta B03; 2: recusa L03; 3: diagnóstico L01).

Uso: python docs/capturar_telas.py
Gera em docs/screens/: <nome>.png (1280×900 a 2x), <nome>_chat.png, <nome>_painel.png,
painel.png (painel da resposta B03) e fig2_app.png (faixa superior da tela do L01, usada no artigo).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parents[1]
TELAS = RAIZ / "docs" / "screens"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
URL = "http://localhost:7860"
W, H, ESCALA = 1280, 900, 2
# Caixas em px CSS, medidas no layout de 1280×900 (web/styles.css):
# topo 0–67; conversa 0–890 × 67–757 (acima do campo de pergunta); painel 890–1280 × 67–900.
CHAT = (0, 67, 890, 757)
PAINEL = (890, 67, 1280, 900)
FAIXA_APP = (0, 0, 1280, 527)


def capturar(url: str, destino: Path, perfil: str) -> None:
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                    "--no-default-browser-check", f"--user-data-dir={perfil}", f"--force-device-scale-factor={ESCALA}",
                    f"--window-size={W},{H}", "--virtual-time-budget=15000", f"--screenshot={destino}", url],
                   check=True, capture_output=True, timeout=180)


def recortar(origem: Path, caixa: tuple[int, int, int, int], destino: Path) -> None:
    im = Image.open(origem)
    if im.size != (W * ESCALA, H * ESCALA):
        raise SystemExit(f"{origem.name}: tamanho {im.size}, esperado {(W * ESCALA, H * ESCALA)}")
    im.crop(tuple(v * ESCALA for v in caixa)).save(destino)


def main() -> None:
    ids = [l.split()[0] for l in (TELAS / "tracos_demo.txt").read_text().splitlines() if l.strip()]
    with tempfile.TemporaryDirectory() as perfil:
        for nome, tid in zip(["resposta", "recusa", "diagnostico"], ids):
            tela = TELAS / f"{nome}.png"
            capturar(f"{URL}/?traco={tid}&rolar=topo&painel=1", tela, perfil)
            recortar(tela, CHAT, TELAS / f"{nome}_chat.png")
            recortar(tela, PAINEL, TELAS / f"{nome}_painel.png")
            print("ok", nome, tid)
    shutil.copy(TELAS / "resposta_painel.png", TELAS / "painel.png")
    recortar(TELAS / "diagnostico.png", FAIXA_APP, TELAS / "fig2_app.png")
    print("ok painel.png e fig2_app.png")


if __name__ == "__main__":
    main()
