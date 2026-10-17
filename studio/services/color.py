"""Operações acadêmicas com matrizes independentes e modelo de cor explícito."""

import cv2
import numpy as np

MODELOS = ("BGR", "RGB", "HSV", "Cinza")
OPERACOES = (
    "Duplicar / restaurar cópia",
    "Converter modelo de cor",
    "Redimensionar",
    "Quantizar níveis",
    "Crescimento de regiões",
)


def validar_imagem(imagem):
    if (
        not isinstance(imagem, np.ndarray)
        or imagem.dtype != np.uint8
        or (not imagem.size)
    ):
        raise ValueError("Use uma imagem não vazia de 8 bits.")
    if imagem.ndim != 2 and (not (imagem.ndim == 3 and imagem.shape[2] == 3)):
        raise ValueError("Use uma imagem de um ou três canais.")
    return imagem


def converter_cor(imagem, origem="BGR", destino="RGB"):
    """Converte dados de verdade; devolver uma cópia evita compartilhar memória."""
    validar_imagem(imagem)
    if origem not in MODELOS or destino not in MODELOS:
        raise ValueError("Modelo de cor inválido.")
    if (imagem.ndim == 2) != (origem == "Cinza"):
        raise ValueError("O modelo informado não corresponde aos canais da matriz.")
    if origem == destino:
        return imagem.copy()
    bgr = (
        imagem
        if origem == "BGR"
        else cv2.cvtColor(
            imagem,
            {
                "RGB": cv2.COLOR_RGB2BGR,
                "HSV": cv2.COLOR_HSV2BGR,
                "Cinza": cv2.COLOR_GRAY2BGR,
            }[origem],
        )
    )
    if destino == "BGR":
        return bgr.copy()
    return cv2.cvtColor(
        bgr,
        {
            "RGB": cv2.COLOR_BGR2RGB,
            "HSV": cv2.COLOR_BGR2HSV,
            "Cinza": cv2.COLOR_BGR2GRAY,
        }[destino],
    )


def redimensionar(imagem, largura, altura):
    validar_imagem(imagem)
    largura, altura = (int(largura), int(altura))
    if largura < 1 or altura < 1 or largura * altura > 40000000:
        raise ValueError(
            "Dimensões devem ser positivas e o resultado deve ter até 40 milhões de pixels."
        )
    h, w = imagem.shape[:2]
    metodo = cv2.INTER_AREA if largura <= w and altura <= h else cv2.INTER_LINEAR
    return cv2.resize(imagem, (largura, altura), interpolation=metodo)


def quantizar(imagem, niveis):
    validar_imagem(imagem)
    niveis = int(niveis)
    if not 2 <= niveis <= 256:
        raise ValueError("Escolha de 2 a 256 níveis por canal.")
    indices = np.floor(imagem.astype(np.float32) * niveis / 256)
    return np.rint(indices * 255 / (niveis - 1)).astype(np.uint8)


def histogramas(imagem, modelo="BGR", espaco="RGB"):
    """Retorna contagens por canal; H de HSV tem 180 níveis no OpenCV de 8 bits."""
    if espaco not in ("RGB", "HSV", "Cinza"):
        raise ValueError("Escolha RGB, HSV ou Cinza para o histograma.")
    dados = converter_cor(imagem, modelo, espaco)
    nomes = ("Cinza",) if espaco == "Cinza" else tuple(espaco)
    canais = (dados,) if dados.ndim == 2 else cv2.split(dados)
    return {
        nome: np.bincount(canal.ravel(), minlength=180 if nome == "H" else 256)
        for nome, canal in zip(nomes, canais)
    }


def crescer_regiao(imagem, semente, tolerancia=15, conectividade=4):
    """Flood fill de faixa fixa: compara cada canal com o pixel semente.

    A máscara contém apenas pixels conectados e dentro da tolerância da semente,
    sem encadear pequenas diferenças que atravessariam gradientes inteiros.
    """
    validar_imagem(imagem)
    x, y = map(int, semente)
    h, w = imagem.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError(
            "A semente deve estar dentro da imagem (coordenadas começam em zero)."
        )
    tolerancia = float(tolerancia)
    if not np.isfinite(tolerancia) or not 0 <= tolerancia <= 255:
        raise ValueError("A tolerância deve estar entre 0 e 255.")
    if conectividade not in (4, 8):
        raise ValueError("A conectividade deve ser 4 ou 8.")
    mascara = np.zeros((h + 2, w + 2), np.uint8)
    diferenca = tolerancia if imagem.ndim == 2 else (tolerancia,) * 3
    flags = (
        conectividade | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | 255 << 8
    )
    cv2.floodFill(imagem.copy(), mascara, (x, y), 0, diferenca, diferenca, flags)
    return mascara[1:-1, 1:-1].copy()
