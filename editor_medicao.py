"""Mede regiões independentes na resolução da imagem, sem alterar seus pixels."""
import csv
import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

from editor_recorte import FORMAS_RECORTE, limites_recorte, mascara_recorte
from editor_interface import AbaFerramenta, CANVAS, VisualizacaoRedimensionavel


FORMAS_MEDICAO = ("Polígono", "Desenho livre") + FORMAS_RECORTE


def mascara_poligono(tamanho, pontos):
    """Rasteriza pelo centro de cada pixel; retorna máscara local e seus limites.

    Bordas pertencem à região. Contornos cruzados usam a regra par/ímpar.
    Coordenadas representam bordas de pixels, não índices inclusivos do OpenCV.
    """
    h, w = tamanho[:2]
    vertices = np.asarray(pontos, dtype=float)
    if vertices.ndim != 2 or vertices.shape[1] != 2 or len(vertices) < 3 or not np.isfinite(vertices).all():
        raise ValueError("Marque pelo menos três pontos para formar um contorno.")
    if np.linalg.matrix_rank(vertices - vertices[0]) < 2:
        raise ValueError("O contorno precisa formar uma área, não apenas uma linha.")
    x0 = max(0, min(w, int(np.floor(vertices[:, 0].min()))))
    y0 = max(0, min(h, int(np.floor(vertices[:, 1].min()))))
    x1 = max(0, min(w, int(np.ceil(vertices[:, 0].max()))))
    y1 = max(0, min(h, int(np.ceil(vertices[:, 1].max()))))
    y, x = np.ogrid[y0:y1, x0:x1]
    x, y = x + 0.5, y + 0.5
    dentro = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    borda = np.zeros_like(dentro)
    for a, b in zip(vertices, np.roll(vertices, -1, axis=0)):
        ax, ay = a
        bx, by = b
        if ay != by:
            cruza = (ay > y) != (by > y)
            dentro ^= cruza & (x < ax + (y - ay) * (bx - ax) / (by - ay))
        if ax != bx or ay != by:
            produto = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
            borda |= (np.abs(produto) < 1e-9) & (x >= min(ax, bx)) & (x <= max(ax, bx)) & (y >= min(ay, by)) & (y <= max(ay, by))
    mascara = dentro | borda
    if not mascara.any():
        raise ValueError("O contorno não contém pixels. Selecione uma área maior.")
    return mascara, (x0, y0, x1, y1)


def medir_regiao(tamanho, forma, inicio=None, fim=None, pontos=()):
    if forma in ("Polígono", "Desenho livre"):
        mascara, limites = mascara_poligono(tamanho, pontos)
    else:
        limites = limites_recorte(tamanho, inicio, fim, forma)
        x0, y0, x1, y1 = limites
        mascara = mascara_recorte(x1 - x0, y1 - y0, forma)
    pixels = int(np.count_nonzero(mascara))
    if not pixels:
        raise ValueError("Selecione uma região com pelo menos um pixel.")
    return dict(forma=forma, inicio=inicio, fim=fim, pontos=list(pontos), limites=limites, pixels=pixels)


def calcular_escala(pontos, distancia):
    distancia = float(str(distancia).replace(",", "."))
    pixels = math.dist(*pontos)
    if not math.isfinite(distancia) or distancia <= 0 or not math.isfinite(pixels) or pixels <= 0:
        raise ValueError("A distância real e a linha de referência devem ser maiores que zero.")
    return distancia / pixels


def area_calibrada(pixels, escala):
    return None if escala is None else pixels * escala ** 2


class JanelaMedicao(AbaFerramenta):
    def __init__(self, parent, imagem, dados):
        super().__init__(parent, "Medições", origem=imagem)
        self.imagem, self.dados = imagem, dados
        dados.setdefault("regioes", [])
        dados.setdefault("escala", None)
        dados.setdefault("unidade", "cm")
        dados.setdefault("referencia", [])
        self.forma = tk.StringVar(value="Polígono")
        self.nome = tk.StringVar(value=f"Objeto {len(dados['regioes']) + 1}")
        self.zoom = tk.StringVar(value="Ajustar")
        self.distancia = tk.StringVar(value=dados.get("distancia", ""))
        self.unidade = tk.StringVar(value=dados["unidade"])
        self.inicio = self.fim = None
        self.pontos = []
        self.fechado = False
        self.arrastando = False
        self.calibrando = False
        self.referencia = list(dados["referencia"])
        self.transformacao = None

        topo = ttk.Frame(self, padding=(8, 4))
        topo.pack(fill="x")
        ttk.Label(topo, text="Seleção").pack(side="left")
        combo = ttk.Combobox(topo, textvariable=self.forma, values=FORMAS_MEDICAO, state="readonly", width=17)
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", self.nova_selecao)
        ttk.Button(topo, text="Nova seleção", command=self.nova_selecao).pack(side="left")
        ttk.Button(topo, text="Voltar um ponto", command=self.remover_ponto).pack(side="left", padx=4)
        ttk.Button(topo, text="Fechar contorno", command=self.fechar_contorno, style="Accent.TButton").pack(side="left")
        zoom_box = ttk.Frame(topo)
        zoom_box.pack(side="right")
        ttk.Label(zoom_box, text="Zoom", style="Muted.TLabel").pack(side="left", padx=4)
        zoom = ttk.Combobox(zoom_box, textvariable=self.zoom, values=("Ajustar", "25%", "50%", "100%", "200%", "400%"), width=8, state="readonly")
        zoom.pack(side="left")
        zoom.bind("<<ComboboxSelected>>", self.renderizar)
        self.visualizacao = VisualizacaoRedimensionavel(self)
        self.visualizacao.pack(fill="both", expand=True, padx=8)
        controles = self.visualizacao.controles
        detalhes = ttk.Frame(controles)

        self.escala_aberta = tk.BooleanVar(value=dados["escala"] is not None)
        ttk.Checkbutton(detalhes, text="Configurar escala física (opcional)", variable=self.escala_aberta,
                        command=self.alternar_escala).pack(anchor="w", padx=8)
        escala = self.escala_box = ttk.LabelFrame(detalhes, text="Comprimento conhecido na imagem", padding=8)
        ttk.Button(escala, text="Marcar referência (2 cliques)", command=self.marcar_referencia).pack(side="left")
        ttk.Label(escala, text="Distância real").pack(side="left", padx=5)
        ttk.Entry(escala, textvariable=self.distancia, width=9).pack(side="left")
        ttk.Combobox(escala, textvariable=self.unidade, values=("cm", "m"), width=4, state="readonly").pack(side="left", padx=4)
        ttk.Button(escala, text="Calibrar", command=self.calibrar).pack(side="left")
        ttk.Button(escala, text="Limpar escala", command=self.limpar_escala).pack(side="left", padx=4)
        self.info_escala = ttk.Label(detalhes, wraplength=850)
        self.info_escala.pack(fill="x", padx=10, pady=(0, 4))
        self.alternar_escala()

        rodape = ttk.Frame(controles, padding=8)
        rodape.pack(side="bottom", fill="x")
        ttk.Button(rodape, text="Voltar ao editor", command=self.destroy).pack(side="right")
        ttk.Button(rodape, text="Exportar medições CSV", command=self.exportar).pack(side="right", padx=6)
        ttk.Button(rodape, text="Excluir medição", command=self.excluir).pack(side="left")

        resultados_container = ttk.Frame(controles, padding=(8, 0))
        resultados_container.pack(side="bottom", fill="x")
        self.mostrar_resultados = tk.BooleanVar(value=bool(dados["regioes"]))
        self.resultados_cabecalho = ttk.Checkbutton(resultados_container, text="Resultados",
            variable=self.mostrar_resultados, command=self.alternar_resultados)
        self.resultados_cabecalho.pack(anchor="w")
        resultados = self.resultados_box = ttk.Frame(resultados_container)
        self.tabela = ttk.Treeview(resultados, columns=("nome", "pixels", "percentual", "area"), show="headings", height=3, selectmode="extended")
        for chave, titulo, largura in (("nome", "Objeto", 240), ("pixels", "Pixels / área em px²", 170), ("percentual", "% da imagem", 130), ("area", "Área física estimada", 230)):
            self.tabela.heading(chave, text=titulo)
            self.tabela.column(chave, width=largura, anchor="w" if chave == "nome" else "e")
        self.tabela.pack(side="left", fill="x", expand=True)
        barra = ttk.Scrollbar(resultados, command=self.tabela.yview)
        barra.pack(side="right", fill="y")
        self.tabela.configure(yscrollcommand=barra.set)

        detalhes.pack(side="bottom", fill="x")
        selecionar = ttk.Frame(controles, padding=8)
        selecionar.pack(side="bottom", fill="x")
        ttk.Label(selecionar, text="Nome").pack(side="left")
        ttk.Entry(selecionar, textvariable=self.nome, width=24).pack(side="left", padx=6)
        self.btn_adicionar = ttk.Button(selecionar, text="Adicionar medição", command=self.adicionar, state="disabled", style="Accent.TButton")
        self.btn_adicionar.pack(side="left")
        self.btn_segmentar = ttk.Button(selecionar, text="Segmentar ROI…", command=self.abrir_segmentacao, state="disabled")
        self.btn_segmentar.pack(side="left", padx=6)
        self.info = ttk.Label(controles, text="Nenhuma seleção.", wraplength=850, style="Muted.TLabel")
        self.info.pack(side="bottom", anchor="w", padx=12, pady=(4, 0))

        self.ajuda = ttk.Label(controles, wraplength=850, style="Muted.TLabel")
        self.ajuda.pack(fill="x", padx=10, pady=4)
        visual = self.visualizacao.visual
        visual.rowconfigure(0, weight=1)
        visual.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(visual, bg=CANVAS, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        sy = ttk.Scrollbar(visual, orient="vertical", command=self.canvas.yview)
        sx = ttk.Scrollbar(visual, orient="horizontal", command=self.canvas.xview)
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        self.canvas.bind("<Configure>", self.renderizar)
        self.canvas.bind("<Button-1>", self.comecar)
        self.canvas.bind("<B1-Motion>", self.arrastar)
        self.canvas.bind("<ButtonRelease-1>", self.terminar)
        self.canvas.bind("<Button-3>", self.fechar_contorno)
        self.canvas.bind("<Button-2>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B2-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-int(e.delta / 120), "units"))
        self.bind("<Escape>", self.nova_selecao)
        self.bind("<BackSpace>", lambda e: self.remover_ponto() if e.widget == self.canvas else None)
        self.nova_selecao()
        self.atualizar_tabela()

    def ao_enter(self):
        self.fechar_contorno()

    def ao_escape(self):
        self.nova_selecao()

    def alternar_escala(self):
        if self.escala_aberta.get():
            self.escala_box.pack(fill="x", padx=8, pady=4, before=self.info_escala)
        else:
            self.escala_box.pack_forget()

    def alternar_resultados(self):
        if self.mostrar_resultados.get():
            self.resultados_box.pack(fill="x")
        else:
            self.resultados_box.pack_forget()

    def nova_selecao(self, _evento=None):
        self.inicio = self.fim = None
        self.pontos = []
        self.fechado = self.arrastando = self.calibrando = False
        self.btn_adicionar.state(["disabled"])
        self.btn_segmentar.state(["disabled"])
        self.info.config(text="Nenhuma seleção.")
        forma = self.forma.get()
        texto = ("Clique ao redor do objeto e feche o contorno (Enter ou botão direito)." if forma == "Polígono" else
                 "Arraste ao redor do objeto e solte para fechar o contorno." if forma == "Desenho livre" else
                 "Arraste na imagem para delimitar a região.")
        self.ajuda.config(text=texto + " Depois adicione a medição ou refine com Segmentar ROI.")
        self.desenhar()

    def renderizar(self, _evento=None):
        h, w = self.imagem.shape[:2]
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        escala = min(cw / w, ch / h, 1) if self.zoom.get() == "Ajustar" else float(self.zoom.get().strip("%")) / 100
        dw, dh = max(1, int(w * escala)), max(1, int(h * escala))
        ox, oy = max(0, (cw - dw) / 2), max(0, (ch - dh) / 2)
        self.transformacao = (ox, oy, dw / w, dh / h)
        rgb = cv2.cvtColor(self.imagem, cv2.COLOR_GRAY2RGB if self.imagem.ndim == 2 else cv2.COLOR_BGR2RGB)
        self.foto = ImageTk.PhotoImage(Image.fromarray(rgb).resize((dw, dh), Image.Resampling.NEAREST if escala >= 1 else Image.Resampling.LANCZOS), master=self.canvas)
        self.canvas.delete("all")
        self.canvas.create_image(ox, oy, image=self.foto, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, max(cw, dw), max(ch, dh)))
        self.desenhar()

    def coordenada(self, evento, exigir_dentro=False):
        if self.transformacao is None:
            return None
        ox, oy, sx, sy = self.transformacao
        h, w = self.imagem.shape[:2]
        x, y = (self.canvas.canvasx(evento.x) - ox) / sx, (self.canvas.canvasy(evento.y) - oy) / sy
        if exigir_dentro and not (0 <= x <= w and 0 <= y <= h):
            return None
        return (int(np.clip(round(x), 0, w)), int(np.clip(round(y), 0, h)))

    def comecar(self, evento):
        ponto = self.coordenada(evento, True)
        if ponto is None:
            return
        self.canvas.focus_set()
        if self.calibrando:
            self.referencia.append(ponto)
            if len(self.referencia) == 2:
                self.calibrando = False
                self.ajuda.config(text="Referência marcada. Informe a distância real e clique em Calibrar.")
            self.desenhar()
            return
        forma = self.forma.get()
        if forma == "Polígono":
            if self.fechado:
                self.nova_selecao()
            self.pontos.append(ponto)
            self.desenhar()
            return
        self.inicio = self.fim = ponto
        self.pontos = [ponto]
        self.fechado = False
        self.arrastando = True
        self.btn_adicionar.state(["disabled"])
        self.btn_segmentar.state(["disabled"])
        self.desenhar()

    def arrastar(self, evento):
        if not self.arrastando:
            return
        self.fim = self.coordenada(evento)
        if self.forma.get() == "Desenho livre" and self.fim != self.pontos[-1]:
            self.pontos.append(self.fim)
        self.desenhar()

    def terminar(self, evento):
        if self.arrastando:
            self.arrastar(evento)
            self.arrastando = False
            self.fechar_contorno()

    def remover_ponto(self):
        if self.pontos:
            self.pontos.pop()
            self.fechado = False
            self.btn_adicionar.state(["disabled"])
            self.btn_segmentar.state(["disabled"])
            self.info.config(text="Contorno aberto. Feche para medir.")
            self.desenhar()

    def regiao_atual(self):
        return medir_regiao(self.imagem.shape, self.forma.get(), self.inicio, self.fim, self.pontos)

    def fechar_contorno(self, _evento=None):
        if self.calibrando:
            return
        try:
            regiao = self.regiao_atual()
        except (ValueError, TypeError) as exc:
            self.info.config(text=str(exc) if isinstance(exc, ValueError) else "Selecione uma região primeiro.")
            self.btn_adicionar.state(["disabled"])
            self.btn_segmentar.state(["disabled"])
            return
        self.fechado = True
        self.btn_adicionar.state(["!disabled"])
        self.btn_segmentar.state(["!disabled"])
        self.info.config(text=self.texto_medida(regiao))
        self.desenhar()

    def texto_medida(self, regiao):
        area = area_calibrada(regiao["pixels"], self.dados["escala"])
        return f"Área: {regiao['pixels']:,} px² ({regiao['pixels']:,} pixels)" + (f" | ≈ {area:.6g} {self.dados['unidade']}²" if area is not None else "")

    def adicionar(self):
        if not self.fechado:
            return
        regiao = self.regiao_atual()
        regiao["nome"] = self.nome.get().strip() or f"Objeto {len(self.dados['regioes']) + 1}"
        self.dados["regioes"].append(regiao)
        self.mostrar_resultados.set(True)
        self.nome.set(f"Objeto {len(self.dados['regioes']) + 1}")
        self.nova_selecao()
        self.atualizar_tabela()

    def abrir_segmentacao(self):
        if not self.fechado:
            return
        from editor_segmentacao import JanelaSegmentacao
        regiao = self.regiao_atual()
        x0, y0, x1, y1 = regiao["limites"]
        if self.forma.get() in ("Polígono", "Desenho livre"):
            mascara, _ = mascara_poligono(self.imagem.shape, self.pontos)
        else:
            mascara = mascara_recorte(x1-x0, y1-y0, self.forma.get())
        roi = np.zeros(self.imagem.shape[:2], np.uint8)
        roi[y0:y1, x0:x1] = mascara.astype(np.uint8) * 255
        existente = self.editor.paginas.get("Segmentação") if self.editor is not None else None
        if isinstance(existente, AbaFerramenta):
            existente.destroy()
        JanelaSegmentacao(self, self.imagem, roi, self.adicionar_segmentacao)

    def adicionar_segmentacao(self, regioes):
        nome = self.nome.get().strip() or "Objeto"
        for i, regiao in enumerate(regioes, 1):
            self.dados["regioes"].append(dict(regiao, nome=nome if len(regioes) == 1 else f"{nome} / {i}"))
        self.mostrar_resultados.set(True)
        self.nome.set(f"Objeto {len(self.dados['regioes']) + 1}")
        self.nova_selecao()
        self.atualizar_tabela()

    def excluir(self):
        indices = {int(i) for i in self.tabela.selection()}
        self.dados["regioes"][:] = [r for i, r in enumerate(self.dados["regioes"]) if i not in indices]
        self.atualizar_tabela()
        self.desenhar()

    def marcar_referencia(self):
        self.nova_selecao()
        self.referencia = []
        self.calibrando = True
        self.ajuda.config(text="Clique nas duas extremidades de uma distância conhecida, no mesmo plano e profundidade dos objetos. Depois informe a distância real e clique em Calibrar.")
        self.desenhar()

    def calibrar(self):
        if len(self.referencia) != 2:
            messagebox.showinfo("Referência", "Marque dois pontos de uma distância conhecida.", parent=self)
            return
        try:
            escala = calcular_escala(self.referencia, self.distancia.get())
        except ValueError as exc:
            messagebox.showinfo("Escala inválida", str(exc), parent=self)
            return
        self.dados.update(escala=escala, unidade=self.unidade.get(), referencia=list(self.referencia), distancia=self.distancia.get())
        self.atualizar_tabela()
        if self.fechado:
            self.info.config(text=self.texto_medida(self.regiao_atual()))

    def limpar_escala(self):
        self.dados.update(escala=None, referencia=[], distancia="")
        self.referencia = []
        self.calibrando = False
        self.distancia.set("")
        self.atualizar_tabela()
        self.desenhar()
        if self.fechado:
            self.info.config(text=self.texto_medida(self.regiao_atual()))

    def atualizar_tabela(self):
        quantidade = len(self.dados["regioes"])
        self.resultados_cabecalho.configure(text=f"Resultados ({quantidade}) — mostrar / ocultar")
        self.tabela.configure(height=max(1, min(3, quantidade)))
        self.alternar_resultados()
        for item in self.tabela.get_children():
            self.tabela.delete(item)
        total = self.imagem.shape[0] * self.imagem.shape[1]
        for i, regiao in enumerate(self.dados["regioes"]):
            area = area_calibrada(regiao["pixels"], self.dados["escala"])
            self.tabela.insert("", "end", iid=str(i), values=(regiao["nome"], f"{regiao['pixels']:,}", f"{100 * regiao['pixels'] / total:.3f}%", "Sem escala" if area is None else f"≈ {area:.6g} {self.dados['unidade']}²"))
        escala = self.dados["escala"]
        self.info_escala.config(text="Área em px² • defina uma escala para estimar cm² ou m²." if escala is None else
            f"Escala: {escala:.6g} {self.dados['unidade']}/pixel • área física estimada da projeção visível; a perspectiva altera a escala.")

    def desenhar_regiao(self, regiao, cor, fechado=True):
        ox, oy, sx, sy = self.transformacao
        opts = dict(outline=cor, width=2, tags="contornos")
        if regiao["forma"] == "Segmentação":
            x0, y0, _, _ = regiao["limites"]
            contornos, _ = cv2.findContours(regiao["mascara"].astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for contorno in contornos:
                pontos = contorno.reshape(-1, 2)
                coords = [v for x, y in pontos for v in (ox+(x0+x+0.5)*sx, oy+(y0+y+0.5)*sy)]
                if len(pontos) >= 3:
                    self.canvas.create_polygon(*coords, fill="", **opts)
                elif len(pontos) == 2:
                    self.canvas.create_line(*coords, fill=cor, width=2, tags="contornos")
                else:
                    a, b = coords
                    self.canvas.create_oval(a-1, b-1, a+1, b+1, outline=cor, tags="contornos")
            return
        if regiao["forma"] in ("Polígono", "Desenho livre"):
            pontos = regiao["pontos"]
            coords = [v for x, y in pontos for v in (ox + x * sx, oy + y * sy)]
            if len(pontos) >= 3 and fechado:
                self.canvas.create_polygon(*coords, fill="", **opts)
            elif len(pontos) >= 2:
                self.canvas.create_line(*coords, fill=cor, width=2, tags="contornos")
            if not fechado:
                for x, y in pontos:
                    a, b = ox + x * sx, oy + y * sy
                    self.canvas.create_oval(a-2, b-2, a+2, b+2, fill=cor, outline=cor, tags="contornos")
            return
        if regiao.get("inicio") is None:
            return
        x0, y0, x1, y1 = limites_recorte(self.imagem.shape, regiao["inicio"], regiao["fim"], regiao["forma"])
        a, b, c, d = ox + x0 * sx, oy + y0 * sy, ox + x1 * sx, oy + y1 * sy
        if regiao["forma"] in ("Elipse", "Círculo"):
            self.canvas.create_oval(a, b, c, d, **opts)
        elif regiao["forma"] == "Losango":
            self.canvas.create_polygon((a+c)/2, b, c, (b+d)/2, (a+c)/2, d, a, (b+d)/2, fill="", **opts)
        else:
            self.canvas.create_rectangle(a, b, c, d, **opts)

    def desenhar(self):
        if self.transformacao is None:
            return
        self.canvas.delete("contornos")
        ox, oy, sx, sy = self.transformacao
        for regiao in self.dados["regioes"]:
            self.desenhar_regiao(regiao, "#67e8a0")
            x0, y0, _, _ = regiao["limites"]
            self.canvas.create_text(ox+x0*sx, oy+y0*sy, text=regiao["nome"], fill="#67e8a0", anchor="sw", tags="contornos")
        self.desenhar_regiao(dict(forma=self.forma.get(), inicio=self.inicio, fim=self.fim, pontos=self.pontos), "#ffe477", self.fechado)
        if len(self.referencia) == 2:
            coords = [v for x, y in self.referencia for v in (ox+x*sx, oy+y*sy)]
            self.canvas.create_line(*coords, fill="#ff9f43", width=3, tags="contornos")
        for x, y in self.referencia:
            a, b = ox+x*sx, oy+y*sy
            self.canvas.create_oval(a-3, b-3, a+3, b+3, fill="#ff9f43", tags="contornos")

    def exportar(self):
        if not self.dados["regioes"]:
            messagebox.showinfo("Medições", "Adicione uma medição antes de exportar.", parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, title="Exportar áreas", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as arquivo:
                writer = csv.writer(arquivo, delimiter=";")
                writer.writerow(("Objeto", "Forma", "Pixels", "Area_px2", "Percentual_imagem", "Area_fisica_estimada", "Unidade_area", "Escala_unidade_por_pixel", "Imagem_largura", "Imagem_altura", "Observacao"))
                h, w = self.imagem.shape[:2]
                for regiao in self.dados["regioes"]:
                    area = area_calibrada(regiao["pixels"], self.dados["escala"])
                    writer.writerow((regiao["nome"], regiao["forma"], regiao["pixels"], regiao["pixels"], 100*regiao["pixels"]/(w*h), "" if area is None else area, "" if area is None else self.dados["unidade"]+"²", self.dados["escala"] or "", w, h, "Projecao visivel; area fisica estimada com escala uniforme"))
        except OSError as exc:
            messagebox.showerror("Erro ao exportar", str(exc), parent=self)
