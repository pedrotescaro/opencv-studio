"""Fluxo de segmentação por ROI, sementes morfológicas e GrabCut."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk
from editor_interface import AbaFerramenta, CANVAS, rolar_em


PADRAO = dict(bilateral_d=7, sigma_cor=50, sigma_espaco=50,
              kernel=5, erosao=2, dilatacao=2, iteracoes=5,
              fechamento=3, fechamento_iteracoes=1, area_minima=50,
              maior_componente=False)
ETAPAS = ("Original / ROI", "1. Bilateral", "3. Sementes", "4. Rótulos GrabCut",
          "5. Máscara binária", "6. Fechamento", "7. Componentes", "9. Sobreposição")
PINCEIS = {"Navegar": None, "Objeto certo": cv2.GC_FGD,
           "Fundo certo": cv2.GC_BGD, "Objeto provável": cv2.GC_PR_FGD,
           "Fundo provável": cv2.GC_PR_BGD}
CORES_SEMENTES = np.array([[0, 0, 0], [255, 255, 255], [210, 80, 20], [0, 220, 255]], np.uint8)


def validar_parametros(opcoes):
    p = dict(PADRAO, **opcoes)
    limites = {"bilateral_d": (1, 31), "sigma_cor": (1, 255), "sigma_espaco": (1, 255),
               "kernel": (1, 99), "erosao": (0, 30), "dilatacao": (0, 30),
               "iteracoes": (1, 20), "fechamento": (1, 99),
               "fechamento_iteracoes": (0, 30), "area_minima": (1, 1000000000)}
    for chave, (baixo, alto) in limites.items():
        try:
            valor = int(p[chave])
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f"Valor inválido para {chave}.") from None
        if str(valor) != str(p[chave]) or not baixo <= valor <= alto:
            raise ValueError(f"{chave}: use um inteiro entre {baixo} e {alto}.")
        p[chave] = valor
    for chave in ("bilateral_d", "kernel", "fechamento"):
        if p[chave] % 2 != 1:
            raise ValueError(f"{chave}: use um tamanho ímpar.")
    if not isinstance(p["maior_componente"], bool):
        raise ValueError("A opção de maior componente deve ser booleana.")
    return p


def criar_sementes(roi, kernel=5, erosao=2, dilatacao=2, correcoes=None):
    if roi.ndim != 2 or not roi.size or not np.any(roi):
        raise ValueError("A ROI precisa conter uma região selecionada.")
    binaria = (roi != 0).astype(np.uint8)
    elemento = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel))
    certa = cv2.erode(binaria, elemento, iterations=erosao, borderType=cv2.BORDER_CONSTANT, borderValue=0) if erosao else binaria.copy()
    entorno = cv2.dilate(binaria, elemento, iterations=dilatacao) if dilatacao else binaria.copy()
    sementes = np.full(roi.shape, cv2.GC_BGD, np.uint8)
    sementes[entorno != 0] = cv2.GC_PR_BGD
    sementes[binaria != 0] = cv2.GC_PR_FGD
    sementes[certa != 0] = cv2.GC_FGD
    if correcoes is not None:
        if correcoes.shape != roi.shape or not np.isin(correcoes, (-1, 0, 1, 2, 3)).all():
            raise ValueError("Correções incompatíveis com a imagem.")
        marcados = correcoes >= 0
        sementes[marcados] = correcoes[marcados]
    objeto = (sementes == cv2.GC_FGD) | (sementes == cv2.GC_PR_FGD)
    fundo = (sementes == cv2.GC_BGD) | (sementes == cv2.GC_PR_BGD)
    if np.count_nonzero(objeto) < 5 or np.count_nonzero(fundo) < 5:
        raise ValueError("GrabCut precisa de pelo menos cinco pixels de objeto e de fundo. Reduza a ROI ou marque fundo com o pincel.")
    return sementes


def limpar_componentes(mascara, area_minima=50, maior_componente=False):
    quantidade, rotulos, estatisticas, _ = cv2.connectedComponentsWithStats((mascara != 0).astype(np.uint8), connectivity=8)
    ids = [i for i in range(1, quantidade) if estatisticas[i, cv2.CC_STAT_AREA] >= area_minima]
    if maior_componente and ids:
        ids = [max(ids, key=lambda i: estatisticas[i, cv2.CC_STAT_AREA])]
    limpa = np.zeros(mascara.shape, np.uint8)
    regioes = []
    for i in ids:
        x, y, w, h, area = (int(v) for v in estatisticas[i])
        local = rotulos[y:y+h, x:x+w] == i
        limpa[y:y+h, x:x+w][local] = 255
        regioes.append(dict(forma="Segmentação", limites=(x, y, x+w, y+h), pixels=area,
                            mascara=local, pontos=[], inicio=None, fim=None))
    return limpa, regioes, quantidade - 1 - len(ids)


def sobrepor_contornos(imagem, mascara):
    cor = cv2.cvtColor(imagem, cv2.COLOR_GRAY2BGR) if imagem.ndim == 2 else imagem.copy()
    saida = cor.copy()
    objeto = mascara != 0
    saida[objeto] = (0.65 * cor[objeto] + 0.35 * np.array([70, 220, 70])).astype(np.uint8)
    contornos, _ = cv2.findContours(mascara.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(saida, contornos, -1, (0, 255, 255), 1)
    return saida


def segmentar_imagem(imagem, roi, opcoes=None, correcoes=None, progresso=None):
    """Cada etapa usa a resolução original; os argumentos não são modificados."""
    p = validar_parametros(opcoes or {})
    if imagem.dtype != np.uint8 or imagem.ndim not in (2, 3) or (imagem.ndim == 3 and imagem.shape[2] != 3):
        raise ValueError("Use uma imagem cinza ou BGR de 8 bits.")
    if roi.shape != imagem.shape[:2]:
        raise ValueError("A ROI deve ter as dimensões da imagem.")
    avisar = progresso or (lambda texto: None)
    avisar("1/9 — Suavizando com filtro bilateral")
    cor = cv2.cvtColor(imagem, cv2.COLOR_GRAY2BGR) if imagem.ndim == 2 else imagem
    suavizada = cv2.bilateralFilter(cor, p["bilateral_d"], p["sigma_cor"], p["sigma_espaco"])
    avisar("2–3/9 — Preparando ROI, erosão, dilatação e sementes")
    sementes = criar_sementes(roi, p["kernel"], p["erosao"], p["dilatacao"], correcoes)
    rotulos = sementes.copy()
    avisar("4/9 — Segmentando com GrabCut")
    fundo, objeto = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(suavizada, rotulos, None, fundo, objeto, p["iteracoes"], cv2.GC_INIT_WITH_MASK)
    avisar("5/9 — Gerando máscara binária")
    binaria = np.where((rotulos == cv2.GC_FGD) | (rotulos == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    avisar("6/9 — Fechamento morfológico")
    elemento = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (p["fechamento"], p["fechamento"]))
    fechada = cv2.morphologyEx(binaria, cv2.MORPH_CLOSE, elemento, iterations=p["fechamento_iteracoes"]) if p["fechamento_iteracoes"] else binaria.copy()
    # O fechamento não pode invadir o fundo certo nem apagar o objeto certo.
    fechada[sementes == cv2.GC_BGD] = 0
    fechada[sementes == cv2.GC_FGD] = 255
    avisar("7/9 — Removendo fragmentos por componentes conexos")
    final, regioes, removidos = limpar_componentes(fechada, p["area_minima"], p["maior_componente"])
    avisar("8–9/9 — Contando pixels e sobrepondo contornos")
    overlay = sobrepor_contornos(cor, final)
    for i, regiao in enumerate(regioes, 1):
        x, y, _, _ = regiao["limites"]
        cv2.putText(overlay, str(i), (x, max(14, y)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    return dict(suavizada=suavizada, sementes=sementes, rotulos=rotulos, binaria=binaria,
                fechada=fechada, mascara=final, sobreposicao=overlay, regioes=regioes,
                pixels=int(np.count_nonzero(final)), removidos=removidos, parametros=p)


class JanelaSegmentacao(AbaFerramenta):
    def __init__(self, parent, imagem, roi, confirmar):
        super().__init__(parent, "Segmentação", origem=imagem, retorno="Medições")
        self.imagem, self.roi, self.confirmar = imagem, roi.copy(), confirmar
        self.correcoes = np.full(roi.shape, -1, np.int8)
        self.resultado = None
        self.processando = self.encerrada = False
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.mensagens = Queue()
        self.poll_id = self.resize_id = None
        self.ultimo_ponto = None
        self.transformacao = None
        self.parametros = {k: tk.StringVar(value=v) for k, v in PADRAO.items() if k != "maior_componente"}
        self.maior = tk.BooleanVar(value=False)
        self.etapa = tk.StringVar(value=ETAPAS[0])
        self.zoom = tk.StringVar(value="Ajustar")
        self.pincel = tk.StringVar(value="Navegar")
        self.raio = tk.StringVar(value="5")

        topo = ttk.Frame(self, padding=8)
        topo.pack(fill="x")
        ttk.Label(topo, text="Visualização").pack(side="left")
        etapa = ttk.Combobox(topo, values=ETAPAS, textvariable=self.etapa, state="readonly", width=22)
        etapa.pack(side="left", padx=5)
        etapa.bind("<<ComboboxSelected>>", self.renderizar)
        ttk.Label(topo, text="Zoom").pack(side="left", padx=(8, 3))
        zoom = ttk.Combobox(topo, values=("Ajustar", "50%", "100%", "200%", "400%"), textvariable=self.zoom, state="readonly", width=8)
        zoom.pack(side="left")
        zoom.bind("<<ComboboxSelected>>", self.renderizar)
        ttk.Label(topo, text="Pincel").pack(side="left", padx=(8, 3))
        pincel = ttk.Combobox(topo, values=tuple(PINCEIS), textvariable=self.pincel, state="readonly", width=17)
        pincel.pack(side="left")
        ttk.Label(topo, text="Raio (px)").pack(side="left", padx=4)
        ttk.Spinbox(topo, from_=1, to=100, textvariable=self.raio, width=4).pack(side="left")

        rodape = ttk.Frame(self, padding=8)
        rodape.pack(side="bottom", fill="x")
        self.status = ttk.Label(rodape, text="Confira a ROI e as sementes antes de executar.", wraplength=650)
        self.status.pack(side="left", fill="x", expand=True)
        ttk.Button(rodape, text="Voltar às medições", command=self.fechar).pack(side="right")
        self.btn_importar = ttk.Button(rodape, text="Adicionar às medições", command=self.importar, state="disabled")
        self.btn_importar.pack(side="right", padx=5)

        principal = ttk.Frame(self)
        principal.pack(fill="both", expand=True, padx=8)
        principal.columnconfigure(0, weight=1)
        principal.rowconfigure(0, weight=1)
        visual = ttk.Frame(principal)
        visual.grid(row=0, column=0, sticky="nsew")
        visual.columnconfigure(0, weight=1)
        visual.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(visual, bg=CANVAS, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        sy = ttk.Scrollbar(visual, command=self.canvas.yview)
        sx = ttk.Scrollbar(visual, orient="horizontal", command=self.canvas.xview)
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        self.canvas.bind("<Configure>", self.agendar_render)
        self.canvas.bind("<Button-1>", self.comecar)
        self.canvas.bind("<B1-Motion>", self.arrastar)
        self.canvas.bind("<ButtonRelease-1>", self.terminar)
        self.canvas.bind("<Button-2>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B2-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-int(e.delta/120), "units"))

        lateral = ttk.Frame(principal, width=300)
        lateral.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        lateral.grid_propagate(False)
        lateral.columnconfigure(0, weight=1)
        lateral.rowconfigure(0, weight=1)
        rolagem = tk.Canvas(lateral, width=280, bg="#eef2f7", highlightthickness=0)
        rolagem.grid(row=0, column=0, sticky="nsew")
        barra = ttk.Scrollbar(lateral, command=rolagem.yview)
        barra.grid(row=0, column=1, sticky="ns")
        rolagem.configure(yscrollcommand=barra.set)
        rolar_em(self.winfo_toplevel(), lateral, rolagem)
        painel = ttk.Frame(rolagem, padding=6)
        painel_id = rolagem.create_window((0, 0), window=painel, anchor="nw")
        painel.bind("<Configure>", lambda e: rolagem.configure(scrollregion=rolagem.bbox("all")))
        rolagem.bind("<Configure>", lambda e: rolagem.itemconfigure(painel_id, width=e.width))
        painel_base = painel
        ttk.Label(painel_base, text="Refine e confira", style="Section.TLabel").pack(anchor="w")
        ttk.Label(painel_base, text="1. Confira a região e as sementes.\n2. Marque objeto ou fundo com o pincel.\n3. Execute e confira a sobreposição.",
                  wraplength=255, style="Muted.TLabel").pack(anchor="w", pady=8)
        ttk.Button(painel_base, text="Ver sementes", command=self.ver_sementes).pack(fill="x", pady=3)
        self.btn_limpar = ttk.Button(painel_base, text="Limpar marcas manuais", command=self.limpar_marcas)
        self.btn_limpar.pack(fill="x", pady=3)
        self.avancado = tk.BooleanVar(value=False)
        ttk.Checkbutton(painel_base, text="Ajustes avançados", variable=self.avancado,
                        command=self.alternar_ajustes).pack(anchor="w", pady=6)
        painel = self.ajustes_box = ttk.Frame(painel_base)
        ttk.Label(painel, text="1. Filtro bilateral", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.campo(painel, "bilateral_d", "Diâmetro (ímpar)", 1, 31)
        self.campo(painel, "sigma_cor", "Sigma de cor", 1, 255)
        self.campo(painel, "sigma_espaco", "Sigma espacial", 1, 255)
        ttk.Label(painel, text="2–3. ROI e sementes", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 0))
        self.campo(painel, "kernel", "Elemento elíptico (ímpar)", 1, 99)
        self.campo(painel, "erosao", "Erosão (iterações)", 0, 30)
        self.campo(painel, "dilatacao", "Dilatação (iterações)", 0, 30)
        ttk.Label(painel, text="Branco: objeto certo\nPreto: fundo certo\nAmarelo: objeto provável\nAzul: fundo provável", wraplength=255).pack(anchor="w", pady=4)
        ttk.Label(painel, text="Se o núcleo da ROI inclui fundo, aumente a erosão ou corrija com o pincel. As marcas manuais prevalecem sobre as sementes geradas.", wraplength=255).pack(anchor="w", pady=4)
        ttk.Label(painel, text="4. GrabCut", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 0))
        self.campo(painel, "iteracoes", "Iterações", 1, 20)
        ttk.Label(painel, text="5–6. Máscara e fechamento", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 0))
        self.campo(painel, "fechamento", "Elemento elíptico (ímpar)", 1, 99)
        self.campo(painel, "fechamento_iteracoes", "Fechamento (0 desliga)", 0, 30)
        ttk.Label(painel, text="7. Componentes conexos", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 0))
        self.campo(painel, "area_minima", "Área mínima (pixels)", 1, 1000000000)
        ttk.Checkbutton(painel, text="Manter apenas o maior", variable=self.maior).pack(anchor="w")
        painel = self.resultados_box = ttk.Frame(painel_base)
        painel.pack(fill="x")
        ttk.Label(painel, text="8–9. Área e conferência", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 0))
        ttk.Label(painel, text="Objeto branco e fundo preto na máscara final. A contagem usa pixels brancos, incluindo buracos e bordas conforme a máscara. Confira a sobreposição antes de adicionar.", wraplength=255).pack(anchor="w", pady=4)
        self.tabela = ttk.Treeview(painel, columns=("objeto", "pixels"), show="headings", height=4, selectmode="extended")
        self.tabela.heading("objeto", text="Componente")
        self.tabela.heading("pixels", text="Pixels / px²")
        self.tabela.column("objeto", width=100)
        self.tabela.column("pixels", width=125, anchor="e")
        self.tabela.pack(fill="x", pady=4)
        self.btn_mascara = ttk.Button(painel, text="Salvar máscara PNG", command=lambda: self.salvar("mascara"), state="disabled")
        self.btn_mascara.pack(fill="x", pady=3)
        self.btn_overlay = ttk.Button(painel, text="Salvar sobreposição PNG", command=lambda: self.salvar("sobreposicao"), state="disabled")
        self.btn_overlay.pack(fill="x")
        acoes = ttk.Frame(lateral, padding=(0, 6))
        acoes.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.btn_executar = ttk.Button(acoes, text="Executar fluxo completo", command=self.executar, style="Accent.TButton")
        self.btn_executar.pack(fill="x")
        self.progress = ttk.Progressbar(acoes, mode="indeterminate")
        self.progress.pack(fill="x", pady=(4, 0))
        for var in (*self.parametros.values(), self.maior):
            var.trace_add("write", self.invalidar)

    def ao_enter(self):
        self.executar()

    def alternar_ajustes(self):
        if self.avancado.get():
            self.ajustes_box.pack(fill="x", before=self.resultados_box)
        else:
            self.ajustes_box.pack_forget()

    def campo(self, painel, chave, titulo, baixo, alto):
        linha = ttk.Frame(painel)
        linha.pack(fill="x", pady=2)
        ttk.Label(linha, text=titulo).pack(side="left")
        ttk.Spinbox(linha, from_=baixo, to=alto, textvariable=self.parametros[chave], width=7).pack(side="right")

    def opcoes(self):
        return validar_parametros({**{k: v.get() for k, v in self.parametros.items()}, "maior_componente": self.maior.get()})

    def invalidar(self, *_args):
        self.resultado = None
        self.btn_importar.state(["disabled"])
        self.btn_mascara.state(["disabled"])
        self.btn_overlay.state(["disabled"])
        for item in self.tabela.get_children():
            self.tabela.delete(item)
        self.status.config(text="Configuração ou marcas alteradas. Execute novamente para atualizar a área.")
        self.agendar_render()

    def ver_sementes(self):
        try:
            p = self.opcoes()
            criar_sementes(self.roi, p["kernel"], p["erosao"], p["dilatacao"], self.correcoes)
        except ValueError as exc:
            messagebox.showinfo("Sementes", str(exc), parent=self)
            return
        self.etapa.set(ETAPAS[2])
        self.renderizar()

    def limpar_marcas(self):
        if self.processando:
            return
        self.correcoes.fill(-1)
        self.invalidar()

    def imagem_visual(self):
        indice = ETAPAS.index(self.etapa.get())
        if self.resultado is not None:
            chaves = (None, "suavizada", "sementes", "rotulos", "binaria", "fechada", "mascara", "sobreposicao")
            if indice:
                imagem = self.resultado[chaves[indice]]
                return CORES_SEMENTES[imagem] if indice in (2, 3) else imagem
        if indice == 2:
            try:
                p = self.opcoes()
                sementes = criar_sementes(self.roi, p["kernel"], p["erosao"], p["dilatacao"], self.correcoes)
                return CORES_SEMENTES[sementes]
            except ValueError:
                pass
        cor = cv2.cvtColor(self.imagem, cv2.COLOR_GRAY2BGR) if self.imagem.ndim == 2 else self.imagem.copy()
        contornos, _ = cv2.findContours(self.roi, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(cor, contornos, -1, (0, 255, 255), 1)
        for valor in range(4):
            cor[self.correcoes == valor] = CORES_SEMENTES[valor]
        return cor

    def agendar_render(self, _evento=None):
        if self.resize_id is not None:
            self.after_cancel(self.resize_id)
        self.resize_id = self.after(80, self.renderizar)

    def renderizar(self, _evento=None):
        if self.encerrada:
            return
        if self.resize_id is not None:
            self.after_cancel(self.resize_id)
            self.resize_id = None
        imagem = self.imagem_visual()
        rgb = cv2.cvtColor(imagem, cv2.COLOR_GRAY2RGB if imagem.ndim == 2 else cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        escala = min(cw/w, ch/h, 1) if self.zoom.get() == "Ajustar" else float(self.zoom.get().strip("%"))/100
        dw, dh = max(1, int(w*escala)), max(1, int(h*escala))
        ox, oy = max(0, (cw-dw)/2), max(0, (ch-dh)/2)
        self.transformacao = (ox, oy, dw/w, dh/h)
        self.foto = ImageTk.PhotoImage(Image.fromarray(rgb).resize((dw, dh), Image.Resampling.NEAREST if escala >= 1 else Image.Resampling.LANCZOS), master=self.canvas)
        self.canvas.delete("all")
        self.canvas.create_image(ox, oy, image=self.foto, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, max(cw, dw), max(ch, dh)))

    def coordenada(self, evento):
        if self.transformacao is None:
            return None
        ox, oy, sx, sy = self.transformacao
        h, w = self.roi.shape
        x, y = (self.canvas.canvasx(evento.x)-ox)/sx, (self.canvas.canvasy(evento.y)-oy)/sy
        return (int(x), int(y)) if 0 <= x < w and 0 <= y < h else None

    def comecar(self, evento):
        if self.processando:
            return
        self.ultimo_ponto = None
        if self.pincel.get() == "Navegar":
            self.canvas.scan_mark(evento.x, evento.y)
        else:
            self.pintar(evento)

    def arrastar(self, evento):
        if self.processando:
            return
        if self.pincel.get() == "Navegar":
            self.canvas.scan_dragto(evento.x, evento.y, gain=1)
        else:
            self.pintar(evento)

    def terminar(self, _evento=None):
        self.ultimo_ponto = None

    def pintar(self, evento):
        ponto = self.coordenada(evento)
        if ponto is None:
            self.ultimo_ponto = None
            return
        try:
            raio = int(self.raio.get())
            if not 1 <= raio <= 100:
                raise ValueError()
        except ValueError:
            self.status.config(text="Raio do pincel: use um inteiro entre 1 e 100 pixels.")
            return
        valor = PINCEIS[self.pincel.get()]
        if valor is None:
            return
        if self.ultimo_ponto is not None:
            cv2.line(self.correcoes, self.ultimo_ponto, ponto, valor, 2*raio+1)
        cv2.circle(self.correcoes, ponto, raio, valor, -1)
        self.ultimo_ponto = ponto
        self.invalidar()

    def executar(self):
        if self.processando:
            return
        try:
            p = self.opcoes()
            criar_sementes(self.roi, p["kernel"], p["erosao"], p["dilatacao"], self.correcoes)
        except ValueError as exc:
            messagebox.showinfo("Configuração inválida", str(exc), parent=self)
            return
        self.invalidar()
        self.processando = True
        self.btn_executar.state(["disabled"])
        self.btn_limpar.state(["disabled"])
        self.progress.start(12)
        self.status.config(text="Iniciando fluxo…")
        self.opcoes_em_execucao = p
        self.future = self.executor.submit(segmentar_imagem, self.imagem, self.roi, p, self.correcoes.copy(), self.mensagens.put)
        self.poll_id = self.after(50, self.verificar)

    def verificar(self):
        self.poll_id = None
        if self.encerrada:
            return
        try:
            while True:
                self.status.config(text=self.mensagens.get_nowait())
        except Empty:
            pass
        if not self.future.done():
            self.poll_id = self.after(80, self.verificar)
            return
        self.processando = False
        self.progress.stop()
        self.btn_executar.state(["!disabled"])
        self.btn_limpar.state(["!disabled"])
        try:
            resultado = self.future.result()
            if self.opcoes() != self.opcoes_em_execucao:
                self.status.config(text="Parâmetros alterados durante o processamento. Execute novamente.")
                return
            self.resultado = resultado
        except (ValueError, cv2.error) as exc:
            self.status.config(text="Não foi possível segmentar. Revise a ROI e as sementes.")
            messagebox.showerror("Segmentação", str(exc), parent=self)
            return
        except Exception as exc:
            messagebox.showerror("Erro na segmentação", str(exc), parent=self)
            return
        for i, regiao in enumerate(resultado["regioes"]):
            self.tabela.insert("", "end", iid=str(i), values=(f"Objeto {i+1}", f"{regiao['pixels']:,}"))
        self.tabela.selection_set(self.tabela.get_children())
        self.btn_importar.state(["!disabled"] if resultado["regioes"] else ["disabled"])
        self.btn_mascara.state(["!disabled"])
        self.btn_overlay.state(["!disabled"])
        self.etapa.set(ETAPAS[-1])
        self.status.config(text=f"{len(resultado['regioes'])} objeto(s) | {resultado['pixels']:,} pixels / px² | {resultado['removidos']} fragmento(s) removido(s). Selecione na tabela os componentes a adicionar.")
        self.renderizar()

    def importar(self):
        if self.resultado is None or self.processando:
            return
        selecionados = self.tabela.selection()
        if not selecionados:
            self.status.config(text="Selecione pelo menos um componente na tabela.")
            return
        regioes = [self.resultado["regioes"][int(i)] for i in selecionados]
        self.confirmar(regioes)
        self.fechar()

    def salvar(self, chave):
        if self.resultado is None:
            return
        path = filedialog.asksaveasfilename(parent=self, title="Salvar resultado", defaultextension=".png", filetypes=[("PNG", "*.png")])
        if not path:
            return
        try:
            ok, buffer = cv2.imencode(".png", self.resultado[chave])
            if not ok:
                raise ValueError("Não foi possível codificar o PNG.")
            buffer.tofile(path)
        except (OSError, ValueError, cv2.error) as exc:
            messagebox.showerror("Erro ao salvar", str(exc), parent=self)

    def fechar(self):
        self.destroy()

    def destroy(self):
        if not self.winfo_exists():
            return
        self.encerrada = True
        for tarefa in (self.poll_id, self.resize_id):
            if tarefa is not None:
                self.after_cancel(tarefa)
        self.poll_id = self.resize_id = None
        self.executor.shutdown(wait=False, cancel_futures=True)
        super().destroy()
