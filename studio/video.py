"""Responsive Qt video/camera workspace backed by the existing video service."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .services.faces import salvar_imagem
from .services.video import (
    EFEITO_FACIAL,
    EFEITOS_VIDEO,
    FonteVideo,
    aplicar_efeito,
    exportar_arquivo_video,
)

from .advanced_jobs import Job, image_pixmap


class VideoPanel(QWidget):
    statusMessage = Signal(str)
    frameReady = Signal(object)

    def __init__(self, parent=None, process_face=None):
        super().__init__(parent)
        self.process_face = process_face
        self.source = None
        self._source_lock = threading.RLock()
        self._frame_lock = threading.RLock()
        self._frame = self._processed = None
        self._jobs = {}
        self._generation = 0
        self._effect_generation = 0
        self._reading = False
        self._playing = False
        self._closed = False
        self._export_cancel = None
        self._pixmaps = [None, None]
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._next_frame)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        title = QLabel("Vídeo e câmera")
        title.setObjectName("workspaceTitle")
        title.setProperty("heading", True)
        layout.addWidget(title)
        subtitle = QLabel(
            "Reprodução com efeitos, reconhecimento facial e exportação do vídeo processado."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        source_row = QHBoxLayout()
        self.open_button = QPushButton("Abrir vídeo")
        self.open_button.clicked.connect(self.open_video)
        source_row.addWidget(self.open_button)
        self.camera_index = QSpinBox()
        self.camera_index.setRange(0, 20)
        source_row.addWidget(QLabel("Câmera"))
        source_row.addWidget(self.camera_index)
        self.camera_button = QPushButton("Conectar câmera")
        self.camera_button.clicked.connect(self.open_camera)
        source_row.addWidget(self.camera_button)
        source_row.addStretch()
        source_row.addWidget(QLabel("Efeito"))
        self.effect = QComboBox()
        self.effect.addItems(list(EFEITOS_VIDEO) + [EFEITO_FACIAL])
        self.effect.currentTextChanged.connect(self._effect_changed)
        source_row.addWidget(self.effect)
        layout.addLayout(source_row)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.previews = []
        for name in ("Original", "Processado"):
            widget = QWidget()
            box = QVBoxLayout(widget)
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(QLabel(name))
            preview = QLabel("Abra um vídeo ou conecte a câmera")
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setMinimumSize(180, 180)
            preview.setStyleSheet(
                "background:#191919;border:1px solid #393939;border-radius:6px;"
            )
            box.addWidget(preview, 1)
            splitter.addWidget(widget)
            self.previews.append(preview)
        layout.addWidget(splitter, 1)
        controls = QHBoxLayout()
        self.play_button = QPushButton("Reproduzir")
        self.play_button.clicked.connect(self.play_pause)
        self.stop_button = QPushButton("Parar / início")
        self.stop_button.clicked.connect(self.stop)
        self.frame_button = QPushButton("Salvar quadro")
        self.frame_button.clicked.connect(self.export_frame)
        self.editor_button = QPushButton("Enviar quadro ao editor")
        self.editor_button.clicked.connect(self.send_frame)
        self.export_button = QPushButton("Exportar vídeo com efeito")
        self.export_button.clicked.connect(self.export_video)
        for button in (
            self.play_button,
            self.stop_button,
            self.frame_button,
            self.editor_button,
            self.export_button,
        ):
            controls.addWidget(button)
        layout.addLayout(controls)
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.cancel_button = QPushButton("Cancelar exportação")
        self.cancel_button.clicked.connect(self.cancel_export)
        self.cancel_button.setEnabled(False)
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.cancel_button)
        layout.addLayout(progress_row)
        self.info = QLabel("Nenhuma fonte conectada")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

    def _notify(self, message):
        if self._closed:
            return
        self.info.setText(message)
        self.statusMessage.emit(message)

    def _work(self, function, callback, kind="operation"):
        job = Job(function)
        self._jobs[job.identifier] = (job, callback, kind)
        job.signals.completed.connect(self._job_finished)
        QThreadPool.globalInstance().start(job)
        return job

    @Slot(int, object, str)
    def _job_finished(self, identifier, result, error):
        item = self._jobs.pop(identifier, None)
        if item is None:
            return
        _, callback, kind = item
        if kind == "frame":
            self._reading = False
        if self._closed:
            if kind == "source" and result is not None:
                result.fechar()
            return
        if kind == "source":
            self.open_button.setEnabled(True)
            self.camera_button.setEnabled(True)
        if kind == "export":
            self._export_cancel = None
            self.cancel_button.setEnabled(False)
            self.export_button.setEnabled(True)
        if error:
            self._notify(error)
            if kind == "frame":
                self.pause()
        else:
            callback(result)

    def open_video(self, filename=None):
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getOpenFileName(
                self,
                "Abrir vídeo",
                "",
                "Vídeos (*.mp4 *.avi *.mov *.mkv *.webm *.m4v);;Todos (*)",
            )
        if filename:
            self.open_source(str(filename))

    def open_camera(self, index=None):
        self.open_source(
            self.camera_index.value()
            if not isinstance(index, int) or isinstance(index, bool)
            else index
        )

    def open_source(self, origin):
        if self._closed:
            return
        self.pause()
        self._generation += 1
        generation = self._generation
        self.open_button.setEnabled(False)
        self.camera_button.setEnabled(False)
        self._notify("Conectando fonte em segundo plano…")

        def open_capture():
            source = FonteVideo(origin)
            if self._closed or generation != self._generation:
                source.fechar()
                return None
            return source

        def done(source):
            if source is None:
                return
            if generation != self._generation:
                source.fechar()
                return
            old = self.source
            self.source = source
            if old is not None:
                self._close_source_async(old)
            with self._frame_lock:
                self._frame = self._processed = None
            self._reading = False
            self.timer.setInterval(max(1, round(1000 / min(source.fps, 120))))
            self._notify(
                f"{'Câmera ' + str(origin) if source.camera else Path(str(origin)).name} · {source.largura} × {source.altura} · {source.fps:.2f} fps"
            )
            self._next_frame()

        self._work(open_capture, done, "source")

    def play_pause(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if self.source is None:
            self._notify("Abra um vídeo ou conecte a câmera primeiro.")
            return
        self._playing = True
        self.play_button.setText("Pausar")
        self.timer.start()
        self._next_frame()

    def pause(self):
        self._playing = False
        self.timer.stop()
        self.play_button.setText("Reproduzir")

    def stop(self):
        self.pause()
        source = self.source
        if source is None:
            return
        if source.camera:
            self.source = None
            self._generation += 1
            self._close_source_async(source)
            self._notify("Câmera desconectada.")
            return
        if self._reading:
            QTimer.singleShot(30, self.stop)
            return

        def rewind():
            with self._source_lock:
                if not source.reiniciar():
                    raise ValueError(
                        "O arquivo não permite voltar ao início; abra-o novamente."
                    )

        self._work(rewind, lambda _: self._next_frame())

    def _next_frame(self):
        if self.source is None or self._reading or self._closed:
            return
        self._reading = True
        generation, source = self._generation, self.source
        effect, processor = self.effect.currentText(), self.process_face
        effect_generation = self._effect_generation

        def read():
            with self._source_lock:
                if self._closed or generation != self._generation:
                    return generation, None, None, 0
                ok, frame = source.ler()
                position = source.posicao
            if not ok:
                return generation, None, None, position
            return generation, frame, aplicar_efeito(frame, effect, processor), position

        def done(result):
            received_generation, frame, processed, position = result
            if received_generation != self._generation:
                return
            if frame is None:
                self.pause()
                self._notify(
                    "Fim do vídeo. Use Parar / início para reproduzir novamente."
                )
                return
            with self._frame_lock:
                self._frame, self._processed = frame.copy(), processed.copy()
            self._pixmaps = [image_pixmap(frame), image_pixmap(processed)]
            self._scale_previews()
            if effect_generation != self._effect_generation:
                self._render_current_effect()
            if source.total:
                self._notify(
                    f"Quadro {position}/{source.total} · {source.largura} × {source.altura} · {effect}"
                )

        self._work(read, done, "frame")

    def _effect_changed(self):
        self._effect_generation += 1
        self._render_current_effect()

    def _render_current_effect(self):
        frame = self.get_frame()
        if frame is None or self._reading or self._closed:
            return
        effect, processor, generation = (
            self.effect.currentText(),
            self.process_face,
            self._generation,
        )
        effect_generation = self._effect_generation

        def done(processed):
            if (
                generation != self._generation
                or effect_generation != self._effect_generation
            ):
                return
            with self._frame_lock:
                self._processed = processed.copy()
            self._pixmaps[1] = image_pixmap(processed)
            self._scale_previews()

        self._work(lambda: aplicar_efeito(frame, effect, processor), done)

    def get_frame(self):
        """The original frame, safe for training without effect contamination."""
        with self._frame_lock:
            return None if self._frame is None else self._frame.copy()

    def get_processed_frame(self):
        with self._frame_lock:
            return None if self._processed is None else self._processed.copy()

    def send_frame(self):
        frame = self.get_processed_frame()
        if frame is None:
            self._notify("Nenhum quadro disponível.")
            return
        self.frameReady.emit(frame)
        self._notify("Quadro processado enviado ao editor.")

    def export_frame(self, filename=None):
        frame = self.get_processed_frame()
        if frame is None:
            self._notify("Nenhum quadro disponível para salvar.")
            return
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Salvar quadro",
                "quadro.png",
                "Imagens (*.png *.jpg *.webp *.tiff)",
            )
        if filename:
            self._work(
                lambda: salvar_imagem(filename, frame),
                lambda _: self._notify(f"Quadro salvo em {filename}."),
            )

    def export_video(self, filename=None):
        if self._export_cancel is not None:
            self._notify("Uma exportação já está em andamento.")
            return
        source = self.source
        if source is None or source.camera:
            self._notify("Abra um arquivo de vídeo para exportar todos os quadros.")
            return
        if isinstance(filename, bool) or filename is None:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Exportar vídeo (sem áudio)",
                "video_processado.mp4",
                "MP4 (*.mp4);;AVI (*.avi)",
            )
        if not filename:
            return
        self._export_cancel = cancel = threading.Event()
        self.cancel_button.setEnabled(True)
        self.export_button.setEnabled(False)
        self.progress.setValue(0)
        effect, processor, origin = (
            self.effect.currentText(),
            self.process_face,
            source.origem,
        )
        job = Job(
            lambda: exportar_arquivo_video(
                origin,
                filename,
                effect,
                processor,
                cancelar=cancel,
                progresso=lambda current, total: job.signals.progress.emit(
                    str(round(100 * current / max(1, total)))
                ),
            )
        )
        self._jobs[job.identifier] = (job, self._export_done, "export")
        job.signals.completed.connect(self._job_finished)
        job.signals.progress.connect(self._export_progress)
        QThreadPool.globalInstance().start(job)
        self._notify(
            "Exportando em segundo plano. O arquivo contém o vídeo processado, sem áudio."
        )

    @Slot(str)
    def _export_progress(self, value):
        if not self._closed:
            self.progress.setValue(min(100, int(value)))

    def _export_done(self, result):
        self.progress.setValue(100)
        self._notify(
            f"{result['frames']} quadros exportados: {result['caminho']} (sem áudio)."
        )

    def cancel_export(self):
        if self._export_cancel is not None:
            self._export_cancel.set()
            self._notify("Cancelando exportação…")

    def _close_source_async(self, source):
        lock = self._source_lock

        def close_source():
            with lock:
                source.fechar()

        # Resource cleanup has no widget callback and remains safe after deletion.
        QThreadPool.globalInstance().start(Job(close_source))

    def _scale_previews(self):
        for preview, pixmap in zip(self.previews, self._pixmaps):
            if pixmap is not None:
                preview.setPixmap(
                    pixmap.scaled(
                        preview.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_previews()

    def cleanup(self):
        self._closed = True
        self.timer.stop()
        self._playing = False
        self._generation += 1
        if self._export_cancel is not None:
            self._export_cancel.set()
        source, self.source = self.source, None
        if source is not None:
            self._close_source_async(source)

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)
