"""Janela de edição: ações, painéis, documento e coordenação dos workers."""

from pathlib import Path
import copy
from PySide6.QtCore import Qt, QTimer, QSize, QThreadPool
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QColor
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolBar,
    QDockWidget,
    QScrollArea,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QCheckBox,
    QStackedWidget,
    QTabWidget,
    QFileDialog,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QInputDialog,
    QColorDialog,
    QProgressBar,
    QSizePolicy,
)
from studio.canvas import ImageCanvas
from studio.document import Document, Operation
from studio.filters import (
    FILTERS,
    FILTER_PARAMETERS,
    ADJUSTMENTS,
    PRESETS,
    render_pipeline,
    output_size,
)
from studio.io import read_image, write_image
from studio.workers import RenderController, Job
from studio.ui.widgets import (
    AdjustmentControl,
    HistogramWidget,
    CurveWidget,
    DockTitleBar,
    FilterSplitter,
)
from studio.ui.theme import FILTER_CATEGORY_ICONS, icon
from studio.ui.layers import LayerPanel
from studio.ui.layer_actions import LayerActions
from studio.ui.project_actions import ProjectActions
from studio.ui.selection_actions import SelectionActions

IMAGE_TYPES = (
    "Imagens (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff);;Todos os arquivos (*)"
)


class MainWindow(SelectionActions, LayerActions, ProjectActions, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenCV Studio")
        self.resize(1440, 900)
        self.setMinimumSize(980, 660)
        self.document = Document()
        self.result = None
        self.modified = False
        self.project_path = None
        self._layer_preview = None
        self._layer_drag = None
        self._syncing_layers = False
        self.edit_index = None
        self.edit_selection = None
        self.jobs = []
        # Preserve save order even when a previous full-resolution render is slow.
        self.export_pool = QThreadPool(self)
        self.export_pool.setMaxThreadCount(1)
        self.child_windows = []
        self.filter_controls = []
        self.filter_active = False
        self._loading_controls = False
        self._load_generation = 0
        self._fit_next = False
        self.renderer = RenderController(self)
        self.renderer.ready.connect(self._rendered)
        self.renderer.failed.connect(self.error)
        self.renderer.busyChanged.connect(self._busy)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(90)
        self.debounce.timeout.connect(lambda: self.request_render(True))
        self.full_debounce = QTimer(self)
        self.full_debounce.setSingleShot(True)
        self.full_debounce.setInterval(320)
        self.full_debounce.timeout.connect(self._idle_full_render)
        self._render_sizes = {}
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.canvas = ImageCanvas()
        self.stack.addWidget(self.canvas)
        from studio.group_faces import GroupFacePanel
        from studio.video import VideoPanel

        self.faces = GroupFacePanel(get_image=lambda: self.result)
        self.video = VideoPanel(
            process_face=lambda frame: self.faces.process_frame(frame, record_attendance=False),
            process_live_face=self.faces.process_frame,
        )
        self.faces.set_frame_provider(self.video.get_frame)
        self.faces.liveCameraRequested.connect(self.start_group_camera)
        self.video.frameReady.connect(self.open_video_frame)
        self.stack.addWidget(self.video)
        self.stack.addWidget(self.faces)
        for panel in (self.faces, self.video):
            panel.statusMessage.connect(
                lambda message, p=panel: (
                    self.status(message) if self.stack.currentWidget() is p else None
                )
            )
        self.canvas.zoomChanged.connect(self._zoom_changed)
        self.canvas.cursorChanged.connect(self._cursor)
        self.canvas.fileDropped.connect(self.open_path)
        self.canvas.contextRequested.connect(self.show_canvas_menu)
        self.canvas.cropRequested.connect(self.apply_crop)
        self.canvas.textRequested.connect(self.add_text)
        self.canvas.layerDragStarted.connect(self.start_layer_drag)
        self.canvas.layerDragMoved.connect(self.move_layer_drag)
        self.canvas.layerDragFinished.connect(self.finish_layer_drag)
        self.canvas.selectionChanged.connect(
            lambda _: self.request_render(True) if self.has_draft() else None
        )
        if hasattr(self.canvas, "colorPicked"):
            self.canvas.colorPicked.connect(
                lambda c: self.status(f"Cor: RGB {tuple(c)}")
            )
        self._menus()
        self._toolbars()
        self._panels()
        self._statusbar()
        self.setAcceptDrops(True)
        self._update_history()
        self._document_actions(False)

    def status(self, text):
        self.statusBar().showMessage(str(text), 10000)

    def error(self, text):
        self.status(str(text))
        QMessageBox.warning(self, "OpenCV Studio", str(text))

    def _action(self, text, slot, shortcut=None, checkable=False, icon_name=None):
        action = QAction(text, self)
        if icon_name:
            action.setIcon(icon(icon_name))
            action.setIconVisibleInMenu(True)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        return action

    def _menus(self):
        bar = self.menuBar()
        self.image_actions = []
        file = bar.addMenu("Arquivo")
        self.open_action = self._action(
            "Abrir…", self.open_dialog, "Ctrl+O", icon_name="open"
        )
        file.addAction(self.open_action)
        self.save_action = self._action("Salvar", self.save, "Ctrl+S", icon_name="save")
        file.addAction(self.save_action)
        self.save_as_action = self._action(
            "Salvar como…", lambda: self.save(True), "Ctrl+Shift+S", icon_name="save_as"
        )
        file.addAction(self.save_as_action)
        self.export_action = self._action(
            "Exportar…", self.export_dialog, "Ctrl+Alt+S", icon_name="export"
        )
        file.addAction(self.export_action)
        self.add_layer_action = self._action(
            "Adicionar imagens como camadas…",
            self.import_layers,
            "Ctrl+Alt+O",
            icon_name="layers",
        )
        file.addAction(self.add_layer_action)
        file.addAction(
            self._action(
                "Abrir projeto com camadas…",
                self.open_project,
                "Ctrl+Shift+O",
                icon_name="layers",
            )
        )
        file.addAction(
            self._action(
                "Salvar projeto com camadas…",
                lambda: self.save_project(True),
                "Ctrl+Alt+P",
                icon_name="save_as",
            )
        )
        file.addSeparator()
        file.addAction(
            self._action("Duplicar documento", self.duplicate, icon_name="duplicate")
        )
        file.addSeparator()
        file.addAction(self._action("Sair", self.close, "Ctrl+Q", icon_name="exit"))
        edit = bar.addMenu("Editar")
        self.undo_action = self._action(
            "Desfazer", self.undo, "Ctrl+Z", icon_name="undo"
        )
        edit.addAction(self.undo_action)
        self.redo_action = self._action(
            "Refazer", self.redo, "Ctrl+Shift+Z", icon_name="redo"
        )
        edit.addAction(self.redo_action)
        edit.addSeparator()
        edit.addAction(
            self._action(
                "Aplicar prévia", self.apply_draft, "Ctrl+Return", icon_name="apply"
            )
        )
        edit.addAction(
            self._action(
                "Descartar prévia", self.discard_preview, "Escape", icon_name="discard"
            )
        )
        edit.addAction(
            self._action(
                "Limpar seleção",
                self.canvas.clear_selection,
                "Ctrl+D",
                icon_name="deselect",
            )
        )
        selection_menu = edit.addMenu(icon("rect"), "Seleção e camadas")
        selection_menu.aboutToShow.connect(
            lambda: self._populate_selection_menu(selection_menu)
        )
        for title, slot, shortcut, symbol in (
            ("Selecionar tudo", self.select_all, "Ctrl+A", "rect"),
            (
                "Inverter seleção",
                lambda: self.modify_selection("invert"),
                "Ctrl+Shift+I",
                "invert_selection",
            ),
            (
                "Camada via cópia",
                lambda: self.edit_selection_pixels("copy"),
                "Ctrl+J",
                "duplicate",
            ),
            (
                "Camada por corte",
                lambda: self.edit_selection_pixels("cut"),
                "Ctrl+Shift+J",
                "cut",
            ),
            (
                "Nova camada transparente",
                self.new_empty_layer,
                "Ctrl+Shift+N",
                "new_layer",
            ),
            (
                "Transformação livre da camada…",
                self.transform_layer_dialog,
                "Ctrl+T",
                "resize",
            ),
            (
                "Apagar pixels selecionados",
                lambda: self.edit_selection_pixels("delete"),
                "Delete",
                "discard",
            ),
        ):
            self.addAction(self._action(title, slot, shortcut, icon_name=symbol))
        image = bar.addMenu("Imagem")
        for text, slot, icon_name in (
            ("Redimensionar…", self.resize_dialog, "resize"),
            (
                "Girar 90° à direita",
                lambda: self.commit(Operation("rotate", {"angle": 90}, "Girar 90°")),
                "rotate_right",
            ),
            (
                "Girar 90° à esquerda",
                lambda: self.commit(Operation("rotate", {"angle": -90}, "Girar −90°")),
                "rotate_left",
            ),
            ("Girar livremente…", self.rotate_dialog, "rotate_right"),
            (
                "Espelhar horizontalmente",
                lambda: self.commit(
                    Operation("flip", {"axis": "horizontal"}, "Espelhar horizontal")
                ),
                "flip_horizontal",
            ),
            (
                "Espelhar verticalmente",
                lambda: self.commit(
                    Operation("flip", {"axis": "vertical"}, "Espelhar vertical")
                ),
                "flip_vertical",
            ),
            (
                "Aplicar recorte selecionado",
                lambda: self.apply_crop(self.canvas.selection),
                "crop",
            ),
            ("Restaurar original", self.restore, "undo"),
        ):
            action = self._action(text, slot, icon_name=icon_name)
            image.addAction(action)
            self.image_actions.append(action)
        image.addSeparator()
        image.addAction(
            self._action(
                "Laboratório e medições…", self.open_science, icon_name="science"
            )
        )
        filters = bar.addMenu("Filtros")
        for category, names in FILTERS.items():
            sub = filters.addMenu(category)
            category_icon = FILTER_CATEGORY_ICONS[category]
            sub.setIcon(icon(category_icon))
            sub.menuAction().setIconVisibleInMenu(True)
            for name in names:
                sub.addAction(
                    self._action(
                        name,
                        lambda checked=False, n=name: self.choose_filter(n),
                        icon_name=category_icon,
                    )
                )
        view = bar.addMenu("Visualizar")
        view.addAction(
            self._action(
                "Ajustar à tela", self.canvas.fit_to_view, "Ctrl+0", icon_name="fit"
            )
        )
        view.addAction(
            self._action(
                "Tamanho real",
                self.canvas.actual_size,
                "Ctrl+1",
                icon_name="actual_size",
            )
        )
        view.addAction(
            self._action(
                "Ampliar",
                lambda: self.canvas.zoom_by(1.25),
                "Ctrl++",
                icon_name="zoom_in",
            )
        )
        extra = self._action(
            "Ampliar (teclado =)", lambda: self.canvas.zoom_by(1.25), "Ctrl+="
        )
        self.addAction(extra)
        view.addAction(
            self._action(
                "Reduzir",
                lambda: self.canvas.zoom_by(0.8),
                "Ctrl+-",
                icon_name="zoom_out",
            )
        )
        self.split_action = self._action(
            "Comparação dividida", self.set_split, checkable=True, icon_name="split"
        )
        view.addAction(self.split_action)
        view.addSeparator()
        self.panels_menu = view.addMenu("Painéis")
        self.panels_menu.setIcon(icon("panels"))
        self.panels_menu.menuAction().setIconVisibleInMenu(True)
        view.addAction(
            self._action("Editor", lambda: self.set_workspace(0), icon_name="image")
        )
        view.addAction(
            self._action(
                "Vídeo e câmera", lambda: self.set_workspace(1), icon_name="video"
            )
        )
        view.addAction(
            self._action(
                "Rostos e chamada", lambda: self.set_workspace(2), icon_name="faces"
            )
        )
        self.image_actions += [
            self.save_action,
            self.save_as_action,
            self.export_action,
        ]

    def _toolbars(self):
        top = QToolBar("Documento", self)
        top.setMovable(False)
        self.addToolBar(top)
        brand = QLabel("  OpenCV Studio  ")
        brand.setProperty("heading", True)
        top.addWidget(brand)
        top.addSeparator()
        self.workspaces = QComboBox()
        self.workspaces.addItems(
            ["Editor de imagens", "Vídeo e câmera", "Rostos e chamada"]
        )
        self.workspaces.setMinimumWidth(175)
        self.workspaces.currentIndexChanged.connect(self.set_workspace)
        top.addWidget(self.workspaces)
        top.addSeparator()
        self.open_action.setIcon(icon("open"))
        top.addAction(self.open_action)
        self.save_action.setIcon(icon("save"))
        top.addAction(self.save_action)
        top.addAction(self.add_layer_action)
        top.addSeparator()
        for action in (self.undo_action, self.redo_action):
            action.setToolTip(f"{action.text()} ({action.shortcut().toString()})")
            top.addAction(action)
        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        top.addWidget(spacer)
        self.name_label = QLabel("Nenhum documento  ")
        self.name_label.setProperty("muted", True)
        top.addWidget(self.name_label)
        tools = QToolBar("Ferramentas", self)
        tools.setObjectName("tools")
        tools.setMovable(False)
        tools.setIconSize(QSize(24, 24))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tools)
        self.tools = tools
        group = QActionGroup(self)
        group.setExclusive(True)
        self.tool_actions = {}
        for name, label, key in (
            ("pan", "Mover / pan", "V"),
            ("crop", "Recortar", "C"),
            ("rect", "Seleção retangular", "M"),
            ("ellipse", "Seleção elíptica", "E"),
            ("eyedropper", "Conta-gotas", "I"),
            ("text", "Texto", "T"),
        ):
            action = self._action(
                f"{label} ({key})",
                lambda checked=False, n=name: self._select_tool(n),
                key,
                True,
            )
            action.setIcon(icon(name))
            group.addAction(action)
            tools.addAction(action)
            self.tool_actions[name] = action
        self.tool_actions["pan"].setChecked(True)
        tools.addSeparator()
        science = self._action("Laboratório, morfologia e medições", self.open_science)
        science.setIcon(icon("science"))
        tools.addAction(science)
        options = QToolBar("Opções da ferramenta", self)
        options.setMovable(False)
        self.addToolBarBreak()
        self.addToolBar(options)
        self.tool_label = QLabel(" Mover / pan  ")
        options.addWidget(self.tool_label)
        self.crop_actions = []
        self.crop_actions.append(options.addWidget(QLabel(" Proporção ")))
        self.crop_ratio = QComboBox()
        self.crop_ratio.addItems(["Livre", "1:1", "4:3", "3:2", "16:9", "9:16"])
        self.crop_ratio.currentTextChanged.connect(
            lambda s: setattr(
                self.canvas,
                "crop_ratio",
                None
                if s == "Livre"
                else float(s.split(":")[0]) / float(s.split(":")[1]),
            )
        )
        self.crop_actions.append(options.addWidget(self.crop_ratio))
        crop = QPushButton("Recortar")
        crop.clicked.connect(lambda: self.apply_crop(self.canvas.selection))
        self.crop_actions.append(options.addWidget(crop))
        for action in self.crop_actions:
            action.setVisible(False)
        options.addSeparator()
        self.compare = QCheckBox("Comparação dividida")
        self.compare.setIcon(icon("split"))
        self.compare.setIconSize(QSize(18, 18))
        self.compare.toggled.connect(self.set_split)
        options.addWidget(self.compare)
        options.setToolTip(
            "Espaço + arrastar: mover · \\: ver original · Ctrl+0: ajustar · Ctrl+1: 100%"
        )
        stretch = QWidget()
        stretch.setSizePolicy(spacer.sizePolicy())
        options.addWidget(stretch)
        options.addSeparator()
        self.apply_button = QPushButton("Aplicar edição")
        self.apply_button.setIcon(icon("apply"))
        self.apply_button.setProperty("primary", True)
        self.apply_button.clicked.connect(self.apply_draft)
        options.addWidget(self.apply_button)
        discard = QPushButton("Descartar")
        discard.setIcon(icon("discard"))
        discard.clicked.connect(self.reset_draft)
        options.addWidget(discard)
        self.options = options

    def _select_tool(self, name):
        self.canvas.set_tool(name)
        self.tool_label.setText(
            " " + self.tool_actions[name].text().split(" (")[0] + "  "
        )
        self.tool_label.setMinimumWidth(
            self.tool_label.fontMetrics().horizontalAdvance(self.tool_label.text()) + 8
        )
        for action in self.crop_actions:
            action.setVisible(name == "crop")
        if name in ("rect", "ellipse"):
            self.status(
                "Arraste para selecionar. Shift: adicionar · Alt: subtrair · Shift+Alt: interseção. Botão direito: ações da seleção."
            )
        else:
            self.status(self.options.toolTip())

    def _dock(self, title, widget):
        dock = QDockWidget(title, self)
        dock.setObjectName(title)
        dock.setWidget(widget)
        dock.setTitleBarWidget(DockTitleBar(dock))
        dock.setMinimumWidth(285)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        action = dock.toggleViewAction()
        dock_icons = {
            "Ajustes": "adjustments",
            "Filtros": "effects",
            "Histograma": "histogram",
            "Histórico": "history",
            "Camadas": "layers",
        }
        action.setIcon(icon(dock_icons[title]))
        action.setIconVisibleInMenu(True)
        self.panels_menu.addAction(action)
        return dock

    def _scroll(self, widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        return scroll

    def _panels(self):
        adjustments = QWidget()
        layout = QVBoxLayout(adjustments)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(7)
        self.preset = QComboBox()
        self.preset.addItems(["Personalizado"] + list(PRESETS))
        self.preset.currentTextChanged.connect(self.use_preset)
        layout.addWidget(QLabel("Preset"))
        layout.addWidget(self.preset)
        self.adjustment_controls = {}
        for key, spec in ADJUSTMENTS.items():
            control = AdjustmentControl(
                spec["label"], spec["min"], spec["max"], spec["default"], spec["step"]
            )
            control.changed.connect(self.changed)
            control.released.connect(lambda: self.request_render(False))
            layout.addWidget(control)
            self.adjustment_controls[key] = control
        layout.addStretch()
        self.adjustments_dock = self._dock("Ajustes", self._scroll(adjustments))
        filter_panel = QWidget()
        fl = QVBoxLayout(filter_panel)
        fl.setContentsMargins(12, 10, 12, 12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar entre todos os filtros…")
        fl.addWidget(self.search)
        self.filter_list = QListWidget()
        self.filter_list.setMinimumHeight(40)
        for category, names in FILTERS.items():
            category_icon = icon(FILTER_CATEGORY_ICONS[category])
            for name in names:
                self.filter_list.addItem(QListWidgetItem(category_icon, name))
        self.filter_splitter = FilterSplitter()
        self.filter_splitter.addWidget(self.filter_list)
        fl.addWidget(self.filter_splitter, 1)
        filter_details = QWidget()
        details_layout = QVBoxLayout(filter_details)
        details_layout.setContentsMargins(0, 4, 0, 4)
        self.search.textChanged.connect(self.search_filters)
        self.filter_list.currentTextChanged.connect(self.choose_filter)
        self.enable_filter = QCheckBox("Prévia do filtro selecionado")
        self.enable_filter.toggled.connect(self.changed)
        details_layout.addWidget(self.enable_filter)
        self.parameters = QWidget()
        self.parameter_layout = QVBoxLayout(self.parameters)
        self.parameter_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.addWidget(self.parameters)
        self.intensity = AdjustmentControl("Intensidade", 0, 100, 100)
        self.intensity.changed.connect(self.changed)
        self.intensity.released.connect(lambda: self.request_render(False))
        details_layout.addWidget(self.intensity)
        buttons = QHBoxLayout()
        apply = QPushButton("Aplicar edição")
        apply.setIcon(icon("apply"))
        apply.setProperty("primary", True)
        apply.clicked.connect(self.apply_draft)
        buttons.addWidget(apply)
        reset = QPushButton("Descartar")
        reset.setIcon(icon("discard"))
        reset.clicked.connect(self.reset_draft)
        buttons.addWidget(reset)
        details_layout.addLayout(buttons)
        details_layout.addStretch()
        details_scroll = self._scroll(filter_details)
        details_scroll.setMinimumHeight(60)
        self.filter_splitter.addWidget(details_scroll)
        self.filter_splitter.setStretchFactor(0, 1)
        self.filter_splitter.setStretchFactor(1, 1)
        self.filter_splitter.setSizes([220, 180])
        self.filters_dock = self._dock("Filtros", filter_panel)
        curves_panel = QWidget()
        cl = QVBoxLayout(curves_panel)
        cl.setContentsMargins(12, 8, 12, 10)
        self.histogram = HistogramWidget()
        cl.addWidget(self.histogram)
        self.curve = CurveWidget()
        self.curve.changed.connect(self.changed)
        self.curve.released.connect(lambda: self.request_render(False))
        cl.addWidget(self.curve)
        self.black = AdjustmentControl("Nível de preto", 0, 254, 0)
        self.white = AdjustmentControl("Nível de branco", 1, 255, 255)
        self.black.number.valueChanged.connect(
            lambda value: (
                self.white.set_value(value + 1) if value >= self.white.value() else None
            )
        )
        self.black.slider.valueChanged.connect(
            lambda _: (
                self.white.set_value(self.black.value() + 1)
                if self.black.value() >= self.white.value()
                else None
            )
        )
        self.white.number.valueChanged.connect(
            lambda value: (
                self.black.set_value(value - 1) if value <= self.black.value() else None
            )
        )
        self.white.slider.valueChanged.connect(
            lambda _: (
                self.black.set_value(self.white.value() - 1)
                if self.white.value() <= self.black.value()
                else None
            )
        )
        self.level_gamma = AdjustmentControl("Gama dos níveis", 0.1, 5, 1, 0.01)
        for c in (self.black, self.white, self.level_gamma):
            c.changed.connect(self.changed)
            c.released.connect(lambda: self.request_render(False))
            cl.addWidget(c)
        cr = QPushButton("Restaurar curvas e níveis")
        cr.clicked.connect(self.reset_curves)
        cl.addWidget(cr)
        self.hist_dock = self._dock("Histograma", self._scroll(curves_panel))
        self.layer_panel = LayerPanel()
        self.layer_panel.importRequested.connect(self.import_layers)
        self.layer_panel.filesDropped.connect(self.import_layers)
        self.layer_panel.selected.connect(self.select_layer)
        self.layer_panel.changed.connect(self.preview_layer)
        self.layer_panel.released.connect(self.commit_layer_preview)
        self.layer_panel.orderChanged.connect(self.reorder_layers)
        self.layer_panel.actionRequested.connect(self.layer_action)
        self.layer_dock = self._dock("Camadas", self.layer_panel)
        tabs = QTabWidget()
        self.history_list = QListWidget()
        self.history_list.currentRowChanged.connect(self.jump_history)
        tabs.addTab(self.history_list, "Histórico")
        stack_panel = QWidget()
        sl = QVBoxLayout(stack_panel)
        sl.setContentsMargins(8, 8, 8, 8)
        self.operation_list = QListWidget()
        sl.addWidget(self.operation_list)
        self.operation_list.itemDoubleClicked.connect(lambda _: self.edit_operation())
        for text, slot in (
            ("Editar selecionada", self.edit_operation),
            ("Remover selecionada", self.remove_operation),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            sl.addWidget(b)
        tabs.addTab(self._scroll(stack_panel), "Pilha de edições")
        self.history_dock = self._dock("Histórico", tabs)
        self.splitDockWidget(
            self.adjustments_dock, self.layer_dock, Qt.Orientation.Vertical
        )
        self.tabifyDockWidget(self.adjustments_dock, self.filters_dock)
        self.tabifyDockWidget(self.filters_dock, self.hist_dock)
        self.tabifyDockWidget(self.hist_dock, self.history_dock)
        self.adjustments_dock.raise_()
        self.resizeDocks([self.adjustments_dock], [330], Qt.Orientation.Horizontal)
        self.resizeDocks(
            [self.adjustments_dock, self.layer_dock],
            [310, 430],
            Qt.Orientation.Vertical,
        )
        self.docks = [
            self.adjustments_dock,
            self.filters_dock,
            self.hist_dock,
            self.layer_dock,
            self.history_dock,
        ]

    def _statusbar(self):
        self.position_label = QLabel("—")
        self.dimension_label = QLabel("Nenhuma imagem")
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setFixedWidth(95)
        self.zoom_combo.addItems(
            ["5%", "25%", "50%", "100%", "200%", "400%", "800%", "1600%", "3200%"]
        )
        self.zoom_combo.setCurrentText("100%")
        self.zoom_combo.activated.connect(self.enter_zoom)
        self.zoom_combo.lineEdit().editingFinished.connect(self.enter_zoom)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setFixedWidth(90)
        self.busy.setFixedHeight(8)
        self.busy.hide()
        self.statusBar().addWidget(self.position_label, 1)
        self.statusBar().addPermanentWidget(self.busy)
        self.statusBar().addPermanentWidget(self.dimension_label)
        self.statusBar().addPermanentWidget(self.zoom_combo)

    def start_group_camera(self):
        self.set_workspace(1)
        self.video.start_live_recognition()

    def set_workspace(self, index):
        self.stack.setCurrentIndex(index)
        self.workspaces.blockSignals(True)
        self.workspaces.setCurrentIndex(index)
        self.workspaces.blockSignals(False)
        for dock in self.docks:
            dock.setVisible(index == 0)
        self.tools.setVisible(index == 0)
        self.options.setVisible(index == 0)
        if index != 0:
            self.save_action.setEnabled(True)
            self.save_as_action.setEnabled(True)
        else:
            self._document_actions(self.document.original is not None)
        self._update_history_actions()

    def _document_actions(self, enabled):
        for a in self.image_actions:
            a.setEnabled(enabled)
        self.apply_button.setEnabled(enabled)

    def _busy(self, value):
        self.busy.setVisible(value)

    def changed(self, *args):
        if not self._loading_controls and self.document.original is not None:
            self.debounce.start()
            self.full_debounce.start()

    def _idle_full_render(self):
        controls = (
            list(self.adjustment_controls.values())
            + self.filter_controls
            + [self.intensity, self.black, self.white, self.level_gamma]
        )
        if any(c.slider.isSliderDown() for c in controls):
            self.full_debounce.start()
            return
        self.request_render(False)

    def _draft(self):
        ops = []
        selection = copy.deepcopy(
            self.edit_selection
            if self.edit_index is not None
            else self.canvas.selection
        )
        values = {key: c.value() for key, c in self.adjustment_controls.items()}
        if any(values[k] != ADJUSTMENTS[k]["default"] for k in values):
            ops.append(Operation("adjustments", values, "Ajustes", selection=selection))
        name = (
            self.filter_list.currentItem().text()
            if self.filter_list.currentItem()
            else None
        )
        if self.enable_filter.isChecked() and name:
            values = [c.value() for c in self.filter_controls]
            ops.append(
                Operation(
                    "filter",
                    dict(
                        name=name,
                        p1=values[0] if values else 50,
                        p2=values[1] if len(values) > 1 else 100,
                    ),
                    name,
                    self.intensity.value() / 100,
                    selection,
                )
            )
        if self.curve.points != [(0, 0), (255, 255)]:
            ops.append(
                Operation(
                    "curves",
                    {"points": list(self.curve.points)},
                    "Curvas",
                    selection=selection,
                )
            )
        if (self.black.value(), self.white.value(), self.level_gamma.value()) != (
            0,
            255,
            1,
        ):
            ops.append(
                Operation(
                    "levels",
                    dict(
                        black=self.black.value(),
                        white=self.white.value(),
                        gamma=self.level_gamma.value(),
                    ),
                    "Níveis",
                    selection=selection,
                )
            )
        return ops

    def has_draft(self):
        return (
            self._layer_preview is not None
            or self.edit_index is not None
            or bool(self._draft())
        )

    def all_operations(self):
        ops = list(self.document.operations)
        if self.edit_index is not None and self.edit_index < len(ops):
            ops[self.edit_index : self.edit_index + 1] = self._draft()
        else:
            ops += self._draft()
        return self._with_layer_preview(ops)

    def request_render(self, reduced=False):
        self.debounce.stop()
        if not reduced:
            self.full_debounce.stop()
        if self.document.original is None:
            return
        if reduced:
            # Presets, selection changes and operation editing also need a full
            # render after the interactive preview, not only slider signals.
            self.full_debounce.start()
        operations = self.all_operations()
        self._render_sizes[self.renderer.generation + 1] = output_size(
            self.document.original.shape, operations
        )
        self.renderer.request(self.document.original, operations, reduced)

    def _rendered(self, image, generation, reduced):
        self.result = image
        size = self._render_sizes.get(generation, (image.shape[1], image.shape[0]))
        self._render_sizes = {
            key: value for key, value in self._render_sizes.items() if key >= generation
        }
        self.canvas.set_images(self.document.original, image, source_size=size)
        self._sync_layer_overlay()
        self.histogram.set_image(image)
        self.dimension_label.setText(
            f"{size[0]:,} × {size[1]:,} px" + (" · prévia" if reduced else "")
        )
        if self._fit_next:
            self.canvas.fit_to_view()
            self._fit_next = False

    def _job(self, function, done, pool=None):
        job = Job(function)
        self.jobs.append(job)

        def finish(result):
            if job in self.jobs:
                self.jobs.remove(job)
            done(result)

        def fail(error):
            if job in self.jobs:
                self.jobs.remove(job)
            self.error(error)

        job.signals.done.connect(finish)
        job.signals.failed.connect(fail)
        (pool or QThreadPool.globalInstance()).start(job)

    def open_dialog(self):
        if self.stack.currentIndex() == 2:
            self.faces.open_photo()
            return
        if self.stack.currentIndex() == 1:
            self.video.open_video()
            return
        path, _ = QFileDialog.getOpenFileName(self, "Abrir imagem", "", IMAGE_TYPES)
        if path:
            self.open_path(path)

    def open_path(self, path):
        if Path(path).suffix.lower() == ".ocvproj":
            self.open_project(path)
            return
        if not self._confirm_discard():
            return
        self._load_generation += 1
        generation = self._load_generation
        self.status("Lendo imagem…")

        def loaded(image):
            if generation != self._load_generation:
                return
            self.open_array(image, path)

        self._job(lambda: read_image(path), loaded)

    def open_array(self, image, path=None):
        self._load_generation += 1
        self.reset_draft(render=False)
        self.canvas.clear_selection()
        self.document.open(image, path)
        self.project_path = None
        self.modified = False
        self.result = image.copy()
        self._fit_next = True
        self.set_workspace(0)
        self.name_label.setText(
            (Path(path).name if path else "Documento sem título") + "  "
        )
        self._document_actions(True)
        self._update_history()
        self.request_render(False)

    def open_video_frame(self, image):
        if self._confirm_discard():
            self.open_array(image)

    def search_filters(self, text):
        import unicodedata

        def normalized(t):
            return "".join(
                c
                for c in unicodedata.normalize("NFKD", t.casefold())
                if not unicodedata.combining(c)
            )

        for i in range(self.filter_list.count()):
            self.filter_list.item(i).setHidden(
                normalized(text) not in normalized(self.filter_list.item(i).text())
            )

    def choose_filter(self, name):
        if not name:
            return
        items = self.filter_list.findItems(name, Qt.MatchFlag.MatchExactly)
        if items and self.filter_list.currentItem() != items[0]:
            self.filter_list.setCurrentItem(items[0])
            return
        while self.parameter_layout.count():
            item = self.parameter_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.filter_controls = []
        for label, minimum, maximum, default in FILTER_PARAMETERS.get(name, []):
            c = AdjustmentControl(label, minimum, maximum, default)
            c.changed.connect(self.changed)
            c.released.connect(lambda: self.request_render(False))
            self.parameter_layout.addWidget(c)
            self.filter_controls.append(c)
        self.enable_filter.setChecked(True)
        self.filters_dock.raise_()
        self.changed()

    def use_preset(self, name):
        if name not in PRESETS:
            return
        for key, control in self.adjustment_controls.items():
            control.set_value(PRESETS[name].get(key, ADJUSTMENTS[key]["default"]))
        self.request_render(True)

    def reset_curves(self):
        self.curve.set_points([(0, 0), (255, 255)])
        for control in (self.black, self.white, self.level_gamma):
            control.set_value(control.default)
        self.changed()
        self.request_render(False)

    def discard_preview(self):
        if self.canvas._selection_transform:
            self.canvas.end_selection_transform(cancel=True)
            return
        self.canvas.clear_selection()
        self.reset_draft()

    def reset_draft(self, checked=False, render=True):
        self.debounce.stop()
        self.full_debounce.stop()
        self._loading_controls = True
        self.edit_index = None
        self.edit_selection = None
        self._layer_preview = None
        for c in self.adjustment_controls.values():
            c.set_value(c.default)
        self.enable_filter.setChecked(False)
        self.intensity.set_value(100)
        self.curve.set_points([(0, 0), (255, 255)])
        for c in (self.black, self.white, self.level_gamma):
            c.set_value(c.default)
        self.preset.setCurrentIndex(0)
        self._loading_controls = False
        self.refresh_layers()
        if render:
            self.request_render(False)

    def apply_draft(self):
        if self.document.original is None:
            return False
        self.commit_layer_preview()
        draft = self._draft()
        if not draft and self.edit_index is None:
            return True
        if self.black.value() >= self.white.value():
            self.status("O nível de branco precisa ser maior que o nível de preto.")
            return False
        self.document.set_operations(
            self.all_operations(),
            " + ".join(o.name for o in draft) or "Neutralizar edição",
        )
        self.reset_draft(render=False)
        self.modified = True
        self._update_history()
        self.request_render(False)
        return True

    def commit(self, operation):
        if self.document.original is None:
            return
        if self.has_draft() and not self.apply_draft():
            return
        self.document.commit(operation)
        self.modified = True
        self.canvas.clear_selection()
        self._update_history()
        self.request_render(False)

    def _update_history(self):
        self.history_list.blockSignals(True)
        self.history_list.clear()
        for entry in self.document.history.entries:
            self.history_list.addItem(entry.label)
        self.history_list.setCurrentRow(self.document.history.index)
        self.history_list.blockSignals(False)
        self.operation_list.clear()
        for op in self.document.operations:
            self.operation_list.addItem(op.name or op.kind)
        self._update_history_actions()
        self.refresh_layers()

    def _update_history_actions(self):
        editor = self.stack.currentIndex() == 0
        self.undo_action.setEnabled(editor and self.document.history.index > 0)
        self.redo_action.setEnabled(
            editor
            and self.document.history.index < len(self.document.history.entries) - 1
        )

    def undo(self):
        self.reset_draft(render=False)
        if self.document.undo():
            self.modified = True
            self._update_history()
            self.request_render(False)

    def redo(self):
        self.reset_draft(render=False)
        if self.document.redo():
            self.modified = True
            self._update_history()
            self.request_render(False)

    def jump_history(self, index):
        if index >= 0 and self.document.jump(index):
            self.reset_draft(render=False)
            self.modified = True
            self._update_history()
            self.request_render(False)

    def edit_operation(self):
        i = self.operation_list.currentRow()
        if not 0 <= i < len(self.document.operations):
            return
        op = self.document.operations[i]
        if op.kind in ("layer", "base_layer"):
            self.layer_dock.show()
            self.layer_dock.raise_()
            self.layer_panel.select_layer(op.params.get("id", "base"))
            return
        self.reset_draft(render=False)
        if op.kind == "adjustments":
            for key, c in self.adjustment_controls.items():
                c.set_value(op.params.get(key, c.default))
            self.adjustments_dock.raise_()
        elif op.kind == "filter":
            self.choose_filter(op.params["name"])
            for j, c in enumerate(self.filter_controls):
                c.set_value(op.params.get(f"p{j + 1}", c.default))
            self.intensity.set_value(op.intensity * 100)
        elif op.kind == "curves":
            self.curve.set_points(op.params["points"])
            self.hist_dock.raise_()
        elif op.kind == "levels":
            for c, key in (
                (self.black, "black"),
                (self.white, "white"),
                (self.level_gamma, "gamma"),
            ):
                c.set_value(op.params.get(key, c.default))
            self.hist_dock.raise_()
        else:
            self.status(
                "Esta operação pode ser removida pela pilha ou desfeita no histórico."
            )
            return
        self.edit_index = i
        self.edit_selection = copy.deepcopy(op.selection)
        self.status("Editando operação existente. Aplicar edição confirma a alteração.")
        self.request_render(True)

    def remove_operation(self):
        i = self.operation_list.currentRow()
        if 0 <= i < len(self.document.operations):
            ops = list(self.document.operations)
            removed = ops.pop(i)
            self.document.set_operations(ops, f"Remover {removed.name}")
            self.reset_draft(render=False)
            self.modified = True
            self._update_history()
            self.request_render(False)

    def apply_crop(self, selection):
        if not selection or self.document.original is None:
            self.status("Arraste uma região no canvas para recortar.")
            return
        self.commit(Operation("crop", {"rect": tuple(selection["rect"])}, "Recorte"))

    def resize_dialog(self):
        if self.document.original is None:
            return
        w, h = output_size(self.document.original.shape, self.all_operations())
        dialog = QDialog(self)
        dialog.setWindowTitle("Redimensionar imagem")
        form = QFormLayout(dialog)
        width = QSpinBox()
        height = QSpinBox()
        for c, v in ((width, w), (height, h)):
            c.setRange(1, 50000)
            c.setValue(v)
        lock = QCheckBox("Manter proporção pela largura")
        lock.setChecked(True)
        width.valueChanged.connect(
            lambda value: (
                height.setValue(max(1, round(value * h / w)))
                if lock.isChecked()
                else None
            )
        )
        form.addRow("Largura (px)", width)
        form.addRow("Altura (px)", height)
        form.addRow(lock)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            self.commit(
                Operation(
                    "resize",
                    dict(width=width.value(), height=height.value()),
                    "Redimensionamento",
                )
            )

    def rotate_dialog(self):
        angle, ok = QInputDialog.getDouble(
            self, "Girar imagem", "Ângulo (graus)", 0, -360, 360, 1
        )
        if ok:
            self.commit(Operation("rotate", {"angle": angle}, f"Girar {angle:g}°"))

    def add_text(self, x, y):
        text, ok = QInputDialog.getText(self, "Adicionar texto", "Texto")
        if not ok or not text:
            return
        size, ok = QInputDialog.getInt(
            self, "Tamanho do texto", "Tamanho em pixels", 36, 8, 1000
        )
        if not ok:
            return
        color = QColorDialog.getColor(QColor("white"), self, "Cor do texto")
        if color.isValid():
            self.commit(
                Operation(
                    "text",
                    dict(
                        x=x,
                        y=y,
                        text=text,
                        size=size,
                        color=(color.blue(), color.green(), color.red()),
                    ),
                    "Texto",
                )
            )

    def restore(self):
        if self.document.original is not None:
            self.document.set_operations([], "Restaurar original")
            self.reset_draft(render=False)
            self.modified = True
            self._update_history()
            self.request_render(False)

    def duplicate(self):
        if self.document.original is None:
            return
        operations = copy.deepcopy(self.all_operations())
        original = self.document.original

        def ready(image):
            window = MainWindow()
            self.child_windows.append(window)
            window.open_array(image)
            if operations:
                window.document.set_operations(operations, "Documento duplicado")
                window._update_history()
                window.request_render(False)
            window.modified = True
            window.show()
            if any(op.kind == "layer" for op in operations):
                window.layer_dock.raise_()

        self._job(lambda: original.copy(), ready)

    def open_science(self):
        if self.document.original is None:
            self.status("Abra uma imagem para usar o laboratório.")
            return
        from studio.science import ScienceDialog

        original = self.document.original
        operations = copy.deepcopy(self.all_operations())
        entry = self.document.history.entries[self.document.history.index]

        def ready(image):
            if (
                self.document.original is not original
                or self.document.history.entries[self.document.history.index]
                is not entry
            ):
                return
            dialog = ScienceDialog(image, self)

            def use_result(result, label):
                if self.document.original is original:
                    self.commit(Operation("raster", {"image": result.copy()}, label))

            dialog.resultReady.connect(use_result)
            dialog.exec()

        self._job(lambda: render_pipeline(original, operations), ready)

    def save(self, save_as=False):
        if self.stack.currentIndex() == 2:
            self.faces.save_photo()
            return
        if self.stack.currentIndex() == 1:
            self.video.export_frame()
            return
        if self.document.original is None:
            return
        if self.project_path or any(
            op.kind in ("layer", "base_layer") for op in self.document.operations
        ):
            self.save_project(save_as)
            return
        path = self.document.path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Salvar imagem", str(path or "imagem.png"), IMAGE_TYPES
            )
        if path:
            self._export(path, 95)

    def export_dialog(self):
        if self.stack.currentIndex() == 2:
            self.faces.save_photo()
            return
        if self.stack.currentIndex() == 1:
            self.video.export_video()
            return
        if self.document.original is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Exportar imagem")
        form = QFormLayout(dialog)
        quality = QSpinBox()
        quality.setRange(1, 100)
        quality.setValue(95)
        form.addRow("Qualidade JPEG / WEBP", quality)
        note = QLabel("PNG/TIFF preservam transparência. JPEG usa fundo branco.")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if not dialog.exec():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar imagem", "imagem.png", IMAGE_TYPES
        )
        if path:
            self._export(path, quality.value())

    def _export(self, path, quality):
        if not self.apply_draft():
            return
        original = self.document.original
        ops = list(self.document.operations)
        entry = self.document.history.entries[self.document.history.index]
        self.status("Exportando na resolução total…")

        def process():
            image = render_pipeline(original, ops)
            write_image(path, image, quality=quality)
            return path

        def saved(result):
            if self.document.original is original:
                if (
                    self.document.history.entries[self.document.history.index] is entry
                    and not self.project_path
                    and not any(op.kind in ("layer", "base_layer") for op in ops)
                ):
                    self.modified = False
                self.document.path = str(result)
                self.name_label.setText(Path(self.project_path or result).name + "  ")
            self.status(f"Imagem salva: {result}")

        self._job(process, saved, pool=self.export_pool)

    def _confirm_discard(self):
        if self.modified or (self.document.original is not None and self.has_draft()):
            return (
                QMessageBox.question(
                    self,
                    "Alterações não salvas",
                    "Continuar e descartar as alterações não salvas?",
                    QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel,
                )
                == QMessageBox.StandardButton.Discard
            )
        return True

    def _cursor(self, x, y, color):
        self.position_label.setText(
            f"X {x}   Y {y}" + (f"   RGB {tuple(color)}" if color is not None else "")
        )

    def _zoom_changed(self, value):
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentText(f"{value * 100:.1f}%")
        self.zoom_combo.blockSignals(False)

    def enter_zoom(self, *args):
        try:
            self.canvas.set_zoom(
                float(self.zoom_combo.currentText().replace("%", "").replace(",", "."))
                / 100
            )
        except ValueError:
            self._zoom_changed(self.canvas.zoom)

    def set_split(self, enabled):
        self.canvas.split = bool(enabled)
        self.canvas.update()
        self.compare.blockSignals(True)
        self.compare.setChecked(bool(enabled))
        self.compare.blockSignals(False)
        self.split_action.blockSignals(True)
        self.split_action.setChecked(bool(enabled))
        self.split_action.blockSignals(False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.open_path(urls[0].toLocalFile())

    def closeEvent(self, event):
        if not self._confirm_discard():
            event.ignore()
            return
        self.debounce.stop()
        self._load_generation += 1
        self.full_debounce.stop()
        self.renderer.close()
        self.export_pool.waitForDone()
        self.faces.cleanup()
        self.video.cleanup()
        QThreadPool.globalInstance().waitForDone()
        event.accept()
