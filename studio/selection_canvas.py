"""Marching ants, selection gestures and eight-handle selection transforms."""

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainterPath, QPen, QTransform

from .selection import combine, transform


class SelectionInteraction:
    def _init_selection_interaction(self):
        self._selection_base = None
        self._selection_mode = "replace"
        self._selection_path_cache = None
        self._selection_transform = False
        self._selection_restore = None
        self._selection_gesture = None
        self._ants_offset = 0
        self._ants_timer = QTimer(self)
        self._ants_timer.setInterval(90)
        self._ants_timer.timeout.connect(self._animate_selection)

    def _animate_selection(self):
        self._ants_offset = (self._ants_offset + 1) % 8
        self.update()

    def _selection_updated(self):
        self._selection_path_cache = None
        if self._selection and self.isVisible():
            self._ants_timer.start()
        else:
            self._ants_timer.stop()
        self.update()

    def showEvent(self, event):
        self._selection_updated()
        super().showEvent(event)

    def hideEvent(self, event):
        self._ants_timer.stop()
        super().hideEvent(event)

    def begin_selection_transform(self):
        if not self._selection:
            return
        self._selection_restore = self.selection
        self._selection_transform = True
        self.setFocus()
        self.update()

    def end_selection_transform(self, cancel=False):
        if cancel:
            self.selection = self._selection_restore
        self._selection_transform = False
        self._selection_restore = None
        self._selection_gesture = None
        self._update_cursor()
        self.update()

    def _selection_handles(self):
        if not self._selection:
            return []
        x, y, w, h = self._selection["rect"]
        return [
            self.image_to_widget(QPointF(x + w * fx, y + h * fy))
            for fx, fy in (
                (0, 0),
                (0.5, 0),
                (1, 0),
                (1, 0.5),
                (1, 1),
                (0.5, 1),
                (0, 1),
                (0, 0.5),
            )
        ]

    def _selection_hit(self, position):
        if not self._selection:
            return None
        if self._selection_transform:
            distances = [
                (position - point).manhattanLength()
                for point in self._selection_handles()
            ]
            nearest = min(range(len(distances)), key=distances.__getitem__)
            if distances[nearest] <= 10:
                return nearest
        if self._tool not in ("rect", "ellipse") and not self._selection_transform:
            return None
        point = self.widget_to_image(position)
        x, y, w, h = self._selection["rect"]
        if not QRectF(x, y, w, h).adjusted(1, 1, -1, -1).contains(point):
            return None
        if "mask" in self._selection:
            mask = self._selection["mask"]
            px, py = (
                int(point.x() * mask.shape[1] / self.source_size[0]),
                int(point.y() * mask.shape[0] / self.source_size[1]),
            )
            inside = (
                0 <= py < mask.shape[0] and 0 <= px < mask.shape[1] and mask[py, px] > 0
            )
        elif self._selection.get("shape") == "ellipse":
            inside = ((point.x() - x - w / 2) / (w / 2)) ** 2 + (
                (point.y() - y - h / 2) / (h / 2)
            ) ** 2 < 1
        else:
            inside = True
        return "move" if inside else None

    def _selection_press(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._space_pressed:
            return False
        modifiers = event.modifiers()
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        self._selection_mode = (
            "intersect"
            if shift and alt
            else "add"
            if shift
            else "subtract"
            if alt
            else "replace"
        )
        if self._selection_mode != "replace" and not self._selection_transform:
            return False
        hit = self._selection_hit(event.position())
        if hit is None:
            return False
        self._selection_gesture = (
            hit,
            self.widget_to_image(event.position()),
            self.selection,
        )
        self.setCursor(
            Qt.CursorShape.SizeAllCursor
            if hit == "move"
            else Qt.CursorShape.CrossCursor
        )
        return True

    def _selection_hover(self, position):
        if self._space_pressed:
            self._update_cursor()
            return
        hit = self._selection_hit(position)
        if hit == "move":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif isinstance(hit, int):
            shapes = (
                Qt.CursorShape.SizeFDiagCursor,
                Qt.CursorShape.SizeVerCursor,
                Qt.CursorShape.SizeBDiagCursor,
                Qt.CursorShape.SizeHorCursor,
            ) * 2
            self.setCursor(shapes[hit])
        else:
            self._update_cursor()

    def _nudge_selection(self, event):
        directions = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if (
            not self._selection
            or (self._tool not in ("rect", "ellipse") and not self._selection_transform)
            or event.key() not in directions
        ):
            return False
        dx, dy = directions[event.key()]
        amount = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        x, y, w, h = self._selection["rect"]
        x = min(max(0, x + dx * amount), max(0, self.source_size[0] - w))
        y = min(max(0, y + dy * amount), max(0, self.source_size[1] - h))
        self.selection = transform(self._selection, self.source_size, (x, y, w, h))
        event.accept()
        return True

    def _selection_move(self, position, modifiers=Qt.KeyboardModifier.NoModifier):
        if not self._selection_gesture:
            return False
        hit, start, original = self._selection_gesture
        delta = self.widget_to_image(position) - start
        dx, dy = delta.x(), delta.y()
        x, y, w, h = original["rect"]
        if hit == "move":
            # Keep the complete selection inside the document while moving.
            x = min(max(0, round(x + dx)), max(0, self.source_size[0] - w))
            y = min(max(0, round(y + dy)), max(0, self.source_size[1] - h))
        else:
            right, bottom = x + w, y + h
            if hit in (0, 6, 7):
                x = min(right - 1, max(0, round(x + dx)))
            if hit in (2, 3, 4):
                right = max(x + 1, min(self.source_size[0], round(right + dx)))
            if hit in (0, 1, 2):
                y = min(bottom - 1, max(0, round(y + dy)))
            if hit in (4, 5, 6):
                bottom = max(y + 1, min(self.source_size[1], round(bottom + dy)))
            w, h = right - x, bottom - y
        self._selection = transform(original, self.source_size, (x, y, w, h))
        self._selection_updated()
        return True

    def _selection_release(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._selection_gesture:
            self._selection_move(event.position(), event.modifiers())
            self._selection_gesture = None
            self.selectionChanged.emit(self.selection)
            self._update_cursor()
            return True
        return False

    def _finish_selection_shape(self):
        self._selection = combine(
            self._selection_base,
            self._selection,
            self.source_size,
            self._selection_mode,
        )
        self._selection_base = None
        self._selection_updated()

    def _selection_path(self, selection):
        path = QPainterPath()
        if "mask" in selection:
            # Contours are cached in image coordinates; animation only repaints.
            mask = selection["mask"]
            binary = np.uint8(mask > 127)
            contours, _ = cv2.findContours(
                binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
            )
            sx = self.source_size[0] / mask.shape[1]
            sy = self.source_size[1] / mask.shape[0]
            path.setFillRule(Qt.FillRule.OddEvenFill)
            for contour in contours:
                if len(contour) == 1:
                    cx, cy = contour[0, 0]
                    path.addRect(QRectF(cx * sx, cy * sy, sx, sy))
                    continue
                for i, (cx, cy) in enumerate(contour[:, 0, :]):
                    point = QPointF((cx + 0.5) * sx, (cy + 0.5) * sy)
                    (path.moveTo if i == 0 else path.lineTo)(point)
                path.closeSubpath()
        else:
            rect = QRectF(*selection["rect"])
            (path.addEllipse if selection.get("shape") == "ellipse" else path.addRect)(
                rect
            )
        return path

    def _paint_selection(self, painter):
        if not self._selection:
            return
        if self._selection_path_cache is None:
            self._selection_path_cache = self._selection_path(self._selection)
        mapping = QTransform(
            self._zoom, 0, 0, self._zoom, self._offset.x(), self._offset.y()
        )
        path = mapping.map(self._selection_path_cache)
        if self._selection_base and self._selection_mode != "replace":
            path.addPath(mapping.map(self._selection_path(self._selection_base)))
        rect = path.boundingRect()
        if self._tool == "crop":
            outside = QPainterPath()
            outside.addRect(self.image_rect)
            painter.fillPath(outside.subtracted(path), QColor(0, 0, 0, 135))
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
        painter.setPen(QPen(QColor("#101113"), 1))
        painter.drawPath(path)
        pen = QPen(QColor("#ffffff"), 1)
        pen.setDashPattern([4, 4])
        pen.setDashOffset(self._ants_offset)
        painter.setPen(pen)
        painter.drawPath(path)
        if self._selection_transform:
            painter.setPen(QPen(QColor("#5798eb"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            x, y, w, h = self._selection["rect"]
            painter.drawRect(
                QRectF(
                    self.image_to_widget(QPointF(x, y)),
                    self.image_to_widget(QPointF(x + w, y + h)),
                )
            )
            painter.setBrush(QColor("#ffffff"))
            for point in self._selection_handles():
                painter.drawRect(QRectF(point.x() - 3, point.y() - 3, 6, 6))
            self._paint_badge(
                painter,
                "Transformar seleção · Enter confirma · Esc cancela",
                QPointF(16, 16),
            )
        elif self._tool == "crop":
            w, h = self._selection["rect"][2:]
            self._paint_badge(
                painter,
                f"{w} × {h}  ·  Enter para recortar",
                QPointF(max(12, rect.left()), max(12, rect.top() - 32)),
            )

    def contextMenuEvent(self, event):
        position = event.pos()
        if event.reason() == event.Reason.Keyboard:
            position = (
                self.image_rect.intersected(QRectF(self.rect())).center().toPoint()
            )
        if self._processed is not None and self.image_rect.contains(position):
            self.contextRequested.emit(self.mapToGlobal(position))
            event.accept()
        else:
            event.ignore()
