"""Qt group controls and attendance routing with explicit controlled identities.

No personal images or physical cameras are read. Model results are supplied by
the test; training accuracy is covered separately by the service evaluation.
"""

import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from studio.group_faces import GroupFacePanel
from studio.services.faces import BancoFaces, ErroFaces, ResultadoFace
from studio.ui.window import MainWindow


APP = QApplication.instance() or QApplication([])
MEMBERS = [
    {"id": "PEDRO", "nome": "Pedro Antônio Silvestre Tescaro", "pasta": "pedro"},
    {"id": "GUILHERME", "nome": "Guilherme Alves de Campos", "pasta": "guilherme"},
    {"id": "PAULO", "nome": "Paulo Henrique Leal dos Santos", "pasta": "paulo"},
]


def wait_idle(panel, seconds=5):
    deadline = time.monotonic() + seconds
    while panel._jobs and time.monotonic() < deadline:
        APP.processEvents()
        QTest.qWait(5)
    APP.processEvents()
    if panel._jobs:
        raise AssertionError("A operação do grupo não terminou dentro do prazo.")


class GroupWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.photos = self.folder / "fotos"
        self.data = self.folder / "modelo"
        self.photos.mkdir()
        (self.photos / "integrantes.json").write_text(
            json.dumps({"versao": 1, "integrantes": MEMBERS}, ensure_ascii=False),
            encoding="utf-8",
        )
        for member in MEMBERS:
            (self.photos / member["pasta"]).mkdir()
        self.startup = patch(
            "studio.group_faces.carregar_grupo_treinado",
            side_effect=ErroFaces("O grupo ainda não foi treinado."),
        )
        self.startup.start()
        self.panel = GroupFacePanel(group_folder=self.photos, data_folder=self.data)
        wait_idle(self.panel)

    def tearDown(self):
        wait_idle(self.panel)
        self.panel.cleanup()
        self.panel.close()
        QThreadPool.globalInstance().waitForDone(5000)
        APP.processEvents()
        self.startup.stop()
        self.temp.cleanup()

    def prepare_model(self):
        bank = BancoFaces(self.data)
        bank.alunos = {m["id"]: {"nome": m["nome"], "amostras": []} for m in MEMBERS}
        motor = SimpleNamespace(
            lock=threading.RLock(),
            modelo=object(),
            pronto=True,
            limiar=60.0,
            status_modelo="Modelo controlado para teste de interface",
            anotar=Mock(side_effect=lambda image: (image.copy(), [])),
        )
        result = SimpleNamespace(
            banco=bank, motor=motor, total_pessoas=3, total_fotos=6
        )
        with patch("studio.group_faces.treinar_grupo", return_value=result) as train:
            self.panel.save_capture_button.click()
            wait_idle(self.panel)
            train.assert_called_once_with(self.photos, self.data)
        self.assertTrue(self.panel._group_ready)
        return motor

    def start_call(self):
        with patch("studio.group_faces.verificar_fontes_grupo", return_value=True):
            self.panel.start_attendance("Chamada controlada")
        self.assertIsNotNone(self.panel.chamada)

    def test_roster_contains_only_three_members_and_no_demo(self):
        self.assertEqual(self.panel.database.count(), 1)
        self.assertFalse(self.panel.database.isEnabled())
        self.assertEqual(self.panel.member_choice.count(), 3)
        self.assertEqual(self.panel.roster.rowCount(), 3)
        self.assertEqual(
            [self.panel.member_choice.itemText(i) for i in range(3)],
            [m["nome"] for m in MEMBERS],
        )
        self.assertEqual(
            [self.panel.roster.item(i, 2).text() for i in range(3)], ["0"] * 3
        )
        self.assertTrue(self.panel.demo_button.isHidden())
        self.assertTrue(self.panel.identifier.isHidden())
        self.assertTrue(self.panel.remove_button.isHidden())
        self.assertIn("não treinado", self.panel.model_badge.text())

    def test_untrained_group_cannot_start_attendance(self):
        signals = []
        self.panel.liveCameraRequested.connect(lambda: signals.append(True))
        with patch(
            "studio.group_faces.verificar_fontes_grupo",
            side_effect=ErroFaces("Treine as fotos do grupo primeiro."),
        ):
            self.panel.start_attendance("Sem modelo")
        self.assertIsNone(self.panel.chamada)
        self.assertFalse(signals)
        self.assertIn("Treine", self.panel.message.text())

    def test_valid_call_emits_camera_signal_once_and_rejects_parallel_session(self):
        self.prepare_model()
        signals = []
        self.panel.liveCameraRequested.connect(lambda: signals.append(True))
        self.start_call()
        first = self.panel.chamada
        with patch("studio.group_faces.verificar_fontes_grupo", return_value=True):
            self.panel.start_attendance("Outra sessão")
        self.assertIs(self.panel.chamada, first)
        self.assertEqual(signals, [True])
        self.assertIn("Já há", self.panel.message.text())

    def test_live_results_are_deduplicated_and_exported(self):
        motor = self.prepare_model()
        self.start_call()
        frame = np.zeros((100, 120, 3), np.uint8)
        result = ResultadoFace("PEDRO", MEMBERS[0]["nome"], 21.0, (5, 5, 40, 40))
        unknown = ResultadoFace(None, "Desconhecido", 100.0, (50, 5, 40, 40))
        motor.anotar.side_effect = None
        motor.anotar.return_value = (frame.copy(), [result, unknown])
        with patch("studio.group_faces.verificar_fontes_grupo", return_value=True):
            self.panel.process_frame(frame)
            self.panel.process_frame(frame)
        APP.processEvents()
        self.assertEqual(len(self.panel.chamada.linhas()), 1)
        self.assertEqual(self.panel.attendance_table.rowCount(), 1)
        self.panel.export_attendance_json(str(self.folder / "chamada.json"))
        self.panel.export_attendance_csv(str(self.folder / "chamada.csv"))
        exported = json.loads((self.folder / "chamada.json").read_text(encoding="utf-8"))
        self.assertEqual(len(exported["registros"]), 1)
        self.assertIn("PEDRO", (self.folder / "chamada.csv").read_text(encoding="utf-8-sig"))

    def test_analyzing_photo_never_records_attendance(self):
        motor = self.prepare_model()
        self.start_call()
        frame = np.zeros((100, 120, 3), np.uint8)
        result = ResultadoFace("PEDRO", MEMBERS[0]["nome"], 21.0, (5, 5, 40, 40))
        motor.anotar.side_effect = None
        motor.anotar.return_value = (frame.copy(), [result])
        with patch("studio.group_faces.verificar_fontes_grupo", return_value=True):
            original, annotated = self.panel._analyze(frame)
        APP.processEvents()
        self.assertEqual(self.panel.chamada.linhas(), [])
        self.assertEqual(self.panel.result_table.rowCount(), 1)
        np.testing.assert_array_equal(original, frame)
        np.testing.assert_array_equal(annotated, frame)

    def test_changed_sources_block_recognition_before_callback(self):
        motor = self.prepare_model()
        with patch(
            "studio.group_faces.verificar_fontes_grupo",
            side_effect=ErroFaces("As fotos mudaram. Treine novamente."),
        ):
            with self.assertRaisesRegex(ErroFaces, "fotos mudaram"):
                self.panel.process_frame(np.zeros((100, 120, 3), np.uint8))
        motor.anotar.assert_not_called()

    def test_folder_button_opens_selected_members_directory(self):
        self.panel.member_choice.setCurrentIndex(2)
        with patch("studio.group_faces.QDesktopServices.openUrl", return_value=True) as open_url:
            self.panel.import_button.click()
        self.assertEqual(
            Path(open_url.call_args.args[0].toLocalFile()),
            (self.photos / "paulo").resolve(),
        )

    def test_camera_can_open_before_training_for_detection(self):
        signals = []
        self.panel.liveCameraRequested.connect(lambda: signals.append(True))
        self.panel.live_button.click()
        self.assertEqual(signals, [True])
        blank = np.zeros((100, 120, 3), np.uint8)
        np.testing.assert_array_equal(self.panel.process_frame(blank), blank)
        self.assertIsNone(self.panel.chamada)

    def test_main_window_routes_scanner_to_live_video_and_separates_photo_callback(self):
        with patch("studio.group_faces.GROUP_FOLDER", self.photos), patch(
            "studio.group_faces.GROUP_DATA_FOLDER", self.folder / "window_model"
        ):
            window = MainWindow()
        try:
            wait_idle(window.faces)
            with patch.object(window.video, "start_live_recognition") as start:
                window.faces.live_button.click()
            start.assert_called_once_with()
            self.assertEqual(window.stack.currentIndex(), 1)
            self.assertEqual(window.workspaces.currentIndex(), 1)
            frame = np.zeros((100, 120, 3), np.uint8)
            with patch.object(window.faces, "process_frame", return_value=frame) as process:
                window.video.process_face(frame)
                process.assert_called_once_with(frame, record_attendance=False)
            self.assertEqual(window.video.process_live_face.__self__, window.faces)
        finally:
            window.modified = False
            window.close()
            QThreadPool.globalInstance().waitForDone(5000)
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
