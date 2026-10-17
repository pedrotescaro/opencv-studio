"""Apply canvas-space selections to the active layer's original pixel space."""

from uuid import uuid4

import cv2
import numpy as np

from .filters import Operation, output_size
from .layers import bgra, layer_rect, layer_transform, can_edit_pixels
from .selection import paint_pixels, selection_mask


def active_layer(original, operations, layer_id):
    for index, op in enumerate(operations):
        if (layer_id == "base" and op.kind == "base_layer") or (
            op.kind == "layer" and op.params.get("id") == layer_id
        ):
            return index, dict(op.params)
    if layer_id == "base":
        return -1, dict(
            id="base", name="Fundo", image=original, opacity=1.0, visible=True
        )
    raise ValueError("Selecione uma camada para editar.")


def layer_selection(original, operations, layer_id, selection):
    index, params = active_layer(original, operations, layer_id)
    image = params.get("image", original)
    matrix = layer_transform(original.shape, operations, index)
    if matrix is None:
        raise ValueError(
            "Esta camada está antes de um resultado rasterizado. Edite-a antes desse resultado na pilha de edições."
        )
    if layer_id != "base":
        x, y, w, h = layer_rect(params)
        matrix = matrix @ np.array(
            [[w / image.shape[1], 0, x], [0, h / image.shape[0], y], [0, 0, 1]]
        )
    if selection is None:
        mask = np.full(image.shape[:2], 255, np.uint8)
    else:
        w, h = output_size(original.shape, operations)
        stage_mask = selection_mask((h, w), selection)
        mask = cv2.warpAffine(
            stage_mask,
            np.linalg.inv(matrix)[:2],
            (image.shape[1], image.shape[0]),
            flags=cv2.INTER_LINEAR,
        )
    return index, params, bgra(image), mask


def _replace(operations, index, params, layer_id):
    kind = "base_layer" if layer_id == "base" else "layer"
    op = Operation(kind, params, "Camada: " + params.get("name", "Fundo"))
    if index < 0:
        operations.insert(0, op)
        return 0
    operations[index] = op
    return index


def edit_pixels(original, operations, layer_id, selection, action, color=None, width=1):
    operations = list(operations)
    index, params, image, mask = layer_selection(
        original, operations, layer_id, selection
    )
    if not can_edit_pixels(params, action):
        raise ValueError("A camada está bloqueada para editar esses pixels.")
    selected_id = layer_id
    if not np.any(mask):
        raise ValueError("A seleção não alcança a camada ativa.")
    if action in ("copy", "cut"):
        selected = image.copy()
        selected[:, :, 3] = np.rint(
            selected[:, :, 3].astype(np.float32) * mask / 255
        ).astype(np.uint8)
        left, top, w, h = cv2.boundingRect(selected[:, :, 3])
        if w == 0 or h == 0:
            raise ValueError("A área selecionada da camada está transparente.")
        asset = selected[top : top + h, left : left + w].copy()
        asset.setflags(write=False)
        sx = params.get("width", image.shape[1]) / image.shape[1]
        sy = params.get("height", image.shape[0]) / image.shape[0]
        if action == "cut":
            image[:, :, 3] = np.rint(
                image[:, :, 3].astype(np.float32) * (1 - mask.astype(np.float32) / 255)
            ).astype(np.uint8)
            image.setflags(write=False)
            params["image"] = image
            index = _replace(operations, index, params, layer_id)
        selected_id = uuid4().hex
        new = dict(
            id=selected_id,
            name="Seleção de " + params.get("name", "Fundo"),
            image=asset,
            x=round(params.get("x", 0) + left * sx),
            y=round(params.get("y", 0) + top * sy),
            width=max(1, round(w * sx)),
            height=max(1, round(h * sy)),
            opacity=params.get("opacity", 1),
            fill=params.get("fill", 1),
            visible=True,
            blend=params.get("blend", "normal"),
        )
        operations.insert(
            max(0, index + 1), Operation("layer", new, "Camada: " + new["name"])
        )
    else:
        if action == "stroke":
            # Inner stroke: the selected boundary remains inside the selection.
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (width * 2 + 1,) * 2)
            mask = cv2.subtract(
                mask,
                cv2.erode(mask, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0),
            )
        if action == "delete":
            image[:, :, 3] = np.rint(
                image[:, :, 3].astype(np.float32) * (1 - mask.astype(np.float32) / 255)
            ).astype(np.uint8)
        elif action in ("fill", "stroke"):
            alpha = image[:, :, 3].copy() if params.get("lock_alpha", False) else None
            previous = image.copy() if alpha is not None else None
            image = paint_pixels(image, mask, color)
            if alpha is not None:
                image[:, :, 3] = alpha
                image[alpha == 0] = previous[alpha == 0]
        else:
            raise ValueError("Ação de pixels desconhecida.")
        image.setflags(write=False)
        params["image"] = image
        _replace(operations, index, params, layer_id)
    return operations, selected_id
