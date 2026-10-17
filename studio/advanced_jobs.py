"""Small Qt helpers shared by the independent scientific workspaces."""

from __future__ import annotations

import logging
from itertools import count

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from PySide6.QtGui import QImage, QPixmap


class JobSignals(QObject):
    completed = Signal(int, object, str)
    progress = Signal(str)


class Job(QRunnable):
    """A worker owns its signal object until run() has finished."""

    _ids = count(1)

    def __init__(self, function):
        super().__init__()
        self.identifier = next(self._ids)
        self.function = function
        self.signals = JobSignals()

    @Slot()
    def run(self):
        try:
            result, error = self.function(), ""
        except Exception as exc:
            result, error = None, f"{type(exc).__name__}: {exc}"
            logging.getLogger(__name__).debug(
                "Background operation failed", exc_info=True
            )
        try:
            self.signals.completed.emit(self.identifier, result, error)
        except RuntimeError:
            # QApplication may already be releasing QObjects during shutdown.
            # Numerical work and resource finalizers have still completed.
            pass


def image_pixmap(image: np.ndarray) -> QPixmap:
    """Detach QImage from NumPy memory before handing it to Qt."""
    if image.ndim == 2:
        data = np.ascontiguousarray(image)
        fmt = QImage.Format.Format_Grayscale8
    elif image.shape[2] == 4:
        data = cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
        fmt = QImage.Format.Format_RGBA8888
    else:
        data = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        fmt = QImage.Format.Format_RGB888
    h, w = data.shape[:2]
    return QPixmap.fromImage(QImage(data.data, w, h, data.strides[0], fmt).copy())
