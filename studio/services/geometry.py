"""Recorte por formas, com coordenadas e contagem na resolução original."""

import numpy as np

FORMAS_RECORTE = ("Retângulo", "Quadrado", "Elipse", "Círculo", "Losango")


def limites_recorte(tamanho, inicio, fim, forma):
    """Retorna limites exclusivos, restringindo a seleção à imagem."""
    if forma not in FORMAS_RECORTE:
        raise ValueError("Forma desconhecida.")
    h, w = tamanho[:2]
    ax, ay = (int(np.clip(v, 0, limite)) for v, limite in zip(inicio, (w, h)))
    bx, by = (int(np.clip(v, 0, limite)) for v, limite in zip(fim, (w, h)))
    if forma in ("Quadrado", "Círculo"):
        lado = min(abs(bx - ax), abs(by - ay))
        bx = ax + (lado if bx >= ax else -lado)
        by = ay + (lado if by >= ay else -lado)
    return (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


def mascara_recorte(largura, altura, forma):
    if largura <= 0 or altura <= 0:
        raise ValueError(
            "Arraste para selecionar uma área com largura e altura maiores que zero."
        )
    if forma not in FORMAS_RECORTE:
        raise ValueError("Forma desconhecida.")
    y, x = np.ogrid[:altura, :largura]
    x = (x + 0.5 - largura / 2) / (largura / 2)
    y = (y + 0.5 - altura / 2) / (altura / 2)
    if forma in ("Elipse", "Círculo"):
        return x * x + y * y <= 1
    if forma == "Losango":
        return abs(x) + abs(y) <= 1
    return np.ones((altura, largura), dtype=bool)


def recortar_imagem(imagem, inicio, fim, forma):
    x0, y0, x1, y1 = limites_recorte(imagem.shape, inicio, fim, forma)
    mascara = mascara_recorte(x1 - x0, y1 - y0, forma)
    resultado = imagem[y0:y1, x0:x1].copy()
    resultado[~mascara] = 0
    return (resultado, int(np.count_nonzero(mascara)))


import math

FORMAS_MEDICAO = ("Polígono", "Desenho livre") + FORMAS_RECORTE


def mascara_poligono(tamanho, pontos):
    """Rasteriza pelo centro de cada pixel; retorna máscara local e seus limites.

    Bordas pertencem à região. Contornos cruzados usam a regra par/ímpar.
    Coordenadas representam bordas de pixels, não índices inclusivos do OpenCV.
    """
    h, w = tamanho[:2]
    vertices = np.asarray(pontos, dtype=float)
    if (
        vertices.ndim != 2
        or vertices.shape[1] != 2
        or len(vertices) < 3
        or (not np.isfinite(vertices).all())
    ):
        raise ValueError("Marque pelo menos três pontos para formar um contorno.")
    if np.linalg.matrix_rank(vertices - vertices[0]) < 2:
        raise ValueError("O contorno precisa formar uma área, não apenas uma linha.")
    x0 = max(0, min(w, int(np.floor(vertices[:, 0].min()))))
    y0 = max(0, min(h, int(np.floor(vertices[:, 1].min()))))
    x1 = max(0, min(w, int(np.ceil(vertices[:, 0].max()))))
    y1 = max(0, min(h, int(np.ceil(vertices[:, 1].max()))))
    y, x = np.ogrid[y0:y1, x0:x1]
    x, y = (x + 0.5, y + 0.5)
    dentro = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    borda = np.zeros_like(dentro)
    for a, b in zip(vertices, np.roll(vertices, -1, axis=0)):
        ax, ay = a
        bx, by = b
        if ay != by:
            cruza = (ay > y) != (by > y)
            dentro ^= cruza & (x < ax + (y - ay) * (bx - ax) / (by - ay))
        if ax != bx or ay != by:
            produto = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
            borda |= (
                (np.abs(produto) < 1e-09)
                & (x >= min(ax, bx))
                & (x <= max(ax, bx))
                & (y >= min(ay, by))
                & (y <= max(ay, by))
            )
    mascara = dentro | borda
    if not mascara.any():
        raise ValueError("O contorno não contém pixels. Selecione uma área maior.")
    return (mascara, (x0, y0, x1, y1))


def medir_regiao(tamanho, forma, inicio=None, fim=None, pontos=()):
    if forma in ("Polígono", "Desenho livre"):
        mascara, limites = mascara_poligono(tamanho, pontos)
    else:
        limites = limites_recorte(tamanho, inicio, fim, forma)
        x0, y0, x1, y1 = limites
        mascara = mascara_recorte(x1 - x0, y1 - y0, forma)
    pixels = int(np.count_nonzero(mascara))
    if not pixels:
        raise ValueError("Selecione uma região com pelo menos um pixel.")
    return dict(
        forma=forma,
        inicio=inicio,
        fim=fim,
        pontos=list(pontos),
        limites=limites,
        pixels=pixels,
    )


def calcular_escala(pontos, distancia):
    distancia = float(str(distancia).replace(",", "."))
    pixels = math.dist(*pontos)
    if (
        not math.isfinite(distancia)
        or distancia <= 0
        or (not math.isfinite(pixels))
        or (pixels <= 0)
    ):
        raise ValueError(
            "A distância real e a linha de referência devem ser maiores que zero."
        )
    return distancia / pixels


def area_calibrada(pixels, escala):
    return None if escala is None else pixels * escala**2
