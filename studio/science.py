"""Scientific tools retained from the semester project, with a Qt workspace.

The original array is immutable. Each computation runs in a worker and becomes
an editor operation only when the user chooses Apply result.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .services.color import converter_cor, crescer_regiao, histogramas, quantizar
from .services.geometry import area_calibrada, calcular_escala, medir_regiao
from .legacy_filters import (
    BORDAS,
    FORMAS,
    MORFOLOGIA,
    aplicar_morfologia,
    criar_kernel,
    validar_morfologia,
)
from .services.segmentation import segmentar_imagem, sobrepor_contornos

from .advanced_jobs import Job
from .canvas import ImageCanvas
from .io import read_image, write_image


def bgr_or_gray(image):
    if image.ndim == 3 and image.shape[2] == 4:
        return image[:, :, :3].copy()
    return image.copy()


def arithmetic(first, second, operation, weight=0.5, resize_second=False):
    """Saturating OpenCV arithmetic, with explicit second-image alignment."""
    first, second = bgr_or_gray(first), bgr_or_gray(second)
    if first.ndim == 2 and second.ndim == 3:
        second = cv2.cvtColor(second, cv2.COLOR_BGR2GRAY)
    elif first.ndim == 3 and second.ndim == 2:
        second = cv2.cvtColor(second, cv2.COLOR_GRAY2BGR)
    if first.shape != second.shape:
        if not resize_second:
            raise ValueError(
                "As imagens precisam ter as mesmas dimensões. Ative Redimensionar segunda imagem para alinhar."
            )
        second = cv2.resize(
            second, (first.shape[1], first.shape[0]), interpolation=cv2.INTER_AREA
        )
    if operation == "Adição":
        return cv2.add(first, second)
    if operation == "Subtração":
        return cv2.subtract(first, second)
    if operation == "Diferença absoluta":
        return cv2.absdiff(first, second)
    if operation == "Mistura ponderada":
        weight = float(weight)
        if not 0 <= weight <= 1:
            raise ValueError("O peso deve estar entre zero e um.")
        return cv2.addWeighted(first, weight, second, 1 - weight, 0)
    if operation == "Multiplicar":
        return (
            np.rint(first.astype(np.float32) * second / 255)
            .clip(0, 255)
            .astype(np.uint8)
        )
    if operation == "Screen":
        return (
            np.rint(
                255
                - (255 - first.astype(np.float32))
                * (255 - second.astype(np.float32))
                / 255
            )
            .clip(0, 255)
            .astype(np.uint8)
        )
    bitwise = {
        "AND (bit a bit)": cv2.bitwise_and,
        "OR (bit a bit)": cv2.bitwise_or,
        "XOR (bit a bit)": cv2.bitwise_xor,
    }
    if operation in bitwise:
        return bitwise[operation](first, second)
    raise ValueError("Operação aritmética inválida.")


def export_matrix(filename, matrix, model):
    # Passing a file object prevents NumPy from silently appending '.npz'.
    with Path(filename).open("wb") as stream:
        np.savez_compressed(stream, imagem=matrix, modelo=np.asarray(model))


def import_matrix(filename):
    with np.load(filename, allow_pickle=False) as data:
        image, model = data["imagem"].copy(), str(data["modelo"].item())
    converter_cor(image, model, "BGR")  # Shared validation, including channel count.
    return image, model


class HistogramChart(QWidget):
    """Three small line plots without an external plotting dependency."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = {}
        self.setMinimumHeight(115)
        self.setMaximumHeight(155)

    def set_data(self, values):
        self.values = values
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#202022"))
        bounds = QRectF(12, 12, max(1, self.width() - 24), max(1, self.height() - 30))
        painter.setPen(QPen(QColor("#454548"), 1))
        painter.drawRect(bounds)
        if not self.values:
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, "Histograma")
            return
        colors = {
            "R": "#e99494",
            "G": "#86c79b",
            "B": "#83abeb",
            "H": "#b9a1df",
            "S": "#d4bd8d",
            "V": "#94c6c7",
            "Cinza": "#d0d0d0",
        }
        maximum = max(1, max(float(np.max(values)) for values in self.values.values()))
        for name, values in self.values.items():
            path = QPainterPath()
            for index, value in enumerate(values):
                point = QPointF(
                    # All channels share the labeled 0–255 intensity axis.
                    # Hue ends at 179; stretching it to 255 misplaces its bins.
                    bounds.left() + index / 255 * bounds.width(),
                    bounds.bottom() - value / maximum * bounds.height(),
                )
                path.moveTo(point) if index == 0 else path.lineTo(point)
            painter.setPen(QPen(QColor(colors.get(name, "#b0b0b0")), 1.25))
            painter.drawPath(path)
        painter.setPen(QColor("#acacaf"))
        painter.drawText(12, self.height() - 5, "0")
        painter.drawText(self.width() - 30, self.height() - 5, "255")
        painter.drawText(
            38,
            self.height() - 5,
            " / ".join("H (0–179)" if name == "H" else name for name in self.values),
        )


class ScienceCanvas(ImageCanvas):
    """Scientific pointer modes share the editor's zoom and coordinate mapping."""

    strokePoint = Signal(int, int)
    strokeFinished = Signal()

    def mousePressEvent(self, event):
        if (
            self.tool in ("freehand", "brush")
            and event.button() == Qt.MouseButton.LeftButton
            and self.image_rect.contains(event.position())
        ):
            point = self.widget_to_image(event.position(), clamp=True)
            self.strokePoint.emit(int(point.x()), int(point.y()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self.tool in ("freehand", "brush")
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            point = self.widget_to_image(event.position(), clamp=True)
            self.strokePoint.emit(int(point.x()), int(point.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            self.tool in ("freehand", "brush")
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.strokeFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ScienceDialog(QDialog):
    resultReady = Signal(object, str)
    statusMessage = Signal(str)

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Laboratório · OpenCV Studio")
        self.resize(1300, 850)
        self.setMinimumSize(900, 650)
        self._source_alpha = (
            image[:, :, 3].copy() if image.ndim == 3 and image.shape[2] == 4 else None
        )
        self.base = bgr_or_gray(image)
        self.matrix = self.base.copy()
        self.model = "Cinza" if self.base.ndim == 2 else "BGR"
        self.result = self.base.copy()
        self.result_label = "Laboratório"
        self.second_image = None
        self.segmentation = None
        self.corrections = np.full(self.base.shape[:2], -1, np.int8)
        self.measurements = []
        self.measure_points = []
        self.reference_points = []
        self.scale = None
        self._mark_reference = False
        self._drawing = False
        self._stroke_render_pending = False
        self._jobs = {}
        self._histogram_jobs = {}
        self._histogram_generation = 0
        self._histogram_pending = None
        self._closed = False
        self._busy = False
        self._build()
        self._update_histogram()

    def _build(self):
        layout = QVBoxLayout(self)
        heading = QLabel("Laboratório de visão computacional")
        heading.setObjectName("workspaceTitle")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        layout.addWidget(
            QLabel(
                "A imagem de origem é preservada. Execute uma operação, confira o resultado e aplique ao editor."
            )
        )
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(340)
        splitter.addWidget(self.tabs)
        self._arithmetic_tab()
        self._color_tab()
        self._segmentation_tab()
        self._measurement_tab()
        self._morphology_tab()
        self.tabs.currentChanged.connect(self._tab_changed)
        view = QWidget()
        visual = QVBoxLayout(view)
        self.canvas = ScienceCanvas()
        self.canvas.set_images(
            self._with_alpha(self.base), self._with_alpha(self.result)
        )
        self.canvas.pointClicked.connect(self._point_clicked)
        self.canvas.selectionChanged.connect(self._selection_changed)
        self.canvas.strokePoint.connect(self._stroke_point)
        self.canvas.strokeFinished.connect(self._stroke_finished)
        visual.addWidget(self.canvas, 1)
        compare = QHBoxLayout()
        split = QCheckBox("Comparar original / resultado")
        split.toggled.connect(lambda enabled: setattr(self.canvas, "split", enabled))
        compare.addWidget(split)
        fit = QPushButton("Ajustar à tela")
        fit.clicked.connect(self.canvas.fit_to_view)
        compare.addWidget(fit)
        visual.addLayout(compare)
        self.histogram = HistogramChart()
        visual.addWidget(self.histogram)
        splitter.addWidget(view)
        splitter.setSizes([400, 900])
        self.message = QLabel(
            "Pronto. Cada operação parte da imagem de origem, salvo conversões explícitas de matriz."
        )
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        bottom = QHBoxLayout()
        restore = QPushButton("Restaurar cópia da origem")
        restore.clicked.connect(self.restore)
        bottom.addWidget(restore)
        save = QPushButton("Salvar resultado PNG")
        save.clicked.connect(self.save_result)
        bottom.addWidget(save)
        bottom.addStretch()
        close = QPushButton("Fechar")
        close.clicked.connect(self.close)
        bottom.addWidget(close)
        self.apply_button = QPushButton("Aplicar resultado ao editor")
        self.apply_button.setObjectName("accentButton")
        self.apply_button.setProperty("primary", True)
        self.apply_button.clicked.connect(self.apply_result)
        bottom.addWidget(self.apply_button)
        layout.addLayout(bottom)

    def _page(self, title):
        page = QWidget()
        box = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, title)
        return page, box

    @staticmethod
    def _spin(minimum, maximum, value):
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        return widget

    @staticmethod
    def _double(minimum, maximum, value, step=0.1):
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(4)
        widget.setValue(value)
        widget.setSingleStep(step)
        return widget

    def _button(self, layout, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _arithmetic_tab(self):
        _, box = self._page("Aritmética")
        note = QLabel(
            "Adição e subtração saturam em 0 e 255, evitando estouro dos canais de 8 bits."
        )
        note.setWordWrap(True)
        box.addWidget(note)
        self.second_label = QLabel("Segunda imagem: nenhuma")
        self.second_label.setWordWrap(True)
        box.addWidget(self.second_label)
        self._button(box, "Abrir segunda imagem", self.open_second_image)
        form = QFormLayout()
        self.arithmetic_operation = QComboBox()
        self.arithmetic_operation.addItems(
            [
                "Adição",
                "Subtração",
                "Diferença absoluta",
                "Mistura ponderada",
                "Multiplicar",
                "Screen",
                "AND (bit a bit)",
                "OR (bit a bit)",
                "XOR (bit a bit)",
            ]
        )
        self.mix_weight = self._double(0, 1, 0.5)
        self.align_second = QCheckBox("Redimensionar segunda imagem para alinhar")
        self.align_second.setChecked(True)
        form.addRow("Operação", self.arithmetic_operation)
        form.addRow("Peso da origem", self.mix_weight)
        box.addLayout(form)
        box.addWidget(self.align_second)
        self._button(box, "Executar aritmética", self.run_arithmetic)
        box.addStretch()

    def _color_tab(self):
        _, box = self._page("Canais e cor")
        form = QFormLayout()
        self.color_destination = QComboBox()
        self.color_destination.addItems(["RGB", "HSV", "BGR", "Cinza"])
        self.color_state = QLabel("Matriz atual: " + self.model)
        form.addRow("Converter para", self.color_destination)
        box.addWidget(self.color_state)
        box.addLayout(form)
        self._button(box, "Converter matriz", self.convert_color)
        note = QLabel(
            "RGB e HSV são matrizes reais. A visualização converte para a tela; exporte NPZ para preservar os valores e o modelo de cor."
        )
        note.setWordWrap(True)
        box.addWidget(note)
        row = QHBoxLayout()
        self._button(row, "Exportar NPZ", self.save_matrix)
        self._button(row, "Importar NPZ", self.load_matrix)
        box.addLayout(row)
        self.histogram_space = QComboBox()
        self.histogram_space.addItems(["RGB", "HSV", "Cinza"])
        self.histogram_space.currentTextChanged.connect(self._update_histogram)
        form2 = QFormLayout()
        form2.addRow("Histograma", self.histogram_space)
        self.channel = QComboBox()
        self.channel.addItems(["R", "G", "B", "H", "S", "V", "Cinza"])
        form2.addRow("Separar canal", self.channel)
        self.quantization_levels = self._spin(2, 256, 4)
        form2.addRow("Níveis por canal", self.quantization_levels)
        box.addLayout(form2)
        self._button(box, "Exibir canal separado", self.split_channel)
        self._button(box, "Quantizar origem", self.quantize)
        self.channel_table = QTableWidget(0, 5)
        self.channel_table.setHorizontalHeaderLabels(
            ["Canal", "Mín", "Máx", "Média", "Desvio"]
        )
        self.channel_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.channel_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        box.addWidget(self.channel_table, 1)

    def _segmentation_tab(self):
        _, box = self._page("Segmentação")
        form = QFormLayout()
        h, w = self.base.shape[:2]
        self.seed_x, self.seed_y = (
            self._spin(0, w - 1, w // 2),
            self._spin(0, h - 1, h // 2),
        )
        self.region_tolerance = self._spin(0, 255, 15)
        self.region_connectivity = QComboBox()
        self.region_connectivity.addItems(["4", "8"])
        form.addRow("Semente X", self.seed_x)
        form.addRow("Semente Y", self.seed_y)
        form.addRow("Tolerância", self.region_tolerance)
        form.addRow("Conectividade", self.region_connectivity)
        box.addLayout(form)
        note = QLabel(
            "Clique na imagem para marcar a semente. Para GrabCut, selecione a ROI retangular na imagem ou informe os limites abaixo."
        )
        note.setWordWrap(True)
        box.addWidget(note)
        self._button(box, "Crescer região a partir da semente", self.run_region_growing)
        self._button(
            box, "Desenhar ROI do GrabCut", lambda: self.canvas.set_tool("rect")
        )
        roi = QFormLayout()
        self.roi_x = self._spin(0, w - 1, max(0, w // 10))
        self.roi_y = self._spin(0, h - 1, max(0, h // 10))
        self.roi_w = self._spin(1, w, max(1, w * 8 // 10))
        self.roi_h = self._spin(1, h, max(1, h * 8 // 10))
        for label, field in (
            ("ROI X", self.roi_x),
            ("ROI Y", self.roi_y),
            ("Largura", self.roi_w),
            ("Altura", self.roi_h),
        ):
            roi.addRow(label, field)
        self.segment_kernel = self._spin(1, 99, 5)
        self.segment_kernel.setSingleStep(2)
        self.segment_iterations = self._spin(1, 20, 5)
        self.segment_erosion = self._spin(0, 30, 2)
        self.segment_dilation = self._spin(0, 30, 2)
        self.segment_bilateral = self._spin(1, 31, 7)
        self.segment_bilateral.setSingleStep(2)
        self.segment_sigma_color = self._spin(1, 255, 50)
        self.segment_sigma_space = self._spin(1, 255, 50)
        self.segment_closing = self._spin(1, 99, 3)
        self.segment_closing.setSingleStep(2)
        self.segment_closing_iterations = self._spin(0, 30, 1)
        self.min_area = self._spin(1, max(1, h * w), 50 if h * w >= 50 else 1)
        self.only_largest = QCheckBox("Manter somente o maior componente")
        roi.addRow("Kernel ímpar", self.segment_kernel)
        roi.addRow("Iterações", self.segment_iterations)
        roi.addRow("Erosão das sementes", self.segment_erosion)
        roi.addRow("Dilatação das sementes", self.segment_dilation)
        roi.addRow("Bilateral · diâmetro", self.segment_bilateral)
        roi.addRow("Bilateral · sigma cor", self.segment_sigma_color)
        roi.addRow("Bilateral · sigma espaço", self.segment_sigma_space)
        roi.addRow("Kernel de fechamento", self.segment_closing)
        roi.addRow("Iterações de fechamento", self.segment_closing_iterations)
        roi.addRow("Área mínima (px)", self.min_area)
        box.addLayout(roi)
        box.addWidget(self.only_largest)
        brush_form = QFormLayout()
        self.segment_brush = QComboBox()
        self.segment_brush.addItem("Objeto certo", int(cv2.GC_FGD))
        self.segment_brush.addItem("Fundo certo", int(cv2.GC_BGD))
        self.segment_brush.addItem("Objeto provável", int(cv2.GC_PR_FGD))
        self.segment_brush.addItem("Fundo provável", int(cv2.GC_PR_BGD))
        self.segment_brush.addItem("Apagar correções", -1)
        self.segment_brush_radius = self._spin(1, 100, 8)
        brush_form.addRow("Pincel de correção", self.segment_brush)
        brush_form.addRow("Raio do pincel (px)", self.segment_brush_radius)
        box.addLayout(brush_form)
        self._button(box, "Pintar correções no GrabCut", self.begin_segmentation_brush)
        self._button(
            box, "Limpar todas as correções", self.clear_segmentation_corrections
        )
        self._button(box, "Segmentar com GrabCut", self.run_grabcut)
        self.segment_stage = QComboBox()
        self.segment_stage.addItems(
            [
                "Sobreposição",
                "Máscara final",
                "Bilateral",
                "Sementes",
                "Rótulos GrabCut",
                "Binária",
                "Fechamento",
            ]
        )
        self.segment_stage.currentTextChanged.connect(self.show_segment_stage)
        box.addWidget(self.segment_stage)
        self._button(box, "Salvar máscara / sobreposição", self.save_segmentation)
        box.addStretch()

    def _measurement_tab(self):
        _, box = self._page("Medição")
        form = QFormLayout()
        self.measure_shape = QComboBox()
        self.measure_shape.addItems(
            [
                "Retângulo",
                "Quadrado",
                "Elipse",
                "Círculo",
                "Losango",
                "Polígono",
                "Desenho livre",
            ]
        )
        self.measure_shape.currentTextChanged.connect(self._measurement_tool)
        form.addRow("Forma", self.measure_shape)
        self.measure_name = QLineEdit("Região 1")
        form.addRow("Nome", self.measure_name)
        box.addLayout(form)
        note = QLabel(
            "Arraste retângulos/elipses na imagem. Em Polígono, clique nos vértices e adicione a medição. A contagem usa a resolução original."
        )
        note.setWordWrap(True)
        box.addWidget(note)
        self._button(box, "Adicionar medição", self.add_measurement)
        self._button(box, "Limpar pontos do polígono", self.clear_measure_points)
        self._button(box, "Voltar um ponto", self.undo_measure_point)
        calibration = QFormLayout()
        self.reference_distance = self._double(0.0001, 1e9, 10, 1)
        self.reference_unit = QComboBox()
        self.reference_unit.addItems(["mm", "cm", "m", "unidade"])
        calibration.addRow("Distância real", self.reference_distance)
        calibration.addRow("Unidade", self.reference_unit)
        box.addLayout(calibration)
        self._button(
            box, "Calibrar: marcar dois pontos na imagem", self.begin_calibration
        )
        self._button(box, "Remover escala", self.clear_scale)
        self.scale_label = QLabel("Área em pixels. Sem escala física.")
        self.scale_label.setWordWrap(True)
        box.addWidget(self.scale_label)
        self.measure_table = QTableWidget(0, 4)
        self.measure_table.setHorizontalHeaderLabels(
            ["Nome", "Pixels", "% imagem", "Área física"]
        )
        self.measure_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.measure_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.measure_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        box.addWidget(self.measure_table, 1)
        self._button(box, "Excluir medição selecionada", self.remove_measurement)
        self._button(box, "Exportar medições CSV", self.export_measurements)

    def _morphology_tab(self):
        _, box = self._page("Morfologia")
        form = QFormLayout()
        self.morph_operation = QComboBox()
        for operation in MORFOLOGIA:
            self.morph_operation.addItem(
                {"Opening": "Abertura", "Closing": "Fechamento"}.get(
                    operation, operation
                ),
                operation,
            )
        self.kernel_shape = QComboBox()
        self.kernel_shape.addItems(
            [shape for shape in FORMAS if shape != "Personalizado"]
        )
        self.kernel_width, self.kernel_height = (
            self._spin(1, 31, 3),
            self._spin(1, 31, 3),
        )
        form.addRow("Operação", self.morph_operation)
        form.addRow("Forma inicial", self.kernel_shape)
        form.addRow("Colunas", self.kernel_width)
        form.addRow("Linhas", self.kernel_height)
        box.addLayout(form)
        self._button(box, "Gerar matriz de kernel", self.generate_kernel)
        self.kernel_table = QTableWidget(3, 3)
        self.kernel_table.setMaximumHeight(180)
        self.kernel_table.horizontalHeader().setDefaultSectionSize(35)
        self.kernel_table.verticalHeader().setDefaultSectionSize(26)
        box.addWidget(self.kernel_table)
        kernel_note = QLabel(
            "Edite as células: 1 = objeto; 0 = ignorar; −1 = fundo em hit-or-miss."
        )
        kernel_note.setWordWrap(True)
        box.addWidget(kernel_note)
        parameters = QFormLayout()
        self.anchor_x, self.anchor_y = self._spin(-1, 30, -1), self._spin(-1, 30, -1)
        self.morph_iterations = self._spin(1, 30, 1)
        self.morph_border = QComboBox()
        self.morph_border.addItems(list(BORDAS))
        self.morph_mode = QComboBox()
        self.morph_mode.addItems(["Colorida", "Cinza", "Binária"])
        self.morph_threshold = self._spin(0, 255, 127)
        for label, field in (
            ("Âncora X (−1 = centro)", self.anchor_x),
            ("Âncora Y (−1 = centro)", self.anchor_y),
            ("Iterações", self.morph_iterations),
            ("Borda", self.morph_border),
            ("Modo", self.morph_mode),
            ("Limiar", self.morph_threshold),
        ):
            parameters.addRow(label, field)
        box.addLayout(parameters)
        self._button(box, "Executar morfologia", self.run_morphology)
        config = QHBoxLayout()
        self._button(config, "Salvar kernel JSON", self.save_kernel)
        self._button(config, "Abrir kernel JSON", self.load_kernel)
        box.addLayout(config)
        box.addStretch()
        self.generate_kernel()

    def _notify(self, message, error=False):
        self.message.setText(message)
        self.message.setStyleSheet("color:#f1b4a8;" if error else "color:#b7c6d8;")
        self.statusMessage.emit(message)

    def _work(self, function, callback, label):
        if self._busy or self._closed:
            self._notify("Aguarde o processamento atual terminar.")
            return
        self._busy = True
        self.apply_button.setEnabled(False)
        self._notify(label + "…")
        job = Job(function)
        self._jobs[job.identifier] = (job, callback)
        job.signals.completed.connect(self._job_finished)
        QThreadPool.globalInstance().start(job)

    @Slot(int, object, str)
    def _job_finished(self, identifier, result, error):
        entry = self._jobs.pop(identifier, None)
        self._busy = False
        if self._closed or entry is None:
            return
        self.apply_button.setEnabled(True)
        if error:
            self._notify(error, True)
        else:
            try:
                entry[1](result)
            except (ValueError, OSError, cv2.error, KeyError, TypeError) as exc:
                self._notify(str(exc), True)

    def _set_result(self, image, label, matrix=None, model=None):
        self.result = image.copy()
        self.matrix = image.copy() if matrix is None else matrix.copy()
        self.model = model or ("Cinza" if image.ndim == 2 else "BGR")
        self.result_label = label
        self.color_state.setText("Matriz atual: " + self.model)
        self.canvas.set_images(
            self._with_alpha(self.base), self._with_alpha(self.result)
        )
        self._update_histogram()
        self._notify(label + " concluído. Confira a imagem e aplique ao editor.")

    def restore(self):
        if not self._busy:
            self._set_result(self.base, "Cópia independente da origem")

    def open_second_image(self, filename=None):
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getOpenFileName(
                self,
                "Segunda imagem",
                "",
                "Imagens (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)",
            )
        if filename:

            def done(image):
                self.second_image = image
                self.second_label.setText(
                    f"{Path(filename).name} · {image.shape[1]} × {image.shape[0]}"
                )
                self._notify("Segunda imagem carregada para aritmética.")

            self._work(lambda: read_image(filename), done, "Lendo segunda imagem")

    def run_arithmetic(self):
        if self.second_image is None:
            self._notify("Abra uma segunda imagem para executar a operação.", True)
            return
        operation, weight, resize = (
            self.arithmetic_operation.currentText(),
            self.mix_weight.value(),
            self.align_second.isChecked(),
        )
        self._work(
            lambda: arithmetic(self.base, self.second_image, operation, weight, resize),
            lambda image: self._set_result(image, operation),
            operation,
        )

    def convert_color(self):
        destination, matrix, model = (
            self.color_destination.currentText(),
            self.matrix.copy(),
            self.model,
        )

        def convert():
            converted = converter_cor(matrix, model, destination)
            return converted, converter_cor(converted, destination, "BGR")

        self._work(
            convert,
            lambda data: self._set_result(
                data[1], f"Conversão {model} → {destination}", data[0], destination
            ),
            "Convertendo modelo de cor",
        )

    def save_matrix(self, filename=None):
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Exportar matriz", "matriz.npz", "NumPy (*.npz)"
            )
        if filename:
            matrix, model = self.matrix.copy(), self.model
            self._work(
                lambda: export_matrix(filename, matrix, model),
                lambda _: self._notify(f"Matriz {model} salva em {filename}."),
                "Exportando matriz",
            )

    def load_matrix(self, filename=None):
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getOpenFileName(
                self, "Importar matriz", "", "NumPy (*.npz)"
            )
        if filename:

            def done(data):
                matrix, model = data
                if matrix.shape[:2] != self.base.shape[:2]:
                    raise ValueError(
                        "A matriz importada deve ter as dimensões da imagem deste laboratório."
                    )
                self._set_result(
                    converter_cor(matrix, model, "BGR"),
                    f"Matriz {model} importada",
                    matrix,
                    model,
                )

            self._work(lambda: import_matrix(filename), done, "Importando matriz")

    def split_channel(self):
        channel = self.channel.currentText()
        space = "Cinza" if channel == "Cinza" else "HSV" if channel in "HSV" else "RGB"

        def split():
            converted = converter_cor(
                self.base, "Cinza" if self.base.ndim == 2 else "BGR", space
            )
            return (
                converted.copy()
                if converted.ndim == 2
                else converted[:, :, space.index(channel)].copy()
            )

        self._work(
            split,
            lambda image: self._set_result(image, "Canal " + channel),
            "Separando canal",
        )

    def quantize(self):
        levels = self.quantization_levels.value()
        self._work(
            lambda: quantizar(self.base, levels),
            lambda image: self._set_result(image, f"Quantização · {levels} níveis"),
            "Quantizando",
        )

    def _update_histogram(self):
        if not hasattr(self, "histogram"):
            return
        space = self.histogram_space.currentText()
        matrix, model = self.matrix, self.model
        self._histogram_generation += 1
        generation = self._histogram_generation
        self._histogram_pending = (matrix, model, space, generation)
        if not self._histogram_jobs:
            self._start_histogram()

    def _start_histogram(self):
        if self._closed or self._histogram_pending is None:
            return
        matrix, model, space, generation = self._histogram_pending
        self._histogram_pending = None

        def compute():
            counts = histogramas(matrix, model, space)
            data = converter_cor(matrix, model, space)
            channels = (data,) if data.ndim == 2 else cv2.split(data)
            names = ("Cinza",) if data.ndim == 2 else tuple(space)
            rows = [
                (
                    name,
                    int(values.min()),
                    int(values.max()),
                    f"{values.mean():.2f}",
                    f"{values.std():.2f}",
                )
                for name, values in zip(names, channels)
            ]
            return generation, counts, rows

        job = Job(compute)
        self._histogram_jobs[job.identifier] = job
        job.signals.completed.connect(self._histogram_finished)
        QThreadPool.globalInstance().start(job)

    @Slot(int, object, str)
    def _histogram_finished(self, identifier, result, error):
        self._histogram_jobs.pop(identifier, None)
        if self._closed:
            self._histogram_pending = None
            return
        if self._histogram_pending is not None:
            self._start_histogram()
        if error:
            return
        generation, counts, rows = result
        if generation != self._histogram_generation:
            return
        self.histogram.set_data(counts)
        self.channel_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for col, value in enumerate(values):
                self.channel_table.setItem(row, col, QTableWidgetItem(str(value)))

    def run_region_growing(self):
        seed = (self.seed_x.value(), self.seed_y.value())
        tolerance, connectivity = (
            self.region_tolerance.value(),
            int(self.region_connectivity.currentText()),
        )

        def grow():
            mask = crescer_regiao(self.base, seed, tolerance, connectivity)
            return mask, int(np.count_nonzero(mask))

        def done(result):
            mask, pixels = result
            self.segmentation = {
                "mascara": mask,
                "sobreposicao": sobrepor_contornos(self.base, mask),
                "pixels": pixels,
                "regioes": [],
            }
            self._set_result(mask, "Crescimento de regiões")
            self._notify(
                f"Região conectada: {pixels:,} pixels; semente {seed}, tolerância {tolerance}, conectividade {connectivity}."
            )

        self._work(grow, done, "Crescendo região")

    def run_grabcut(self):
        h, w = self.base.shape[:2]
        x, y, rw, rh = (
            self.roi_x.value(),
            self.roi_y.value(),
            self.roi_w.value(),
            self.roi_h.value(),
        )
        kernel = self.segment_kernel.value()
        if kernel % 2 == 0:
            self._notify("O kernel da segmentação precisa ser ímpar.", True)
            return
        roi = np.zeros((h, w), np.uint8)
        roi[y : min(h, y + rh), x : min(w, x + rw)] = 255
        options = {
            "kernel": kernel,
            "iteracoes": self.segment_iterations.value(),
            "area_minima": self.min_area.value(),
            "maior_componente": self.only_largest.isChecked(),
            "erosao": self.segment_erosion.value(),
            "dilatacao": self.segment_dilation.value(),
            "bilateral_d": self.segment_bilateral.value(),
            "sigma_cor": self.segment_sigma_color.value(),
            "sigma_espaco": self.segment_sigma_space.value(),
            "fechamento": self.segment_closing.value(),
            "fechamento_iteracoes": self.segment_closing_iterations.value(),
        }
        corrections = self.corrections.copy()

        def done(result):
            self.segmentation = result
            self.show_segment_stage()
            self._notify(
                f"GrabCut: {result['pixels']:,} pixels, {len(result['regioes'])} componente(s), {result['removidos']} fragmento(s) removido(s)."
            )

        self._work(
            lambda: segmentar_imagem(self.base, roi, options, correcoes=corrections),
            done,
            "Segmentando com GrabCut",
        )

    def begin_segmentation_brush(self):
        self.canvas.set_tool("brush")
        self._show_brush_overlay()
        self._notify(
            "Pinte sobre a imagem para corrigir as sementes; depois execute GrabCut."
        )

    def clear_segmentation_corrections(self):
        self.corrections.fill(-1)
        self._show_brush_overlay()
        self._notify("Correções manuais removidas.")

    def _stroke_point(self, x, y):
        if self.canvas.tool == "freehand":
            if not self._drawing:
                self.measure_points.clear()
                self._drawing = True
            if (
                not self.measure_points
                or (x - self.measure_points[-1][0]) ** 2
                + (y - self.measure_points[-1][1]) ** 2
                >= 4
            ):
                self.measure_points.append((x, y))
        elif self.canvas.tool == "brush":
            radius = self.segment_brush_radius.value()
            h, w = self.corrections.shape
            x0, x1 = max(0, x - radius), min(w, x + radius + 1)
            y0, y1 = max(0, y - radius), min(h, y + radius + 1)
            yy, xx = np.ogrid[y0:y1, x0:x1]
            self.corrections[y0:y1, x0:x1][
                (xx - x) ** 2 + (yy - y) ** 2 <= radius**2
            ] = self.segment_brush.currentData()
        if not self._stroke_render_pending:
            self._stroke_render_pending = True
            QTimer.singleShot(33, self._render_stroke)

    def _render_stroke(self):
        self._stroke_render_pending = False
        if self._closed:
            return
        if self.canvas.tool == "brush":
            self._show_brush_overlay()
        elif self.canvas.tool == "freehand":
            self._draw_measurements()

    def _stroke_finished(self):
        self._drawing = False
        self._render_stroke()
        if self.canvas.tool == "freehand":
            self._notify(
                f"Contorno livre com {len(self.measure_points)} pontos. Adicione a medição para fechar a área."
            )

    def _show_brush_overlay(self):
        image = (
            cv2.cvtColor(self.base, cv2.COLOR_GRAY2BGR)
            if self.base.ndim == 2
            else self.base.copy()
        )
        palette = np.array(
            [[50, 75, 230], [90, 215, 100], [80, 145, 220], [160, 210, 110]], np.uint8
        )
        corrected = self.corrections >= 0
        image[corrected] = (
            image[corrected].astype(np.float32) * 0.45
            + palette[self.corrections[corrected]] * 0.55
        ).astype(np.uint8)
        self.canvas.set_images(self._with_alpha(self.base), self._with_alpha(image))

    def show_segment_stage(self):
        if self.segmentation is None:
            return
        stage = {
            "Sobreposição": "sobreposicao",
            "Máscara final": "mascara",
            "Bilateral": "suavizada",
            "Sementes": "sementes",
            "Rótulos GrabCut": "rotulos",
            "Binária": "binaria",
            "Fechamento": "fechada",
        }[self.segment_stage.currentText()]
        if stage not in self.segmentation:
            self._notify("Essa etapa está disponível após executar GrabCut.")
            return
        image = self.segmentation[stage]
        if stage in ("sementes", "rotulos"):
            palette = np.array(
                [[15, 15, 15], [230, 230, 230], [200, 100, 45], [40, 180, 230]],
                np.uint8,
            )
            image = palette[image]
        self._set_result(image, "Segmentação · " + self.segment_stage.currentText())

    def save_segmentation(self, filename=None):
        if self.segmentation is None:
            self._notify("Execute uma segmentação primeiro.", True)
            return
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Salvar máscara e sobreposição", "segmentacao.png", "PNG (*.png)"
            )
        if filename:
            path = Path(filename)
            mask, overlay = (
                self.segmentation["mascara"].copy(),
                self.segmentation["sobreposicao"].copy(),
            )

            def save():
                write_image(path, mask)
                write_image(path.with_name(path.stem + "_sobreposicao.png"), overlay)

            self._work(
                save,
                lambda _: self._notify("Máscara e sobreposição salvas."),
                "Salvando segmentação",
            )

    def _tab_changed(self, index):
        if not hasattr(self, "canvas"):
            return
        self._mark_reference = False
        title = self.tabs.tabText(index)
        if title == "Medição":
            self._measurement_tool()
        elif title == "Segmentação":
            self.canvas.set_tool("point")
        else:
            self.canvas.set_tool("pan")

    def _point_clicked(self, x, y):
        if self._mark_reference:
            self.reference_points.append((x, y))
            if len(self.reference_points) == 2:
                try:
                    self.scale = calcular_escala(
                        self.reference_points, self.reference_distance.value()
                    )
                    self._mark_reference = False
                    self.scale_label.setText(
                        f"Escala: {self.scale:.6g} {self.reference_unit.currentText()}/pixel. Área física estimada da projeção visível."
                    )
                    self._refresh_measurements()
                    self._notify("Escala calibrada pelos dois pontos.")
                except ValueError as exc:
                    self.reference_points.clear()
                    self._notify(str(exc), True)
            else:
                self._notify(
                    "Primeiro ponto marcado. Clique no segundo ponto da referência."
                )
            return
        if (
            self.tabs.tabText(self.tabs.currentIndex()) == "Medição"
            and self.measure_shape.currentText() == "Polígono"
        ):
            self.measure_points.append((x, y))
            self._draw_measurements()
            self._notify(
                f"Polígono: {len(self.measure_points)} vértices. Adicione a medição para fechar o contorno."
            )
        else:
            self.seed_x.setValue(x)
            self.seed_y.setValue(y)

    def _selection_changed(self, selection):
        if selection:
            x, y, w, h = selection["rect"]
            self.roi_x.setValue(x)
            self.roi_y.setValue(y)
            self.roi_w.setValue(w)
            self.roi_h.setValue(h)

    def _measurement_tool(self):
        if not hasattr(self, "canvas"):
            return
        shape = self.measure_shape.currentText()
        self.canvas.set_tool(
            "freehand"
            if shape == "Desenho livre"
            else "point"
            if shape == "Polígono"
            else "ellipse"
            if shape in ("Elipse", "Círculo")
            else "rect"
        )

    def add_measurement(self):
        try:
            shape = self.measure_shape.currentText()
            if shape in ("Polígono", "Desenho livre"):
                region = medir_regiao(
                    self.base.shape, shape, pontos=self.measure_points
                )
            else:
                selection = self.canvas.selection
                if not selection:
                    raise ValueError("Selecione uma região na imagem primeiro.")
                x, y, w, h = selection["rect"]
                region = medir_regiao(self.base.shape, shape, (x, y), (x + w, y + h))
            region["nome"] = (
                self.measure_name.text().strip()
                or f"Região {len(self.measurements) + 1}"
            )
            self.measurements.append(region)
            self.measure_points.clear()
            self.measure_name.setText(f"Região {len(self.measurements) + 1}")
            self._refresh_measurements()
            self._draw_measurements()
            self._notify(f"Medição adicionada: {region['pixels']:,} pixels.")
        except (ValueError, TypeError) as exc:
            self._notify(str(exc), True)

    def clear_measure_points(self):
        self.measure_points.clear()
        self._draw_measurements()

    def undo_measure_point(self):
        if self.measure_points:
            self.measure_points.pop()
            self._draw_measurements()
        else:
            self._notify("Não há vértices para remover.")

    def begin_calibration(self):
        self.reference_points.clear()
        self._mark_reference = True
        self.canvas.set_tool("point")
        self._notify(
            "Clique em dois pontos cuja distância real corresponde ao valor informado."
        )

    def clear_scale(self):
        self.scale = None
        self.reference_points.clear()
        self._mark_reference = False
        self.scale_label.setText("Área em pixels. Sem escala física.")
        self._refresh_measurements()

    def _refresh_measurements(self):
        total = self.base.shape[0] * self.base.shape[1]
        self.measure_table.setRowCount(len(self.measurements))
        for row, region in enumerate(self.measurements):
            area = area_calibrada(region["pixels"], self.scale)
            values = (
                region["nome"],
                region["pixels"],
                f"{100 * region['pixels'] / total:.3f}%",
                "—"
                if area is None
                else f"{area:.6g} {self.reference_unit.currentText()}²",
            )
            for col, value in enumerate(values):
                self.measure_table.setItem(row, col, QTableWidgetItem(str(value)))

    def _draw_measurements(self):
        canvas = (
            cv2.cvtColor(self.base, cv2.COLOR_GRAY2BGR)
            if self.base.ndim == 2
            else self.base.copy()
        )
        for region in self.measurements:
            x0, y0, x1, y1 = region["limites"]
            shape = region["forma"]
            if shape in ("Polígono", "Desenho livre"):
                cv2.polylines(
                    canvas,
                    [np.asarray(region["pontos"], np.int32)],
                    True,
                    (90, 200, 140),
                    2,
                )
            elif shape in ("Elipse", "Círculo"):
                cv2.ellipse(
                    canvas,
                    ((x0 + x1) // 2, (y0 + y1) // 2),
                    (max(1, (x1 - x0) // 2), max(1, (y1 - y0) // 2)),
                    0,
                    0,
                    360,
                    (90, 200, 140),
                    2,
                )
            elif shape == "Losango":
                vertices = np.asarray(
                    [
                        ((x0 + x1) // 2, y0),
                        (x1, (y0 + y1) // 2),
                        ((x0 + x1) // 2, y1),
                        (x0, (y0 + y1) // 2),
                    ],
                    np.int32,
                )
                cv2.polylines(canvas, [vertices], True, (90, 200, 140), 2)
            else:
                cv2.rectangle(canvas, (x0, y0), (x1 - 1, y1 - 1), (90, 200, 140), 2)
        if self.measure_points:
            points = np.asarray(self.measure_points, np.int32)
            cv2.polylines(canvas, [points], False, (80, 170, 240), 2)
            for x, y in self.measure_points:
                cv2.circle(canvas, (x, y), 3, (80, 170, 240), -1)
        selection = self.canvas.selection
        self._set_result(canvas, "Medições anotadas")
        self.canvas.selection = selection

    def remove_measurement(self):
        row = self.measure_table.currentRow()
        if row >= 0:
            self.measurements.pop(row)
            self._refresh_measurements()
            self._draw_measurements()
        else:
            self._notify("Selecione uma medição na tabela.")

    def export_measurements(self, filename=None):
        if not self.measurements:
            self._notify("Adicione uma medição antes de exportar.", True)
            return
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Exportar medições", "medicoes.csv", "CSV (*.csv)"
            )
        if filename:
            try:
                with Path(filename).open(
                    "w", newline="", encoding="utf-8-sig"
                ) as stream:
                    writer = csv.writer(stream, delimiter=";")
                    writer.writerow(
                        [
                            "Nome",
                            "Forma",
                            "Pixels",
                            "Percentual_imagem",
                            "Area_fisica_estimada",
                            "Unidade_area",
                            "Escala_unidade_por_pixel",
                        ]
                    )
                    total = self.base.shape[0] * self.base.shape[1]
                    for region in self.measurements:
                        area = area_calibrada(region["pixels"], self.scale)
                        writer.writerow(
                            [
                                region["nome"],
                                region["forma"],
                                region["pixels"],
                                100 * region["pixels"] / total,
                                "" if area is None else area,
                                ""
                                if area is None
                                else self.reference_unit.currentText() + "²",
                                self.scale or "",
                            ]
                        )
                self._notify(f"Medições exportadas em {filename}.")
            except OSError as exc:
                self._notify(str(exc), True)

    def generate_kernel(self):
        kernel = criar_kernel(
            self.kernel_shape.currentText(),
            self.kernel_width.value(),
            self.kernel_height.value(),
        )
        self.kernel_table.setRowCount(kernel.shape[0])
        self.kernel_table.setColumnCount(kernel.shape[1])
        for y in range(kernel.shape[0]):
            for x in range(kernel.shape[1]):
                self.kernel_table.setItem(y, x, QTableWidgetItem(str(kernel[y, x])))

    def kernel_config(self):
        try:
            kernel = [
                [
                    int(self.kernel_table.item(y, x).text())
                    for x in range(self.kernel_table.columnCount())
                ]
                for y in range(self.kernel_table.rowCount())
            ]
        except (ValueError, AttributeError):
            raise ValueError("Cada célula do kernel deve conter −1, 0 ou 1.") from None
        config = {
            "kernel": kernel,
            "anchor": (self.anchor_x.value(), self.anchor_y.value()),
            "iterations": self.morph_iterations.value(),
            "border": self.morph_border.currentText(),
            "mode": self.morph_mode.currentText(),
            "threshold": self.morph_threshold.value(),
        }
        return validar_morfologia(config)

    def run_morphology(self):
        try:
            config = self.kernel_config()
        except ValueError as exc:
            self._notify(str(exc), True)
            return
        operation = self.morph_operation.currentData()
        self._work(
            lambda: aplicar_morfologia(self.base, operation, config),
            lambda image: self._set_result(image, "Morfologia · " + operation),
            "Aplicando morfologia",
        )

    def save_kernel(self, filename=None):
        try:
            config = self.kernel_config()
            config["kernel"] = config["kernel"].tolist()
            if isinstance(filename, bool) or filename is None:
                filename, _ = QFileDialog.getSaveFileName(
                    self, "Salvar kernel", "kernel.json", "JSON (*.json)"
                )
            if filename:
                Path(filename).write_text(
                    json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                self._notify("Matriz e parâmetros morfológicos salvos.")
        except (ValueError, OSError) as exc:
            self._notify(str(exc), True)

    def load_kernel(self, filename=None):
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getOpenFileName(
                self, "Abrir kernel", "", "JSON (*.json)"
            )
        if filename:
            try:
                config = validar_morfologia(
                    json.loads(Path(filename).read_text(encoding="utf-8"))
                )
                kernel = config["kernel"]
                self.kernel_width.setValue(kernel.shape[1])
                self.kernel_height.setValue(kernel.shape[0])
                self.kernel_table.setRowCount(kernel.shape[0])
                self.kernel_table.setColumnCount(kernel.shape[1])
                for y in range(kernel.shape[0]):
                    for x in range(kernel.shape[1]):
                        self.kernel_table.setItem(
                            y, x, QTableWidgetItem(str(kernel[y, x]))
                        )
                self.anchor_x.setValue(config["anchor"][0])
                self.anchor_y.setValue(config["anchor"][1])
                self.morph_iterations.setValue(config["iterations"])
                self.morph_border.setCurrentText(config["border"])
                self.morph_mode.setCurrentText(config["mode"])
                self.morph_threshold.setValue(config["threshold"])
                self._notify("Kernel e parâmetros carregados.")
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self._notify(str(exc), True)

    def save_result(self, filename=None):
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Salvar resultado", "laboratorio.png", "PNG (*.png)"
            )
        if filename:
            image = self._with_alpha(self.result)
            self._work(
                lambda: write_image(filename, image),
                lambda _: self._notify(f"Resultado salvo em {filename}."),
                "Salvando resultado",
            )

    def apply_result(self):
        if not self._busy:
            self.resultReady.emit(self._with_alpha(self.result), self.result_label)
            self.accept()

    def _with_alpha(self, image):
        if self._source_alpha is None:
            return image.copy()
        color = (
            cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            if image.ndim == 2
            else image[:, :, :3]
        )
        return np.dstack((color, self._source_alpha))

    def done(self, result):
        self._closed = True
        super().done(result)

    def closeEvent(self, event):
        self._closed = True
        super().closeEvent(event)
