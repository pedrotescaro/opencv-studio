"""Selection masks and pixel edits, independent of the Qt interface."""

import cv2
import numpy as np


def selection_mask(shape, selection):
    h, w = shape[:2]
    if selection is None:
        return np.full((h, w), 255, np.uint8)
    if "mask" in selection:
        mask = np.asarray(selection["mask"])
        if mask.ndim != 2 or mask.dtype != np.uint8 or not mask.size:
            raise ValueError("A seleção precisa de uma máscara de 8 bits válida.")
        return cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR)
    mask = np.zeros((h, w), np.uint8)
    x, y, rw, rh = map(float, selection["rect"])
    sw, sh = selection.get("source_size", (w, h))
    x0, y0 = round(x * w / sw), round(y * h / sh)
    x1, y1 = round((x + rw) * w / sw), round((y + rh) * h / sh)
    x0, x1 = sorted((max(0, min(w, x0)), max(0, min(w, x1))))
    y0, y1 = sorted((max(0, min(h, y0)), max(0, min(h, y1))))
    if x1 <= x0 or y1 <= y0:
        return mask
    if selection.get("shape", "rect") == "ellipse":
        yy, xx = np.ogrid[y0:y1, x0:x1]
        mask[y0:y1, x0:x1] = (
            ((xx + 0.5 - (x0 + x1) / 2) / ((x1 - x0) / 2)) ** 2
            + ((yy + 0.5 - (y0 + y1) / 2) / ((y1 - y0) / 2)) ** 2
            <= 1
        ).astype(np.uint8) * 255
    else:
        mask[y0:y1, x0:x1] = 255
    return mask


def from_mask(mask):
    mask = np.array(mask, dtype=np.uint8, copy=True)
    rect = cv2.boundingRect(mask)
    if rect[2] == 0 or rect[3] == 0:
        return None
    mask.setflags(write=False)
    return dict(
        shape="mask", rect=rect, source_size=(mask.shape[1], mask.shape[0]), mask=mask
    )


def combine(first, second, size, mode):
    if mode == "replace":
        return second
    if first is None:
        return second if mode == "add" else None
    w, h = size
    a = selection_mask((h, w), first).astype(np.int16)
    b = selection_mask((h, w), second) if second else np.zeros((h, w), np.uint8)
    result = {
        "add": lambda: np.maximum(a, b),
        "subtract": lambda: np.maximum(0, a - b),
        "intersect": lambda: np.minimum(a, b),
    }[mode]()
    return from_mask(result)


def modify(selection, size, action, amount=1):
    w, h = size
    mask = selection_mask((h, w), selection)
    radius = max(1, min(200, int(amount)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1,) * 2)
    if action == "invert":
        mask = 255 - mask
    elif action == "expand":
        mask = cv2.dilate(mask, kernel)
    elif action == "contract":
        mask = cv2.erode(mask, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)
    elif action == "border":
        mask = cv2.subtract(
            mask, cv2.erode(mask, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)
        )
    elif action == "smooth":
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    elif action == "feather":
        mask = cv2.GaussianBlur(
            mask, (radius * 6 + 1,) * 2, radius, borderType=cv2.BORDER_CONSTANT
        )
    else:
        raise ValueError("Modificação de seleção desconhecida.")
    return from_mask(mask)


def transform(selection, size, target):
    """Move/resize a selection; clipped portions remain outside the document."""
    x, y, w, h = selection["rect"]
    tx, ty, tw, th = target
    if "mask" not in selection:
        return dict(
            shape=selection.get("shape", "rect"), rect=tuple(target), source_size=size
        )
    matrix = np.array(
        [[tw / w, 0, tx - x * tw / w], [0, th / h, ty - y * th / h]], np.float32
    )
    return from_mask(
        cv2.warpAffine(selection_mask((size[1], size[0]), selection), matrix, size)
    )


def paint_pixels(image, mask, color):
    """Source-over fill; coverage includes feathering and the chosen color alpha."""
    from .layers import bgra

    out = bgra(image)
    sa = mask.astype(np.float32)[..., None] / 255 * color[3] / 255
    ba = out[:, :, 3:4].astype(np.float32) / 255
    alpha = sa + ba * (1 - sa)
    rgb = np.array(color[:3], np.float32) * sa + out[:, :, :3] * ba * (1 - sa)
    rgb = np.divide(rgb, alpha, out=np.zeros_like(rgb), where=alpha > 1e-7)
    return (
        np.rint(np.concatenate((rgb, alpha * 255), axis=2))
        .clip(0, 255)
        .astype(np.uint8)
    )
