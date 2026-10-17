"""Layer editing commands coordinated with the document's existing history."""

from pathlib import Path
from uuid import uuid4
from copy import deepcopy
import numpy as np
from PySide6.QtWidgets import QFileDialog
from studio.document import Operation
from studio.io import read_image
from studio.layers import (
    layer_rect,
    layer_transform,
    blocks_layer_change,
    effective_opacity,
)


class LayerActions:
    def layer_records(self):
        if self.document.original is None:
            return []
        base = dict(
            id="base",
            name="Fundo",
            image=self.document.original,
            opacity=1.0,
            visible=True,
        )
        overlays = []
        for op in self.document.operations:
            if op.kind == "base_layer":
                base.update(op.params)
            elif op.kind == "layer":
                overlays.append(dict(op.params))
        return list(reversed(overlays)) + [base]

    def refresh_layers(self, selected_id=None):
        if not hasattr(self, "layer_panel"):
            return
        self._syncing_layers = True
        try:
            self.layer_panel.set_layers(self.layer_records(), selected_id)
        finally:
            self._syncing_layers = False
        self._sync_layer_overlay()

    def _layer_params(self, layer_id):
        for op in self.document.operations:
            if (op.kind == "base_layer" and layer_id == "base") or (
                op.kind == "layer" and op.params.get("id") == layer_id
            ):
                return dict(op.params)
        if layer_id == "base" and self.document.original is not None:
            return dict(id="base", name="Fundo", opacity=1.0, visible=True)
        return None

    def _with_layer_preview(self, operations):
        if self._layer_preview is None:
            return operations
        layer_id, params = self._layer_preview
        operations = list(operations)
        kind = "base_layer" if layer_id == "base" else "layer"
        replacement = Operation(
            kind, dict(params), "Camada: " + params.get("name", "Fundo")
        )
        for index, op in enumerate(operations):
            if (kind == "base_layer" and op.kind == kind) or (
                op.kind == kind and op.params.get("id") == layer_id
            ):
                operations[index] = replacement
                return operations
        if kind == "base_layer":
            operations.insert(0, replacement)
        return operations

    def preview_layer(self, layer_id, changes):
        if self._syncing_layers or self.document.original is None:
            return
        if self._layer_preview is None and self.has_draft() and not self.apply_draft():
            return
        if self._layer_preview and self._layer_preview[0] != layer_id:
            self.commit_layer_preview()
        params = (
            dict(self._layer_preview[1])
            if self._layer_preview
            else self._layer_params(layer_id)
        )
        if params is None:
            return
        if blocks_layer_change(params, changes):
            self.status("A camada está bloqueada para essa alteração.")
            self.refresh_layers(layer_id)
            return
        if all(params.get(key) == value for key, value in changes.items()):
            return
        params.update(changes)
        try:
            if layer_id != "base":
                layer_rect(params)
            effective_opacity(params)
        except (ValueError, TypeError) as exc:
            self.status(str(exc))
            return
        self._layer_preview = (layer_id, params)
        self._sync_layer_overlay()
        self.changed()

    def commit_layer_preview(self):
        if self._layer_preview is None:
            return
        layer_id, params = self._layer_preview
        operations = self._with_layer_preview(list(self.document.operations))
        self._layer_preview = None
        self.document.set_operations(
            operations, "Editar camada: " + params.get("name", "Fundo")
        )
        self.modified = True
        self._update_history()
        self.layer_panel.select_layer(layer_id)
        self.request_render(False)

    def select_layer(self, layer_id):
        if (
            not self._syncing_layers
            and self._layer_preview
            and self._layer_preview[0] != layer_id
        ):
            self.commit_layer_preview()
        self._sync_layer_overlay()

    def import_layers(self, paths=None):
        if self.stack.currentIndex() != 0:
            self.set_workspace(0)
        if paths is None or isinstance(paths, bool):
            paths, _ = QFileDialog.getOpenFileNames(
                self,
                "Adicionar imagens como camadas",
                "",
                "Imagens (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)",
            )
        if not paths:
            return
        if isinstance(paths, str):
            paths = [paths]
        if self.document.original is not None and not self.apply_draft():
            return
        original, generation = self.document.original, self._load_generation
        self.status("Carregando imagens para as camadas…")

        def loaded(images):
            if (
                self.document.original is not original
                or self._load_generation != generation
            ):
                self.status("Importação ignorada porque o documento foi trocado.")
                return
            if self.document.original is None:
                path, first = images.pop(0)
                self.open_array(first, path)
            operations = list(self.document.operations)
            height, width = self.document.original.shape[:2]
            last_id = "base"
            for path, image in images:
                factor = min(1, width / image.shape[1], height / image.shape[0])
                iw, ih = (
                    max(1, round(image.shape[1] * factor)),
                    max(1, round(image.shape[0] * factor)),
                )
                last_id = uuid4().hex
                params = dict(
                    id=last_id,
                    name=Path(path).stem,
                    image=image,
                    x=(width - iw) // 2,
                    y=(height - ih) // 2,
                    width=iw,
                    height=ih,
                    opacity=1.0,
                    visible=True,
                    blend="normal",
                )
                insertion = max(
                    (
                        i + 1
                        for i, op in enumerate(operations)
                        if op.kind in ("layer", "base_layer")
                    ),
                    default=0,
                )
                operations.insert(
                    insertion, Operation("layer", params, "Camada: " + params["name"])
                )
            if images:
                self.document.set_operations(
                    operations, f"Adicionar {len(images)} camada(s)"
                )
                self.modified = True
                self._update_history()
                self.request_render(False)
            self.layer_dock.show()
            self.layer_dock.raise_()
            self.layer_panel.select_layer(last_id)
            self.status(
                "Camadas adicionadas. Use Mover para arrastar a camada selecionada."
            )

        self._job(lambda: [(str(path), read_image(path)) for path in paths], loaded)

    def reorder_layers(self, ids):
        if self.document.original is None or not self.apply_draft():
            return
        operations = list(self.document.operations)
        by_id = {op.params["id"]: op for op in operations if op.kind == "layer"}
        ordered = [layer_id for layer_id in reversed(ids) if layer_id in by_id]
        if len(ordered) != len(by_id) or len(set(ordered)) != len(ordered):
            self.refresh_layers()
            return
        current = [op.params["id"] for op in operations if op.kind == "layer"]
        if current == ordered:
            self.refresh_layers()
            return
        iterator = iter(ordered)
        operations = [
            by_id[next(iterator)] if op.kind == "layer" else op for op in operations
        ]
        self.document.set_operations(operations, "Reordenar camadas")
        self.modified = True
        self._update_history()
        self.request_render(False)

    def layer_action(self, action, layer_id):
        if action == "new":
            self.new_empty_layer()
            return
        if action == "remove" and (self._layer_params(layer_id) or {}).get(
            "locked", False
        ):
            self.status("Desbloqueie a camada antes de removê-la.")
            return
        if self.document.original is None or not self.apply_draft():
            return
        operations = list(self.document.operations)
        index = next(
            (
                i
                for i, op in enumerate(operations)
                if op.kind == "layer" and op.params.get("id") == layer_id
            ),
            None,
        )
        if action in ("up", "down") and index is not None:
            ids = [r["id"] for r in self.layer_records() if r["id"] != "base"]
            position = ids.index(layer_id)
            target = position + (-1 if action == "up" else 1)
            if 0 <= target < len(ids):
                ids[position], ids[target] = ids[target], ids[position]
                self.reorder_layers(ids)
            return
        if action == "remove" and index is not None:
            operations.pop(index)
            label = "Remover camada"
        elif action == "duplicate":
            params = deepcopy(self._layer_params(layer_id))
            if params is None:
                return
            if layer_id == "base":
                params.update(
                    image=params.get("image", self.document.original),
                    x=0,
                    y=0,
                    width=self.document.original.shape[1],
                    height=self.document.original.shape[0],
                    blend="normal",
                )
            layer_id = uuid4().hex
            params.update(
                id=layer_id,
                locked=False,
                lock_position=False,
                lock_pixels=False,
                lock_alpha=False,
                name=params.get("name", "Camada") + " cópia",
                x=params.get("x", 0) + 20,
                y=params.get("y", 0) + 20,
            )
            insertion = (
                index + 1
                if index is not None
                else max(
                    (
                        i + 1
                        for i, op in enumerate(operations)
                        if op.kind in ("layer", "base_layer")
                    ),
                    default=0,
                )
            )
            operations.insert(
                insertion, Operation("layer", params, "Camada: " + params["name"])
            )
            label = "Duplicar camada"
        else:
            return
        self.document.set_operations(operations, label)
        self.modified = True
        self._update_history()
        self.layer_panel.select_layer(layer_id)
        self.request_render(False)

    def _sync_layer_overlay(self):
        if not hasattr(self, "layer_panel") or self.document.original is None:
            self.canvas.set_layer_rect(None)
            return
        layer_id = self.layer_panel.current_id
        operations = self.all_operations()
        for index, op in enumerate(operations):
            if op.kind == "layer" and op.params.get("id") == layer_id:
                transform = layer_transform(
                    self.document.original.shape, operations, index
                )
                if (
                    transform is None
                    or not op.params.get("visible", True)
                    or blocks_layer_change(op.params, {"x", "y"})
                ):
                    break
                x, y, w, h = layer_rect(op.params)
                corners = transform @ np.array(
                    [[x, x + w, x + w, x], [y, y, y + h, y + h], [1, 1, 1, 1]]
                )
                left, top = corners[:2].min(axis=1)
                right, bottom = corners[:2].max(axis=1)
                self.canvas.set_layer_rect((left, top, right - left, bottom - top))
                return
        self.canvas.set_layer_rect(None)

    def start_layer_drag(self):
        self.commit_layer_preview()
        if self.has_draft() and not self.apply_draft():
            return
        layer_id = self.layer_panel.current_id
        operations = self.document.operations
        index = next(
            (
                i
                for i, op in enumerate(operations)
                if op.kind == "layer" and op.params.get("id") == layer_id
            ),
            None,
        )
        if index is None:
            return
        transform = layer_transform(self.document.original.shape, operations, index)
        if transform is None:
            return
        params = operations[index].params
        if blocks_layer_change(params, {"x", "y"}):
            self._layer_drag = None
            return
        self._layer_drag = (
            layer_id,
            params.get("x", 0),
            params.get("y", 0),
            np.linalg.inv(transform[:2, :2]),
        )

    def move_layer_drag(self, dx, dy):
        if self._layer_drag is not None:
            layer_id, x, y, inverse = self._layer_drag
            local = inverse @ np.array([dx, dy])
            self.preview_layer(
                layer_id, {"x": round(x + local[0]), "y": round(y + local[1])}
            )

    def finish_layer_drag(self, dx, dy):
        self.move_layer_drag(dx, dy)
        self._layer_drag = None
        self.commit_layer_preview()
