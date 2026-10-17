"""Roundtrips reais de codecs e ciclo de vida da aba de vídeo."""
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from editor_video import (EFEITOS_VIDEO, ExportacaoCancelada, FonteVideo, JanelaVideo,
                          aplicar_efeito, exportar_arquivo_video)


def criar_video(caminho, quantidade=9, fps=12.5):
    writer = cv2.VideoWriter(str(caminho), cv2.VideoWriter_fourcc(*"MJPG"), fps, (96, 64))
    if not writer.isOpened():
        raise RuntimeError("O codec MJPG não está disponível para o teste de roundtrip.")
    try:
        for indice in range(quantidade):
            frame = np.full((64, 96, 3), (20 + indice * 20, 40, 180 - indice * 15), np.uint8)
            cv2.rectangle(frame, (12 + indice, 15), (50 + indice, 45), (200, 180, 30), -1)
            writer.write(frame)
    finally:
        writer.release()


def ler_frames(caminho):
    with FonteVideo(str(caminho)) as fonte:
        fps = fonte.fps
        frames = []
        while True:
            ok, frame = fonte.ler()
            if not ok:
                return frames, fps
            frames.append(frame)


class ProcessamentoVideoTests(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory(prefix="teste_video_")
        self.addCleanup(self.pasta.cleanup)
        self.entrada = Path(self.pasta.name) / "entrada.avi"
        criar_video(self.entrada)

    def test_efeitos_preservam_entrada_canais_e_tamanho(self):
        frame = np.random.default_rng(42).integers(0, 256, (40, 60, 3), np.uint8)
        original = frame.copy()
        for efeito in EFEITOS_VIDEO:
            with self.subTest(efeito=efeito):
                resultado = aplicar_efeito(frame, efeito)
                self.assertEqual(resultado.shape, frame.shape)
                self.assertEqual(resultado.dtype, np.uint8)
                np.testing.assert_array_equal(frame, original)
        np.testing.assert_array_equal(aplicar_efeito(frame, "Inversão de cores"), 255 - frame)
        cinza = aplicar_efeito(frame, "Escala de cinza")
        np.testing.assert_array_equal(cinza[:, :, 0], cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        np.testing.assert_array_equal(cinza[:, :, 0], cinza[:, :, 2])
        canny = aplicar_efeito(frame, "Canny")
        self.assertTrue(set(np.unique(canny)) <= {0, 255})

    def test_callback_facial_recebe_copia_e_saida_e_validada(self):
        frame = np.full((40, 60, 3), 50, np.uint8)
        def facial(copia):
            copia[:] = 100
            return copia
        resultado = aplicar_efeito(frame, "Reconhecimento facial", facial)
        self.assertTrue(np.all(resultado == 100))
        self.assertTrue(np.all(frame == 50))
        for efeito, callback in (("desconhecido", None), ("Reconhecimento facial", None),
                                 ("Reconhecimento facial", lambda _: np.zeros((1, 1, 3), np.uint8))):
            with self.assertRaises(ValueError):
                aplicar_efeito(frame, efeito, callback)

    def test_fonte_preserva_primeiro_e_ultimo_frame_e_reinicia(self):
        with FonteVideo(str(self.entrada)) as fonte:
            self.assertEqual((fonte.largura, fonte.altura), (96, 64))
            self.assertAlmostEqual(fonte.fps, 12.5, places=2)
            frames = []
            while True:
                ok, frame = fonte.ler()
                if not ok:
                    break
                frames.append(frame)
            self.assertEqual(len(frames), 9)
            self.assertEqual(fonte.posicao, 9)
            self.assertGreater(float(frames[-1][:, :, 0].mean()), float(frames[0][:, :, 0].mean()) + 100)
            self.assertTrue(fonte.reiniciar())
            ok, primeiro = fonte.ler()
            self.assertTrue(ok)
            np.testing.assert_array_equal(primeiro, frames[0])
            capture = fonte.capture
        self.assertFalse(capture.isOpened())
        self.assertIsNone(fonte.capture)

    def test_exportacao_real_conserva_todos_os_frames_fps_e_dimensoes(self):
        # Diretório e arquivo Unicode também exercitam o destino temporário.
        pasta_unicode = Path(self.pasta.name) / "ação e visão"
        pasta_unicode.mkdir()
        origem = pasta_unicode / "vídeo original.avi"
        origem.write_bytes(self.entrada.read_bytes())
        original, fps = ler_frames(origem)
        for extensao in (".avi", ".mp4"):
            with self.subTest(extensao=extensao):
                destino = pasta_unicode / ("resultado ç" + extensao)
                progresso = []
                resultado = exportar_arquivo_video(origem, destino, "Inversão de cores",
                    progresso=lambda atual, total: progresso.append((atual, total)))
                frames, fps_saida = ler_frames(destino)
                self.assertEqual(resultado["frames"], 9)
                self.assertEqual(len(frames), len(original))
                self.assertEqual(frames[0].shape, original[0].shape)
                self.assertAlmostEqual(fps_saida, fps, places=2)
                self.assertEqual(progresso[-1][0], 9)
                # Codecs são com perdas: compare conteúdo no primeiro e último frame.
                for indice in (0, -1):
                    esperado = 255 - original[indice]
                    erro = np.abs(frames[indice].astype(float) - esperado.astype(float)).mean()
                    self.assertLess(erro, 8)
        self.assertEqual(origem.read_bytes(), self.entrada.read_bytes())

    def test_exportacao_cancelada_preserva_destino_e_libera_fonte(self):
        destino = Path(self.pasta.name) / "saida.avi"
        destino.write_bytes(b"destino anterior")
        cancelar = threading.Event()
        def progresso(atual, _total):
            if atual == 3:
                cancelar.set()
        with self.assertRaises(ExportacaoCancelada):
            exportar_arquivo_video(self.entrada, destino, cancelar=cancelar, progresso=progresso)
        self.assertEqual(destino.read_bytes(), b"destino anterior")
        # No Windows a substituição seria bloqueada se o Capture continuasse aberto.
        self.entrada.rename(self.entrada.with_name("renomeado.avi"))
        self.assertEqual(list(Path(self.pasta.name).glob(".opencv_*")), [])

    def test_exportacao_facial_erro_nao_substitui_destino(self):
        destino = Path(self.pasta.name) / "saida.avi"
        destino.write_bytes(b"preservar")
        def falhar(_frame):
            raise ValueError("Modelo não treinado.")
        with self.assertRaisesRegex(ValueError, "não treinado"):
            exportar_arquivo_video(self.entrada, destino, "Reconhecimento facial", falhar)
        self.assertEqual(destino.read_bytes(), b"preservar")

    def test_arquivo_invalido_camera_indisponivel_e_destino_original(self):
        invalido = Path(self.pasta.name) / "invalido.avi"
        invalido.write_bytes(b"nao e um video")
        with self.assertRaises(ValueError):
            FonteVideo(str(invalido))
        with self.assertRaises(ValueError):
            FonteVideo(str(invalido.with_name("ausente.avi")))
        with patch("editor_video.cv2.VideoCapture") as classe:
            captura = classe.return_value
            captura.isOpened.return_value = False
            with self.assertRaisesRegex(ValueError, "Câmera indisponível"):
                FonteVideo(99)
            captura.release.assert_called_once()
        with self.assertRaisesRegex(ValueError, "diferente"):
            exportar_arquivo_video(self.entrada, self.entrada)


class AbaVideoTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.erros_tk = []
        self.root.report_callback_exception = lambda *args: self.erros_tk.append(args)
        self.pasta = tempfile.TemporaryDirectory(prefix="teste_video_ui_")
        self.entrada = Path(self.pasta.name) / "entrada.avi"
        criar_video(self.entrada)
        self.video = JanelaVideo(self.root)
        self.erro = patch("editor_video.messagebox.showerror")
        self.mensagem = self.erro.start()

    def tearDown(self):
        self.video.destroy()
        self.root.update()
        self.root.destroy()
        self.erro.stop()
        self.pasta.cleanup()
        self.assertEqual(self.erros_tk, [])

    def aguardar(self, condicao, limite=5):
        final = time.monotonic() + limite
        while not condicao():
            if time.monotonic() > final:
                self.fail("O evento de vídeo não terminou a tempo.")
            self.root.update()
            time.sleep(.005)

    def test_aba_abre_sem_imagem_e_play_pause_stop_destroy(self):
        self.assertEqual(self.video.titulo, "Vídeo")
        self.assertIsNone(self.video.origem)
        self.assertNotIn("Reconhecimento facial", self.video.combo_efeito["values"])
        self.video.abrir_video(self.entrada)
        fonte = self.video.fonte
        primeiro = self.video.frame_original.copy()
        self.assertEqual(fonte.posicao, 1)
        self.video.efeito.set("Inversão de cores")
        self.video._atualizar_efeito()
        np.testing.assert_array_equal(self.video.frame_processado, 255 - primeiro)
        self.video.reproduzir()
        self.aguardar(lambda: fonte.posicao >= 2)
        self.video.pausar()
        self.assertIsNone(self.video.play_id)
        self.assertFalse(self.video.reproduzindo)
        self.video.parar()
        self.assertEqual(fonte.posicao, 1)
        np.testing.assert_array_equal(self.video.frame_original, primeiro)
        capture = fonte.capture
        self.video.reproduzir()
        self.video.destroy()
        self.assertFalse(capture.isOpened())
        self.assertIsNone(self.video.play_id)
        self.assertIsNone(self.video.resize_id)
        self.assertTrue(self.video.encerrada)

    def test_fim_do_video_mantem_ultimo_e_reproduzir_reinicia(self):
        self.video.abrir_video(self.entrada)
        primeiro = self.video.frame_original.copy()
        self.video.reproduzir()
        self.aguardar(lambda: self.video.finalizado)
        self.assertEqual(self.video.fonte.posicao, 9)
        ultimo = self.video.frame_original.copy()
        self.assertFalse(np.array_equal(primeiro, ultimo))
        self.video.reproduzir()
        self.aguardar(lambda: self.video.fonte.posicao == 1)
        self.video.pausar()
        np.testing.assert_array_equal(self.video.frame_original, primeiro)

    def test_trocar_fonte_libera_anterior_e_camera_invalida_informa(self):
        self.video.abrir_video(self.entrada)
        anterior = self.video.fonte.capture
        self.video.abrir_video(self.entrada)
        self.assertFalse(anterior.isOpened())
        segunda = self.video.fonte.capture
        with patch("editor_video.cv2.VideoCapture") as classe:
            classe.return_value.isOpened.return_value = False
            self.video.abrir_camera(99)
            self.assertFalse(segunda.isOpened())
            classe.return_value.release.assert_called_once()
        self.assertIsNone(self.video.fonte)
        self.assertIn("Câmera indisponível", self.video.status.get())
        self.video.indice_camera.set("abc")
        self.video.abrir_camera()
        self.assertIn("inteiro", self.video.status.get())
        self.assertEqual(self.mensagem.call_count, 2)

    def test_camera_parar_libera_dispositivo(self):
        frame = np.full((64, 96, 3), 80, np.uint8)
        with patch("editor_video.cv2.VideoCapture") as classe:
            capture = classe.return_value
            capture.isOpened.return_value = True
            capture.read.return_value = (True, frame)
            capture.get.return_value = 30
            self.video.abrir_camera(0)
            self.assertTrue(self.video.fonte.camera)
            self.assertIsNone(self.video.caminho_video)
            self.video.parar()
            capture.release.assert_called_once()
            self.assertIsNone(self.video.fonte)

    def test_exporta_frame_unicode_e_video_no_worker_sem_alterar_playback(self):
        self.video.abrir_video(self.entrada)
        self.video.efeito.set("Escala de cinza")
        self.video._atualizar_efeito()
        imagem = Path(self.pasta.name) / "visão frame.png"
        self.video.exportar_frame(imagem)
        png = cv2.imdecode(np.fromfile(str(imagem), np.uint8), cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(png, self.video.frame_processado)
        destino = Path(self.pasta.name) / "saída vídeo.avi"
        self.video.exportar_video(destino)
        self.aguardar(lambda: self.video.worker is None)
        self.assertEqual(self.video.fonte.posicao, 1)
        frames, _fps = ler_frames(destino)
        self.assertEqual(len(frames), 9)
        self.assertTrue(np.all(np.abs(frames[0][:, :, 0].astype(int) - frames[0][:, :, 2]) <= 3))
        self.assertIn("9 frames", self.video.status.get())
        self.mensagem.assert_not_called()

    def test_worker_nao_bloqueia_tk_cancelamento_e_fechamento(self):
        self.video.abrir_video(self.entrada)
        entrou = threading.Event()
        def exportar_lento(_origem, _destino, _efeito, _processador, cancelar, _progresso):
            entrou.set()
            if not cancelar.wait(5):
                raise RuntimeError("O cancelamento não foi solicitado.")
            raise ExportacaoCancelada()
        with patch("editor_video.exportar_arquivo_video", side_effect=exportar_lento):
            self.video.exportar_video(Path(self.pasta.name) / "saida.avi")
            self.assertTrue(entrou.wait(1))
            executou_tk = []
            self.root.after(1, lambda: executou_tk.append(True))
            self.aguardar(lambda: bool(executou_tk))
            self.video.abrir_video(self.entrada)
            self.aguardar(lambda: self.video.worker is None)
            self.assertIn("cancelada", self.video.status.get())
            self.video.exportar_video(Path(self.pasta.name) / "saida.avi")
            worker = self.video.worker
            self.video.destroy()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertIsNone(self.video.poll_id)

    def test_facial_pode_ser_injetado_depois_da_abertura(self):
        self.video.abrir_video(self.entrada)
        self.video.configurar_processador_facial(lambda frame: 255 - frame)
        self.assertIn("Reconhecimento facial", self.video.combo_efeito["values"])
        self.video.efeito.set("Reconhecimento facial")
        self.video._atualizar_efeito()
        np.testing.assert_array_equal(self.video.frame_processado, 255 - self.video.frame_original)


if __name__ == "__main__":
    unittest.main()
