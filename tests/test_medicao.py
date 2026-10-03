import csv
import uuid
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from editor_medicao import JanelaMedicao, area_calibrada, calcular_escala, mascara_poligono, medir_regiao
from editor_opencv_otimizado import EditorOpenCV


class AreaTests(unittest.TestCase):
    def test_retangulo_por_contorno_sem_erro_de_borda(self):
        pontos = [(2, 1), (6, 1), (6, 4), (2, 4)]
        regiao = medir_regiao((10, 10), "Polígono", pontos=pontos)
        self.assertEqual(regiao["pixels"], 12)
        self.assertEqual(regiao["limites"], (2, 1, 6, 4))
        reverso = medir_regiao((10, 10, 3), "Desenho livre", pontos=pontos[::-1])
        self.assertEqual(reverso["pixels"], 12)

    def test_triangulo_inclui_centros_na_borda(self):
        mascara, _ = mascara_poligono((4, 4), [(0, 0), (4, 0), (0, 4)])
        esperado = np.array([[1, 1, 1, 1], [1, 1, 1, 0], [1, 1, 0, 0], [1, 0, 0, 0]], dtype=bool)
        np.testing.assert_array_equal(mascara, esperado)

    def test_concavo_nao_conta_retangulo_externo(self):
        regiao = medir_regiao((3, 3), "Polígono", pontos=[(0, 0), (3, 0), (3, 1), (1, 1), (1, 3), (0, 3)])
        self.assertEqual(regiao["pixels"], 5)

    def test_restringe_a_imagem(self):
        regiao = medir_regiao((3, 3), "Polígono", pontos=[(-3, -3), (2, -3), (2, 2), (-3, 2)])
        self.assertEqual(regiao["pixels"], 4)
        self.assertEqual(regiao["limites"], (0, 0, 2, 2))

    def test_contornos_invalidos(self):
        for pontos in ([], [(0, 0), (1, 1)], [(0, 0)] * 3, [(0, 0), (1, 1), (2, 2)], [(5, 5), (6, 5), (6, 6)], [(0, 0), (float("nan"), 2), (1, 2)]):
            with self.subTest(pontos=pontos), self.assertRaises(ValueError):
                mascara_poligono((3, 3), pontos)

    def test_escala_quadratica(self):
        escala = calcular_escala([(0, 0), (3, 4)], "2,5")
        self.assertEqual(escala, 0.5)
        self.assertEqual(area_calibrada(12, escala), 3)
        self.assertIsNone(area_calibrada(12, None))
        for distancia in ("0", "-1", "nan", "inf", "abc"):
            with self.assertRaises(ValueError):
                calcular_escala([(0, 0), (3, 4)], distancia)
        with self.assertRaises(ValueError):
            calcular_escala([(1, 1), (1, 1)], 2)


class MedicaoInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.avisos = patch("editor_medicao.messagebox.showinfo", side_effect=AssertionError("Aviso inesperado"))
        self.erros = patch("editor_medicao.messagebox.showerror", side_effect=AssertionError("Erro inesperado"))
        self.avisos.start()
        self.erros.start()
        self.addCleanup(self.avisos.stop)
        self.addCleanup(self.erros.stop)
        self.imagem = np.full((600, 800, 3), 200, np.uint8)
        self.dados = {}
        self.win = JanelaMedicao(self.root, self.imagem, self.dados)
        self.win.withdraw()
        self.win.renderizar()
        self.win.transformacao = (0, 0, 1, 1)

    def tearDown(self):
        self.root.destroy()

    def poligono(self):
        for x, y in ((2, 1), (6, 1), (6, 4), (2, 4)):
            self.win.comecar(SimpleNamespace(x=x, y=y))
        self.win.fechar_contorno()

    def test_medicoes_separadas_e_imagem_preservada(self):
        self.poligono()
        self.win.adicionar()
        self.win.forma.set("Retângulo")
        self.win.comecar(SimpleNamespace(x=10, y=10))
        self.win.terminar(SimpleNamespace(x=15, y=15))
        self.win.adicionar()
        self.assertEqual([r["pixels"] for r in self.dados["regioes"]], [12, 25])
        self.assertEqual(len(self.win.tabela.get_children()), 2)
        self.assertTrue(np.all(self.imagem == 200))
        self.win.destroy()
        self.win = JanelaMedicao(self.root, self.imagem, self.dados)
        self.win.withdraw()
        self.assertEqual(len(self.win.tabela.get_children()), 2)

    def test_desenho_livre_e_correcao(self):
        self.win.forma.set("Desenho livre")
        self.win.comecar(SimpleNamespace(x=0, y=0))
        self.win.arrastar(SimpleNamespace(x=4, y=0))
        self.win.arrastar(SimpleNamespace(x=4, y=3))
        self.win.terminar(SimpleNamespace(x=0, y=3))
        self.assertEqual(self.win.regiao_atual()["pixels"], 12)
        self.win.remover_ponto()
        self.assertFalse(self.win.fechado)
        self.assertIn("disabled", self.win.btn_adicionar.state())

    def test_coordenadas_com_zoom_e_rolagem(self):
        self.win.zoom.set("200%")
        self.win.renderizar()
        self.win.canvas.xview_moveto(0.25)
        self.win.canvas.yview_moveto(0.25)
        evento = SimpleNamespace(x=20, y=40)
        x, y = self.win.coordenada(evento)
        self.assertEqual(x, round(self.win.canvas.canvasx(20) / 2))
        self.assertEqual(y, round(self.win.canvas.canvasy(40) / 2))
        self.assertGreater(x, 10)

    def test_calibracao_e_csv(self):
        self.poligono()
        self.win.adicionar()
        self.win.marcar_referencia()
        self.win.comecar(SimpleNamespace(x=0, y=0))
        self.win.comecar(SimpleNamespace(x=3, y=4))
        self.win.distancia.set("2,5")
        self.win.calibrar()
        self.assertEqual(self.dados["escala"], 0.5)
        self.assertIn("3 cm²", self.win.tabela.item("0", "values")[3])
        path = Path(__file__).resolve().parent / f"areas-{uuid.uuid4().hex}.csv"
        try:
            with patch("editor_medicao.filedialog.asksaveasfilename", return_value=path):
                self.win.exportar()
            with open(path, encoding="utf-8-sig", newline="") as arquivo:
                rows = list(csv.DictReader(arquivo, delimiter=";"))
            self.assertEqual(rows[0]["Pixels"], "12")
            self.assertEqual(rows[0]["Area_fisica_estimada"], "3.0")
            self.assertEqual(rows[0]["Unidade_area"], "cm²")
        finally:
            path.unlink(missing_ok=True)
        self.win.limpar_escala()
        self.assertIsNone(self.dados["escala"])
        self.assertEqual(self.win.tabela.item("0", "values")[3], "Sem escala")

    def test_excluir_regiao(self):
        self.poligono()
        self.win.adicionar()
        self.win.tabela.selection_set("0")
        self.win.excluir()
        self.assertEqual(self.dados["regioes"], [])

    def test_editor_conserva_medicoes_ao_reabrir(self):
        self.win.destroy()
        app = EditorOpenCV(self.root)
        app.live_preview.set(False)
        app.atual = self.imagem
        with patch("editor_opencv_otimizado.JanelaMedicao") as janela:
            app.abrir_medicao()
            app._dados_medicoes["regioes"] = ["exemplo"]
            app.abrir_medicao()
            self.assertEqual(janela.call_args.args[2]["regioes"], ["exemplo"])
            app.atual = self.imagem.copy()
            app.abrir_medicao()
            self.assertEqual(janela.call_args.args[2], {})
        app.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
