"""LBPH real em recortes sintéticos controlados; não mede acurácia humana.

As cenas de integração fornecem caixas conhecidas para isolar o contrato do
reconhecedor. O detector Haar também é executado em uma imagem sem faces.
"""
import csv
import json
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from editor_faces import (BancoFaces, Chamada, ErroFaces, JanelaFaces, MotorFaces,
                          ResultadoFace, ler_imagem, normalizar_face, salvar_imagem)


def face_sintetica(tipo, variante=0):
    rng = np.random.default_rng(300 + variante + 100 * tipo)
    face = np.full((128, 128), 45 + variante * 3, np.uint8)
    cv2.ellipse(face, (64, 64), (49, 59), 0, 0, 360, 160, -1)
    if tipo == 0:
        cv2.circle(face, (44, 45), 9, 15, -1)
        cv2.circle(face, (84, 45), 9, 15, -1)
        cv2.ellipse(face, (64, 79), (26, 17), 0, 0, 180, 30, 5)
        cv2.line(face, (64, 55), (57, 78), 100, 5)
    else:
        cv2.rectangle(face, (26, 32), (55, 53), 25, -1)
        cv2.rectangle(face, (72, 32), (100, 53), 25, -1)
        cv2.line(face, (35, 93), (94, 85), 20, 6)
        cv2.rectangle(face, (58, 52), (70, 78), 100, -1)
        for x in range(20, 110, 12):
            cv2.line(face, (x, 106), (x+5, 116), 30, 2)
    ruido = rng.integers(-3, 4, face.shape, dtype=np.int16)
    return np.clip(face.astype(np.int16) + ruido, 0, 255).astype(np.uint8)


class FacesTests(unittest.TestCase):
    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.pasta = Path(self.temporario.name) / "Dados de Visão e João"
        self.banco = BancoFaces(self.pasta)

    def tearDown(self):
        self.temporario.cleanup()

    def preparar(self):
        self.banco.cadastrar("2026-A", "João da Silva", [face_sintetica(0, 0), face_sintetica(0, 1)])
        self.banco.cadastrar("2026-B", "Ágata Souza", [face_sintetica(1, 0), face_sintetica(1, 1)])
        motor = MotorFaces(self.banco, limiar=60)
        motor.treinar()
        return motor

    def test_lbph_real_reconhece_cadastrados_e_rejeita_textura_desconhecida(self):
        motor = self.preparar()
        for tipo, codigo in ((0, "2026-A"), (1, "2026-B")):
            resultado = motor.prever_face(face_sintetica(tipo))
            self.assertTrue(resultado.reconhecido)
            self.assertEqual(resultado.codigo, codigo)
            self.assertLess(resultado.distancia, 1)
        desconhecida = np.random.default_rng(88).integers(0, 256, (128, 128), dtype=np.uint8)
        resultado = motor.prever_face(desconhecida)
        self.assertFalse(resultado.reconhecido)
        self.assertIsNone(resultado.codigo)
        self.assertGreater(resultado.distancia, 60)

    def test_limiar_controla_rejeicao_sem_tratar_distancia_como_probabilidade(self):
        motor = self.preparar()
        teste = face_sintetica(0, 8)
        motor.definir_limiar(1000)
        distancia = motor.prever_face(teste).distancia
        self.assertGreater(distancia, 0)
        motor.definir_limiar(distancia / 2)
        self.assertFalse(motor.prever_face(teste).reconhecido)
        motor.definir_limiar(distancia + 1)
        self.assertTrue(motor.prever_face(teste).reconhecido)
        for valor in (0, -1, "texto", "nan", "inf"):
            with self.assertRaises(ErroFaces):
                motor.definir_limiar(valor)

    def test_persistencia_unicode_preserva_ids_nomes_e_amostras(self):
        self.preparar()
        banco = BancoFaces(self.pasta)
        self.assertEqual(banco.alunos, self.banco.alunos)
        motor = MotorFaces(banco)
        self.assertEqual(motor.treinar(), (4, 2))
        self.assertEqual(motor.prever_face(face_sintetica(0)).nome, "João da Silva")
        caminho = self.pasta / "Foto de Ágata.png"
        original = cv2.cvtColor(face_sintetica(1), cv2.COLOR_GRAY2BGR)
        salvar_imagem(caminho, original)
        np.testing.assert_array_equal(ler_imagem(caminho), original)

    def test_treino_exige_dois_recortes_distintos_por_pessoa_e_invalida_ao_alterar(self):
        motor = MotorFaces(self.banco)
        with self.assertRaisesRegex(ErroFaces, "Cadastre"):
            motor.treinar()
        with self.assertRaisesRegex(ErroFaces, "Treine"):
            motor.prever_face(face_sintetica(0))
        self.banco.cadastrar("a", "Ana", [face_sintetica(0)])
        with self.assertRaisesRegex(ErroFaces, "duas fotos"):
            motor.treinar()
        with self.assertRaisesRegex(ErroFaces, "repetem"):
            self.banco.cadastrar("a", "Ana", [face_sintetica(0)])
        self.banco.cadastrar("a", "Ana", [face_sintetica(0, 1)])
        self.assertEqual(motor.treinar(), (2, 1))
        self.banco.cadastrar("a", "Ana", [face_sintetica(0, 2)])
        with self.assertRaisesRegex(ErroFaces, "cadastro mudou"):
            motor.prever_face(face_sintetica(0))

    def test_ausencia_contrib_exibe_instrucao_amigavel(self):
        self.banco.cadastrar("a", "Ana", [face_sintetica(0), face_sintetica(0, 1)])
        motor = MotorFaces(self.banco)
        with patch("editor_faces.cv2.face", None):
            with self.assertRaisesRegex(ErroFaces, "opencv-contrib-python"):
                motor.treinar()

    def test_detector_haar_real_em_imagem_sem_face_e_anotacao_preserva_entrada(self):
        motor = self.preparar()
        self.assertEqual(motor.detectar(np.zeros((240, 320, 3), np.uint8)), [])
        imagem = cv2.cvtColor(face_sintetica(0), cv2.COLOR_GRAY2BGR)
        copia = imagem.copy()
        with patch.object(motor, "detectar", return_value=[(0, 0, 128, 128)]):
            anotada, resultados = motor.anotar(imagem)
        np.testing.assert_array_equal(imagem, copia)
        self.assertEqual(anotada.shape, imagem.shape)
        self.assertEqual(resultados[0].codigo, "2026-A")
        self.assertFalse(np.array_equal(anotada, imagem))

    def test_chamada_persistida_e_csv_unicode_deduplicam_id_por_sessao(self):
        chamada = Chamada("Visão Computacional", self.pasta / "chamadas")
        conhecido = ResultadoFace("2026-A", "João da Silva", 12.5)
        self.assertTrue(chamada.registrar(conhecido))
        self.assertFalse(chamada.registrar(ResultadoFace("2026-A", "João da Silva", 5.0)))
        self.assertFalse(chamada.registrar(ResultadoFace(None, "Desconhecido", 115.0)))
        dados = json.loads(chamada.caminho.read_text(encoding="utf-8"))
        self.assertEqual(len(dados["registros"]), 1)
        self.assertEqual(dados["registros"][0]["distancia_lbph"], 12.5)
        csv_path = self.pasta / "Chamada da Visão.csv"
        chamada.exportar_csv(csv_path)
        with csv_path.open(encoding="utf-8-sig", newline="") as arquivo:
            linhas = list(csv.DictReader(arquivo, delimiter=";"))
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["nome"], "João da Silva")
        chamada.encerrar()
        self.assertFalse(chamada.registrar(ResultadoFace("2026-B", "Ágata", 3.0)))
        outra = Chamada("Próxima aula", self.pasta / "chamadas")
        self.assertTrue(outra.registrar(conhecido))

    def test_cadastro_rejeita_manifesto_malformado_e_remocao_apaga_amostras(self):
        self.preparar()
        arquivos = [self.pasta / "amostras" / n for n in self.banco.alunos["2026-A"]["amostras"]]
        self.banco.remover("2026-A")
        self.assertNotIn("2026-A", BancoFaces(self.pasta).alunos)
        self.assertTrue(all(not arquivo.exists() for arquivo in arquivos))
        dados = {"versao": 1, "alunos": {"a": {"nome": "Ana", "amostras": ["../fora.png"]}}}
        self.banco.arquivo.write_text(json.dumps(dados), encoding="utf-8")
        with self.assertRaises(ErroFaces):
            BancoFaces(self.pasta)

    def test_normalizacao_valida_tipo_e_nao_altera_original(self):
        imagem = face_sintetica(0)
        copia = imagem.copy()
        self.assertEqual(normalizar_face(imagem).shape, (128, 128))
        np.testing.assert_array_equal(imagem, copia)
        for invalida in (None, np.zeros((2, 2), np.float32), np.zeros((2, 2, 2), np.uint8)):
            with self.assertRaises(ErroFaces):
                normalizar_face(invalida)


class AbaFacesTests(unittest.TestCase):
    def test_aplicar_limiar_sem_editar_preserva_precisao_da_calibracao(self):
        limiar = 61.204219650042056
        self.aba.motor.definir_limiar(limiar)
        self.aba._treino_concluido(False)
        self.aba.aplicar_limiar()
        self.assertEqual(self.aba.motor.limiar, limiar)
        self.assertEqual(MotorFaces(self.aba.banco).limiar, limiar)

    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.erros = []
        self.root.report_callback_exception = lambda *args: self.erros.append(args)
        self.aba = JanelaFaces(self.root, self.temporario.name)

    def tearDown(self):
        self.aba.destroy()
        self.root.destroy()
        self.temporario.cleanup()
        self.assertEqual(self.erros, [])

    def test_callback_worker_nao_usa_tk_e_registra_uma_presenca(self):
        self.aba.banco.cadastrar("id", "João", [face_sintetica(0), face_sintetica(0, 1)])
        self.aba.motor.treinar()
        self.aba.iniciar_chamada("Aula teste")
        imagem = cv2.cvtColor(face_sintetica(0), cv2.COLOR_GRAY2BGR)
        falhas = []
        saidas = []
        def executar():
            try:
                for _ in range(3):
                    saidas.append(self.aba.anotar_frame(imagem))
            except Exception as exc:
                falhas.append(exc)
        with patch.object(self.aba.motor, "detectar", return_value=[(0, 0, 128, 128)]):
            worker = threading.Thread(target=executar)
            worker.start()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(falhas, [])
        self.assertEqual(len(saidas), 3)
        self.aba._poll()
        self.assertEqual(len(self.aba.tabela.get_children()), 1)
        self.assertEqual(len(self.aba.chamada.linhas()), 1)
        self.aba.encerrar_chamada()
        self.assertFalse(self.aba.chamada.ativa)

    def test_aba_independente_detecta_sem_treino_e_libera_after(self):
        imagem = np.zeros((50, 50, 3), np.uint8)
        with patch("editor_faces.messagebox.showerror") as popup:
            anotada = self.aba.anotar_frame(imagem)
            self.aba._poll()
        np.testing.assert_array_equal(anotada, imagem)
        popup.assert_not_called()
        self.assertEqual(self.aba.btn_analisar.cget("text"), "Detectar rostos")
        self.assertEqual(self.aba.titulo, "Reconhecimento facial")
        self.aba.destroy()
        self.assertIsNone(self.aba.poll_id)
        self.assertIsNone(self.aba.resize_id)
        with self.assertRaisesRegex(ErroFaces, "encerrada"):
            self.aba.anotar_frame(np.zeros((50, 50, 3), np.uint8))
        self.root.update()

    def test_fluxo_foto_sem_modelo_e_erros_recuperaveis_sao_inline(self):
        imagem = np.full((90, 120, 3), 100, np.uint8)
        with patch("editor_faces.messagebox.showerror") as popup:
            self.aba.reconhecer_foto(imagem)
            self.aba._poll()
            self.aba.usar_editor()
            self.assertIn("Abra uma imagem", self.aba.status_var.get())
            self.aba.treinar()
            self.assertIn("duas fotos", self.aba.status_var.get())
            popup.assert_not_called()
        self.assertEqual(len(self.aba.abas_laterais.tabs()), 3)
        np.testing.assert_array_equal(self.aba.original, imagem)
        self.assertIsNotNone(self.aba.processada)

    def test_cadastro_completo_inicia_treino_automatico_e_sincroniza_estado(self):
        self.aba.banco.cadastrar("id", "João", [face_sintetica(0), face_sintetica(0, 1)])
        self.aba._cadastro_concluido((2, []))
        limite = time.monotonic() + 5
        while self.aba.ocupada and time.monotonic() < limite:
            self.root.update()
            self.aba._poll()
            time.sleep(.01)
        self.assertFalse(self.aba.ocupada)
        self.assertTrue(self.aba.motor.pronto)
        self.assertEqual(self.aba.btn_analisar.cget("text"), "Reconhecer rostos")
        self.assertIn("pronto", self.aba.status_var.get())
        self.assertEqual(float(self.aba.limiar_var.get()), self.aba.motor.limiar)

    def test_layout_faces_minimo_preserva_previews_e_tres_etapas(self):
        self.root.deiconify()
        self.root.geometry("1000x680")
        self.root.update()
        for canvas in self.aba.canvases:
            self.assertGreater(canvas.winfo_width(), 220)
            self.assertGreater(canvas.winfo_height(), 350)
        for aba in self.aba.abas_laterais.tabs():
            self.aba.abas_laterais.select(aba)
            self.root.update()
        self.assertTrue(self.aba.btn_analisar.winfo_ismapped())
        self.assertLess(self.aba.btn_analisar.winfo_rootx()+self.aba.btn_analisar.winfo_width(), self.root.winfo_rootx()+self.root.winfo_width()+1)

    def test_captura_descarta_amostras_se_camera_muda_ou_para(self):
        imagem = cv2.cvtColor(face_sintetica(0), cv2.COLOR_GRAY2BGR)
        self.aba.id_var.set("id")
        self.aba.nome_var.set("João")
        for alteracao in ("outra_camera", "arquivo", "pausa", "encerrada"):
            with self.subTest(alteracao=alteracao):
                fonte = SimpleNamespace(camera=True)
                video = SimpleNamespace(fonte=fonte, frame_original=imagem, reproduzindo=True, encerrada=False)
                with patch.object(self.aba, "_video_atual", return_value=video), patch.object(self.aba.motor, "detectar", return_value=[(0, 0, 128, 128)]):
                    self.aba.capturar_amostras()
                    self.assertEqual(len(self.aba._captura["faces"]), 1)
                    self.aba.after_cancel(self.aba._captura_id)
                    self.aba._captura_id = None
                    if alteracao == "outra_camera":
                        video.fonte = SimpleNamespace(camera=True)
                    elif alteracao == "arquivo":
                        fonte.camera = False
                    elif alteracao == "pausa":
                        video.reproduzindo = False
                    else:
                        video.encerrada = True
                    with patch.object(self.aba.banco, "cadastrar") as cadastrar:
                        self.aba._capturar_proxima()
                        cadastrar.assert_not_called()
                self.assertIsNone(self.aba._captura)
                self.assertIsNone(self.aba._captura_id)
                self.assertFalse(self.aba.ocupada)
                self.assertIn("Captura cancelada", self.aba.status_var.get())
                self.assertEqual(self.aba.banco.alunos, {})

    def test_treino_com_lock_do_motor_nao_bloqueia_tk_nem_acoes_de_foto(self):
        imagem = np.zeros((60, 80, 3), np.uint8)
        entrou, liberar, terminou = threading.Event(), threading.Event(), threading.Event()
        self.aba.ocupada = True
        def simular_treino():
            with self.aba.motor.lock:
                entrou.set()
                liberar.wait(timeout=3)
            terminou.set()
        worker = threading.Thread(target=simular_treino)
        worker.start()
        try:
            self.assertTrue(entrou.wait(timeout=1))
            self.aba.eventos.put_nowait([ResultadoFace(None, "Rosto detectado", float("nan"), (0, 0, 20, 20))])
            with patch("editor_faces.filedialog.askopenfilename") as dialogo, patch.object(self.aba.motor, "anotar") as anotar, patch.object(self.aba.motor, "definir_limiar") as definir:
                self.aba._atualizar_estado()
                self.aba.abrir_foto()
                self.aba.usar_editor()
                self.aba.usar_video()
                self.aba.analisar_atual()
                self.assertIsNone(self.aba.reconhecer_foto(imagem))
                np.testing.assert_array_equal(self.aba.anotar_frame(imagem), imagem)
                self.aba.aplicar_limiar()
                self.aba.treinar()
                self.aba._poll()
                ticks = []
                self.root.after(0, lambda: ticks.append("Tk disponível"))
                self.root.update()
                self.assertEqual(ticks, ["Tk disponível"])
                self.assertFalse(terminou.is_set(), "O Tk esperou o lock do treinamento ser liberado.")
                dialogo.assert_not_called()
                anotar.assert_not_called()
                definir.assert_not_called()
                self.assertTrue(self.aba.btn_abrir.instate(["disabled"]))
                self.assertIn("Aguarde", self.aba.status_var.get())
        finally:
            liberar.set()
            worker.join(timeout=1)
            self.aba.ocupada = False
        self.assertFalse(worker.is_alive())

    def test_reconhecer_foto_cancela_render_pendente_antes_de_renderizar_diretamente(self):
        imagem = np.zeros((50, 60, 3), np.uint8)
        self.aba._agendar_render()
        pendente = self.aba.resize_id
        self.assertIn(pendente, self.root.tk.call("after", "info"))
        with patch.object(self.aba, "anotar_frame", return_value=imagem.copy()):
            self.aba.reconhecer_foto(imagem)
        self.assertIsNone(self.aba.resize_id)
        self.assertNotIn(pendente, self.root.tk.call("after", "info"))
        self.aba.destroy()
        self.root.update()

    def test_falha_em_nova_foto_preserva_par_original_processada_anterior(self):
        anterior = np.full((50, 60, 3), 40, np.uint8)
        anotada = np.full((50, 60, 3), 70, np.uint8)
        with patch.object(self.aba.motor, "anotar", return_value=(anotada, [])):
            self.aba.reconhecer_foto(anterior)
        original_salva, processada_salva = self.aba.original, self.aba.processada
        nova = np.full((70, 80, 3), 190, np.uint8)
        with patch.object(self.aba.motor, "anotar", side_effect=ErroFaces("O cadastro mudou.")):
            with self.assertRaisesRegex(ErroFaces, "cadastro mudou"):
                self.aba.reconhecer_foto(nova)
        self.assertIs(self.aba.original, original_salva)
        self.assertIs(self.aba.processada, processada_salva)
        np.testing.assert_array_equal(self.aba.original, anterior)
        np.testing.assert_array_equal(self.aba.processada, anotada)

    def test_frame_em_processamento_nao_registra_em_chamada_criada_depois(self):
        imagem = np.zeros((50, 60, 3), np.uint8)
        for havia_chamada in (False, True):
            with self.subTest(havia_chamada=havia_chamada):
                anterior = self.aba.iniciar_chamada("Sessão anterior") if havia_chamada else None
                entrou, liberar = threading.Event(), threading.Event()
                falhas = []

                def anotar_bloqueado(_imagem):
                    entrou.set()
                    if not liberar.wait(timeout=4):
                        raise RuntimeError("O teste não liberou o reconhecimento.")
                    return imagem.copy(), [ResultadoFace("id", "João", 10.0)]

                def executar():
                    try:
                        self.aba.anotar_frame(imagem)
                    except Exception as exc:
                        falhas.append(exc)

                with patch.object(self.aba.motor, "anotar", side_effect=anotar_bloqueado):
                    worker = threading.Thread(target=executar)
                    worker.start()
                    try:
                        self.assertTrue(entrou.wait(timeout=2))
                        nova = self.aba.iniciar_chamada("Sessão nova")
                    finally:
                        liberar.set()
                        worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(falhas, [])
                self.assertEqual(nova.linhas(), [])
                if anterior is not None:
                    self.assertFalse(anterior.ativa)
                    self.assertEqual(anterior.linhas(), [])


if __name__ == "__main__":
    unittest.main()
