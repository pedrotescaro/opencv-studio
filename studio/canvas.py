"""Image viewport: coordinate transforms and interaction, independent of filters.

The painter requests only the visible source rectangle. No full-size zoomed
bitmap is ever allocated, including at 3200% or while comparing two images.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget


def array_to_qimage(image: np.ndarray) -> QImage:
    """Copy an OpenCV gray/BGR/BGRA image into an owned, correctly ordered image."""
    image = np.asarray(image)
    if image.size == 0 or image.ndim not in (2, 3):
        raise ValueError("A imagem deve conter pixels em cinza, BGR ou BGRA.")
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    if image.ndim == 2 or image.shape[2] == 1:
        gray = np.ascontiguousarray(image.reshape(image.shape[:2]))
        return QImage(
            gray.data,
            gray.shape[1],
            gray.shape[0],
            gray.strides[0],
            QImage.Format.Format_Grayscale8,
        ).copy()
    if image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        format_ = QImage.Format.Format_RGB888
    elif image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
        format_ = QImage.Format.Format_RGBA8888
    else:
        raise ValueError("Quantidade de canais inválida: use cinza, BGR ou BGRA.")
    image = np.ascontiguousarray(image)
    return QImage(
        image.data, image.shape[1], image.shape[0], image.strides[0], format_
    ).copy()


class ImageCanvas(QWidget):
    """Dark checkerboard viewport with zoom, pan, ROI tools and comparison."""

    zoomChanged = Signal(float)
    cursorChanged = Signal(int, int, object)
    selectionChanged = Signal(object)
    cropRequested = Signal(object)
    textRequested = Signal(int, int)
    pointClicked = Signal(int, int)
    colorPicked = Signal(object)
    fileDropped = Signal(str)
    layerDragStarted = Signal()
    layerDragMoved = Signal(float, float)
    layerDragFinished = Signal(float, float)

    MIN_ZOOM = 0.05
    MAX_ZOOM = 32.0
    FILE_SUFFIXES = {
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".webp",
        ".tif",
        ".tiff",
        ".ocvproj",
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("imageCanvas")
        self.setMinimumSize(200, 180)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self._original: np.ndarray | None = None
        self._processed: np.ndarray | None = None
        self._original_qimage = QImage()
        self._processed_qimage = QImage()
        self._source_size = QSize(0, 0)
        self._zoom = 1.0
        self._offset = QPointF()
        self._fit_mode = True
        self._tool = "pan"
        self._split = False
        self._split_position = 0.5
        self._compare_original = False
        self._space_pressed = False
        self._panning = False
        self._dragging_split = False
        self._pan_start = QPointF()
        self._pan_origin = QPointF()
        self._selection_start: QPointF | None = None
        self._selection: dict | None = None
        self._layer_rect = None
        self._dragging_layer = False
        self._layer_start = QPointF()
        self.crop_ratio: float | None = None
        self._checker = self._make_checker()
        self._update_cursor()

    @staticmethod
    def _make_checker() -> QPixmap:
        tile = QPixmap(24, 24)
        tile.fill(QColor("#292a2c"))
        painter = QPainter(tile)
        painter.fillRect(0, 0, 12, 12, QColor("#323335"))
        painter.fillRect(12, 12, 12, 12, QColor("#323335"))
        painter.end()
        return tile

    @property
    def zoom(self) -> float:
        return self._zoom

    @zoom.setter
    def zoom(self, factor: float):
        self.set_zoom(factor)

    @property
    def tool(self) -> str:
        return self._tool

    @property
    def selection(self) -> dict | None:
        return self._selection.copy() if self._selection else None

    @selection.setter
    def selection(self, value: dict | None):
        self._selection = value.copy() if value else None
        self.selectionChanged.emit(self.selection)
        self.update()

    @property
    def split(self) -> bool:
        return self._split

    @split.setter
    def split(self, enabled: bool):
        self._split = bool(enabled)
        self.update()

    @property
    def split_position(self) -> float:
        return self._split_position

    @split_position.setter
    def split_position(self, position: float):
        self._split_position = min(1.0, max(0.0, float(position)))
        self.update()

    @property
    def compare_original(self) -> bool:
        return self._compare_original

    @compare_original.setter
    def compare_original(self, enabled: bool):
        self._compare_original = bool(enabled)
        self.update()

    @property
    def source_size(self) -> tuple[int, int]:
        return self._source_size.width(), self._source_size.height()

    @property
    def image_rect(self) -> QRectF:
        return QRectF(
            self._offset.x(),
            self._offset.y(),
            self._source_size.width() * self._zoom,
            self._source_size.height() * self._zoom,
        )

    def set_images(
        self,
        original: np.ndarray | None,
        processed: np.ndarray | None = None,
        source_size: tuple[int, int] | None = None,
    ):
        """Set rendered images; optional full-resolution stage size keeps preview stable."""
        if processed is None:
            processed = original
        if processed is None:
            self._original = self._processed = None
            self._original_qimage = self._processed_qimage = QImage()
            self._source_size = QSize(0, 0)
            self.clear_selection()
            self.update()
            return
        if original is None:
            original = processed
        processed_qimage = array_to_qimage(processed)
        original_qimage = array_to_qimage(original)
        width, height = source_size or (processed.shape[1], processed.shape[0])
        if width <= 0 or height <= 0:
            raise ValueError("As dimensões da imagem devem ser maiores que zero.")
        dimensions_changed = self._source_size != QSize(int(width), int(height))
        self._original = original
        self._processed = processed
        self._original_qimage = original_qimage
        self._processed_qimage = processed_qimage
        self._source_size = QSize(int(width), int(height))
        if dimensions_changed:
            self.clear_selection()
            self.fit_to_view()
        self.update()

    def set_image(self, image: np.ndarray | None):
        self.set_images(image, image)

    def set_tool(self, tool: str):
        aliases = {
            "move": "pan",
            "rectangle": "rect",
            "select": "rect",
            "rectangle_selection": "rect",
            "ellipse_selection": "ellipse",
            "picker": "eyedropper",
        }
        self._tool = aliases.get(tool, tool)
        self._selection_start = None
        self._update_cursor()
        self.update()

    def clear_selection(self):
        self._selection = None
        self._selection_start = None
        self.selectionChanged.emit(None)
        self.update()

    def set_layer_rect(self, rect):
        self._layer_rect = QRectF(*rect) if rect is not None else None
        if rect is None:
            self._dragging_layer = False
        self.update()

    def fit_to_view(self):
        if self._source_size.isEmpty():
            return
        factor = min(
            max(1, self.width() - 64) / self._source_size.width(),
            max(1, self.height() - 64) / self._source_size.height(),
        )
        self._zoom = min(self.MAX_ZOOM, max(self.MIN_ZOOM, factor))
        self._center_image()
        self._fit_mode = True
        self.zoomChanged.emit(self._zoom)
        self.update()

    def actual_size(self):
        self.set_zoom(1.0)
        self._center_image()
        self.update()

    def _center_image(self):
        self._offset = QPointF(
            (self.width() - self._source_size.width() * self._zoom) / 2,
            (self.height() - self._source_size.height() * self._zoom) / 2,
        )

    def zoom_by(self, factor: float, anchor: QPointF | QPoint | None = None):
        self.set_zoom(self._zoom * float(factor), anchor)

    def set_zoom(self, factor: float, anchor: QPointF | QPoint | None = None):
        factor = float(factor)
        if not math.isfinite(factor) or factor <= 0:
            return
        factor = min(self.MAX_ZOOM, max(self.MIN_ZOOM, factor))
        anchor = (
            QPointF(anchor) if anchor is not None else QPointF(self.rect().center())
        )
        image_point = self.widget_to_image(anchor)
        self._zoom = factor
        self._offset = anchor - image_point * factor
        self._fit_mode = False
        self.zoomChanged.emit(self._zoom)
        self.update()

    def widget_to_image(self, point: QPointF | QPoint, clamp: bool = False) -> QPointF:
        result = (QPointF(point) - self._offset) / self._zoom
        if clamp:
            result.setX(min(self._source_size.width(), max(0.0, result.x())))
            result.setY(min(self._source_size.height(), max(0.0, result.y())))
        return result

    def image_to_widget(self, point: QPointF | QPoint) -> QPointF:
        return QPointF(point) * self._zoom + self._offset

    def _pixel_at(
        self, position: QPointF
    ) -> tuple[int, int, tuple[int, int, int] | None]:
        point = self.widget_to_image(position)
        x, y = math.floor(point.x()), math.floor(point.y())
        image = self._original if self._compare_original else self._processed
        if self._split and point.x() < self._source_size.width() * self._split_position:
            image = self._original
        if image is None or not (
            0 <= x < self._source_size.width() and 0 <= y < self._source_size.height()
        ):
            return x, y, None
        px = min(
            image.shape[1] - 1, int(x * image.shape[1] / self._source_size.width())
        )
        py = min(
            image.shape[0] - 1, int(y * image.shape[0] / self._source_size.height())
        )
        color = image[py, px]
        if np.ndim(color) == 0 or np.size(color) == 1:
            value = int(np.ravel(color)[0])
            return x, y, (value, value, value)
        return x, y, (int(color[2]), int(color[1]), int(color[0]))

    def _draw_image(self, painter: QPainter, image: QImage, clip: QRectF | None = None):
        if image.isNull():
            return
        target = self.image_rect.intersected(QRectF(self.rect()))
        if clip is not None:
            target = target.intersected(clip)
        if target.isEmpty():
            return
        # Source clipping is proportional to the stage, also for reduced previews.
        source = QRectF(
            (target.x() - self._offset.x()) / self.image_rect.width() * image.width(),
            (target.y() - self._offset.y()) / self.image_rect.height() * image.height(),
            target.width() / self.image_rect.width() * image.width(),
            target.height() / self.image_rect.height() * image.height(),
        )
        painter.drawImage(target, image, source)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1b1c1e"))
        if self._processed_qimage.isNull():
            self._paint_empty(painter)
            return
        image_rect = self.image_rect
        visible = image_rect.intersected(QRectF(self.rect()))
        painter.save()
        painter.setClipRect(visible)
        painter.drawTiledPixmap(visible.toAlignedRect(), self._checker)
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform, self._zoom < 1.0
        )
        if self._compare_original:
            self._draw_image(painter, self._original_qimage)
        elif self._split:
            split_x = image_rect.left() + image_rect.width() * self._split_position
            self._draw_image(
                painter,
                self._original_qimage,
                QRectF(
                    image_rect.left(),
                    image_rect.top(),
                    split_x - image_rect.left(),
                    image_rect.height(),
                ),
            )
            self._draw_image(
                painter,
                self._processed_qimage,
                QRectF(
                    split_x,
                    image_rect.top(),
                    image_rect.right() - split_x,
                    image_rect.height(),
                ),
            )
        else:
            self._draw_image(painter, self._processed_qimage)
        painter.restore()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#101113"), 1))
        painter.drawRect(image_rect)
        self._paint_selection(painter)
        if self._layer_rect is not None and not self._compare_original:
            a = self.image_to_widget(self._layer_rect.topLeft())
            b = self.image_to_widget(self._layer_rect.bottomRight())
            bounds = QRectF(a, b).normalized()
            painter.setPen(QPen(QColor("#5798eb"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(bounds)
        if self._split and not self._compare_original:
            self._paint_split(painter)
        if self._compare_original:
            self._paint_badge(painter, "ORIGINAL", QPointF(16, 16))

    def _paint_empty(self, painter: QPainter):
        center = QPointF(self.rect().center())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#62666e"), 1.5))
        icon = QRectF(center.x() - 22, center.y() - 74, 44, 36)
        painter.drawRoundedRect(icon, 3, 3)
        painter.drawEllipse(QPointF(icon.left() + 31, icon.top() + 10), 3, 3)
        path = QPainterPath(QPointF(icon.left() + 4, icon.bottom() - 7))
        path.lineTo(icon.left() + 15, icon.top() + 15)
        path.lineTo(icon.left() + 25, icon.bottom() - 9)
        path.lineTo(icon.left() + 32, icon.top() + 23)
        path.lineTo(icon.right() - 4, icon.bottom() - 7)
        painter.drawPath(path)
        font = self.font()
        font.setPointSize(15)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#e0e2e6"))
        painter.drawText(
            QRectF(12, center.y() - 15, self.width() - 24, 30),
            Qt.AlignmentFlag.AlignCenter,
            "Seu próximo projeto começa aqui",
        )
        font.setPointSize(10)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor("#a5a8af"))
        painter.drawText(
            QRectF(12, center.y() + 23, self.width() - 24, 24),
            Qt.AlignmentFlag.AlignCenter,
            "Arraste uma imagem ou use Arquivo → Abrir",
        )
        painter.drawText(
            QRectF(12, center.y() + 55, self.width() - 24, 24),
            Qt.AlignmentFlag.AlignCenter,
            "PNG · JPG · BMP · WEBP · TIFF",
        )

    def _paint_selection(self, painter: QPainter):
        if not self._selection:
            return
        x, y, width, height = self._selection["rect"]
        rect = QRectF(
            self.image_to_widget(QPointF(x, y)),
            self.image_to_widget(QPointF(x + width, y + height)),
        )
        path = QPainterPath()
        if self._selection.get("shape") == "ellipse":
            path.addEllipse(rect)
        else:
            path.addRect(rect)
        if self._tool == "crop":
            outside = QPainterPath()
            outside.addRect(self.image_rect)
            painter.fillPath(outside.subtracted(path), QColor(0, 0, 0, 135))
            painter.save()
            painter.setClipPath(path)
            painter.setPen(QPen(QColor(255, 255, 255, 95), 1))
            for fraction in (1 / 3, 2 / 3):
                painter.drawLine(
                    QPointF(rect.left() + rect.width() * fraction, rect.top()),
                    QPointF(rect.left() + rect.width() * fraction, rect.bottom()),
                )
                painter.drawLine(
                    QPointF(rect.left(), rect.top() + rect.height() * fraction),
                    QPointF(rect.right(), rect.top() + rect.height() * fraction),
                )
            painter.restore()
        else:
            painter.fillPath(path, QColor(62, 143, 255, 22))
        painter.setPen(QPen(QColor("#141619"), 3))
        painter.drawPath(path)
        painter.setPen(QPen(QColor("#e9edf3"), 1, Qt.PenStyle.DashLine))
        painter.drawPath(path)
        if self._tool == "crop":
            self._paint_badge(
                painter,
                f"{width} × {height}  ·  Enter para recortar",
                QPointF(max(12, rect.left()), max(12, rect.top() - 32)),
            )

    def _paint_split(self, painter: QPainter):
        rect = self.image_rect.intersected(QRectF(self.rect()))
        split_x = (
            self.image_rect.left() + self.image_rect.width() * self._split_position
        )
        if not self.rect().contains(QPoint(int(split_x), int(rect.center().y()))):
            return
        painter.setPen(QPen(QColor("#111214"), 3))
        painter.drawLine(QPointF(split_x, rect.top()), QPointF(split_x, rect.bottom()))
        painter.setPen(QPen(QColor("#f1f3f6"), 1))
        painter.drawLine(QPointF(split_x, rect.top()), QPointF(split_x, rect.bottom()))
        handle = QRectF(split_x - 13, rect.center().y() - 20, 26, 40)
        painter.setBrush(QColor("#25272b"))
        painter.drawRoundedRect(handle, 5, 5)
        painter.drawLine(
            QPointF(split_x - 3, handle.top() + 12),
            QPointF(split_x - 3, handle.bottom() - 12),
        )
        painter.drawLine(
            QPointF(split_x + 3, handle.top() + 12),
            QPointF(split_x + 3, handle.bottom() - 12),
        )
        self._paint_badge(painter, "ANTES", QPointF(rect.left() + 12, rect.top() + 12))
        self._paint_badge(
            painter,
            "DEPOIS",
            QPointF(max(split_x + 12, rect.right() - 86), rect.top() + 12),
        )

    def _paint_badge(self, painter: QPainter, text: str, point: QPointF):
        painter.save()
        font = self.font()
        font.setPointSize(8)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(text) + 18
        rect = QRectF(point.x(), point.y(), width, 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(26, 27, 30, 220))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor("#e4e7ed"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def resizeEvent(self, event):
        previous = event.oldSize()
        if self._fit_mode:
            self.fit_to_view()
        elif previous.isValid():
            self._offset += QPointF(
                (self.width() - previous.width()) / 2,
                (self.height() - previous.height()) / 2,
            )
        super().resizeEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y() or event.pixelDelta().y() * 8
        if delta:
            self.zoom_by(2.0 ** (delta / 480.0), event.position())
        event.accept()

    def _update_cursor(self):
        if self._panning or self._dragging_layer:
            cursor = Qt.CursorShape.ClosedHandCursor
        elif self._space_pressed or self._tool == "pan":
            cursor = Qt.CursorShape.OpenHandCursor
        elif self._tool == "text":
            cursor = Qt.CursorShape.IBeamCursor
        else:
            cursor = Qt.CursorShape.CrossCursor
        self.setCursor(cursor)

    def mousePressEvent(self, event: QMouseEvent):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self._processed_qimage.isNull():
            return
        position = event.position()
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and (self._space_pressed or self._tool == "pan")
        ):
            # The split handle has priority over left-button pan.
            split_x = (
                self.image_rect.left() + self.image_rect.width() * self._split_position
            )
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._split
                and not self._space_pressed
                and abs(position.x() - split_x) <= 10
                and self.image_rect.contains(position)
            ):
                self._dragging_split = True
                self.setCursor(Qt.CursorShape.SplitHCursor)
                return
            if (
                event.button() == Qt.MouseButton.LeftButton
                and not self._space_pressed
                and self._tool == "pan"
                and self._layer_rect is not None
                and self._layer_rect.contains(self.widget_to_image(position))
            ):
                self._dragging_layer = True
                self._layer_start = self.widget_to_image(position)
                self.layerDragStarted.emit()
                self._update_cursor()
                return
            self._panning = True
            self._pan_start = position
            self._pan_origin = QPointF(self._offset)
            self._fit_mode = False
            self._update_cursor()
            return
        if event.button() != Qt.MouseButton.LeftButton or not self.image_rect.contains(
            position
        ):
            return
        split_x = (
            self.image_rect.left() + self.image_rect.width() * self._split_position
        )
        if self._split and abs(position.x() - split_x) <= 10:
            self._dragging_split = True
            self.setCursor(Qt.CursorShape.SplitHCursor)
            return
        x, y, color = self._pixel_at(position)
        if color is None:
            return
        if self._tool in ("rect", "ellipse", "crop"):
            self._selection_start = self.widget_to_image(position, clamp=True)
            self._selection = None
        elif self._tool == "text":
            self.textRequested.emit(x, y)
        elif self._tool == "eyedropper":
            self.cursorChanged.emit(x, y, color)
            self.colorPicked.emit(color)
        else:
            self.pointClicked.emit(x, y)
        self.update()

    def _selection_to(self, position: QPointF):
        if self._selection_start is None:
            return
        start = self._selection_start
        end = self.widget_to_image(position, clamp=True)
        dx, dy = end.x() - start.x(), end.y() - start.y()
        if self._tool == "crop" and self.crop_ratio and self.crop_ratio > 0:
            width, height = abs(dx), abs(dy)
            if width / self.crop_ratio <= height:
                height = width / self.crop_ratio
            else:
                width = height * self.crop_ratio
            dx = math.copysign(width, dx)
            dy = math.copysign(height, dy)
            end = start + QPointF(dx, dy)
        x0 = max(0, math.floor(min(start.x(), end.x())))
        y0 = max(0, math.floor(min(start.y(), end.y())))
        x1 = min(self._source_size.width(), math.ceil(max(start.x(), end.x())))
        y1 = min(self._source_size.height(), math.ceil(max(start.y(), end.y())))
        if x1 > x0 and y1 > y0:
            self._selection = {
                "shape": "ellipse" if self._tool == "ellipse" else "rect",
                "rect": (x0, y0, x1 - x0, y1 - y0),
                "source_size": self.source_size,
            }
        else:
            self._selection = None
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        position = event.position()
        if self._dragging_layer:
            delta = self.widget_to_image(position) - self._layer_start
            self.layerDragMoved.emit(delta.x(), delta.y())
        elif self._dragging_split:
            self.split_position = (
                position.x() - self.image_rect.left()
            ) / self.image_rect.width()
        elif self._panning:
            self._offset = self._pan_origin + position - self._pan_start
            self.update()
        elif self._selection_start is not None:
            self._selection_to(position)
        x, y, color = self._pixel_at(position)
        self.cursorChanged.emit(x, y, color)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_layer:
            delta = self.widget_to_image(event.position()) - self._layer_start
            self._dragging_layer = False
            self.layerDragFinished.emit(delta.x(), delta.y())
            self._update_cursor()
            return
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            if self._selection_start is not None:
                self._selection_to(event.position())
                self._selection_start = None
                self.selectionChanged.emit(self.selection)
            self._panning = self._dragging_split = False
            self._update_cursor()
            self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if self._tool == "crop" and self._selection:
            self.cropRequested.emit(self.selection)
        elif self._tool == "pan":
            self.fit_to_view()
        else:
            super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        self.cursorChanged.emit(-1, -1, None)
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = True
            self._update_cursor()
            event.accept()
        elif event.key() == Qt.Key.Key_Backslash:
            self.compare_original = True
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.clear_selection()
            event.accept()
        elif (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self._tool == "crop"
            and self._selection
        ):
            self.cropRequested.emit(self.selection)
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = False
            self._update_cursor()
            event.accept()
        elif event.key() == Qt.Key.Key_Backslash and not event.isAutoRepeat():
            self.compare_original = False
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self._space_pressed = False
        self._panning = False
        self._dragging_split = False
        self.compare_original = False
        self._update_cursor()
        super().focusOutEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() and any(
            url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in self.FILE_SUFFIXES
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if url.isLocalFile() and Path(path).suffix.lower() in self.FILE_SUFFIXES:
                self.fileDropped.emit(path)
                event.acceptProposedAction()
                return
        event.ignore()
