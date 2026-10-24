"""Continuous-camera lifecycle without opening a physical device in the suite."""

import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from studio.services.video import EFEITO_FACIAL
from studio.video import VideoPanel


APP = QApplication.instance() or QApplication([])


def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    raise AssertionError("A operação de câmera não terminou dentro do prazo.")


class FakeSource:
    """A changing stream that records reads and explicit resource release."""

    def __init__(self, origin):
        self.origem = origin
        self.camera = isinstance(origin, int)
        self.fps = 60
        self.largura, self.altura = 48, 32
        self.total = 0 if self.camera else 100
        self.posicao = 0
        self.closed = False
        self.fail_after = None
        self.raise_on_read = False

    def ler(self):
        if self.raise_on_read:
            raise OSError("Dispositivo desconectado durante a leitura")
        if self.closed or (
            self.fail_after is not None and self.posicao >= self.fail_after
        ):
            return False, None
        self.posicao += 1
        return True, np.full((32, 48, 3), self.posicao % 256, np.uint8)

    def reiniciar(self):
        self.posicao = 0
        return not self.camera

    def fechar(self):
        self.closed = True


class LiveCameraTests(unittest.TestCase):
    def setUp(self):
        self.sources = []

        def create_source(origin):
            # Most webcams are exclusive; opening a replacement before release
            # is a real failure even if both sources point to the same index.
            if isinstance(origin, int):
                self.assertFalse(any(s.camera and not s.closed for s in self.sources))
            source = FakeSource(origin)
            self.sources.append(source)
            return source

        self.factory = patch("studio.video.FonteVideo", side_effect=create_source)
        self.factory.start()
        self.panel = VideoPanel()

    def tearDown(self):
        self.panel.cleanup()
        QThreadPool.globalInstance().waitForDone(5000)
        APP.processEvents()
        self.panel.close()
        self.factory.stop()

    def open_camera(self):
        self.panel.open_camera()
        wait_for(lambda: self.panel.source is not None)
        wait_for(lambda: self.panel.get_frame() is not None)
        return self.panel.source

    def test_connect_autoplays_continuous_frames(self):
        source = self.open_camera()
        wait_for(lambda: source.posicao >= 4)
        self.assertTrue(self.panel._playing)
        self.assertTrue(self.panel.timer.isActive())
        self.assertEqual(self.panel.live_status.text(), "Ao vivo")
        self.assertEqual(self.panel.stop_button.text(), "Desligar câmera")
        self.assertFalse(self.panel.export_button.isEnabled())

    def test_stop_releases_and_restart_opens_fresh_connection(self):
        first = self.open_camera()
        self.panel.stop()
        # Reconnect immediately, even before the queued release has run.
        self.panel.open_camera()
        wait_for(lambda: self.panel.source is not None)
        second = self.panel.source
        wait_for(lambda: second.posicao >= 2)
        self.assertTrue(first.closed)
        self.assertIsNot(first, second)
        self.panel.stop()
        wait_for(lambda: second.closed)
        self.assertIsNone(self.panel.source)
        self.assertFalse(self.panel._playing)
        self.assertFalse(self.panel.timer.isActive())
        self.assertEqual(self.panel.live_status.text(), "Câmera desligada")
        count = second.posicao
        QTest.qWait(60)
        APP.processEvents()
        self.assertEqual(second.posicao, count)

    def test_scanner_uses_selected_index_and_facial_callback(self):
        processed = []

        def recognize(frame):
            processed.append(frame.copy())
            return 255 - frame

        self.panel.process_face = recognize
        self.panel.camera_index.setValue(2)
        self.panel.start_live_recognition()
        wait_for(lambda: len(processed) >= 3)
        self.panel.pause()
        wait_for(lambda: not self.panel._reading)
        self.assertEqual(self.panel.source.origem, 2)
        self.assertEqual(self.panel.effect.currentText(), EFEITO_FACIAL)
        np.testing.assert_array_equal(
            self.panel.get_processed_frame(), 255 - self.panel.get_frame()
        )

    def test_only_playing_camera_uses_attendance_callback(self):
        ordinary, live = [], []
        self.panel.process_face = lambda frame: ordinary.append(frame.copy()) or frame
        self.panel.process_live_face = lambda frame: live.append(frame.copy()) or frame
        self.panel.effect.setCurrentText(EFEITO_FACIAL)
        self.open_camera()
        wait_for(lambda: len(live) >= 3)
        self.panel.pause()
        wait_for(lambda: not self.panel._reading)
        count = len(live)
        self.panel._render_current_effect()
        wait_for(lambda: not self.panel._jobs)
        self.assertEqual(len(live), count)
        self.assertEqual(len(ordinary), 1)

        self.panel.open_source("source.avi")
        wait_for(lambda: self.panel.source is not None and not self.panel.source.camera)
        wait_for(lambda: self.panel.get_frame() is not None)
        self.panel.play()
        wait_for(lambda: len(ordinary) >= 4)
        self.panel.pause()
        wait_for(lambda: not self.panel._reading)
        self.assertEqual(len(live), count)

        def export_snapshot(origin, filename, effect, processor, **kwargs):
            processor(np.zeros((32, 48, 3), np.uint8))
            return {"frames": 1, "caminho": filename}

        before = len(ordinary)
        with patch("studio.video.exportar_arquivo_video", side_effect=export_snapshot):
            self.panel.export_video("controlled-export.avi")
            wait_for(lambda: not self.panel._jobs)
        self.assertEqual(len(ordinary), before + 1)
        self.assertEqual(len(live), count)

    def test_pause_and_resume_keep_one_connection(self):
        self.panel.process_face = lambda frame: frame
        source = self.open_camera()
        self.panel.pause()
        wait_for(lambda: not self.panel._reading)
        position = source.posicao
        QTest.qWait(60)
        APP.processEvents()
        self.assertEqual(source.posicao, position)
        self.assertFalse(source.closed)
        self.assertEqual(self.panel.live_status.text(), "Câmera pausada")
        self.panel.start_live_recognition()
        wait_for(lambda: source.posicao > position)
        self.assertEqual(len(self.sources), 1)
        self.assertIs(self.panel.source, source)
        self.assertEqual(self.panel.live_status.text(), "Ao vivo")

    def test_replaced_source_cannot_run_facial_callback_after_slow_read(self):
        started, release = threading.Event(), threading.Event()
        processed = []
        self.panel.process_face = lambda frame: processed.append(frame.copy()) or frame
        self.panel.effect.setCurrentText(EFEITO_FACIAL)
        source = self.open_camera()
        self.panel.pause()
        wait_for(lambda: not self.panel._reading)

        def slow_read():
            started.set()
            release.wait(3)
            return True, np.full((32, 48, 3), 99, np.uint8)

        source.ler = slow_read
        before = len(processed)
        try:
            self.panel.play()
            wait_for(started.is_set)
            self.panel.stop()
            release.set()
            wait_for(lambda: not self.panel._jobs and source.closed)
        finally:
            release.set()
        self.assertEqual(len(processed), before)

    def test_pending_file_stop_does_not_stop_replacement_camera(self):
        self.panel.open_source("source.avi")
        wait_for(lambda: self.panel.get_frame() is not None)
        source = self.panel.source
        started, release = threading.Event(), threading.Event()

        def slow_read():
            started.set()
            release.wait(3)
            return True, np.full((32, 48, 3), 50, np.uint8)

        source.ler = slow_read
        try:
            self.panel.play()
            wait_for(started.is_set)
            self.panel.stop()
            self.panel.open_camera()
            release.set()
            wait_for(lambda: self.panel.source is not None and self.panel.source.camera)
            camera = self.panel.source
            wait_for(lambda: camera.posicao >= 5)
            self.assertIs(self.panel.source, camera)
            self.assertTrue(self.panel._playing)
        finally:
            release.set()

    def test_switch_camera_to_file_closes_camera_and_keeps_file_paused(self):
        camera = self.open_camera()
        self.panel.open_source("source.avi")
        wait_for(lambda: self.panel.source is not None and not self.panel.source.camera)
        wait_for(lambda: self.panel.get_frame() is not None)
        self.assertTrue(camera.closed)
        self.assertFalse(self.panel._playing)
        self.assertEqual(self.panel.source.posicao, 1)
        self.assertTrue(self.panel.export_button.isEnabled())
        self.assertEqual(self.panel.live_status.text(), "Vídeo em arquivo")

    def test_stop_during_connect_does_not_restart_when_worker_returns(self):
        started, release = threading.Event(), threading.Event()
        source = FakeSource(0)

        def slow_open(_origin):
            started.set()
            release.wait(3)
            return source

        try:
            with patch("studio.video.FonteVideo", side_effect=slow_open):
                self.panel.open_camera()
                wait_for(started.is_set)
                self.assertTrue(self.panel.stop_button.isEnabled())
                self.panel.stop()
                release.set()
                wait_for(lambda: not self.panel._jobs)
        finally:
            release.set()
        self.assertTrue(source.closed)
        self.assertIsNone(self.panel.source)
        self.assertFalse(self.panel._playing)
        self.assertTrue(self.panel.camera_button.isEnabled())

    def test_camera_stops_when_frames_end(self):
        source = self.open_camera()
        source.fail_after = source.posicao + 1
        wait_for(lambda: self.panel.source is None)
        wait_for(lambda: source.closed)
        self.assertEqual(self.panel.live_status.text(), "Câmera interrompida")
        self.assertIn("parou de enviar imagens", self.panel.info.text())
        self.assertFalse(self.panel.timer.isActive())

    def test_camera_read_error_releases_device_and_allows_retry(self):
        source = self.open_camera()
        source.raise_on_read = True
        wait_for(lambda: self.panel.source is None)
        wait_for(lambda: source.closed)
        self.assertIn("Dispositivo desconectado", self.panel.info.text())
        self.assertTrue(self.panel.camera_button.isEnabled())
        self.assertFalse(self.panel.timer.isActive())


if __name__ == "__main__":
    unittest.main()
