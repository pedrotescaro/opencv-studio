"""Compact layer rows, functional coverage/locks and persistent dock layout."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from pathlib import Path
import tempfile
import time
import unittest
import zipfile
import numpy as np
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QTabBar
from studio.document import Operation
from studio.filters import render_pipeline
from studio.layers import base_layer, composite_layer
from studio.project import read_project, write_project
from studio.selection_edits import edit_pixels
from studio.ui.window import MainWindow
from studio.ui.theme import STYLE

app = QApplication.instance() or QApplication([])
app.setStyleSheet(STYLE)


def wait_for(predicate, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            app.processEvents()
            if predicate():
                return
        time.sleep(0.005)
    raise AssertionError("Layer panel operation timed out")


class LayerPropertiesTests(unittest.TestCase):
    def test_fill_and_opacity_multiply_coverage_on_background_and_overlay(self):
        source = np.full((2, 3, 4), (20, 40, 60, 200), np.uint8)
        for result in (
            base_layer(source, dict(fill=0.5, opacity=0.5)),
            composite_layer(
                np.zeros_like(source), dict(image=source, fill=0.5, opacity=0.5)
            ),
        ):
            np.testing.assert_array_equal(result[0, 0], (20, 40, 60, 50))

    def test_transparency_lock_preserves_alpha_and_blocks_cut_delete(self):
        source = np.full((4, 4, 4), (20, 40, 60, 128), np.uint8)
        source[0] = 0
        operations = [
            Operation("base_layer", dict(id="base", image=source, lock_alpha=True))
        ]
        changed, _ = edit_pixels(
            source, operations, "base", None, "fill", (255, 0, 0, 255)
        )
        image = changed[0].params["image"]
        np.testing.assert_array_equal(image[:, :, 3], source[:, :, 3])
        np.testing.assert_array_equal(image[0], source[0])
        self.assertEqual(image[2, 2, 0], 255)
        for action in ("cut", "delete"):
            with self.assertRaisesRegex(ValueError, "bloqueada"):
                edit_pixels(source, operations, "base", None, action)

    def test_pixel_and_all_locks_allow_copy_but_block_changes(self):
        source = np.full((5, 6, 4), 255, np.uint8)
        for key in ("lock_pixels", "locked"):
            ops = [Operation("base_layer", dict(id="base", **{key: True}))]
            for action in ("fill", "stroke", "cut", "delete"):
                with self.assertRaisesRegex(ValueError, "bloqueada"):
                    edit_pixels(source, ops, "base", None, action, (0, 0, 0, 255))
            copied, _ = edit_pixels(source, ops, "base", None, "copy")
            self.assertEqual(copied[1].kind, "layer")

    def test_project_v3_preserves_properties_and_reads_previous_versions(self):
        source = np.full((4, 5, 3), 200, np.uint8)
        ops = [
            Operation(
                "base_layer",
                dict(
                    id="base",
                    name="Fundo",
                    fill=0.4,
                    opacity=0.8,
                    locked=True,
                    lock_alpha=True,
                    lock_pixels=True,
                    lock_position=True,
                ),
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layers.ocvproj"
            write_project(path, source, ops)
            original, restored = read_project(path)
            self.assertEqual(restored[0].params, ops[0].params)
            np.testing.assert_array_equal(
                render_pipeline(original, restored), render_pipeline(source, ops)
            )
            write_project(path, source, [])
            for version in (1, 2):
                legacy = Path(directory) / f"v{version}.ocvproj"
                with zipfile.ZipFile(path) as src, zipfile.ZipFile(legacy, "w") as dst:
                    for entry in src.infolist():
                        data = src.read(entry.filename)
                        if entry.filename == "project.json":
                            payload = json.loads(data)
                            self.assertEqual(payload["version"], 3)
                            payload["version"] = version
                            data = json.dumps(payload).encode()
                        dst.writestr(entry.filename, data)
                image, restored = read_project(legacy)
                np.testing.assert_array_equal(image, source)
                self.assertEqual(restored, [])


class CompactLayerPanelTests(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        self.window.open_array(np.full((60, 80, 3), 40, np.uint8))
        asset = np.full((20, 24, 4), (20, 90, 210, 255), np.uint8)
        asset.setflags(write=False)
        self.window.document.set_operations(
            [
                Operation(
                    "layer",
                    dict(
                        id="photo",
                        name="Foto",
                        image=asset,
                        x=10,
                        y=10,
                        width=24,
                        height=20,
                    ),
                )
            ],
            "Adicionar foto",
        )
        self.window._update_history()
        self.window.layer_panel.select_layer("photo")
        self.window.request_render(False)
        self.ready()

    def tearDown(self):
        self.window.layer_panel.properties.hide()
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

    def test_eye_click_and_name_edit_keep_the_same_layer_and_history(self):
        w, panel = self.window, self.window.layer_panel
        item = panel.list.currentItem()
        rect = panel.list.visualItemRect(item)
        history = w.document.history.index
        QTest.mouseClick(
            panel.list.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(rect.left() + 15, rect.center().y()),
        )
        self.ready()
        self.assertFalse(w._layer_params("photo")["visible"])
        self.assertEqual(w.document.history.index, history + 1)
        panel.list.setFocus()
        QTest.keyClick(panel.list, Qt.Key.Key_Space)
        self.ready()
        self.assertTrue(w._layer_params("photo")["visible"])
        panel.list.editItem(panel.list.currentItem())
        editor = panel.list.findChild(QLineEdit)
        self.assertIsNotNone(editor)
        editor.setText("Reconhecimento")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.ready()
        self.assertEqual(w._layer_params("photo")["name"], "Reconhecimento")
        self.assertEqual(panel.current_id, "photo")
        w.undo()
        self.ready()
        self.assertEqual(w._layer_params("photo")["name"], "Foto")

    def test_fill_control_updates_render_and_undo_redo(self):
        w, panel = self.window, self.window.layer_panel
        panel.fill.set_value(50, True)
        self.ready()
        self.assertEqual(w._layer_params("photo")["fill"], 0.5)
        np.testing.assert_allclose(w.result[15, 15, :3], (30, 65, 125), atol=1)
        w.undo()
        self.ready()
        self.assertEqual(panel.fill.value(), 100)
        w.redo()
        self.ready()
        self.assertEqual(panel.fill.value(), 50)

    def test_position_and_all_locks_block_move_transform_pixels_and_removal(self):
        w, panel = self.window, self.window.layer_panel
        panel.lock_buttons["lock_position"].click()
        self.ready()
        history = w.document.history.index
        w.preview_layer("photo", dict(x=40))
        w.commit_layer_preview()
        self.assertEqual(w.document.history.index, history)
        self.assertEqual(w._layer_params("photo")["x"], 10)
        self.assertFalse(panel.geometry_controls["x"].isEnabled())
        w.start_layer_drag()
        self.assertIsNone(w._layer_drag)
        panel.lock_buttons["locked"].click()
        self.ready()
        history = w.document.history.index
        self.assertFalse(panel.opacity.isEnabled())
        self.assertFalse(panel.fill.isEnabled())
        self.assertFalse(panel.buttons["remove"].isEnabled())
        w.layer_action("remove", "photo")
        w.canvas.selection = dict(
            shape="rect", rect=(10, 10, 10, 10), source_size=(80, 60)
        )
        w.edit_selection_pixels("delete")
        self.ready()
        self.assertEqual(w.document.history.index, history)
        actions = {a.text().split("\t")[0]: a for a in w.build_canvas_menu().actions()}
        self.assertFalse(actions["Camada por corte"].isEnabled())
        self.assertTrue(actions["Camada via cópia"].isEnabled())
        panel.buttons["duplicate"].click()
        self.ready()
        self.assertFalse(w._layer_params(panel.current_id)["locked"])

    def test_footer_new_and_delete_are_functional(self):
        w, panel = self.window, self.window.layer_panel
        original = w.document.original
        panel.buttons["new"].click()
        self.ready()
        self.assertEqual(panel.list.count(), 3)
        added = panel.current_id
        self.assertTrue(np.all(w._layer_params(added)["image"][:, :, 3] == 0))
        panel.buttons["remove"].click()
        self.ready()
        self.assertEqual(panel.list.count(), 2)
        self.assertIs(w.document.original, original)

    def test_layers_remain_visible_and_tabs_readable_at_small_window(self):
        w, panel = self.window, self.window.layer_panel
        w.resize(980, 660)
        for upper in (w.filters_dock, w.adjustments_dock, w.history_dock):
            upper.raise_()
            QTest.qWait(50)
            self.assertTrue(w.layer_dock.isVisible())
            self.assertNotIn(w.layer_dock, w.tabifiedDockWidgets(upper))
            self.assertFalse(w.layer_dock.geometry().intersects(upper.geometry()))
            self.assertGreaterEqual(panel.list.height(), 80)
        self.assertEqual(panel.list.visualItemRect(panel.list.item(0)).height(), 40)
        bars = [
            bar
            for bar in w.findChildren(QTabBar)
            if bar.isVisible() and bar.parent() is w
        ]
        self.assertTrue(bars)
        for bar in bars:
            self.assertGreaterEqual(bar.visibleRegion().boundingRect().height(), 30)

    def test_properties_open_without_reducing_list_and_close_in_sync(self):
        w, panel = self.window, self.window.layer_panel
        w.resize(980, 660)
        before = panel.list.height()
        panel.buttons["properties"].click()
        app.processEvents()
        self.assertTrue(panel.properties.isVisible())
        self.assertGreater(panel.properties.height(), 80)
        self.assertEqual(panel.list.height(), before)
        panel.properties.close()
        app.processEvents()
        self.assertFalse(panel.buttons["properties"].isChecked())

    def test_footer_stays_pinned_while_scrolling_layers(self):
        w, panel = self.window, self.window.layer_panel
        asset = w._layer_params("photo")["image"]
        operations = [
            Operation(
                "layer",
                dict(
                    id=f"photo{i}", name=f"Foto {i}", image=asset, width=24, height=20
                ),
            )
            for i in range(20)
        ]
        w.document.set_operations(operations, "Várias camadas")
        w._update_history()
        w.resize(980, 660)
        app.processEvents()
        footer_y = panel.buttons["new"].mapTo(panel, QPoint()).y()
        panel.list.verticalScrollBar().setValue(
            panel.list.verticalScrollBar().maximum()
        )
        app.processEvents()
        self.assertEqual(panel.buttons["new"].mapTo(panel, QPoint()).y(), footer_y)
        self.assertTrue(panel.buttons["new"].isVisible())
        self.assertGreater(panel.list.verticalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()
