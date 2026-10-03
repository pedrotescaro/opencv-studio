import time
import tkinter as tk
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from editor_medicao import JanelaMedicao
from editor_segmentacao import (ETAPAS, JanelaSegmentacao, criar_sementes,
                                limpar_componentes, segmentar_imagem, validar_parametros)


def cena():
    imagem = np.random.default_rng(12).integers(15, 35, (100, 140, 3), dtype=np.uint8)
    verdade = np.zeros((100, 140), np.uint8)
    cv2.circle(verdade, (40, 50), 18, 255, -1)
    cv2.circle(verdade, (100, 50), 12, 255, -1)
    imagem[verdade != 0] = [20, 40, 220]
    roi = cv2.dilate(verdade, np.ones((5, 5), np.uint8))
    opcoes = dict(kernel=7, erosao=2, dilatacao=1, fechamento_iteracoes=0, area_minima=10)
    return imagem, verdade, roi, opcoes


class SegmentacaoTests(unittest.TestCase):
    def test_sementes_certas_e_incertas_com_correcao(self):
        roi = np.zeros((30, 30), np.uint8)
        roi[10:20, 10:20] = 255
        correcoes = np.full(roi.shape, -1, np.int8)
        correcoes[15, 15] = cv2.GC_BGD
        correcoes[0, 0] = cv2.GC_FGD
        sementes = criar_sementes(roi, 3, 1, 1, correcoes)
        self.assertEqual(sementes[14, 14], cv2.GC_FGD)
        self.assertEqual(sementes[10, 14], cv2.GC_PR_FGD)
        self.assertEqual(sementes[9, 14], cv2.GC_PR_BGD)
        self.assertEqual(sementes[5, 5], cv2.GC_BGD)
        self.assertEqual(sementes[15, 15], cv2.GC_BGD)
        self.assertEqual(sementes[0, 0], cv2.GC_FGD)

    def test_grabcut_real_separa_dois_objetos_e_preserva_entrada(self):
        imagem, verdade, roi, opcoes = cena()
        copia, copia_roi = imagem.copy(), roi.copy()
        etapas = []
        resultado = segmentar_imagem(imagem, roi, opcoes, progresso=etapas.append)
        np.testing.assert_array_equal(resultado["mascara"], verdade)
        np.testing.assert_array_equal(imagem, copia)
        np.testing.assert_array_equal(roi, copia_roi)
        self.assertEqual(len(resultado["regioes"]), 2)
        self.assertEqual(resultado["pixels"], sum(r["pixels"] for r in resultado["regioes"]))
        self.assertEqual(len(etapas), 7)
        for chave in ("suavizada", "sementes", "rotulos", "binaria", "fechada", "mascara", "sobreposicao"):
            self.assertEqual(resultado[chave].shape[:2], imagem.shape[:2])
        self.assertEqual(set(np.unique(resultado["mascara"])), {0, 255})

    def test_componentes_remove_fragmentos_e_nao_conta_buracos(self):
        mascara = np.zeros((20, 30), np.uint8)
        mascara[1:6, 1:6] = 255
        mascara[3, 3] = 0
        mascara[10:14, 15:19] = 255
        mascara[18, 28] = 255
        limpa, regioes, removidos = limpar_componentes(mascara, 2)
        self.assertEqual([r["pixels"] for r in regioes], [24, 16])
        self.assertEqual(removidos, 1)
        self.assertEqual(np.count_nonzero(limpa), 40)
        maior, regioes, removidos = limpar_componentes(mascara, 2, True)
        self.assertEqual(np.count_nonzero(maior), 24)
        self.assertEqual(removidos, 2)
        self.assertEqual(len(regioes), 1)

    def test_fechamento_respeita_fundo_certo(self):
        imagem = np.full((30, 30, 3), 100, np.uint8)
        roi = np.zeros((30, 30), np.uint8)
        roi[5:25, 5:25] = 255
        correcoes = np.full(roi.shape, -1, np.int8)
        correcoes[15, 15] = cv2.GC_BGD
        def grabcut(_img, rotulos, *_args):
            rotulos[5:25, 5:25] = cv2.GC_PR_FGD
            rotulos[15, 15] = cv2.GC_BGD
            rotulos[6, 6] = cv2.GC_PR_BGD
        with patch("editor_segmentacao.cv2.grabCut", side_effect=grabcut):
            resultado = segmentar_imagem(imagem, roi, dict(area_minima=1), correcoes)
        self.assertEqual(resultado["fechada"][15, 15], 0)
        self.assertEqual(resultado["fechada"][6, 6], 255)
        self.assertEqual(resultado["pixels"], np.count_nonzero(resultado["mascara"]))

    def test_conectividade_diagonal(self):
        mascara = np.eye(6, dtype=np.uint8) * 255
        _, regioes, _ = limpar_componentes(mascara, 2)
        self.assertEqual(len(regioes), 1)
        self.assertEqual(regioes[0]["pixels"], 6)

    def test_validacao_e_mascara_vazia(self):
        for invalido in (dict(kernel=2), dict(iteracoes=0), dict(area_minima="abc"), dict(sigma_cor=float("inf"))):
            with self.assertRaises(ValueError):
                validar_parametros(invalido)
        for roi in (np.zeros((20, 20), np.uint8), np.ones((20, 20), np.uint8)):
            with self.assertRaises(ValueError):
                criar_sementes(roi)
        limpa, regioes, removidos = limpar_componentes(np.zeros((20, 20), np.uint8))
        self.assertFalse(limpa.any())
        self.assertEqual(regioes, [])
        self.assertEqual(removidos, 0)


class SegmentacaoInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.imagem, self.verdade, self.roi, self.opcoes = cena()
        self.medicao = JanelaMedicao(self.root, self.imagem, {})
        self.medicao.withdraw()
        self.win = JanelaSegmentacao(self.medicao, self.imagem, self.roi, self.medicao.adicionar_segmentacao)
        self.win.withdraw()
        for chave, valor in self.opcoes.items():
            self.win.parametros[chave].set(valor)
        for funcao in ("showinfo", "showerror"):
            mock = patch(f"editor_segmentacao.messagebox.{funcao}", side_effect=AssertionError("Mensagem inesperada"))
            mock.start()
            self.addCleanup(mock.stop)

    def tearDown(self):
        if self.win.winfo_exists():
            self.win.fechar()
        self.root.destroy()

    def executar(self):
        self.win.executar()
        limite = time.monotonic() + 10
        while self.win.processando and time.monotonic() < limite:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.win.processando)
        self.assertIsNotNone(self.win.resultado)

    def test_fluxo_assincrono_etapas_importacao_e_exportacao_png(self):
        self.executar()
        for etapa in ETAPAS:
            self.win.etapa.set(etapa)
            imagem = self.win.imagem_visual()
            self.assertEqual(imagem.shape[:2], self.roi.shape)
        path = Path(__file__).resolve().parent / f"mascara-{uuid.uuid4().hex}.png"
        try:
            with patch("editor_segmentacao.filedialog.asksaveasfilename", return_value=str(path)):
                self.win.salvar("mascara")
            gravada = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_GRAYSCALE)
            np.testing.assert_array_equal(gravada, self.verdade)
        finally:
            path.unlink(missing_ok=True)
        self.win.importar()
        regioes = self.medicao.dados["regioes"]
        self.assertEqual(len(regioes), 2)
        self.assertEqual(sum(r["pixels"] for r in regioes), np.count_nonzero(self.verdade))
        self.assertTrue(all(r["forma"] == "Segmentação" for r in regioes))
        self.medicao.renderizar()

    def test_alterar_parametro_invalida_contagem(self):
        self.executar()
        self.win.parametros["area_minima"].set("200")
        self.assertIsNone(self.win.resultado)
        self.assertIn("disabled", self.win.btn_importar.state())
        self.assertIn("disabled", self.win.btn_mascara.state())
        self.assertEqual(self.win.tabela.get_children(), ())

    def test_pincel_usa_pixels_originais_e_invalida_resultado(self):
        self.win.transformacao = (0, 0, 2, 2)
        self.win.pincel.set("Fundo certo")
        self.win.raio.set("1")
        self.win.comecar(SimpleNamespace(x=80, y=100))
        self.win.arrastar(SimpleNamespace(x=84, y=100))
        self.win.terminar()
        self.assertEqual(self.win.correcoes[50, 40], cv2.GC_BGD)
        self.assertEqual(self.win.correcoes[50, 42], cv2.GC_BGD)
        self.assertEqual(self.win.correcoes[70, 40], -1)
        self.win.limpar_marcas()
        self.assertTrue(np.all(self.win.correcoes == -1))

    def test_roi_de_poligono_encaminhada_e_nome_generico(self):
        self.medicao.forma.set("Polígono")
        self.medicao.pontos = [(10, 10), (30, 10), (30, 30), (10, 30)]
        self.medicao.fechar_contorno()
        with patch("editor_segmentacao.JanelaSegmentacao") as janela:
            self.medicao.abrir_segmentacao()
            roi = janela.call_args.args[2]
            self.assertEqual(np.count_nonzero(roi), 400)
            self.assertEqual(roi.shape, self.imagem.shape[:2])
        self.assertTrue(self.medicao.nome.get().startswith("Objeto"))


if __name__ == "__main__":
    unittest.main()
