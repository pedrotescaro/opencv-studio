"""Non-destructive image operations, independent from Qt and widget state.

Matrices use OpenCV's BGR/BGRA convention, always unsigned eight-bit. Alpha is
preserved by photographic filters. Geometry acts on every channel together.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any

import cv2
import numpy as np

from .legacy_filters import LEGACY_CATALOG, PARAMETROS, processar_filtro
from .selection import selection_mask


@dataclass
class Operation:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    name: str = ""
    intensity: float = 1.0
    selection: dict[str, Any] | None = None

    def __deepcopy__(self, memo):
        # History recipes share immutable image operands instead of multiplying
        # full-resolution raster buffers on every edit and undo snapshot.
        def clone(value):
            if isinstance(value, np.ndarray):
                if value.flags.writeable:
                    value = value.copy()
                    value.flags.writeable = False
                return value
            if isinstance(value, dict):
                return {key: clone(item) for key, item in value.items()}
            if isinstance(value, list):
                return [clone(item) for item in value]
            if isinstance(value, tuple):
                return tuple(clone(item) for item in value)
            return deepcopy(value, memo)

        return Operation(
            self.kind,
            clone(self.params),
            self.name,
            self.intensity,
            clone(self.selection),
        )


def _adjustment(label, low, high, default=0.0, step=1.0):
    return dict(label=label, min=low, max=high, default=default, step=step)


ADJUSTMENTS = {
    "brightness": _adjustment("Brilho", -100, 100),
    "contrast": _adjustment("Contraste", -100, 100),
    "exposure": _adjustment("Exposição (EV)", -5, 5, step=0.05),
    "saturation": _adjustment("Saturação", -100, 100),
    "vibrance": _adjustment("Vibração", -100, 100),
    "temperature": _adjustment("Temperatura", -100, 100),
    "hue": _adjustment("Matiz", -180, 180),
    "sharpness": _adjustment("Nitidez", 0, 200),
    "shadows": _adjustment("Sombras", -100, 100),
    "highlights": _adjustment("Luzes", -100, 100),
    "gamma": _adjustment("Gama", 0.1, 3, 1.0, 0.01),
}

FILTERS = deepcopy(LEGACY_CATALOG)
FILTERS["Fotografia"] = [
    "Vinheta",
    "Grão de filme",
    "Glitch / RGB shift",
    "Duotone",
    "HDR",
]
FILTER_PARAMETERS = deepcopy(PARAMETROS)
FILTER_PARAMETERS.update(
    {
        "Preto e branco": [("Limiar", 0, 255, 127)],
        "Threshold adaptativo": [
            ("Bloco (ímpar)", 3, 51, 11),
            ("Constante C", -20, 20, 2),
        ],
        "Solarizar": [("Ponto de inversão", 0, 255, 128)],
        "Posterizar": [("Níveis", 2, 64, 8)],
        "Brilho": [("Brilho", -100, 100, 25)],
        "Contraste": [("Contraste (%)", -80, 200, 35)],
        "Gamma": [("Gama × 100", 10, 300, 100)],
        "Blur": [("Kernel", 1, 51, 5)],
        "Gaussian Blur": [("Kernel", 1, 51, 5)],
        "Median Blur": [("Kernel", 1, 51, 5)],
        "Bilateral": [("Diâmetro", 1, 25, 9), ("Sigma", 10, 200, 75)],
        "Unsharp Mask": [("Força × 100", 10, 300, 120), ("Kernel", 1, 31, 5)],
        "Canny": [("Limiar mínimo", 0, 255, 100), ("Limiar máximo", 0, 255, 200)],
        "Pixelizar": [("Tamanho do pixel", 2, 100, 16)],
        "Rotação livre": [("Ângulo", -180, 180, 30)],
        "Vinheta": [("Escurecimento (%)", 0, 100, 55), ("Raio (%)", 10, 150, 85)],
        "Grão de filme": [("Quantidade", 0, 80, 15), ("Semente", 0, 1000, 42)],
        "Glitch / RGB shift": [("Deslocamento (px)", 0, 100, 8)],
        "Duotone": [
            ("Matiz das sombras", 0, 179, 115),
            ("Matiz das luzes", 0, 179, 22),
        ],
        "HDR": [("Força (%)", 0, 100, 45), ("Detalhe (%)", 0, 100, 35)],
    }
)
from .legacy_filters import MORFOLOGIA

for _name in MORFOLOGIA:
    FILTER_PARAMETERS.setdefault(_name, [("Kernel", 1, 31, 3)])

PRESETS = {
    "Cinematic": dict(
        contrast=18, saturation=-12, temperature=-12, shadows=14, highlights=-22
    ),
    "Vintage": dict(
        contrast=-15, saturation=-20, temperature=24, shadows=20, gamma=1.08
    ),
    "B&W Contrast": dict(saturation=-100, contrast=35, highlights=-10, sharpness=25),
    "Cyberpunk": dict(
        contrast=24, saturation=28, temperature=-30, hue=12, exposure=0.15
    ),
    "Warm Film": dict(
        temperature=28, saturation=-8, shadows=12, highlights=-18, contrast=8
    ),
}

_GEOMETRIC_FILTERS = {
    "Flip horizontal",
    "Flip vertical",
    "Flip completo",
    "Rotacionar 90°",
    "Rotacionar -90°",
    "Rotacionar 180°",
    "Rotação livre",
    "Reduzir 50%",
    "Aumentar 200%",
}


def validate_image(image):
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or not image.size:
        raise ValueError("Use uma imagem não vazia de 8 bits.")
    if image.ndim != 2 and not (image.ndim == 3 and image.shape[2] in (3, 4)):
        raise ValueError("A imagem deve ter um, três ou quatro canais.")
    return image


def bgr(image):
    return (
        cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image[:, :, :3]
    )


def gray(image):
    return (
        image if image.ndim == 2 else cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
    )


def adjustment_defaults():
    return {key: spec["default"] for key, spec in ADJUSTMENTS.items()}


def apply_adjustments(image, params):
    p = adjustment_defaults()
    aliases = {
        "brilho": "brightness",
        "contraste": "contrast",
        "exposicao": "exposure",
        "saturacao": "saturation",
        "vibracao": "vibrance",
        "temperatura": "temperature",
        "matiz": "hue",
        "nitidez": "sharpness",
        "sombras": "shadows",
        "luzes": "highlights",
    }
    for key, value in params.items():
        key = aliases.get(key, key)
        if key in p:
            value = float(value)
            if not np.isfinite(value):
                raise ValueError(f"Ajuste inválido: {key}.")
            spec = ADJUSTMENTS[key]
            p[key] = float(np.clip(value, spec["min"], spec["max"]))
    if p == adjustment_defaults():
        return image.copy()
    out = bgr(image).astype(np.float32) / 255
    out *= 2.0 ** p["exposure"]
    out += p["brightness"] / 255
    out = (out - 0.5) * (1 + p["contrast"] / 100) + 0.5
    out += np.array([-1, 0, 1], np.float32) * p["temperature"] / 500
    out = np.clip(out, 0, 1)
    if p["hue"] or p["saturation"] or p["vibrance"]:
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        hsv[:, :, 0] = (hsv[:, :, 0] + p["hue"]) % 360
        sat = hsv[:, :, 1]
        sat *= 1 + p["saturation"] / 100
        sat *= 1 + p["vibrance"] / 100 * (1 - np.clip(sat, 0, 1))
        hsv[:, :, 1] = np.clip(sat, 0, 1)
        out = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    lum = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)[..., None]
    out += (1 - lum) ** 2 * p["shadows"] / 350
    out += lum**2 * p["highlights"] / 350
    out = np.power(np.clip(out, 0, 1), 1 / p["gamma"])
    if p["sharpness"]:
        blur = cv2.GaussianBlur(out, (0, 0), 1.2)
        out += p["sharpness"] / 100 * (out - blur)
    result = np.rint(np.clip(out, 0, 1) * 255).astype(np.uint8)
    return gray(result) if image.ndim == 2 else result


def histogram(image, space="RGB"):
    """Counts visible pixels; fully transparent pixels do not affect the plot."""
    validate_image(image)
    mask = image[:, :, 3] > 0 if image.ndim == 3 and image.shape[2] == 4 else None
    if space in ("Cinza", "Gray", "GRAY") or image.ndim == 2:
        converted, names = gray(image), ["Cinza"]
    elif space == "HSV":
        converted, names = cv2.cvtColor(bgr(image), cv2.COLOR_BGR2HSV), list("HSV")
    elif space == "RGB":
        converted, names = cv2.cvtColor(bgr(image), cv2.COLOR_BGR2RGB), list("RGB")
    else:
        raise ValueError("Modelo de histograma inválido.")
    channels = [converted] if converted.ndim == 2 else cv2.split(converted)
    return {
        name: np.bincount(
            channel[mask] if mask is not None else channel.ravel(),
            minlength=180 if name == "H" else 256,
        )
        for name, channel in zip(names, channels)
    }


def grow_region(image, seed, tolerance=15, connectivity=4):
    source = bgr(image)
    h, w = source.shape[:2]
    x, y = map(int, seed)
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError("A semente deve estar dentro da imagem.")
    if connectivity not in (4, 8) or not 0 <= float(tolerance) <= 255:
        raise ValueError("Use tolerância 0–255 e conectividade 4 ou 8.")
    mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = (
        int(connectivity)
        | cv2.FLOODFILL_FIXED_RANGE
        | cv2.FLOODFILL_MASK_ONLY
        | (255 << 8)
    )
    cv2.floodFill(
        source.copy(),
        mask,
        (x, y),
        0,
        (float(tolerance),) * 3,
        (float(tolerance),) * 3,
        flags,
    )
    return mask[1:-1, 1:-1].copy()


def _photographic_filter(image, name, p1, p2):
    if name == "Vinheta":
        h, w = image.shape[:2]
        yy, xx = np.ogrid[-1 : 1 : complex(h), -1 : 1 : complex(w)]
        distance = (xx**2 + yy**2) / max(0.05, float(p2) / 100) ** 2
        weight = 1 - np.clip(distance / 2, 0, 1) * float(p1) / 100
        return (
            np.rint(
                image.astype(np.float32)
                * (weight[..., None] if image.ndim == 3 else weight)
            )
            .clip(0, 255)
            .astype(np.uint8)
        )
    if name == "Grão de filme":
        noise = np.random.default_rng(int(p2)).normal(0, float(p1), image.shape[:2])
        return (
            np.rint(
                image.astype(float) + (noise[..., None] if image.ndim == 3 else noise)
            )
            .clip(0, 255)
            .astype(np.uint8)
        )
    if name == "Glitch / RGB shift":
        out = bgr(image).copy()
        shift = min(out.shape[1] - 1, max(0, round(p1)))
        # Replicated edge pixels avoid artificial wraparound on the frame edges.
        xs = np.arange(out.shape[1])
        out[:, :, 0] = out[:, np.clip(xs - shift, 0, len(xs) - 1), 0]
        out[:, :, 2] = out[:, np.clip(xs + shift, 0, len(xs) - 1), 2]
        return out
    if name == "Duotone":
        colors = cv2.cvtColor(
            np.array([[[int(p1) % 180, 190, 95], [int(p2) % 180, 100, 255]]], np.uint8),
            cv2.COLOR_HSV2BGR,
        )[0].astype(float)
        t = gray(image).astype(float)[..., None] / 255
        return np.rint(colors[0] * (1 - t) + colors[1] * t).astype(np.uint8)
    if name == "HDR":
        lab = cv2.cvtColor(bgr(image), cv2.COLOR_BGR2LAB)
        local = cv2.createCLAHE(
            clipLimit=1 + float(p1) / 25, tileGridSize=(8, 8)
        ).apply(lab[:, :, 0])
        lab[:, :, 0] = cv2.addWeighted(lab[:, :, 0], 0.5, local, 0.5, 0)
        out = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        blur = cv2.GaussianBlur(out, (0, 0), 2)
        return cv2.addWeighted(out, 1 + float(p2) / 100, blur, -float(p2) / 100, 0)
    raise ValueError(f"Filtro desconhecido: {name}")


def _rotate(image, angle):
    angle = float(angle) % 360
    if abs(angle) < 1e-7:
        return image.copy()
    for value, code in (
        (90, cv2.ROTATE_90_CLOCKWISE),
        (180, cv2.ROTATE_180),
        (270, cv2.ROTATE_90_COUNTERCLOCKWISE),
    ):
        if abs(angle - value) < 1e-7:
            return cv2.rotate(image, code)
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1)
    nw = max(1, int(np.ceil(h * abs(matrix[0, 1]) + w * abs(matrix[0, 0]))))
    nh = max(1, int(np.ceil(h * abs(matrix[0, 0]) + w * abs(matrix[0, 1]))))
    matrix[0, 2] += (nw - w) / 2
    matrix[1, 2] += (nh - h) / 2
    return cv2.warpAffine(
        image,
        matrix,
        (nw, nh),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def _core_operation(image, operation):
    p, kind = operation.params, operation.kind
    if kind == "adjustments":
        return apply_adjustments(image, p)
    if kind == "preset":
        return apply_adjustments(image, PRESETS[p["name"]])
    if kind == "filter":
        name = p["name"]
        specs = FILTER_PARAMETERS.get(name, [])
        p1 = float(p.get("p1", specs[0][3] if specs else 50))
        p2 = float(p.get("p2", specs[1][3] if len(specs) > 1 else 100))
        if name in FILTERS["Fotografia"]:
            return _photographic_filter(image, name, p1, p2)
        return processar_filtro(image, name, p1, p2, p.get("morphology"))
    if kind == "curves":
        points = np.asarray(p.get("points", [(0, 0), (255, 255)]), np.float64)
        if (
            points.ndim != 2
            or points.shape[1] != 2
            or len(points) < 2
            or not np.isfinite(points).all()
        ):
            raise ValueError("A curva precisa de pelo menos dois pontos válidos.")
        points = points[np.argsort(points[:, 0], kind="stable")]
        if np.any(np.diff(points[:, 0]) <= 0):
            raise ValueError("Pontos da curva devem ter entradas distintas.")
        lut = (
            np.rint(np.interp(np.arange(256), points[:, 0], points[:, 1]))
            .clip(0, 255)
            .astype(np.uint8)
        )
        out = image.copy()
        channel = p.get("channel", "RGB")
        if channel in ("R", "G", "B") and out.ndim == 3:
            idx = {"R": 2, "G": 1, "B": 0}[channel]
            out[:, :, idx] = cv2.LUT(out[:, :, idx], lut)
            return out
        return cv2.LUT(image, lut)
    if kind == "levels":
        black, white, gamma = (
            float(p.get("black", 0)),
            float(p.get("white", 255)),
            float(p.get("gamma", 1)),
        )
        if not np.isfinite((black, white, gamma)).all() or white <= black or gamma <= 0:
            raise ValueError(
                "O ponto branco deve superar o preto; gama deve ser positiva."
            )
        normalized = np.clip((image.astype(float) - black) / (white - black), 0, 1)
        return np.rint(normalized ** (1 / gamma) * 255).astype(np.uint8)
    if kind == "crop":
        x, y, w, h = map(int, p["rect"])
        ih, iw = image.shape[:2]
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > iw or y + h > ih:
            raise ValueError(
                "O recorte deve estar dentro da imagem e ter área positiva."
            )
        return image[y : y + h, x : x + w].copy()
    if kind == "resize":
        w, h = int(p["width"]), int(p["height"])
        if min(w, h) < 1 or w * h > 100_000_000:
            raise ValueError("Use dimensões positivas e até 100 milhões de pixels.")
        return cv2.resize(
            image,
            (w, h),
            interpolation=cv2.INTER_AREA
            if w <= image.shape[1] and h <= image.shape[0]
            else cv2.INTER_CUBIC,
        )
    if kind == "rotate":
        return _rotate(image, p.get("angle", 90))
    if kind == "flip":
        return cv2.flip(
            image, {"horizontal": 1, "vertical": 0, "both": -1}.get(p.get("axis"), 1)
        )
    if kind == "text":
        from PIL import Image, ImageDraw, ImageFont
        from pathlib import Path

        text = str(p.get("text", ""))
        if not text:
            raise ValueError("Digite o texto a inserir.")
        size = max(1, round(float(p.get("size", 32))))
        fonts = (
            "C:/Windows/Fonts/segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
        font = next(
            (ImageFont.truetype(path, size) for path in fonts if Path(path).is_file()),
            None,
        )
        if font is None:
            font = ImageFont.load_default(size=size)
        color = tuple(
            int(np.clip(v, 0, 255)) for v in p.get("color", (255, 255, 255))[:3]
        )[::-1]
        canvas = Image.fromarray(cv2.cvtColor(bgr(image), cv2.COLOR_BGR2RGB))
        ImageDraw.Draw(canvas).text(
            (int(p.get("x", 20)), int(p.get("y", 50))),
            text,
            font=font,
            fill=color,
            anchor="ls",
        )
        return cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)
    if kind == "arithmetic":
        other = validate_image(p.get("image", p.get("second")))
        other = cv2.resize(
            bgr(other), (image.shape[1], image.shape[0]), interpolation=cv2.INTER_AREA
        )
        source = bgr(image)
        mode = p.get("mode", p.get("operation", "add"))
        if mode in ("add", "soma", "Adicionar"):
            return cv2.add(source, other)
        if mode in ("subtract", "sub", "subtrair", "Subtrair"):
            return cv2.subtract(source, other)
        if mode in ("blend", "Misturar"):
            weight = float(np.clip(p.get("weight", 0.5), 0, 1))
            return cv2.addWeighted(source, 1 - weight, other, weight, 0)
        raise ValueError("Operação aritmética inválida.")
    if kind == "region":
        mask = grow_region(
            image,
            p.get("seed", (0, 0)),
            p.get("tolerance", 15),
            int(p.get("connectivity", 4)),
        )
        if p.get("output", "mask") == "overlay":
            out = bgr(image).copy()
            out[mask > 0] = np.rint(
                0.55 * out[mask > 0] + 0.45 * np.array([40, 190, 255])
            ).astype(np.uint8)
            return out
        return mask
    if kind == "quantize":
        levels = int(p.get("levels", 8))
        if not 2 <= levels <= 256:
            raise ValueError("Escolha de 2 a 256 níveis por canal.")
        return np.rint(
            np.floor(image.astype(np.float32) * levels / 256) * 255 / (levels - 1)
        ).astype(np.uint8)
    if kind == "color_model":
        model = p.get("model", "RGB")
        if model == "RGB":
            return cv2.cvtColor(bgr(image), cv2.COLOR_BGR2RGB)
        if model == "HSV":
            return cv2.cvtColor(bgr(image), cv2.COLOR_BGR2HSV)
        if model in ("Gray", "Cinza"):
            return gray(image)
        raise ValueError("Modelo de cor inválido.")
    if kind == "mask":
        mask = np.asarray(p["mask"], np.uint8)
        if mask.shape != image.shape[:2]:
            mask = cv2.resize(
                mask, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST
            )
        return cv2.bitwise_and(bgr(image), bgr(image), mask=mask)
    if kind == "raster":
        return validate_image(p["image"]).copy()
    raise ValueError(f"Operação desconhecida: {kind}")


def apply_operation(image, operation):
    validate_image(image)
    if not isinstance(operation, Operation):
        raise TypeError("Use uma Operation para modificar a imagem.")
    intensity = float(operation.intensity)
    if not np.isfinite(intensity) or not 0 <= intensity <= 1:
        raise ValueError("A intensidade deve estar entre zero e um.")
    if intensity == 0:
        return image.copy()
    if operation.kind in ("layer", "base_layer"):
        from .layers import composite_layer, base_layer

        return (composite_layer if operation.kind == "layer" else base_layer)(
            image, operation.params
        )
    geometry = operation.kind in ("crop", "resize", "rotate", "flip", "raster") or (
        operation.kind == "filter"
        and operation.params.get("name") in _GEOMETRIC_FILTERS
    )
    alpha = image[:, :, 3] if image.ndim == 3 and image.shape[2] == 4 else None
    source = image if geometry else image[:, :, :3] if alpha is not None else image
    out = _core_operation(source, operation)
    if alpha is not None and not geometry:
        if out.shape[:2] != alpha.shape:
            # Split BGR creates a contact sheet; repeat the same transparency.
            if (
                operation.kind == "filter"
                and operation.params.get("name") == "Split BGR"
            ):
                alpha = np.tile(alpha, (2, 2))
            else:
                alpha = cv2.resize(
                    alpha, (out.shape[1], out.shape[0]), interpolation=cv2.INTER_NEAREST
                )
        out = np.dstack((bgr(out), alpha))
    if intensity == 1 and operation.selection is None:
        return np.ascontiguousarray(out)
    if out.shape[:2] != image.shape[:2]:
        if operation.selection is not None:
            raise ValueError(
                "Não aplique operações que mudam dimensões apenas à seleção."
            )
        # A transform has no meaningful fractional geometry; the result is exact.
        return np.ascontiguousarray(out)
    base = image
    if out.shape != base.shape:
        base = bgr(base)
        out = bgr(out)
    weight = np.full(image.shape[:2], intensity, np.float32)
    if operation.selection is not None:
        weight *= selection_mask(image.shape, operation.selection) / 255
    if base.ndim == 3:
        weight = weight[..., None]
    result = (
        np.rint(
            base.astype(np.float32) * (1 - weight) + out.astype(np.float32) * weight
        )
        .clip(0, 255)
        .astype(np.uint8)
    )
    return np.ascontiguousarray(result)


def render_pipeline(original, operations, max_size=None):
    """Rebuild from immutable source; preview geometry uses the same coordinates.

    Reduced previews approximate spatial kernels, while full-resolution rendering
    always replays the exact stored operations and is used for export.
    """
    validate_image(original)
    image = original.copy()
    scale = 1.0
    if max_size is not None:
        if int(max_size) < 1:
            raise ValueError("A dimensão da prévia deve ser positiva.")
        # Include resulting geometry before allocation: resizing a small source
        # to a huge canvas must still render a bounded preview in the worker.
        target_width, target_height = output_size(
            original.shape, operations, _largest=True
        )
        scale = min(
            1.0, float(max_size) / max(*image.shape[:2], target_width, target_height)
        )
        if scale < 1:
            image = cv2.resize(
                image,
                (
                    max(1, round(image.shape[1] * scale)),
                    max(1, round(image.shape[0] * scale)),
                ),
                interpolation=cv2.INTER_AREA,
            )
    for operation in operations:
        op = operation
        if scale < 1:
            p = dict(operation.params)
            if op.kind == "crop":
                x, y, w, h = p["rect"]
                ix, iy = round(x * scale), round(y * scale)
                ex, ey = round((x + w) * scale), round((y + h) * scale)
                p["rect"] = (
                    ix,
                    iy,
                    max(1, min(image.shape[1], ex) - ix),
                    max(1, min(image.shape[0], ey) - iy),
                )
            elif op.kind == "resize":
                p["width"], p["height"] = (
                    max(1, round(p["width"] * scale)),
                    max(1, round(p["height"] * scale)),
                )
            elif op.kind == "layer":
                raster = p["image"]
                p["width"] = max(1, round(p.get("width", raster.shape[1]) * scale))
                p["height"] = max(1, round(p.get("height", raster.shape[0]) * scale))
                p["x"] = round(p.get("x", 0) * scale)
                p["y"] = round(p.get("y", 0) * scale)
            elif op.kind == "text":
                for key in ("x", "y", "size"):
                    if key in p:
                        p[key] = float(p[key]) * scale
            elif op.kind == "region":
                x, y = p.get("seed", (0, 0))
                p["seed"] = (
                    min(image.shape[1] - 1, round(x * scale)),
                    min(image.shape[0] - 1, round(y * scale)),
                )
            elif op.kind == "base_layer" and "image" in p:
                raster = p["image"]
                p["image"] = cv2.resize(
                    raster,
                    (image.shape[1], image.shape[0]),
                    interpolation=cv2.INTER_AREA,
                )
            elif op.kind == "raster":
                raster = validate_image(p["image"])
                p["image"] = cv2.resize(
                    raster,
                    (
                        max(1, round(raster.shape[1] * scale)),
                        max(1, round(raster.shape[0] * scale)),
                    ),
                    interpolation=cv2.INTER_AREA,
                )
            op = replace(operation, params=p)
        image = apply_operation(image, op)
    if max_size is not None and max(image.shape[:2]) > max_size:
        factor = max_size / max(image.shape[:2])
        image = cv2.resize(
            image,
            (
                max(1, round(image.shape[1] * factor)),
                max(1, round(image.shape[0] * factor)),
            ),
            interpolation=cv2.INTER_AREA,
        )
    return image


histograms = histogram


def output_size(original_shape, operations, *, _largest=False):
    """Return full-resolution (width, height) without running pixel filters."""
    h, w = map(int, original_shape[:2])
    largest_w, largest_h = w, h
    for operation in operations:
        p, kind = operation.params, operation.kind
        if operation.intensity == 0:
            continue
        if kind == "resize":
            w, h = int(p["width"]), int(p["height"])
        elif kind == "crop":
            w, h = int(p["rect"][2]), int(p["rect"][3])
        elif kind == "raster":
            h, w = p["image"].shape[:2]
        elif kind == "rotate":
            angle = float(p.get("angle", 90)) % 360
            if angle in (90, 270):
                w, h = h, w
            elif angle not in (0, 180):
                a = np.deg2rad(angle)
                w, h = (
                    max(1, int(np.ceil(h * abs(np.sin(a)) + w * abs(np.cos(a))))),
                    max(1, int(np.ceil(h * abs(np.cos(a)) + w * abs(np.sin(a))))),
                )
        elif kind == "filter":
            name = p.get("name")
            if name in ("Rotacionar 90°", "Rotacionar -90°"):
                w, h = h, w
            elif name == "Reduzir 50%":
                w, h = max(1, w // 2), max(1, h // 2)
            elif name in ("Aumentar 200%", "Split BGR"):
                w, h = w * 2, h * 2
            elif name == "Rotação livre":
                a = np.deg2rad(float(p.get("p1", 30)))
                w, h = (
                    max(1, int(h * abs(np.sin(a)) + w * abs(np.cos(a)))),
                    max(1, int(h * abs(np.cos(a)) + w * abs(np.sin(a)))),
                )
        largest_w, largest_h = max(largest_w, w), max(largest_h, h)
    return (int(largest_w), int(largest_h)) if _largest else (int(w), int(h))
