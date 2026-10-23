"""Exercise the Qt workspaces against real arrays, persisted models and files."""

import csv
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from studio.services.faces import BancoFaces, MotorFaces, ResultadoFace
from studio.faces import DEMO_FOLDER, FacePanel, register_photos
from studio.science import ScienceDialog, arithmetic, export_matrix, import_matrix
from studio.video import VideoPanel

APP = QApplication.instance() or QApplication([])


def wait_for(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            APP.processEvents()
            return
        QTest.qWait(10)
    raise AssertionError("O worker Qt não concluiu dentro do prazo.")


def wait_idle(widget):
    wait_for(
        lambda: (
            not widget._jobs
            and not getattr(widget, "_busy", False)
            and not getattr(widget, "_histogram_jobs", {})
        )
    )
    QTest.qWait(20)
    wait_for(
        lambda: (
            not widget._jobs
            and not getattr(widget, "_busy", False)
            and not getattr(widget, "_histogram_jobs", {})
        )
    )


class ScienceWorkspaceTests(unittest.TestCase):
    def test_hsv_histogram_bins_share_the_same_intensity_axis(self):
        chart = self.dialog.histogram
        chart.set_data({"H": np.zeros(180), "S": np.zeros(256), "V": np.zeros(256)})
        for counts in chart.values.values():
            counts[90] = 1
        with patch("studio.science.QPainter") as painter:
            chart.paintEvent(None)
        peaks = [
            call.args[0].elementAt(90).x
            for call in painter.return_value.drawPath.call_args_list
        ]
        self.assertEqual(len(peaks), 3)
        self.assertAlmostEqual(peaks[0], peaks[1])
        self.assertAlmostEqual(peaks[0], peaks[2])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        y, x = np.indices((100, 140))
        self.image = np.dstack((x % 256, y % 256, (x + y) % 256)).astype(np.uint8)
        self.dialog = ScienceDialog(self.image)

    def tearDown(self):
        wait_idle(self.dialog)
        self.dialog.close()
        self.dialog.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def test_arithmetic_saturates_and_preserves_input(self):
        first = np.full((10, 10, 3), 240, np.uint8)
        second = np.full((10, 10, 3), 40, np.uint8)
        self.assertTrue(np.all(arithmetic(first, second, "Adição") == 255))
        self.assertTrue(np.all(arithmetic(second, first, "Subtração") == 0))
        self.assertTrue(
            np.all(arithmetic(first, second, "Mistura ponderada", 0.5) == 140)
        )
        self.assertTrue(np.all(first == 240))
        with self.assertRaises(ValueError):
            arithmetic(first, second[:5], "Adição")
        self.assertEqual(
            arithmetic(first, second[:5], "Adição", resize_second=True).shape,
            first.shape,
        )

    def test_legacy_composition_modes_remain_available(self):
        first = np.array([[[16, 80, 230]]], np.uint8)
        second = np.array([[[48, 150, 200]]], np.uint8)
        expectations = {
            "AND (bit a bit)": cv2.bitwise_and(first, second),
            "OR (bit a bit)": cv2.bitwise_or(first, second),
            "XOR (bit a bit)": cv2.bitwise_xor(first, second),
            "Multiplicar": np.rint(first.astype(float) * second / 255).astype(np.uint8),
            "Screen": np.rint(
                255 - (255 - first.astype(float)) * (255 - second.astype(float)) / 255
            ).astype(np.uint8),
        }
        for mode, expected in expectations.items():
            with self.subTest(mode=mode):
                np.testing.assert_array_equal(arithmetic(first, second, mode), expected)
                self.assertGreaterEqual(
                    self.dialog.arithmetic_operation.findText(mode), 0
                )

    def test_real_rgb_hsv_matrix_roundtrip_and_npz(self):
        self.dialog.color_destination.setCurrentText("RGB")
        self.dialog.convert_color()
        wait_idle(self.dialog)
        np.testing.assert_array_equal(self.dialog.matrix, self.image[:, :, ::-1])
        np.testing.assert_array_equal(self.dialog.result, self.image)
        self.dialog.color_destination.setCurrentText("HSV")
        self.dialog.convert_color()
        wait_idle(self.dialog)
        self.assertEqual(self.dialog.model, "HSV")
        path = self.folder / "matriz.npz"
        self.dialog.save_matrix(str(path))
        wait_idle(self.dialog)
        matrix, model = import_matrix(path)
        self.assertEqual(model, "HSV")
        np.testing.assert_array_equal(matrix, self.dialog.matrix)
        self.dialog.color_destination.setCurrentText("BGR")
        self.dialog.convert_color()
        wait_idle(self.dialog)
        self.assertLessEqual(
            np.abs(self.dialog.result.astype(int) - self.image.astype(int)).max(), 4
        )

    def test_transparency_survives_scientific_operation_and_apply(self):
        self.dialog.close()
        alpha = np.broadcast_to(np.arange(140, dtype=np.uint8), (100, 140)).copy()
        self.dialog = ScienceDialog(np.dstack((self.image, alpha)))
        self.dialog.channel.setCurrentText("G")
        self.dialog.split_channel()
        wait_idle(self.dialog)
        emitted = []
        self.dialog.resultReady.connect(lambda image, label: emitted.append(image))
        self.dialog.apply_result()
        self.assertEqual(emitted[0].shape, (100, 140, 4))
        np.testing.assert_array_equal(emitted[0][:, :, 3], alpha)
        np.testing.assert_array_equal(emitted[0][:, :, 0], self.image[:, :, 1])

    def test_npz_without_pickle_rejects_invalid_color_model(self):
        path = self.folder / "bad.npz"
        export_matrix(path, self.image, "XYZ")
        with self.assertRaises(ValueError):
            import_matrix(path)

    def test_channel_split_quantization_histogram_and_apply(self):
        self.dialog.channel.setCurrentText("G")
        self.dialog.split_channel()
        wait_idle(self.dialog)
        np.testing.assert_array_equal(self.dialog.result, self.image[:, :, 1])
        self.assertEqual(int(self.dialog.histogram.values["R"].sum()), 14000)
        self.dialog.quantization_levels.setValue(4)
        self.dialog.quantize()
        wait_idle(self.dialog)
        self.assertTrue(set(np.unique(self.dialog.result)).issubset({0, 85, 170, 255}))
        emitted = []
        self.dialog.resultReady.connect(
            lambda image, label: emitted.append((image, label))
        )
        self.dialog.apply_result()
        self.assertEqual(len(emitted), 1)
        self.assertFalse(np.shares_memory(emitted[0][0], self.dialog.base))

    def test_arithmetic_ui_reads_real_second_file(self):
        path = self.folder / "second.png"
        cv2.imwrite(str(path), np.full((80, 90, 3), 100, np.uint8))
        self.dialog.open_second_image(str(path))
        wait_idle(self.dialog)
        self.dialog.arithmetic_operation.setCurrentText("Subtração")
        self.dialog.run_arithmetic()
        wait_idle(self.dialog)
        np.testing.assert_array_equal(
            self.dialog.result, cv2.subtract(self.image, np.full_like(self.image, 100))
        )

    def test_region_growing_uses_connected_fixed_range(self):
        image = np.zeros((80, 100, 3), np.uint8)
        image[10:50, 10:50] = 100
        image[10:50, 60:90] = 100
        self.dialog.close()
        self.dialog = ScienceDialog(image)
        self.dialog.seed_x.setValue(20)
        self.dialog.seed_y.setValue(20)
        self.dialog.region_tolerance.setValue(0)
        self.dialog.run_region_growing()
        wait_idle(self.dialog)
        self.assertEqual(np.count_nonzero(self.dialog.result), 1600)
        path = self.folder / "mask.png"
        self.dialog.save_segmentation(str(path))
        wait_idle(self.dialog)
        self.assertTrue(path.exists())
        self.assertTrue(path.with_name("mask_sobreposicao.png").exists())

    def test_grabcut_preserves_real_pipeline_and_component_counts(self):
        image = np.full((100, 140, 3), 30, np.uint8)
        cv2.rectangle(image, (45, 30), (95, 75), (210, 180, 70), -1)
        self.dialog.close()
        self.dialog = ScienceDialog(image)
        self.dialog.roi_x.setValue(45)
        self.dialog.roi_y.setValue(30)
        self.dialog.roi_w.setValue(51)
        self.dialog.roi_h.setValue(46)
        self.dialog.run_grabcut()
        wait_idle(self.dialog)
        self.assertIsNotNone(self.dialog.segmentation)
        self.assertGreater(self.dialog.segmentation["pixels"], 1800)
        self.assertEqual(len(self.dialog.segmentation["regioes"]), 1)
        self.dialog.segment_stage.setCurrentText("Sementes")
        self.assertEqual(self.dialog.result.shape, image.shape)

    def test_grabcut_manual_brush_and_freehand_measurement(self):
        self.dialog.tabs.setCurrentIndex(2)
        self.dialog.begin_segmentation_brush()
        self.dialog.segment_brush.setCurrentIndex(0)
        self.dialog._stroke_point(20, 20)
        self.dialog._stroke_finished()
        self.assertEqual(self.dialog.corrections[20, 20], cv2.GC_FGD)
        self.dialog.segment_brush.setCurrentIndex(1)
        self.dialog._stroke_point(80, 60)
        self.assertEqual(self.dialog.corrections[60, 80], cv2.GC_BGD)
        self.dialog.clear_segmentation_corrections()
        self.assertTrue(np.all(self.dialog.corrections == -1))
        self.dialog.tabs.setCurrentIndex(3)
        self.dialog.measure_shape.setCurrentText("Desenho livre")
        for x, y in ((10, 10), (30, 10), (30, 30), (10, 30)):
            self.dialog._stroke_point(x, y)
        self.dialog._stroke_finished()
        self.dialog.undo_measure_point()
        self.assertEqual(len(self.dialog.measure_points), 3)
        self.dialog._drawing = True
        self.dialog._stroke_point(10, 30)
        self.dialog.add_measurement()
        self.assertEqual(self.dialog.measurements[-1]["pixels"], 400)

    def test_escape_discards_late_worker_callback(self):
        self.dialog.show()
        self.dialog._work(
            lambda: (time.sleep(0.08), self.image + 1)[1],
            lambda image: self.dialog._set_result(image, "late"),
            "Processando",
        )
        QTest.keyClick(self.dialog, Qt.Key.Key_Escape)
        self.assertTrue(self.dialog._closed)
        wait_idle(self.dialog)
        np.testing.assert_array_equal(self.dialog.result, self.image)

    def test_measurement_shapes_polygon_calibration_csv(self):
        self.dialog.canvas.selection = {
            "shape": "rect",
            "rect": (10, 10, 20, 30),
            "source_size": (140, 100),
        }
        self.dialog.add_measurement()
        self.assertEqual(self.dialog.measurements[0]["pixels"], 600)
        self.dialog.measure_shape.setCurrentText("Polígono")
        self.dialog.measure_points = [(50, 20), (60, 20), (60, 30), (50, 30)]
        self.dialog.add_measurement()
        self.assertEqual(self.dialog.measurements[1]["pixels"], 100)
        self.dialog.reference_distance.setValue(2)
        self.dialog.begin_calibration()
        self.dialog._point_clicked(0, 0)
        self.dialog._point_clicked(10, 0)
        self.assertAlmostEqual(self.dialog.scale, 0.2)
        path = self.folder / "areas.csv"
        self.dialog.export_measurements(str(path))
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter=";"))
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(float(rows[0]["Area_fisica_estimada"]), 24)

    def test_custom_morphology_kernel_json_and_invalid_values(self):
        self.dialog.kernel_table.setItem(1, 0, QTableWidgetItem("0"))
        self.dialog.kernel_table.setItem(1, 2, QTableWidgetItem("0"))
        self.dialog.morph_mode.setCurrentText("Binária")
        path = self.folder / "kernel.json"
        self.dialog.save_kernel(str(path))
        expected = json.loads(path.read_text(encoding="utf-8"))
        self.dialog.generate_kernel()
        self.dialog.load_kernel(str(path))
        self.assertEqual(
            self.dialog.kernel_config()["kernel"].tolist(), expected["kernel"]
        )
        self.dialog.run_morphology()
        wait_idle(self.dialog)
        self.assertEqual(self.dialog.result.ndim, 2)
        self.dialog.kernel_table.setItem(0, 0, QTableWidgetItem("9"))
        self.dialog.run_morphology()
        self.assertIn("apenas", self.dialog.message.text())


class FaceWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.default_patch = patch("studio.faces.PASTA_PADRAO", self.folder / "turma")
        self.demo_patch = patch(
            "studio.faces.DEMO_FOLDER", self.folder / "missing_demo"
        )
        self.default_patch.start()
        self.demo_patch.start()
        self.panel = FacePanel()
        wait_idle(self.panel)

    def tearDown(self):
        wait_idle(self.panel)
        self.panel.cleanup()
        self.panel.close()
        self.panel.deleteLater()
        APP.processEvents()
        self.demo_patch.stop()
        self.default_patch.stop()
        self.temp.cleanup()

    def test_empty_database_detects_without_model_error(self):
        blank = np.zeros((100, 140, 3), np.uint8)
        result = self.panel.process_frame(blank)
        np.testing.assert_array_equal(result, blank)
        self.assertIn("Detecção", self.panel.model_badge.text())
        self.assertIsNone(self.panel.motor.modelo)

    def test_real_lbph_training_persistence_threshold_reload(self):
        rng = np.random.default_rng(8)
        faces = [rng.integers(0, 256, (128, 128), np.uint8) for _ in range(2)]
        self.panel.bank.cadastrar("42", "Pessoa teste", faces)
        self.panel.train_model()
        wait_idle(self.panel)
        self.assertTrue(self.panel.motor.pronto)
        self.assertEqual(self.panel.motor.prever_face(faces[0]).codigo, "42")
        self.panel.threshold.setValue(43.25)
        self.panel.save_threshold()
        wait_idle(self.panel)
        reloaded = MotorFaces(BancoFaces(self.panel.bank.pasta))
        self.assertTrue(reloaded.preparar_modelo())
        self.assertAlmostEqual(reloaded.limiar, 43.25)
        self.assertIn("salvo", reloaded.status_modelo)

    def test_register_import_requires_distinct_photos_and_trains(self):
        rng = np.random.default_rng(9)
        paths = []
        for index in range(2):
            path = self.folder / f"p{index}.png"
            cv2.imwrite(str(path), rng.integers(0, 256, (140, 140, 3), np.uint8))
            paths.append(str(path))
        with patch.object(
            self.panel.motor, "detectar", return_value=[(0, 0, 140, 140)]
        ):
            with self.assertRaisesRegex(ValueError, "duas"):
                register_photos(
                    self.panel.bank,
                    self.panel.motor,
                    "A",
                    "Aluno",
                    [paths[0], paths[0]],
                )
            added, trained = register_photos(
                self.panel.bank, self.panel.motor, "A", "Aluno", paths
            )
        self.assertEqual(added, 2)
        self.assertTrue(trained)

    def test_attendance_is_deduplicated_persisted_and_exported(self):
        self.panel.start_attendance("Aula Qt")
        result = ResultadoFace("A", "Aluno", 12.5, (10, 10, 40, 40))
        with patch.object(
            self.panel.motor,
            "anotar",
            return_value=(np.zeros((60, 60, 3), np.uint8), [result]),
        ):
            self.panel.process_frame(np.zeros((60, 60, 3), np.uint8))
            self.panel.process_frame(np.zeros((60, 60, 3), np.uint8))
        APP.processEvents()
        self.assertEqual(len(self.panel.chamada.linhas()), 1)
        self.assertEqual(self.panel.attendance_table.rowCount(), 1)
        self.panel.export_attendance_csv(str(self.folder / "call.csv"))
        self.panel.export_attendance_json(str(self.folder / "call.json"))
        self.assertEqual(
            len(
                json.loads((self.folder / "call.json").read_text(encoding="utf-8"))[
                    "registros"
                ]
            ),
            1,
        )
        self.panel.end_attendance()
        self.assertFalse(self.panel.chamada.ativa)

    @unittest.skipUnless(
        (DEMO_FOLDER / "alunos.json").exists(),
        "A base pública não está instalada no CI.",
    )
    def test_existing_public_model_recognizes_heldout_photo(self):
        bank = BancoFaces(DEMO_FOLDER)
        motor = MotorFaces(bank)
        self.assertTrue(motor.preparar_modelo())
        path = DEMO_FOLDER / "teste" / "pessoa_02_09.png"
        image = cv2.imread(str(path))
        results = motor.reconhecer(image)
        self.assertTrue(any(result.reconhecido for result in results), path.name)


class VideoWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.path = self.folder / "source.avi"
        writer = cv2.VideoWriter(
            str(self.path), cv2.VideoWriter_fourcc(*"MJPG"), 12, (96, 64)
        )
        for index in range(12):
            frame = np.zeros((64, 96, 3), np.uint8)
            frame[:, :, 0] = index * 18
            cv2.rectangle(frame, (10 + index, 10), (40 + index, 40), (30, 200, 250), -1)
            writer.write(frame)
        writer.release()
        self.panel = VideoPanel(process_face=lambda frame: cv2.bitwise_not(frame))

    def tearDown(self):
        self.panel.pause()
        wait_idle(self.panel)
        self.panel.cleanup()
        QThreadPool.globalInstance().waitForDone()
        APP.processEvents()
        self.panel.close()
        self.temp.cleanup()

    def test_open_effect_frame_export_and_original_copy(self):
        self.panel.open_video(str(self.path))
        wait_idle(self.panel)
        frame = self.panel.get_frame()
        self.assertIsNotNone(frame)
        frame[:] = 255
        self.assertFalse(np.all(self.panel.get_frame() == 255))
        self.panel.effect.setCurrentText("Canny")
        wait_idle(self.panel)
        result = self.panel.get_processed_frame()
        self.assertTrue(np.array_equal(result[:, :, 0], result[:, :, 1]))
        path = self.folder / "frame.png"
        self.panel.export_frame(str(path))
        wait_idle(self.panel)
        np.testing.assert_array_equal(cv2.imread(str(path)), result)

    def test_play_pause_rewind_and_real_video_export(self):
        self.panel.open_video(str(self.path))
        wait_idle(self.panel)
        self.panel.play()
        wait_for(lambda: self.panel.source.posicao >= 3)
        self.panel.pause()
        wait_idle(self.panel)
        self.panel.stop()
        wait_idle(self.panel)
        self.assertEqual(self.panel.source.posicao, 1)
        self.panel.effect.setCurrentText("Reconhecimento facial")
        wait_idle(self.panel)
        np.testing.assert_array_equal(
            self.panel.get_processed_frame(), cv2.bitwise_not(self.panel.get_frame())
        )
        output = self.folder / "result.avi"
        self.panel.export_video(str(output))
        wait_idle(self.panel)
        capture = cv2.VideoCapture(str(output))
        self.assertEqual(int(capture.get(cv2.CAP_PROP_FRAME_COUNT)), 12)
        self.assertEqual(int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), 96)
        capture.release()

    def test_invalid_file_reports_error_without_crashing(self):
        self.panel.open_video(str(self.folder / "invalid.mp4"))
        wait_idle(self.panel)
        self.assertIsNone(self.panel.source)
        self.assertIn("não existe", self.panel.info.text())

    def test_effect_changed_during_paused_read_uses_latest_choice(self):
        self.panel.open_video(str(self.path))
        wait_idle(self.panel)
        original_read = self.panel.source.ler
        started = threading.Event()

        def slow_read():
            started.set()
            time.sleep(0.08)
            return original_read()

        with patch.object(self.panel.source, "ler", side_effect=slow_read):
            self.panel._next_frame()
            wait_for(started.is_set)
            self.assertTrue(self.panel._reading)
            self.panel.effect.setCurrentText("Canny")
            wait_idle(self.panel)
        expected = cv2.cvtColor(
            cv2.Canny(
                cv2.cvtColor(self.panel.get_frame(), cv2.COLOR_BGR2GRAY), 80, 160
            ),
            cv2.COLOR_GRAY2BGR,
        )
        np.testing.assert_array_equal(self.panel.get_processed_frame(), expected)


if __name__ == "__main__":
    unittest.main()
