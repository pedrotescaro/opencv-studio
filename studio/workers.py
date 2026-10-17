"""Jobs Qt e renderização serial: somente a solicitação mais recente fica pendente."""

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class JobSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = JobSignals()

    @Slot()
    def run(self):
        try:
            self.signals.done.emit(self.function())
        except Exception as exc:
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


class RenderController(QObject):
    ready = Signal(object, int, bool)
    failed = Signal(str)
    busyChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.generation = 0
        self.pending = None
        self.running = None
        self.closed = False

    def request(self, image, operations, reduced=False):
        self.generation += 1
        self.pending = (image, operations, reduced, self.generation)
        if self.running is None:
            self._start()

    def _start(self):
        if self.closed or self.pending is None:
            return
        from studio.filters import render_pipeline

        image, operations, reduced, generation = self.pending
        self.pending = None
        job = Job(
            lambda: render_pipeline(
                image, operations, max_size=1400 if reduced else None
            )
        )
        self.running = (job, generation, reduced)
        job.signals.done.connect(self._finished)
        job.signals.failed.connect(self._failed)
        self.busyChanged.emit(True)
        self.pool.start(job)

    @Slot(object)
    def _finished(self, image):
        if self.running is None:
            return
        _, generation, reduced = self.running
        self.running = None
        if not self.closed and generation == self.generation:
            self.ready.emit(image, generation, reduced)
        self._continue()

    @Slot(str)
    def _failed(self, error):
        if self.running is None:
            return
        _, generation, _ = self.running
        self.running = None
        if not self.closed and generation == self.generation:
            self.failed.emit(error)
        self._continue()

    def _continue(self):
        if self.running is not None:
            return
        if self.pending is not None and not self.closed:
            self._start()
        else:
            self.busyChanged.emit(False)

    def close(self):
        self.closed = True
        self.pending = None
        # A janela só é destruída depois de os workers liberarem os buffers.
        self.pool.waitForDone()
