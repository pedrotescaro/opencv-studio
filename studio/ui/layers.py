"""Layer list, file drops, opacity and transform controls; no pixel processing."""

import cv2
from PySide6.QtCore import Qt, Signal, QSize, QEvent
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QScrollArea,
)
from studio.layers import BLEND_MODES
from .theme import icon
from .widgets import AdjustmentControl


class LayerList(QListWidget):
    filesDropped = Signal(object)
    orderChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setIconSize(QSize(42, 34))
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAcceptDrops(True)
        self.setToolTip(
            "Arraste arquivos para adicionar camadas. Arraste uma linha para mudar a ordem."
        )
        self.setAccessibleName("Camadas, de cima para baixo")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [
                u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()
            ]
            if paths:
                self.filesDropped.emit(paths)
                event.acceptProposedAction()
            return
        super().dropEvent(event)
        self.orderChanged.emit(
            [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]
        )


class LayerPanel(QWidget):
    importRequested = Signal()
    filesDropped = Signal(object)
    selected = Signal(str)
    changed = Signal(str, object)
    released = Signal()
    orderChanged = Signal(object)
    actionRequested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._layers = {}
        self._thumbnails = {}
        self._selected_id = "base"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        controls = QVBoxLayout(body)
        controls.setContentsMargins(10, 8, 10, 10)
        controls.setSpacing(7)
        add = QPushButton("Adicionar imagens como camadas…")
        add.setIcon(icon("open"))
        add.clicked.connect(self.importRequested)
        controls.addWidget(add)
        self.opacity = AdjustmentControl("Opacidade", 0, 100, 100)
        self.opacity.changed.connect(
            lambda: self._change({"opacity": self.opacity.value() / 100})
        )
        self.opacity.released.connect(self.released)
        controls.addWidget(self.opacity)
        self.blend = QComboBox()
        for key, label in BLEND_MODES.items():
            self.blend.addItem(label, key)
        self.blend.currentIndexChanged.connect(self._blend_changed)
        controls.addWidget(self.blend)
        self.list = LayerList()
        self.list.currentItemChanged.connect(self._selection_changed)
        self.list.itemChanged.connect(self._item_changed)
        self.list.filesDropped.connect(self.filesDropped)
        self.list.orderChanged.connect(self.orderChanged)
        controls.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.buttons = {}
        for key, label, glyph in (
            ("up", "Subir camada", "layer_up"),
            ("down", "Descer camada", "layer_down"),
            ("duplicate", "Duplicar camada", "duplicate"),
            ("remove", "Remover camada", "discard"),
        ):
            button = QToolButton()
            button.setIcon(icon(glyph))
            button.setIconSize(QSize(18, 18))
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.clicked.connect(
                lambda checked=False, action=key: self.actionRequested.emit(
                    action, self.current_id
                )
            )
            row.addWidget(button)
            self.buttons[key] = button
        row.addStretch()
        controls.addLayout(row)
        note = QLabel(
            "Topo = frente · marque para mostrar · duplo clique para renomear"
        )
        note.setWordWrap(True)
        note.setProperty("muted", True)
        controls.addWidget(note)
        form = QGridLayout()
        self.geometry_controls = {}
        for index, (key, label) in enumerate(
            (("x", "X"), ("y", "Y"), ("width", "Largura"), ("height", "Altura"))
        ):
            field = QSpinBox()
            field.setRange(-100000 if key in ("x", "y") else 1, 100000)
            field.setKeyboardTracking(False)
            field.setAccessibleName(label + " da camada")
            field.valueChanged.connect(
                lambda value, k=key: self._geometry_changed(k, value)
            )
            field.editingFinished.connect(self.released)
            form.addWidget(QLabel(label), index // 2, (index % 2) * 2)
            form.addWidget(field, index // 2, (index % 2) * 2 + 1)
            self.geometry_controls[key] = field
        controls.addLayout(form)
        self.aspect = QCheckBox("Manter proporção ao redimensionar")
        self.aspect.setChecked(True)
        controls.addWidget(self.aspect)
        self.move_note = QLabel(
            "Com a camada selecionada, use Mover e arraste no canvas. Espaço + arrastar move a visualização."
        )
        self.move_note.setWordWrap(True)
        self.move_note.setProperty("muted", True)
        controls.addWidget(self.move_note)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        self.set_layers([])
        # A drop anywhere in this panel adds layers, including on properties;
        # it must never bubble up to MainWindow's document-replacement drop.
        for widget in [self, *self.findChildren(QWidget)]:
            widget.setAcceptDrops(True)
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if (
            event.type()
            in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)
            and event.mimeData().hasUrls()
        ):
            paths = [
                url.toLocalFile()
                for url in event.mimeData().urls()
                if url.isLocalFile()
            ]
            if paths:
                if event.type() == QEvent.Type.Drop:
                    self.filesDropped.emit(paths)
                event.acceptProposedAction()
            else:
                event.ignore()
            return True
        return super().eventFilter(watched, event)

    @property
    def current_id(self):
        return self._selected_id

    def select_layer(self, layer_id):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == layer_id:
                self.list.setCurrentItem(item)
                return

    def _thumbnail(self, layer_id, image):
        key = (layer_id, image.__array_interface__["data"][0], image.shape)
        if key not in self._thumbnails:
            ratio = min(42 / image.shape[1], 34 / image.shape[0])
            small = cv2.resize(
                image,
                (
                    max(1, round(image.shape[1] * ratio)),
                    max(1, round(image.shape[0] * ratio)),
                ),
            )
            if small.ndim == 2:
                small = cv2.cvtColor(small, cv2.COLOR_GRAY2RGBA)
            else:
                small = cv2.cvtColor(
                    small,
                    cv2.COLOR_BGRA2RGBA if small.shape[2] == 4 else cv2.COLOR_BGR2RGBA,
                )
            qimage = QImage(
                small.data,
                small.shape[1],
                small.shape[0],
                small.strides[0],
                QImage.Format.Format_RGBA8888,
            ).copy()
            self._thumbnails[key] = QIcon(QPixmap.fromImage(qimage))
        return self._thumbnails[key]

    def set_layers(self, layers, selected_id=None):
        self._loading = True
        self._layers = {layer["id"]: layer for layer in layers}
        keep = selected_id or self._selected_id
        self.list.clear()
        for layer in layers:
            item = QListWidgetItem(
                self._thumbnail(layer["id"], layer["image"]), layer["name"]
            )
            item.setData(Qt.ItemDataRole.UserRole, layer["id"])
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEditable
            )
            item.setCheckState(
                Qt.CheckState.Checked
                if layer.get("visible", True)
                else Qt.CheckState.Unchecked
            )
            self.list.addItem(item)
        self._loading = False
        self.select_layer(
            keep if keep in self._layers else (layers[0]["id"] if layers else "")
        )
        if not layers:
            self._selected_id = ""
            self._populate(None)
        else:
            self._selection_changed(self.list.currentItem(), None)

    def _selection_changed(self, current, previous):
        if self._loading or current is None:
            return
        self._selected_id = current.data(Qt.ItemDataRole.UserRole)
        self._populate(self._layers.get(self.current_id))
        self.selected.emit(self.current_id)

    def _populate(self, layer):
        self._loading = True
        enabled = layer is not None
        self.opacity.setEnabled(enabled)
        base = enabled and layer["id"] == "base"
        self.opacity.set_value(round(layer.get("opacity", 1) * 100) if layer else 100)
        self.blend.setEnabled(enabled and not base)
        self.blend.setCurrentIndex(
            max(
                0,
                self.blend.findData(
                    layer.get("blend", "normal") if layer else "normal"
                ),
            )
        )
        for key, field in self.geometry_controls.items():
            field.setEnabled(enabled and not base)
            fallback = (
                layer["image"].shape[1 if key == "width" else 0]
                if layer and key in ("width", "height")
                else 0
            )
            field.setValue(
                int(layer.get(key, fallback))
                if layer
                else (1 if key in ("width", "height") else 0)
            )
        for key, button in self.buttons.items():
            button.setEnabled(enabled and (not base or key == "duplicate"))
        self.aspect.setEnabled(enabled and not base)
        self._loading = False

    def _item_changed(self, item):
        if self._loading:
            return
        self.changed.emit(
            item.data(Qt.ItemDataRole.UserRole),
            {
                "visible": item.checkState() == Qt.CheckState.Checked,
                "name": item.text().strip() or "Camada",
            },
        )
        self.released.emit()

    def _change(self, values):
        if not self._loading and self.current_id:
            self.changed.emit(self.current_id, values)

    def _blend_changed(self):
        if not self._loading:
            self._change({"blend": self.blend.currentData()})
            self.released.emit()

    def _geometry_changed(self, key, value):
        if self._loading:
            return
        changes = {key: value}
        layer = self._layers.get(self.current_id)
        if layer and key in ("width", "height") and self.aspect.isChecked():
            other = "height" if key == "width" else "width"
            width = layer.get("width", layer["image"].shape[1])
            height = layer.get("height", layer["image"].shape[0])
            changes[other] = max(
                1, round(value * (height / width if key == "width" else width / height))
            )
            self.geometry_controls[other].blockSignals(True)
            self.geometry_controls[other].setValue(changes[other])
            self.geometry_controls[other].blockSignals(False)
        self._change(changes)
