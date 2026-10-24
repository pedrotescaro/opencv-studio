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
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

PASTA_PADRAO = Path(__file__).resolve().parents[2] / ".dados_faces"
TIPOS_IMAGEM = [
    ("Imagens", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
    ("Todos", "*.*"),
]


class ErroFaces(ValueError):
    """Erro de dados/configuração que pode ser mostrado diretamente ao usuário."""


def validar_imagem(imagem):
    if (
        not isinstance(imagem, np.ndarray)
        or imagem.dtype != np.uint8
        or imagem.ndim not in (2, 3)
        or (not imagem.size)
        or (imagem.ndim == 3 and imagem.shape[2] not in (3, 4))
    ):
        raise ErroFaces("Use uma imagem de 8 bits em cinza, BGR ou BGRA.")
    return imagem


def ler_imagem(caminho):
    """imdecode permite nomes e pastas Unicode também no Windows."""
    try:
        imagem = cv2.imdecode(
            np.frombuffer(Path(caminho).read_bytes(), np.uint8), cv2.IMREAD_COLOR
        )
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
    cinza = (
        face
        if face.ndim == 2
        else cv2.cvtColor(
            face, cv2.COLOR_BGRA2GRAY if face.shape[2] == 4 else cv2.COLOR_BGR2GRAY
        )
    )
    return cv2.equalizeHist(cv2.resize(cinza, (128, 128), interpolation=cv2.INTER_AREA))


def _escrever_json(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporario.replace(caminho)


def _assinatura_arquivo(caminho):
    """Metadados baratos para reaproveitar hashes entre frames de vídeo."""
    try:
        estado = caminho.stat()
        return (estado.st_size, estado.st_mtime_ns, estado.st_ctime_ns)
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
                if (
                    not isinstance(dados, dict)
                    or dados.get("versao") != 1
                    or (not isinstance(dados["alunos"], dict))
                ):
                    raise ValueError("formato incompatível")
                for codigo, aluno in dados["alunos"].items():
                    if (
                        not isinstance(codigo, str)
                        or not codigo.strip()
                        or (not isinstance(aluno, dict))
                        or (not isinstance(aluno.get("nome"), str))
                        or (not aluno["nome"].strip())
                        or (not isinstance(aluno.get("amostras"), list))
                    ):
                        raise ValueError("cadastro inválido")
                    for nome in aluno["amostras"]:
                        if (
                            not isinstance(nome, str)
                            or Path(nome).name != nome
                            or "/" in nome
                            or ("\\" in nome)
                            or (not nome.endswith(".png"))
                        ):
                            raise ValueError("caminho de amostra inválido")
                return dados["alunos"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ErroFaces(
                    f"Não foi possível carregar o cadastro {self.arquivo}: {exc}"
                ) from exc
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
        codigo, nome = (str(codigo).strip(), str(nome).strip())
        if not codigo or not nome or len(codigo) > 80 or (len(nome) > 160):
            raise ErroFaces(
                "Informe matrícula/ID (até 80 caracteres) e nome (até 160)."
            )
        if any((ord(c) < 32 for c in codigo + nome)):
            raise ErroFaces(
                "Matrícula e nome não podem conter quebras de linha ou caracteres de controle."
            )
        novas = [normalizar_face(face) for face in faces]
        if not novas:
            raise ErroFaces("Escolha ao menos uma foto para o cadastro.")
        with self.lock:
            existentes = self.alunos.get(codigo, {"nome": nome, "amostras": []})
            hashes = {
                hashlib.sha256(self.ler_amostra(n).tobytes()).digest()
                for n in existentes["amostras"]
            }
            unicas = []
            for face in novas:
                resumo = hashlib.sha256(face.tobytes()).digest()
                if resumo not in hashes:
                    hashes.add(resumo)
                    unicas.append(face)
            if not unicas:
                raise ErroFaces(
                    "As fotos selecionadas repetem amostras já cadastradas. Use fotos diferentes."
                )
            self.pasta.joinpath("amostras").mkdir(parents=True, exist_ok=True)
            arquivos = []
            try:
                for face in unicas:
                    arquivo = f"{uuid.uuid4().hex}.png"
                    salvar_imagem(self.pasta / "amostras" / arquivo, face)
                    arquivos.append(arquivo)
                anterior = self.alunos.get(codigo)
                self.alunos[codigo] = {
                    "nome": nome,
                    "amostras": existentes["amostras"] + arquivos,
                }
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
        return cv2.cvtColor(
            ler_imagem(self.pasta / "amostras" / nome), cv2.COLOR_BGR2GRAY
        )

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
    detalhes = (
        f"{resultado.codigo} | d={resultado.distancia:.1f}"
        if resultado.reconhecido
        else f"d={resultado.distancia:.1f}"
        if resultado.modo != "deteccao"
        else ""
    )
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
    largura_caixa = min(
        largura_maxima,
        max((largura(linha) for linha in linhas), default=0) + 2 * margem,
    )
    altura_caixa = len(linhas) * altura_linha + 2 * margem
    return (fonte, linhas, largura_caixa, altura_caixa, altura_linha, margem)


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
                if (
                    config.get("versao") != 1
                    or not math.isfinite(limiar_salvo)
                    or limiar_salvo <= 0
                ):
                    raise ValueError("limiar inválido")
            except (OSError, ValueError, KeyError, TypeError):
                limiar_salvo = 60.0
                self.status_modelo += (
                    " A configuração de limiar foi restaurada para 60."
                )
        self.definir_limiar(limiar_salvo if limiar is None else limiar, persistir=False)
        cascata = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        self.detector = cv2.CascadeClassifier(str(cascata))
        if self.detector.empty():
            raise ErroFaces(
                "O detector Haar não foi encontrado na instalação do OpenCV."
            )

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
        cadastro = json.dumps(
            alunos, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        arquivos = [
            (codigo, nome)
            for codigo, aluno in sorted(alunos.items())
            for nome in aluno["amostras"]
        ]
        assinatura = (
            cadastro,
            self.banco.revisao,
            _assinatura_arquivo(self.banco.arquivo),
            tuple(
                (
                    (
                        codigo,
                        nome,
                        _assinatura_arquivo(self.banco.pasta / "amostras" / nome),
                    )
                    for codigo, nome in arquivos
                )
            ),
        )
        if assinatura == self._assinatura_dataset and self._dados_cache is not None:
            return self._dados_cache
        amostras, resumo = ({}, hashlib.sha256())
        resumo.update(
            json.dumps(
                {
                    "parametros": self.PARAMETROS,
                    "normalizacao": self.NORMALIZACAO,
                    "alunos": alunos,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        )
        for codigo, nome in arquivos:
            try:
                conteudo = (self.banco.pasta / "amostras" / nome).read_bytes()
            except OSError as exc:
                raise ErroFaces(
                    f"A amostra {nome} não está disponível. Reponha a foto ou refaça o cadastro."
                ) from exc
            digest = hashlib.sha256(conteudo).hexdigest()
            amostras[nome] = digest
            resumo.update(
                json.dumps([codigo, nome, digest], ensure_ascii=False).encode("utf-8")
            )
        dados = {
            "fingerprint": resumo.hexdigest(),
            "amostras": amostras,
            "total_amostras": len(arquivos),
            "total_pessoas": len(alunos),
        }
        self._assinatura_dataset, self._dados_cache = (assinatura, dados)
        return dados

    def _validar_cadastro_treinavel(self, dados):
        if not self.banco.alunos:
            raise ErroFaces(
                "Cadastre ao menos uma pessoa com duas fotos distintas para identificar."
            )
        incompletos = [
            f"{aluno['nome']} ({codigo})"
            for codigo, aluno in self.banco.alunos.items()
            if len({dados["amostras"][nome] for nome in aluno["amostras"]}) < 2
        ]
        if incompletos:
            raise ErroFaces(
                "Cada pessoa precisa de pelo menos duas fotos distintas. Complete: "
                + ", ".join(incompletos)
            )

    def _criar_modelo(self):
        if not hasattr(cv2, "face") or not hasattr(
            cv2.face, "LBPHFaceRecognizer_create"
        ):
            raise ErroFaces(
                "LBPH não está disponível. Instale as dependências do projeto com opencv-contrib-python; não misture com opencv-python."
            )
        return cv2.face.LBPHFaceRecognizer_create(**self.PARAMETROS)

    def _persistir_modelo(self, dados):
        armazenamento = cv2.FileStorage(
            "modelo.yml", cv2.FILE_STORAGE_WRITE | cv2.FILE_STORAGE_MEMORY
        )
        try:
            cv2.Algorithm.write(self.modelo, armazenamento, "lbph")
            conteudo = armazenamento.releaseAndGetString().encode("utf-8")
        finally:
            armazenamento.release()
        manifesto = dict(
            versao=1,
            algoritmo="LBPH",
            parametros=self.PARAMETROS,
            normalizacao=self.NORMALIZACAO,
            **dados,
            rotulos={
                str(rotulo): list(pessoa) for rotulo, pessoa in self.rotulos.items()
            },
            modelo_sha256=hashlib.sha256(conteudo).hexdigest(),
        )
        _escrever_bytes(self.arquivo_modelo, conteudo)
        _escrever_bytes(
            self.arquivo_manifesto,
            json.dumps(manifesto, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    def _carregar_modelo(self, dados):
        """Um cache ausente, incompatível ou corrompido apenas pede novo treino."""
        try:
            manifesto = json.loads(self.arquivo_manifesto.read_text(encoding="utf-8"))
            conteudo = self.arquivo_modelo.read_bytes()
            esperados = {
                rotulo: (codigo, aluno["nome"])
                for rotulo, (codigo, aluno) in enumerate(
                    sorted(self.banco.alunos.items())
                )
            }
            if (
                manifesto.get("versao") != 1
                or manifesto.get("algoritmo") != "LBPH"
                or manifesto.get("parametros") != self.PARAMETROS
                or (manifesto.get("normalizacao") != self.NORMALIZACAO)
                or (manifesto.get("fingerprint") != dados["fingerprint"])
                or (manifesto.get("amostras") != dados["amostras"])
                or (manifesto.get("total_amostras") != dados["total_amostras"])
                or (manifesto.get("total_pessoas") != dados["total_pessoas"])
                or (
                    manifesto.get("modelo_sha256")
                    != hashlib.sha256(conteudo).hexdigest()
                )
                or (
                    manifesto.get("rotulos")
                    != {str(k): list(v) for k, v in esperados.items()}
                )
            ):
                return False
            armazenamento = cv2.FileStorage(
                conteudo.decode("utf-8"),
                cv2.FILE_STORAGE_READ | cv2.FILE_STORAGE_MEMORY,
            )
            try:
                modelo = self._criar_modelo()
                cv2.Algorithm.read(modelo, armazenamento.getNode("lbph"))
            finally:
                armazenamento.release()
            labels = modelo.getLabels().reshape(-1)
            histogramas = modelo.getHistograms()
            tamanho_histograma = (
                self.PARAMETROS["grid_x"]
                * self.PARAMETROS["grid_y"]
                * 2 ** self.PARAMETROS["neighbors"]
            )
            if (
                modelo.empty()
                or len(labels) != dados["total_amostras"]
                or len(histogramas) != len(labels)
                or any(
                    (
                        histograma.size != tamanho_histograma
                        or not np.isfinite(histograma).all()
                        for histograma in histogramas
                    )
                )
                or (set((int(valor) for valor in labels)) != set(esperados))
                or (
                    (
                        modelo.getRadius(),
                        modelo.getNeighbors(),
                        modelo.getGridX(),
                        modelo.getGridY(),
                    )
                    != tuple(
                        (
                            self.PARAMETROS[chave]
                            for chave in ("radius", "neighbors", "grid_x", "grid_y")
                        )
                    )
                )
            ):
                return False
            self.modelo, self.rotulos = (modelo, esperados)
            self.fingerprint_treinado = dados["fingerprint"]
            self.revisao_treinada = self.banco.revisao
            self.status_modelo = f"Modelo salvo carregado: {dados['total_pessoas']} pessoa(s), {dados['total_amostras']} fotos."
            return True
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            SystemError,
            cv2.error,
        ):
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
                if (
                    self._falha_preparo is not None
                    and self._falha_preparo[0] == dados["fingerprint"]
                ):
                    self.status_modelo = self._falha_preparo[1]
                    return False
                if (
                    self.modelo is not None
                    and self.fingerprint_treinado == dados["fingerprint"]
                ):
                    self.revisao_treinada = self.banco.revisao
                    return True
                self.modelo, self.rotulos = (None, {})
                if self._carregar_modelo(dados):
                    return True
                self.treinar()
                return True
            except (ErroFaces, OSError, cv2.error) as exc:
                self.modelo, self.rotulos, self.fingerprint_treinado = (None, {}, None)
                self.revisao_treinada = -1
                self.status_modelo = f"Detecção de rostos ativa. {exc}"
                if "dados" in locals():
                    self._falha_preparo = (dados["fingerprint"], self.status_modelo)
                return False

    garantir_modelo = preparar_modelo

    def definir_limiar(self, valor, *, persistir=True):
        try:
            limiar = float(valor)
        except (TypeError, ValueError):
            raise ErroFaces(
                "O limiar LBPH deve ser um número maior que zero."
            ) from None
        if not math.isfinite(limiar) or limiar <= 0:
            raise ErroFaces("O limiar LBPH deve ser um número finito maior que zero.")
        with self.lock:
            self.limiar = limiar
            if persistir:
                try:
                    _escrever_bytes(
                        self.arquivo_config,
                        json.dumps({"versao": 1, "limiar_lbph": limiar}).encode(
                            "utf-8"
                        ),
                    )
                except OSError as exc:
                    self.status_modelo += f" Não foi possível guardar o limiar: {exc}"

    def treinar(self):
        with self.lock, self.banco.lock:
            modelo = self._criar_modelo()
            dados = self._dados_dataset()
            self._validar_cadastro_treinavel(dados)
            faces, rotulos, mapeamento = ([], [], {})
            for rotulo, (codigo, aluno) in enumerate(sorted(self.banco.alunos.items())):
                mapeamento[rotulo] = (codigo, aluno["nome"])
                for arquivo in aluno["amostras"]:
                    faces.append(self.banco.ler_amostra(arquivo))
                    rotulos.append(rotulo)
            modelo.train(faces, np.asarray(rotulos, np.int32))
            self.modelo, self.rotulos = (modelo, mapeamento)
            self.revisao_treinada = self.banco.revisao
            self.fingerprint_treinado = dados["fingerprint"]
            self._falha_preparo = None
            self.status_modelo = (
                f"Modelo treinado: {len(mapeamento)} pessoa(s), {len(faces)} fotos."
            )
            try:
                self._persistir_modelo(dados)
            except (OSError, cv2.error) as exc:
                self.status_modelo += f" Não foi possível guardar o treino: {exc}"
            return (len(faces), len(mapeamento))

    def _exigir_treino(self):
        if self.modelo is None:
            raise ErroFaces("Treine o modelo LBPH antes de reconhecer faces.")
        if self.revisao_treinada != self.banco.revisao:
            raise ErroFaces("O cadastro mudou. Treine novamente o modelo LBPH.")
        if self.fingerprint_treinado != self._dados_dataset()["fingerprint"]:
            raise ErroFaces("O cadastro mudou. Treine novamente o modelo LBPH.")

    def detectar(self, imagem):
        validar_imagem(imagem)
        cinza = (
            imagem
            if imagem.ndim == 2
            else cv2.cvtColor(
                imagem,
                cv2.COLOR_BGRA2GRAY if imagem.shape[2] == 4 else cv2.COLOR_BGR2GRAY,
            )
        )
        fator = min(1.0, 1400 / max(cinza.shape))
        reduzida = (
            cv2.resize(cinza, None, fx=fator, fy=fator, interpolation=cv2.INTER_AREA)
            if fator < 1
            else cinza
        )
        with self.lock:
            caixas = self.detector.detectMultiScale(
                cv2.equalizeHist(reduzida),
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30),
            )
        return [tuple((int(round(v / fator)) for v in caixa)) for caixa in caixas]

    def prever_face(self, face, caixa=None):
        normalizada = normalizar_face(face)
        with self.lock, self.banco.lock:
            self._exigir_treino()
            rotulo, distancia = self.modelo.predict(normalizada)
            distancia = float(distancia)
            if (
                rotulo in self.rotulos
                and math.isfinite(distancia)
                and (distancia <= self.limiar)
            ):
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
                    resultado = self.prever_face(
                        imagem[y : y + h, x : x + w], (x, y, w, h)
                    )
                else:
                    resultado = ResultadoFace(
                        None, "Rosto detectado", math.nan, (x, y, w, h), modo="deteccao"
                    )
                resultados.append(resultado)
            return resultados

    def anotar(self, imagem):
        resultados = self.reconhecer(imagem)
        bgr = (
            cv2.cvtColor(imagem, cv2.COLOR_GRAY2BGR)
            if imagem.ndim == 2
            else imagem[:, :, :3].copy()
        )
        for resultado in resultados:
            x, y, w, h = resultado.caixa
            cor = (
                (70, 180, 40)
                if resultado.reconhecido
                else (210, 150, 35)
                if resultado.modo == "deteccao"
                else (40, 90, 230)
            )
            cv2.rectangle(bgr, (x, y), (x + w, y + h), cor, 2)
        if resultados:
            pil = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            desenho = ImageDraw.Draw(pil)
            tamanho = max(13, min(24, round(min(imagem.shape[:2]) / 35)))
            for resultado in resultados:
                x, y, _, _ = resultado.caixa
                fonte, linhas, largura, altura, altura_linha, margem = _layout_legenda(
                    resultado, pil.width, tamanho
                )
                esquerda = max(0, min(x, pil.width - largura))
                topo = max(0, min(y - altura, pil.height - altura))
                fundo = (
                    "#205d2d"
                    if resultado.reconhecido
                    else "#186b94"
                    if resultado.modo == "deteccao"
                    else "#a83226"
                )
                desenho.rectangle(
                    (
                        esquerda,
                        topo,
                        min(pil.width - 1, esquerda + largura - 1),
                        min(pil.height - 1, topo + altura - 1),
                    ),
                    fill=fundo,
                )
                for indice, linha in enumerate(linhas):
                    bbox = fonte.getbbox(linha)
                    desenho.text(
                        (
                            esquerda + margem - bbox[0],
                            topo + margem + indice * altura_linha - bbox[1],
                        ),
                        linha,
                        font=fonte,
                        fill="white",
                    )
            bgr = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
        return (bgr, resultados)


class Chamada:
    """Uma primeira identificação por ID em cada sessão, persistida em JSON."""

    def __init__(self, nome="", pasta=None, *, metrica="distancia_lbph"):
        if metrica not in ("distancia_lbph", "distancia_sface"):
            raise ErroFaces("Métrica de reconhecimento inválida para a chamada.")
        self.metrica = metrica
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
        dados = dict(
            versao=1,
            codigo=self.codigo,
            nome=self.nome,
            inicio=self.inicio,
            ativa=self.ativa,
            registros=list(self.registros.values()),
        )
        if self.metrica == "distancia_sface":
            dados.update(versao=2, algoritmo="SFace", metrica=self.metrica)
        _escrever_json(
            self.caminho,
            dados,
        )

    def registrar(self, resultado):
        with self.lock:
            if (
                not self.ativa
                or not resultado.reconhecido
                or resultado.codigo in self.registros
            ):
                return False
            registro = dict(
                id_aluno=resultado.codigo,
                nome=resultado.nome,
                primeira_identificacao=datetime.now()
                .astimezone()
                .isoformat(timespec="seconds"),
            )
            registro[self.metrica] = round(resultado.distancia, 4)
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
                colunas = (
                    "sessao",
                    "id_aluno",
                    "nome",
                    "primeira_identificacao",
                    self.metrica,
                )
                escritor = csv.DictWriter(arquivo, fieldnames=colunas, delimiter=";")
                escritor.writeheader()
                for registro in self.registros.values():
                    escritor.writerow(dict(sessao=self.nome, **registro))
