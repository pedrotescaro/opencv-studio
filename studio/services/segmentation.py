"""Fluxo de segmentação por ROI, sementes morfológicas e GrabCut."""

import cv2
import numpy as np

PADRAO = dict(
    bilateral_d=7,
    sigma_cor=50,
    sigma_espaco=50,
    kernel=5,
    erosao=2,
    dilatacao=2,
    iteracoes=5,
    fechamento=3,
    fechamento_iteracoes=1,
    area_minima=50,
    maior_componente=False,
)
ETAPAS = (
    "Original / ROI",
    "1. Bilateral",
    "3. Sementes",
    "4. Rótulos GrabCut",
    "5. Máscara binária",
    "6. Fechamento",
    "7. Componentes",
    "9. Sobreposição",
)
PINCEIS = {
    "Navegar": None,
    "Objeto certo": cv2.GC_FGD,
    "Fundo certo": cv2.GC_BGD,
    "Objeto provável": cv2.GC_PR_FGD,
    "Fundo provável": cv2.GC_PR_BGD,
}
CORES_SEMENTES = np.array(
    [[0, 0, 0], [255, 255, 255], [210, 80, 20], [0, 220, 255]], np.uint8
)


def validar_parametros(opcoes):
    p = dict(PADRAO, **opcoes)
    limites = {
        "bilateral_d": (1, 31),
        "sigma_cor": (1, 255),
        "sigma_espaco": (1, 255),
        "kernel": (1, 99),
        "erosao": (0, 30),
        "dilatacao": (0, 30),
        "iteracoes": (1, 20),
        "fechamento": (1, 99),
        "fechamento_iteracoes": (0, 30),
        "area_minima": (1, 1000000000),
    }
    for chave, (baixo, alto) in limites.items():
        try:
            valor = int(p[chave])
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f"Valor inválido para {chave}.") from None
        if str(valor) != str(p[chave]) or not baixo <= valor <= alto:
            raise ValueError(f"{chave}: use um inteiro entre {baixo} e {alto}.")
        p[chave] = valor
    for chave in ("bilateral_d", "kernel", "fechamento"):
        if p[chave] % 2 != 1:
            raise ValueError(f"{chave}: use um tamanho ímpar.")
    if not isinstance(p["maior_componente"], bool):
        raise ValueError("A opção de maior componente deve ser booleana.")
    return p


def criar_sementes(roi, kernel=5, erosao=2, dilatacao=2, correcoes=None):
    if roi.ndim != 2 or not roi.size or (not np.any(roi)):
        raise ValueError("A ROI precisa conter uma região selecionada.")
    binaria = (roi != 0).astype(np.uint8)
    elemento = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel))
    certa = (
        cv2.erode(
            binaria,
            elemento,
            iterations=erosao,
            borderType=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        if erosao
        else binaria.copy()
    )
    entorno = (
        cv2.dilate(binaria, elemento, iterations=dilatacao)
        if dilatacao
        else binaria.copy()
    )
    sementes = np.full(roi.shape, cv2.GC_BGD, np.uint8)
    sementes[entorno != 0] = cv2.GC_PR_BGD
    sementes[binaria != 0] = cv2.GC_PR_FGD
    sementes[certa != 0] = cv2.GC_FGD
    if correcoes is not None:
        if (
            correcoes.shape != roi.shape
            or not np.isin(correcoes, (-1, 0, 1, 2, 3)).all()
        ):
            raise ValueError("Correções incompatíveis com a imagem.")
        marcados = correcoes >= 0
        sementes[marcados] = correcoes[marcados]
    objeto = (sementes == cv2.GC_FGD) | (sementes == cv2.GC_PR_FGD)
    fundo = (sementes == cv2.GC_BGD) | (sementes == cv2.GC_PR_BGD)
    if np.count_nonzero(objeto) < 5 or np.count_nonzero(fundo) < 5:
        raise ValueError(
            "GrabCut precisa de pelo menos cinco pixels de objeto e de fundo. Reduza a ROI ou marque fundo com o pincel."
        )
    return sementes


def limpar_componentes(mascara, area_minima=50, maior_componente=False):
    quantidade, rotulos, estatisticas, _ = cv2.connectedComponentsWithStats(
        (mascara != 0).astype(np.uint8), connectivity=8
    )
    ids = [
        i
        for i in range(1, quantidade)
        if estatisticas[i, cv2.CC_STAT_AREA] >= area_minima
    ]
    if maior_componente and ids:
        ids = [max(ids, key=lambda i: estatisticas[i, cv2.CC_STAT_AREA])]
    limpa = np.zeros(mascara.shape, np.uint8)
    regioes = []
    for i in ids:
        x, y, w, h, area = (int(v) for v in estatisticas[i])
        local = rotulos[y : y + h, x : x + w] == i
        limpa[y : y + h, x : x + w][local] = 255
        regioes.append(
            dict(
                forma="Segmentação",
                limites=(x, y, x + w, y + h),
                pixels=area,
                mascara=local,
                pontos=[],
                inicio=None,
                fim=None,
            )
        )
    return (limpa, regioes, quantidade - 1 - len(ids))


def sobrepor_contornos(imagem, mascara):
    cor = (
        cv2.cvtColor(imagem, cv2.COLOR_GRAY2BGR) if imagem.ndim == 2 else imagem.copy()
    )
    saida = cor.copy()
    objeto = mascara != 0
    saida[objeto] = (0.65 * cor[objeto] + 0.35 * np.array([70, 220, 70])).astype(
        np.uint8
    )
    contornos, _ = cv2.findContours(
        mascara.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(saida, contornos, -1, (0, 255, 255), 1)
    return saida


def segmentar_imagem(imagem, roi, opcoes=None, correcoes=None, progresso=None):
    """Cada etapa usa a resolução original; os argumentos não são modificados."""
    p = validar_parametros(opcoes or {})
    if (
        imagem.dtype != np.uint8
        or imagem.ndim not in (2, 3)
        or (imagem.ndim == 3 and imagem.shape[2] != 3)
    ):
        raise ValueError("Use uma imagem cinza ou BGR de 8 bits.")
    if roi.shape != imagem.shape[:2]:
        raise ValueError("A ROI deve ter as dimensões da imagem.")
    avisar = progresso or (lambda texto: None)
    avisar("1/9 — Suavizando com filtro bilateral")
    cor = cv2.cvtColor(imagem, cv2.COLOR_GRAY2BGR) if imagem.ndim == 2 else imagem
    suavizada = cv2.bilateralFilter(
        cor, p["bilateral_d"], p["sigma_cor"], p["sigma_espaco"]
    )
    avisar("2–3/9 — Preparando ROI, erosão, dilatação e sementes")
    sementes = criar_sementes(roi, p["kernel"], p["erosao"], p["dilatacao"], correcoes)
    rotulos = sementes.copy()
    avisar("4/9 — Segmentando com GrabCut")
    fundo, objeto = (np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64))
    cv2.grabCut(
        suavizada, rotulos, None, fundo, objeto, p["iteracoes"], cv2.GC_INIT_WITH_MASK
    )
    avisar("5/9 — Gerando máscara binária")
    binaria = np.where(
        (rotulos == cv2.GC_FGD) | (rotulos == cv2.GC_PR_FGD), 255, 0
    ).astype(np.uint8)
    avisar("6/9 — Fechamento morfológico")
    elemento = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (p["fechamento"], p["fechamento"])
    )
    fechada = (
        cv2.morphologyEx(
            binaria, cv2.MORPH_CLOSE, elemento, iterations=p["fechamento_iteracoes"]
        )
        if p["fechamento_iteracoes"]
        else binaria.copy()
    )
    fechada[sementes == cv2.GC_BGD] = 0
    fechada[sementes == cv2.GC_FGD] = 255
    avisar("7/9 — Removendo fragmentos por componentes conexos")
    final, regioes, removidos = limpar_componentes(
        fechada, p["area_minima"], p["maior_componente"]
    )
    avisar("8–9/9 — Contando pixels e sobrepondo contornos")
    overlay = sobrepor_contornos(cor, final)
    for i, regiao in enumerate(regioes, 1):
        x, y, _, _ = regiao["limites"]
        cv2.putText(
            overlay,
            str(i),
            (x, max(14, y)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 255),
            1,
        )
    return dict(
        suavizada=suavizada,
        sementes=sementes,
        rotulos=rotulos,
        binaria=binaria,
        fechada=fechada,
        mascara=final,
        sobreposicao=overlay,
        regioes=regioes,
        pixels=int(np.count_nonzero(final)),
        removidos=removidos,
        parametros=p,
    )
