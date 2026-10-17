import tempfile
import time
from pathlib import Path
import tkinter as tk
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from editor_laboratorio import (JanelaLaboratorio, converter_cor, crescer_regiao,
                                histogramas, quantizar, redimensionar)
from editor_opencv_otimizado import EditorOpenCV


class LaboratorioTests(unittest.TestCase):
    def test_rgb_troca_canais_e_copia_independente(self):
        imagem = np.array([[[10, 20, 240]]], np.uint8)
        rgb = converter_cor(imagem, "BGR", "RGB")
        np.testing.assert_array_equal(rgb, [[[240, 20, 10]]])
        np.testing.assert_array_equal(converter_cor(rgb, "RGB", "BGR"), imagem)
        copia = converter_cor(imagem, "BGR", "BGR")
        self.assertFalse(np.shares_memory(imagem, copia))

    def test_hsv_roundtrip_e_cinza(self):
        imagem = np.array([[[0, 0, 255], [0, 255, 0], [255, 0, 0], [110, 150, 200]]], np.uint8)
        hsv = converter_cor(imagem, "BGR", "HSV")
        self.assertEqual(hsv[0, :, 0].tolist()[:3], [0, 60, 120])
        volta = converter_cor(hsv, "HSV", "BGR")
        self.assertLessEqual(np.max(np.abs(volta.astype(int)-imagem.astype(int))), 3)
        cinza = converter_cor(imagem, "BGR", "Cinza")
        self.assertEqual(cinza.shape, (1, 4))
        self.assertEqual(converter_cor(cinza, "Cinza", "HSV").shape, imagem.shape)
        with self.assertRaises(ValueError):
            converter_cor(cinza, "HSV", "BGR")

    def test_histograma_soma_pixels_e_cores_exatas(self):
        imagem = np.zeros((6, 10, 3), np.uint8)
        imagem[:, :, 2] = 255
        for espaco in ("RGB", "HSV", "Cinza"):
            for canal in histogramas(imagem, espaco=espaco).values():
                self.assertEqual(int(canal.sum()), 60)
        hist = histogramas(imagem)
        self.assertEqual(hist["R"][255], 60)
        self.assertEqual(hist["B"][0], 60)
        self.assertEqual(len(histogramas(imagem, espaco="HSV")["H"]), 180)

    def test_redimensionamento_real_e_limites(self):
        imagem = np.ones((10, 20, 3), np.uint8)
        self.assertEqual(redimensionar(imagem, 40, 30).shape, (30, 40, 3))
        for dimensoes in ((0, 10), (-1, 20), (10000, 10000)):
            with self.assertRaises(ValueError):
                redimensionar(imagem, *dimensoes)
        self.assertEqual(imagem.shape, (10, 20, 3))

    def test_quantizacao_niveis_identidade_e_extremos(self):
        imagem = np.arange(256, dtype=np.uint8)[None, :]
        for n in (2, 4, 8, 16, 256):
            saida = quantizar(imagem, n)
            self.assertEqual(len(np.unique(saida)), n)
            self.assertEqual((saida.min(), saida.max()), (0, 255))
        np.testing.assert_array_equal(quantizar(imagem, 256), imagem)
        with self.assertRaises(ValueError):
            quantizar(imagem, 1)

    def test_regiao_faixa_fixa_nao_atravessa_gradiente(self):
        imagem = np.array([[10, 15, 20, 25, 30]], np.uint8)
        mascara = crescer_regiao(imagem, (0, 0), 10)
        np.testing.assert_array_equal(mascara, [[255, 255, 255, 0, 0]])
        np.testing.assert_array_equal(imagem, [[10, 15, 20, 25, 30]])

    def test_regiao_conectividade_e_canales(self):
        imagem = np.eye(5, dtype=np.uint8)*255
        self.assertEqual(np.count_nonzero(crescer_regiao(imagem, (0, 0), 0, 4)), 1)
        self.assertEqual(np.count_nonzero(crescer_regiao(imagem, (0, 0), 0, 8)), 5)
        cor = np.zeros((3, 3, 3), np.uint8)
        cor[1, 1] = (0, 0, 20)
        self.assertEqual(np.count_nonzero(crescer_regiao(cor, (0, 0), 10)), 8)
        for args in (((5, 0), 10, 4), ((-1, 0), 10, 4), ((0, 0), -1, 4), ((0, 0), 10, 6)):
            with self.assertRaises(ValueError):
                crescer_regiao(imagem, *args)

    def test_soma_subtracao_saturadas_sem_overflow(self):
        a, b = np.full((4, 4, 3), 230, np.uint8), np.full((4, 4, 3), 60, np.uint8)
        self.assertTrue(np.all(EditorOpenCV.combinar_imagens(a, b, "Soma saturada", 50) == 255))
        self.assertTrue(np.all(EditorOpenCV.combinar_imagens(b, a, "Subtração", 50) == 0))
        self.assertTrue(np.all(a == 230))

    def test_filtros_minimos_em_cinza_e_cor(self):
        app = EditorOpenCV.__new__(EditorOpenCV)
        imagem = np.random.default_rng(20).integers(0, 256, (60, 80, 3), dtype=np.uint8)
        copia = imagem.copy()
        filtros = ("Inverter cores", "Brilho", "Contraste", "Escala de cinza", "Blur",
                   "Median Blur", "Gaussian Blur", "Sobel XY", "Canny", "Equalizar histograma",
                   "Preto e branco", "Threshold Otsu", "Threshold adaptativo", "Posterizar",
                   "Erosão", "Dilatação", "Opening", "Closing")
        for filtro in filtros:
            for base in (imagem, cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)):
                with self.subTest(filtro=filtro, canais=base.ndim):
                    resultado = app.processar_filtro(base, filtro, 5, 10)
                    self.assertEqual(resultado.shape[:2], base.shape[:2])
                    self.assertEqual(resultado.dtype, np.uint8)
        np.testing.assert_array_equal(imagem, copia)


class LaboratorioInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.erros = []
        self.root.report_callback_exception = lambda *args: self.erros.append(args)
        self.app = EditorOpenCV(self.root)
        self.app.atual = np.full((80, 100, 3), (20, 40, 200), np.uint8)
        self.app.original = self.app.atual.copy()
        self.app.atualizar_info()
        self.app.abrir_laboratorio()
        self.win = self.app.paginas["Laboratório"]

    def tearDown(self):
        self.app.fechar()
        self.assertEqual(self.erros, [])

    def esperar(self):
        limite = time.monotonic()+5
        while self.win.processando and time.monotonic() < limite:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.win.processando)

    def test_copia_independente_redimensiona_envia_e_desfaz(self):
        self.assertFalse(np.shares_memory(self.win.base, self.app.atual))
        self.assertFalse(np.shares_memory(self.win.resultado, self.win.base))
        self.win.operacao.set("Redimensionar")
        self.win.largura.set("50")
        self.win.executar()
        self.esperar()
        self.assertEqual(self.win.resultado.shape, (40, 50, 3))
        self.assertEqual(self.app.atual.shape, (80, 100, 3))
        self.win.enviar()
        self.assertEqual(self.app.atual.shape, (40, 50, 3))
        self.app.desfazer()
        self.assertEqual(self.app.atual.shape, (80, 100, 3))

    def test_salvar_hsv_visual_e_matriz_preserva_modelo(self):
        self.win.modelo = "HSV"
        self.win.resultado = converter_cor(self.win.base, "BGR", "HSV")
        with tempfile.TemporaryDirectory() as pasta:
            png, npz = Path(pasta)/"cor ação.png", Path(pasta)/"matriz.npz"
            with patch("editor_laboratorio.filedialog.asksaveasfilename", return_value=str(png)):
                self.win.salvar()
            with patch("editor_laboratorio.filedialog.asksaveasfilename", return_value=str(npz)):
                self.win.exportar_matriz()
            gravada = cv2.imdecode(np.fromfile(png, np.uint8), cv2.IMREAD_COLOR)
            np.testing.assert_array_equal(gravada, self.win.imagem_bgr())
            with np.load(npz) as dados:
                self.assertEqual(str(dados["modelo"]), "HSV")
                np.testing.assert_array_equal(dados["imagem"], self.win.resultado)

    def test_video_e_faces_independem_da_imagem_do_editor(self):
        self.app.abrir_faces()
        faces = self.app.paginas["Reconhecimento facial"]
        self.app.abrir_video()
        video = self.app.paginas["Vídeo"]
        self.app.atual = np.zeros((20, 30), np.uint8)
        self.app.atualizar_info()
        self.assertTrue(faces.winfo_exists())
        self.assertTrue(video.winfo_exists())
        self.assertFalse(self.win.winfo_exists())

    def test_renderizar_direto_cancela_timer_antes_de_fechar(self):
        self.win.agendar_render()
        pendente = self.win.render_id
        self.win.renderizar()
        self.assertNotIn(pendente, self.root.tk.call("after", "info"))
        self.win.destroy()
        self.assertIsNone(self.win.render_id)

    def test_abas_e_acoes_cabem_na_janela_minima(self):
        self.root.deiconify()
        self.root.geometry("1000x680")
        self.root.update()
        encontrados = set()
        for x in range(0, self.app.abas.winfo_width(), 5):
            try:
                encontrados.add(self.app.abas.index(f"@{x},12"))
            except tk.TclError:
                pass
        self.assertEqual(encontrados, set(range(len(self.app.nomes_abas))))
        for operacao in ("Redimensionar", "Crescimento de regiões", "Converter modelo de cor"):
            self.win.operacao.set(operacao)
            self.win.mostrar_parametros()
            self.root.update()
            self.assertGreater(self.win.canvases["resultado"].winfo_height(), 150)
            for widget in self.win.parametros.winfo_children():
                self.assertTrue(widget.winfo_ismapped())
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.root.winfo_rootx()+1000)
        for titulo in ("Vídeo", "Reconhecimento facial"):
            self.app.selecionar_aba(titulo)
            self.root.update()
            pagina = self.app.paginas[titulo]
            self.assertTrue(pagina.winfo_ismapped())
            for canvas in pagina.canvases:
                self.assertGreater(canvas.winfo_width(), 150)
                self.assertGreater(canvas.winfo_height(), 150)

    def test_faces_com_dados_invalidos_exibe_erro_sem_callback_quebrado(self):
        with patch("editor_faces.JanelaFaces", side_effect=ValueError("Cadastro inválido")):
            with patch("editor_opencv_otimizado.messagebox.showerror") as erro:
                self.app.abrir_faces()
        erro.assert_called_once()

    def test_comparacao_editor_mostra_original_e_preview_sem_mudar_matrizes(self):
        original = self.app.original.copy()
        atual = self.app.atual.copy()
        self.app.preview = np.full((20, 30), 30, np.uint8)
        self.app.comparar_lado_a_lado.set(True)
        self.app.atualizar_canvas()
        tipos = [self.app.canvas.type(item) for item in self.app.canvas.find_all()]
        self.assertEqual(tipos.count("image"), 2)
        textos = [self.app.canvas.itemcget(item, "text") for item in self.app.canvas.find_all() if self.app.canvas.type(item) == "text"]
        self.assertEqual(textos, ["Original", "Prévia"])
        np.testing.assert_array_equal(self.app.original, original)
        np.testing.assert_array_equal(self.app.atual, atual)
        self.app.comparar_lado_a_lado.set(False)
        self.app.atualizar_canvas()
        self.assertEqual(len(self.app.canvas.find_all()), 1)

    def test_salvar_na_aba_faces_usa_foto_anotada_em_vez_de_imagem_do_editor(self):
        self.app.abrir_faces()
        faces = self.app.paginas["Reconhecimento facial"]
        with patch.object(faces, "salvar_foto") as salvar_rosto:
            with patch.object(self.app, "salvar_imagem") as salvar_editor:
                self.app.acao_arquivo_contextual("salvar")
        salvar_rosto.assert_called_once()
        salvar_editor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
