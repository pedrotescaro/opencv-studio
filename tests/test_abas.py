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
        self.assertEqual(len(self.app.abas.tabs()), len(self.app.nomes_abas))
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
        self.assertEqual(len(self.app.abas.tabs()), len(self.app.nomes_abas))

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
        self.assertEqual(len(self.app.abas.tabs()), len(self.app.nomes_abas))
        self.assertEqual(self.app.abas.tab(self.app.abas.select(), "text"), "Editor")

    def test_substituir_ultima_aba_nao_duplica_paginas(self):
        primeira = AbaFerramenta(self.root, "Composição", origem=self.app.atual)
        segunda = AbaFerramenta(self.root, "Composição", origem=self.app.atual)
        self.assertFalse(primeira.winfo_exists())
        self.assertEqual(len(self.app.abas.tabs()), len(self.app.nomes_abas))
        segunda.destroy()
        self.assertEqual(len(self.app.abas.tabs()), len(self.app.nomes_abas))

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

    def test_arrastar_divisoria_amplia_imagem_sem_alterar_medicao(self):
        self.root.deiconify()
        self.app.atual = np.full((1600, 1200, 3), 100, np.uint8)
        self.app.atualizar_info()
        medicao = self.abrir_medicao()
        self.root.update()
        altura = medicao.canvas.winfo_height()
        escala = medicao.transformacao[3]
        pixels = medicao.regiao_atual()["pixels"]
        divisao = medicao.visualizacao.divisao
        x, y = divisao.sash_coord(0)
        # Exercita o arraste pelo mesmo binding nativo usado pelo mouse.
        divisao.event_generate("<ButtonPress-1>", x=x+20, y=y+4)
        divisao.event_generate("<B1-Motion>", x=x+20, y=y+84)
        divisao.event_generate("<ButtonRelease-1>", x=x+20, y=y+84)
        self.root.update()
        self.assertGreater(medicao.canvas.winfo_height(), altura+60)
        self.assertGreater(medicao.transformacao[3], escala)
        self.assertEqual(medicao.regiao_atual()["pixels"], pixels)
        self.assertTrue(medicao.fechado)

    def test_expandir_e_restaurar_todas_as_areas_de_imagem(self):
        self.root.deiconify()
        medicao = self.abrir_medicao()
        medicao.abrir_segmentacao()
        self.app.abrir_recorte()
        recorte = self.app.paginas["Recorte"]
        recorte.inicio, recorte.fim = (10, 10), (60, 60)
        for titulo in ("Editor", "Recorte", "Medições", "Segmentação"):
            self.app.selecionar_aba(titulo)
            pagina = self.app if titulo == "Editor" else self.app.paginas[titulo]
            self.root.update()
            visualizacao = pagina.visualizacao
            dimensao = pagina.canvas.winfo_height() if visualizacao.orient == "vertical" else pagina.canvas.winfo_width()
            posicao = visualizacao.divisao.sash_coord(0)
            visualizacao.botao_expandir.invoke()
            self.root.update()
            ampliada = pagina.canvas.winfo_height() if visualizacao.orient == "vertical" else pagina.canvas.winfo_width()
            self.assertGreater(ampliada, dimensao+60, titulo)
            self.assertFalse(visualizacao.painel_controles.winfo_ismapped())
            visualizacao.botao_expandir.invoke()
            self.root.update()
            self.assertTrue(visualizacao.painel_controles.winfo_ismapped())
            self.assertEqual(visualizacao.divisao.sash_coord(0), posicao)
        self.assertEqual(recorte.fim, (60, 60))
        self.assertTrue(medicao.fechado)


if __name__ == "__main__":
    unittest.main()
