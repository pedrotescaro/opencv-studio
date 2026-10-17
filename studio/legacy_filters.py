"""Pure OpenCV algorithms migrated from the original editor (no UI imports)."""

import cv2

import numpy as np

MORFOLOGIA = {
    "Erosão": cv2.MORPH_ERODE,
    "Dilatação": cv2.MORPH_DILATE,
    "Opening": cv2.MORPH_OPEN,
    "Closing": cv2.MORPH_CLOSE,
    "Gradiente morfológico": cv2.MORPH_GRADIENT,
    "Top-hat": cv2.MORPH_TOPHAT,
    "Black-hat": cv2.MORPH_BLACKHAT,
    "Hit-or-miss": cv2.MORPH_HITMISS,
}

FORMAS = (
    "Retângulo",
    "Elipse",
    "Cruz",
    "Losango",
    "Linha horizontal",
    "Linha vertical",
    "Diagonal",
    "Diagonal inversa",
    "Personalizado",
)

BORDAS = {
    "Padrão morfológico": cv2.BORDER_CONSTANT,
    "Replicar": cv2.BORDER_REPLICATE,
    "Refletir": cv2.BORDER_REFLECT_101,
    "Constante preta": cv2.BORDER_CONSTANT,
    "Constante branca": cv2.BORDER_CONSTANT,
}

EXTRAS = {
    "Cores": ["Saturação", "Matiz", "Temperatura"],
    "Luz e contraste": ["Normalizar"],
    "Bordas": ["Scharr X", "Scharr Y", "Magnitude do gradiente"],
    "Efeitos": ["Estilização", "Lápis cinza", "Lápis colorido", "Preservar bordas"],
    "Segmentação": [
        "Threshold inverso",
        "Threshold truncado",
        "Threshold to-zero",
        "Threshold to-zero inverso",
        "Threshold Triangle",
        "Adaptativo médio",
        "Distância L1",
        "Distância L2",
        "Distância xadrez",
        "Contornos",
    ],
    "Desfoque": ["Desfoque de movimento"],
}

MAPAS = {
    "Mapa " + name.title(): getattr(cv2, "COLORMAP_" + name)
    for name in (
        "AUTUMN",
        "BONE",
        "JET",
        "WINTER",
        "RAINBOW",
        "OCEAN",
        "SUMMER",
        "SPRING",
        "COOL",
        "HSV",
        "PINK",
        "HOT",
        "PARULA",
        "MAGMA",
        "INFERNO",
        "PLASMA",
        "VIRIDIS",
        "CIVIDIS",
        "TWILIGHT",
        "TWILIGHT_SHIFTED",
        "TURBO",
        "DEEPGREEN",
    )
    if hasattr(cv2, "COLORMAP_" + name)
}

EXTRAS["Mapas de cores"] = list(MAPAS)

PARAMETROS = {
    "Saturação": [("Saturação (%)", 0, 300, 120)],
    "Matiz": [("Deslocamento (graus)", -180, 180, 30)],
    "Temperatura": [("Frio ← → quente", -100, 100, 20)],
    "Desfoque de movimento": [("Comprimento", 1, 51, 9), ("Ângulo", -180, 180, 0)],
    "CLAHE": [("Limite × 10", 1, 100, 20), ("Grade", 2, 32, 8)],
    "Denoise": [("Força", 1, 40, 10)],
    "Detail Enhance": [
        ("Sigma espacial", 1, 100, 10),
        ("Sigma de cor (%)", 1, 100, 15),
    ],
    "Contornos": [("Limiar binário", 0, 255, 127), ("Espessura", 1, 10, 2)],
}

for _name in (
    "Threshold inverso",
    "Threshold truncado",
    "Threshold to-zero",
    "Threshold to-zero inverso",
):
    PARAMETROS[_name] = [("Limiar", 0, 255, 127)]

PARAMETROS["Adaptativo médio"] = [
    ("Bloco (ímpar)", 3, 51, 11),
    ("Constante C", -20, 20, 2),
]

for _name in ("Estilização", "Lápis cinza", "Lápis colorido", "Preservar bordas"):
    PARAMETROS[_name] = [
        ("Sigma espacial", 1, 200, 60),
        ("Sigma de cor (%)", 1, 100, 30),
    ]


def criar_kernel(forma, largura, altura):
    if not (1 <= largura <= 31 and 1 <= altura <= 31):
        raise ValueError("As dimensões devem estar entre 1 e 31.")
    if forma in ("Retângulo", "Elipse", "Cruz"):
        tipo = {
            "Retângulo": cv2.MORPH_RECT,
            "Elipse": cv2.MORPH_ELLIPSE,
            "Cruz": cv2.MORPH_CROSS,
        }[forma]
        return cv2.getStructuringElement(tipo, (largura, altura)).astype(np.int8)
    y, x = np.indices((altura, largura))
    if forma == "Losango":
        return (
            abs(x - largura // 2) / max(1, largura // 2)
            + abs(y - altura // 2) / max(1, altura // 2)
            <= 1
        ).astype(np.int8)
    k = np.zeros((altura, largura), np.int8)
    if forma == "Linha horizontal":
        k[altura // 2, :] = 1
    elif forma == "Linha vertical":
        k[:, largura // 2] = 1
    elif forma in ("Diagonal", "Diagonal inversa"):
        cv2.line(
            k,
            (0, 0 if forma == "Diagonal" else altura - 1),
            (largura - 1, altura - 1 if forma == "Diagonal" else 0),
            1,
            1,
        )
    else:
        raise ValueError("Forma desconhecida.")
    return k


def validar_morfologia(config):
    required = {"kernel", "anchor", "iterations", "border", "mode", "threshold"}
    if not isinstance(config, dict) or not required.issubset(config):
        raise ValueError(
            "Configuração incompleta: matriz, âncora, iterações, borda, modo e limiar são obrigatórios."
        )
    k = np.asarray(config["kernel"])
    if k.ndim != 2 or not all((1 <= n <= 31 for n in k.shape)):
        raise ValueError("A matriz precisa ter entre 1 e 31 linhas e colunas.")
    if not np.isin(k, [-1, 0, 1]).all() or not np.any(k == 1):
        raise ValueError("Use apenas -1, 0 e 1, com pelo menos uma célula 1.")
    if not isinstance(config["anchor"], (tuple, list)):
        raise ValueError("A âncora deve conter dois inteiros.")
    anchor = tuple(config["anchor"])
    if len(anchor) != 2 or any((type(v) is not int for v in anchor)):
        raise ValueError("A âncora deve conter dois inteiros.")
    if anchor != (-1, -1) and (
        not (0 <= anchor[0] < k.shape[1] and 0 <= anchor[1] < k.shape[0])
    ):
        raise ValueError("A âncora deve estar dentro da matriz.")
    if type(config["iterations"]) is not int or not 1 <= config["iterations"] <= 30:
        raise ValueError("Use entre 1 e 30 iterações.")
    if (
        not isinstance(config["border"], str)
        or config["border"] not in BORDAS
        or config["mode"] not in ("Colorida", "Cinza", "Binária")
    ):
        raise ValueError("Modo de imagem ou borda inválidos.")
    if type(config["threshold"]) is not int or not 0 <= config["threshold"] <= 255:
        raise ValueError("O limiar deve estar entre 0 e 255.")
    return dict(config, kernel=k.astype(np.int8), anchor=anchor)


def aplicar_morfologia(img, filtro, config):
    c = validar_morfologia(config)
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    source = img if c["mode"] == "Colorida" else gray
    if c["mode"] == "Binária" or filtro == "Hit-or-miss":
        source = cv2.threshold(gray, c["threshold"], 255, cv2.THRESH_BINARY)[1]
    kernel = (
        c["kernel"] if filtro == "Hit-or-miss" else (c["kernel"] == 1).astype(np.uint8)
    )
    kwargs = dict(
        anchor=c["anchor"], iterations=c["iterations"], borderType=BORDAS[c["border"]]
    )
    if c["border"].startswith("Constante"):
        value = 255 if c["border"] == "Constante branca" else 0
        kwargs["borderValue"] = (value,) * 4
    if filtro == "Hit-or-miss":
        objeto = cv2.erode(source, (kernel == 1).astype(np.uint8), **kwargs)
        if not np.any(kernel == -1):
            return objeto
        fundo_kwargs = dict(kwargs)
        if "borderValue" in fundo_kwargs:
            fundo_kwargs["borderValue"] = (255 - value,) * 4
        fundo = cv2.erode(
            cv2.bitwise_not(source), (kernel == -1).astype(np.uint8), **fundo_kwargs
        )
        return cv2.bitwise_and(objeto, fundo)
    return cv2.morphologyEx(source, MORFOLOGIA[filtro], kernel, **kwargs)


def processar_extra(img, filtro, p1, p2):
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cor = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img
    if filtro in MAPAS:
        return cv2.applyColorMap(gray, MAPAS[filtro])
    if filtro == "Normalizar":
        return cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    if filtro in ("Saturação", "Matiz"):
        hsv = cv2.cvtColor(cor, cv2.COLOR_BGR2HSV)
        if filtro == "Matiz":
            hsv[:, :, 0] = (hsv[:, :, 0].astype(np.int16) + int(p1 / 2)) % 180
        else:
            hsv[:, :, 1] = np.clip(hsv[:, :, 1].astype(float) * p1 / 100, 0, 255)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    if filtro == "Temperatura":
        return np.clip(cor.astype(np.float32) + np.array([-p1, 0, p1]), 0, 255).astype(
            np.uint8
        )
    thresholds = {
        "Threshold inverso": cv2.THRESH_BINARY_INV,
        "Threshold truncado": cv2.THRESH_TRUNC,
        "Threshold to-zero": cv2.THRESH_TOZERO,
        "Threshold to-zero inverso": cv2.THRESH_TOZERO_INV,
        "Threshold Triangle": cv2.THRESH_BINARY | cv2.THRESH_TRIANGLE,
    }
    if filtro in thresholds:
        return cv2.threshold(gray, p1, 255, thresholds[filtro])[1]
    if filtro == "Adaptativo médio":
        return cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY,
            max(3, int(p1) | 1),
            p2,
        )
    if filtro.startswith("Distância "):
        mode = {
            "Distância L1": cv2.DIST_L1,
            "Distância L2": cv2.DIST_L2,
            "Distância xadrez": cv2.DIST_C,
        }[filtro]
        binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        dist = cv2.distanceTransform(binary, mode, 3)
        return cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if filtro == "Contornos":
        binary = cv2.threshold(gray, p1, 255, cv2.THRESH_BINARY)[1]
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        return cv2.drawContours(
            cor.copy(), contours, -1, (50, 220, 120), max(1, int(p2))
        )
    if filtro in ("Scharr X", "Scharr Y", "Magnitude do gradiente"):
        sx = cv2.Scharr(gray, cv2.CV_32F, 1, 0)
        sy = cv2.Scharr(gray, cv2.CV_32F, 0, 1)
        return cv2.convertScaleAbs(
            sx
            if filtro == "Scharr X"
            else sy
            if filtro == "Scharr Y"
            else cv2.magnitude(sx, sy)
        )
    if filtro == "Desfoque de movimento":
        n = max(1, int(p1) | 1)
        kernel = np.zeros((n, n), np.float32)
        kernel[n // 2] = 1
        kernel = cv2.warpAffine(
            kernel, cv2.getRotationMatrix2D((n // 2, n // 2), p2, 1), (n, n)
        )
        return cv2.filter2D(img, -1, kernel / max(float(kernel.sum()), 1e-08))
    if filtro == "Estilização":
        return cv2.stylization(cor, sigma_s=p1, sigma_r=p2 / 100)
    if filtro in ("Lápis cinza", "Lápis colorido"):
        return cv2.pencilSketch(cor, sigma_s=p1, sigma_r=p2 / 100, shade_factor=0.05)[
            int(filtro == "Lápis colorido")
        ]
    if filtro == "Preservar bordas":
        return cv2.edgePreservingFilter(cor, flags=1, sigma_s=p1, sigma_r=p2 / 100)
    raise ValueError(f"Filtro adicional desconhecido: {filtro}")


class LegacyFilters:
    def criar_catalogo_filtros(self):
        catalogo = {
            "Cores": [
                "Escala de cinza",
                "Preto e branco",
                "Threshold Otsu",
                "Threshold adaptativo",
                "Inverter cores",
                "Sépia",
                "Solarizar",
                "Posterizar",
            ],
            "Canais": [
                "Canal Azul",
                "Canal Verde",
                "Canal Vermelho",
                "Canal H (HSV)",
                "Canal S (HSV)",
                "Canal V (HSV)",
                "Split BGR",
            ],
            "Luz e contraste": [
                "Brilho",
                "Contraste",
                "Gamma",
                "Equalizar histograma",
                "CLAHE",
            ],
            "Desfoque": ["Blur", "Gaussian Blur", "Median Blur", "Bilateral"],
            "Detalhes": [
                "Sharpen",
                "Sharpen forte",
                "Unsharp Mask",
                "Detail Enhance",
                "Denoise",
            ],
            "Bordas": ["Canny", "Sobel X", "Sobel Y", "Sobel XY", "Laplacian"],
            "Morfologia": [
                "Erosão",
                "Dilatação",
                "Opening",
                "Closing",
                "Gradiente morfológico",
            ],
            "Efeitos": ["Emboss", "Sketch", "Cartoon", "Pixelizar"],
            "Transformar": [
                "Flip horizontal",
                "Flip vertical",
                "Flip completo",
                "Rotacionar 90°",
                "Rotacionar -90°",
                "Rotacionar 180°",
                "Rotação livre",
                "Reduzir 50%",
                "Aumentar 200%",
            ],
        }
        catalogo["Morfologia"] = list(MORFOLOGIA)
        for categoria, filtros in EXTRAS.items():
            catalogo.setdefault(categoria, []).extend(filtros)
        return catalogo

    @staticmethod
    def garantir_bgr(img):
        if img.ndim == 2:
            return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        return img

    @staticmethod
    def cinza(img):
        if img.ndim == 2:
            return img
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def impar(valor, minimo=1):
        n = max(minimo, int(round(valor)))
        if n % 2 == 0:
            n += 1
        return n

    def processar_filtro(self, img, filtro, p1, p2, morfologia=None):
        if filtro in MORFOLOGIA:
            if morfologia is not None and (not morfologia.get("enabled", True)):
                return img.copy()
            if morfologia is None:
                k = self.impar(p1)
                morfologia = dict(
                    kernel=np.ones((k, k), np.int8),
                    anchor=(-1, -1),
                    iterations=1,
                    border="Padrão morfológico",
                    mode="Colorida",
                    threshold=127,
                )
            return aplicar_morfologia(img, filtro, morfologia)
        if any((filtro in filtros for filtros in EXTRAS.values())):
            return processar_extra(img, filtro, p1, p2)
        if filtro == "Escala de cinza":
            return self.cinza(img)
        if filtro == "Preto e branco":
            gray = self.cinza(img)
            _, out = cv2.threshold(gray, int(p1), 255, cv2.THRESH_BINARY)
            return out
        if filtro == "Threshold Otsu":
            gray = self.cinza(img)
            _, out = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return out
        if filtro == "Threshold adaptativo":
            gray = self.cinza(img)
            bloco = self.impar(p1, 3)
            return cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                bloco,
                int(p2),
            )
        if filtro == "Inverter cores":
            return cv2.bitwise_not(img)
        if filtro == "Sépia":
            cor = self.garantir_bgr(img)
            matriz = np.array(
                [[0.272, 0.534, 0.131], [0.349, 0.686, 0.168], [0.393, 0.769, 0.189]],
                dtype=np.float32,
            )
            return np.clip(cv2.transform(cor, matriz), 0, 255).astype(np.uint8)
        if filtro == "Solarizar":
            limiar = int(p1)
            return np.where(img < limiar, img, 255 - img).astype(np.uint8)
        if filtro == "Posterizar":
            niveis = max(2, int(p1))
            passo = 256 / niveis
            return (np.floor(img / passo) * passo).clip(0, 255).astype(np.uint8)
        if filtro in {"Canal Azul", "Canal Verde", "Canal Vermelho"}:
            cor = self.garantir_bgr(img)
            b, g, r = cv2.split(cor)
            return {"Canal Azul": b, "Canal Verde": g, "Canal Vermelho": r}[filtro]
        if filtro in {"Canal H (HSV)", "Canal S (HSV)", "Canal V (HSV)"}:
            hsv = cv2.cvtColor(self.garantir_bgr(img), cv2.COLOR_BGR2HSV)
            h, s, v = cv2.split(hsv)
            return {"Canal H (HSV)": h, "Canal S (HSV)": s, "Canal V (HSV)": v}[filtro]
        if filtro == "Split BGR":
            cor = self.garantir_bgr(img)
            b, g, r = cv2.split(cor)
            zero = np.zeros_like(b)
            azul = cv2.merge([b, zero, zero])
            verde = cv2.merge([zero, g, zero])
            vermelho = cv2.merge([zero, zero, r])
            cima = np.hstack([cor, azul])
            baixo = np.hstack([verde, vermelho])
            return np.vstack([cima, baixo])
        if filtro == "Brilho":
            beta = int(p1)
            if beta >= 0:
                return cv2.add(img, np.full_like(img, beta))
            return cv2.subtract(img, np.full_like(img, -beta))
        if filtro == "Contraste":
            alpha = max(0.05, 1.0 + p1 / 100.0)
            return cv2.convertScaleAbs(img, alpha=alpha, beta=0)
        if filtro == "Gamma":
            gamma = max(0.1, p1 / 100.0)
            tabela = np.array(
                [(i / 255.0) ** (1.0 / gamma) * 255 for i in range(256)], dtype=np.uint8
            )
            return cv2.LUT(img, tabela)
        if filtro == "Equalizar histograma":
            if img.ndim == 2:
                return cv2.equalizeHist(img)
            ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
            ycrcb[:, :, 0] = cv2.equalizeHist(ycrcb[:, :, 0])
            return cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)
        if filtro == "CLAHE":
            clahe = cv2.createCLAHE(
                clipLimit=max(0.1, p1 / 10),
                tileGridSize=(max(2, int(p2)), max(2, int(p2))),
            )
            if img.ndim == 2:
                return clahe.apply(img)
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            l = clahe.apply(l)
            return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
        if filtro == "Blur":
            k = self.impar(p1)
            return cv2.blur(img, (k, k))
        if filtro == "Gaussian Blur":
            k = self.impar(p1)
            return cv2.GaussianBlur(img, (k, k), 0)
        if filtro == "Median Blur":
            k = self.impar(p1, 3)
            return cv2.medianBlur(img, k)
        if filtro == "Bilateral":
            return cv2.bilateralFilter(img, max(1, int(p1)), float(p2), float(p2))
        if filtro == "Sharpen":
            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
            return cv2.filter2D(img, -1, kernel)
        if filtro == "Sharpen forte":
            kernel = np.array(
                [[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]], dtype=np.float32
            )
            return cv2.filter2D(img, -1, kernel)
        if filtro == "Unsharp Mask":
            k = self.impar(p2)
            blur = cv2.GaussianBlur(img, (k, k), 0)
            forca = max(0.1, p1 / 100.0)
            return cv2.addWeighted(img, 1.0 + forca, blur, -forca, 0)
        if filtro == "Detail Enhance":
            return cv2.detailEnhance(
                self.garantir_bgr(img), sigma_s=float(p1), sigma_r=float(p2) / 100
            )
        if filtro == "Denoise":
            if img.ndim == 2:
                return cv2.fastNlMeansDenoising(img, None, float(p1), 7, 21)
            return cv2.fastNlMeansDenoisingColored(
                img, None, float(p1), float(p1), 7, 21
            )
        if filtro == "Canny":
            return cv2.Canny(self.cinza(img), int(min(p1, p2)), int(max(p1, p2)))
        if filtro == "Sobel X":
            sobel = cv2.Sobel(self.cinza(img), cv2.CV_64F, 1, 0, ksize=3)
            return cv2.convertScaleAbs(sobel)
        if filtro == "Sobel Y":
            sobel = cv2.Sobel(self.cinza(img), cv2.CV_64F, 0, 1, ksize=3)
            return cv2.convertScaleAbs(sobel)
        if filtro == "Sobel XY":
            gray = self.cinza(img)
            sx = cv2.convertScaleAbs(cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3))
            sy = cv2.convertScaleAbs(cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3))
            return cv2.addWeighted(sx, 0.5, sy, 0.5, 0)
        if filtro == "Laplacian":
            lap = cv2.Laplacian(self.cinza(img), cv2.CV_64F)
            return cv2.convertScaleAbs(lap)
        if filtro == "Emboss":
            kernel = np.array([[-2, -1, 0], [-1, 1, 1], [0, 1, 2]], dtype=np.float32)
            tmp = cv2.filter2D(self.garantir_bgr(img), cv2.CV_16S, kernel)
            return np.clip(tmp.astype(np.float32) + 128, 0, 255).astype(np.uint8)
        if filtro == "Sketch":
            gray = self.cinza(img)
            invertida = cv2.bitwise_not(gray)
            blur = cv2.GaussianBlur(invertida, (21, 21), 0)
            return cv2.divide(gray, cv2.bitwise_not(blur), scale=256.0)
        if filtro == "Cartoon":
            cor = self.garantir_bgr(img)
            gray = cv2.cvtColor(cor, cv2.COLOR_BGR2GRAY)
            gray = cv2.medianBlur(gray, 7)
            edges = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 9
            )
            smooth = cv2.bilateralFilter(cor, 9, 200, 200)
            return cv2.bitwise_and(smooth, smooth, mask=edges)
        if filtro == "Pixelizar":
            h, w = img.shape[:2]
            fator = max(2, int(p1))
            pequeno = cv2.resize(
                img,
                (max(1, w // fator), max(1, h // fator)),
                interpolation=cv2.INTER_LINEAR,
            )
            return cv2.resize(pequeno, (w, h), interpolation=cv2.INTER_NEAREST)
        if filtro == "Flip horizontal":
            return cv2.flip(img, 1)
        if filtro == "Flip vertical":
            return cv2.flip(img, 0)
        if filtro == "Flip completo":
            return cv2.flip(img, -1)
        if filtro == "Rotacionar 90°":
            return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        if filtro == "Rotacionar -90°":
            return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if filtro == "Rotacionar 180°":
            return cv2.rotate(img, cv2.ROTATE_180)
        if filtro == "Rotação livre":
            h, w = img.shape[:2]
            centro = (w / 2.0, h / 2.0)
            matriz = cv2.getRotationMatrix2D(centro, p1, 1.0)
            cos = abs(matriz[0, 0])
            sin = abs(matriz[0, 1])
            novo_w = int(h * sin + w * cos)
            novo_h = int(h * cos + w * sin)
            matriz[0, 2] += novo_w / 2.0 - centro[0]
            matriz[1, 2] += novo_h / 2.0 - centro[1]
            return cv2.warpAffine(img, matriz, (novo_w, novo_h))
        if filtro == "Reduzir 50%":
            return cv2.resize(
                img,
                (max(1, img.shape[1] // 2), max(1, img.shape[0] // 2)),
                interpolation=cv2.INTER_AREA,
            )
        if filtro == "Aumentar 200%":
            return cv2.resize(img, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        raise ValueError(f"Filtro não implementado: {filtro}")


ENGINE = LegacyFilters()
LEGACY_CATALOG = ENGINE.criar_catalogo_filtros()
processar_filtro = ENGINE.processar_filtro
