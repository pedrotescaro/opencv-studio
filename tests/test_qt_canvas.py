"""Behavioral canvas tests using real Qt events and offscreen painting."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

import numpy as np
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from studio.canvas import ImageCanvas, array_to_qimage


class CanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas = ImageCanvas()
        self.canvas.resize(640, 480)
        self.image = np.zeros((100, 200, 3), np.uint8)
        self.image[:, :, 2] = 220
        self.canvas.set_image(self.image)
        self.canvas.show()
        self.app.processEvents()

    def tearDown(self):
        self.canvas.close()
        self.canvas.deleteLater()
        self.app.processEvents()

    def test_owned_qimage_color_order_and_alpha(self):
        source = np.array([[[12, 34, 210, 87]]], np.uint8)
        result = array_to_qimage(source)
        source[:] = 0
        self.assertEqual(result.pixelColor(0, 0).getRgb(), (210, 34, 12, 87))
        self.assertEqual(
            array_to_qimage(np.array([[80]], np.uint8)).pixelColor(0, 0).red(), 80
        )
        with self.assertRaises(ValueError):
            array_to_qimage(np.zeros((0, 0, 3), np.uint8))
        with self.assertRaises(ValueError):
            array_to_qimage(np.zeros((2, 2, 2), np.uint8))

    def test_zoom_cursor_anchor_clamp_and_coordinate_roundtrip(self):
        anchor = QPointF(410, 210)
        before = self.canvas.widget_to_image(anchor)
        self.canvas.zoom_by(1.7, anchor)
        after = self.canvas.widget_to_image(anchor)
        self.assertAlmostEqual(before.x(), after.x(), places=8)
        self.assertAlmostEqual(before.y(), after.y(), places=8)
        point = QPointF(57.5, 32.2)
        roundtrip = self.canvas.widget_to_image(self.canvas.image_to_widget(point))
        self.assertAlmostEqual(point.x(), roundtrip.x(), places=8)
        self.canvas.set_zoom(1000)
        self.assertEqual(self.canvas.zoom, 32)
        self.canvas.set_zoom(0.001)
        self.assertEqual(self.canvas.zoom, 0.05)
        self.canvas.set_zoom(float("nan"))
        self.assertEqual(self.canvas.zoom, 0.05)

    def test_wheel_zoom_preserves_anchor_and_actual_fit(self):
        anchor = QPointF(420, 210)
        before = self.canvas.widget_to_image(anchor)
        event = QWheelEvent(
            anchor,
            anchor,
            QPoint(),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(self.canvas, event)
        after = self.canvas.widget_to_image(anchor)
        self.assertAlmostEqual(before.x(), after.x(), places=7)
        self.canvas.actual_size()
        self.assertEqual(self.canvas.zoom, 1)
        self.assertAlmostEqual(self.canvas.image_rect.center().x(), 320)
        self.canvas.fit_to_view()
        self.assertLessEqual(self.canvas.image_rect.width(), 640)
        self.assertLessEqual(self.canvas.image_rect.height(), 480)

    def test_rectangle_ellipse_crop_and_escape(self):
        self.canvas.actual_size()
        start = self.canvas.image_to_widget(QPointF(20, 10)).toPoint()
        end = self.canvas.image_to_widget(QPointF(100, 70)).toPoint()
        for tool in ("rect", "ellipse", "crop"):
            self.canvas.set_tool(tool)
            QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(self.canvas, end)
            QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=end)
            self.assertEqual(self.canvas.selection["rect"], (20, 10, 80, 60))
            self.assertEqual(
                self.canvas.selection["shape"],
                "ellipse" if tool == "ellipse" else "rect",
            )
        spy = QSignalSpy(self.canvas.cropRequested)
        QTest.keyClick(self.canvas, Qt.Key.Key_Return)
        self.assertEqual(spy.count(), 1)
        QTest.keyClick(self.canvas, Qt.Key.Key_Escape)
        self.assertIsNone(self.canvas.selection)

    def test_crop_fixed_ratio_and_bounds(self):
        self.canvas.actual_size()
        self.canvas.set_tool("crop")
        self.canvas.crop_ratio = 1.0
        start = self.canvas.image_to_widget(QPointF(10, 10)).toPoint()
        end = self.canvas.image_to_widget(QPointF(180, 80)).toPoint()
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.canvas, end)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(self.canvas.selection["rect"], (10, 10, 70, 70))

    def test_pan_middle_and_space_preserve_source_pixels(self):
        self.canvas.actual_size()
        before = self.canvas.image_rect.topLeft()
        QTest.mousePress(self.canvas, Qt.MouseButton.MiddleButton, pos=QPoint(300, 220))
        QTest.mouseMove(self.canvas, QPoint(340, 250))
        QTest.mouseRelease(
            self.canvas, Qt.MouseButton.MiddleButton, pos=QPoint(340, 250)
        )
        after = self.canvas.image_rect.topLeft()
        self.assertEqual(after - before, QPointF(40, 30))
        QTest.keyPress(self.canvas, Qt.Key.Key_Space)
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=QPoint(300, 220))
        QTest.mouseMove(self.canvas, QPoint(310, 225))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=QPoint(310, 225))
        QTest.keyRelease(self.canvas, Qt.Key.Key_Space)
        self.assertEqual(self.canvas.image_rect.topLeft() - after, QPointF(10, 5))

    def test_comparison_split_rendering_and_keyboard(self):
        processed = np.zeros_like(self.image)
        processed[:, :, 0] = 230
        self.canvas.set_images(self.image, processed)
        self.canvas.actual_size()
        self.canvas.split = True
        self.canvas.split_position = 0.5
        rendered = self.canvas.grab().toImage()
        left = self.canvas.image_to_widget(QPointF(30, 60)).toPoint()
        right = self.canvas.image_to_widget(QPointF(170, 60)).toPoint()
        self.assertEqual(rendered.pixelColor(left).getRgb()[:3], (220, 0, 0))
        self.assertEqual(rendered.pixelColor(right).getRgb()[:3], (0, 0, 230))
        QTest.keyPress(self.canvas, Qt.Key.Key_Backslash)
        self.assertTrue(self.canvas.compare_original)
        self.assertEqual(
            self.canvas.grab().toImage().pixelColor(right).getRgb()[:3], (220, 0, 0)
        )
        QTest.keyRelease(self.canvas, Qt.Key.Key_Backslash)
        self.assertFalse(self.canvas.compare_original)

    def test_eyedropper_and_text_emit_full_resolution_coordinates(self):
        self.canvas.actual_size()
        position = self.canvas.image_to_widget(QPointF(60, 40)).toPoint()
        self.canvas.set_tool("eyedropper")
        spy = QSignalSpy(self.canvas.colorPicked)
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, pos=position)
        self.assertEqual(spy.count(), 1)
        self.assertEqual(spy.at(0)[0], (220, 0, 0))
        self.canvas.set_tool("text")
        text_spy = QSignalSpy(self.canvas.textRequested)
        QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, pos=position)
        self.assertEqual(text_spy.at(0), [60, 40])

    def test_preview_does_not_change_stage_zoom_or_selection(self):
        self.canvas.actual_size()
        self.canvas.selection = {
            "shape": "rect",
            "rect": (1, 2, 20, 30),
            "source_size": (200, 100),
        }
        preview = self.image[::2, ::2].copy()
        self.canvas.set_images(self.image, preview, source_size=(200, 100))
        self.assertEqual(self.canvas.source_size, (200, 100))
        self.assertEqual(self.canvas.zoom, 1)
        self.assertEqual(self.canvas.selection["rect"], (1, 2, 20, 30))
        self.assertEqual(
            self.canvas._pixel_at(self.canvas.image_to_widget(QPointF(40, 40)))[2],
            (220, 0, 0),
        )

    def test_transparent_canvas_checker_and_empty_state_paint(self):
        transparent = np.zeros((20, 20, 4), np.uint8)
        self.canvas.set_image(transparent)
        self.canvas.set_zoom(4)
        output = self.canvas.grab().toImage()
        point = self.canvas.image_to_widget(QPointF(5, 5)).toPoint()
        color = output.pixelColor(point)
        self.assertIn(color.red(), (41, 50))
        self.canvas.set_image(None)
        self.assertFalse(self.canvas.grab().isNull())
        self.assertEqual(self.canvas.source_size, (0, 0))

    def test_split_handle_can_be_dragged_and_clamps_to_image(self):
        self.canvas.actual_size()
        self.canvas.split = True
        start = self.canvas.image_to_widget(QPointF(100, 50)).toPoint()
        end = self.canvas.image_to_widget(QPointF(150, 50)).toPoint()
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.canvas, end)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=end)
        self.assertAlmostEqual(self.canvas.split_position, 0.75)
        self.canvas.split_position = 5
        self.assertEqual(self.canvas.split_position, 1)

    def test_large_zoom_painter_only_receives_visible_source_rectangle(self):
        self.canvas.set_zoom(32)

        class RecordingPainter:
            def drawImage(recorder, target, image, source):
                recorder.target = target
                recorder.source = source

        recorder = RecordingPainter()
        self.canvas._draw_image(recorder, self.canvas._processed_qimage)
        self.assertLessEqual(recorder.source.width(), self.canvas.width() / 32 + 0.001)
        self.assertLessEqual(
            recorder.source.height(), self.canvas.height() / 32 + 0.001
        )
        self.assertGreaterEqual(recorder.source.left(), 0)
        self.assertLessEqual(recorder.source.right(), self.image.shape[1])
        self.assertLessEqual(recorder.target.width(), self.canvas.width())

    def test_file_drag_drop_emits_image_and_rejects_nonimage(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile("C:/photos/exemplo.png")])
        enter = QDragEnterEvent(
            QPointF(20, 20),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(self.canvas, enter)
        self.assertTrue(enter.isAccepted())
        spy = QSignalSpy(self.canvas.fileDropped)
        drop = QDropEvent(
            QPointF(20, 20),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(self.canvas, drop)
        self.assertEqual(spy.count(), 1)
        self.assertTrue(spy.at(0)[0].endswith("exemplo.png"))
        mime.setUrls([QUrl.fromLocalFile("C:/photos/exemplo.txt")])
        rejected = QDragEnterEvent(
            QPointF(20, 20),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(self.canvas, rejected)
        self.assertFalse(rejected.isAccepted())


if __name__ == "__main__":
    unittest.main()
