"""Group data lifecycle using synthetic images, mock detection and real LBPH.

These tests verify persistence and gating, not accuracy on real people.
"""

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from studio.services.faces import ErroFaces, MotorFaces, ler_imagem
from studio.services import group_faces as group


class GroupFacesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.photos = self.root / "fotos"
        self.data = self.root / "modelo"
        self.photos.mkdir()
        self.members = [
            {"id": "A", "nome": "Integrante A", "pasta": "pessoa_a"},
            {"id": "B", "nome": "Integrante B", "pasta": "pessoa_b"},
            {"id": "C", "nome": "Integrante C", "pasta": "pessoa_c"},
        ]
        self.write_config()
        self.rng = np.random.default_rng(614)
        for member in self.members:
            (self.photos / member["pasta"]).mkdir()
            for index in range(2):
                self.write_photo(member, f"{index}.png")
        self.detector_patch = patch.object(
            MotorFaces, "detectar", return_value=[(0, 0, 128, 128)]
        )
        self.detector_patch.start()

    def tearDown(self):
        self.detector_patch.stop()
        self.temporary.cleanup()

    def write_config(self):
        (self.photos / "integrantes.json").write_text(
            json.dumps({"versao": 1, "integrantes": self.members}), encoding="utf-8"
        )

    def write_photo(self, member, name):
        path = self.photos / member["pasta"] / name
        image = self.rng.integers(0, 256, (128, 128, 3), dtype=np.uint8)
        self.assertTrue(cv2.imwrite(str(path), image))
        return path

    def train(self):
        return group.treinar_grupo(self.photos, self.data)

    def snapshot(self):
        return {
            path.relative_to(self.data).as_posix(): path.read_bytes()
            for path in self.data.rglob("*") if path.is_file()
        }

    def test_real_lbph_training_reload_and_only_three_identities(self):
        result = self.train()
        self.assertEqual((result.total_pessoas, result.total_fotos), (3, 6))
        self.assertTrue(result.motor.pronto)
        reloaded = group.carregar_grupo_treinado(self.photos, self.data)
        self.assertEqual(set(reloaded.banco.alunos), {"A", "B", "C"})
        self.assertTrue(group.verificar_fontes_grupo(self.photos, self.data))
        for member in self.members:
            image = ler_imagem(self.photos / member["pasta"] / "0.png")
            self.assertEqual(reloaded.motor.prever_face(image).codigo, member["id"])

    def test_inventory_ignores_unlisted_people_and_non_image_files(self):
        extra = self.photos / "outra_pessoa"
        extra.mkdir()
        (extra / "foto.png").write_bytes(b"not a supported training input")
        (self.photos / "pessoa_a" / "README.md").write_text("Instructions")
        inventory = group.inventariar_fotos(self.photos)
        self.assertEqual(inventory.total_fotos, 6)
        self.assertEqual(set(inventory.fotos), {"A", "B", "C"})
        self.assertEqual(self.train().total_pessoas, 3)

    def test_config_rejects_four_people_duplicate_ids_and_path_escape(self):
        original = list(self.members)
        for members in (
            original + [{"id": "D", "nome": "D", "pasta": "d"}],
            [original[0], original[0], original[2]],
            [dict(original[0], pasta="../escape"), *original[1:]],
        ):
            with self.subTest(members=members):
                self.members = members
                self.write_config()
                with self.assertRaises(ErroFaces):
                    group.carregar_integrantes(self.photos)

    def test_missing_photos_give_named_error_and_no_model(self):
        for path in (self.photos / "pessoa_b").glob("*.png"):
            path.unlink()
        self.assertEqual(len(group.inventariar_fotos(self.photos).fotos["B"]), 0)
        with self.assertRaisesRegex(ErroFaces, "Faltam fotos de: Integrante B"):
            self.train()
        self.assertFalse(self.data.exists())

    def test_duplicate_face_cannot_satisfy_two_distinct_photos(self):
        folder = self.photos / "pessoa_b"
        (folder / "1.png").write_bytes((folder / "0.png").read_bytes())
        with self.assertRaisesRegex(ErroFaces, "Integrante B.*duas fotos diferentes"):
            self.train()

    def test_multiple_faces_rejected_without_replacing_previous_model(self):
        self.train()
        previous = self.snapshot()
        with patch.object(MotorFaces, "detectar", return_value=[(0, 0, 64, 64)] * 2):
            with self.assertRaisesRegex(ErroFaces, "detectados 2 rostos"):
                self.train()
        self.assertEqual(self.snapshot(), previous)

    def test_added_removed_and_replaced_photos_invalidate_active_model(self):
        for mutation in ("add", "remove", "replace"):
            with self.subTest(mutation=mutation):
                result = self.train()
                probe = ler_imagem(self.photos / "pessoa_a" / "0.png")
                if mutation == "add":
                    path = self.write_photo(self.members[0], "extra.png")
                elif mutation == "remove":
                    (self.photos / "pessoa_a" / "extra.png").unlink()
                else:
                    self.write_photo(self.members[0], "0.png")
                with self.assertRaisesRegex(ErroFaces, "mudaram"):
                    group.verificar_fontes_grupo(self.photos, self.data)
                self.assertFalse(result.motor.pronto)
                with self.assertRaises(ErroFaces):
                    result.motor.prever_face(probe)
                self.assertFalse(result.motor.preparar_modelo())

    def test_retraining_replaces_samples_and_keeps_attendance(self):
        result = self.train()
        old_files = set((self.data / "amostras").iterdir())
        attendance = self.data / "chamadas" / "aula.json"
        attendance.parent.mkdir()
        attendance.write_text('{"aula": "preservada"}', encoding="utf-8")
        self.write_photo(self.members[0], "nova.png")
        retrained = self.train()
        self.assertEqual(retrained.total_fotos, 7)
        self.assertFalse(old_files.intersection((self.data / "amostras").iterdir()))
        self.assertEqual(json.loads(attendance.read_text()), {"aula": "preservada"})
        self.assertNotEqual(result.assinatura, retrained.assinatura)

    def test_injected_publish_failure_restores_every_previous_file(self):
        self.train()
        before = self.snapshot()
        original_replace = Path.replace
        failed = False

        def fail_once(path, target):
            nonlocal failed
            if path.parent.name == "novo" and path.name == "modelo_lbph.json" and not failed:
                failed = True
                raise OSError("simulated publication failure")
            return original_replace(path, target)

        with patch.object(Path, "replace", fail_once):
            with self.assertRaisesRegex(ErroFaces, "simulated publication failure"):
                self.train()
        self.assertTrue(failed)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(group.carregar_grupo_treinado(self.photos, self.data).motor.pronto)

    def test_external_extra_identity_blocks_recognition_and_retraining(self):
        result = self.train()
        result.banco.cadastrar(
            "D", "Pessoa não permitida",
            [self.rng.integers(0, 256, (128, 128), np.uint8) for _ in range(2)],
        )
        self.assertFalse(result.motor.preparar_modelo())
        with self.assertRaisesRegex(ErroFaces, "três integrantes"):
            result.motor.treinar()
        with self.assertRaisesRegex(ErroFaces, "três integrantes"):
            group.carregar_grupo_treinado(self.photos, self.data)

    def test_all_prediction_entry_points_lock_group_before_motor(self):
        result = self.train()
        motor = result.motor
        real_group_lock = group._LOCK
        active = threading.local()
        case = self

        class LockOrderGuard:
            def __enter__(self):
                if not getattr(active, "depth", 0):
                    case.assertFalse(motor.lock._is_owned(), "motor lock taken before group lock")
                    case.assertFalse(motor.banco.lock._is_owned(), "bank lock taken before group lock")
                real_group_lock.acquire()
                active.depth = getattr(active, "depth", 0) + 1

            def __exit__(self, *args):
                active.depth -= 1
                real_group_lock.release()

        image = ler_imagem(self.photos / "pessoa_a" / "0.png")
        with patch.object(group, "_LOCK", LockOrderGuard()):
            self.assertTrue(motor.pronto)
            self.assertEqual(motor.prever_face(image).codigo, "A")
            self.assertEqual(motor.reconhecer(image)[0].codigo, "A")
            self.assertTrue(motor.preparar_modelo())
            self.assertEqual(motor.treinar(), (6, 3))


if __name__ == "__main__":
    unittest.main()
