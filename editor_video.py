"""Vídeo e câmera independentes da imagem do editor, com exportação em worker."""
import math
import queue
import shutil
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from editor_interface import AbaFerramenta, CANVAS


EFEITOS_VIDEO = ("Original", "Escala de cinza", "Inversão de cores", "Gaussiano", "Canny",
                 "Erosão", "Dilatação", "Abertura", "Fechamento")
EFEITO_FACIAL = "Reconhecimento facial"


def aplicar_efeito(frame, efeito="Original", processador_facial=None):
    """Processa um frame BGR sem modificar a entrada e conserva tamanho/canais."""
    if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
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
        operacao = {"Erosão": cv2.MORPH_ERODE, "Dilatação": cv2.MORPH_DILATE,
                    "Abertura": cv2.MORPH_OPEN, "Fechamento": cv2.MORPH_CLOSE}[efeito]
        resultado = cv2.morphologyEx(frame, operacao, np.ones((3, 3), np.uint8))
    elif efeito == EFEITO_FACIAL:
        if not callable(processador_facial):
            raise ValueError("Abra o módulo Faces e treine um modelo para reconhecer faces.")
        resultado = processador_facial(frame.copy())
    else:
        raise ValueError("Efeito de vídeo desconhecido.")
    if not isinstance(resultado, np.ndarray) or resultado.dtype != np.uint8:
        raise ValueError("O processamento deve retornar uma imagem de 8 bits.")
    if resultado.ndim == 2:
        resultado = cv2.cvtColor(resultado, cv2.COLOR_GRAY2BGR)
    if resultado.shape != frame.shape:
        raise ValueError("O processamento de vídeo deve preservar o tamanho e os três canais do frame.")
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
                raise ValueError("O índice da câmera deve ser um inteiro maior ou igual a zero.")
            if not self.camera and not Path(self.origem).is_file():
                raise ValueError("O arquivo de vídeo não existe.")
            self.capture = cv2.VideoCapture(self.origem)
            ok, frame = self.capture.read() if self.capture.isOpened() else (False, None)
            if not ok and not self.camera:
                self.capture.release()
                self.temporario = tempfile.TemporaryDirectory(prefix="opencv_fonte_")
                copia = Path(self.temporario.name) / ("entrada" + Path(self.origem).suffix)
                shutil.copyfile(self.origem, copia)
                self.capture = cv2.VideoCapture(str(copia))
                ok, frame = self.capture.read() if self.capture.isOpened() else (False, None)
            if not ok or frame is None:
                raise ValueError("Câmera indisponível. Confira o índice, a permissão e outros aplicativos."
                                 if self.camera else "Não foi possível ler frames deste arquivo de vídeo.")
            self.primeiro = frame
            self.altura, self.largura = frame.shape[:2]
            fps = self.capture.get(cv2.CAP_PROP_FPS)
            self.fps = float(fps) if math.isfinite(fps) and fps > 0 else 30.0
            total = self.capture.get(cv2.CAP_PROP_FRAME_COUNT)
            self.total = int(total) if math.isfinite(total) and total > 0 and not self.camera else 0
        except Exception:
            self.fechar()
            raise

    def ler(self):
        if self.capture is None:
            return False, None
        if self.primeiro is not None:
            frame, self.primeiro = self.primeiro, None
            ok = True
        else:
            ok, frame = self.capture.read()
        if ok:
            self.posicao += 1
        return ok, frame

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


def exportar_arquivo_video(origem, destino, efeito="Original", processador_facial=None,
                          cancelar=None, progresso=None):
    """Exporta todos os frames, mantendo FPS e resolução. Não inclui áudio.

    A escrita é feita em temporário ASCII e só substitui o destino ao concluir.
    Não acessa Tk; pode ser executada em um worker.
    """
    origem, destino = Path(origem).resolve(), Path(destino).resolve()
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
    with FonteVideo(str(origem)) as fonte, tempfile.TemporaryDirectory(prefix="opencv_exportacao_") as pasta:
        # Os codecs de vídeo usuais truncam dimensões ímpares silenciosamente.
        if fonte.largura % 2 or fonte.altura % 2:
            raise ValueError("Estes codecs exigem largura e altura pares para conservar a resolução.")
        temporario = Path(pasta) / ("resultado" + destino.suffix.lower())
        codec = "MJPG" if destino.suffix.lower() == ".avi" else "mp4v"
        writer = cv2.VideoWriter(str(temporario), cv2.VideoWriter_fourcc(*codec), fonte.fps,
                                 (fonte.largura, fonte.altura), True)
        quantidade = 0
        try:
            if not writer.isOpened():
                raise ValueError("Não foi possível iniciar o codec de vídeo. Tente o formato AVI.")
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
        # copyfile aceita caminhos Unicode e também destinos em outro disco.
        # O temporário no destino permite substituição atômica ao final da cópia.
        arquivo = None
        try:
            with tempfile.NamedTemporaryFile(dir=destino.parent, suffix=destino.suffix,
                                             prefix=".opencv_", delete=False) as arquivo:
                pendente = Path(arquivo.name)
            shutil.copyfile(temporario, pendente)
            verificar_cancelamento()
            pendente.replace(destino)
        finally:
            if arquivo is not None:
                Path(arquivo.name).unlink(missing_ok=True)
        return {"frames": quantidade, "fps": fonte.fps,
                "largura": fonte.largura, "altura": fonte.altura, "caminho": str(destino)}


class JanelaVideo(AbaFerramenta):
    """Página de vídeo com preview original/resultado e captura independente."""
    def __init__(self, root, processador_facial=None):
        super().__init__(root, "Vídeo")
        self.processador_facial = processador_facial
        self.fonte = None
        self.caminho_video = None
        self.frame_original = self.frame_processado = None
        self.reproduzindo = self.encerrada = self.finalizado = False
        self.play_id = self.poll_id = self.resize_id = None
        self.worker = None
        self.cancelamento = threading.Event()
        self.eventos = queue.Queue()
        self.efeito = tk.StringVar(self, value="Original")
        self.indice_camera = tk.StringVar(self, value="0")
        self.status = tk.StringVar(self, value="Abra um vídeo ou uma câmera para começar.")
        self.info = tk.StringVar(self, value="Original e resultado aparecem lado a lado.")
        self.fotos = []
        self._criar_interface()
        self.bind("<Destroy>", self._ao_destruir, add="+")

    def _criar_interface(self):
        topo = ttk.Frame(self, padding=8)
        topo.pack(fill="x")
        ttk.Label(topo, text="Vídeo e câmera", style="Title.TLabel").pack(side="left")
        ttk.Button(topo, text="Abrir vídeo", command=self.abrir_video).pack(side="right")
        fonte = ttk.Frame(self, padding=(8, 2))
        fonte.pack(fill="x")
        ttk.Label(fonte, text="Índice da câmera").pack(side="left")
        ttk.Spinbox(fonte, from_=0, to=20, textvariable=self.indice_camera, width=4).pack(side="left", padx=8)
        ttk.Button(fonte, text="Abrir câmera", command=self.abrir_camera).pack(side="left")
        ttk.Label(fonte, text="Efeito").pack(side="left", padx=(24, 6))
        efeitos = EFEITOS_VIDEO + ((EFEITO_FACIAL,) if callable(self.processador_facial) else ())
        self.combo_efeito = ttk.Combobox(fonte, textvariable=self.efeito, values=efeitos,
                                        state="readonly", width=23)
        self.combo_efeito.pack(side="left")
        self.combo_efeito.bind("<<ComboboxSelected>>", lambda _e: self._atualizar_efeito())
        visual = ttk.Frame(self)
        visual.pack(fill="both", expand=True, padx=8, pady=8)
        visual.columnconfigure((0, 1), weight=1, uniform="video")
        visual.rowconfigure(1, weight=1)
        self.canvases = []
        for indice, titulo in enumerate(("Original", "Resultado")):
            ttk.Label(visual, text=titulo, style="Section.TLabel").grid(row=0, column=indice, pady=(0, 6))
            canvas = tk.Canvas(visual, bg=CANVAS, highlightthickness=0, width=320, height=240)
            canvas.grid(row=1, column=indice, sticky="nsew", padx=4)
            canvas.bind("<Configure>", self._redimensionar)
            self.canvases.append(canvas)
        controles = ttk.Frame(self, padding=8)
        controles.pack(fill="x")
        self.btn_play = ttk.Button(controles, text="Reproduzir", command=self.reproduzir, state="disabled")
        self.btn_play.pack(side="left")
        self.btn_pause = ttk.Button(controles, text="Pausar", command=self.pausar, state="disabled")
        self.btn_pause.pack(side="left", padx=6)
        self.btn_stop = ttk.Button(controles, text="Parar", command=self.parar, state="disabled")
        self.btn_stop.pack(side="left")
        self.btn_frame = ttk.Button(controles, text="Salvar frame", command=self.exportar_frame, state="disabled")
        self.btn_frame.pack(side="right")
        self.btn_exportar = ttk.Button(controles, text="Exportar vídeo", command=self.exportar_video, state="disabled")
        self.btn_exportar.pack(side="right", padx=6)
        self.btn_cancelar = ttk.Button(controles, text="Cancelar exportação", command=self.cancelar_exportacao, state="disabled")
        self.btn_cancelar.pack(side="right")
        ttk.Label(self, textvariable=self.info, style="Muted.TLabel").pack(anchor="w", padx=12)
        self.progresso = ttk.Progressbar(self, maximum=100)
        self.progresso.pack(fill="x", padx=12, pady=6)
        ttk.Label(self, textvariable=self.status, wraplength=950).pack(anchor="w", padx=12, pady=(0, 5))
        ttk.Label(self, text="Exportação: todos os frames do arquivo, no FPS e tamanho originais, sem áudio. "
                  "A câmera permite salvar frames; use arquivos para exportar vídeo.",
                  style="Muted.TLabel", wraplength=950).pack(anchor="w", padx=12, pady=(0, 8))

    def configurar_processador_facial(self, processador):
        self.processador_facial = processador
        self.combo_efeito.configure(values=EFEITOS_VIDEO + ((EFEITO_FACIAL,) if callable(processador) else ()))
        if not callable(processador) and self.efeito.get() == EFEITO_FACIAL:
            self.efeito.set("Original")
        self._atualizar_efeito()

    def _erro(self, erro):
        if not self.encerrada:
            self.status.set(str(erro))
            messagebox.showerror("Vídeo", str(erro), parent=self.winfo_toplevel())

    def _botoes(self):
        disponivel = self.fonte is not None
        self.btn_play.configure(state="normal" if disponivel and not self.reproduzindo else "disabled")
        self.btn_pause.configure(state="normal" if self.reproduzindo else "disabled")
        self.btn_stop.configure(state="normal" if disponivel else "disabled")
        self.btn_frame.configure(state="normal" if self.frame_processado is not None else "disabled")
        exportando = self.worker is not None and self.worker.is_alive()
        self.btn_exportar.configure(state="normal" if self.caminho_video and not exportando else "disabled")
        self.btn_cancelar.configure(state="normal" if exportando else "disabled")

    def _liberar_fonte(self):
        self.pausar()
        # Uma troca de fonte também encerra a exportação da fonte anterior.
        if self.worker is not None and self.worker.is_alive():
            self.cancelamento.set()
        if self.fonte is not None:
            self.fonte.fechar()
            self.fonte = None
        self.caminho_video = None

    def _abrir_fonte(self, origem):
        # Fecha antes de abrir outra câmera para liberar o dispositivo anterior.
        self._liberar_fonte()
        try:
            self.fonte = FonteVideo(origem)
            self.caminho_video = None if self.fonte.camera else self.fonte.origem
            self.finalizado = False
            ok, frame = self.fonte.ler()
            if not ok:
                raise ValueError("A fonte não retornou um frame válido.")
            self._mostrar_frame(frame)
            nome = f"Câmera {origem}" if self.fonte.camera else Path(self.fonte.origem).name
            self.status.set(f"{nome} aberto. Selecione um efeito e clique em Reproduzir.")
        except Exception as erro:
            self._liberar_fonte()
            self._erro(erro)
        self._botoes()

    def abrir_video(self, caminho=None):
        if caminho is None:
            caminho = filedialog.askopenfilename(parent=self.winfo_toplevel(), title="Abrir vídeo",
                filetypes=[("Vídeos", "*.mp4 *.avi *.mov *.mkv *.webm *.m4v"), ("Todos os arquivos", "*.*")])
        if caminho:
            self._abrir_fonte(str(caminho))

    def abrir_camera(self, indice=None):
        try:
            if indice is None:
                indice = int(self.indice_camera.get())
            if isinstance(indice, bool) or not isinstance(indice, int) or indice < 0:
                raise ValueError("O índice da câmera deve ser um inteiro maior ou igual a zero.")
        except (ValueError, TypeError):
            self._erro(ValueError("O índice da câmera deve ser um inteiro maior ou igual a zero."))
            return
        self._abrir_fonte(indice)

    def _mostrar_frame(self, frame):
        self.frame_original = frame.copy()
        self.frame_processado = aplicar_efeito(frame, self.efeito.get(), self.processador_facial)
        fonte = self.fonte
        if fonte is not None:
            total = str(fonte.total) if fonte.total else "ao vivo"
            self.info.set(f"{fonte.largura} × {fonte.altura} px · {fonte.fps:.2f} FPS · "
                          f"Frame {fonte.posicao}/{total} · {self.efeito.get()}")
        self.renderizar()

    def _atualizar_efeito(self):
        if self.frame_original is None or self.encerrada:
            return
        try:
            self._mostrar_frame(self.frame_original)
        except Exception as erro:
            self.pausar()
            self._erro(erro)

    def reproduzir(self):
        if self.fonte is None or self.encerrada or self.reproduzindo:
            return
        if self.finalizado:
            if not self.fonte.reiniciar():
                self._erro(ValueError("Não foi possível reiniciar este vídeo. Abra o arquivo novamente."))
                return
            self.finalizado = False
        self.reproduzindo = True
        self.status.set("Reproduzindo…")
        self._botoes()
        self._agendar_frame()

    def _agendar_frame(self):
        if self.reproduzindo and self.fonte is not None:
            self.play_id = self.after(max(1, round(1000 / self.fonte.fps)), self._proximo_frame)

    def _proximo_frame(self):
        self.play_id = None
        if not self.reproduzindo or self.encerrada or self.fonte is None:
            return
        inicio = time.monotonic()
        try:
            ok, frame = self.fonte.ler()
            if not ok:
                camera = self.fonte.camera
                self.pausar()
                self.finalizado = True
                if camera:
                    self._liberar_fonte()
                    self._erro(ValueError("A câmera foi desconectada ou não retornou frames."))
                else:
                    self.status.set("Fim do vídeo. Clique em Reproduzir para reiniciar.")
                self._botoes()
                return
            self._mostrar_frame(frame)
        except Exception as erro:
            self.pausar()
            self._erro(erro)
            return
        atraso = max(1, round(1000 / self.fonte.fps - (time.monotonic() - inicio) * 1000))
        self.play_id = self.after(atraso, self._proximo_frame)

    def pausar(self):
        self.reproduzindo = False
        if self.play_id is not None:
            self.after_cancel(self.play_id)
            self.play_id = None
        if not self.encerrada and hasattr(self, "btn_play"):
            self._botoes()
            if self.fonte is not None:
                self.status.set("Pausado.")

    def parar(self):
        self.pausar()
        if self.fonte is None:
            return
        if self.fonte.camera:
            self._liberar_fonte()
            self.status.set("Câmera liberada. Clique em Abrir câmera para reconectar.")
        else:
            try:
                if not self.fonte.reiniciar():
                    raise ValueError("Não foi possível retornar ao início do vídeo.")
                ok, frame = self.fonte.ler()
                if not ok:
                    raise ValueError("Não foi possível ler o primeiro frame.")
                self._mostrar_frame(frame)
                self.finalizado = False
                self.status.set("Parado no primeiro frame.")
            except Exception as erro:
                self._erro(erro)
        self._botoes()

    def exportar_frame(self, caminho=None):
        if self.frame_processado is None:
            self._erro(ValueError("Abra um vídeo ou uma câmera antes de salvar um frame."))
            return
        if caminho is None:
            caminho = filedialog.asksaveasfilename(parent=self.winfo_toplevel(), title="Salvar frame processado",
                defaultextension=".png", filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")])
        if not caminho:
            return
        try:
            caminho = Path(caminho)
            extensao = caminho.suffix.lower()
            if extensao not in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"):
                raise ValueError("Escolha um formato de imagem: PNG, JPEG, BMP, TIFF ou WebP.")
            ok, dados = cv2.imencode(extensao, self.frame_processado)
            if not ok:
                raise ValueError("Não foi possível codificar o frame neste formato.")
            dados.tofile(str(caminho))
            self.status.set(f"Frame salvo em {caminho.name}.")
        except Exception as erro:
            self._erro(erro)

    def exportar_video(self, caminho=None):
        if self.worker is not None and self.worker.is_alive():
            return
        if not self.caminho_video:
            self._erro(ValueError("Abra um arquivo de vídeo para exportar todos os frames."))
            return
        if caminho is None:
            caminho = filedialog.asksaveasfilename(parent=self.winfo_toplevel(), title="Exportar vídeo processado",
                defaultextension=".mp4", filetypes=[("MP4, sem áudio", "*.mp4"), ("AVI, sem áudio", "*.avi")])
        if not caminho:
            return
        origem, efeito, processador = self.caminho_video, self.efeito.get(), self.processador_facial
        self.cancelamento = threading.Event()
        cancelar = self.cancelamento
        self.progresso["value"] = 0
        self.status.set("Exportando todos os frames em segundo plano…")
        def executar():
            try:
                resultado = exportar_arquivo_video(origem, caminho, efeito, processador, cancelar,
                    lambda atual, total: self.eventos.put(("progresso", atual, total)) if atual % 10 == 0 else None)
                self.eventos.put(("concluido", resultado))
            except ExportacaoCancelada:
                self.eventos.put(("cancelado",))
            except Exception as erro:
                self.eventos.put(("erro", str(erro)))
        self.worker = threading.Thread(target=executar, name="exportar-video", daemon=True)
        self.worker.start()
        self._botoes()
        self.poll_id = self.after(60, self._acompanhar_exportacao)

    def _acompanhar_exportacao(self):
        self.poll_id = None
        if self.encerrada:
            return
        terminou = False
        while True:
            try:
                evento = self.eventos.get_nowait()
            except queue.Empty:
                break
            if evento[0] == "progresso":
                if evento[2]:
                    self.progresso["value"] = min(99, 100 * evento[1] / evento[2])
            elif evento[0] == "concluido":
                self.progresso["value"] = 100
                self.status.set(f"Vídeo exportado: {evento[1]['frames']} frames · {evento[1]['fps']:.2f} FPS · sem áudio.")
                terminou = True
            elif evento[0] == "cancelado":
                self.status.set("Exportação cancelada. O destino anterior foi preservado.")
                terminou = True
            elif evento[0] == "erro":
                self._erro(evento[1])
                terminou = True
        if terminou:
            self.worker = None
            self._botoes()
        else:
            self.poll_id = self.after(60, self._acompanhar_exportacao)

    def cancelar_exportacao(self):
        self.cancelamento.set()
        self.status.set("Cancelando exportação…")

    def _redimensionar(self, _evento=None):
        if self.resize_id is not None:
            self.after_cancel(self.resize_id)
        self.resize_id = self.after(50, self.renderizar)

    def renderizar(self):
        if self.resize_id is not None:
            self.after_cancel(self.resize_id)
        self.resize_id = None
        if self.encerrada:
            return
        self.fotos = []
        for canvas, frame in zip(self.canvases, (self.frame_original, self.frame_processado)):
            canvas.delete("all")
            w, h = canvas.winfo_width(), canvas.winfo_height()
            if frame is None:
                canvas.create_text(w // 2, h // 2, text="Nenhum vídeo aberto", fill="#68778d")
                continue
            imagem = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            imagem.thumbnail((max(1, w - 8), max(1, h - 8)), Image.Resampling.LANCZOS)
            foto = ImageTk.PhotoImage(imagem, master=canvas)
            self.fotos.append(foto)
            canvas.create_image(w // 2, h // 2, image=foto)

    def _ao_destruir(self, evento):
        if evento.widget is self:
            self._limpar()

    def _limpar(self):
        if self.encerrada:
            return
        self.encerrada = True
        self.cancelamento.set()
        for nome in ("play_id", "poll_id", "resize_id"):
            identificador = getattr(self, nome)
            if identificador is not None:
                self.after_cancel(identificador)
                setattr(self, nome, None)
        self.reproduzindo = False
        if self.fonte is not None:
            self.fonte.fechar()
            self.fonte = None

    def destroy(self):
        self._limpar()
        super().destroy()

    def fechar(self):
        self.destroy()
