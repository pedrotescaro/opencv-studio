"""Functional image context menu and commands for selections and active layers."""

from uuid import uuid4

import cv2
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QInputDialog,
    QMenu,
    QSpinBox,
)

from studio.document import Operation
from studio.io import read_image, write_image
from studio.layers import layer_transform, can_edit_pixels, blocks_layer_change
from studio.selection import from_mask, modify, selection_mask
from studio.selection_edits import active_layer, edit_pixels

from .theme import icon


class SelectionActions:
    def build_canvas_menu(self):
        """Build fresh action states; the same actions work from the Edit menu."""
        menu = QMenu(self.canvas)
        menu.setObjectName("canvasContextMenu")
        has_image = (
            self.document.original is not None and self.stack.currentIndex() == 0
        )
        selected = self.canvas.selection is not None
        editable = self._active_layer_editable()

        def action(parent, text, slot, name, enabled=True, shortcut=None):
            item = parent.addAction(icon(name), text)
            item.setIconVisibleInMenu(True)
            item.setEnabled(has_image and enabled)
            if shortcut:
                # Display hints here; global shortcuts are registered only once.
                item.setText(text + "\t" + shortcut)
            item.triggered.connect(slot)
            return item

        action(
            menu,
            "Desselecionar",
            self.canvas.clear_selection,
            "deselect",
            selected,
            "Ctrl+D",
        )
        action(menu, "Selecionar tudo", self.select_all, "rect", shortcut="Ctrl+A")
        action(
            menu,
            "Inverter seleção",
            lambda: self.modify_selection("invert"),
            "invert_selection",
            selected,
            "Ctrl+Shift+I",
        )
        modifier = menu.addMenu(icon("selection_modify"), "Modificar")
        modifier.setEnabled(has_image and selected)
        for text, command in (
            ("Expandir…", "expand"),
            ("Contrair…", "contract"),
            ("Borda…", "border"),
            ("Suavizar…", "smooth"),
            ("Difusão / suavizar arestas…", "feather"),
        ):
            action(
                modifier,
                text,
                lambda checked=False, cmd=command: self.modify_selection(cmd),
                "selection_modify",
            )
        action(
            menu,
            "Refinar arestas…",
            self.refine_selection_dialog,
            "edges",
            selected,
        )
        menu.addSeparator()
        action(menu, "Salvar seleção…", self.save_selection, "save", selected)
        action(menu, "Carregar seleção…", self.load_selection, "open")
        menu.addSeparator()
        action(
            menu,
            "Camada via cópia",
            lambda: self.edit_selection_pixels("copy"),
            "duplicate",
            selected and editable,
            "Ctrl+J",
        )
        action(
            menu,
            "Camada por corte",
            lambda: self.edit_selection_pixels("cut"),
            "cut",
            selected and editable and self._active_layer_writable("cut"),
            "Ctrl+Shift+J",
        )
        action(
            menu,
            "Nova camada transparente",
            self.new_empty_layer,
            "new_layer",
            shortcut="Ctrl+Shift+N",
        )
        action(menu, "Adicionar imagem como camada…", self.import_layers, "layers")
        menu.addSeparator()
        action(
            menu,
            "Transformação livre da camada…",
            self.transform_layer_dialog,
            "resize",
            editable
            and self.layer_panel.current_id != "base"
            and not blocks_layer_change(
                self._layer_params(self.layer_panel.current_id) or {}, {"x", "width"}
            ),
            "Ctrl+T",
        )
        action(
            menu,
            "Transformar seleção",
            self.canvas.begin_selection_transform,
            "selection_transform",
            selected,
        )
        menu.addSeparator()
        action(
            menu,
            "Preencher…",
            lambda: self.edit_selection_pixels("fill"),
            "fill",
            editable and self._active_layer_writable("fill"),
        )
        action(
            menu,
            "Traçar contorno…",
            lambda: self.edit_selection_pixels("stroke"),
            "stroke",
            selected and editable and self._active_layer_writable("stroke"),
        )
        action(
            menu,
            "Apagar pixels",
            lambda: self.edit_selection_pixels("delete"),
            "discard",
            selected and editable and self._active_layer_writable("delete"),
            "Delete",
        )
        return menu

    def _populate_selection_menu(self, menu):
        menu.clear()
        context = self.build_canvas_menu()
        menu.addActions(context.actions())
        previous = getattr(self, "_selection_menu_contents", None)
        self._selection_menu_contents = context
        if previous is not None:
            previous.deleteLater()

    def show_canvas_menu(self, position):
        if self.canvas._selection_transform:
            self.canvas.end_selection_transform()
        menu = self.build_canvas_menu()
        menu.exec(position)
        menu.deleteLater()

    def _active_layer_editable(self):
        if self.document.original is None or self.stack.currentIndex() != 0:
            return False
        try:
            index, _ = active_layer(
                self.document.original,
                self.document.operations,
                self.layer_panel.current_id or "base",
            )
            return (
                layer_transform(
                    self.document.original.shape, self.document.operations, index
                )
                is not None
            )
        except (ValueError, KeyError):
            return False

    def _active_layer_writable(self, action):
        return can_edit_pixels(
            self._layer_params(self.layer_panel.current_id or "base") or {}, action
        )

    def select_all(self):
        if self.document.original is None or self.stack.currentIndex() != 0:
            return
        w, h = self.canvas.source_size
        self.canvas.selection = dict(
            shape="rect", rect=(0, 0, w, h), source_size=(w, h)
        )

    def _selection_job(self, task, ready):
        original = self.document.original
        entry = self.document.history.entries[self.document.history.index]
        selection = self.canvas._selection
        generation = self._load_generation

        def guarded(result):
            if (
                self.document.original is original
                and self._load_generation == generation
                and self.document.history.entries[self.document.history.index] is entry
                and self.canvas._selection is selection
            ):
                ready(result)
            else:
                self.status(
                    "Ação ignorada porque o documento ou a seleção foi alterado."
                )

        self._job(task, guarded)

    def modify_selection(self, command, amount=None):
        if self.stack.currentIndex() != 0:
            return
        selection = self.canvas.selection
        if not selection:
            return
        if command != "invert" and amount is None:
            amount, ok = QInputDialog.getInt(
                self, "Modificar seleção", "Raio em pixels da imagem:", 3, 1, 200
            )
            if not ok:
                return
        size = self.canvas.source_size
        self._selection_job(
            lambda: modify(selection, size, command, amount or 1),
            lambda value: setattr(self.canvas, "selection", value),
        )

    def save_selection(self):
        selection = self.canvas.selection
        if not selection:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Salvar máscara da seleção", "selecao.png", "Máscara PNG (*.png)"
        )
        if path:
            size = self.canvas.source_size
            self._job(
                lambda: write_image(
                    path, selection_mask((size[1], size[0]), selection)
                ),
                lambda _: self.status("Seleção salva como máscara PNG."),
            )

    def refine_selection_dialog(self):
        original = self.canvas.selection
        if not original:
            return
        size = self.canvas.source_size
        dialog = QDialog(self)
        dialog.setWindowTitle("Refinar arestas da seleção")
        form = QFormLayout(dialog)
        controls = {}
        for key, text, low, high in (
            ("smooth", "Suavizar contorno", 0, 20),
            ("feather", "Difusão da borda", 0, 100),
            ("expand", "Expandir / contrair", -100, 100),
        ):
            control = QSpinBox()
            control.setRange(low, high)
            control.setSuffix(" px")
            form.addRow(text, control)
            controls[key] = control
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Aplicar seleção")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        state = dict(active=True, generation=0)
        debounce = QTimer(dialog)
        debounce.setSingleShot(True)
        debounce.setInterval(90)

        def changed():
            state["generation"] += 1
            buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            debounce.start()

        def preview():
            generation = state["generation"]
            values = {key: control.value() for key, control in controls.items()}

            def process():
                selection = original
                for key, amount in values.items():
                    if amount and selection:
                        selection = modify(
                            selection,
                            size,
                            "contract" if key == "expand" and amount < 0 else key,
                            abs(amount),
                        )
                return selection

            def ready(selection):
                if state["active"] and generation == state["generation"]:
                    self.canvas.selection = selection
                    buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

            self._job(process, ready)

        debounce.timeout.connect(preview)
        for control in controls.values():
            control.valueChanged.connect(changed)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        state["active"] = False
        debounce.stop()
        if not accepted:
            self.canvas.selection = original

    def load_selection(self):
        if self.document.original is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Carregar máscara de seleção",
            "",
            "Máscara (*.png *.bmp *.tif *.tiff)",
        )
        if not path:
            return
        size = self.canvas.source_size

        def load():
            image = read_image(path)
            if image.ndim == 3:
                image = (
                    image[:, :, 3]
                    if image.shape[2] == 4
                    else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                )
            return from_mask(cv2.resize(image, size, interpolation=cv2.INTER_LINEAR))

        self._selection_job(
            load, lambda value: setattr(self.canvas, "selection", value)
        )

    def edit_selection_pixels(self, action, color=None, width=None):
        if self.document.original is None or self.stack.currentIndex() != 0:
            return
        selection = self.canvas.selection
        if action in ("copy", "cut", "stroke", "delete") and not selection:
            return
        if not self._active_layer_writable(action):
            self.status("Desbloqueie a camada para editar seus pixels.")
            return
        if not self._active_layer_editable():
            self.status(
                "Selecione uma camada editável, anterior ao resultado rasterizado."
            )
            return
        if action in ("fill", "stroke") and color is None:
            chosen = QColorDialog.getColor(
                QColor("#3478cb"),
                self,
                "Cor do preenchimento" if action == "fill" else "Cor do contorno",
                QColorDialog.ColorDialogOption.ShowAlphaChannel,
            )
            if not chosen.isValid():
                return
            color = (chosen.blue(), chosen.green(), chosen.red(), chosen.alpha())
        if action == "stroke" and width is None:
            width, ok = QInputDialog.getInt(
                self, "Traçar contorno", "Espessura em pixels da camada:", 3, 1, 200
            )
            if not ok:
                return
        if not self.apply_draft():
            return
        original, operations = self.document.original, self.document.operations
        layer_id = self.layer_panel.current_id or "base"
        labels = dict(
            copy="Camada via cópia",
            cut="Camada por corte",
            fill="Preencher camada",
            stroke="Traçar contorno",
            delete="Apagar pixels",
        )

        def ready(result):
            operations, selected_id = result
            self.document.set_operations(operations, labels[action])
            self.modified = True
            self._update_history()
            self.layer_panel.select_layer(selected_id)
            if action in ("copy", "cut"):
                self.canvas.clear_selection()
                self.layer_dock.show()
                self.layer_dock.raise_()
            self.request_render(False)
            self.status(labels[action] + ". Ctrl+Z para desfazer.")

        self._selection_job(
            lambda: edit_pixels(
                original, operations, layer_id, selection, action, color, width or 1
            ),
            ready,
        )

    def new_empty_layer(self):
        if (
            self.document.original is None
            or self.stack.currentIndex() != 0
            or not self.apply_draft()
        ):
            return
        original, operations = self.document.original, list(self.document.operations)
        layer_id = uuid4().hex

        def create():
            h, w = original.shape[:2]
            image = np.zeros((h, w, 4), np.uint8)
            image.setflags(write=False)
            params = dict(
                id=layer_id,
                name="Nova camada",
                image=image,
                x=0,
                y=0,
                width=w,
                height=h,
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
            operations.insert(insertion, Operation("layer", params, "Nova camada"))
            return operations

        def ready(ops):
            self.document.set_operations(ops, "Nova camada transparente")
            self.modified = True
            self._update_history()
            self.layer_panel.select_layer(layer_id)
            self.layer_dock.show()
            self.layer_dock.raise_()
            self.request_render(False)

        self._selection_job(create, ready)

    def transform_layer_dialog(self):
        if self.document.original is None or self.stack.currentIndex() != 0:
            return
        layer_id = self.layer_panel.current_id
        if (
            layer_id == "base"
            or not self._active_layer_editable()
            or blocks_layer_change(self._layer_params(layer_id) or {}, {"x", "width"})
            or not self.apply_draft()
        ):
            self.status("Selecione uma camada sobreposta para transformar.")
            return
        params = self._layer_params(layer_id)
        dialog = QDialog(self)
        dialog.setWindowTitle("Transformação livre da camada")
        form = QFormLayout(dialog)
        controls = {}
        for key, title in (
            ("x", "Posição X"),
            ("y", "Posição Y"),
            ("width", "Largura"),
            ("height", "Altura"),
        ):
            control = QSpinBox()
            control.setRange(-100000, 100000) if key in (
                "x",
                "y",
            ) else control.setRange(1, 100000)
            control.setSuffix(" px")
            control.setValue(params.get(key, 0))
            control.valueChanged.connect(
                lambda value, name=key: self.preview_layer(layer_id, {name: value})
            )
            form.addRow(title, control)
            controls[key] = control
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Aplicar transformação"
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")

        def validate():
            valid = (
                controls["width"].value() * controls["height"].value() <= 100_000_000
            )
            buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setToolTip(
                "Até 100 milhões de pixels por camada." if not valid else ""
            )

        controls["width"].valueChanged.connect(validate)
        controls["height"].valueChanged.connect(validate)
        validate()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.commit_layer_preview()
        else:
            self._layer_preview = None
            self.refresh_layers(layer_id)
            self.request_render(False)
