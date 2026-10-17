"""Controles com valor editável, reset local e histogramas/curvas interativos."""

import numpy as np
from PySide6.QtCore import Qt, Signal, QPointF, QSize, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QPolygonF
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QSlider,
    QDoubleSpinBox,
    QToolButton,
    QVBoxLayout,
    QHBoxLayout,
    QAbstractSpinBox,
    QDockWidget,
    QSplitter,
    QSplitterHandle,
)
from studio.ui.theme import icon


class DockWidthGrip(QWidget):
    """Explicit horizontal resize grip, including for tabbed dock panels."""

    def __init__(self, dock):
        super().__init__(dock)
        self.dock = dock
        self.setObjectName("dockWidthGrip")
        self.setFixedSize(12, 28)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setToolTip(
            "Arraste para a esquerda ou direita para ajustar a largura do painel"
        )
        self.setAccessibleName("Redimensionar largura do painel")
        self._origin = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = (
                event.globalPosition().x(),
                self.dock.width(),
                self.dock.x(),
            )
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._origin is None:
            return
        x, width, left = self._origin
        delta = round(event.globalPosition().x() - x)
        parent = self.dock.parentWidget()
        is_left = (
            not self.dock.isFloating()
            and parent.dockWidgetArea(self.dock) == Qt.DockWidgetArea.LeftDockWidgetArea
        )
        target = max(
            self.dock.minimumWidth(), width + delta if is_left else width - delta
        )
        if self.dock.isFloating():
            self.dock.resize(target, self.dock.height())
            self.dock.move(left + width - target, self.dock.y())
        else:
            parent.resizeDocks([self.dock], [target], Qt.Orientation.Horizontal)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._origin = None
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#5798eb" if self.underMouse() else "#858590"))
        painter.drawRoundedRect(QRectF(5, 7, 2, 14), 1, 1)


class DockTitleBar(QWidget):
    """Readable dock controls while retaining Qt's title-bar drag behavior."""

    def __init__(self, dock):
        super().__init__(dock)
        self.dock = dock
        self.setObjectName("dockTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 2, 4, 2)
        layout.setSpacing(2)
        self.width_grip = DockWidthGrip(dock)
        layout.addWidget(self.width_grip)
        label = QLabel(dock.windowTitle())
        dock.windowTitleChanged.connect(label.setText)
        layout.addWidget(label, 1)
        self.float_button = QToolButton(self)
        self.close_button = QToolButton(self)
        for button in (self.float_button, self.close_button):
            button.setFixedSize(28, 28)
            button.setIconSize(QSize(18, 18))
            layout.addWidget(button)
        self.close_button.setIcon(icon("discard"))
        self.close_button.setToolTip("Fechar painel")
        self.close_button.setAccessibleName("Fechar painel")
        self.close_button.clicked.connect(dock.close)
        self.float_button.clicked.connect(self._toggle_floating)
        dock.topLevelChanged.connect(self._floating_changed)
        dock.featuresChanged.connect(self._features_changed)
        self._floating_changed(dock.isFloating())
        self._features_changed(dock.features())

    def _toggle_floating(self):
        self.dock.setFloating(not self.dock.isFloating())
        self.dock.raise_()

    def _floating_changed(self, floating):
        self.float_button.setIcon(icon("redock" if floating else "undock"))
        label = "Encaixar painel" if floating else "Destacar painel"
        self.float_button.setToolTip(label)
        self.float_button.setAccessibleName(label)

    def _features_changed(self, features):
        self.float_button.setVisible(
            bool(features & QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        )
        self.close_button.setVisible(
            bool(features & QDockWidget.DockWidgetFeature.DockWidgetClosable)
        )


class FilterSplitterHandle(QSplitterHandle):
    """A visible grip with the native vertical-resize mouse interaction."""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip(
            "Arraste para cima ou para baixo para ajustar a lista de filtros"
        )
        self.setAccessibleName("Redimensionar altura da lista de filtros")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#5798eb" if self.underMouse() else "#9797a2"))
        painter.drawRoundedRect(
            QRectF(self.width() / 2 - 16, self.height() / 2 - 1, 32, 2), 1, 1
        )

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


class FilterSplitter(QSplitter):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self.setObjectName("filterSplitter")
        self.setHandleWidth(12)
        self.setChildrenCollapsible(False)

    def createHandle(self):
        return FilterSplitterHandle(self.orientation(), self)


class AdjustmentControl(QWidget):
    changed = Signal()
    released = Signal()

    def __init__(self, label, minimum, maximum, default, step=1, parent=None):
        super().__init__(parent)
        self.default, self.minimum, self.maximum = default, minimum, maximum
        self.factor = 100 if step < 1 else 1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(3)
        header = QHBoxLayout()
        header.addWidget(QLabel(label))
        header.addStretch()
        self.number = QDoubleSpinBox()
        self.number.setRange(minimum, maximum)
        self.number.setDecimals(2 if step < 1 else 0)
        self.number.setSingleStep(step)
        # Qt 6.12's NoButtons + stylesheet collapses its internal editor to 1px.
        # Keep the native edit field; theme.py hides only the arrow subcontrols.
        self.number.setFixedWidth(72)
        self.number.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self.number.setValue(default)
        self.reset = QToolButton()
        self.reset.setIcon(icon("undo"))
        self.reset.setToolTip(f"Restaurar {label}")
        self.reset.clicked.connect(lambda: self.set_value(self.default, notify=True))
        header.addWidget(self.number)
        header.addWidget(self.reset)
        layout.addLayout(header)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(round(minimum * self.factor), round(maximum * self.factor))
        self.slider.setValue(round(default * self.factor))
        layout.addWidget(self.slider)
        self.slider.valueChanged.connect(self._slider)
        self.number.valueChanged.connect(self._number)
        self.slider.sliderReleased.connect(self.released)
        self.number.editingFinished.connect(self.released)

    def _slider(self, value):
        self.number.blockSignals(True)
        self.number.setValue(value / self.factor)
        self.number.blockSignals(False)
        self.changed.emit()

    def _number(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(round(value * self.factor))
        self.slider.blockSignals(False)
        self.changed.emit()

    def value(self):
        return self.number.value()

    def set_value(self, value, notify=False):
        self.number.blockSignals(True)
        self.slider.blockSignals(True)
        self.number.setValue(value)
        self.slider.setValue(round(value * self.factor))
        self.number.blockSignals(False)
        self.slider.blockSignals(False)
        if notify:
            self.changed.emit()
            self.released.emit()


class HistogramWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(115)
        self.values = None

    def set_image(self, image):
        if image is None:
            self.values = None
        else:
            small = image[
                :: max(1, image.shape[0] // 700), :: max(1, image.shape[1] // 700)
            ]
            if small.ndim == 2:
                self.values = [np.bincount(small.ravel(), minlength=256)]
            else:
                visible = (
                    small[:, :, :3][small[:, :, 3] > 0]
                    if small.shape[2] == 4
                    else small[:, :, :3].reshape(-1, 3)
                )
                self.values = (
                    [np.bincount(visible[:, c], minlength=256) for c in (2, 1, 0)]
                    if len(visible)
                    else [np.zeros(256)]
                )
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#202022"))
        w, h = self.width(), self.height()
        p.setPen(QColor("#36363b"))
        for i in range(1, 4):
            p.drawLine(w * i // 4, 5, w * i // 4, h - 16)
        if self.values is not None:
            maximum = max(float(np.percentile(v, 99.5)) for v in self.values) or 1
            for values, color in zip(
                self.values,
                ["#bb6b70", "#6f9e82", "#6d92bd"]
                if len(self.values) > 1
                else ["#c1c1cd"],
            ):
                poly = QPolygonF([QPointF(0, h - 17)])
                poly += QPolygonF(
                    [
                        QPointF(i / 255 * w, h - 17 - min(1, v / maximum) * (h - 26))
                        for i, v in enumerate(values)
                    ]
                )
                poly.append(QPointF(w, h - 17))
                c = QColor(color)
                c.setAlpha(75)
                p.setBrush(c)
                p.setPen(QColor(color))
                p.drawPolygon(poly)
        p.setPen(QColor("#a9a9b3"))
        p.drawText(4, h - 3, "0")
        p.drawText(w - 25, h - 3, "255")


class CurveWidget(QWidget):
    changed = Signal()
    released = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(190, 160)
        self.points = [(0, 0), (255, 255)]
        self.drag = None
        self.setToolTip(
            "Clique para adicionar um ponto; arraste para ajustar. Botão direito remove um ponto intermediário."
        )

    def set_points(self, points):
        self.points = [tuple(p) for p in points]
        self.update()

    def position(self, event):
        return (
            round(
                np.clip(
                    (event.position().x() - 10) / max(1, self.width() - 20) * 255,
                    0,
                    255,
                )
            ),
            round(
                np.clip(
                    (self.height() - 10 - event.position().y())
                    / max(1, self.height() - 20)
                    * 255,
                    0,
                    255,
                )
            ),
        )

    def mousePressEvent(self, event):
        x, y = self.position(event)
        near = min(
            range(len(self.points)),
            key=lambda i: abs(self.points[i][0] - x) + abs(self.points[i][1] - y),
        )
        if event.button() == Qt.MouseButton.RightButton:
            if 0 < near < len(self.points) - 1:
                self.points.pop(near)
                self.changed.emit()
                self.released.emit()
                self.update()
            return
        if abs(self.points[near][0] - x) > 12:
            if len(self.points) >= 12:
                return
            self.points.append((x, y))
            self.points.sort()
            near = self.points.index((x, y))
        self.drag = near
        self.mouseMoveEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag is None:
            return
        x, y = self.position(event)
        i = self.drag
        x = (
            0
            if i == 0
            else 255
            if i == len(self.points) - 1
            else max(self.points[i - 1][0] + 1, min(x, self.points[i + 1][0] - 1))
        )
        self.points[i] = (x, y)
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, event):
        self.drag = None
        self.released.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#202022"))
        w, h = self.width() - 20, self.height() - 20
        p.setPen(QColor("#3c3c43"))
        for i in range(5):
            p.drawLine(10 + w * i // 4, 10, 10 + w * i // 4, h + 10)
            p.drawLine(10, 10 + h * i // 4, w + 10, 10 + h * i // 4)
        points = QPolygonF(
            [
                QPointF(10 + x / 255 * w, 10 + (255 - y) / 255 * h)
                for x, y in self.points
            ]
        )
        p.setPen(QPen(QColor("#5798eb"), 2))
        p.drawPolyline(points)
        p.setBrush(QColor("#e4e4eb"))
        for point in points:
            p.drawEllipse(point, 4, 4)
