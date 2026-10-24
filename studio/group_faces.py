"""Cadastro do grupo por pastas, integrado à câmera e à chamada Qt."""

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QTableWidgetItem

from .faces import FacePanel
from .services.faces import ErroFaces
from .services.sface_group import (
    GROUP_DATA_FOLDER,
    GROUP_FOLDER,
    carregar_grupo_treinado,
    carregar_integrantes,
    treinar_grupo,
    verificar_fontes_grupo,
)


class GroupFacePanel(FacePanel):
    """O aplicativo usa somente as identidades declaradas em fotos_grupo."""

    liveCameraRequested = Signal()

    def __init__(self, parent=None, get_image=None, group_folder=None, data_folder=None):
        self.group_folder = Path(group_folder) if group_folder is not None else GROUP_FOLDER
        self.group_data_folder = Path(data_folder) if data_folder is not None else GROUP_DATA_FOLDER
        self.members = []
        self._group_ready = False
        self._detection_motor = None
        super().__init__(
            parent, get_image, database_folder=self.group_data_folder, demo_enabled=False
        )

    def _build(self):
        super()._build()
        self.subtitle.setText("Fotos do grupo, comparação facial e chamada pela câmera ao vivo.")
        self.database.blockSignals(True)
        self.database.clear()
        self.database.addItem("Meu grupo · 3 integrantes")
        self.database.blockSignals(False)
        self.database.setEnabled(False)
        self.tabs.setMinimumWidth(350)
        form = self.register_layout.itemAt(0).layout()
        if isinstance(form, QFormLayout):
            for field in (self.identifier, self.person_name):
                form.labelForField(field).hide()
                field.hide()
        self.member_choice = QComboBox()
        self.member_choice.setAccessibleName("Integrante do grupo")
        self.member_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.member_choice.setMinimumContentsLength(20)
        self.member_choice.currentIndexChanged.connect(self._member_changed)
        self.register_layout.insertWidget(0, QLabel("Fotos do integrante"))
        self.register_layout.insertWidget(1, self.member_choice)
        self.import_button.clicked.disconnect()
        self.import_button.setText("Abrir pasta de fotos")
        self.import_button.setProperty("primary", False)
        self.import_button.clicked.connect(self.open_member_folder)
        self.capture_button.clicked.disconnect()
        self.capture_button.setText("Atualizar contagem de fotos")
        self.capture_button.clicked.connect(self.refresh_group)
        self.save_capture_button.clicked.disconnect()
        self.save_capture_button.setText("Treinar com as fotos do grupo")
        self.save_capture_button.setProperty("primary", True)
        self.save_capture_button.clicked.connect(self.train_model)
        self.capture_label.setText(
            "Coloque pelo menos duas fotos diferentes de cada integrante em sua pasta. "
            "Depois, treine o grupo."
        )
        self.remove_button.hide()
        self.roster.setHorizontalHeaderLabels(["ID", "Integrante", "Fotos"])
        self.roster.setWordWrap(True)
        self.demo_button.hide()
        self.model_note.setText(
            "O modelo compara somente Pedro, Guilherme e Paulo. Outras pessoas podem "
            "ser rejeitadas como Desconhecido, mas podem ocorrer falsos reconhecimentos. "
            "A distância SFace (1 − similaridade) não é uma porcentagem de confiança."
        )
        self.threshold.setRange(0.01, 1.0)
        self.threshold.setDecimals(3)
        self.threshold.setSingleStep(0.01)
        self.threshold.setValue(0.637)
        self.threshold.setToolTip("Distância SFace máxima (1 − similaridade de cosseno). Menor = mais restritivo.")
        self.result_table.setHorizontalHeaderLabels(["ID", "Resultado", "Distância SFace"])
        self.start_attendance_button.setText("Iniciar chamada ao vivo")
        live_row = QHBoxLayout()
        self.live_button = QPushButton("Abrir câmera ao vivo")
        self.live_button.clicked.connect(self.liveCameraRequested.emit)
        live_row.addWidget(self.live_button)
        live_note = QLabel("A chamada usa o grupo treinado. Reconhecimento não comprova presença física.")
        live_note.setWordWrap(True)
        live_row.addWidget(live_note, 1)
        self.layout().insertLayout(3, live_row)
        self._refresh_roster()

    def _member_changed(self, index):
        if 0 <= index < len(self.members):
            self.member_choice.setToolTip(self.members[index]["nome"])

    def _refresh_roster(self):
        try:
            self.members = carregar_integrantes(self.group_folder)
        except (ErroFaces, OSError) as exc:
            self.members = []
            self._notify(str(exc), True)
        previous = self.member_choice.currentData()
        self.member_choice.blockSignals(True)
        self.member_choice.clear()
        for member in self.members:
            self.member_choice.addItem(member["nome"], member["id"])
        selected = self.member_choice.findData(previous)
        self.member_choice.setCurrentIndex(max(0, selected))
        self.member_choice.blockSignals(False)
        self._member_changed(self.member_choice.currentIndex())
        self.roster.setRowCount(len(self.members))
        extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
        for row, member in enumerate(self.members):
            folder = self.group_folder / member["pasta"]
            count = sum(
                path.is_file() and path.suffix.lower() in extensions
                for path in folder.iterdir()
            ) if folder.is_dir() else 0
            for col, value in enumerate((member["id"], member["nome"], count)):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.roster.setItem(row, col, item)
        self.roster.resizeRowsToContents()

    def _select_person(self):
        row = self.roster.currentRow()
        if 0 <= row < len(self.members):
            self.member_choice.setCurrentIndex(row)

    def open_member_folder(self):
        index = self.member_choice.currentIndex()
        if not 0 <= index < len(self.members):
            self._notify("Confira integrantes.json antes de abrir a pasta.", True)
            return
        folder = self.group_folder / self.members[index]["pasta"]
        folder.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve()))):
            self._notify(f"Abra a pasta de fotos: {folder}", True)

    def refresh_group(self):
        self._switch_database(self.group_data_folder)

    def _switch_database(self, folder, initial=False):
        if self._busy:
            return
        self._notify("Conferindo fotos e modelo do grupo…")

        def prepare():
            try:
                return carregar_grupo_treinado(self.group_folder, self.group_data_folder), None
            except (ErroFaces, OSError) as exc:
                return None, str(exc)

        def done(result):
            trained, error = result
            if trained is not None:
                self._accept_training(trained)
            else:
                self._group_ready = False
                with self.motor.lock:
                    self.motor.modelo = None
                self.motor.status_modelo = error
                self._notify(error, True)

        self._work(prepare, done)

    def _job_finished(self, identifier, result, error):
        super()._job_finished(identifier, result, error)
        if self._closed:
            return
        self.database.setEnabled(False)
        if not self._group_ready:
            self.model_badge.setText("Grupo ainda não treinado")

    def _accept_training(self, result):
        with self._state_lock:
            self.bank, self.motor = result.banco, result.motor
        self._group_ready = True
        self.threshold.setValue(self.motor.limiar)
        self._notify(
            f"Grupo pronto: {result.total_pessoas} integrantes, {result.total_fotos} fotos. "
            "Abra a câmera ou inicie uma chamada ao vivo."
        )

    def train_model(self):
        if self.chamada is not None and self.chamada.ativa:
            self._notify("Encerre a chamada antes de treinar novamente.", True)
            return
        self._notify("Preparando YuNet/SFace e cadastrando as fotos dos três integrantes…")
        self._work(
            lambda: treinar_grupo(self.group_folder, self.group_data_folder),
            self._accept_training,
        )

    def start_attendance(self, name=None):
        try:
            if self._busy:
                raise ErroFaces("Aguarde o treinamento terminar antes de iniciar a chamada.")
            verificar_fontes_grupo(self.group_folder, self.group_data_folder)
            if not self._group_ready or not self.motor.pronto:
                raise ErroFaces("Treine as fotos dos três integrantes antes de iniciar a chamada.")
        except (ErroFaces, OSError) as exc:
            self._notify(str(exc), True)
            return
        already_active = self.chamada is not None and self.chamada.ativa
        super().start_attendance(name)
        if not already_active and self.chamada is not None and self.chamada.ativa:
            self.liveCameraRequested.emit()

    def process_frame(self, frame, record_attendance=True):
        # Never let the base motor's automatic reload bypass group validation.
        with self._state_lock:
            ready = self._group_ready
            motor = self.motor
            attendance = self.chamada if record_attendance else None
        if ready:
            verificar_fontes_grupo(self.group_folder, self.group_data_folder)
            annotated, results = motor.anotar(frame)
            changed = False
            if attendance is not None:
                for result in results:
                    changed = attendance.registrar(result) or changed
            if not self._closed:
                self._resultsReady.emit(results)
                if changed:
                    self.attendanceChanged.emit()
            return annotated
        # Detection remains available before any photos have been supplied.
        from .services.faces import BancoFaces, MotorFaces

        with self._state_lock:
            if self._detection_motor is None:
                self._detection_motor = MotorFaces(BancoFaces(self.group_data_folder / "deteccao"))
        annotated, results = self._detection_motor.anotar(frame)
        if not self._closed:
            self._resultsReady.emit(results)
        return annotated

    def _analyze(self, image):
        return image.copy(), self.process_frame(image, record_attendance=False)

    def _show_photo(self, result):
        super()._show_photo(result)
        self._notify("Foto analisada com SFace. Fotos de teste não registram presença na chamada ao vivo.")

    def _results_changed(self, results):
        super()._results_changed(results)
        for row, result in enumerate(results):
            if result.distancia != float("inf"):
                self.result_table.setItem(row, 2, QTableWidgetItem(f"{result.distancia:.3f}"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "roster"):
            self.roster.resizeRowsToContents()
