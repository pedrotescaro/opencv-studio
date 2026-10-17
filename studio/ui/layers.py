"""Layer list, file drops, opacity and transform controls; no pixel processing."""

import cv2
from PySide6.QtCore import Qt, Signal, QSize, QEvent, QRect, QPoint
from PySide6.QtGui import QIcon, QImage, QPixmap, QColor, QPen
from PySide6.QtWidgets import (
    QWidget,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QToolButton,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QDialog,
    QStyledItemDelegate,
    QStyle,
    QDoubleSpinBox,
)
from studio.layers import BLEND_MODES
from .theme import icon


class LayerPercent(QWidget):
    """Compact editable percentage with the same signal contract as adjustments."""

    changed = Signal()
    released = Signal()

    def __init__(self, label, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.number = QDoubleSpinBox()
        self.number.setRange(0, 100)
        self.number.setDecimals(0)
        self.number.setSuffix("%")
        self.number.setValue(100)
        self.number.setKeyboardTracking(False)
        self.number.setFixedSize(60, 24)
        self.number.setAccessibleName(label + " da camada")
        self.number.valueChanged.connect(self.changed)
        self.number.editingFinished.connect(self.released)
        row.addWidget(self.number)
        self.setFixedWidth(60)

    def value(self):
        return self.number.value()

    def set_value(self, value, notify=False):
        self.number.blockSignals(True)
        self.number.setValue(value)
        self.number.blockSignals(False)
        if notify:
            self.changed.emit()
            self.released.emit()


class LayerDelegate(QStyledItemDelegate):
    """Dense eye/thumbnail/name rows, with the complete row available for dragging."""

    LOCK_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icons = {name: icon(name) for name in ("eye", "eye_off", "lock")}

    def sizeHint(self, option, index):
        return QSize(180, 40)

    @staticmethod
    def eye_rect(rect):
        return QRect(rect.left() + 2, rect.top(), 28, rect.height())

    def paint(self, painter, option, index):
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.fillRect(
            option.rect,
            QColor("#37465a" if selected else "#303034" if hovered else "#29292c"),
        )
        painter.setPen(QPen(QColor("#3b3b40"), 1))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        visible = index.data(Qt.ItemDataRole.CheckStateRole) in (
            Qt.CheckState.Checked,
            Qt.CheckState.Checked.value,
        )
        eye = self.eye_rect(option.rect)
        self._icons["eye" if visible else "eye_off"].paint(
            painter, eye.adjusted(6, 12, -6, -12)
        )
        thumb = QRect(option.rect.left() + 34, option.rect.top() + 4, 32, 32)
        for y in range(0, 32, 4):
            for x in range(0, 32, 4):
                painter.fillRect(
                    thumb.left() + x,
                    thumb.top() + y,
                    4,
                    4,
                    QColor("#77777c" if (x + y) % 8 else "#b2b2b8"),
                )
        thumbnail = index.data(Qt.ItemDataRole.DecorationRole)
        if thumbnail is not None:
            thumbnail.paint(painter, thumb, Qt.AlignmentFlag.AlignCenter)
        painter.setPen(QPen(QColor("#d0d0d7" if selected else "#68686f"), 1))
        painter.drawRect(thumb.adjusted(0, 0, -1, -1))
        locked = bool(index.data(self.LOCK_ROLE))
        text_rect = option.rect.adjusted(76, 0, -30 if locked else -8, 0)
        painter.setFont(option.font)
        painter.setPen(QColor("#eeeeF2" if visible else "#aaaab4"))
        text = option.fontMetrics.elidedText(
            str(index.data() or ""),
            Qt.TextElideMode.ElideRight,
            max(0, text_rect.width()),
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, text)
        if locked:
            self._icons["lock"].paint(
                painter, QRect(option.rect.right() - 23, option.rect.top() + 12, 16, 16)
            )
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Select,
        ):
            visible = index.data(Qt.ItemDataRole.CheckStateRole) in (
                Qt.CheckState.Checked,
                Qt.CheckState.Checked.value,
            )
            return model.setData(
                index,
                Qt.CheckState.Unchecked if visible else Qt.CheckState.Checked,
                Qt.ItemDataRole.CheckStateRole,
            )
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self.eye_rect(option.rect).contains(event.position().toPoint())
        ):
            visible = index.data(Qt.ItemDataRole.CheckStateRole) in (
                Qt.CheckState.Checked,
                Qt.CheckState.Checked.value,
            )
            return model.setData(
                index,
                Qt.CheckState.Unchecked if visible else Qt.CheckState.Checked,
                Qt.ItemDataRole.CheckStateRole,
            )
        return False

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(74, 5, -28, -5))


class LayerList(QListWidget):
    filesDropped = Signal(object)
    orderChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("layerList")
        self.setMinimumHeight(80)
        self.setItemDelegate(LayerDelegate(self))
        self.setMouseTracking(True)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
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
        layout.setSpacing(0)
        header = QWidget()
        header.setObjectName("layerHeader")
        controls = QVBoxLayout(header)
        controls.setContentsMargins(7, 5, 7, 5)
        controls.setSpacing(3)
        self.blend = QComboBox()
        self.blend.setFixedHeight(26)
        self.blend.setAccessibleName("Modo de mesclagem da camada")
        for key, label in BLEND_MODES.items():
            self.blend.addItem(label, key)
        self.blend.currentIndexChanged.connect(self._blend_changed)
        controls.addWidget(self.blend)
        percentages = QHBoxLayout()
        percentages.setSpacing(4)
        percentages.addWidget(QLabel("Opacidade:"))
        self.opacity = LayerPercent("Opacidade")
        self.opacity.changed.connect(
            lambda: self._change({"opacity": self.opacity.value() / 100})
        )
        self.opacity.released.connect(self.released)
        percentages.addWidget(self.opacity)
        percentages.addStretch()
        percentages.addWidget(QLabel("Preench.:"))
        self.fill = LayerPercent("Preenchimento")
        self.fill.setToolTip("Cobertura dos pixels da camada")
        self.fill.changed.connect(
            lambda: self._change({"fill": self.fill.value() / 100})
        )
        self.fill.released.connect(self.released)
        percentages.addWidget(self.fill)
        controls.addLayout(percentages)
        locks = QHBoxLayout()
        locks.setSpacing(2)
        locks.addWidget(QLabel("Bloquear:"))
        self.lock_buttons = {}
        for key, label, glyph in (
            ("lock_alpha", "Bloquear transparência", "lock_alpha"),
            ("lock_pixels", "Bloquear edição de pixels", "lock_pixels"),
            ("lock_position", "Bloquear posição e tamanho", "pan"),
            ("locked", "Bloquear camada", "lock"),
        ):
            button = QToolButton()
            button.setCheckable(True)
            button.setFixedSize(24, 24)
            button.setIconSize(QSize(16, 16))
            button.setIcon(icon(glyph))
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.clicked.connect(lambda checked, k=key: self._toggle_lock(k, checked))
            locks.addWidget(button)
            self.lock_buttons[key] = button
        locks.addStretch()
        controls.addLayout(locks)
        layout.addWidget(header)
        self.list = LayerList()
        self.list.currentItemChanged.connect(self._selection_changed)
        self.list.itemChanged.connect(self._item_changed)
        self.list.filesDropped.connect(self.filesDropped)
        self.list.orderChanged.connect(self.orderChanged)
        layout.addWidget(self.list, 1)
        self.properties = QDialog(self, Qt.WindowType.Tool)
        self.properties.setWindowTitle("Propriedades da camada")
        self.properties.setMinimumWidth(300)
        properties_layout = QVBoxLayout(self.properties)
        properties_layout.setContentsMargins(5, 5, 5, 5)
        body = QWidget()
        form = QGridLayout(body)
        form.setContentsMargins(7, 5, 7, 5)
        form.setSpacing(4)
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
        self.aspect = QCheckBox("Manter proporção")
        self.aspect.setChecked(True)
        form.addWidget(self.aspect, 2, 0, 1, 4)
        properties_layout.addWidget(body)
        self.properties.finished.connect(
            lambda _: self.buttons["properties"].setChecked(False)
        )
        self.properties.hide()
        footer = QWidget()
        footer.setObjectName("layerFooter")
        row = QHBoxLayout(footer)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(1)
        self.buttons = {}
        for key, label, glyph in (
            ("new", "Nova camada transparente", "new_layer"),
            ("import", "Adicionar imagens como camadas", "open"),
            ("up", "Subir camada", "layer_up"),
            ("down", "Descer camada", "layer_down"),
            ("duplicate", "Duplicar camada", "duplicate"),
            ("properties", "Propriedades: posição e tamanho", "adjustments"),
            ("remove", "Remover camada", "trash"),
        ):
            button = QToolButton()
            button.setFixedSize(28, 28)
            button.setIcon(icon(glyph))
            button.setIconSize(QSize(18, 18))
            button.setToolTip(label)
            button.setAccessibleName(label)
            if key == "properties":
                button.setCheckable(True)
                button.toggled.connect(self._show_properties)
            elif key == "import":
                button.clicked.connect(self.importRequested)
            else:
                button.clicked.connect(
                    lambda checked=False, action=key: self.actionRequested.emit(
                        action, self.current_id
                    )
                )
            if key == "remove":
                row.addStretch()
            row.addWidget(button)
            self.buttons[key] = button
        layout.addWidget(footer)
        self.set_layers([])
        # A drop anywhere in this panel adds layers, including on properties;
        # it must never bubble up to MainWindow's document-replacement drop.
        for widget in [self, *self.findChildren(QWidget)]:
            widget.setAcceptDrops(True)
            widget.installEventFilter(self)

    def _show_properties(self, visible):
        if visible:
            self.properties.adjustSize()
            point = self.mapToGlobal(QPoint(-self.properties.width() - 8, 0))
            screen = self.screen().availableGeometry()
            point.setX(
                max(
                    screen.left(),
                    min(point.x(), screen.right() - self.properties.width()),
                )
            )
            point.setY(
                max(
                    screen.top(),
                    min(point.y(), screen.bottom() - self.properties.height()),
                )
            )
            self.properties.move(point)
            self.properties.show()
            self.properties.raise_()
        else:
            self.properties.hide()

    def hideEvent(self, event):
        self.buttons["properties"].setChecked(False)
        self.properties.hide()
        super().hideEvent(event)

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
        key = (layer_id, id(image), image.shape)
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
            self._thumbnails[key] = (image, QIcon(QPixmap.fromImage(qimage)))
        return self._thumbnails[key][1]

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
            item.setData(
                LayerDelegate.LOCK_ROLE,
                any(
                    layer.get(key, False)
                    for key in ("locked", "lock_position", "lock_pixels", "lock_alpha")
                ),
            )
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
        current_thumbnails = {
            (layer["id"], id(layer["image"]), layer["image"].shape) for layer in layers
        }
        self._thumbnails = {
            key: value
            for key, value in self._thumbnails.items()
            if key in current_thumbnails
        }
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
        locked = bool(layer and layer.get("locked", False))
        position_locked = locked or bool(layer and layer.get("lock_position", False))
        self.fill.set_value(round(layer.get("fill", 1) * 100) if layer else 100)
        self.fill.setEnabled(enabled and not locked)
        self.opacity.setEnabled(enabled and not locked)
        for key, button in self.lock_buttons.items():
            button.setChecked(bool(layer and layer.get(key, False)))
            button.setEnabled(enabled and (key == "locked" or not locked))
        self.blend.setEnabled(enabled and not base and not locked)
        self.blend.setCurrentIndex(
            max(
                0,
                self.blend.findData(
                    layer.get("blend", "normal") if layer else "normal"
                ),
            )
        )
        for key, field in self.geometry_controls.items():
            field.setEnabled(enabled and not base and not position_locked)
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
            button.setEnabled(
                key == "import"
                or (
                    enabled
                    and (key in ("new", "duplicate", "properties") or not base)
                    and (key != "remove" or not locked)
                )
            )
        overlay_ids = [key for key in self._layers if key != "base"]
        position = (
            overlay_ids.index(self.current_id) if self.current_id in overlay_ids else -1
        )
        self.buttons["up"].setEnabled(position > 0)
        self.buttons["down"].setEnabled(0 <= position < len(overlay_ids) - 1)
        self.aspect.setEnabled(enabled and not base and not position_locked)
        self._loading = False

    def _toggle_lock(self, key, checked):
        self._change({key: checked})
        self.released.emit()

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
