"""Behavioral equivalence and GUI-free imports for the extracted services.

Legacy baselines load only their original pure definitions, so these regression
tests also run on Python distributions where tkinter is not installed.
"""

import ast
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import uuid
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from studio.services import color, faces, geometry, segmentation, video


ROOT = Path(__file__).resolve().parents[1]


def legacy_baseline(filename, stop_class, dependencies=None):
    """Execute the unmodified algorithms without the legacy widget imports."""
    path = ROOT / filename
    source = ast.parse(path.read_text(encoding="utf-8-sig"))
    body = []
    for node in source.body:
        if isinstance(node, ast.ClassDef) and node.name == stop_class:
            break
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            body.append(node)
    module_name = "_baseline_" + path.stem
    module = types.ModuleType(module_name)
    sys.modules[module_name] = module
    module.__dict__.update(
        {
            "__file__": str(path),
            "cv2": cv2,
            "np": np,
            "Path": Path,
            "csv": csv,
            "hashlib": hashlib,
            "json": json,
            "math": math,
            "shutil": shutil,
            "tempfile": tempfile,
            "threading": threading,
            "uuid": uuid,
            "dataclass": dataclass,
            "datetime": datetime,
            "Image": Image,
            "ImageDraw": ImageDraw,
            "ImageFont": ImageFont,
        }
    )
    if dependencies:
        module.__dict__.update(dependencies)
    exec(
        compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"),
        module.__dict__,
    )
    return module


OLD_COLOR = legacy_baseline("editor_laboratorio.py", "JanelaLaboratorio")
OLD_FACES = legacy_baseline("editor_faces.py", "JanelaFaces")
OLD_VIDEO = legacy_baseline("editor_video.py", "JanelaVideo")
OLD_CROP = legacy_baseline("editor_recorte.py", "JanelaRecorte")
OLD_GEOMETRY = legacy_baseline(
    "editor_medicao.py",
    "JanelaMedicao",
    {
        name: getattr(OLD_CROP, name)
        for name in ("FORMAS_RECORTE", "limites_recorte", "mascara_recorte")
    },
)
OLD_SEGMENTATION = legacy_baseline("editor_segmentacao.py", "JanelaSegmentacao")


class ExtractedServicesTests(unittest.TestCase):
    def setUp(self):
        self.image = np.random.default_rng(81).integers(
            0, 256, (48, 64, 3), dtype=np.uint8
        )

    def test_services_import_without_tk_or_any_legacy_application_module(self):
        code = r"""
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name in ("tkinter", "_tkinter", "PIL.ImageTk") or name.startswith(("tkinter.", "editor_")):
        raise AssertionError("Forbidden GUI/legacy import: " + name)
    if name == "PIL" and "ImageTk" in (args[2] if len(args)>2 else kwargs.get("fromlist", ())):
        raise AssertionError("ImageTk is not a pure service dependency")
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from studio.services import color, faces, geometry, segmentation, video
from studio import filters
assert faces.MotorFaces.NORMALIZACAO == "cinza-128x128-equalizeHist-v1"
assert geometry.FORMAS_RECORTE
print("GUI-free services imported")
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GUI-free services imported", result.stdout)

    def test_face_default_storage_keeps_the_existing_repository_directory(self):
        self.assertEqual(faces.PASTA_PADRAO, ROOT / ".dados_faces")
        self.assertEqual(faces.PASTA_PADRAO, OLD_FACES.PASTA_PADRAO)

    def test_complete_qt_window_runs_with_tk_and_legacy_imports_forbidden(self):
        code = r"""
import builtins, os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name in ("tkinter", "_tkinter", "PIL.ImageTk") or name.startswith(("tkinter.", "editor_")):
        raise AssertionError("Forbidden GUI/legacy import: " + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from studio.ui.window import MainWindow
app = QApplication([])
window = MainWindow()
window.open_array(np.full((32, 48, 4), 200, np.uint8))
window.show()
def finish():
    assert window.result is not None
    assert window.result.shape == (32, 48, 4)
    window.modified = False
    window.reset_draft(render=False)
    window.close()
    app.quit()
QTimer.singleShot(1500, finish)
app.exec()
print("Complete Qt application rendered without Tk")
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=25,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Complete Qt application rendered without Tk", result.stdout)

    def test_color_models_histograms_quantization_and_region_equivalence(self):
        for destination in color.MODELOS:
            with self.subTest(destination=destination):
                expected = OLD_COLOR.converter_cor(self.image, "BGR", destination)
                actual = color.converter_cor(self.image, "BGR", destination)
                np.testing.assert_array_equal(actual, expected)
                np.testing.assert_array_equal(
                    color.converter_cor(actual, destination, "BGR"),
                    OLD_COLOR.converter_cor(expected, destination, "BGR"),
                )
        for space in ("RGB", "HSV", "Cinza"):
            for name, values in color.histogramas(self.image, espaco=space).items():
                np.testing.assert_array_equal(
                    values, OLD_COLOR.histogramas(self.image, espaco=space)[name]
                )
        for levels in (2, 8, 64, 256):
            np.testing.assert_array_equal(
                color.quantizar(self.image, levels),
                OLD_COLOR.quantizar(self.image, levels),
            )
        for dimensions in ((20, 12), (120, 90)):
            np.testing.assert_array_equal(
                color.redimensionar(self.image, *dimensions),
                OLD_COLOR.redimensionar(self.image, *dimensions),
            )
        for connectivity in (4, 8):
            np.testing.assert_array_equal(
                color.crescer_regiao(self.image, (20, 15), 40, connectivity),
                OLD_COLOR.crescer_regiao(self.image, (20, 15), 40, connectivity),
            )

    def test_crop_and_measurement_equivalence_for_all_shapes(self):
        self.assertEqual(geometry.FORMAS_RECORTE, OLD_CROP.FORMAS_RECORTE)
        for shape in geometry.FORMAS_RECORTE:
            with self.subTest(shape=shape):
                expected, count = OLD_CROP.recortar_imagem(
                    self.image, (58, 40), (8, 6), shape
                )
                actual, actual_count = geometry.recortar_imagem(
                    self.image, (58, 40), (8, 6), shape
                )
                np.testing.assert_array_equal(actual, expected)
                self.assertEqual(actual_count, count)
                self.assertEqual(
                    geometry.medir_regiao(self.image.shape, shape, (8, 6), (58, 40)),
                    OLD_GEOMETRY.medir_regiao(
                        self.image.shape, shape, (8, 6), (58, 40)
                    ),
                )
        points = [(4, 4), (50, 8), (45, 39), (12, 43)]
        for shape in ("Polígono", "Desenho livre"):
            self.assertEqual(
                geometry.medir_regiao(self.image.shape, shape, pontos=points),
                OLD_GEOMETRY.medir_regiao(self.image.shape, shape, pontos=points),
            )
        scale = geometry.calcular_escala([(0, 0), (30, 40)], "12,5")
        self.assertEqual(
            scale, OLD_GEOMETRY.calcular_escala([(0, 0), (30, 40)], "12,5")
        )
        self.assertEqual(
            geometry.area_calibrada(1250, scale),
            OLD_GEOMETRY.area_calibrada(1250, scale),
        )

    def test_seed_generation_grabcut_and_components_equivalence(self):
        image = np.full((80, 100, 3), (20, 30, 35), np.uint8)
        truth = np.zeros((80, 100), np.uint8)
        cv2.circle(truth, (50, 40), 20, 255, -1)
        image[truth != 0] = (30, 80, 220)
        roi = cv2.dilate(truth, np.ones((5, 5), np.uint8))
        corrections = np.full(truth.shape, -1, np.int8)
        corrections[40, 50] = cv2.GC_FGD
        np.testing.assert_array_equal(
            segmentation.criar_sementes(roi, 3, 1, 1, corrections),
            OLD_SEGMENTATION.criar_sementes(roi, 3, 1, 1, corrections),
        )
        options = {
            "kernel": 3,
            "erosao": 1,
            "dilatacao": 1,
            "iteracoes": 2,
            "area_minima": 10,
        }
        cv2.setRNGSeed(123)
        expected = OLD_SEGMENTATION.segmentar_imagem(image, roi, options, corrections)
        cv2.setRNGSeed(123)
        actual = segmentation.segmentar_imagem(image, roi, options, corrections)
        for key in (
            "suavizada",
            "sementes",
            "rotulos",
            "binaria",
            "fechada",
            "mascara",
            "sobreposicao",
        ):
            np.testing.assert_array_equal(actual[key], expected[key])
        self.assertEqual(actual["pixels"], expected["pixels"])
        self.assertEqual(actual["removidos"], expected["removidos"])
        self.assertEqual(actual["parametros"], expected["parametros"])

    def test_persisted_lbph_model_is_interchangeable_with_legacy_service(self):
        with tempfile.TemporaryDirectory() as folder:
            bank = OLD_FACES.BancoFaces(folder)
            samples = [
                np.random.default_rng(seed).integers(0, 256, (128, 128), dtype=np.uint8)
                for seed in (10, 11, 50, 51)
            ]
            bank.cadastrar("A1", "Ana", samples[:2])
            bank.cadastrar("B2", "Bruno", samples[2:])
            old_motor = OLD_FACES.MotorFaces(bank)
            self.assertEqual(old_motor.treinar(), (4, 2))
            saved_model = (Path(folder) / "modelo_lbph.yml").read_bytes()
            manifest = json.loads(
                (Path(folder) / "modelo_lbph.json").read_text(encoding="utf-8")
            )
            new_bank = faces.BancoFaces(folder)
            motor = faces.MotorFaces(new_bank)
            self.assertTrue(motor.preparar_modelo())
            self.assertEqual(
                (Path(folder) / "modelo_lbph.yml").read_bytes(), saved_model
            )
            self.assertEqual(manifest["versao"], 1)
            self.assertEqual(manifest["normalizacao"], faces.MotorFaces.NORMALIZACAO)
            self.assertEqual(motor.rotulos, old_motor.rotulos)
            for sample in samples:
                np.testing.assert_array_equal(
                    faces.normalizar_face(sample), OLD_FACES.normalizar_face(sample)
                )
                actual, expected = (
                    motor.prever_face(sample),
                    old_motor.prever_face(sample),
                )
                self.assertEqual(
                    (actual.codigo, actual.nome), (expected.codigo, expected.nome)
                )
                self.assertAlmostEqual(actual.distancia, expected.distancia, places=10)
            motor.definir_limiar(42.5)
            self.assertEqual(OLD_FACES.MotorFaces(bank).limiar, 42.5)

    def test_attendance_schema_deduplication_and_csv_are_compatible(self):
        with tempfile.TemporaryDirectory() as folder:
            expected = OLD_FACES.Chamada("Aula", Path(folder) / "old")
            actual = faces.Chamada("Aula", Path(folder) / "new")
            for call in (expected, actual):
                self.assertTrue(
                    call.registrar(faces.ResultadoFace("A1", "Ana", 20.125))
                )
                self.assertFalse(
                    call.registrar(faces.ResultadoFace("A1", "Ana", 20.125))
                )
                self.assertFalse(
                    call.registrar(faces.ResultadoFace(None, "Desconhecido", 90))
                )
                call.encerrar()
                self.assertFalse(call.registrar(faces.ResultadoFace("B2", "Bruno", 10)))
            new_payload = json.loads(actual.caminho.read_text(encoding="utf-8"))
            old_payload = json.loads(expected.caminho.read_text(encoding="utf-8"))
            self.assertEqual(set(new_payload), set(old_payload))
            self.assertEqual(new_payload["versao"], 1)
            self.assertEqual(
                set(new_payload["registros"][0]), set(old_payload["registros"][0])
            )
            destination = Path(folder) / "presenças.csv"
            actual.exportar_csv(destination)
            with destination.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream, delimiter=";"))
            self.assertEqual(rows[0]["id_aluno"], "A1")

    def test_video_effects_and_unicode_codec_roundtrip_match_legacy(self):
        for effect in video.EFEITOS_VIDEO:
            with self.subTest(effect=effect):
                np.testing.assert_array_equal(
                    video.aplicar_efeito(self.image, effect),
                    OLD_VIDEO.aplicar_efeito(self.image, effect),
                )
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "origem_á.avi"
            writer = cv2.VideoWriter(
                str(source), cv2.VideoWriter_fourcc(*"MJPG"), 12.5, (64, 48)
            )
            self.assertTrue(
                writer.isOpened(), "MJPG is required for this actual codec test"
            )
            try:
                for index in range(4):
                    writer.write(np.roll(self.image, index * 2, axis=1))
            finally:
                writer.release()
            old_target, new_target = (
                Path(folder) / "old.avi",
                Path(folder) / "novo_ç.avi",
            )
            old_result = OLD_VIDEO.exportar_arquivo_video(
                source, old_target, "Inversão de cores"
            )
            result = video.exportar_arquivo_video(
                source, new_target, "Inversão de cores"
            )
            for key in ("frames", "fps", "largura", "altura"):
                self.assertEqual(result[key], old_result[key])
            with (
                video.FonteVideo(new_target) as new,
                OLD_VIDEO.FonteVideo(old_target) as old,
            ):
                for _ in range(4):
                    new_ok, new_frame = new.ler()
                    old_ok, old_frame = old.ler()
                    self.assertTrue(new_ok and old_ok)
                    np.testing.assert_array_equal(new_frame, old_frame)
            cancel = threading.Event()
            cancel.set()
            previous = new_target.read_bytes()
            with self.assertRaises(video.ExportacaoCancelada):
                video.exportar_arquivo_video(source, new_target, cancelar=cancel)
            self.assertEqual(new_target.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
