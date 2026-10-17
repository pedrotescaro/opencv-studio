"""Verifica integridade e separação do experimento sem rede nem fotos no Git."""
import unittest

import numpy as np

from studio.services.faces import ErroFaces
from preparar_faces_demo import (particionar, preparar_foto, selecionar_limiar,
                                 selecionar_limiar_com_limite, resumir, verificar_arquivo)


class DemonstracaoFacesTests(unittest.TestCase):
    def test_particoes_nao_vazam_fotos_ou_pessoas_desconhecidas(self):
        partes = particionar()
        conjuntos = [set(chaves) for chaves in partes.values()]
        self.assertEqual([len(item) for item in conjuntos], [180, 60, 50, 60, 50])
        for indice, conjunto in enumerate(conjuntos):
            for outro in conjuntos[indice + 1:]:
                self.assertFalse(conjunto & outro)
        self.assertEqual(len(set.union(*conjuntos)), 400)
        pessoas_treino = {s for s, _ in partes["treino"]}
        pessoas_cal = {s for s, _ in partes["calibracao_desconhecidos"]}
        pessoas_teste = {s for s, _ in partes["teste_desconhecidos"]}
        self.assertFalse(pessoas_treino & (pessoas_cal | pessoas_teste))
        self.assertFalse(pessoas_cal & pessoas_teste)

    def test_download_com_bytes_alterados_e_rejeitado(self):
        with self.assertRaisesRegex(ErroFaces, "SHA-256"):
            verificar_arquivo(b"arquivo incompleto ou modificado")

    def test_calibracao_escolhe_empate_mais_restritivo(self):
        conhecidos = [dict(esperado="A", previsto="A", distancia=40.0),
                      dict(esperado="B", previsto="B", distancia=50.0)]
        desconhecidos = [dict(esperado=None, previsto="A", distancia=70.0)]
        self.assertEqual(selecionar_limiar(conhecidos, desconhecidos), 50.0)
        with self.assertRaises(ErroFaces):
            selecionar_limiar([], desconhecidos)

    def test_resumo_contabiliza_falsas_aceitacoes_e_identidades_erradas(self):
        conhecidos = [dict(esperado="A", previsto="A", distancia=40),
                      dict(esperado="B", previsto="A", distancia=45),
                      dict(esperado="C", previsto="C", distancia=90)]
        desconhecidos = [dict(esperado=None, previsto="A", distancia=30),
                        dict(esperado=None, previsto="B", distancia=80)]
        resultado = resumir(conhecidos, desconhecidos, 60)
        self.assertEqual(resultado["conhecidos_corretos"], 1)
        self.assertEqual(resultado["conhecidos_rejeitados"], 1)
        self.assertEqual(resultado["conhecidos_identidade_errada"], 1)
        self.assertEqual(resultado["desconhecidos_rejeitados"], 1)
        self.assertEqual(resultado["desconhecidos_aceitos_incorretamente"], 1)

    def test_politica_alternativa_respeita_limite_de_falsa_aceitacao_calibracao(self):
        conhecidos = [dict(esperado="A", previsto="A", distancia=40),
                      dict(esperado="B", previsto="B", distancia=50),
                      dict(esperado="C", previsto="C", distancia=60)]
        desconhecidos = [dict(esperado=None, previsto="A", distancia=55)]
        self.assertEqual(selecionar_limiar_com_limite(conhecidos, desconhecidos, 0.04), 50)

    def test_distancia_zero_na_calibracao_preserva_limiar_positivo(self):
        conhecidos = [dict(esperado="A", previsto="A", distancia=0)]
        desconhecidos = [dict(esperado=None, previsto="A", distancia=70)]
        self.assertGreater(selecionar_limiar(conhecidos, desconhecidos), 0)

    def test_enquadramento_conserva_foto_e_adiciona_borda_explicita(self):
        foto = np.full((112, 92), 150, np.uint8)
        preparada = preparar_foto(foto)
        self.assertEqual(preparada.shape, (304, 264))
        self.assertTrue(np.all(preparada[:40] == 30))
        self.assertTrue(np.all(preparada[40:-40, 40:-40] == 150))


if __name__ == "__main__":
    unittest.main()
