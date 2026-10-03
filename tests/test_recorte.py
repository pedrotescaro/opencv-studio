import tkinter as tk
import unittest
from types import SimpleNamespace

import numpy as np

from editor_recorte import JanelaRecorte, limites_recorte, recortar_imagem
from editor_opencv_otimizado import EditorOpenCV


class RecorteTests(unittest.TestCase):
    def test_retangulo_invertido_e_limites(self):
        image = np.arange(60, dtype=np.uint8).reshape(6, 10)
        result, pixels = recortar_imagem(image, (12, 5), (-2, 2), "Retângulo")
        np.testing.assert_array_equal(result, image[2:5, :])
        self.assertEqual(pixels, 30)
        result[:] = 0
        self.assertNotEqual(int(image[2, 0]), 0)

    def test_quadrado_nas_quatro_direcoes(self):
        for fim in ((9, 8), (1, 8), (9, 2), (1, 2)):
            x0, y0, x1, y1 = limites_recorte((10, 10), (5, 5), fim, "Quadrado")
            self.assertEqual(x1 - x0, 3)
            self.assertEqual(y1 - y0, 3)

    def test_formas_e_contagem_independente_de_canais(self):
        for canais in ((), (3,)):
            image = np.full((3, 3) + canais, 255, np.uint8)
            for forma, esperado in (("Retângulo", 9), ("Elipse", 9), ("Círculo", 9), ("Losango", 5)):
                result, pixels = recortar_imagem(image, (0, 0), (3, 3), forma)
                self.assertEqual(pixels, esperado)
                self.assertEqual(np.count_nonzero(result), esperado * (3 if canais else 1))
            self.assertTrue(np.all(image == 255))

    def test_selecao_vazia_e_um_pixel(self):
        image = np.ones((1, 1), np.uint8)
        with self.assertRaises(ValueError):
            recortar_imagem(image, (0, 0), (0, 1), "Retângulo")
        for forma in ("Retângulo", "Quadrado", "Elipse", "Círculo", "Losango"):
            result, pixels = recortar_imagem(image, (0, 0), (1, 1), forma)
            self.assertEqual(pixels, 1)
            np.testing.assert_array_equal(result, image)


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = EditorOpenCV(self.root)
        self.app.live_preview.set(False)
        self.app.atual = np.full((40, 60, 3), 200, np.uint8)
        self.app.original = self.app.atual.copy()

    def tearDown(self):
        self.app.fechar()

    def test_aplicar_desfazer_refazer_e_info(self):
        original = self.app.atual.copy()
        result, pixels = recortar_imagem(original, (2, 3), (12, 13), "Círculo")
        self.app.aplicar_recorte(result, pixels)
        self.assertIn("Pixels: 100", self.app.info_label.cget("text"))
        self.app.desfazer()
        np.testing.assert_array_equal(self.app.atual, original)
        self.app.refazer()
        np.testing.assert_array_equal(self.app.atual, result)

    def test_janela_coordenadas_e_confirmacao(self):
        win = JanelaRecorte(self.root, self.app.atual, self.app.aplicar_recorte)
        win.withdraw()
        win.renderizar()
        win.transformacao = (10, 20, 0.5, 0.25)
        self.assertEqual(win.coordenada(SimpleNamespace(x=20, y=25)), (20, 20))
        self.assertIsNone(win.coordenada(SimpleNamespace(x=0, y=0), True))
        win.forma.set("Quadrado")
        win.selecionar_tudo()
        self.assertIn("1,600", win.info.cget("text"))
        win.aplicar()
        self.assertEqual(self.app.atual.shape, (40, 40, 3))


if __name__ == "__main__":
    unittest.main()
