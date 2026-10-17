"""Straight-alpha layer composition and geometry, independent of Qt."""

import cv2
import numpy as np

BLEND_MODES = {
    "normal": "Normal",
    "multiply": "Multiplicar",
    "screen": "Tela",
    "overlay": "Sobrepor",
}


def bgra(image):
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or not image.size:
        raise ValueError("A camada precisa de uma imagem válida de 8 bits.")
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    if image.ndim == 3 and image.shape[2] == 4:
        return image.copy()
    raise ValueError("Use camadas em cinza, BGR ou BGRA.")


def layer_rect(params):
    image = params["image"]
    width = int(params.get("width", image.shape[1]))
    height = int(params.get("height", image.shape[0]))
    if width < 1 or height < 1 or width * height > 100_000_000:
        raise ValueError(
            "A camada deve ter dimensões positivas e até 100 milhões de pixels."
        )
    return int(params.get("x", 0)), int(params.get("y", 0)), width, height


def base_layer(image, params):
    source = params.get("image", image)
    if source.shape[:2] != image.shape[:2]:
        raise ValueError("A imagem do fundo deve manter as dimensões do documento.")
    out = bgra(source)
    opacity = float(params.get("opacity", 1)) if params.get("visible", True) else 0.0
    if not np.isfinite(opacity) or not 0 <= opacity <= 1:
        raise ValueError("A opacidade deve estar entre zero e um.")
    out[:, :, 3] = np.rint(out[:, :, 3].astype(np.float32) * opacity).astype(np.uint8)
    return out


def composite_layer(image, params):
    """Source-over with correct premultiplication, clipping and blend modes."""
    out = bgra(image)
    if not params.get("visible", True):
        return out
    x, y, width, height = layer_rect(params)
    opacity = float(params.get("opacity", 1))
    mode = params.get("blend", "normal")
    if not np.isfinite(opacity) or not 0 <= opacity <= 1 or mode not in BLEND_MODES:
        raise ValueError("Opacidade ou modo de mesclagem inválido.")
    left, top = max(0, x), max(0, y)
    right, bottom = min(out.shape[1], x + width), min(out.shape[0], y + height)
    if left >= right or top >= bottom or opacity == 0:
        return out
    source = bgra(params["image"])
    if source.shape[:2] != (height, width):
        # Resample premultiplied color to avoid dark fringes at transparent edges.
        rgba = source.astype(np.float32) / 255
        rgba[:, :, :3] *= rgba[:, :, 3:4]
        rgba = cv2.resize(
            rgba,
            (width, height),
            interpolation=cv2.INTER_AREA
            if width < source.shape[1] and height < source.shape[0]
            else cv2.INTER_LINEAR,
        )
        rgba[:, :, :3] = np.divide(
            rgba[:, :, :3],
            rgba[:, :, 3:4],
            out=np.zeros_like(rgba[:, :, :3]),
            where=rgba[:, :, 3:4] > 1e-7,
        )
        source = np.rint(rgba * 255).clip(0, 255).astype(np.uint8)
    source = source[top - y : bottom - y, left - x : right - x].astype(np.float32) / 255
    target = out[top:bottom, left:right].astype(np.float32) / 255
    foreground, background = source[:, :, :3], target[:, :, :3]
    sa, ba = source[:, :, 3:4] * opacity, target[:, :, 3:4]
    if mode == "multiply":
        mixed = foreground * background
    elif mode == "screen":
        mixed = 1 - (1 - foreground) * (1 - background)
    elif mode == "overlay":
        mixed = np.where(
            background <= 0.5,
            2 * background * foreground,
            1 - 2 * (1 - foreground) * (1 - background),
        )
    else:
        mixed = foreground
    alpha = sa + ba * (1 - sa)
    premultiplied = (
        foreground * sa * (1 - ba) + background * ba * (1 - sa) + mixed * ba * sa
    )
    color = np.divide(
        premultiplied, alpha, out=np.zeros_like(premultiplied), where=alpha > 1e-7
    )
    out[top:bottom, left:right] = (
        np.rint(np.concatenate((color, alpha), axis=2) * 255)
        .clip(0, 255)
        .astype(np.uint8)
    )
    return out


def layer_transform(original_shape, operations, index):
    """Map this layer's insertion coordinates through later canvas geometry."""
    from .filters import output_size

    width, height = output_size(original_shape, operations[: index + 1])
    transform = np.eye(3)
    for op in operations[index + 1 :]:
        if op.intensity == 0:
            continue
        kind, p = op.kind, op.params
        if kind == "raster":
            return None  # A scientific raster replaces all preceding content.
        if kind == "filter":
            name = p.get("name")
            if name in (
                "Rotacionar 90°",
                "Rotacionar -90°",
                "Rotacionar 180°",
                "Rotação livre",
            ):
                kind = "rotate"
                p = {
                    "angle": {
                        "Rotacionar 90°": 90,
                        "Rotacionar -90°": -90,
                        "Rotacionar 180°": 180,
                    }.get(name, -float(p.get("p1", 30))),
                    "legacy_free": name == "Rotação livre",
                }
            elif name in ("Flip horizontal", "Flip vertical", "Flip completo"):
                kind, p = (
                    "flip",
                    {
                        "axis": "horizontal"
                        if name.endswith("horizontal")
                        else "vertical"
                        if name.endswith("vertical")
                        else "both"
                    },
                )
            elif name in ("Reduzir 50%", "Aumentar 200%"):
                factor = 0.5 if name == "Reduzir 50%" else 2
                kind, p = (
                    "resize",
                    {
                        "width": max(1, int(width * factor)),
                        "height": max(1, int(height * factor)),
                    },
                )
            elif name == "Split BGR":
                return None
        step = np.eye(3)
        if kind == "resize":
            nw, nh = int(p["width"]), int(p["height"])
            step[0, 0], step[1, 1] = nw / width, nh / height
            width, height = nw, nh
        elif kind == "crop":
            x, y, width, height = p["rect"]
            step[0, 2], step[1, 2] = -x, -y
        elif kind == "flip":
            axis = p.get("axis", "horizontal")
            if axis in ("horizontal", "both"):
                step[0, 0], step[0, 2] = -1, width - 1
            if axis in ("vertical", "both"):
                step[1, 1], step[1, 2] = -1, height - 1
        elif kind == "rotate":
            angle = float(p.get("angle", 90)) % 360
            if p.get("legacy_free"):
                matrix = cv2.getRotationMatrix2D((width / 2, height / 2), -angle, 1)
                nw = max(1, int(height * abs(matrix[0, 1]) + width * abs(matrix[0, 0])))
                nh = max(1, int(height * abs(matrix[0, 0]) + width * abs(matrix[0, 1])))
                step[:2] = matrix
                step[0, 2] += (nw - width) / 2
                step[1, 2] += (nh - height) / 2
                width, height = nw, nh
            elif angle == 90:
                step = np.array(
                    [[0, -1, height - 1], [1, 0, 0], [0, 0, 1]], dtype=float
                )
                width, height = height, width
            elif angle == 270:
                step = np.array([[0, 1, 0], [-1, 0, width - 1], [0, 0, 1]], dtype=float)
                width, height = height, width
            elif angle == 180:
                step = np.array(
                    [[-1, 0, width - 1], [0, -1, height - 1], [0, 0, 1]], dtype=float
                )
            elif angle:
                a = np.deg2rad(angle)
                nw = max(
                    1, int(np.ceil(height * abs(np.sin(a)) + width * abs(np.cos(a))))
                )
                nh = max(
                    1, int(np.ceil(height * abs(np.cos(a)) + width * abs(np.sin(a))))
                )
                step[:2] = cv2.getRotationMatrix2D((width / 2, height / 2), -angle, 1)
                step[0, 2] += nw / 2 - width / 2
                step[1, 2] += nh / 2 - height / 2
                width, height = nw, nh
        transform = step @ transform
    return transform
