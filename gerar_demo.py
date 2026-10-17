"""Gera imagens e vídeo sintéticos reproduzíveis, sem fotos de pessoas."""
import argparse
from pathlib import Path

import cv2
import numpy as np


def gerar_demo(pasta="demo"):
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    h, w = 360, 640
    gradiente = np.tile(np.linspace(30, 210, w, dtype=np.uint8), (h, 1))
    cena = cv2.merge([gradiente, gradiente, gradiente])
    cv2.rectangle(cena, (40, 60), (220, 250), (40, 60, 220), -1)
    cv2.circle(cena, (370, 170), 85, (60, 200, 40), -1)
    cv2.circle(cena, (370, 170), 25, (40, 60, 80), -1)
    cv2.rectangle(cena, (500, 60), (595, 260), (220, 100, 40), -1)
    cv2.putText(cena, "OpenCV Studio - demo sintetica", (30, 325), cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 2)
    baixo = np.clip(cena.astype(np.float32)*.18+95, 0, 255).astype(np.uint8)
    ruido = cena.copy()
    pontos = rng.integers(0, h*w, h*w//12)
    ruido.reshape(-1, 3)[pontos] = rng.choice([0, 255], (len(pontos), 1))
    morfologia = np.zeros((h, w), np.uint8)
    cv2.rectangle(morfologia, (50, 60), (250, 280), 255, -1)
    cv2.circle(morfologia, (420, 170), 95, 255, -1)
    morfologia[150:156, 50:251] = 0
    cv2.circle(morfologia, (420, 170), 8, 0, -1)
    morfologia[rng.integers(0, h, 200), rng.integers(0, w, 200)] = 255
    segunda = np.zeros_like(cena)
    segunda[:] = (65, 30, 10)
    cv2.circle(segunda, (320, 180), 120, (20, 80, 150), -1)
    for nome, imagem in {"cena": cena, "baixo_contraste": baixo, "ruido": ruido,
                          "morfologia": morfologia, "segunda": segunda}.items():
        ok, buffer = cv2.imencode(".png", imagem)
        if not ok:
            raise RuntimeError(f"Falha ao gerar {nome}.")
        buffer.tofile(pasta / f"{nome}.png")
    caminho = pasta / "video_demo.avi"
    writer = cv2.VideoWriter(str(caminho), cv2.VideoWriter_fourcc(*"MJPG"), 15, (w, h))
    if not writer.isOpened():
        raise RuntimeError("Codec MJPG indisponível para gerar o vídeo de demonstração.")
    try:
        for i in range(60):
            frame = cena.copy()
            x = 30 + i*8
            cv2.rectangle(frame, (x, 30), (min(x+70, w-1), 95), (255, 210, 20), -1)
            cv2.putText(frame, f"Frame {i+1:02}/60", (440, 345), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 1)
            writer.write(frame)
    finally:
        writer.release()
    return pasta.resolve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pasta", default="demo", help="Diretório dos arquivos gerados")
    args = parser.parse_args()
    print(f"Demonstração sintética criada em: {gerar_demo(args.pasta)}")
