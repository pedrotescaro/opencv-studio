import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from editor_interface import AbaFerramenta
from editor_opencv_otimizado import EditorOpenCV


class AbasTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.erros = []
        self.root.report_callback_exception = lambda *args: self.erros.append(args)
        self.app = EditorOpenCV(self.root)
        self.app.atual = np.full((120, 180, 3), 100, np.uint8)
        self.app.original = self.app.atual.copy()
        self.app.atualizar_info()
        self.app.atualizar_botoes()

    def tearDown(self):
        self.app.fechar()
        self.assertEqual(self.erros, [])

    def abrir_medicao(self):
        self.app.abrir_medicao()
        medicao = self.app.paginas["Medições"]
        medicao.pontos = [(30, 30), (120, 30), (120, 90), (30, 90)]
        medicao.fechar_contorno()
        return medicao

    def test_ferramentas_sao_abas_e_selecao_persiste(self):
        medicao = self.abrir_medicao()
        pontos = list(medicao.pontos)
        self.app.abrir_recorte()
        recorte = self.app.paginas["Recorte"]
        recorte.inicio, recorte.fim = (10, 10), (60, 60)
        self.app.abrir_medicao()
        self.assertIs(self.app.paginas["Medições"], medicao)
        self.assertEqual(medicao.pontos, pontos)
        self.app.abrir_recorte()
        self.assertIs(self.app.paginas["Recorte"], recorte)
        self.assertEqual(recorte.fim, (60, 60))
        self.assertEqual(len(self.app.abas.tabs()), 6)
        self.assertIs(medicao.winfo_toplevel(), self.root)
        self.assertIs(recorte.master, self.app.abas)
        self.assertIsNone(self.root.grab_current())

    def test_selecionar_tab_constroi_ferramenta(self):
        self.app.selecionar_aba("Recorte")
        self.root.update()
        self.assertIsInstance(self.app.paginas["Recorte"], AbaFerramenta)
        self.assertEqual(self.app.abas.tab(self.app.abas.select(), "text"), "Recorte")
        self.app.editar_kernel()
        self.assertEqual(self.app.abas.tab(self.app.abas.select(), "text"), "Morfologia")
        self.assertEqual(len(self.app.abas.tabs()), 6)

    def test_enter_e_desfazer_seguem_aba_ativa(self):
        medicao = self.abrir_medicao()
        medicao.fechado = False
        evento = SimpleNamespace(widget=medicao.canvas)
        with patch.object(self.app, "aplicar_filtro") as aplicar:
            self.app.atalho_local("enter", evento)
            aplicar.assert_not_called()
        self.assertTrue(medicao.fechado)
        with patch.object(self.app, "desfazer") as desfazer:
            self.app.atalho_historico(evento)
            desfazer.assert_not_called()
        self.assertEqual(len(medicao.pontos), 3)
        self.assertFalse(medicao.fechado)

    def test_imagem_nova_fecha_ferramentas_sem_callbacks_pendentes(self):
        medicao = self.abrir_medicao()
        medicao.abrir_segmentacao()
        seg = self.app.paginas["Segmentação"]
        seg.executar()
        self.app.atual = np.zeros((80, 90, 3), np.uint8)
        self.app.atualizar_info()
        self.root.update()
        self.assertFalse(seg.winfo_exists())
        self.assertFalse(medicao.winfo_exists())
        self.assertTrue(seg.encerrada)
        self.assertIsNone(seg.poll_id)
        self.assertIsNone(seg.resize_id)
        self.assertEqual(len(self.app.abas.tabs()), 6)
        self.assertEqual(self.app.abas.tab(self.app.abas.select(), "text"), "Editor")

    def test_substituir_ultima_aba_nao_duplica_paginas(self):
        primeira = AbaFerramenta(self.root, "Composição", origem=self.app.atual)
        segunda = AbaFerramenta(self.root, "Composição", origem=self.app.atual)
        self.assertFalse(primeira.winfo_exists())
        self.assertEqual(len(self.app.abas.tabs()), 6)
        segunda.destroy()
        self.assertEqual(len(self.app.abas.tabs()), 6)

    def test_filtros_ocultam_parametros_inutilizados(self):
        self.app.filtro_var.set("Escala de cinza")
        self.app.configurar_parametros()
        self.assertEqual(self.app.ajustes.winfo_manager(), "")
        self.app.filtro_var.set("Brilho")
        self.app.configurar_parametros()
        self.assertEqual(self.app.ajustes.winfo_manager(), "pack")
        self.assertEqual(self.app.slider2.winfo_manager(), "")
        self.app.filtro_var.set("Erosão")
        self.app.configurar_parametros()
        self.assertEqual(self.app.morfologia_box.winfo_manager(), "pack")

    def test_layout_minimo_mantem_acao_e_canvas_acessiveis(self):
        self.root.deiconify()
        self.root.geometry("1000x680")
        medicao = self.abrir_medicao()
        self.root.update()
        self.assertGreater(medicao.canvas.winfo_height(), 150)
        for widget in (medicao.btn_adicionar, medicao.btn_segmentar):
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), self.root.winfo_rootx()+self.root.winfo_width())
        medicao.abrir_segmentacao()
        seg = self.app.paginas["Segmentação"]
        self.root.update()
        self.assertGreater(seg.canvas.winfo_height(), 200)
        self.assertTrue(seg.btn_executar.winfo_ismapped())
        self.assertTrue(seg.btn_importar.winfo_ismapped())
        self.assertEqual(seg.ajustes_box.winfo_manager(), "")
        self.assertTrue(seg.tabela.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
