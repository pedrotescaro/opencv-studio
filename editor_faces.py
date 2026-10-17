"""Cadastro local, reconhecimento LBPH e chamada deduplicada por matrícula.

O detector Haar apenas localiza faces. A identidade é estimada pelo LBPH treinado
com as amostras cadastradas; uma distância acima do limiar vira desconhecido.
Os dados são locais. O modelo é persistido com um manifesto do cadastro e das
amostras; uma base alterada é revalidada antes de qualquer identificação.
"""
import csv
import hashlib
import json
import math
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Empty, Full, Queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

from editor_interface import AbaFerramenta, CANVAS, FUNDO, VisualizacaoRedimensionavel, rolar_em


PASTA_PADRAO = Path(__file__).resolve().parent / ".dados_faces"
TIPOS_IMAGEM = [("Imagens", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"), ("Todos", "*.*")]


class ErroFaces(ValueError):
    """Erro de dados/configuração que pode ser mostrado diretamente ao usuário."""


def validar_imagem(imagem):
    if (not isinstance(imagem, np.ndarray) or imagem.dtype != np.uint8
            or imagem.ndim not in (2, 3) or not imagem.size
            or (imagem.ndim == 3 and imagem.shape[2] not in (3, 4))):
        raise ErroFaces("Use uma imagem de 8 bits em cinza, BGR ou BGRA.")
    return imagem


def ler_imagem(caminho):
    """imdecode permite nomes e pastas Unicode também no Windows."""
    try:
        imagem = cv2.imdecode(np.frombuffer(Path(caminho).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    except (OSError, cv2.error) as exc:
        raise ErroFaces(f"Não foi possível ler {Path(caminho).name}: {exc}") from exc
    if imagem is None:
        raise ErroFaces(f"O arquivo {Path(caminho).name} não é uma imagem válida.")
    return imagem


def salvar_imagem(caminho, imagem):
    caminho = Path(caminho)
    extensao = caminho.suffix.lower()
    if extensao not in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"):
        raise ErroFaces("Salve em PNG, JPEG, BMP, TIFF ou WebP.")
    try:
        ok, dados = cv2.imencode(extensao, validar_imagem(imagem))
        if not ok:
            raise ErroFaces("Não foi possível codificar a imagem.")
        caminho.write_bytes(dados.tobytes())
    except (OSError, cv2.error) as exc:
        raise ErroFaces(f"Não foi possível salvar a imagem: {exc}") from exc


def normalizar_face(face):
    validar_imagem(face)
    cinza = face if face.ndim == 2 else cv2.cvtColor(face, cv2.COLOR_BGRA2GRAY if face.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    return cv2.equalizeHist(cv2.resize(cinza, (128, 128), interpolation=cv2.INTER_AREA))


def _escrever_json(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(caminho)


def _assinatura_arquivo(caminho):
    """Metadados baratos para reaproveitar hashes entre frames de vídeo."""
    try:
        estado = caminho.stat()
        return estado.st_size, estado.st_mtime_ns, estado.st_ctime_ns
    except FileNotFoundError:
        return None


def _escrever_bytes(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(f".{caminho.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporario.write_bytes(dados)
        temporario.replace(caminho)
    finally:
        temporario.unlink(missing_ok=True)


class BancoFaces:
    """Persistência de IDs/nomes e recortes PNG; nunca usa o ID como caminho."""
    def __init__(self, pasta=None):
        self.pasta = Path(pasta) if pasta is not None else PASTA_PADRAO
        self.arquivo = self.pasta / "alunos.json"
        self.alunos = {}
        self.revisao = 0
        self.lock = threading.RLock()
        self._assinatura_manifesto = _assinatura_arquivo(self.arquivo)
        if self.arquivo.exists():
            self.alunos = self._ler_cadastro()

    def _ler_cadastro(self):
        """Valida também recargas de um cadastro editado fora desta instância."""
        if self.arquivo.exists():
            try:
                dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
                if not isinstance(dados, dict) or dados.get("versao") != 1 or not isinstance(dados["alunos"], dict):
                    raise ValueError("formato incompatível")
                for codigo, aluno in dados["alunos"].items():
                    if (not isinstance(codigo, str) or not codigo.strip() or not isinstance(aluno, dict)
                            or not isinstance(aluno.get("nome"), str) or not aluno["nome"].strip()
                            or not isinstance(aluno.get("amostras"), list)):
                        raise ValueError("cadastro inválido")
                    for nome in aluno["amostras"]:
                        if (not isinstance(nome, str) or Path(nome).name != nome
                                or "/" in nome or "\\" in nome or not nome.endswith(".png")):
                            raise ValueError("caminho de amostra inválido")
                return dados["alunos"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ErroFaces(f"Não foi possível carregar o cadastro {self.arquivo}: {exc}") from exc
        return {}

    def atualizar_do_disco(self):
        with self.lock:
            assinatura = _assinatura_arquivo(self.arquivo)
            if assinatura != self._assinatura_manifesto:
                alunos = self._ler_cadastro()
                if alunos != self.alunos:
                    self.alunos = alunos
                    self.revisao += 1
                self._assinatura_manifesto = assinatura

    def _salvar(self):
        _escrever_json(self.arquivo, {"versao": 1, "alunos": self.alunos})
        self._assinatura_manifesto = _assinatura_arquivo(self.arquivo)

    def cadastrar(self, codigo, nome, faces):
        """Adiciona recortes faciais distintos. A UI obtém cada recorte com Haar."""
        codigo, nome = str(codigo).strip(), str(nome).strip()
        if not codigo or not nome or len(codigo) > 80 or len(nome) > 160:
            raise ErroFaces("Informe matrícula/ID (até 80 caracteres) e nome (até 160).")
        if any(ord(c) < 32 for c in codigo + nome):
            raise ErroFaces("Matrícula e nome não podem conter quebras de linha ou caracteres de controle.")
        novas = [normalizar_face(face) for face in faces]
        if not novas:
            raise ErroFaces("Escolha ao menos uma foto para o cadastro.")
        with self.lock:
            existentes = self.alunos.get(codigo, {"nome": nome, "amostras": []})
            hashes = {hashlib.sha256(self.ler_amostra(n).tobytes()).digest() for n in existentes["amostras"]}
            unicas = []
            for face in novas:
                resumo = hashlib.sha256(face.tobytes()).digest()
                if resumo not in hashes:
                    hashes.add(resumo)
                    unicas.append(face)
            if not unicas:
                raise ErroFaces("As fotos selecionadas repetem amostras já cadastradas. Use fotos diferentes.")
            self.pasta.joinpath("amostras").mkdir(parents=True, exist_ok=True)
            arquivos = []
            try:
                for face in unicas:
                    arquivo = f"{uuid.uuid4().hex}.png"
                    salvar_imagem(self.pasta / "amostras" / arquivo, face)
                    arquivos.append(arquivo)
                anterior = self.alunos.get(codigo)
                self.alunos[codigo] = {"nome": nome, "amostras": existentes["amostras"] + arquivos}
                try:
                    self._salvar()
                except OSError:
                    if anterior is None:
                        del self.alunos[codigo]
                    else:
                        self.alunos[codigo] = anterior
                    raise
            except (OSError, ErroFaces):
                for arquivo in arquivos:
                    (self.pasta / "amostras" / arquivo).unlink(missing_ok=True)
                raise
            self.revisao += 1
            return len(unicas)

    def ler_amostra(self, nome):
        return cv2.cvtColor(ler_imagem(self.pasta / "amostras" / nome), cv2.COLOR_BGR2GRAY)

    def remover(self, codigo):
        with self.lock:
            if codigo not in self.alunos:
                raise ErroFaces("Selecione um aluno cadastrado.")
            aluno = self.alunos.pop(codigo)
            try:
                self._salvar()
            except OSError:
                self.alunos[codigo] = aluno
                raise
            self.revisao += 1
            for nome in aluno["amostras"]:
                (self.pasta / "amostras" / nome).unlink(missing_ok=True)


@dataclass(frozen=True)
class ResultadoFace:
    codigo: str | None
    nome: str
    distancia: float
    caixa: tuple | None = None
    modo: str = "identificacao"

    @property
    def reconhecido(self):
        return self.codigo is not None and self.modo == "identificacao"


def _fonte_legenda(tamanho):
    for caminho in ("C:/Windows/Fonts/segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(caminho, tamanho)
        except OSError:
            pass
    return ImageFont.load_default()


def _layout_legenda(resultado, largura_maxima, tamanho=13):
    """Organiza a legenda dentro da foto, sem alterar nome/ID nos resultados.

    O nome ocupa uma linha; uma elipse indica quando foi abreviado na imagem.
    IDs excepcionalmente longos podem ocupar mais linhas para manter os dados.
    """
    largura_maxima = max(1, int(largura_maxima))
    margem = min(4, max(0, largura_maxima // 20))
    disponivel = max(1, largura_maxima - 2 * margem)
    detalhes = (f"{resultado.codigo} | d={resultado.distancia:.1f}" if resultado.reconhecido
                else (f"d={resultado.distancia:.1f}" if resultado.modo != "deteccao" else ""))
    tamanho = max(10, int(tamanho))
    fonte = _fonte_legenda(tamanho)

    def largura(texto):
        caixa = fonte.getbbox(texto)
        return caixa[2] - caixa[0]

    while tamanho > 10 and max(largura(resultado.nome), largura(detalhes)) > disponivel:
        tamanho -= 1
        fonte = _fonte_legenda(tamanho)
    nome = resultado.nome
    if largura(nome) > disponivel:
        while nome and largura(nome + "…") > disponivel:
            nome = nome[:-1]
        nome = nome.rstrip() + "…" if largura("…") <= disponivel else ""
    linhas = [nome]
    if detalhes:
        linha = ""
        for caractere in detalhes:
            if linha and largura(linha + caractere) > disponivel:
                linhas.append(linha)
                linha = ""
            linha += caractere
        if linha:
            linhas.append(linha)
    caixa_linha = fonte.getbbox("Ágj")
    altura_linha = caixa_linha[3] - caixa_linha[1] + 3
    largura_caixa = min(largura_maxima, max((largura(linha) for linha in linhas), default=0) + 2 * margem)
    altura_caixa = len(linhas) * altura_linha + 2 * margem
    return fonte, linhas, largura_caixa, altura_caixa, altura_linha, margem


class MotorFaces:
    """Haar + LBPH, protegido para callbacks de vídeo em threads de exportação."""
    PARAMETROS = {"radius": 1, "neighbors": 8, "grid_x": 8, "grid_y": 8}
    NORMALIZACAO = "cinza-128x128-equalizeHist-v1"

    def __init__(self, banco, limiar=None):
        self.banco = banco
        self.lock = threading.RLock()
        self.modelo = None
        self.rotulos = {}
        self.revisao_treinada = -1
        self.arquivo_modelo = banco.pasta / "modelo_lbph.yml"
        self.arquivo_manifesto = banco.pasta / "modelo_lbph.json"
        self.arquivo_config = banco.pasta / "config_faces.json"
        self.fingerprint_treinado = None
        self._assinatura_dataset = self._dados_cache = None
        self._falha_preparo = None
        self.status_modelo = "Detecção pronta. Cadastre duas fotos distintas por pessoa para identificar."
        limiar_salvo = 60.0
        if limiar is None and self.arquivo_config.exists():
            try:
                config = json.loads(self.arquivo_config.read_text(encoding="utf-8"))
                limiar_salvo = float(config["limiar_lbph"])
                if config.get("versao") != 1 or not math.isfinite(limiar_salvo) or limiar_salvo <= 0:
                    raise ValueError("limiar inválido")
            except (OSError, ValueError, KeyError, TypeError):
                limiar_salvo = 60.0
                self.status_modelo += " A configuração de limiar foi restaurada para 60."
        self.definir_limiar(limiar_salvo if limiar is None else limiar, persistir=False)
        cascata = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        self.detector = cv2.CascadeClassifier(str(cascata))
        if self.detector.empty():
            raise ErroFaces("O detector Haar não foi encontrado na instalação do OpenCV.")

    @property
    def pronto(self):
        with self.lock, self.banco.lock:
            try:
                self._exigir_treino()
                return True
            except (ErroFaces, OSError):
                return False

    def _dados_dataset(self):
        """Hash do conteúdo e dos IDs; revisão numérica não basta após reabrir."""
        self.banco.atualizar_do_disco()
        alunos = self.banco.alunos
        cadastro = json.dumps(alunos, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        arquivos = [(codigo, nome) for codigo, aluno in sorted(alunos.items()) for nome in aluno["amostras"]]
        assinatura = (cadastro, self.banco.revisao, _assinatura_arquivo(self.banco.arquivo),
                      tuple((codigo, nome, _assinatura_arquivo(self.banco.pasta / "amostras" / nome))
                            for codigo, nome in arquivos))
        if assinatura == self._assinatura_dataset and self._dados_cache is not None:
            return self._dados_cache
        amostras, resumo = {}, hashlib.sha256()
        resumo.update(json.dumps({"parametros": self.PARAMETROS, "normalizacao": self.NORMALIZACAO,
                                  "alunos": alunos}, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        for codigo, nome in arquivos:
            try:
                conteudo = (self.banco.pasta / "amostras" / nome).read_bytes()
            except OSError as exc:
                raise ErroFaces(f"A amostra {nome} não está disponível. Reponha a foto ou refaça o cadastro.") from exc
            digest = hashlib.sha256(conteudo).hexdigest()
            amostras[nome] = digest
            resumo.update(json.dumps([codigo, nome, digest], ensure_ascii=False).encode("utf-8"))
        dados = {"fingerprint": resumo.hexdigest(), "amostras": amostras,
                 "total_amostras": len(arquivos), "total_pessoas": len(alunos)}
        self._assinatura_dataset, self._dados_cache = assinatura, dados
        return dados

    def _validar_cadastro_treinavel(self, dados):
        if not self.banco.alunos:
            raise ErroFaces("Cadastre ao menos uma pessoa com duas fotos distintas para identificar.")
        incompletos = [f"{aluno['nome']} ({codigo})" for codigo, aluno in self.banco.alunos.items()
                       if len({dados["amostras"][nome] for nome in aluno["amostras"]}) < 2]
        if incompletos:
            raise ErroFaces("Cada pessoa precisa de pelo menos duas fotos distintas. Complete: " + ", ".join(incompletos))

    def _criar_modelo(self):
        if not hasattr(cv2, "face") or not hasattr(cv2.face, "LBPHFaceRecognizer_create"):
            raise ErroFaces("LBPH não está disponível. Instale as dependências do projeto com opencv-contrib-python; não misture com opencv-python.")
        return cv2.face.LBPHFaceRecognizer_create(**self.PARAMETROS)

    def _persistir_modelo(self, dados):
        # FaceRecognizer.write(filename) não aceita FileStorage na API Python;
        # a implementação herdada de Algorithm aceita e preserva caminhos Unicode.
        armazenamento = cv2.FileStorage("modelo.yml", cv2.FILE_STORAGE_WRITE | cv2.FILE_STORAGE_MEMORY)
        try:
            cv2.Algorithm.write(self.modelo, armazenamento, "lbph")
            conteudo = armazenamento.releaseAndGetString().encode("utf-8")
        finally:
            armazenamento.release()
        manifesto = dict(versao=1, algoritmo="LBPH", parametros=self.PARAMETROS,
                          normalizacao=self.NORMALIZACAO, **dados,
                          rotulos={str(rotulo): list(pessoa) for rotulo, pessoa in self.rotulos.items()},
                          modelo_sha256=hashlib.sha256(conteudo).hexdigest())
        _escrever_bytes(self.arquivo_modelo, conteudo)
        _escrever_bytes(self.arquivo_manifesto, json.dumps(manifesto, ensure_ascii=False, indent=2).encode("utf-8"))

    def _carregar_modelo(self, dados):
        """Um cache ausente, incompatível ou corrompido apenas pede novo treino."""
        try:
            manifesto = json.loads(self.arquivo_manifesto.read_text(encoding="utf-8"))
            conteudo = self.arquivo_modelo.read_bytes()
            esperados = {rotulo: (codigo, aluno["nome"]) for rotulo, (codigo, aluno)
                         in enumerate(sorted(self.banco.alunos.items()))}
            if (manifesto.get("versao") != 1 or manifesto.get("algoritmo") != "LBPH"
                    or manifesto.get("parametros") != self.PARAMETROS
                    or manifesto.get("normalizacao") != self.NORMALIZACAO
                    or manifesto.get("fingerprint") != dados["fingerprint"]
                    or manifesto.get("amostras") != dados["amostras"]
                    or manifesto.get("total_amostras") != dados["total_amostras"]
                    or manifesto.get("total_pessoas") != dados["total_pessoas"]
                    or manifesto.get("modelo_sha256") != hashlib.sha256(conteudo).hexdigest()
                    or manifesto.get("rotulos") != {str(k): list(v) for k, v in esperados.items()}):
                return False
            armazenamento = cv2.FileStorage(conteudo.decode("utf-8"), cv2.FILE_STORAGE_READ | cv2.FILE_STORAGE_MEMORY)
            try:
                modelo = self._criar_modelo()
                cv2.Algorithm.read(modelo, armazenamento.getNode("lbph"))
            finally:
                armazenamento.release()
            labels = modelo.getLabels().reshape(-1)
            histogramas = modelo.getHistograms()
            tamanho_histograma = self.PARAMETROS["grid_x"] * self.PARAMETROS["grid_y"] * 2 ** self.PARAMETROS["neighbors"]
            if (modelo.empty() or len(labels) != dados["total_amostras"]
                    or len(histogramas) != len(labels)
                    or any(histograma.size != tamanho_histograma or not np.isfinite(histograma).all()
                           for histograma in histogramas)
                    or set(int(valor) for valor in labels) != set(esperados)
                    or (modelo.getRadius(), modelo.getNeighbors(), modelo.getGridX(), modelo.getGridY())
                    != tuple(self.PARAMETROS[chave] for chave in ("radius", "neighbors", "grid_x", "grid_y"))):
                return False
            self.modelo, self.rotulos = modelo, esperados
            self.fingerprint_treinado = dados["fingerprint"]
            self.revisao_treinada = self.banco.revisao
            self.status_modelo = f"Modelo salvo carregado: {dados['total_pessoas']} pessoa(s), {dados['total_amostras']} fotos."
            return True
        except (OSError, ValueError, KeyError, TypeError, AttributeError, SystemError, cv2.error):
            return False

    def preparar_modelo(self):
        """Reusa o treino, carrega o cache válido ou treina um cadastro completo.

        Sem cadastro completo continua possível detectar rostos. Não produz
        identidades nem presenças enquanto o modelo não estiver pronto.
        """
        with self.lock, self.banco.lock:
            try:
                dados = self._dados_dataset()
                self._validar_cadastro_treinavel(dados)
                if self._falha_preparo is not None and self._falha_preparo[0] == dados["fingerprint"]:
                    self.status_modelo = self._falha_preparo[1]
                    return False
                if self.modelo is not None and self.fingerprint_treinado == dados["fingerprint"]:
                    self.revisao_treinada = self.banco.revisao
                    return True
                self.modelo, self.rotulos = None, {}
                if self._carregar_modelo(dados):
                    return True
                self.treinar()
                return True
            except (ErroFaces, OSError, cv2.error) as exc:
                self.modelo, self.rotulos, self.fingerprint_treinado = None, {}, None
                self.revisao_treinada = -1
                self.status_modelo = f"Detecção de rostos ativa. {exc}"
                if "dados" in locals():
                    self._falha_preparo = dados["fingerprint"], self.status_modelo
                return False

    garantir_modelo = preparar_modelo

    def definir_limiar(self, valor, *, persistir=True):
        try:
            limiar = float(valor)
        except (TypeError, ValueError):
            raise ErroFaces("O limiar LBPH deve ser um número maior que zero.") from None
        if not math.isfinite(limiar) or limiar <= 0:
            raise ErroFaces("O limiar LBPH deve ser um número finito maior que zero.")
        with self.lock:
            self.limiar = limiar
            if persistir:
                try:
                    _escrever_bytes(self.arquivo_config, json.dumps({"versao": 1, "limiar_lbph": limiar}).encode("utf-8"))
                except OSError as exc:
                    self.status_modelo += f" Não foi possível guardar o limiar: {exc}"

    def treinar(self):
        with self.lock, self.banco.lock:
            modelo = self._criar_modelo()
            dados = self._dados_dataset()
            self._validar_cadastro_treinavel(dados)
            faces, rotulos, mapeamento = [], [], {}
            for rotulo, (codigo, aluno) in enumerate(sorted(self.banco.alunos.items())):
                mapeamento[rotulo] = (codigo, aluno["nome"])
                for arquivo in aluno["amostras"]:
                    faces.append(self.banco.ler_amostra(arquivo))
                    rotulos.append(rotulo)
            modelo.train(faces, np.asarray(rotulos, np.int32))
            self.modelo, self.rotulos = modelo, mapeamento
            self.revisao_treinada = self.banco.revisao
            self.fingerprint_treinado = dados["fingerprint"]
            self._falha_preparo = None
            self.status_modelo = f"Modelo treinado: {len(mapeamento)} pessoa(s), {len(faces)} fotos."
            try:
                self._persistir_modelo(dados)
            except (OSError, cv2.error) as exc:
                # O treino em memória continua utilizável, inclusive em pasta somente leitura.
                self.status_modelo += f" Não foi possível guardar o treino: {exc}"
            return len(faces), len(mapeamento)

    def _exigir_treino(self):
        if self.modelo is None:
            raise ErroFaces("Treine o modelo LBPH antes de reconhecer faces.")
        if self.revisao_treinada != self.banco.revisao:
            raise ErroFaces("O cadastro mudou. Treine novamente o modelo LBPH.")
        if self.fingerprint_treinado != self._dados_dataset()["fingerprint"]:
            raise ErroFaces("O cadastro mudou. Treine novamente o modelo LBPH.")

    def detectar(self, imagem):
        validar_imagem(imagem)
        cinza = imagem if imagem.ndim == 2 else cv2.cvtColor(imagem, cv2.COLOR_BGRA2GRAY if imagem.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
        fator = min(1.0, 1400 / max(cinza.shape))
        reduzida = cv2.resize(cinza, None, fx=fator, fy=fator, interpolation=cv2.INTER_AREA) if fator < 1 else cinza
        with self.lock:
            caixas = self.detector.detectMultiScale(cv2.equalizeHist(reduzida), scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        return [tuple(int(round(v / fator)) for v in caixa) for caixa in caixas]

    def prever_face(self, face, caixa=None):
        normalizada = normalizar_face(face)
        with self.lock, self.banco.lock:
            self._exigir_treino()
            rotulo, distancia = self.modelo.predict(normalizada)
            distancia = float(distancia)
            if rotulo in self.rotulos and math.isfinite(distancia) and distancia <= self.limiar:
                codigo, nome = self.rotulos[rotulo]
                return ResultadoFace(codigo, nome, distancia, caixa)
            return ResultadoFace(None, "Desconhecido", distancia, caixa)

    def reconhecer(self, imagem):
        validar_imagem(imagem)
        with self.lock, self.banco.lock:
            identificacao_pronta = self.preparar_modelo()
            resultados = []
            for x, y, w, h in self.detectar(imagem):
                if identificacao_pronta:
                    resultado = self.prever_face(imagem[y:y+h, x:x+w], (x, y, w, h))
                else:
                    resultado = ResultadoFace(None, "Rosto detectado", math.nan, (x, y, w, h), modo="deteccao")
                resultados.append(resultado)
            return resultados

    def anotar(self, imagem):
        resultados = self.reconhecer(imagem)
        bgr = cv2.cvtColor(imagem, cv2.COLOR_GRAY2BGR) if imagem.ndim == 2 else imagem[:, :, :3].copy()
        for resultado in resultados:
            x, y, w, h = resultado.caixa
            cor = (70, 180, 40) if resultado.reconhecido else ((210, 150, 35) if resultado.modo == "deteccao" else (40, 90, 230))
            cv2.rectangle(bgr, (x, y), (x+w, y+h), cor, 2)
        if resultados:
            pil = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            desenho = ImageDraw.Draw(pil)
            tamanho = max(13, min(24, round(min(imagem.shape[:2]) / 35)))
            for resultado in resultados:
                x, y, _, _ = resultado.caixa
                fonte, linhas, largura, altura, altura_linha, margem = _layout_legenda(resultado, pil.width, tamanho)
                esquerda = max(0, min(x, pil.width-largura))
                topo = max(0, min(y-altura, pil.height-altura))
                fundo = "#205d2d" if resultado.reconhecido else ("#186b94" if resultado.modo == "deteccao" else "#a83226")
                desenho.rectangle((esquerda, topo, min(pil.width-1, esquerda+largura-1), min(pil.height-1, topo+altura-1)), fill=fundo)
                for indice, linha in enumerate(linhas):
                    bbox = fonte.getbbox(linha)
                    desenho.text((esquerda+margem-bbox[0], topo+margem+indice*altura_linha-bbox[1]),
                                 linha, font=fonte, fill="white")
            bgr = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
        return bgr, resultados


class Chamada:
    """Uma primeira identificação por ID em cada sessão, persistida em JSON."""
    def __init__(self, nome="", pasta=None):
        self.codigo = uuid.uuid4().hex
        self.inicio = datetime.now().astimezone().isoformat(timespec="seconds")
        self.nome = str(nome).strip() or f"Aula {datetime.now():%d/%m/%Y %H:%M}"
        self.registros = {}
        self.ativa = True
        self.pasta = Path(pasta) if pasta is not None else PASTA_PADRAO / "chamadas"
        self.lock = threading.RLock()
        self._salvar()

    @property
    def caminho(self):
        return self.pasta / f"{self.codigo}.json"

    def _salvar(self):
        _escrever_json(self.caminho, dict(versao=1, codigo=self.codigo, nome=self.nome, inicio=self.inicio,
                                       ativa=self.ativa, registros=list(self.registros.values())))

    def registrar(self, resultado):
        with self.lock:
            if not self.ativa or not resultado.reconhecido or resultado.codigo in self.registros:
                return False
            registro = dict(id_aluno=resultado.codigo, nome=resultado.nome,
                            primeira_identificacao=datetime.now().astimezone().isoformat(timespec="seconds"),
                            distancia_lbph=round(resultado.distancia, 4))
            self.registros[resultado.codigo] = registro
            try:
                self._salvar()
            except OSError:
                del self.registros[resultado.codigo]
                raise
            return True

    def encerrar(self):
        with self.lock:
            anterior = self.ativa
            self.ativa = False
            try:
                self._salvar()
            except OSError:
                self.ativa = anterior
                raise

    def linhas(self):
        with self.lock:
            return [dict(registro) for registro in self.registros.values()]

    def exportar_csv(self, caminho):
        with self.lock:
            with Path(caminho).open("w", newline="", encoding="utf-8-sig") as arquivo:
                colunas = ("sessao", "id_aluno", "nome", "primeira_identificacao", "distancia_lbph")
                escritor = csv.DictWriter(arquivo, fieldnames=colunas, delimiter=";")
                escritor.writeheader()
                for registro in self.registros.values():
                    escritor.writerow(dict(sessao=self.nome, **registro))


class JanelaFaces(AbaFerramenta):
    """Área de trabalho facial; processamento em vídeo nunca acessa widgets Tk."""
    def __init__(self, parent, pasta=None):
        banco = BancoFaces(pasta)
        motor = MotorFaces(banco)
        pasta_pessoal = banco.pasta
        demonstracao = Path(__file__).resolve().parent / ".dados_faces_demo"
        if pasta is None and not banco.alunos and (demonstracao / "alunos.json").exists():
            try:
                dados_demo = json.loads((demonstracao / "relatorio.json").read_text(encoding="utf-8"))
                banco = BancoFaces(demonstracao)
                motor = MotorFaces(banco) if (demonstracao / "config_faces.json").exists() else MotorFaces(banco, limiar=dados_demo.get("limiar_lbph", 60))
            except (ErroFaces, OSError, ValueError, TypeError):
                banco = BancoFaces(pasta_pessoal)
                motor = MotorFaces(banco)
        super().__init__(parent, "Reconhecimento facial")
        self.encerrada = False
        self.poll_id = self.resize_id = None
        self._lock = threading.RLock()
        self.eventos = Queue(maxsize=2)
        self.tarefas = Queue()
        self.banco, self.motor = banco, motor
        self._pasta_pessoal = pasta_pessoal
        self.ocupada = False
        self._captura_id = None
        self._captura = None
        self.chamada = None
        self.original = self.processada = None
        self._fotos = []
        self.id_var, self.nome_var = tk.StringVar(), tk.StringVar()
        self.limiar_var, self.sessao_var = tk.StringVar(value="60"), tk.StringVar()
        self.base_var = tk.StringVar(value="Minha turma" if banco.pasta == pasta_pessoal else "Demonstração AT&T")
        self.status_var = tk.StringVar(value="Abra uma foto para detectar rostos. Cadastre pessoas para identificá-las automaticamente.")
        self.modelo_var = tk.StringVar(value="Detecção pronta · sem pessoas cadastradas")
        self.resumo_var = tk.StringVar(value="Nenhuma imagem aberta")
        self.cadastro_var = tk.StringVar(value="Nenhuma pessoa cadastrada")
        self.chamada_var = tk.StringVar(value="Nenhuma chamada iniciada.")
        self._montar()
        self._atualizar_cadastros()
        self._atualizar_estado()
        self.poll_id = self.after(250, self._poll)
        if self._cadastro_completo():
            self._preparar_automaticamente()

    def _montar(self):
        cabecalho = ttk.Frame(self, padding=(8, 4, 8, 12))
        integrado = self.editor is not None
        if not integrado:
            cabecalho.pack(fill="x")
        ttk.Label(cabecalho, text="Rostos e presença", style="Title.TLabel").pack(side="left")
        self.indicador_modelo = ttk.Label(cabecalho, textvariable=self.modelo_var, style="Muted.TLabel")
        self.indicador_modelo.pack(side="right", padx=(16, 0))
        barra = ttk.Frame(self, padding=(8, 0, 8, 8))
        barra.pack(fill="x")
        self.btn_abrir = ttk.Button(barra, text="Abrir foto", command=self.abrir_foto)
        self.btn_abrir.pack(side="left")
        self.btn_editor = ttk.Button(barra, text="Do editor", command=self.usar_editor)
        self.btn_editor.pack(side="left", padx=6)
        self.btn_video = ttk.Button(barra, text="Do vídeo", command=self.usar_video)
        self.btn_video.pack(side="left")
        self.btn_salvar = ttk.Button(barra, text="Salvar resultado", command=self.salvar_foto, state="disabled")
        self.btn_salvar.pack(side="left", padx=6)
        self.btn_analisar = ttk.Button(barra, text="Detectar rostos", command=self.analisar_atual, style="Accent.TButton")
        self.btn_analisar.pack(side="right")
        self.seletor_base = ttk.Combobox(barra, textvariable=self.base_var, values=("Minha turma", "Demonstração AT&T"), state="readonly", width=19)
        self.seletor_base.pack(side="right", padx=(8, 12))
        self.seletor_base.bind("<<ComboboxSelected>>", self._selecionar_base)
        rodape = ttk.Frame(self, padding=(8, 10, 8, 4))
        rodape.pack(side="bottom", fill="x")
        self.status_label = ttk.Label(rodape, textvariable=self.status_var, wraplength=1050)
        self.status_label.pack(fill="x")
        rodape.bind("<Configure>", lambda e: self.status_label.configure(wraplength=max(240, e.width-20)))
        self.visualizacao = VisualizacaoRedimensionavel(self, orient="horizontal")
        self.visualizacao.pack(fill="both", expand=True, padx=8)
        if integrado:
            # O cabeçalho global já identifica a ferramenta ativa.
            barra_visual = self.visualizacao.winfo_children()[0]
            for widget in barra_visual.winfo_children():
                if isinstance(widget, ttk.Label):
                    widget.configure(textvariable=self.modelo_var)
                    self.indicador_modelo = widget
                    break
        visual = self.visualizacao.visual
        visual.columnconfigure((0, 1), weight=1)
        visual.rowconfigure(1, weight=1)
        self.canvases = []
        for coluna, titulo in enumerate(("Imagem original", "Resultado")):
            ttk.Label(visual, text=titulo, style="Section.TLabel").grid(row=0, column=coluna, sticky="w", padx=10, pady=(4, 8))
            canvas = tk.Canvas(visual, bg=CANVAS, highlightthickness=0, width=260, height=240)
            canvas.grid(row=1, column=coluna, sticky="nsew", padx=(0, 6) if coluna == 0 else (6, 0))
            canvas.bind("<Configure>", self._agendar_render)
            self.canvases.append(canvas)
        ttk.Label(visual, textvariable=self.resumo_var, style="Muted.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(10, 4))
        lateral = self.visualizacao.controles
        lateral.configure(width=320)
        lateral.pack_propagate(False)
        self.abas_laterais = ttk.Notebook(lateral)
        self.abas_laterais.pack(fill="both", expand=True, padx=(10, 0))
        painel, modelo, chamada = (self._painel_lateral(nome) for nome in ("Cadastro", "Modelo", "Chamada"))
        ttk.Label(painel, text="Matrícula ou ID").pack(anchor="w")
        ttk.Entry(painel, textvariable=self.id_var).pack(fill="x")
        ttk.Label(painel, text="Nome").pack(anchor="w", pady=(6, 0))
        ttk.Entry(painel, textvariable=self.nome_var).pack(fill="x")
        self.btn_importar = ttk.Button(painel, text="Adicionar fotos da pessoa", command=self.adicionar_fotos, style="Accent.TButton")
        self.btn_importar.pack(fill="x", pady=(8, 4))
        self.btn_capturar = ttk.Button(painel, text="Capturar amostras da câmera", command=self.capturar_amostras)
        self.btn_capturar.pack(fill="x", pady=(0, 4))
        ttk.Label(painel, text="Uma pessoa por foto. Duas fotos distintas iniciam o treino.", wraplength=265, style="Muted.TLabel").pack(anchor="w", pady=(4, 8))
        ttk.Label(painel, textvariable=self.cadastro_var, style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        self.cadastros = ttk.Treeview(painel, columns=("nome", "qtd"), show="headings", height=2, selectmode="browse")
        self.cadastros.heading("nome", text="Pessoa / ID")
        self.cadastros.heading("qtd", text="Fotos")
        self.cadastros.column("nome", width=210, minwidth=100)
        self.cadastros.column("qtd", width=48, minwidth=40, stretch=False)
        self.cadastros.pack(fill="both", expand=True)
        self.cadastros.bind("<<TreeviewSelect>>", self._selecionar)
        self.btn_remover = ttk.Button(painel, text="Remover selecionado", command=self.remover_aluno)
        self.btn_remover.pack(fill="x", pady=(8, 0))
        ttk.Label(modelo, text="Identificação automática", style="Section.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Label(modelo, text="Treino automático e salvo neste computador.", wraplength=265, style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        self.btn_treinar = ttk.Button(modelo, text="Atualizar treinamento", command=self.treinar)
        self.btn_treinar.pack(fill="x")
        self.progresso = ttk.Progressbar(modelo, mode="indeterminate", length=200)
        self.progresso.pack(fill="x", pady=(6, 4))
        ttk.Label(modelo, text="Rejeitar desconhecidos", style="Section.TLabel").pack(anchor="w", pady=(4, 6))
        linha = ttk.Frame(modelo)
        linha.pack(fill="x", pady=(0, 6))
        ttk.Label(linha, text="Distância máx.").pack(side="left")
        ttk.Entry(linha, textvariable=self.limiar_var, width=7).pack(side="left", padx=5)
        self.btn_limiar = ttk.Button(linha, text="Aplicar", command=self.aplicar_limiar, padding=(8, 5))
        self.btn_limiar.pack(side="right")
        ttk.Label(modelo, text="Menor = mais exigente. A distância não é uma porcentagem de confiança.", wraplength=265, style="Muted.TLabel").pack(anchor="w", pady=(4, 8))
        ttk.Label(modelo, text="Demonstração AT&T", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(modelo, text="Escolha a base na barra superior e experimente uma foto reservada para teste.", wraplength=265, style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Button(modelo, text="Testar foto da demonstração", command=self.testar_demonstracao).pack(fill="x", pady=(6, 0))
        ttk.Label(modelo, text="Identidades de estudo; seu cadastro fica separado.", wraplength=265, style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Label(chamada, text="Presença nesta aula", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(chamada, text="Nome da sessão").pack(anchor="w")
        ttk.Entry(chamada, textvariable=self.sessao_var).pack(fill="x")
        ttk.Button(chamada, text="Iniciar chamada", command=lambda: self._acao(lambda: self.iniciar_chamada(self.sessao_var.get())), style="Accent.TButton").pack(fill="x", pady=(10, 4))
        ttk.Button(chamada, text="Encerrar chamada", command=lambda: self._acao(self.encerrar_chamada)).pack(fill="x")
        ttk.Label(chamada, textvariable=self.chamada_var, wraplength=265, style="Muted.TLabel").pack(anchor="w", pady=12)
        self.tabela = ttk.Treeview(chamada, columns=("nome", "hora"), show="headings", height=2)
        self.tabela.heading("nome", text="Presença / ID")
        self.tabela.heading("hora", text="Horário")
        self.tabela.column("nome", width=165, minwidth=100)
        self.tabela.column("hora", width=72, minwidth=60, stretch=False)
        self.tabela.pack(fill="both", expand=True)
        ttk.Button(chamada, text="Exportar CSV", command=self.exportar_csv).pack(fill="x", pady=(10, 6))
        ttk.Label(chamada, text="Cada ID entra uma vez. Confira os registros antes de usar a chamada.", wraplength=265, style="Muted.TLabel").pack(anchor="w")

    def _painel_lateral(self, titulo):
        """Rolagem local aparece apenas quando a altura disponível exige."""
        container = ttk.Frame(self.abas_laterais)
        self.abas_laterais.add(container, text=titulo)
        canvas = tk.Canvas(container, bg=FUNDO, highlightthickness=0, width=280, height=160)
        barra = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=barra.set)
        painel = ttk.Frame(canvas, padding=(10, 10, 10, 8))
        item = canvas.create_window((0, 0), window=painel, anchor="nw")
        def ajustar(_evento=None):
            largura, altura = canvas.winfo_width(), canvas.winfo_height()
            precisa = painel.winfo_reqheight() > altura
            if precisa and not barra.winfo_manager():
                barra.pack(side="right", fill="y")
            elif not precisa and barra.winfo_manager():
                barra.pack_forget()
                canvas.yview_moveto(0)
            canvas.itemconfigure(item, width=max(1, largura), height=max(altura, painel.winfo_reqheight()))
            for widget in painel.winfo_children():
                if isinstance(widget, ttk.Label) and int(widget.cget("wraplength") or 0):
                    widget.configure(wraplength=max(120, largura-24))
            canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.bind("<Configure>", ajustar)
        painel.bind("<Configure>", ajustar)
        rolar_em(self.winfo_toplevel(), container, canvas)
        return painel

    def _acao(self, funcao):
        try:
            return funcao()
        except (ErroFaces, OSError, cv2.error) as exc:
            self._mostrar_erro(str(exc))
            return None

    def _mostrar_erro(self, texto):
        self.status_var.set(texto)
        self.status_label.configure(foreground="#b33c2e")

    def _informar(self, texto):
        self.status_label.configure(foreground="#203047")
        self.status_var.set(texto)

    def _aguardar_processamento(self):
        if self.ocupada:
            self._informar("Aguarde o processamento atual terminar. A interface continua disponível.")
            return True
        return False

    def _cadastro_completo(self):
        return bool(self.banco.alunos) and all(len(a["amostras"]) >= 2 for a in self.banco.alunos.values())

    def _atualizar_estado(self):
        # O treino mantém o lock do motor; a thread do Tk nunca o espera.
        pronto = False if self.ocupada else self.motor.pronto
        total = len(self.banco.alunos)
        fotos = sum(len(a["amostras"]) for a in self.banco.alunos.values())
        if self.ocupada:
            texto = "Preparando identificação…"
        elif pronto:
            texto = f"Identificação pronta · {total} pessoa(s)"
        elif total:
            texto = "Detecção pronta · complete o cadastro"
        else:
            texto = "Detecção pronta · cadastre para identificar"
        if self.banco.pasta != self._pasta_pessoal:
            texto = "Demonstração · " + texto.lower()
        self.modelo_var.set(texto)
        self.cadastro_var.set(f"{total} pessoa(s) · {fotos} amostra(s)" if total else "Seu cadastro está vazio")
        self.btn_analisar.configure(text="Reconhecer rostos" if pronto else "Detectar rostos", state="disabled" if self.ocupada else "normal")
        self.btn_treinar.configure(state="normal" if self._cadastro_completo() and not self.ocupada else "disabled")
        self.btn_importar.configure(state="disabled" if self.ocupada else "normal")
        self.btn_importar.configure(text="Cadastrar na minha turma" if self.banco.pasta != self._pasta_pessoal else "Adicionar fotos da pessoa")
        self.btn_remover.configure(state="normal" if not self.ocupada and self.banco.pasta == self._pasta_pessoal else "disabled")
        self.btn_capturar.configure(text="Cancelar captura" if self._captura is not None else "Capturar amostras da câmera",
                                  state="normal" if self._captura is not None or not self.ocupada else "disabled")
        self.btn_salvar.configure(state="normal" if self.processada is not None else "disabled")
        self.seletor_base.configure(state="disabled" if self.ocupada else "readonly")
        for botao in (self.btn_abrir, self.btn_editor, self.btn_video, self.btn_limiar):
            botao.configure(state="disabled" if self.ocupada else "normal")

    def _trabalhar(self, funcao, concluida):
        """O worker só toca dados; a fila entrega o resultado à thread do Tk."""
        if self.ocupada:
            self._informar("Aguarde o processamento atual terminar.")
            return False
        self.ocupada = True
        self.progresso.start(12)
        self._atualizar_estado()
        def executar():
            try:
                self.tarefas.put(("concluida", concluida, funcao()))
            except Exception as exc:
                self.tarefas.put(("erro", str(exc)))
        threading.Thread(target=executar, daemon=True).start()
        return True

    def _preparar_automaticamente(self):
        self._informar("Preparando o reconhecimento com as fotos cadastradas…")
        self._trabalhar(self.motor.preparar_modelo, self._treino_concluido)

    def _treino_concluido(self, pronto):
        self.limiar_var.set(str(self.motor.limiar))
        self._atualizar_estado()
        if pronto:
            self._informar("Modelo pronto. Abra uma foto diferente das usadas no cadastro para testar a identificação.")
            foto_demo = Path(__file__).resolve().parent / ".dados_faces_demo" / "teste" / "pessoa_02_09.png"
            if self.banco.pasta != self._pasta_pessoal and self.original is None and foto_demo.exists():
                self.testar_demonstracao()
        else:
            self._informar("A detecção está disponível. Adicione duas fotos distintas por pessoa para identificar nomes.")

    def _atualizar_cadastros(self):
        self.cadastros.delete(*self.cadastros.get_children())
        for numero, (codigo, aluno) in enumerate(sorted(self.banco.alunos.items())):
            self.cadastros.insert("", "end", iid=str(numero), values=(f"{aluno['nome']} [{codigo}]", len(aluno["amostras"])), tags=(codigo,))
        self._atualizar_estado()

    def _selecionar(self, _evento=None):
        selecionados = self.cadastros.selection()
        if selecionados:
            codigo = self.cadastros.item(selecionados[0], "tags")[0]
            self.id_var.set(codigo)
            self.nome_var.set(self.banco.alunos[codigo]["nome"])

    def adicionar_fotos(self):
        def executar():
            if self.banco.pasta != self._pasta_pessoal:
                if self._trocar_base(self._pasta_pessoal):
                    self._informar("Seu cadastro pessoal está aberto. Informe matrícula/ID e nome, depois adicione as fotos.")
                return
            if not self.id_var.get().strip() or not self.nome_var.get().strip():
                raise ErroFaces("Informe matrícula/ID e nome antes de escolher as fotos.")
            if self.ocupada:
                return
            arquivos = filedialog.askopenfilenames(parent=self, title="Fotos do aluno: uma face por imagem", filetypes=TIPOS_IMAGEM)
            if not arquivos:
                return
            codigo, nome = self.id_var.get().strip(), self.nome_var.get().strip()
            banco, motor = self.banco, self.motor
            def importar():
                recortes, ignoradas = [], []
                for indice, caminho in enumerate(arquivos, 1):
                    self.tarefas.put(("progresso", f"Lendo foto {indice} de {len(arquivos)}…"))
                    try:
                        imagem = ler_imagem(caminho)
                        caixas = motor.detectar(imagem)
                        if len(caixas) != 1:
                            ignoradas.append(f"{Path(caminho).name}: {len(caixas)} rostos")
                            continue
                        x, y, w, h = caixas[0]
                        recortes.append(imagem[y:y+h, x:x+w].copy())
                    except (ErroFaces, OSError, cv2.error):
                        ignoradas.append(f"{Path(caminho).name}: arquivo inválido")
                if not recortes:
                    raise ErroFaces("Nenhuma foto aproveitada. Use uma pessoa de frente por foto. " + "; ".join(ignoradas[:2]))
                quantidade = banco.cadastrar(codigo, nome, recortes)
                return quantidade, ignoradas
            self._informar(f"Preparando {len(arquivos)} foto(s) de {nome}…")
            self._trabalhar(importar, self._cadastro_concluido)
        self._acao(executar)

    def _cadastro_concluido(self, resultado):
        quantidade, ignoradas = resultado
        self._atualizar_cadastros()
        texto = f"{quantidade} amostra(s) adicionada(s)."
        if ignoradas:
            texto += f" {len(ignoradas)} foto(s) ignorada(s): " + "; ".join(ignoradas[:2])
        self._informar(texto)
        if self._cadastro_completo():
            self._preparar_automaticamente()
        else:
            self._informar(texto + " Complete duas fotos distintas por pessoa para iniciar o treino automático.")

    def _video_atual(self):
        app = getattr(self.winfo_toplevel(), "_editor_app", None)
        paginas = getattr(app, "paginas", {})
        video = paginas.get("Vídeo")
        if video is None:
            video = next((p for p in paginas.values() if hasattr(p, "frame_original")), None)
        return video

    def capturar_amostras(self):
        """Coleta imagens da câmera já aberta; não disputa outro VideoCapture."""
        if self._captura is not None:
            self._cancelar_captura()
            self._informar("Captura cancelada. Nenhuma amostra foi adicionada.")
            return
        def iniciar():
            if self.ocupada:
                return
            if self.banco.pasta != self._pasta_pessoal:
                if self._trocar_base(self._pasta_pessoal):
                    self._informar("Seu cadastro pessoal está aberto. Informe matrícula/ID e nome antes de capturar.")
                return
            codigo, nome = self.id_var.get().strip(), self.nome_var.get().strip()
            if not codigo or not nome:
                raise ErroFaces("Informe matrícula/ID e nome antes de capturar.")
            video = self._video_atual()
            if video is None or getattr(video, "frame_original", None) is None:
                raise ErroFaces("Abra sua câmera na aba Vídeo, deixe a reprodução ativa e volte aqui para capturar amostras.")
            fonte = getattr(video, "fonte", None)
            if fonte is None or not getattr(fonte, "camera", False):
                raise ErroFaces("Use uma câmera ao vivo na aba Vídeo para cadastrar amostras.")
            if not getattr(video, "reproduzindo", False):
                raise ErroFaces("Inicie a reprodução da câmera na aba Vídeo antes de capturar amostras.")
            self.ocupada = True
            self._captura = dict(codigo=codigo, nome=nome, video=video, fonte=fonte, faces=[], tentativas=0)
            self._atualizar_estado()
            self._informar("Capturando: olhe para a câmera e varie levemente a posição. 0 de 12 amostras.")
            self._capturar_proxima()
        self._acao(iniciar)

    def _cancelar_captura(self):
        if self._captura_id:
            self.after_cancel(self._captura_id)
            self._captura_id = None
        self._captura = None
        self.ocupada = False
        self._atualizar_estado()

    def _capturar_proxima(self):
        self._captura_id = None
        dados = self._captura
        if self.encerrada or dados is None:
            return
        video = dados["video"]
        fonte = getattr(video, "fonte", None)
        if (fonte is not dados["fonte"] or not getattr(fonte, "camera", False)
                or not getattr(video, "reproduzindo", False) or getattr(video, "encerrada", False)):
            self._cancelar_captura()
            self._mostrar_erro("Captura cancelada: a câmera parou ou a fonte mudou. Nenhuma amostra foi cadastrada. Reinicie a câmera e tente novamente.")
            return
        frame = getattr(video, "frame_original", None)
        dados["tentativas"] += 1
        if frame is not None:
            try:
                caixas = self.motor.detectar(frame)
                if len(caixas) == 1:
                    x, y, w, h = caixas[0]
                    recorte = normalizar_face(frame[y:y+h, x:x+w])
                    if not any(np.array_equal(recorte, anterior) for anterior in dados["faces"]):
                        dados["faces"].append(recorte)
            except (ErroFaces, cv2.error):
                pass
        quantidade = len(dados["faces"])
        self._informar(f"Capturando {dados['nome']}: {quantidade} de 12 amostras. Varie levemente o rosto e a iluminação.")
        if quantidade >= 12 or dados["tentativas"] >= 32:
            self._captura = None
            self.ocupada = False
            self._atualizar_estado()
            if quantidade < 2:
                self._mostrar_erro("A captura precisa de duas imagens distintas com um rosto visível. Mantenha a câmera reproduzindo na aba Vídeo e tente novamente.")
                return
            banco = self.banco
            self._trabalhar(lambda: (banco.cadastrar(dados["codigo"], dados["nome"], dados["faces"]), []), self._cadastro_concluido)
        else:
            self._captura_id = self.after(450, self._capturar_proxima)

    def remover_aluno(self):
        def executar():
            if self.banco.pasta != self._pasta_pessoal:
                raise ErroFaces("A base de demonstração é preservada. Escolha Minha turma para editar seus cadastros.")
            if self.ocupada:
                raise ErroFaces("Aguarde o processamento atual antes de remover um cadastro.")
            selecionados = self.cadastros.selection()
            if not selecionados:
                raise ErroFaces("Selecione um aluno na tabela do cadastro.")
            codigo = self.cadastros.item(selecionados[0], "tags")[0]
            if messagebox.askyesno("Remover cadastro", f"Remover {self.banco.alunos[codigo]['nome']} e suas fotos locais?", parent=self):
                self.banco.remover(codigo)
                self._atualizar_cadastros()
                if self._cadastro_completo():
                    self._preparar_automaticamente()
                else:
                    self._informar("Cadastro removido. A detecção de rostos continua disponível.")
        self._acao(executar)

    def treinar(self):
        if self._aguardar_processamento():
            return
        def executar():
            self.motor.definir_limiar(self.limiar_var.get().replace(",", "."))
            if not self._cadastro_completo():
                raise ErroFaces("Adicione duas fotos distintas por pessoa na aba Cadastro. A detecção funciona desde já.")
            self._informar("Treinando o modelo com as amostras cadastradas…")
            def treinar():
                self.motor.treinar()
                return True
            self._trabalhar(treinar, self._treino_concluido)
        self._acao(executar)

    def aplicar_limiar(self):
        if self._aguardar_processamento():
            return
        def executar():
            self.motor.definir_limiar(self.limiar_var.get().replace(",", "."))
            self._informar(f"Distância máxima atualizada: {self.motor.limiar:g}. Analise novamente a foto para aplicar.")
        self._acao(executar)

    def _trocar_base(self, pasta, limiar=None):
        if self.ocupada:
            self._informar("Aguarde o processamento atual antes de trocar a base.")
            return False
        banco = BancoFaces(pasta)
        motor = MotorFaces(banco, limiar=limiar)
        with self._lock:
            if self.chamada is not None and self.chamada.ativa:
                self.chamada.encerrar()
            self.banco, self.motor = banco, motor
        self.id_var.set("")
        self.nome_var.set("")
        self.original = self.processada = None
        self.resumo_var.set("Nenhuma imagem aberta")
        self.limiar_var.set(str(motor.limiar))
        self.base_var.set("Minha turma" if banco.pasta == self._pasta_pessoal else "Demonstração AT&T")
        self._atualizar_cadastros()
        self._atualizar_chamada()
        self._atualizar_estado()
        self._renderizar()
        if self._cadastro_completo():
            self._preparar_automaticamente()
        else:
            self._informar("Seu cadastro está aberto. Adicione fotos para identificar pessoas.")
        return True

    def carregar_demonstracao(self):
        def executar():
            pasta = Path(__file__).resolve().parent / ".dados_faces_demo"
            if not (pasta / "alunos.json").exists():
                raise ErroFaces("Prepare a base pública com: python preparar_faces_demo.py. Depois clique em Carregar base de demonstração.")
            relatorio = pasta / "relatorio.json"
            limiar = None
            if not (pasta / "config_faces.json").exists():
                limiar = json.loads(relatorio.read_text(encoding="utf-8")).get("limiar_lbph", 60) if relatorio.exists() else 60
            self._trocar_base(pasta, limiar)
        self._acao(executar)

    def voltar_cadastro(self):
        self._acao(lambda: self._trocar_base(self._pasta_pessoal))

    def _selecionar_base(self, _evento=None):
        if self.base_var.get() == "Minha turma":
            self.voltar_cadastro()
        else:
            self.carregar_demonstracao()
        self.base_var.set("Minha turma" if self.banco.pasta == self._pasta_pessoal else "Demonstração AT&T")

    def testar_demonstracao(self):
        caminho = Path(__file__).resolve().parent / ".dados_faces_demo" / "teste" / "pessoa_02_09.png"
        if self.banco.pasta == self._pasta_pessoal:
            self._mostrar_erro("Carregue a base de demonstração primeiro para reconhecer as identidades de estudo.")
            return
        if self.ocupada:
            self._informar("Aguarde a preparação da demonstração terminar.")
            return
        self._acao(lambda: self.reconhecer_foto(ler_imagem(caminho)))

    def anotar_frame(self, frame):
        """Callback BGR→BGR para vídeo/câmera, seguro fora da thread do Tk.

        Registra presenças somente quando existe chamada ativa. Não altera frame.
        Falhas de treino/dados são propagadas para o chamador exibir/interromper.
        """
        if self.encerrada:
            raise ErroFaces("A aba de reconhecimento facial foi encerrada. Abra-a novamente.")
        if self.ocupada:
            # O preview de vídeo também passa por este callback na thread Tk.
            return validar_imagem(frame).copy()
        with self._lock:
            chamada_do_frame = self.chamada
            motor_do_frame = self.motor
        anotada, resultados = motor_do_frame.anotar(frame)
        with self._lock:
            if (chamada_do_frame is not None and self.chamada is chamada_do_frame
                    and chamada_do_frame.ativa):
                for resultado in resultados:
                    chamada_do_frame.registrar(resultado)
        try:
            self.eventos.put_nowait(resultados)
        except Full:
            pass
        return anotada

    def reconhecer_foto(self, imagem):
        if self._aguardar_processamento():
            return None
        original = validar_imagem(imagem).copy()
        processada = self.anotar_frame(imagem)
        self.original, self.processada = original, processada
        self.resumo_var.set(f"{original.shape[1]} × {original.shape[0]} px · {'Identificação LBPH' if self.motor.pronto else 'Detecção de rostos'}")
        self._atualizar_estado()
        self._renderizar()
        return self.processada

    def analisar_atual(self):
        if self._aguardar_processamento():
            return
        if self.original is None:
            self.abrir_foto()
        else:
            self._acao(lambda: self.reconhecer_foto(self.original))

    def abrir_foto(self):
        if self._aguardar_processamento():
            return
        caminho = filedialog.askopenfilename(parent=self, title="Reconhecer em foto", filetypes=TIPOS_IMAGEM)
        if caminho:
            self._acao(lambda: self.reconhecer_foto(ler_imagem(caminho)))

    def usar_editor(self):
        if self._aguardar_processamento():
            return
        def executar():
            imagem = getattr(getattr(self.winfo_toplevel(), "_editor_app", None), "atual", None)
            if imagem is None:
                raise ErroFaces("Abra uma imagem no editor ou use Abrir foto nesta aba.")
            self.reconhecer_foto(imagem)
        self._acao(executar)

    def usar_video(self):
        if self._aguardar_processamento():
            return
        def executar():
            video = self._video_atual()
            imagem = getattr(video, "frame_original", None)
            if imagem is None:
                raise ErroFaces("Abra um vídeo ou uma câmera na aba Vídeo e tente novamente.")
            self.reconhecer_foto(imagem)
        self._acao(executar)

    def salvar_foto(self):
        if self.processada is None:
            self._mostrar_erro("Abra e analise uma foto antes de salvar o resultado.")
            return
        caminho = filedialog.asksaveasfilename(parent=self, title="Salvar foto anotada", defaultextension=".png", filetypes=TIPOS_IMAGEM)
        if caminho:
            self._acao(lambda: salvar_imagem(caminho, self.processada))

    def iniciar_chamada(self, nome=None):
        with self._lock:
            if self.chamada is not None and self.chamada.ativa:
                self.chamada.encerrar()
            self.chamada = Chamada(nome or "", self.banco.pasta / "chamadas")
        self._atualizar_chamada()
        self._informar("Chamada iniciada. As pessoas reconhecidas em fotos ou na aba Vídeo entram automaticamente.")
        return self.chamada

    def encerrar_chamada(self):
        with self._lock:
            if self.chamada is None:
                raise ErroFaces("Inicie uma chamada primeiro.")
            self.chamada.encerrar()
        self._atualizar_chamada()
        self._informar("Chamada encerrada e salva neste computador. O CSV está disponível para exportação.")

    def _atualizar_chamada(self):
        with self._lock:
            if self.chamada is None:
                return
            linhas = self.chamada.linhas()
            self.chamada_var.set(f"{self.chamada.nome} · {'Em andamento' if self.chamada.ativa else 'Encerrada'} · {len(linhas)} presente(s)")
        self.tabela.delete(*self.tabela.get_children())
        for registro in linhas:
            self.tabela.insert("", "end", values=(f"{registro['nome']} [{registro['id_aluno']}]", registro["primeira_identificacao"][11:19]))

    def exportar_csv(self):
        if self.chamada is None:
            self._mostrar_erro("Inicie uma chamada antes de exportar.")
            return
        caminho = filedialog.asksaveasfilename(parent=self, title="Exportar chamada", defaultextension=".csv", initialfile="chamada.csv", filetypes=[("CSV", "*.csv")])
        if caminho:
            self._acao(lambda: self.chamada.exportar_csv(caminho))

    def _poll(self):
        if self.poll_id:
            self.after_cancel(self.poll_id)
        self.poll_id = None
        if self.encerrada:
            return
        try:
            while True:
                tarefa = self.tarefas.get_nowait()
                if tarefa[0] == "progresso":
                    self._informar(tarefa[1])
                else:
                    self.ocupada = False
                    self.progresso.stop()
                    self._atualizar_estado()
                    if tarefa[0] == "erro":
                        self._mostrar_erro(tarefa[1])
                    else:
                        self._acao(lambda t=tarefa: t[1](t[2]))
        except Empty:
            pass
        ultimo = None
        try:
            while True:
                ultimo = self.eventos.get_nowait()
        except Empty:
            pass
        if ultimo is not None and not self.ocupada:
            conhecidas = sum(r.reconhecido for r in ultimo)
            if self.motor.pronto:
                texto = f"{len(ultimo)} rosto(s) · {conhecidas} identificado(s) · {len(ultimo)-conhecidas} desconhecido(s)"
            else:
                texto = f"{len(ultimo)} rosto(s) detectado(s). Cadastre duas fotos por pessoa para identificar nomes."
            if not ultimo:
                texto = "Nenhum rosto encontrado. Use uma foto frontal, nítida e com boa iluminação."
            self._informar(texto)
            self._atualizar_estado()
            self._atualizar_chamada()
        self.poll_id = self.after(250, self._poll)

    def _agendar_render(self, _evento=None):
        if self.resize_id:
            self.after_cancel(self.resize_id)
        self.resize_id = self.after(80, self._renderizar)

    def _renderizar(self):
        if self.resize_id:
            self.after_cancel(self.resize_id)
        self.resize_id = None
        if self.encerrada:
            return
        self._fotos = []
        for indice, (canvas, imagem) in enumerate(zip(self.canvases, (self.original, self.processada))):
            canvas.delete("all")
            largura, altura = max(canvas.winfo_width(), 1), max(canvas.winfo_height(), 1)
            if imagem is None:
                centro_x, centro_y = largura/2, altura/2-28
                cor = "#aab6c7"
                # Moldura desenhada: affordance de imagem, sem fontes de ícones.
                canvas.create_rectangle(centro_x-30, centro_y-23, centro_x+30, centro_y+23, outline=cor, width=2)
                canvas.create_oval(centro_x+10, centro_y-15, centro_x+19, centro_y-6, outline=cor, width=2)
                canvas.create_line(centro_x-23, centro_y+15, centro_x-7, centro_y-1, centro_x+5, centro_y+10, centro_x+15, centro_y+3, centro_x+24, centro_y+15, fill=cor, width=2)
                titulo = "Abra uma foto" if indice == 0 else "Confira o resultado aqui"
                dica = "ou traga uma imagem do editor" if indice == 0 else "Rostos localizados e nomes identificados"
                canvas.create_text(centro_x, centro_y+50, text=titulo, fill="#203047", font=("Segoe UI", 12, "bold"), width=max(largura-32, 20))
                canvas.create_text(centro_x, centro_y+78, text=dica, fill="#68778d", font=("Segoe UI", 10), width=max(largura-36, 20))
                continue
            rgb = cv2.cvtColor(imagem, cv2.COLOR_GRAY2RGB if imagem.ndim == 2 else cv2.COLOR_BGRA2RGB if imagem.shape[2] == 4 else cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(rgb)
            pil.thumbnail((max(1, largura-12), max(1, altura-12)), Image.Resampling.LANCZOS)
            foto = ImageTk.PhotoImage(pil, master=self)
            self._fotos.append(foto)
            canvas.create_image(largura/2, altura/2, image=foto)

    def fechar(self):
        self.destroy()

    def destroy(self):
        if not self.winfo_exists():
            return
        self.encerrada = True
        self._captura = None
        self.progresso.stop()
        for nome in ("poll_id", "resize_id", "_captura_id"):
            callback = getattr(self, nome, None)
            if callback:
                self.after_cancel(callback)
                setattr(self, nome, None)
        super().destroy()
