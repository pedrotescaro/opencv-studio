"""Qt workspace for the existing local Haar/LBPH model and attendance records.

Only the tested data/model services from editor_faces are reused. This module
never constructs a Tk widget and never performs model work in the GUI thread.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .services.faces import (
    PASTA_PADRAO,
    BancoFaces,
    Chamada,
    ErroFaces,
    MotorFaces,
    ler_imagem,
    normalizar_face,
    salvar_imagem,
)

from .advanced_jobs import Job, image_pixmap

IMAGE_FILTER = "Imagens (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff *.pgm)"
DEMO_FOLDER = Path(__file__).resolve().parents[1] / ".dados_faces_demo"


def register_photos(bank, motor, identifier, name, filenames):
    """Validate all imports before writing anything, then retrain once."""
    if not identifier.strip() or not name.strip():
        raise ErroFaces("Informe a matrícula/ID e o nome antes de importar fotos.")
    faces = []
    for filename in filenames:
        image = ler_imagem(filename)
        boxes = motor.detectar(image)
        if len(boxes) != 1:
            raise ErroFaces(
                f"{Path(filename).name}: foram detectados {len(boxes)} rostos. Use uma foto com exatamente um rosto frontal."
            )
        x, y, w, h = boxes[0]
        faces.append(image[y : y + h, x : x + w].copy())
    unique = {normalizar_face(face).tobytes() for face in faces}
    with bank.lock:
        existing = bank.alunos.get(identifier.strip(), {}).get("amostras", [])
        unique.update(bank.ler_amostra(filename).tobytes() for filename in existing)
    if len(unique) < 2:
        raise ErroFaces("Cada pessoa precisa de pelo menos duas fotos diferentes.")
    added = bank.cadastrar(identifier, name, faces)
    trained = motor.preparar_modelo()
    return added, trained


class FacePanel(QWidget):
    statusMessage = Signal(str)
    attendanceChanged = Signal()
    _resultsReady = Signal(object)

    def __init__(self, parent=None, get_image=None, database_folder=None, demo_enabled=True):
        super().__init__(parent)
        self.get_image = get_image
        self.get_video_frame = None
        self._state_lock = threading.RLock()
        self._jobs = {}
        self._closed = False
        self._busy = False
        self._picture = None
        self._annotated = None
        self._preview_pixmap = None
        self._capture_faces = []
        self.chamada = None
        self.default_folder = Path(database_folder) if database_folder is not None else PASTA_PADRAO
        self.bank = BancoFaces(self.default_folder)
        self.motor = MotorFaces(self.bank)
        self._build()
        self._resultsReady.connect(self._results_changed)
        self.attendanceChanged.connect(self._attendance_table)
        # No identities in the personal roster: open the existing trained public
        # demonstration, while keeping every personal record in its own folder.
        use_demo = demo_enabled and not self.bank.alunos and (DEMO_FOLDER / "alunos.json").exists()
        self.database.blockSignals(True)
        self.database.setCurrentIndex(1 if use_demo else 0)
        self.database.blockSignals(False)
        self._switch_database(DEMO_FOLDER if use_demo else self.default_folder, initial=True)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        title = QLabel("Reconhecimento facial")
        title.setObjectName("workspaceTitle")
        title.setProperty("heading", True)
        subtitle = self.subtitle = QLabel(
            "Cadastro local, modelo LBPH persistido e presença registrada uma vez por pessoa."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        top = QHBoxLayout()
        self.database = QComboBox()
        self.database.addItems(["Minha turma", "Demonstração pública · AT&T/ORL"])
        self.database.currentIndexChanged.connect(self._database_selected)
        top.addWidget(QLabel("Base"))
        top.addWidget(self.database, 1)
        self.model_badge = QLabel("Preparando modelo…")
        top.addWidget(self.model_badge)
        layout.addLayout(top)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(310)
        splitter.addWidget(self.tabs)

        register = QWidget()
        reg = QVBoxLayout(register)
        self.register_layout = reg
        form = QFormLayout()
        self.identifier, self.person_name = QLineEdit(), QLineEdit()
        self.identifier.setPlaceholderText("Matrícula ou ID")
        self.person_name.setPlaceholderText("Nome da pessoa")
        form.addRow("ID", self.identifier)
        form.addRow("Nome", self.person_name)
        reg.addLayout(form)
        self.import_button = QPushButton("Importar fotos e treinar")
        self.import_button.setProperty("primary", True)
        self.import_button.clicked.connect(self.import_photos)
        reg.addWidget(self.import_button)
        self.capture_button = QPushButton("Capturar amostra do vídeo")
        self.capture_button.clicked.connect(self.capture_sample)
        reg.addWidget(self.capture_button)
        self.save_capture_button = QPushButton("Cadastrar amostras capturadas")
        self.save_capture_button.clicked.connect(self.save_captured_samples)
        reg.addWidget(self.save_capture_button)
        self.capture_label = QLabel(
            "Use duas ou mais fotos distintas, com um rosto frontal em cada foto."
        )
        self.capture_label.setWordWrap(True)
        reg.addWidget(self.capture_label)
        self.roster = QTableWidget(0, 3)
        self.roster.setHorizontalHeaderLabels(["ID", "Nome", "Fotos"])
        self.roster.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.roster.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.roster.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.roster.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.roster.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.roster.itemSelectionChanged.connect(self._select_person)
        reg.addWidget(self.roster, 1)
        self.remove_button = QPushButton("Excluir pessoa selecionada")
        self.remove_button.clicked.connect(self.remove_person)
        reg.addWidget(self.remove_button)
        self.tabs.addTab(register, "Cadastro")

        model = QWidget()
        model_layout = QVBoxLayout(model)
        self.model_summary = QLabel()
        self.model_summary.setWordWrap(True)
        model_layout.addWidget(self.model_summary)
        settings = QFormLayout()
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.01, 1000)
        self.threshold.setDecimals(2)
        self.threshold.setSingleStep(1)
        self.threshold.setToolTip(
            "Distância LBPH máxima. Menor = reconhecimento mais restritivo. Não representa porcentagem de confiança."
        )
        settings.addRow("Distância máxima", self.threshold)
        model_layout.addLayout(settings)
        threshold_button = QPushButton("Guardar limiar")
        threshold_button.clicked.connect(self.save_threshold)
        model_layout.addWidget(threshold_button)
        self.train_button = QPushButton("Treinar novamente")
        self.train_button.clicked.connect(self.train_model)
        model_layout.addWidget(self.train_button)
        reload_button = QPushButton("Recarregar cadastro e modelo")
        reload_button.clicked.connect(lambda: self._switch_database(self.bank.pasta))
        model_layout.addWidget(reload_button)
        demo_button = self.demo_button = QPushButton("Abrir exemplo público de teste")
        demo_button.clicked.connect(self.open_demo_example)
        model_layout.addWidget(demo_button)
        note = self.model_note = QLabel(
            "A base pública contém participantes anônimos, não os alunos da turma. A distância LBPH não é probabilidade. Para a chamada real, selecione Minha turma e cadastre os alunos."
        )
        note.setWordWrap(True)
        model_layout.addWidget(note)
        model_layout.addStretch()
        self.tabs.addTab(model, "Modelo")

        attendance = QWidget()
        att = QVBoxLayout(attendance)
        self.session_name = QLineEdit()
        self.session_name.setPlaceholderText("Nome da aula / sessão")
        att.addWidget(self.session_name)
        controls = QHBoxLayout()
        start = self.start_attendance_button = QPushButton("Iniciar chamada")
        start.clicked.connect(self.start_attendance)
        end = QPushButton("Encerrar")
        end.clicked.connect(self.end_attendance)
        controls.addWidget(start)
        controls.addWidget(end)
        att.addLayout(controls)
        self.attendance_label = QLabel("Nenhuma chamada iniciada")
        att.addWidget(self.attendance_label)
        self.attendance_table = QTableWidget(0, 3)
        self.attendance_table.setHorizontalHeaderLabels(
            ["ID", "Nome", "Primeira identificação"]
        )
        self.attendance_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.attendance_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        att.addWidget(self.attendance_table, 1)
        exports = QHBoxLayout()
        csv_button = QPushButton("Exportar CSV")
        csv_button.clicked.connect(self.export_attendance_csv)
        json_button = QPushButton("Exportar JSON")
        json_button.clicked.connect(self.export_attendance_json)
        exports.addWidget(csv_button)
        exports.addWidget(json_button)
        att.addLayout(exports)
        self.tabs.addTab(attendance, "Chamada")

        visual = QWidget()
        visual_layout = QVBoxLayout(visual)
        actions = QHBoxLayout()
        for text, callback in (
            ("Abrir foto", self.open_photo),
            ("Usar imagem do editor", self.use_editor_image),
            ("Usar quadro do vídeo", self.use_video_image),
            ("Salvar resultado", self.save_photo),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        visual_layout.addLayout(actions)
        self.preview = QLabel("Abra uma foto para localizar e identificar rostos")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(260, 240)
        self.preview.setStyleSheet(
            "background:#191919;border:1px solid #393939;border-radius:6px;"
        )
        visual_layout.addWidget(self.preview, 1)
        self.result_table = QTableWidget(0, 3)
        self.result_table.setMaximumHeight(180)
        self.result_table.setHorizontalHeaderLabels(
            ["ID", "Resultado", "Distância LBPH"]
        )
        self.result_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        visual_layout.addWidget(self.result_table)
        splitter.addWidget(visual)
        splitter.setSizes([350, 900])
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

    def _notify(self, text, error=False):
        self.message.setText(text)
        self.message.setStyleSheet("color:#f1b4a8;" if error else "color:#b7c6d8;")
        self.statusMessage.emit(text)

    def _work(self, function, callback):
        if self._busy or self._closed:
            self._notify("Aguarde a operação atual terminar.")
            return False
        self._busy = True
        for widget in (
            self.database,
            self.import_button,
            self.train_button,
            self.remove_button,
            self.capture_button,
            self.save_capture_button,
        ):
            widget.setEnabled(False)
        job = Job(function)
        self._jobs[job.identifier] = (job, callback)
        job.signals.completed.connect(self._job_finished)
        QThreadPool.globalInstance().start(job)
        return True

    @Slot(int, object, str)
    def _job_finished(self, identifier, result, error):
        item = self._jobs.pop(identifier, None)
        self._busy = False
        if self._closed or item is None:
            return
        for widget in (
            self.database,
            self.import_button,
            self.train_button,
            self.remove_button,
            self.capture_button,
            self.save_capture_button,
        ):
            widget.setEnabled(True)
        if error:
            self._notify(error, True)
        else:
            item[1](result)
        self._refresh_roster()
        self.model_summary.setText(self.motor.status_modelo)
        self.model_badge.setText(
            "Modelo disponível"
            if self.motor.modelo is not None
            else "Detecção disponível"
        )

    def _database_selected(self, index):
        self._switch_database(DEMO_FOLDER if index else self.default_folder)

    def _switch_database(self, folder, initial=False):
        if self._busy:
            return
        folder = Path(folder)
        if folder == DEMO_FOLDER and not (folder / "alunos.json").exists():
            self._notify(
                "Base pública ausente. Execute preparar_faces_demo.py para baixar e treinar a demonstração.",
                True,
            )
            self.database.blockSignals(True)
            self.database.setCurrentIndex(0)
            self.database.blockSignals(False)
            return
        if self.chamada is not None and self.chamada.ativa:
            self.chamada.encerrar()
        self._capture_faces.clear()
        self._notify("Carregando modelo e validando amostras…")

        def prepare():
            bank = BancoFaces(folder)
            motor = MotorFaces(bank)
            ready = motor.preparar_modelo()
            return bank, motor, ready

        def done(result):
            bank, motor, ready = result
            with self._state_lock:
                self.bank, self.motor, self.chamada = bank, motor, None
            self.threshold.setValue(motor.limiar)
            self._notify(motor.status_modelo)
            self._attendance_table()
            if initial and folder == DEMO_FOLDER and ready:
                QTimer.singleShot(0, self.open_demo_example)

        self._work(prepare, done)

    def set_frame_provider(self, provider):
        self.get_video_frame = provider

    def _refresh_roster(self):
        with self.bank.lock:
            students = sorted(self.bank.alunos.items())
        self.roster.setRowCount(len(students))
        for row, (identifier, student) in enumerate(students):
            for col, value in enumerate(
                (identifier, student["nome"], len(student["amostras"]))
            ):
                self.roster.setItem(row, col, QTableWidgetItem(str(value)))

    def _select_person(self):
        row = self.roster.currentRow()
        if row >= 0 and self.roster.item(row, 0):
            self.identifier.setText(self.roster.item(row, 0).text())
            self.person_name.setText(self.roster.item(row, 1).text())

    def import_photos(self, filenames=None):
        if isinstance(filenames, bool) or filenames is None:
            filenames, _ = QFileDialog.getOpenFileNames(
                self, "Fotos da pessoa", "", IMAGE_FILTER
            )
        if not filenames:
            return
        identifier, name = (
            self.identifier.text().strip(),
            self.person_name.text().strip(),
        )
        bank, motor = self.bank, self.motor
        self._notify("Localizando rostos e treinando o cadastro…")
        self._work(
            lambda: register_photos(bank, motor, identifier, name, filenames),
            lambda result: self._notify(
                f"{result[0]} foto(s) cadastrada(s). {motor.status_modelo}"
            ),
        )

    def capture_sample(self):
        if not callable(self.get_video_frame):
            self._notify(
                "Abra a câmera no módulo Vídeo antes de capturar amostras.", True
            )
            return
        frame = self.get_video_frame()
        if frame is None:
            self._notify("O vídeo ainda não tem um quadro disponível.", True)
            return
        motor = self.motor

        def find():
            boxes = motor.detectar(frame)
            if len(boxes) != 1:
                raise ErroFaces(
                    "A captura precisa mostrar exatamente um rosto frontal."
                )
            x, y, w, h = boxes[0]
            return frame[y : y + h, x : x + w].copy()

        def done(face):
            normalized = normalizar_face(face)
            if any(
                np.array_equal(normalized, normalizar_face(old))
                for old in self._capture_faces
            ):
                self._notify(
                    "Esse quadro já foi capturado. Mova levemente o rosto para a próxima amostra."
                )
                return
            self._capture_faces.append(face)
            self.capture_label.setText(
                f"{len(self._capture_faces)} amostra(s) capturada(s). Capture pelo menos duas e cadastre."
            )
            self._notify("Amostra capturada; ela será salva ao cadastrar o conjunto.")

        self._work(find, done)

    def save_captured_samples(self):
        if len(self._capture_faces) < 2:
            self._notify("Capture pelo menos duas amostras distintas.", True)
            return
        identifier, name = (
            self.identifier.text().strip(),
            self.person_name.text().strip(),
        )
        faces = [face.copy() for face in self._capture_faces]
        bank, motor = self.bank, self.motor

        def save():
            added = bank.cadastrar(identifier, name, faces)
            motor.preparar_modelo()
            return added

        def done(added):
            self._capture_faces.clear()
            self.capture_label.setText(
                "Amostras salvas. Você já pode identificar essa pessoa."
            )
            self._notify(f"{added} amostras cadastradas. {motor.status_modelo}")

        self._work(save, done)

    def remove_person(self):
        row = self.roster.currentRow()
        if row < 0:
            self._notify("Selecione uma pessoa na tabela.", True)
            return
        identifier = self.roster.item(row, 0).text()
        bank, motor = self.bank, self.motor

        def remove():
            bank.remover(identifier)
            return motor.preparar_modelo()

        self._work(
            remove,
            lambda _: self._notify(
                f"Cadastro {identifier} excluído. {motor.status_modelo}"
            ),
        )

    def train_model(self):
        motor = self.motor
        self._notify("Treinando LBPH em segundo plano…")
        self._work(motor.treinar, lambda _: self._notify(motor.status_modelo))

    def save_threshold(self):
        motor, value = self.motor, self.threshold.value()
        self._work(
            lambda: motor.definir_limiar(value),
            lambda _: self._notify(f"Distância máxima guardada: {motor.limiar:.2f}."),
        )

    def open_demo_example(self):
        preferred = DEMO_FOLDER / "teste" / "pessoa_02_09.png"
        examples = [preferred] if preferred.exists() else []
        if not examples:
            examples = sorted((DEMO_FOLDER / "teste").glob("pessoa_*.png"))
        if not examples:
            self._notify(
                "Nenhuma foto pública de teste disponível. Execute preparar_faces_demo.py.",
                True,
            )
            return
        if self.bank.pasta != DEMO_FOLDER:
            self._notify(
                "Selecione Demonstração pública para identificar os participantes dessa base."
            )
        self.open_photo(str(examples[0]))

    def process_frame(self, frame):
        """May run in playback/export workers; only emit Qt signals here."""
        with self._state_lock:
            motor, attendance = self.motor, self.chamada
        annotated, results = motor.anotar(frame)
        changed = False
        if attendance is not None:
            for result in results:
                changed = attendance.registrar(result) or changed
        if not self._closed:
            try:
                self._resultsReady.emit(results)
                if changed:
                    self.attendanceChanged.emit()
            except RuntimeError:
                pass  # The application may be closing after a worker completed.
        return annotated

    @Slot(object)
    def _results_changed(self, results):
        if self._closed:
            return
        self.result_table.setRowCount(len(results))
        for row, result in enumerate(results):
            distance = (
                f"{result.distancia:.2f}" if np.isfinite(result.distancia) else "—"
            )
            for col, value in enumerate((result.codigo or "—", result.nome, distance)):
                self.result_table.setItem(row, col, QTableWidgetItem(str(value)))

    def open_photo(self, filename=None):
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getOpenFileName(
                self, "Abrir foto", "", IMAGE_FILTER
            )
        if filename:
            self._work(lambda: self._analyze(ler_imagem(filename)), self._show_photo)

    def _analyze(self, image):
        return image.copy(), self.process_frame(image)

    def analyze_image(self, image):
        if image is None:
            self._notify("Abra uma imagem primeiro.", True)
            return
        self._work(lambda: self._analyze(image.copy()), self._show_photo)

    def _show_photo(self, result):
        self._picture, self._annotated = result
        self._preview_pixmap = image_pixmap(self._annotated)
        self._scale_preview()
        self._notify(
            "Foto analisada. Os resultados mostram a distância LBPH de cada rosto."
        )

    def use_editor_image(self):
        self.analyze_image(self.get_image() if callable(self.get_image) else None)

    def use_video_image(self):
        self.analyze_image(
            self.get_video_frame() if callable(self.get_video_frame) else None
        )

    def save_photo(self, filename=None):
        if self._annotated is None:
            self._notify("Analise uma foto antes de salvar.", True)
            return
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Salvar reconhecimento", "reconhecimento.png", IMAGE_FILTER
            )
        if filename:
            image = self._annotated.copy()
            self._work(
                lambda: salvar_imagem(filename, image),
                lambda _: self._notify(f"Imagem salva em {filename}."),
            )

    def start_attendance(self, name=None):
        try:
            if self.chamada is not None and self.chamada.ativa:
                self._notify(
                    "Já há uma chamada ativa. Encerre a sessão antes de iniciar outra."
                )
                return
            name = self.session_name.text() if not isinstance(name, str) else name
            with self._state_lock:
                self.chamada = Chamada(name, self.bank.pasta / "chamadas")
            self._attendance_table()
            self._notify(
                "Chamada iniciada. Rostos identificados serão registrados uma vez por ID."
            )
        except (ErroFaces, OSError) as exc:
            self._notify(str(exc), True)

    def end_attendance(self):
        try:
            if self.chamada is None:
                self._notify("Nenhuma chamada iniciada.")
                return
            self.chamada.encerrar()
            self._attendance_table()
            self._notify("Chamada encerrada e guardada em JSON local.")
        except OSError as exc:
            self._notify(str(exc), True)

    @Slot()
    def _attendance_table(self):
        attendance = self.chamada
        rows = attendance.linhas() if attendance is not None else []
        self.attendance_table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            for col, key in enumerate(("id_aluno", "nome", "primeira_identificacao")):
                self.attendance_table.setItem(
                    row, col, QTableWidgetItem(str(record[key]))
                )
        self.attendance_label.setText(
            f"{attendance.nome} · {'ativa' if attendance.ativa else 'encerrada'} · {len(rows)} presente(s)"
            if attendance
            else "Nenhuma chamada iniciada"
        )

    def export_attendance_csv(self, filename=None):
        if self.chamada is None:
            self._notify("Inicie uma chamada antes de exportar.", True)
            return
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Exportar chamada", "chamada.csv", "CSV (*.csv)"
            )
        if filename:
            try:
                self.chamada.exportar_csv(filename)
                self._notify(f"Chamada exportada em {filename}.")
            except OSError as exc:
                self._notify(str(exc), True)

    def export_attendance_json(self, filename=None):
        if self.chamada is None:
            self._notify("Inicie uma chamada antes de exportar.", True)
            return
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Exportar chamada", "chamada.json", "JSON (*.json)"
            )
        if filename:
            try:
                Path(filename).write_text(
                    self.chamada.caminho.read_text(encoding="utf-8"), encoding="utf-8"
                )
                self._notify(f"Chamada exportada em {filename}.")
            except OSError as exc:
                self._notify(str(exc), True)

    def _scale_preview(self):
        if self._preview_pixmap is not None:
            self.preview.setPixmap(
                self._preview_pixmap.scaled(
                    self.preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_preview()

    def cleanup(self):
        self._closed = True
        if self.chamada is not None and self.chamada.ativa:
            try:
                self.chamada.encerrar()
            except OSError:
                pass

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)
