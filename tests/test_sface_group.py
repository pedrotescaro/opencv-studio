"""Synthetic SFace lifecycle tests; embedding inference is mocked, no network."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from studio.services.faces import ErroFaces, ler_imagem
from studio.services import sface_group as service


class SyntheticEngine:
    def __init__(self, folder=None):
        pass

    def detect(self, image):
        return image, [np.array([0, 0, 128, 128], np.float32)], 1.0

    def descriptor(self, image, face):
        feature = np.zeros(128, np.float32)
        marker = int(image[0, 0, 0])
        if marker == 250:
            feature[:2] = np.sqrt(0.5)
        else:
            feature[marker // 50 - 1] = 1
        return feature, image.copy()


class SFaceGroupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.photos, self.data = self.root / "photos", self.root / "model"
        self.photos.mkdir()
        self.members = [{"id": code, "nome": f"Integrante {code}", "pasta": code} for code in "ABC"]
        (self.photos / "integrantes.json").write_text(
            json.dumps({"versao": 1, "integrantes": self.members}), encoding="utf-8"
        )
        rng = np.random.default_rng(411)
        for index, person in enumerate(self.members):
            (self.photos / person["pasta"]).mkdir()
            for photo in range(2):
                image = rng.integers(0, 256, (128, 128, 3), np.uint8)
                image[0, 0, 0] = (index + 1) * 50
                cv2.imwrite(str(self.photos / person["pasta"] / f"{photo}.png"), image)
        self.engine = patch.object(service, "_SFaceEngine", SyntheticEngine)
        self.models = patch.object(service, "preparar_modelos", return_value=self.root)
        self.engine.start()
        self.models_mock = self.models.start()

    def tearDown(self):
        self.engine.stop()
        self.models.stop()
        self.temp.cleanup()

    def train(self):
        return service.treinar_grupo(self.photos, self.data)

    def snapshot(self):
        return {path.relative_to(self.data).as_posix(): path.read_bytes()
                for path in self.data.rglob("*") if path.is_file()}

    def test_train_reload_and_recognize_whitelist(self):
        result = self.train()
        self.assertEqual((result.total_pessoas, result.total_fotos), (3, 6))
        self.assertAlmostEqual(result.motor.limiar, .637)
        loaded = service.carregar_grupo_treinado(self.photos, self.data)
        self.assertTrue(loaded.motor.pronto)
        for code in "ABC":
            image = ler_imagem(self.photos / code / "0.png")
            prediction = loaded.motor.reconhecer(image)[0]
            self.assertEqual(prediction.codigo, code)
            self.assertAlmostEqual(prediction.distancia, 0)
        loaded.motor.definir_limiar(.5)
        self.assertAlmostEqual(service.carregar_grupo_treinado(self.photos, self.data).motor.limiar, .5)

    def test_reject_unknown_and_ambiguous_identity(self):
        motor = self.train().motor
        image = ler_imagem(self.photos / "A" / "0.png")
        for marker in (200, 250):
            with self.subTest(marker=marker):
                image[0, 0, 0] = marker
                result = motor.reconhecer(image)[0]
                self.assertIsNone(result.codigo)
                self.assertEqual(result.nome, "Desconhecido")

    def test_invalid_thresholds_are_rejected_without_change(self):
        motor = self.train().motor
        for value in (0, 1.01, float("nan"), "invalid"):
            with self.assertRaises(ErroFaces):
                motor.definir_limiar(value)
        self.assertAlmostEqual(motor.limiar, .637)

    def test_missing_photos_does_not_download_or_create_model(self):
        (self.photos / "B" / "1.png").unlink()
        with self.assertRaisesRegex(ErroFaces, "Integrante B"):
            self.train()
        self.models_mock.assert_not_called()
        self.assertFalse(self.data.exists())

    def test_duplicate_photos_and_invalid_face_preserve_previous_model(self):
        self.train()
        original = self.snapshot()
        with patch.object(SyntheticEngine, "detect", return_value=(None, [], 1)):
            with self.assertRaisesRegex(ErroFaces, "detectados 0 rostos"):
                self.train()
        self.assertEqual(self.snapshot(), original)
        (self.photos / "B" / "1.png").write_bytes((self.photos / "B" / "0.png").read_bytes())
        with self.assertRaisesRegex(ErroFaces, "duas fotos distintas"):
            self.train()
        self.assertEqual(self.snapshot(), original)

    def test_changed_sources_and_extra_identity_block_prediction(self):
        result = self.train()
        probe = ler_imagem(self.photos / "A" / "0.png")
        extra = self.photos / "A" / "copy.png"
        extra.write_bytes((self.photos / "A" / "0.png").read_bytes())
        with self.assertRaisesRegex(ErroFaces, "mudaram"):
            result.motor.reconhecer(probe)
        self.assertFalse(result.motor.pronto)
        extra.unlink()
        result.banco.cadastrar("D", "Outro", [probe, np.rot90(probe)])
        with self.assertRaisesRegex(ErroFaces, "três integrantes"):
            result.motor.reconhecer(probe)

    def test_corrupted_descriptors_cannot_load(self):
        self.train()
        (self.data / "descritores_sface.npz").write_bytes(b"corrupted")
        with self.assertRaisesRegex(ErroFaces, "Descritores SFace inválidos"):
            service.carregar_grupo_treinado(self.photos, self.data)

    def test_publish_failure_rolls_back_and_keeps_attendance(self):
        self.train()
        calls = self.data / "chamadas"
        calls.mkdir()
        (calls / "aula.json").write_text("preservar")
        original = self.snapshot()
        replace = Path.replace
        failed = False

        def fail_once(path, target):
            nonlocal failed
            if path.parent.name == "novo" and path.name == "sface.json" and not failed:
                failed = True
                raise OSError("publication failed")
            return replace(path, target)

        with patch.object(Path, "replace", fail_once):
            with self.assertRaisesRegex(ErroFaces, "publication failed"):
                self.train()
        self.assertTrue(failed)
        self.assertEqual(self.snapshot(), original)
        self.assertTrue(service.carregar_grupo_treinado(self.photos, self.data).motor.pronto)


class OfficialModelsTests(unittest.TestCase):
    def test_missing_models_never_download_without_explicit_training(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(service.urllib.request, "urlopen") as download:
            with self.assertRaisesRegex(ErroFaces, "Treinar"):
                service.preparar_modelos(folder)
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
