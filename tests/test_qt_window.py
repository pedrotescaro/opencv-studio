"""Integration of real Qt controls, workers and non-destructive document state."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from studio.document import Operation
from studio.filters import render_pipeline
from studio.io import read_image
from studio.ui.window import MainWindow
from studio.ui.theme import STYLE
from studio.workers import RenderController

app = QApplication.instance() or QApplication([])
app.setStyleSheet(STYLE)


def wait_for(predicate, timeout=15):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    if not predicate():
        raise AssertionError("Qt operation did not finish in time")


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow()
        self.window.resize(1200, 800)
        self.window.show()
        self.image = np.random.default_rng(42).integers(
            0, 256, (100, 160, 4), dtype=np.uint8
        )
        self.image[:, :, 3] = 200
        self.window.open_array(self.image)
        wait_for(lambda: self.window.renderer.running is None)

    def tearDown(self):
        self.window.modified = False
        self.window.reset_draft(render=False)
        self.window.close()
        app.processEvents()

    def rendered(self):
        wait_for(
            lambda: (
                self.window.renderer.running is None
                and not self.window.debounce.isActive()
            )
        )

    def test_adjustment_filter_preset_history_and_original_are_integrated(self):
        w = self.window
        w.adjustment_controls["brightness"].set_value(20, True)
        self.rendered()
        self.assertFalse(np.array_equal(w.result, self.image))
        w.apply_draft()
        self.rendered()
        w.choose_filter("Sépia")
        w.request_render(False)
        self.rendered()
        w.apply_draft()
        self.rendered()
        self.assertEqual(len(w.document.operations), 2)
        w.undo()
        self.rendered()
        self.assertEqual(len(w.document.operations), 1)
        w.redo()
        self.rendered()
        self.assertEqual(len(w.document.operations), 2)
        w.jump_history(0)
        self.rendered()
        np.testing.assert_array_equal(w.result, self.image)
        w.preset.setCurrentText("Cinematic")
        self.rendered()
        self.assertTrue(w.has_draft())
        np.testing.assert_array_equal(w.document.original, self.image)

    def test_edit_selection_keeps_position_and_order_before_geometry(self):
        w = self.window
        selection = dict(shape="rect", rect=(5, 6, 20, 20), source_size=(160, 100))
        w.commit(
            Operation("adjustments", {"brightness": 20}, "Local", selection=selection)
        )
        w.commit(Operation("resize", {"width": 80, "height": 50}, "Metade"))
        self.rendered()
        w.operation_list.setCurrentRow(0)
        w.edit_operation()
        w.adjustment_controls["brightness"].set_value(40)
        ops = w.all_operations()
        self.assertEqual([o.kind for o in ops], ["adjustments", "resize"])
        self.assertEqual(ops[0].selection, selection)
        w.apply_draft()
        self.rendered()
        self.assertEqual(w.result.shape, (50, 80, 4))

    def test_curves_levels_crop_and_restore(self):
        w = self.window
        w.curve.set_points([(0, 0), (120, 180), (255, 255)])
        w.black.set_value(12)
        w.request_render(False)
        self.rendered()
        w.apply_draft()
        self.rendered()
        self.assertEqual([o.kind for o in w.document.operations], ["curves", "levels"])
        w.apply_crop(dict(shape="rect", rect=(10, 10, 30, 40), source_size=(160, 100)))
        self.rendered()
        self.assertEqual(w.result.shape, (40, 30, 4))
        w.restore()
        self.rendered()
        np.testing.assert_array_equal(w.result, self.image)

    def test_export_full_resolution_includes_draft_and_alpha(self):
        w = self.window
        w.adjustment_controls["exposure"].set_value(0.5)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edição.png"
            w._export(str(path), 92)
            wait_for(lambda: not w.jobs)
            from studio.io import read_image

            expected = render_pipeline(w.document.original, w.document.operations)
            np.testing.assert_array_equal(read_image(path), expected)
            self.assertFalse(w.modified)

    def test_raster_operand_export_does_not_compare_arrays_with_boolean(self):
        w = self.window
        w.commit(Operation("raster", {"image": self.image.copy()}, "Laboratório"))
        self.rendered()
        with tempfile.TemporaryDirectory() as tmp:
            w._export(str(Path(tmp) / "saida.png"), 95)
            wait_for(lambda: not w.jobs)
        self.assertFalse(w.modified)

    def test_export_requests_preserve_order_when_first_render_is_slow(self):
        w = self.window
        entered, second_started, release = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def gated(original, operations):
            if len(operations) == 1:
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("Test export was not released")
            else:
                second_started.set()
            return render_pipeline(original, operations)

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "ultima.png")
            with patch("studio.ui.window.render_pipeline", side_effect=gated):
                w.commit(Operation("adjustments", {"brightness": 10}, "Primeira"))
                w._export(path, 95)
                wait_for(entered.is_set)
                w.commit(Operation("adjustments", {"brightness": 20}, "Segunda"))
                expected = render_pipeline(w.document.original, w.all_operations())
                w._export(path, 95)
                try:
                    QTest.qWait(100)
                    self.assertFalse(second_started.is_set())
                finally:
                    release.set()
                wait_for(lambda: not w.jobs)
            self.assertTrue(second_started.is_set())
            np.testing.assert_array_equal(read_image(path), expected)
            self.assertFalse(w.modified)

    def test_preset_returns_to_full_resolution_after_idle(self):
        w = self.window
        image = np.full((1600, 2000, 3), (35, 100, 180), np.uint8)
        w.open_array(image)
        self.rendered()
        w.preset.setCurrentText("Warm Film")
        wait_for(lambda: w.renderer.running is None and not w.full_debounce.isActive())
        self.assertEqual(w.result.shape, image.shape)
        self.assertNotIn("prévia", w.dimension_label.text())

    def test_escape_discards_preview_and_clears_canvas_selection(self):
        w = self.window
        w.canvas.selection = dict(
            shape="rect", rect=(10, 10, 20, 20), source_size=(160, 100)
        )
        w.adjustment_controls["brightness"].set_value(20, True)
        w.canvas.setFocus()
        app.processEvents()
        QTest.keyClick(w.canvas, Qt.Key.Key_Escape)
        self.rendered()
        self.assertIsNone(w.canvas.selection)
        self.assertFalse(w.has_draft())

    def test_workspace_actions_and_video_frame_provider(self):
        w = self.window
        w.set_workspace(2)
        self.assertEqual(w.stack.currentIndex(), 2)
        with patch.object(w.faces, "save_photo") as save:
            w.save()
            save.assert_called_once()
        w.set_workspace(1)
        with patch.object(w.video, "export_frame") as save:
            w.save()
            save.assert_called_once()
        w.set_workspace(0)
        self.assertTrue(w.tools.isVisible())

    def test_neutralize_edit_removes_it_and_numeric_editor_remains_usable(self):
        w = self.window
        w.commit(Operation("adjustments", {"brightness": 20}, "Brilho"))
        self.rendered()
        w.operation_list.setCurrentRow(0)
        w.edit_operation()
        w.adjustment_controls["brightness"].set_value(0)
        self.assertTrue(w.has_draft())
        self.assertTrue(w.apply_draft())
        self.rendered()
        self.assertEqual(w.document.operations, [])
        number = w.adjustment_controls["brightness"].number
        app.processEvents()
        self.assertGreater(number.lineEdit().width(), 30)

    def test_invalid_levels_cannot_commit_or_export_a_different_recipe(self):
        w = self.window
        w.black.set_value(200)
        w.white.set_value(100)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.png"
            w._export(str(path), 95)
            self.assertFalse(path.exists())
            self.assertEqual(w.document.operations, [])

    def test_reset_and_illegal_file_report_error_without_losing_document(self):
        w = self.window
        w.choose_filter("Canny")
        w.reset_draft()
        self.rendered()
        self.assertFalse(w.has_draft())
        with patch.object(w, "error") as errors:
            w.open_path("arquivo-ausente.png")
            wait_for(lambda: not w.jobs)
        errors.assert_called_once()
        np.testing.assert_array_equal(w.document.original, self.image)


class WorkerTests(unittest.TestCase):
    def test_coalesces_stale_work_and_keeps_qt_event_loop_alive(self):
        controller = RenderController()
        image = np.zeros((8, 8, 3), np.uint8)
        accepted = []
        ticks = []
        controller.ready.connect(
            lambda data, generation, reduced: accepted.append(
                (generation, int(data[0, 0, 0]))
            )
        )

        def delayed(original, operations, max_size=None):
            time.sleep(0.05)
            return np.full_like(original, operations[0].params["value"])

        with patch("studio.filters.render_pipeline", side_effect=delayed):
            controller.request(image, [Operation("test", {"value": 1})])
            for n in range(2, 20):
                controller.request(image, [Operation("test", {"value": n})])
            QTimer.singleShot(1, lambda: ticks.append(True))
            wait_for(lambda: controller.running is None)
        self.assertTrue(ticks)
        self.assertEqual(accepted, [(19, 19)])
        controller.close()


if __name__ == "__main__":
    unittest.main()
