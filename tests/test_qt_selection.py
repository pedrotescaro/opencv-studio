"""Selection gestures, real context commands and active-layer pixel semantics."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import time
import unittest
import json
import zipfile
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QDialog, QSpinBox, QDialogButtonBox
from studio.canvas import ImageCanvas
from studio.document import Operation
from studio.filters import render_pipeline
from studio.io import read_image
from studio.project import read_project, write_project
from studio.selection import selection_mask, from_mask, combine, modify, paint_pixels
from studio.selection_edits import edit_pixels, layer_selection
from studio.ui.theme import STYLE
from studio.ui.window import MainWindow

app = QApplication.instance() or QApplication([])
app.setStyleSheet(STYLE)


def roi(rect=(10, 10, 20, 20), size=(80, 60), shape="rect"):
    return dict(rect=rect, source_size=size, shape=shape)


def wait_for(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    if not predicate():
        raise AssertionError("Selection worker did not finish")


class SelectionPixelsTests(unittest.TestCase):
    def setUp(self):
        self.image = np.full((60, 80, 3), (20, 60, 180), np.uint8)

    def test_combination_subtraction_intersection_and_empty(self):
        first, second = roi(), roi((20, 10, 20, 20))
        for mode, count in (("add", 600), ("subtract", 200), ("intersect", 200)):
            result = combine(first, second, (80, 60), mode)
            self.assertEqual(np.count_nonzero(result["mask"]), count)
            self.assertFalse(result["mask"].flags.writeable)
        self.assertIsNone(combine(first, first, (80, 60), "subtract"))
        self.assertIsNone(combine(None, second, (80, 60), "subtract"))

    def test_invert_modify_and_feather_keep_coverage(self):
        inverted = modify(roi(), (80, 60), "invert")
        self.assertEqual(inverted["mask"][15, 15], 0)
        self.assertEqual(inverted["mask"][1, 1], 255)
        for action in ("expand", "contract", "border", "smooth", "feather"):
            result = modify(roi(), (80, 60), action, 2)
            self.assertEqual(result["mask"].shape, (60, 80))
        soft = modify(roi(), (80, 60), "feather", 2)["mask"]
        self.assertTrue(np.any((soft > 0) & (soft < 255)))
        scaled = selection_mask((30, 40), from_mask(soft))
        self.assertEqual(scaled.shape, (30, 40))

    def test_copy_uses_active_source_and_preserves_global_filter_order(self):
        operations = [Operation("adjustments", {"brightness": 30}, "Brilho")]
        changed, layer_id = edit_pixels(self.image, operations, "base", roi(), "copy")
        self.assertEqual(changed[0].kind, "layer")
        self.assertEqual(changed[0].params["id"], layer_id)
        np.testing.assert_array_equal(
            changed[0].params["image"][0, 0, :3], self.image[10, 10]
        )
        np.testing.assert_array_equal(
            render_pipeline(self.image, changed)[:, :, :3],
            render_pipeline(self.image, operations),
        )
        np.testing.assert_array_equal(self.image[0, 0], (20, 60, 180))

    def test_cut_base_has_real_transparency_and_reconstructs_binary_selection(self):
        operations, _ = edit_pixels(self.image, [], "base", roi(), "cut")
        self.assertEqual([op.kind for op in operations], ["base_layer", "layer"])
        self.assertEqual(operations[0].params["image"][15, 15, 3], 0)
        self.assertEqual(operations[1].params["image"].shape, (20, 20, 4))
        rendered = render_pipeline(self.image, operations)
        np.testing.assert_array_equal(rendered[:, :, :3], self.image)
        self.assertTrue(np.all(rendered[:, :, 3] == 255))
        self.assertFalse(operations[0].params["image"].flags.writeable)

    def test_copy_ellipse_and_soft_mask_retains_alpha(self):
        for selection in (roi(shape="ellipse"), modify(roi(), (80, 60), "feather", 2)):
            operations, _ = edit_pixels(self.image, [], "base", selection, "copy")
            asset = operations[0].params["image"]
            self.assertTrue(np.any(asset[:, :, 3] < 255))

    def test_selection_maps_through_resize_crop_and_rotation(self):
        asset = np.full((12, 16, 4), (1, 2, 3, 255), np.uint8)
        layer = Operation(
            "layer", dict(id="a", image=asset, x=10, y=8, width=16, height=12)
        )
        ops = [
            layer,
            Operation("resize", dict(width=160, height=120)),
            Operation("crop", dict(rect=(10, 10, 100, 80))),
            Operation("rotate", dict(angle=90)),
        ]
        # Layer pixel (5,4) -> stage (20,14) -> rotation (65,20).
        selection = roi((63, 18, 5, 5), (80, 100))
        _, _, _, mask = layer_selection(self.image, ops, "a", selection)
        self.assertEqual(mask[4, 5], 255)
        self.assertEqual(mask[0, 0], 0)
        changed, _ = edit_pixels(self.image, ops, "a", selection, "delete")
        self.assertEqual(changed[0].params["image"][4, 5, 3], 0)
        self.assertEqual(asset[4, 5, 3], 255)

    def test_fill_stroke_delete_and_transparent_source_over(self):
        changed, _ = edit_pixels(
            self.image, [], "base", roi(), "fill", (240, 100, 30, 255)
        )
        output = render_pipeline(self.image, changed)
        np.testing.assert_array_equal(output[15, 15], (240, 100, 30, 255))
        np.testing.assert_array_equal(output[0, 0, :3], self.image[0, 0])
        changed, _ = edit_pixels(
            self.image, [], "base", roi(), "stroke", (255, 255, 255, 255), 2
        )
        output = render_pipeline(self.image, changed)
        self.assertEqual(output[10, 15, 0], 255)
        self.assertEqual(output[15, 15, 0], 20)
        transparent = np.zeros((1, 1, 4), np.uint8)
        result = paint_pixels(
            transparent, np.array([[128]], np.uint8), (20, 30, 40, 255)
        )
        np.testing.assert_array_equal(result[0, 0], (20, 30, 40, 128))

    def test_project_restores_edited_background_and_masked_filter_preview(self):
        operations, _ = edit_pixels(self.image, [], "base", roi(), "delete")
        operations.append(
            Operation(
                "adjustments",
                {"brightness": 20},
                selection=modify(roi(), (80, 60), "feather", 2),
            )
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "selection.ocvproj"
            write_project(path, self.image, operations)
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(json.loads(archive.read("project.json"))["version"], 2)
            original, restored = read_project(path)
            np.testing.assert_array_equal(
                render_pipeline(original, restored),
                render_pipeline(self.image, operations),
            )
            preview = render_pipeline(original, restored, max_size=40)
            self.assertEqual(preview.shape, (30, 40, 4))
            self.assertLess(preview[7, 7, 3], 20)

    def test_legacy_v1_projects_remain_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "modern.ocvproj"
            legacy = Path(folder) / "legacy.ocvproj"
            write_project(path, self.image, [])
            with (
                zipfile.ZipFile(path) as source,
                zipfile.ZipFile(legacy, "w") as target,
            ):
                for entry in source.infolist():
                    data = source.read(entry.filename)
                    if entry.filename == "project.json":
                        payload = json.loads(data)
                        payload["version"] = 1
                        data = json.dumps(payload).encode("utf-8")
                    target.writestr(entry.filename, data)
            original, operations = read_project(legacy)
            np.testing.assert_array_equal(original, self.image)
            self.assertEqual(operations, [])

    def test_raster_obscured_layer_and_transparent_copy_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "rasterizado"):
            edit_pixels(
                self.image,
                [Operation("raster", dict(image=self.image))],
                "base",
                roi(),
                "copy",
            )
        with self.assertRaisesRegex(ValueError, "transparente"):
            edit_pixels(np.zeros((60, 80, 4), np.uint8), [], "base", roi(), "copy")


class SelectionCanvasTests(unittest.TestCase):
    def setUp(self):
        self.canvas = ImageCanvas()
        self.canvas.resize(500, 400)
        self.canvas.show()
        self.canvas.set_image(np.full((60, 80, 3), (20, 60, 180), np.uint8))
        self.canvas.actual_size()
        self.canvas.set_tool("rect")

    def tearDown(self):
        self.canvas.close()
        app.processEvents()

    def gesture(self, start, end, modifier=Qt.KeyboardModifier.NoModifier):
        a = self.canvas.image_to_widget(QPointF(*start)).toPoint()
        b = self.canvas.image_to_widget(QPointF(*end)).toPoint()
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, modifier, a)
        QTest.mouseMove(self.canvas, b)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, modifier, b)

    def test_modifier_add_subtract_intersect_and_move_inside(self):
        self.gesture((10, 10), (30, 30))
        self.gesture((20, 10), (40, 30), Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(np.count_nonzero(self.canvas.selection["mask"]), 600)
        self.gesture((20, 10), (40, 30), Qt.KeyboardModifier.AltModifier)
        self.assertEqual(np.count_nonzero(self.canvas.selection["mask"]), 200)
        self.gesture((12, 12), (17, 17))
        self.assertEqual(self.canvas.selection["rect"], (15, 15, 10, 20))
        self.gesture(
            (15, 15),
            (22, 35),
            Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier,
        )
        self.assertEqual(self.canvas.selection["rect"], (15, 15, 7, 20))

    def test_eight_handles_resize_confirm_and_cancel(self):
        self.canvas.selection = roi()
        self.canvas.begin_selection_transform()
        self.assertEqual(len(self.canvas._selection_handles()), 8)
        self.gesture((30, 30), (45, 40))
        self.assertEqual(self.canvas.selection["rect"], (10, 10, 35, 30))
        QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
        self.assertEqual(self.canvas.selection["rect"], (10, 10, 20, 20))
        self.canvas.begin_selection_transform()
        self.gesture((30, 30), (40, 40))
        QTest.keyClick(self.canvas, Qt.Key.Key_Return)
        self.assertEqual(self.canvas.selection["rect"], (10, 10, 30, 30))
        self.assertFalse(self.canvas._selection_transform)

    def test_keyboard_nudge_and_shift_nudge_preserve_selection_shape(self):
        self.canvas.selection = roi(shape="ellipse")
        QTest.keyClick(self.canvas, Qt.Key.Key_Right)
        QTest.keyClick(self.canvas, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.canvas.selection["rect"], (11, 20, 20, 20))
        self.assertEqual(self.canvas.selection["shape"], "ellipse")

    def test_right_click_and_keyboard_menu_only_on_loaded_image(self):
        spy = QSignalSpy(self.canvas.contextRequested)
        point = self.canvas.image_to_widget(QPointF(20, 20)).toPoint()
        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, point, self.canvas.mapToGlobal(point)
        )
        QApplication.sendEvent(self.canvas, event)
        self.assertEqual(spy.count(), 1)
        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Keyboard, point, self.canvas.mapToGlobal(point)
        )
        QApplication.sendEvent(self.canvas, event)
        self.assertEqual(spy.count(), 2)
        self.canvas.set_image(None)
        QApplication.sendEvent(
            self.canvas,
            QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse, point, self.canvas.mapToGlobal(point)
            ),
        )
        self.assertEqual(spy.count(), 2)

    def test_ants_cache_does_not_tint_selected_pixels_and_stops_when_hidden(self):
        self.canvas.selection = modify(roi(), (80, 60), "invert")
        self.canvas.grab()
        cache = self.canvas._selection_path_cache
        self.canvas._animate_selection()
        self.canvas.grab()
        self.assertIs(self.canvas._selection_path_cache, cache)
        self.assertTrue(self.canvas._ants_timer.isActive())
        point = self.canvas.image_to_widget(QPointF(50, 40)).toPoint()
        self.assertEqual(
            self.canvas.grab().toImage().pixelColor(point).getRgb()[:3], (180, 60, 20)
        )
        self.canvas.hide()
        self.assertFalse(self.canvas._ants_timer.isActive())


class SelectionWindowTests(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow()
        self.errors = []
        self.window.error = self.errors.append
        self.window.show()
        self.window.open_array(np.full((60, 80, 3), (20, 60, 180), np.uint8))
        self.ready()
        self.window.canvas.selection = roi()

    def tearDown(self):
        self.window.modified = False
        self.window.reset_draft(render=False)
        self.window.close()
        app.processEvents()

    def ready(self):
        w = self.window
        wait_for(
            lambda: (
                not w.jobs
                and w.renderer.running is None
                and not w.debounce.isActive()
                and not w.full_debounce.isActive()
            )
        )
        self.assertEqual(self.errors, [])

    def test_menu_icons_and_enabled_states_track_selection_and_active_layer(self):
        menu = self.window.build_canvas_menu()
        actions = {
            a.text().split("\t")[0]: a for a in menu.actions() if not a.isSeparator()
        }
        self.assertTrue(actions["Camada via cópia"].isEnabled())
        self.assertFalse(actions["Transformação livre da camada…"].isEnabled())
        self.assertTrue(all(not a.icon().isNull() for a in actions.values()))
        self.window.canvas.clear_selection()
        menu = self.window.build_canvas_menu()
        actions = {a.text().split("\t")[0]: a for a in menu.actions()}
        self.assertFalse(actions["Camada via cópia"].isEnabled())
        self.assertTrue(actions["Preencher…"].isEnabled())
        self.assertTrue(actions["Nova camada transparente"].isEnabled())

    def test_context_copy_cut_fill_and_clickable_history_undo_redo(self):
        w = self.window
        w.edit_selection_pixels("cut")
        self.ready()
        self.assertEqual(len(w.document.operations), 2)
        self.assertEqual(w.layer_panel.list.count(), 2)
        self.assertIsNone(w.canvas.selection)
        self.assertEqual(w.document.operations[0].params["image"][15, 15, 3], 0)
        w.undo()
        self.ready()
        self.assertEqual(len(w.document.operations), 0)
        w.redo()
        self.ready()
        w.layer_panel.select_layer(w.document.operations[1].params["id"])
        w.canvas.selection = roi()
        w.edit_selection_pixels("fill", color=(255, 0, 0, 255))
        self.ready()
        np.testing.assert_array_equal(w.result[15, 15], (255, 0, 0, 255))
        w.jump_history(0)
        self.ready()
        np.testing.assert_array_equal(w.result[15, 15], (20, 60, 180))

    def test_ctrl_j_and_escape_cancel_selection_transform_in_main_window(self):
        w = self.window
        w.activateWindow()
        w.canvas.setFocus()
        QTest.qWait(50)
        QTest.keyClick(w.canvas, Qt.Key.Key_J, Qt.KeyboardModifier.ControlModifier)
        self.ready()
        self.assertEqual(w.layer_panel.list.count(), 2)
        w.canvas.selection = roi()
        w.canvas.begin_selection_transform()
        w.canvas.selection = roi((20, 20, 10, 10))
        QTest.keyClick(w.canvas, Qt.Key.Key_Escape)
        self.assertEqual(w.canvas.selection["rect"], (10, 10, 20, 20))

    def test_new_layer_is_transparent_fill_and_duplicate_edited_base(self):
        w = self.window
        original = w.result.copy()
        w.new_empty_layer()
        self.ready()
        self.assertEqual(w.layer_panel.list.count(), 2)
        np.testing.assert_array_equal(w.result[:, :, :3], original)
        w.canvas.clear_selection()
        w.edit_selection_pixels("fill", (30, 40, 50, 128))
        self.ready()
        self.assertEqual(w.document.operations[0].params["image"][0, 0, 3], 128)
        w.layer_panel.select_layer("base")
        w.edit_selection_pixels(
            "delete"
        )  # No selection: does not delete the whole image.
        self.ready()
        w.canvas.selection = roi()
        w.edit_selection_pixels("fill", (90, 80, 70, 255))
        self.ready()
        w.layer_action("duplicate", "base")
        self.ready()
        copied = [o for o in w.document.operations if o.kind == "layer"][-1]
        np.testing.assert_array_equal(copied.params["image"][15, 15], (90, 80, 70, 255))

    def test_save_load_mask_and_worker_stale_document_guard(self):
        w = self.window
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "selecao.png")
            with patch(
                "studio.ui.selection_actions.QFileDialog.getSaveFileName",
                return_value=(path, ""),
            ):
                w.save_selection()
            self.ready()
            self.assertEqual(read_image(path).shape, (60, 80))
            w.canvas.clear_selection()
            with patch(
                "studio.ui.selection_actions.QFileDialog.getOpenFileName",
                return_value=(path, ""),
            ):
                w.load_selection()
            self.ready()
            self.assertEqual(w.canvas.selection["rect"], (10, 10, 20, 20))
        w.edit_selection_pixels("cut")
        w.open_array(np.full((40, 50, 3), 200, np.uint8))
        self.ready()
        self.assertEqual(w.document.operations, [])
        self.assertEqual(w.result.shape, (40, 50, 3))

    def test_transform_dialog_preview_cancel_and_apply(self):
        w = self.window
        w.edit_selection_pixels("copy")
        self.ready()
        history = w.document.history.index

        def change(cancel):
            dialog = QApplication.activeModalWidget()
            self.assertIsInstance(dialog, QDialog)
            controls = dialog.findChildren(QSpinBox)
            controls[0].setValue(25)
            controls[2].setValue(35)
            (dialog.reject if cancel else dialog.accept)()

        QTimer.singleShot(30, lambda: change(True))
        w.transform_layer_dialog()
        self.ready()
        self.assertEqual(w.document.history.index, history)
        self.assertEqual(w.document.operations[0].params["x"], 10)
        QTimer.singleShot(30, lambda: change(False))
        w.transform_layer_dialog()
        self.ready()
        self.assertEqual(w.document.history.index, history + 1)
        self.assertEqual(w.document.operations[0].params["x"], 25)
        self.assertEqual(w.document.operations[0].params["width"], 35)

    def test_refine_edges_live_preview_apply_and_cancel_pending_changes(self):
        w = self.window
        original = w.canvas.selection

        def cancel_pending():
            dialog = QApplication.activeModalWidget()
            dialog.findChildren(QSpinBox)[1].setValue(4)
            dialog.reject()

        QTimer.singleShot(30, cancel_pending)
        w.refine_selection_dialog()
        self.ready()
        self.assertEqual(w.canvas.selection, original)
        results = []

        def accept_preview():
            dialog = QApplication.activeModalWidget()
            dialog.findChildren(QSpinBox)[1].setValue(2)
            QTest.qWait(250)
            self.ready()
            selection = w.canvas.selection
            results.append(
                "mask" in selection
                and np.any((selection["mask"] > 0) & (selection["mask"] < 255))
            )
            results.append(
                dialog.findChild(QDialogButtonBox)
                .button(QDialogButtonBox.StandardButton.Ok)
                .isEnabled()
            )
            dialog.accept()

        QTimer.singleShot(30, accept_preview)
        w.refine_selection_dialog()
        self.ready()
        self.assertEqual(results, [True, True])
        self.assertEqual(w.document.history.index, 0)


if __name__ == "__main__":
    unittest.main()
