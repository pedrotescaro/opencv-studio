"""Regressões de detecção livre e do cache LBPH real, sem medir acurácia humana."""
import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from editor_faces import BancoFaces, Chamada, MotorFaces, ResultadoFace, _layout_legenda, salvar_imagem
from tests.test_faces import face_sintetica


class PersistenciaFacesTests(unittest.TestCase):
    def setUp(self):
        self.temporario = tempfile.TemporaryDirectory()
        self.pasta = Path(self.temporario.name) / "Visão — João e Ágata"

    def tearDown(self):
        self.temporario.cleanup()

    def banco_completo(self, codigo="id-joão", nome="João da Visão", tipo=0):
        banco = BancoFaces(self.pasta)
        banco.cadastrar(codigo, nome, [face_sintetica(tipo, 0), face_sintetica(tipo, 1)])
        return banco

    def test_banco_vazio_detecta_anota_e_nao_marca_presenca(self):
        motor = MotorFaces(BancoFaces(self.pasta))
        imagem = cv2.cvtColor(face_sintetica(0), cv2.COLOR_GRAY2BGR)
        original = imagem.copy()
        with patch.object(motor, "detectar", return_value=[(0, 0, 128, 128)]):
            anotada, resultados = motor.anotar(imagem)
        np.testing.assert_array_equal(imagem, original)
        self.assertFalse(np.array_equal(anotada, imagem))
        self.assertEqual(resultados[0].nome, "Rosto detectado")
        self.assertEqual(resultados[0].modo, "deteccao")
        self.assertFalse(resultados[0].reconhecido)
        self.assertFalse(motor.pronto)
        chamada = Chamada("Aula", self.pasta / "chamadas")
        self.assertFalse(chamada.registrar(resultados[0]))
        self.assertEqual(chamada.linhas(), [])

    def test_legenda_cabe_em_foto_pequena_sem_perder_id_ou_distancia(self):
        resultado = ResultadoFace("DEMO-02", "Pessoa demonstração 02", 46.8, (35, 60, 192, 190))
        fonte, linhas, largura, altura, _, _ = _layout_legenda(resultado, 264)
        self.assertEqual(linhas, ["Pessoa demonstração 02", "DEMO-02 | d=46.8"])
        self.assertLessEqual(largura, 264)
        self.assertLess(altura, 264)
        self.assertGreaterEqual(fonte.size, 10)
        longo = ResultadoFace("DEMO-02", "Nome muito extenso " * 20, 46.8)
        _, linhas, largura, _, _, _ = _layout_legenda(longo, 120)
        self.assertTrue(linhas[0].endswith("…"))
        self.assertEqual("".join(linhas[1:]), "DEMO-02 | d=46.8")
        self.assertLessEqual(largura, 120)
        self.assertEqual(longo.nome, "Nome muito extenso " * 20)
        _, deteccao, largura, _, _, _ = _layout_legenda(ResultadoFace(None, "Rosto detectado", float("nan"), modo="deteccao"), 264)
        self.assertEqual(deteccao, ["Rosto detectado"])
        self.assertLessEqual(largura, 264)

    def test_primeira_identificacao_treina_e_proximos_frames_reusam(self):
        motor = MotorFaces(self.banco_completo())
        imagem = cv2.cvtColor(face_sintetica(0), cv2.COLOR_GRAY2BGR)
        with patch.object(motor, "treinar", wraps=motor.treinar) as treinar:
            with patch.object(motor, "detectar", return_value=[(0, 0, 128, 128)]):
                for _ in range(3):
                    self.assertEqual(motor.reconhecer(imagem)[0].codigo, "id-joão")
            self.assertEqual(treinar.call_count, 1)
        self.assertTrue(motor.pronto)

    def test_preparos_concorrentes_compartilham_um_unico_treino(self):
        motor = MotorFaces(self.banco_completo())
        with patch.object(motor, "treinar", wraps=motor.treinar) as treinar:
            with ThreadPoolExecutor(max_workers=4) as workers:
                resultados = list(workers.map(lambda _: motor.preparar_modelo(), range(4)))
            self.assertEqual(resultados, [True] * 4)
            self.assertEqual(treinar.call_count, 1)

    def test_cadastro_incompleto_e_lbph_indisponivel_preservam_deteccao(self):
        banco = BancoFaces(self.pasta)
        banco.cadastrar("id", "João", [face_sintetica(0)])
        motor = MotorFaces(banco)
        self.assertFalse(motor.preparar_modelo())
        self.assertIn("duas fotos", motor.status_modelo)
        banco.cadastrar("id", "João", [face_sintetica(0, 1)])
        imagem = cv2.cvtColor(face_sintetica(0), cv2.COLOR_GRAY2BGR)
        with patch("editor_faces.cv2.face", None):
            with patch.object(motor, "detectar", return_value=[(0, 0, 128, 128)]):
                self.assertEqual(motor.reconhecer(imagem)[0].modo, "deteccao")
        self.assertIn("opencv-contrib-python", motor.status_modelo)

    def test_modelo_real_salvo_unicode_reabre_sem_retreinar(self):
        primeiro = MotorFaces(self.banco_completo())
        primeiro.treinar()
        manifesto = json.loads(primeiro.arquivo_manifesto.read_text(encoding="utf-8"))
        self.assertEqual(manifesto["rotulos"], {"0": ["id-joão", "João da Visão"]})
        self.assertEqual(manifesto["modelo_sha256"], hashlib.sha256(primeiro.arquivo_modelo.read_bytes()).hexdigest())
        segundo = MotorFaces(BancoFaces(self.pasta))
        self.assertEqual(segundo.banco.revisao, 0)
        with patch.object(segundo, "treinar", side_effect=AssertionError("não deve retreinar")):
            self.assertTrue(segundo.preparar_modelo())
        self.assertTrue(segundo.pronto)
        resultado = segundo.prever_face(face_sintetica(0))
        self.assertEqual(resultado.codigo, "id-joão")
        self.assertEqual(resultado.nome, "João da Visão")
        self.assertLess(resultado.distancia, 1)
        self.assertIn("carregado", segundo.status_modelo)

    def test_limiar_calibrado_persiste_e_constructor_explicito_respeita_override(self):
        primeiro = MotorFaces(self.banco_completo())
        primeiro.treinar()
        primeiro.definir_limiar(61.2042)
        segundo = MotorFaces(BancoFaces(self.pasta))
        self.assertTrue(segundo.preparar_modelo())
        self.assertEqual(segundo.limiar, 61.2042)
        explicito = MotorFaces(BancoFaces(self.pasta), limiar=60)
        self.assertTrue(explicito.preparar_modelo())
        self.assertEqual(explicito.limiar, 60)
        primeiro.arquivo_config.write_text('{"versao": 1, "limiar_lbph": "nan"}', encoding="utf-8")
        corrompido = MotorFaces(BancoFaces(self.pasta))
        self.assertEqual(corrompido.limiar, 60)
        self.assertIn("restaurada", corrompido.status_modelo)

    def test_mesma_revisao_com_dataset_substituido_nao_carrega_identidade_antiga(self):
        anterior = MotorFaces(self.banco_completo())
        anterior.treinar()
        banco = BancoFaces(self.pasta)
        aluno = banco.alunos.pop("id-joão")
        banco.alunos["id-ágata"] = {"nome": "Ágata", "amostras": aluno["amostras"]}
        banco._salvar()
        novo = MotorFaces(BancoFaces(self.pasta))
        self.assertEqual(novo.banco.revisao, 0)
        with patch.object(novo, "treinar", wraps=novo.treinar) as treinar:
            self.assertTrue(novo.preparar_modelo())
            self.assertEqual(treinar.call_count, 1)
        self.assertEqual(novo.prever_face(face_sintetica(0)).codigo, "id-ágata")

    def test_troca_de_amostras_em_disco_invalida_hash_e_retreina(self):
        motor = MotorFaces(self.banco_completo())
        motor.treinar()
        fingerprint_anterior = motor.fingerprint_treinado
        for indice, arquivo in enumerate(motor.banco.alunos["id-joão"]["amostras"]):
            salvar_imagem(self.pasta / "amostras" / arquivo, face_sintetica(1, indice))
        self.assertFalse(motor.pronto)
        with patch.object(motor, "treinar", wraps=motor.treinar) as treinar:
            self.assertTrue(motor.preparar_modelo())
            self.assertEqual(treinar.call_count, 1)
        self.assertNotEqual(motor.fingerprint_treinado, fingerprint_anterior)
        self.assertEqual(motor.prever_face(face_sintetica(1)).codigo, "id-joão")

    def test_modelo_corrompido_e_manifesto_falso_recuperam_por_treino(self):
        for corromper_manifesto in (False, True):
            with self.subTest(corromper_manifesto=corromper_manifesto):
                banco = BancoFaces(self.pasta)
                if not banco.alunos:
                    banco = self.banco_completo()
                anterior = MotorFaces(banco)
                anterior.treinar()
                anterior.arquivo_modelo.write_bytes(b"modelo corrompido")
                if corromper_manifesto:
                    manifesto = json.loads(anterior.arquivo_manifesto.read_text(encoding="utf-8"))
                    manifesto["modelo_sha256"] = hashlib.sha256(b"modelo corrompido").hexdigest()
                    anterior.arquivo_manifesto.write_text(json.dumps(manifesto), encoding="utf-8")
                novo = MotorFaces(BancoFaces(self.pasta))
                with patch.object(novo, "treinar", wraps=novo.treinar) as treinar:
                    self.assertTrue(novo.preparar_modelo())
                    self.assertEqual(treinar.call_count, 1)
                self.assertEqual(novo.prever_face(face_sintetica(0)).codigo, "id-joão")

    def test_manifesto_de_alunos_editado_em_disco_atualiza_nome_e_treino(self):
        motor = MotorFaces(self.banco_completo())
        motor.treinar()
        externo = BancoFaces(self.pasta)
        externo.alunos["id-joão"]["nome"] = "João atualizado"
        externo._salvar()
        self.assertFalse(motor.pronto)
        self.assertTrue(motor.preparar_modelo())
        self.assertEqual(motor.prever_face(face_sintetica(0)).nome, "João atualizado")

    def test_foto_ausente_ou_cadastro_incompleto_voltam_a_deteccao(self):
        banco = self.banco_completo()
        motor = MotorFaces(banco)
        motor.treinar()
        arquivo = banco.alunos["id-joão"]["amostras"][0]
        (self.pasta / "amostras" / arquivo).unlink()
        imagem = cv2.cvtColor(face_sintetica(0), cv2.COLOR_GRAY2BGR)
        with patch.object(motor, "detectar", return_value=[(0, 0, 128, 128)]):
            self.assertEqual(motor.reconhecer(imagem)[0].modo, "deteccao")
        self.assertFalse(motor.pronto)
        self.assertIn("amostra", motor.status_modelo)


if __name__ == "__main__":
    unittest.main()
