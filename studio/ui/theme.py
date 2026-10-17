"""Paleta única, métricas e ícones vetoriais da interface."""

from PySide6.QtCore import Qt, QRectF, QPoint
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath

FILTER_CATEGORY_ICONS = {
    "Cores": "colors",
    "Canais": "channels",
    "Luz e contraste": "contrast",
    "Desfoque": "blur",
    "Detalhes": "details",
    "Bordas": "edges",
    "Morfologia": "morphology",
    "Efeitos": "effects",
    "Transformar": "resize",
    "Segmentação": "segment",
    "Mapas de cores": "colormap",
    "Fotografia": "image",
}

STYLE = """QWidget { background:#252526; color:#e4e4e7; font-family:'Segoe UI'; font-size:12px; }
QMainWindow,QStackedWidget { background:#1e1e1e; }
QMainWindow::separator { background:#36363c; width:8px; height:8px; }
QMainWindow::separator:hover { background:#488bdc; }
QMenuBar { background:#252526; padding:4px 10px; border-bottom:1px solid #38383b; }
QMenuBar::item { padding:5px 12px; background:transparent; }
QMenuBar::item:selected,QMenu::item:selected { background:#34465d; }
QMenu { background:#29292c; border:1px solid #45454a; padding:5px; }
QMenu::item { padding:7px 25px; }
QToolBar { background:#252526; border:0; spacing:6px; padding:8px; }
QToolBar#tools { border-right:1px solid #38383b; padding:8px 5px; }
QToolButton { border:1px solid transparent; padding:7px; border-radius:4px; }
QToolButton:hover { background:#36363a; }
QToolButton:checked { background:#304c70; border-color:#578ad0; }
QDockWidget { font-weight:600; }
QDockWidget::title { background:#2d2d30; padding:9px 12px; }
QDockWidget::close-button,QDockWidget::float-button { padding:3px; }
QWidget#dockTitleBar { background:#2d2d30; border-bottom:1px solid #38383b; }
QWidget#dockTitleBar QLabel { background:transparent; font-weight:600; }
QWidget#dockWidthGrip { background:transparent; }
QWidget#dockTitleBar QToolButton { padding:3px; border:1px solid transparent; border-radius:4px; }
QWidget#dockTitleBar QToolButton:hover { background:#414147; border-color:#62626b; }
QPushButton { background:#343438; border:1px solid #49494f; border-radius:4px; padding:7px 11px; }
QPushButton:hover { background:#424248; border-color:#707077; }
QPushButton:pressed { background:#242428; }
QPushButton:disabled { color:#77777e; background:#2b2b2e; border-color:#36363a; }
QPushButton[primary=true] { background:#3478cb; border-color:#3478cb; color:white; font-weight:600; }
QPushButton[primary=true]:hover { background:#4489dc; }
QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QPlainTextEdit { background:#1e1e20; border:1px solid #48484d; border-radius:4px; padding:5px 6px; min-height:19px; selection-background-color:#3478cb; }
QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QComboBox:focus { border-color:#5798eb; }
QDoubleSpinBox::up-button,QDoubleSpinBox::down-button { width:0px; height:0px; border:none; }
QComboBox QAbstractItemView { selection-background-color:#304c70; }
QSlider::groove:horizontal { background:#48484e; height:3px; border-radius:1px; }
QSlider::sub-page:horizontal { background:#488bdc; }
QSlider::handle:horizontal { background:#dedee3; border:1px solid #797983; width:11px; margin:-5px 0; border-radius:6px; }
QLabel[muted=true] { color:#aaaab4; }
QLabel[heading=true] { font-size:16px; font-weight:600; }
QListWidget,QTreeWidget,QTableWidget { background:#202022; border:0; alternate-background-color:#28282b; selection-background-color:#304c70; }
QListWidget::item { padding:7px 9px; border-bottom:1px solid #2b2b2e; }
QHeaderView::section { background:#303034; border:0; padding:6px; }
QTabWidget::pane { border:0; }
QTabBar::tab { background:#252526; color:#a9a9b3; padding:9px 14px; border-bottom:2px solid transparent; }
QTabBar::tab:selected { color:#f3f3f5; border-bottom-color:#488bdc; background:#2d2d30; }
QScrollArea { border:0; }
QScrollBar:vertical { background:#252526; width:9px; margin:0; }
QScrollBar::handle:vertical { background:#515158; min-height:25px; border-radius:4px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { height:9px; background:#252526; }
QScrollBar::handle:horizontal { background:#515158; min-width:25px; }
QGroupBox { border:1px solid #424248; border-radius:4px; margin-top:12px; padding-top:12px; }
QGroupBox::title { subcontrol-origin:margin; left:9px; padding:0 5px; }
QStatusBar { background:#252526; border-top:1px solid #38383b; }
QStatusBar QLabel { padding:2px 8px; color:#b8b8c2; }
QCheckBox { spacing:7px; }
QToolTip { background:#35353a; color:#f3f3f5; border:1px solid #62626a; padding:6px; }
QSplitter::handle { background:#38383c; }
QSplitter#filterSplitter::handle { background:#303034; }
QSplitter#filterSplitter::handle:hover { background:#3b414a; }
"""


def _icon_pixmap(name, size, color):
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 24, size / 24)
    p.setPen(
        QPen(
            QColor(color),
            1.6,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    if name == "pan":
        p.drawLine(12, 3, 12, 21)
        p.drawLine(3, 12, 21, 12)
        for a, b, c, d in (
            (12, 3, 9, 6),
            (12, 3, 15, 6),
            (12, 21, 9, 18),
            (12, 21, 15, 18),
            (3, 12, 6, 9),
            (3, 12, 6, 15),
            (21, 12, 18, 9),
            (21, 12, 18, 15),
        ):
            p.drawLine(a, b, c, d)
    elif name == "crop":
        p.drawLine(6, 2, 6, 18)
        p.drawLine(6, 18, 22, 18)
        p.drawLine(2, 6, 18, 6)
        p.drawLine(18, 6, 18, 22)
    elif name in ("rect", "ellipse"):
        p.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.DashLine))
        (p.drawRect if name == "rect" else p.drawEllipse)(QRectF(4, 5, 16, 14))
    elif name == "eyedropper":
        path = QPainterPath()
        path.moveTo(5, 17)
        path.lineTo(15, 7)
        path.lineTo(18, 10)
        path.lineTo(8, 20)
        path.lineTo(4, 21)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(13, 5, 20, 12)
    elif name == "text":
        p.drawLine(4, 5, 20, 5)
        p.drawLine(12, 5, 12, 21)
        p.drawLine(8, 21, 16, 21)
    elif name == "open":
        p.drawPolyline(
            [
                QPoint(x, y)
                for x, y in [
                    (3, 20),
                    (3, 5),
                    (10, 5),
                    (12, 8),
                    (21, 8),
                    (21, 20),
                    (3, 20),
                ]
            ]
        )
    elif name in ("save", "save_as"):
        p.drawRoundedRect(4, 3, 16, 18, 2, 2)
        p.drawRect(8, 3, 8, 6)
        p.drawRect(8, 14, 8, 7)
        if name == "save_as":
            p.save()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(QRectF(13, 12, 10, 11), Qt.GlobalColor.transparent)
            p.restore()
            p.drawLine(18, 14, 18, 22)
            p.drawLine(14, 18, 22, 18)
    elif name == "export":
        p.drawPolyline(
            [QPoint(10, 4), QPoint(4, 4), QPoint(4, 21), QPoint(20, 21), QPoint(20, 14)]
        )
        p.drawLine(11, 13, 21, 3)
        p.drawLine(14, 3, 21, 3)
        p.drawLine(21, 3, 21, 10)
    elif name == "layers":
        p.drawPolygon([QPoint(3, 8), QPoint(12, 3), QPoint(21, 8), QPoint(12, 13)])
        p.drawPolyline([QPoint(3, 12), QPoint(12, 17), QPoint(21, 12)])
        p.drawPolyline([QPoint(3, 16), QPoint(12, 21), QPoint(21, 16)])
    elif name in ("layer_up", "layer_down"):
        if name == "layer_down":
            p.translate(24, 24)
            p.rotate(180)
        p.drawLine(12, 20, 12, 4)
        p.drawPolyline([QPoint(5, 11), QPoint(12, 4), QPoint(19, 11)])
    elif name in ("duplicate", "undock", "redock"):
        if name == "redock":
            p.drawRoundedRect(3, 3, 18, 18, 1, 1)
            p.drawLine(14, 3, 14, 21)
            p.drawRect(QRectF(16, 7, 3, 10))
        else:
            p.drawRoundedRect(3, 8, 13, 13, 1, 1)
            p.drawRoundedRect(8, 3, 13, 13, 1, 1)
    elif name == "exit":
        p.drawPolyline([QPoint(11, 4), QPoint(4, 4), QPoint(4, 20), QPoint(11, 20)])
        p.drawLine(10, 12, 22, 12)
        p.drawLine(17, 7, 22, 12)
        p.drawLine(17, 17, 22, 12)
    elif name in ("rotate_left", "rotate_right"):
        if name == "rotate_right":
            p.translate(24, 0)
            p.scale(-1, 1)
        p.drawArc(5, 5, 15, 15, 145 * 16, -290 * 16)
        p.drawPolyline([QPoint(4, 3), QPoint(4, 9), QPoint(10, 9)])
    elif name in ("flip_horizontal", "flip_vertical"):
        if name == "flip_vertical":
            p.translate(24, 0)
            p.rotate(90)
        p.drawLine(12, 3, 12, 21)
        p.drawPolygon([QPoint(3, 18), QPoint(9, 6), QPoint(9, 18)])
        p.drawPolygon([QPoint(21, 18), QPoint(15, 6), QPoint(15, 18)])
    elif name in ("resize", "fit"):
        for x, y, dx, dy in (
            (3, 3, 1, 1),
            (21, 3, -1, 1),
            (3, 21, 1, -1),
            (21, 21, -1, -1),
        ):
            p.drawLine(x, y, x + dx * 5, y)
            p.drawLine(x, y, x, y + dy * 5)
        if name == "resize":
            p.drawLine(4, 20, 20, 4)
    elif name in ("zoom_in", "zoom_out"):
        p.drawEllipse(QRectF(3, 3, 13, 13))
        p.drawLine(15, 15, 21, 21)
        p.drawLine(6, 9, 13, 9)
        if name == "zoom_in":
            p.drawLine(9, 6, 9, 13)
    elif name == "actual_size":
        p.drawRect(QRectF(4, 4, 16, 16))
        p.drawRect(QRectF(9, 9, 6, 6))
    elif name == "split":
        p.drawRoundedRect(3, 4, 18, 16, 1, 1)
        p.drawLine(12, 2, 12, 22)
        p.drawLine(15, 8, 18, 8)
        p.drawLine(15, 12, 18, 12)
        p.drawLine(15, 16, 18, 16)
    elif name == "panels":
        p.drawRoundedRect(3, 4, 18, 16, 1, 1)
        p.drawLine(15, 4, 15, 20)
        p.drawLine(15, 12, 21, 12)
    elif name == "video":
        p.drawRoundedRect(3, 4, 18, 16, 1, 1)
        p.drawLine(3, 8, 21, 8)
        p.drawLine(7, 4, 10, 8)
        p.drawLine(14, 4, 17, 8)
        p.drawPolygon([QPoint(10, 11), QPoint(10, 17), QPoint(16, 14)])
    elif name == "faces":
        p.drawEllipse(QRectF(8, 4, 8, 8))
        p.drawArc(5, 14, 14, 12, 0, 180 * 16)
        p.drawPolyline([QPoint(3, 8), QPoint(3, 3), QPoint(7, 3)])
        p.drawPolyline([QPoint(17, 3), QPoint(21, 3), QPoint(21, 8)])
    elif name == "image":
        p.drawRoundedRect(3, 4, 18, 16, 1, 1)
        p.drawEllipse(QRectF(6, 7, 3, 3))
        p.drawPolyline(
            [
                QPoint(4, 18),
                QPoint(10, 12),
                QPoint(14, 16),
                QPoint(17, 12),
                QPoint(21, 16),
            ]
        )
    elif name == "science":
        p.drawLine(8, 3, 16, 3)
        p.drawPolyline(
            [
                QPoint(9, 3),
                QPoint(9, 10),
                QPoint(4, 19),
                QPoint(5, 21),
                QPoint(19, 21),
                QPoint(20, 19),
                QPoint(15, 10),
                QPoint(15, 3),
            ]
        )
        p.drawLine(7, 15, 17, 15)
    elif name == "colors":
        for x, y in ((8, 8), (16, 8), (12, 16)):
            p.drawEllipse(QRectF(x - 4, y - 4, 8, 8))
    elif name == "channels":
        for x, y in ((3, 3), (7, 7), (11, 11)):
            p.drawRect(QRectF(x, y, 10, 10))
    elif name == "contrast":
        p.drawEllipse(QRectF(4, 4, 16, 16))
        p.drawLine(12, 4, 12, 20)
        p.drawLine(15, 6, 15, 18)
        p.drawLine(18, 9, 18, 15)
    elif name == "blur":
        for inset in (3, 7, 10):
            p.drawEllipse(QRectF(inset, inset, 24 - 2 * inset, 24 - 2 * inset))
    elif name == "details":
        p.drawPolygon([QPoint(12, 3), QPoint(21, 20), QPoint(3, 20)])
        p.drawLine(12, 3, 12, 20)
    elif name == "edges":
        p.drawPolyline(
            [QPoint(3, 20), QPoint(3, 10), QPoint(10, 10), QPoint(10, 4), QPoint(21, 4)]
        )
        p.drawPolyline(
            [QPoint(8, 20), QPoint(8, 15), QPoint(15, 15), QPoint(15, 9), QPoint(21, 9)]
        )
    elif name == "morphology":
        for x, y in ((9, 3), (3, 9), (9, 9), (15, 9), (9, 15)):
            p.drawRect(QRectF(x, y, 5, 5))
    elif name == "effects":
        p.drawPolygon(
            [
                QPoint(12, 2),
                QPoint(15, 9),
                QPoint(22, 12),
                QPoint(15, 15),
                QPoint(12, 22),
                QPoint(9, 15),
                QPoint(2, 12),
                QPoint(9, 9),
            ]
        )
    elif name == "segment":
        p.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.DashLine))
        p.drawRect(QRectF(3, 3, 18, 18))
        p.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine))
        p.drawPolygon([QPoint(7, 16), QPoint(9, 7), QPoint(17, 10), QPoint(15, 17)])
    elif name == "colormap":
        p.drawRect(QRectF(3, 5, 18, 14))
        for x in (7, 12, 17):
            p.drawLine(x, 5, x, 19)
    elif name == "adjustments":
        for y, x in ((6, 8), (12, 16), (18, 10)):
            p.drawLine(3, y, 21, y)
            p.drawEllipse(QRectF(x - 2, y - 2, 4, 4))
    elif name == "histogram":
        for x, height in ((4, 7), (9, 15), (14, 11), (19, 5)):
            p.drawRect(QRectF(x, 21 - height, 2, height))
    elif name == "history":
        p.drawEllipse(QRectF(4, 4, 16, 16))
        p.drawLine(12, 7, 12, 12)
        p.drawLine(12, 12, 16, 14)
    elif name in ("undo", "redo"):
        if name == "redo":
            p.translate(24, 0)
            p.scale(-1, 1)
        path = QPainterPath()
        path.moveTo(4, 9)
        path.lineTo(13, 9)
        path.cubicTo(23, 9, 23, 20, 14, 20)
        path.lineTo(10, 20)
        p.drawPath(path)
        p.drawLine(4, 9, 9, 4)
        p.drawLine(4, 9, 9, 14)
    elif name == "apply":
        p.drawPolyline([QPoint(5, 12), QPoint(10, 17), QPoint(20, 6)])
    elif name == "discard":
        p.drawLine(6, 6, 18, 18)
        p.drawLine(18, 6, 6, 18)
    elif name == "cut":
        p.drawEllipse(QRectF(3, 14, 5, 5))
        p.drawEllipse(QRectF(14, 14, 5, 5))
        p.drawLine(6, 15, 17, 4)
        p.drawLine(16, 15, 5, 4)
    elif name == "new_layer":
        p.drawRect(QRectF(4, 4, 14, 16))
        p.drawLine(14, 9, 22, 9)
        p.drawLine(18, 5, 18, 13)
    elif name == "invert_selection":
        p.drawRect(QRectF(4, 4, 16, 16))
        p.fillRect(QRectF(5, 5, 7, 14), QColor(color))
        p.setPen(QPen(QColor(color), 1, Qt.PenStyle.DashLine))
        p.drawRect(QRectF(8, 8, 8, 8))
    elif name in ("selection_modify", "selection_transform"):
        p.setPen(QPen(QColor(color), 1, Qt.PenStyle.DashLine))
        p.drawRect(QRectF(5, 5, 14, 14))
        p.setPen(QPen(QColor(color), 1.5))
        for x, y in ((4, 4), (17, 4), (4, 17), (17, 17)):
            p.drawRect(QRectF(x, y, 3, 3))
    elif name == "fill":
        path = QPainterPath()
        path.moveTo(12, 3)
        path.lineTo(20, 11)
        path.lineTo(11, 20)
        path.lineTo(3, 12)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(5, 12, 18, 12)
        p.drawLine(9, 2, 15, 8)
    elif name == "stroke":
        p.drawEllipse(QRectF(4, 4, 16, 16))
        p.setPen(QPen(QColor(color), 1, Qt.PenStyle.DashLine))
        p.drawEllipse(QRectF(7, 7, 10, 10))
    elif name == "deselect":
        p.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.DashLine))
        p.drawRect(QRectF(4, 5, 16, 14))
        p.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine))
        p.drawLine(3, 21, 21, 3)
    else:
        p.drawEllipse(5, 5, 14, 14)
        p.drawLine(12, 8, 12, 16)
        p.drawLine(8, 12, 16, 12)
    p.end()
    return pix


def icon(name):
    """Consistent strokes, explicit disabled state and high-DPI pixmaps."""
    result = QIcon()
    for size in (24, 48):
        for mode, color in (
            (QIcon.Mode.Normal, "#ffffff" if name == "apply" else "#d8d8df"),
            (QIcon.Mode.Disabled, "#707078"),
        ):
            result.addPixmap(_icon_pixmap(name, size, color), mode)
    return result
