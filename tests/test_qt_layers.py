"""Pixel-level layer composition, project integrity and integrated Qt editing."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import Qt, QPoint, QPointF, QMimeData, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from studio.document import Document, Operation
from studio.filters import render_pipeline
from studio.io import read_image, write_image
from studio.layers import composite_layer, base_layer, layer_transform, BLEND_MODES
from studio.project import read_project, write_project
from studio.ui.window import MainWindow
from studio.ui.theme import STYLE

app = QApplication.instance() or QApplication([])
app.setStyleSheet(STYLE)


def wait_for(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            app.processEvents()
            return
        time.sleep(0.005)
    raise AssertionError("Qt layer operation did not finish")


class LayerPixelTests(unittest.TestCase):
    def test_layer_coordinates_follow_all_legacy_flip_and_rotation_filters(self):
        original = np.zeros((20, 30, 3), np.uint8)
        layer = Operation(
            "layer", dict(id="a", image=np.full((1, 1, 3), 255, np.uint8), x=4, y=8)
        )
        for name in (
            "Flip horizontal",
            "Flip vertical",
            "Flip completo",
            "Rotacionar 90°",
            "Rotacionar -90°",
            "Rotacionar 180°",
            "Rotação livre",
        ):
            with self.subTest(name=name):
                ops = [layer, Operation("filter", dict(name=name, p1=90))]
                matrix = layer_transform(original.shape, ops, 0)
                x, y, _ = np.rint(matrix @ np.array([4, 8, 1])).astype(int)
                result = render_pipeline(original, ops)
                self.assertEqual(int(result[y, x, 0]), 255)

    def test_straight_alpha_composition_matches_known_values(self):
        base = np.full((4, 5, 3), 100, np.uint8)
        source = np.full((2, 2, 4), (0, 0, 255, 128), np.uint8)
        result = composite_layer(base, dict(image=source, x=1, y=1))
        np.testing.assert_array_equal(result[1, 1], (50, 50, 178, 255))
        np.testing.assert_array_equal(result[0, 0], (100, 100, 100, 255))
        np.testing.assert_array_equal(base, np.full_like(base, 100))

    def test_transparent_background_and_hidden_layers_preserve_alpha(self):
        base = np.zeros((4, 4, 4), np.uint8)
        source = np.full((2, 2, 4), (10, 90, 230, 128), np.uint8)
        result = composite_layer(base, dict(image=source, opacity=0.5))
        np.testing.assert_array_equal(result[0, 0], (10, 90, 230, 64))
        np.testing.assert_array_equal(result[3, 3], (0, 0, 0, 0))
        np.testing.assert_array_equal(
            composite_layer(base, dict(image=source, visible=False)), base
        )

    def test_negative_positions_and_completely_outside_layers(self):
        base = np.zeros((4, 4, 3), np.uint8)
        source = np.full((3, 3, 3), (10, 20, 30), np.uint8)
        out = composite_layer(base, dict(image=source, x=-2, y=-1))
        self.assertEqual(np.count_nonzero(out[:, :, 0]), 2)
        np.testing.assert_array_equal(out[:2, 0, :3], source[:2, 0])
        self.assertFalse(
            np.any(composite_layer(base, dict(image=source, x=40))[:, :, :3])
        )

    def test_blends_and_resizing_gray_layers(self):
        base = np.full((3, 3, 3), 128, np.uint8)
        source = np.full((1, 1), 128, np.uint8)
        expected = {"normal": 128, "multiply": 64, "screen": 192, "overlay": 128}
        for mode in BLEND_MODES:
            with self.subTest(mode=mode):
                out = composite_layer(
                    base, dict(image=source, width=3, height=3, blend=mode)
                )
                self.assertLessEqual(abs(int(out[1, 1, 0]) - expected[mode]), 1)

    def test_resizing_transparency_does_not_introduce_black_fringe(self):
        source = np.zeros((2, 2, 4), np.uint8)
        source[0, 0] = (255, 255, 255, 255)
        out = composite_layer(
            np.zeros((8, 8, 4), np.uint8), dict(image=source, width=8, height=8)
        )
        visible = out[:, :, 3] > 0
        self.assertTrue(np.all(out[:, :, :3][visible] == 255))

    def test_preview_scaling_layer_order_and_history_are_non_destructive(self):
        source = np.full((800, 1200, 3), 20, np.uint8)
        red = np.full((100, 200, 4), (0, 0, 255, 255), np.uint8)
        op = Operation(
            "layer", dict(id="r", image=red, x=400, y=200, width=200, height=100)
        )
        document = Document()
        document.open(source)
        document.commit(op)
        full, preview = document.render(), document.render(300)
        self.assertEqual(preview.shape, (200, 300, 4))
        np.testing.assert_array_equal(preview[51, 101], full[204, 404])
        self.assertFalse(document.operations[0].params["image"].flags.writeable)
        document.undo()
        np.testing.assert_array_equal(document.render(), source)
        document.redo()
        np.testing.assert_array_equal(document.render(), full)

    def test_base_visibility_and_later_geometry_use_the_same_recipe(self):
        base = np.full((20, 30, 3), 180, np.uint8)
        op = Operation(
            "layer", dict(id="a", image=np.full((4, 6, 3), 255, np.uint8), x=2, y=3)
        )
        ops = [
            Operation("base_layer", dict(id="base", visible=False)),
            op,
            Operation("resize", dict(width=60, height=40)),
        ]
        out = render_pipeline(base, ops)
        self.assertEqual(out.shape, (40, 60, 4))
        self.assertEqual(out[-1, -1, 3], 0)
        transform = layer_transform(base.shape, ops, 1)
        np.testing.assert_array_equal(transform[:2, :2], np.eye(2) * 2)
        ops.append(Operation("rotate", dict(angle=90)))
        transform = layer_transform(base.shape, ops, 1)
        np.testing.assert_array_equal(transform[:2, :2], [[0, -2], [2, 0]])

    def test_invalid_layer_dimensions_opacity_and_mode_are_reported(self):
        image = np.zeros((2, 2, 3), np.uint8)
        for values in (
            dict(width=0),
            dict(opacity=float("nan")),
            dict(opacity=2),
            dict(blend="invalid"),
            dict(width=100000, height=100000),
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                composite_layer(image, dict(image=image, **values))
        self.assertEqual(base_layer(image, dict(opacity=0.5))[0, 0, 3], 128)


class LayerProjectTests(unittest.TestCase):
    def test_invalid_properties_are_rejected_even_for_a_hidden_layer(self):
        image = np.zeros((4, 4, 3), np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.ocvproj"
            op = Operation("layer", dict(id="a", image=image, visible=False, opacity=2))
            write_project(path, image, [op])
            with self.assertRaises(ValueError):
                read_project(path)

    def test_lossless_portable_project_roundtrip_keeps_arrays_and_tuples(self):
        image = np.random.default_rng(10).integers(0, 256, (12, 18, 4), dtype=np.uint8)
        overlay = np.full((5, 8, 4), (5, 70, 190, 128), np.uint8)
        operations = [
            Operation(
                "layer", dict(id="a", name="Foto", image=overlay, x=-1, opacity=0.75)
            ),
            Operation(
                "adjustments",
                dict(brightness=10),
                selection=dict(shape="rect", rect=(1, 2, 5, 6), source_size=(18, 12)),
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "composição.ocvproj"
            write_project(path, image, operations)
            original, restored = read_project(path)
            np.testing.assert_array_equal(original, image)
            self.assertEqual(restored[1].selection["rect"], (1, 2, 5, 6))
            self.assertIsInstance(restored[1].selection["rect"], tuple)
            self.assertFalse(restored[0].params["image"].flags.writeable)
            np.testing.assert_array_equal(
                render_pipeline(original, restored), render_pipeline(image, operations)
            )

    def test_failure_preserves_existing_project(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "work.ocvproj"
            path.write_bytes(b"previous")
            with self.assertRaises(ValueError):
                write_project(
                    path,
                    np.zeros((2, 2, 3), np.uint8),
                    [Operation("filter", {"value": float("nan")})],
                )
            self.assertEqual(path.read_bytes(), b"previous")

    def test_corrupt_archive_and_unsupported_version_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.ocvproj"
            path.write_bytes(b"bad")
            with self.assertRaises(ValueError):
                read_project(path)
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "project.json",
                    json.dumps(dict(format="opencv-studio", version=999)),
                )
            with self.assertRaises(ValueError):
                read_project(path)

    def test_forged_numpy_dimensions_are_rejected_before_allocation(self):
        stream = io.BytesIO()
        np.lib.format.write_array_header_1_0(
            stream, dict(descr="|u1", fortran_order=False, shape=(10**12, 10**12))
        )
        payload = dict(
            format="opencv-studio",
            version=1,
            original={"__array__": "arrays/0.npy"},
            operations=[],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huge.ocvproj"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("project.json", json.dumps(payload))
                archive.writestr("arrays/0.npy", stream.getvalue())
            with self.assertRaisesRegex(ValueError, "Dimensões"):
                read_project(path)


class LayerWindowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.paths = []
        for index, color in enumerate(((20, 80, 210, 255), (180, 120, 30, 128))):
            path = Path(self.folder.name) / f"camada{index}.png"
            write_image(path, np.full((30, 40, 4), color, np.uint8))
            self.paths.append(str(path))
        self.window = MainWindow()
        self.window.show()
        self.window.open_array(np.full((100, 160, 3), 40, np.uint8))
        self.ready()

    def tearDown(self):
        self.window.modified = False
        self.window.reset_draft(render=False)
        self.window.close()
        app.processEvents()
        self.folder.cleanup()

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

    def import_images(self):
        self.window.import_layers(self.paths)
        self.ready()
        return [op for op in self.window.document.operations if op.kind == "layer"]

    def test_import_preview_opacity_visibility_and_undo_redo(self):
        w = self.window
        layers = self.import_images()
        self.assertEqual(w.layer_panel.list.count(), 3)
        selected = layers[-1].params["id"]
        self.assertEqual(w.layer_panel.current_id, selected)
        history = w.document.history.index
        w.layer_panel.opacity.set_value(50, True)
        self.ready()
        self.assertEqual(w.document.operations[-1].params["opacity"], 0.5)
        self.assertEqual(w.document.history.index, history + 1)
        item = w.layer_panel.list.currentItem()
        item.setCheckState(Qt.CheckState.Unchecked)
        self.ready()
        self.assertFalse(w.document.operations[-1].params["visible"])
        w.undo()
        self.ready()
        self.assertTrue(w.document.operations[-1].params["visible"])
        w.redo()
        self.ready()
        self.assertFalse(w.document.operations[-1].params["visible"])

    def test_duplicate_document_preserves_an_independent_layer_stack(self):
        w = self.window
        self.import_images()
        expected = w.result.copy()
        w.duplicate()
        self.ready()
        child = w.child_windows[-1]
        try:
            wait_for(lambda: child.renderer.running is None)
            self.assertEqual(child.layer_panel.list.count(), 3)
            self.assertFalse(
                np.shares_memory(child.document.original, w.document.original)
            )
            np.testing.assert_array_equal(child.result, expected)
            child.layer_action("remove", child.document.operations[-1].params["id"])
            self.assertEqual(len(w.document.operations), 2)
        finally:
            child.modified = False
            child.reset_draft(render=False)
            child.close()

    def test_drag_after_canvas_resize_converts_to_layer_source_coordinates(self):
        w = self.window
        layers = self.import_images()
        layer_id = layers[-1].params["id"]
        before = w._layer_params(layer_id)
        w.commit(Operation("resize", dict(width=320, height=200), "Dobrar"))
        self.ready()
        w.canvas.actual_size()
        start = w.canvas.image_to_widget(QPointF(160, 100)).toPoint()
        QTest.mousePress(w.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(w.canvas, start + QPoint(20, 10), delay=30)
        QTest.mouseRelease(
            w.canvas, Qt.MouseButton.LeftButton, pos=start + QPoint(20, 10)
        )
        self.ready()
        after = w._layer_params(layer_id)
        self.assertEqual((after["x"], after["y"]), (before["x"] + 10, before["y"] + 5))

    def test_drop_adds_layers_instead_of_replacing_background(self):
        w = self.window
        original = w.document.original
        position = QPoint(10, 10)
        for path, target in zip(
            self.paths,
            (w.layer_panel.list.viewport(), w.layer_panel.opacity.number.lineEdit()),
        ):
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(path)])
            app.sendEvent(
                target,
                QDragEnterEvent(
                    position,
                    Qt.DropAction.CopyAction,
                    mime,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
            app.sendEvent(
                target,
                QDropEvent(
                    QPointF(position),
                    Qt.DropAction.CopyAction,
                    mime,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
            self.ready()
        self.assertIs(w.document.original, original)
        self.assertEqual(sum(op.kind == "layer" for op in w.document.operations), 2)

    def test_reorder_duplicate_remove_and_base_visibility(self):
        w = self.window
        layers = self.import_images()
        ids = [op.params["id"] for op in layers]
        w.reorder_layers(ids)
        self.ready()
        self.assertEqual(
            [op.params["id"] for op in w.document.operations], list(reversed(ids))
        )
        w.layer_action("duplicate", ids[0])
        self.ready()
        self.assertEqual(len(w.document.operations), 3)
        clone = w.layer_panel.current_id
        w.layer_action("remove", clone)
        self.ready()
        self.assertEqual(len(w.document.operations), 2)
        w.preview_layer("base", dict(visible=False))
        w.commit_layer_preview()
        self.ready()
        self.assertEqual(w.result[0, 0, 3], 0)
        self.assertEqual(w.document.operations[0].kind, "base_layer")

    def test_canvas_drag_is_one_history_step_and_space_still_pans(self):
        w = self.window
        layers = self.import_images()
        layer_id = layers[-1].params["id"]
        w.canvas.actual_size()
        self.ready()
        start = w.canvas.image_to_widget(QPointF(80, 50)).toPoint()
        initial = w._layer_params(layer_id)
        history = w.document.history.index
        QTest.mousePress(w.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(w.canvas, start + QPoint(20, 10), delay=30)
        QTest.mouseRelease(
            w.canvas, Qt.MouseButton.LeftButton, pos=start + QPoint(20, 10)
        )
        self.ready()
        moved = w._layer_params(layer_id)
        self.assertEqual(
            (moved["x"], moved["y"]), (initial["x"] + 20, initial["y"] + 10)
        )
        self.assertEqual(w.document.history.index, history + 1)
        history = w.document.history.index
        QTest.keyPress(w.canvas, Qt.Key.Key_Space)
        QTest.mousePress(w.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(w.canvas, start + QPoint(-10, -5), delay=30)
        QTest.mouseRelease(
            w.canvas, Qt.MouseButton.LeftButton, pos=start + QPoint(-10, -5)
        )
        QTest.keyRelease(w.canvas, Qt.Key.Key_Space)
        self.assertEqual(w.document.history.index, history)

    def test_imported_layers_remain_below_general_filters_and_export_matches(self):
        w = self.window
        w.commit(Operation("adjustments", dict(brightness=20), "Brilho"))
        self.ready()
        self.import_images()
        self.assertEqual(w.document.operations[-1].kind, "adjustments")
        expected = render_pipeline(w.document.original, w.document.operations)
        target = Path(self.folder.name) / "resultado.png"
        w._export(str(target), 95)
        self.ready()
        np.testing.assert_array_equal(read_image(target), expected)
        self.assertTrue(
            w.modified, "A flattened export must not mark the layered project as saved"
        )

    def test_resize_keeps_aspect_and_project_reopens_all_layers(self):
        w = self.window
        self.import_images()
        w.layer_panel.geometry_controls["width"].setValue(80)
        w.layer_panel.released.emit()
        self.ready()
        self.assertEqual(
            (
                w.document.operations[-1].params["width"],
                w.document.operations[-1].params["height"],
            ),
            (80, 60),
        )
        expected = w.result.copy()
        target = Path(self.folder.name) / "trabalho.ocvproj"
        w._save_project(str(target))
        self.ready()
        self.assertFalse(w.modified)
        w.open_array(np.zeros((20, 20, 3), np.uint8))
        self.ready()
        w.open_project(str(target))
        self.ready()
        self.assertEqual(w.layer_panel.list.count(), 3)
        np.testing.assert_array_equal(w.result, expected)
        with patch.object(w, "save_project") as save:
            w.save()
            save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
