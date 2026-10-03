"""Recorte por formas, com coordenadas e contagem na resolução original."""
import tkinter as tk
from tkinter import ttk, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk
from editor_interface import AbaFerramenta, CANVAS, VisualizacaoRedimensionavel


FORMAS_RECORTE = ("Retângulo", "Quadrado", "Elipse", "Círculo", "Losango")


def limites_recorte(tamanho, inicio, fim, forma):
    """Retorna limites exclusivos, restringindo a seleção à imagem."""
    if forma not in FORMAS_RECORTE:
        raise ValueError("Forma desconhecida.")
    h, w = tamanho[:2]
    ax, ay = (int(np.clip(v, 0, limite)) for v, limite in zip(inicio, (w, h)))
    bx, by = (int(np.clip(v, 0, limite)) for v, limite in zip(fim, (w, h)))
    if forma in ("Quadrado", "Círculo"):
        lado = min(abs(bx - ax), abs(by - ay))
        bx = ax + (lado if bx >= ax else -lado)
        by = ay + (lado if by >= ay else -lado)
    return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)


def mascara_recorte(largura, altura, forma):
    if largura <= 0 or altura <= 0:
        raise ValueError("Arraste para selecionar uma área com largura e altura maiores que zero.")
    if forma not in FORMAS_RECORTE:
        raise ValueError("Forma desconhecida.")
    # Os centros dos pixels determinam se pertencem à forma.
    y, x = np.ogrid[:altura, :largura]
    x = (x + 0.5 - largura / 2) / (largura / 2)
    y = (y + 0.5 - altura / 2) / (altura / 2)
    if forma in ("Elipse", "Círculo"):
        return x * x + y * y <= 1
    if forma == "Losango":
        return abs(x) + abs(y) <= 1
    return np.ones((altura, largura), dtype=bool)


def recortar_imagem(imagem, inicio, fim, forma):
    x0, y0, x1, y1 = limites_recorte(imagem.shape, inicio, fim, forma)
    mascara = mascara_recorte(x1 - x0, y1 - y0, forma)
    resultado = imagem[y0:y1, x0:x1].copy()
    resultado[~mascara] = 0
    return resultado, int(np.count_nonzero(mascara))


class JanelaRecorte(AbaFerramenta):
    def __init__(self, parent, imagem, confirmar):
        super().__init__(parent, "Recorte", origem=imagem)
        self.imagem = imagem
        self.confirmar = confirmar
        self.inicio = self.fim = None
        self.arrastando = False
        self.transformacao = None
        self.forma = tk.StringVar(value="Retângulo")
        self.zoom = tk.StringVar(value="Ajustar")
        topo = ttk.Frame(self, padding=10)
        topo.pack(fill="x")
        ttk.Label(topo, text="Forma").pack(side="left")
        combo = ttk.Combobox(topo, textvariable=self.forma, values=FORMAS_RECORTE, state="readonly")
        combo.pack(side="left", padx=8)
        combo.bind("<<ComboboxSelected>>", lambda e: self.desenhar_selecao())
        ttk.Button(topo, text="Selecionar tudo", command=self.selecionar_tudo).pack(side="left")
        zoom = ttk.Combobox(topo, textvariable=self.zoom, values=("Ajustar", "50%", "100%", "200%", "400%"), width=8, state="readonly")
        zoom.pack(side="right")
        ttk.Label(topo, text="Zoom", style="Muted.TLabel").pack(side="right", padx=6)
        zoom.bind("<<ComboboxSelected>>", self.renderizar)
        self.visualizacao = VisualizacaoRedimensionavel(self)
        self.visualizacao.pack(fill="both", expand=True, padx=10)
        controles = self.visualizacao.controles
        h, w = imagem.shape[:2]
        ttk.Label(controles, text=f"Imagem: {w} × {h} = {w * h:,} pixels ({w * h / 1e6:.2f} MP)").pack(anchor="w", padx=10)
        ttk.Label(controles, text="Arraste na imagem para selecionar. A área externa às formas fica preta.",
                  wraplength=530).pack(anchor="w", padx=10, pady=5)
        rodape = ttk.Frame(controles, padding=10)
        rodape.pack(side="bottom", fill="x")
        self.info = ttk.Label(rodape, text="Nenhuma seleção.")
        self.info.pack(anchor="w")
        self.botao = ttk.Button(rodape, text="Aplicar recorte", command=self.aplicar, state="disabled", style="Accent.TButton")
        self.botao.pack(side="right", pady=6)
        ttk.Button(rodape, text="Voltar ao editor", command=self.destroy).pack(side="right", padx=8)
        visual = self.visualizacao.visual
        visual.rowconfigure(0, weight=1)
        visual.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(visual, bg=CANVAS, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        sy = ttk.Scrollbar(visual, command=self.canvas.yview)
        sx = ttk.Scrollbar(visual, orient="horizontal", command=self.canvas.xview)
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        self.canvas.bind("<Button-2>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B2-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-int(e.delta/120), "units"))
        self.canvas.bind("<Configure>", self.renderizar)
        self.canvas.bind("<Button-1>", self.comecar)
        self.canvas.bind("<B1-Motion>", self.arrastar)
        self.canvas.bind("<ButtonRelease-1>", self.terminar)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self.aplicar())

    def ao_enter(self):
        self.aplicar()

    def ao_escape(self):
        self.inicio = self.fim = None
        self.arrastando = False
        self.botao.state(["disabled"])
        self.info.config(text="Seleção limpa. Arraste para selecionar novamente.")
        self.canvas.delete("selecao")

    def renderizar(self, _evento=None):
        h, w = self.imagem.shape[:2]
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        escala = min(cw / w, ch / h, 1) if self.zoom.get() == "Ajustar" else float(self.zoom.get().strip("%"))/100
        dw, dh = max(1, int(w * escala)), max(1, int(h * escala))
        ox, oy = max(0, (cw - dw) / 2), max(0, (ch - dh) / 2)
        self.transformacao = ox, oy, dw / w, dh / h
        rgb = cv2.cvtColor(self.imagem, cv2.COLOR_GRAY2RGB if self.imagem.ndim == 2 else cv2.COLOR_BGR2RGB)
        self.foto = ImageTk.PhotoImage(Image.fromarray(rgb).resize((dw, dh), Image.Resampling.LANCZOS), master=self.canvas)
        self.canvas.delete("all")
        self.canvas.create_image(ox, oy, image=self.foto, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, max(cw, dw), max(ch, dh)))
        self.desenhar_selecao()

    def coordenada(self, evento, exigir_dentro=False):
        if self.transformacao is None:
            return None
        ox, oy, sx, sy = self.transformacao
        h, w = self.imagem.shape[:2]
        x, y = (self.canvas.canvasx(evento.x) - ox) / sx, (self.canvas.canvasy(evento.y) - oy) / sy
        if exigir_dentro and not (0 <= x <= w and 0 <= y <= h):
            return None
        return int(np.clip(round(x), 0, w)), int(np.clip(round(y), 0, h))

    def comecar(self, evento):
        ponto = self.coordenada(evento, exigir_dentro=True)
        self.arrastando = ponto is not None
        if ponto is not None:
            self.inicio = self.fim = ponto
            self.desenhar_selecao()

    def arrastar(self, evento):
        if self.arrastando:
            self.fim = self.coordenada(evento)
            self.desenhar_selecao(contar=False)

    def terminar(self, evento):
        self.arrastar(evento)
        self.arrastando = False
        self.desenhar_selecao()

    def selecionar_tudo(self):
        h, w = self.imagem.shape[:2]
        self.inicio, self.fim = (0, 0), (w, h)
        self.desenhar_selecao()

    def desenhar_selecao(self, contar=True):
        self.canvas.delete("selecao")
        if self.inicio is None or self.transformacao is None:
            return
        x0, y0, x1, y1 = limites_recorte(self.imagem.shape, self.inicio, self.fim, self.forma.get())
        w, h = x1 - x0, y1 - y0
        self.botao.state(["!disabled"] if w and h else ["disabled"])
        ox, oy, sx, sy = self.transformacao
        a, b, c, d = ox + x0 * sx, oy + y0 * sy, ox + x1 * sx, oy + y1 * sy
        opts = dict(outline="#ffe477", width=2, tags="selecao")
        if self.forma.get() in ("Elipse", "Círculo"):
            self.canvas.create_oval(a, b, c, d, **opts)
        elif self.forma.get() == "Losango":
            self.canvas.create_polygon((a+c)/2, b, c, (b+d)/2, (a+c)/2, d, a, (b+d)/2, fill="", **opts)
        else:
            self.canvas.create_rectangle(a, b, c, d, **opts)
        texto = f"Seleção: {w} × {h} | posição: ({x0}, {y0})"
        if contar and w and h:
            total = int(np.count_nonzero(mascara_recorte(w, h, self.forma.get())))
            texto += f"\nNa forma: {total:,} pixels | arquivo recortado: {w * h:,} pixels"
        self.info.config(text=texto)

    def aplicar(self):
        if self.inicio is None:
            return
        try:
            resultado, pixels = recortar_imagem(self.imagem, self.inicio, self.fim, self.forma.get())
        except ValueError as exc:
            messagebox.showinfo("Seleção inválida", str(exc), parent=self)
            return
        self.confirmar(resultado, pixels)
        self.destroy()
