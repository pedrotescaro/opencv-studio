"""Operações acadêmicas com matrizes independentes e modelo de cor explícito."""
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

from editor_interface import AbaFerramenta, CANVAS, VisualizacaoRedimensionavel

MODELOS = ("BGR", "RGB", "HSV", "Cinza")
OPERACOES = ("Duplicar / restaurar cópia", "Converter modelo de cor", "Redimensionar",
             "Quantizar níveis", "Crescimento de regiões")


def validar_imagem(imagem):
    if not isinstance(imagem, np.ndarray) or imagem.dtype != np.uint8 or not imagem.size:
        raise ValueError("Use uma imagem não vazia de 8 bits.")
    if imagem.ndim != 2 and not (imagem.ndim == 3 and imagem.shape[2] == 3):
        raise ValueError("Use uma imagem de um ou três canais.")
    return imagem


def converter_cor(imagem, origem="BGR", destino="RGB"):
    """Converte dados de verdade; devolver uma cópia evita compartilhar memória."""
    validar_imagem(imagem)
    if origem not in MODELOS or destino not in MODELOS:
        raise ValueError("Modelo de cor inválido.")
    if (imagem.ndim == 2) != (origem == "Cinza"):
        raise ValueError("O modelo informado não corresponde aos canais da matriz.")
    if origem == destino:
        return imagem.copy()
    bgr = imagem if origem == "BGR" else cv2.cvtColor(imagem, {
        "RGB": cv2.COLOR_RGB2BGR, "HSV": cv2.COLOR_HSV2BGR,
        "Cinza": cv2.COLOR_GRAY2BGR}[origem])
    if destino == "BGR":
        return bgr.copy()
    return cv2.cvtColor(bgr, {"RGB": cv2.COLOR_BGR2RGB, "HSV": cv2.COLOR_BGR2HSV,
                              "Cinza": cv2.COLOR_BGR2GRAY}[destino])


def redimensionar(imagem, largura, altura):
    validar_imagem(imagem)
    largura, altura = int(largura), int(altura)
    if largura < 1 or altura < 1 or largura * altura > 40_000_000:
        raise ValueError("Dimensões devem ser positivas e o resultado deve ter até 40 milhões de pixels.")
    h, w = imagem.shape[:2]
    metodo = cv2.INTER_AREA if largura <= w and altura <= h else cv2.INTER_LINEAR
    return cv2.resize(imagem, (largura, altura), interpolation=metodo)


def quantizar(imagem, niveis):
    validar_imagem(imagem)
    niveis = int(niveis)
    if not 2 <= niveis <= 256:
        raise ValueError("Escolha de 2 a 256 níveis por canal.")
    # Inclui preto e branco e mantém exatamente a identidade com 256 níveis.
    indices = np.floor(imagem.astype(np.float32) * niveis / 256)
    return np.rint(indices * 255 / (niveis - 1)).astype(np.uint8)


def histogramas(imagem, modelo="BGR", espaco="RGB"):
    """Retorna contagens por canal; H de HSV tem 180 níveis no OpenCV de 8 bits."""
    if espaco not in ("RGB", "HSV", "Cinza"):
        raise ValueError("Escolha RGB, HSV ou Cinza para o histograma.")
    dados = converter_cor(imagem, modelo, espaco)
    nomes = ("Cinza",) if espaco == "Cinza" else tuple(espaco)
    canais = (dados,) if dados.ndim == 2 else cv2.split(dados)
    return {nome: np.bincount(canal.ravel(), minlength=180 if nome == "H" else 256)
            for nome, canal in zip(nomes, canais)}


def crescer_regiao(imagem, semente, tolerancia=15, conectividade=4):
    """Flood fill de faixa fixa: compara cada canal com o pixel semente.

    A máscara contém apenas pixels conectados e dentro da tolerância da semente,
    sem encadear pequenas diferenças que atravessariam gradientes inteiros.
    """
    validar_imagem(imagem)
    x, y = map(int, semente)
    h, w = imagem.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError("A semente deve estar dentro da imagem (coordenadas começam em zero).")
    tolerancia = float(tolerancia)
    if not np.isfinite(tolerancia) or not 0 <= tolerancia <= 255:
        raise ValueError("A tolerância deve estar entre 0 e 255.")
    if conectividade not in (4, 8):
        raise ValueError("A conectividade deve ser 4 ou 8.")
    mascara = np.zeros((h + 2, w + 2), np.uint8)
    diferenca = tolerancia if imagem.ndim == 2 else (tolerancia,) * 3
    flags = conectividade | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    cv2.floodFill(imagem.copy(), mascara, (x, y), 0, diferenca, diferenca, flags)
    return mascara[1:-1, 1:-1].copy()


class JanelaLaboratorio(AbaFerramenta):
    def __init__(self, root, imagem, confirmar=None):
        super().__init__(root, "Laboratório", origem=imagem)
        self.base = validar_imagem(imagem).copy()
        self.resultado = self.base.copy()
        self.modelo_base = "Cinza" if imagem.ndim == 2 else "BGR"
        self.modelo = self.modelo_base
        self.confirmar = confirmar
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.encerrada = self.processando = False
        self.poll_id = self.render_id = None
        self.fotos, self.transformacoes = {}, {}
        self.operacao = tk.StringVar(value=OPERACOES[0])
        self.destino = tk.StringVar(value="HSV")
        self.largura = tk.StringVar(value=str(imagem.shape[1]))
        self.altura = tk.StringVar(value=str(imagem.shape[0]))
        self.proporcao = tk.BooleanVar(value=True)
        self.niveis = tk.StringVar(value="4")
        self.x = tk.StringVar(value="0")
        self.y = tk.StringVar(value="0")
        self.tolerancia = tk.StringVar(value="15")
        self.conectividade = tk.StringVar(value="4")
        self.espaco_hist = tk.StringVar(value="RGB")
        self.construir()

    def construir(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        barra = ttk.Frame(self)
        barra.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(barra, text="Laboratório de imagens", style="Section.TLabel").pack(side="left")
        ttk.Button(barra, text="Salvar resultado PNG", command=self.salvar).pack(side="right", padx=3)
        ttk.Button(barra, text="Exportar matriz NPZ", command=self.exportar_matriz).pack(side="right", padx=3)
        self.btn_enviar = ttk.Button(barra, text="Enviar ao editor", command=self.enviar)
        self.btn_enviar.pack(side="right", padx=3)
        self.visualizacao = VisualizacaoRedimensionavel(self)
        self.visualizacao.grid(row=1, column=0, sticky="nsew")
        visual = self.visualizacao.visual
        visual.columnconfigure((0, 1), weight=1)
        visual.rowconfigure(1, weight=1)
        visual.bind("<Configure>", self.ajustar_grafico)
        self.canvases = {}
        for coluna, (chave, titulo) in enumerate((("base", "Base preservada"), ("resultado", "Cópia independente / resultado"))):
            ttk.Label(visual, text=titulo, style="Muted.TLabel").grid(row=0, column=coluna, sticky="w", padx=6)
            canvas = tk.Canvas(visual, bg=CANVAS, highlightthickness=0, width=300, height=220)
            canvas.grid(row=1, column=coluna, sticky="nsew", padx=3)
            canvas.bind("<Configure>", self.agendar_render)
            self.canvases[chave] = canvas
        self.canvases["resultado"].bind("<Button-1>", self.marcar_semente)
        self.grafico = tk.Canvas(visual, bg="white", height=145, highlightthickness=0)
        self.grafico.grid(row=2, column=0, columnspan=2, sticky="ew", pady=6)
        self.grafico.bind("<Configure>", lambda e: self.desenhar_histograma())
        controles = self.visualizacao.controles
        linha = ttk.Frame(controles)
        linha.pack(fill="x", pady=4)
        ttk.Label(linha, text="Operação").pack(side="left", padx=(4, 8))
        combo = ttk.Combobox(linha, textvariable=self.operacao, values=OPERACOES, state="readonly", width=27)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda e: self.mostrar_parametros())
        self.btn_executar = ttk.Button(linha, text="Executar na cópia", command=self.executar, style="Accent.TButton")
        self.btn_executar.pack(side="left", padx=8)
        ttk.Label(linha, text="Histograma").pack(side="left", padx=(12, 6))
        hist = ttk.Combobox(linha, textvariable=self.espaco_hist, values=("RGB", "HSV", "Cinza"), state="readonly", width=7)
        hist.pack(side="left")
        hist.bind("<<ComboboxSelected>>", lambda e: self.desenhar_histograma())
        self.parametros = ttk.Frame(controles)
        self.parametros.pack(fill="x", pady=4)
        self.detalhes = ttk.Label(controles, style="Muted.TLabel", wraplength=900)
        self.detalhes.pack(anchor="w", padx=4, pady=4)
        self.status = ttk.Label(self, style="Muted.TLabel", wraplength=1100)
        self.status.grid(row=2, column=0, sticky="ew", pady=6)
        self.mostrar_parametros()
        self.atualizar()

    def campo(self, texto, variavel, largura=8):
        ttk.Label(self.parametros, text=texto).pack(side="left", padx=(6, 4))
        ttk.Entry(self.parametros, textvariable=variavel, width=largura).pack(side="left")

    def mostrar_parametros(self):
        for filho in self.parametros.winfo_children():
            filho.destroy()
        op = self.operacao.get()
        texto = "Restaura uma cópia independente da base. A imagem do editor só muda em Enviar ao editor."
        if op == OPERACOES[1]:
            ttk.Label(self.parametros, text="Destino").pack(side="left", padx=6)
            ttk.Combobox(self.parametros, textvariable=self.destino, values=MODELOS, state="readonly", width=10).pack(side="left")
            texto = "A matriz muda de modelo; a visualização reconstrói as cores. HSV: H 0–179, S e V 0–255. NPZ preserva dados e modelo."
        elif op == OPERACOES[2]:
            self.campo("Largura (px)", self.largura)
            self.campo("Altura (px)", self.altura)
            ttk.Checkbutton(self.parametros, text="Manter proporção pela largura", variable=self.proporcao).pack(side="left", padx=8)
            texto = "Altera a resolução da cópia. Com proporção ativada, a altura é calculada pela largura."
        elif op == OPERACOES[3]:
            self.campo("Níveis por canal (2–256)", self.niveis)
            texto = "Reduz os níveis em cinza ou BGR. Matrizes RGB/HSV são convertidas para BGR antes de quantizar."
        elif op == OPERACOES[4]:
            self.campo("Semente X", self.x)
            self.campo("Y", self.y)
            self.campo("Tolerância", self.tolerancia)
            ttk.Label(self.parametros, text="Vizinhança").pack(side="left", padx=6)
            ttk.Combobox(self.parametros, textvariable=self.conectividade, values=("4", "8"), state="readonly", width=4).pack(side="left")
            texto = "Clique no resultado para marcar a semente. Cresce por pixels conectados, comparando cada canal BGR (ou cinza) com a semente. Retorna máscara."
        self.detalhes.config(text=texto)

    def executar(self):
        if self.processando:
            return
        try:
            op = self.operacao.get()
            imagem, modelo = self.resultado.copy(), self.modelo
            if op == OPERACOES[0]:
                trabalho = lambda: (self.base.copy(), self.modelo_base)
            elif op == OPERACOES[1]:
                destino = self.destino.get()
                trabalho = lambda: (converter_cor(imagem, modelo, destino), destino)
            elif op == OPERACOES[2]:
                largura = int(self.largura.get())
                altura = max(1, round(imagem.shape[0] * largura / imagem.shape[1])) if self.proporcao.get() else int(self.altura.get())
                trabalho = lambda: (redimensionar(imagem, largura, altura), modelo)
            elif op == OPERACOES[3]:
                niveis = int(self.niveis.get())
                destino = "Cinza" if modelo == "Cinza" else "BGR"
                trabalho = lambda: (quantizar(converter_cor(imagem, modelo, destino), niveis), destino)
            elif op == OPERACOES[4]:
                semente = (int(self.x.get()), int(self.y.get()))
                tolerancia, conectividade = float(self.tolerancia.get()), int(self.conectividade.get())
                destino = "Cinza" if modelo == "Cinza" else "BGR"
                trabalho = lambda: (crescer_regiao(converter_cor(imagem, modelo, destino), semente, tolerancia, conectividade), "Cinza")
            else:
                raise ValueError("Escolha uma operação.")
            self.processando = True
            self.btn_executar.state(["disabled"])
            self.btn_enviar.state(["disabled"])
            self.status.config(text="Processando a cópia…")
            future = self.executor.submit(trabalho)
            self.poll_id = self.after(20, self.concluir, future, op)
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Parâmetros inválidos", str(exc), parent=self)

    def concluir(self, future, op):
        self.poll_id = None
        if self.encerrada:
            return
        if not future.done():
            self.poll_id = self.after(20, self.concluir, future, op)
            return
        self.processando = False
        self.btn_executar.state(["!disabled"])
        self.btn_enviar.state(["!disabled"])
        try:
            self.resultado, self.modelo = future.result()
            self.atualizar()
            if op == OPERACOES[4]:
                self.status.config(text=f"Região: {np.count_nonzero(self.resultado):,} pixels selecionados. Salve a máscara ou envie ao editor.")
        except (ValueError, cv2.error) as exc:
            self.status.config(text=f"Operação não aplicada: {exc}")
            messagebox.showerror("Não foi possível processar", str(exc), parent=self)

    def atualizar(self):
        h, w = self.resultado.shape[:2]
        self.largura.set(str(w))
        self.altura.set(str(h))
        self.status.config(text=f"Resultado: {w} × {h} px | modelo {self.modelo} | {self.resultado.nbytes:,} bytes. Base e resultado são matrizes independentes.")
        self.renderizar()
        self.desenhar_histograma()

    def agendar_render(self, _evento=None):
        if self.render_id is not None:
            self.after_cancel(self.render_id)
        self.render_id = self.after(50, self.renderizar)

    def renderizar(self):
        if self.render_id is not None:
            self.after_cancel(self.render_id)
        self.render_id = None
        if self.encerrada:
            return
        for chave, dados, modelo in (("base", self.base, self.modelo_base), ("resultado", self.resultado, self.modelo)):
            canvas = self.canvases[chave]
            rgb = converter_cor(dados, modelo, "RGB")
            h, w = rgb.shape[:2]
            cw, ch = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
            escala = min(cw / w, ch / h, 2)
            dw, dh = max(1, round(w * escala)), max(1, round(h * escala))
            ox, oy = (cw - dw) / 2, (ch - dh) / 2
            self.fotos[chave] = ImageTk.PhotoImage(Image.fromarray(rgb).resize((dw, dh), Image.Resampling.LANCZOS))
            canvas.delete("all")
            canvas.create_image(ox, oy, anchor="nw", image=self.fotos[chave])
            self.transformacoes[chave] = (ox, oy, dw / w, dh / h)

    def marcar_semente(self, evento):
        if self.processando:
            return
        ox, oy, sx, sy = self.transformacoes["resultado"]
        x, y = int(np.floor((evento.x - ox) / sx)), int(np.floor((evento.y - oy) / sy))
        h, w = self.resultado.shape[:2]
        if 0 <= x < w and 0 <= y < h:
            self.x.set(str(x))
            self.y.set(str(y))
            self.canvases["resultado"].delete("semente")
            self.canvases["resultado"].create_oval(evento.x-5, evento.y-5, evento.x+5, evento.y+5, outline="#e11d48", width=2, tags="semente")

    def desenhar_histograma(self):
        if self.encerrada:
            return
        dados = histogramas(self.resultado, self.modelo, self.espaco_hist.get())
        canvas = self.grafico
        canvas.delete("all")
        w, h = max(300, canvas.winfo_width()), max(90, canvas.winfo_height())
        esquerda, topo, direita, baixo = 55, 25, w - 25, h - 26
        maximo = max(int(v.max()) for v in dados.values()) or 1
        cores = dict(R="#dc2626", G="#15803d", B="#2563eb", H="#7c3aed", S="#b45309", V="#334155", Cinza="#334155")
        canvas.create_text(10, 10, anchor="w", text=f"Histograma do resultado · {self.espaco_hist.get()} · contagem por canal", fill="#203047")
        canvas.create_line(esquerda, topo, esquerda, baixo, direita, baixo, fill="#68778d")
        canvas.create_text(esquerda-5, topo, anchor="e", text=str(maximo), fill="#68778d")
        for i, (nome, valores) in enumerate(dados.items()):
            pontos = []
            for nivel, contagem in enumerate(valores):
                pontos.extend((esquerda + nivel / 255 * (direita-esquerda), baixo - int(contagem)/maximo * (baixo-topo)))
            canvas.create_line(*pontos, fill=cores[nome], width=1.5)
            canvas.create_text(direita-140*i, 10, anchor="e", text=f"{nome}: {int(valores.sum()):,} px", fill=cores[nome])
        canvas.create_text(esquerda, baixo+13, text="0", fill="#68778d")
        canvas.create_text(direita, baixo+13, text="255", fill="#68778d")

    def ajustar_grafico(self, evento):
        altura = max(90, min(145, round(evento.height * .28)))
        if int(self.grafico.cget("height")) != altura:
            self.grafico.configure(height=altura)

    def imagem_bgr(self):
        return converter_cor(self.resultado, self.modelo, "Cinza" if self.modelo == "Cinza" else "BGR")

    def salvar(self):
        if self.processando:
            return
        caminho = filedialog.asksaveasfilename(parent=self, title="Salvar resultado visual", defaultextension=".png", filetypes=[("PNG", "*.png")])
        if caminho:
            try:
                ok, buffer = cv2.imencode(".png", self.imagem_bgr())
                if not ok:
                    raise ValueError("Falha ao codificar PNG.")
                buffer.tofile(caminho)
                self.status.config(text="PNG salvo. Modelos RGB/HSV foram convertidos para a imagem visual.")
            except (OSError, ValueError, cv2.error) as exc:
                messagebox.showerror("Erro ao salvar", str(exc), parent=self)

    def exportar_matriz(self):
        if self.processando:
            return
        caminho = filedialog.asksaveasfilename(parent=self, title="Exportar matriz e modelo", defaultextension=".npz", filetypes=[("NumPy", "*.npz")])
        if caminho:
            try:
                np.savez_compressed(caminho, imagem=self.resultado, modelo=self.modelo)
                self.status.config(text="Matriz exportada. Leia com np.load(caminho): chaves imagem e modelo.")
            except OSError as exc:
                messagebox.showerror("Erro ao exportar", str(exc), parent=self)

    def enviar(self):
        if not self.processando and self.confirmar is not None:
            self.confirmar(self.imagem_bgr())

    def destroy(self):
        if self.encerrada:
            return
        self.encerrada = True
        for tarefa in (self.poll_id, self.render_id):
            if tarefa is not None:
                self.after_cancel(tarefa)
        self.poll_id = self.render_id = None
        self.executor.shutdown(wait=False, cancel_futures=True)
        super().destroy()
