"""Vídeo e câmera independentes da imagem do editor, com exportação em worker."""

import math
import shutil
import tempfile
from pathlib import Path
import cv2
import numpy as np

EFEITOS_VIDEO = (
    "Original",
    "Escala de cinza",
    "Inversão de cores",
    "Gaussiano",
    "Canny",
    "Erosão",
    "Dilatação",
    "Abertura",
    "Fechamento",
)
EFEITO_FACIAL = "Reconhecimento facial"


def aplicar_efeito(frame, efeito="Original", processador_facial=None):
    """Processa um frame BGR sem modificar a entrada e conserva tamanho/canais."""
    if (
        not isinstance(frame, np.ndarray)
        or frame.dtype != np.uint8
        or frame.ndim != 3
        or (frame.shape[2] != 3)
    ):
        raise ValueError("O frame deve ser uma imagem BGR de 8 bits e três canais.")
    if efeito == "Original":
        resultado = frame.copy()
    elif efeito == "Escala de cinza":
        resultado = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    elif efeito == "Inversão de cores":
        resultado = cv2.bitwise_not(frame)
    elif efeito == "Gaussiano":
        resultado = cv2.GaussianBlur(frame, (5, 5), 0)
    elif efeito == "Canny":
        resultado = cv2.Canny(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 80, 160)
    elif efeito in ("Erosão", "Dilatação", "Abertura", "Fechamento"):
        operacao = {
            "Erosão": cv2.MORPH_ERODE,
            "Dilatação": cv2.MORPH_DILATE,
            "Abertura": cv2.MORPH_OPEN,
            "Fechamento": cv2.MORPH_CLOSE,
        }[efeito]
        resultado = cv2.morphologyEx(frame, operacao, np.ones((3, 3), np.uint8))
    elif efeito == EFEITO_FACIAL:
        if not callable(processador_facial):
            raise ValueError(
                "Abra o módulo Faces e treine um modelo para reconhecer faces."
            )
        resultado = processador_facial(frame.copy())
    else:
        raise ValueError("Efeito de vídeo desconhecido.")
    if not isinstance(resultado, np.ndarray) or resultado.dtype != np.uint8:
        raise ValueError("O processamento deve retornar uma imagem de 8 bits.")
    if resultado.ndim == 2:
        resultado = cv2.cvtColor(resultado, cv2.COLOR_GRAY2BGR)
    if resultado.shape != frame.shape:
        raise ValueError(
            "O processamento de vídeo deve preservar o tamanho e os três canais do frame."
        )
    return np.ascontiguousarray(resultado)


class FonteVideo:
    """VideoCapture com primeiro frame preservado e liberação explícita.

    Alguns backends do OpenCV não aceitam caminhos Unicode no Windows. Nesse
    caso um arquivo temporário é usado, sem mudar ou renomear a fonte.
    """

    def __init__(self, origem):
        self.capture = None
        self.temporario = None
        self.primeiro = None
        self.camera = isinstance(origem, int)
        self.origem = origem if self.camera else str(Path(origem).resolve())
        self.posicao = 0
        try:
            if self.camera and origem < 0:
                raise ValueError(
                    "O índice da câmera deve ser um inteiro maior ou igual a zero."
                )
            if not self.camera and (not Path(self.origem).is_file()):
                raise ValueError("O arquivo de vídeo não existe.")
            self.capture = cv2.VideoCapture(self.origem)
            ok, frame = (
                self.capture.read() if self.capture.isOpened() else (False, None)
            )
            if not ok and (not self.camera):
                self.capture.release()
                self.temporario = tempfile.TemporaryDirectory(prefix="opencv_fonte_")
                copia = Path(self.temporario.name) / (
                    "entrada" + Path(self.origem).suffix
                )
                shutil.copyfile(self.origem, copia)
                self.capture = cv2.VideoCapture(str(copia))
                ok, frame = (
                    self.capture.read() if self.capture.isOpened() else (False, None)
                )
            if not ok or frame is None:
                raise ValueError(
                    "Câmera indisponível. Confira o índice, a permissão e outros aplicativos."
                    if self.camera
                    else "Não foi possível ler frames deste arquivo de vídeo."
                )
            self.primeiro = frame
            self.altura, self.largura = frame.shape[:2]
            fps = self.capture.get(cv2.CAP_PROP_FPS)
            self.fps = float(fps) if math.isfinite(fps) and fps > 0 else 30.0
            total = self.capture.get(cv2.CAP_PROP_FRAME_COUNT)
            self.total = (
                int(total)
                if math.isfinite(total) and total > 0 and (not self.camera)
                else 0
            )
        except Exception:
            self.fechar()
            raise

    def ler(self):
        if self.capture is None:
            return (False, None)
        if self.primeiro is not None:
            frame, self.primeiro = (self.primeiro, None)
            ok = True
        else:
            ok, frame = self.capture.read()
        if ok:
            self.posicao += 1
        return (ok, frame)

    def reiniciar(self):
        if self.camera or self.capture is None:
            return False
        self.primeiro = None
        if not self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0):
            return False
        self.posicao = 0
        return True

    def fechar(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        self.primeiro = None
        if self.temporario is not None:
            self.temporario.cleanup()
            self.temporario = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.fechar()


class ExportacaoCancelada(Exception):
    """A exportação foi interrompida antes de substituir o arquivo de destino."""


def exportar_arquivo_video(
    origem,
    destino,
    efeito="Original",
    processador_facial=None,
    cancelar=None,
    progresso=None,
):
    """Exporta todos os frames, mantendo FPS e resolução. Não inclui áudio.

    A escrita é feita em temporário ASCII e só substitui o destino ao concluir.
    Não acessa Tk; pode ser executada em um worker.
    """
    origem, destino = (Path(origem).resolve(), Path(destino).resolve())
    if origem == destino or (destino.exists() and origem.samefile(destino)):
        raise ValueError("Escolha um arquivo de saída diferente do vídeo original.")
    if destino.suffix.lower() not in (".avi", ".mp4"):
        raise ValueError("Salve o vídeo com a extensão .avi ou .mp4.")
    if not destino.parent.is_dir():
        raise ValueError("A pasta de destino não existe.")

    def verificar_cancelamento():
        if cancelar is not None and cancelar.is_set():
            raise ExportacaoCancelada("Exportação cancelada.")

    verificar_cancelamento()
    with (
        FonteVideo(str(origem)) as fonte,
        tempfile.TemporaryDirectory(prefix="opencv_exportacao_") as pasta,
    ):
        if fonte.largura % 2 or fonte.altura % 2:
            raise ValueError(
                "Estes codecs exigem largura e altura pares para conservar a resolução."
            )
        temporario = Path(pasta) / ("resultado" + destino.suffix.lower())
        codec = "MJPG" if destino.suffix.lower() == ".avi" else "mp4v"
        writer = cv2.VideoWriter(
            str(temporario),
            cv2.VideoWriter_fourcc(*codec),
            fonte.fps,
            (fonte.largura, fonte.altura),
            True,
        )
        quantidade = 0
        try:
            if not writer.isOpened():
                raise ValueError(
                    "Não foi possível iniciar o codec de vídeo. Tente o formato AVI."
                )
            while True:
                verificar_cancelamento()
                ok, frame = fonte.ler()
                if not ok:
                    break
                resultado = aplicar_efeito(frame, efeito, processador_facial)
                writer.write(resultado)
                quantidade += 1
                if progresso is not None:
                    progresso(quantidade, fonte.total)
        finally:
            writer.release()
        verificar_cancelamento()
        if quantidade == 0 or not temporario.exists() or temporario.stat().st_size == 0:
            raise ValueError("O vídeo de saída não contém frames.")
        arquivo = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destino.parent,
                suffix=destino.suffix,
                prefix=".opencv_",
                delete=False,
            ) as arquivo:
                pendente = Path(arquivo.name)
            shutil.copyfile(temporario, pendente)
            verificar_cancelamento()
            pendente.replace(destino)
        finally:
            if arquivo is not None:
                Path(arquivo.name).unlink(missing_ok=True)
        return {
            "frames": quantidade,
            "fps": fonte.fps,
            "largura": fonte.largura,
            "altura": fonte.altura,
            "caminho": str(destino),
        }
