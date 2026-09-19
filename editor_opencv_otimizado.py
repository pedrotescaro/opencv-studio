import sys
import subprocess
import importlib.util


def instalar_dependencias():
    """Instala automaticamente apenas as dependências que estiverem faltando."""
    dependencias = {
        "cv2": "opencv-python",
        "numpy": "numpy",
        "PIL": "Pillow",
    }

    faltando = [
        pacote_pip
        for modulo, pacote_pip in dependencias.items()
        if importlib.util.find_spec(modulo) is None
    ]

    if not faltando:
        return

    print("Dependências ausentes:", ", ".join(faltando))
    print("Instalando automaticamente...\n")

    subprocess.check_call([
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        *faltando,
    ])


try:
    if __name__ == "__main__":
        instalar_dependencias()
except Exception as erro:
    print("Não foi possível instalar as dependências automaticamente.")
    print("Erro:", erro)
    print("\nTente manualmente:")
    print(f'"{sys.executable}" -m pip install opencv-python numpy Pillow')
    raise


import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
from concurrent.futures import ThreadPoolExecutor


from editor_recursos import (RecursosEditor, MORFOLOGIA, EXTRAS, PARAMETROS,
                             aplicar_morfologia, processar_extra)


class EditorOpenCV(RecursosEditor):
    def __init__(self, root):
        self.root = root
        self.inicializar_recursos()
        self.root.title("OpenCV Studio")
        self.root.geometry("1450x900")
        self.root.minsize(1050, 680)

        # Estado da imagem
        self.original = None
        self.atual = None
        self.preview = None
        self.caminho_atual = None

        # Histórico
        self.undo_stack = []
        self.redo_stack = []
        self.max_historico = 25

        # Processamento assíncrono: uma operação pesada por vez
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.processando = False
        self.preview_pendente = False
        self.preview_job_id = 0
        self.debounce_id = None
        self.resize_debounce_id = None

        # UI / preview
        self.live_preview = tk.BooleanVar(value=True)
        self.zoom = tk.DoubleVar(value=1.0)
        self.filtro_var = tk.StringVar()
        self.categoria_var = tk.StringVar()
        self.param1 = tk.DoubleVar(value=50)
        self.param2 = tk.DoubleVar(value=100)

        self.filtros = self.criar_catalogo_filtros()

        self.criar_interface()
        self.configurar_atalhos()
        self.root.protocol("WM_DELETE_WINDOW", self.fechar)

    # ================================================================
    # Catálogo
    # ================================================================

    def criar_catalogo_filtros(self):
        catalogo = {
            "Cores": [
                "Escala de cinza",
                "Preto e branco",
                "Threshold Otsu",
                "Threshold adaptativo",
                "Inverter cores",
                "Sépia",
                "Solarizar",
                "Posterizar",
            ],
            "Canais": [
                "Canal Azul",
                "Canal Verde",
                "Canal Vermelho",
                "Canal H (HSV)",
                "Canal S (HSV)",
                "Canal V (HSV)",
                "Split BGR",
            ],
            "Luz e contraste": [
                "Brilho",
                "Contraste",
                "Gamma",
                "Equalizar histograma",
                "CLAHE",
            ],
            "Desfoque": [
                "Blur",
                "Gaussian Blur",
                "Median Blur",
                "Bilateral",
            ],
            "Detalhes": [
                "Sharpen",
                "Sharpen forte",
                "Unsharp Mask",
                "Detail Enhance",
                "Denoise",
            ],
            "Bordas": [
                "Canny",
                "Sobel X",
                "Sobel Y",
                "Sobel XY",
                "Laplacian",
            ],
            "Morfologia": [
                "Erosão",
                "Dilatação",
                "Opening",
                "Closing",
                "Gradiente morfológico",
            ],
            "Efeitos": [
                "Emboss",
                "Sketch",
                "Cartoon",
                "Pixelizar",
            ],
            "Transformar": [
                "Flip horizontal",
                "Flip vertical",
                "Flip completo",
                "Rotacionar 90°",
                "Rotacionar -90°",
                "Rotacionar 180°",
                "Rotação livre",
                "Reduzir 50%",
                "Aumentar 200%",
            ],
        }

        catalogo["Morfologia"] = list(MORFOLOGIA)
        for categoria, filtros in EXTRAS.items():
            catalogo.setdefault(categoria, []).extend(filtros)
        return catalogo

    # ================================================================
    # Interface
    # ================================================================

    def criar_interface(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        # Toolbar
        toolbar = ttk.Frame(self.root, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(20, weight=1)

        self.btn_abrir = ttk.Button(toolbar, text="Abrir", command=self.abrir_imagem)
        self.btn_abrir.grid(row=0, column=0, padx=3)

        self.btn_salvar = ttk.Button(toolbar, text="Salvar", command=self.salvar_imagem)
        self.btn_salvar.grid(row=0, column=1, padx=3)

        self.btn_salvar_como = ttk.Button(toolbar, text="Salvar como", command=self.salvar_como)
        self.btn_salvar_como.grid(row=0, column=2, padx=3)

        self.btn_combinar = ttk.Button(
            toolbar, text="Combinar imagens", command=self.abrir_composicao
        )
        self.btn_combinar.grid(row=0, column=3, padx=(10, 3))

        ttk.Separator(toolbar, orient="vertical").grid(row=0, column=4, sticky="ns", padx=8)

        self.btn_undo = ttk.Button(toolbar, text="↶ Desfazer", command=self.desfazer)
        self.btn_undo.grid(row=0, column=5, padx=3)

        self.btn_redo = ttk.Button(toolbar, text="↷ Refazer", command=self.refazer)
        self.btn_redo.grid(row=0, column=6, padx=3)

        self.btn_reset = ttk.Button(toolbar, text="Resetar", command=self.resetar)
        self.btn_reset.grid(row=0, column=7, padx=3)

        ttk.Separator(toolbar, orient="vertical").grid(row=0, column=8, sticky="ns", padx=8)

        self.btn_original = ttk.Button(toolbar, text="Segure: Original")
        self.btn_original.grid(row=0, column=9, padx=3)
        self.btn_original.bind("<ButtonPress-1>", self.mostrar_original_temporario)
        self.btn_original.bind("<ButtonRelease-1>", self.restaurar_preview_temporario)
        self.btn_original.bind("<Leave>", self.restaurar_preview_temporario)

        ttk.Label(toolbar, text="Zoom").grid(row=0, column=10, padx=(14, 4))
        self.zoom_combo = ttk.Combobox(
            toolbar,
            width=7,
            state="readonly",
            values=["25%", "50%", "75%", "100%", "125%", "150%", "200%", "Ajustar"],
        )
        self.zoom_combo.set("Ajustar")
        self.zoom_combo.grid(row=0, column=11, padx=3)
        self.zoom_combo.bind("<<ComboboxSelected>>", lambda _e: self.atualizar_canvas())

        # Área principal
        principal = ttk.Panedwindow(self.root, orient="horizontal")
        principal.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        lateral = ttk.Frame(principal, width=330)
        lateral.pack_propagate(False)
        area = tk.Canvas(lateral, width=320, highlightthickness=0, bg="#eef2f7")
        barra = ttk.Scrollbar(lateral, orient="vertical", command=area.yview)
        barra.pack(side="right", fill="y")
        area.pack(side="left", fill="both", expand=True)
        area.configure(yscrollcommand=barra.set)
        painel = ttk.Frame(area, padding=12)
        painel_id = area.create_window((0, 0), window=painel, anchor="nw")
        painel.bind("<Configure>", lambda e: area.configure(scrollregion=area.bbox("all")))
        area.bind("<Configure>", lambda e: area.itemconfigure(painel_id, width=e.width))
        def rolar_painel(event):
            widget = event.widget
            while widget is not None:
                if widget == lateral:
                    area.yview_scroll(-int(event.delta / 120), "units")
                    return "break"
                widget = getattr(widget, "master", None)
        self.root.bind("<MouseWheel>", rolar_painel, add="+")
        visual = ttk.Frame(principal)
        principal.add(lateral, weight=0)
        principal.add(visual, weight=1)

        # Painel esquerdo
        ttk.Label(painel, text="Filtros", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            painel,
            text="Escolha uma categoria e ajuste os parâmetros. O preview não altera a imagem até você clicar em Aplicar.",
            wraplength=290,
        ).pack(anchor="w", pady=(4, 12))

        ttk.Label(painel, text="Categoria").pack(anchor="w")
        self.combo_categoria = ttk.Combobox(
            painel,
            textvariable=self.categoria_var,
            state="readonly",
            values=list(self.filtros.keys()),
        )
        self.combo_categoria.pack(fill="x", pady=(2, 10))
        self.combo_categoria.bind("<<ComboboxSelected>>", self.mudar_categoria)

        ttk.Label(painel, text="Filtro").pack(anchor="w")
        self.combo_filtro = ttk.Combobox(
            painel,
            textvariable=self.filtro_var,
            state="readonly",
        )
        self.combo_filtro.pack(fill="x", pady=(2, 12))
        self.combo_filtro.bind("<<ComboboxSelected>>", self.filtro_selecionado)

        self.adicionar_recursos_interface(painel)
        ttk.Separator(painel).pack(fill="x", pady=4)

        self.param1_label = ttk.Label(painel, text="Parâmetro 1")
        self.param1_label.pack(anchor="w", pady=(10, 2))
        self.slider1 = ttk.Scale(
            painel,
            variable=self.param1,
            from_=0,
            to=255,
            command=self.parametros_alterados,
        )
        self.slider1.pack(fill="x")
        self.param1_valor = ttk.Label(painel, text="50")
        self.param1_valor.pack(anchor="e")

        self.param2_label = ttk.Label(painel, text="Parâmetro 2")
        self.param2_label.pack(anchor="w", pady=(8, 2))
        self.slider2 = ttk.Scale(
            painel,
            variable=self.param2,
            from_=0,
            to=255,
            command=self.parametros_alterados,
        )
        self.slider2.pack(fill="x")
        self.param2_valor = ttk.Label(painel, text="100")
        self.param2_valor.pack(anchor="e")

        self.chk_preview = ttk.Checkbutton(
            painel,
            text="Preview automático",
            variable=self.live_preview,
            command=self.on_toggle_preview,
        )
        self.chk_preview.pack(anchor="w", pady=(12, 4))

        self.btn_preview = ttk.Button(painel, text="Atualizar preview", command=self.agendar_preview_imediato)
        self.btn_preview.pack(fill="x", pady=3)

        self.btn_aplicar = ttk.Button(painel, text="Aplicar filtro", style="Accent.TButton", command=self.aplicar_filtro)
        self.btn_aplicar.pack(fill="x", pady=(8, 4))

        self.btn_descartar = ttk.Button(painel, text="Descartar preview", command=self.descartar_preview)
        self.btn_descartar.pack(fill="x", pady=3)

        ttk.Separator(painel).pack(fill="x", pady=12)

        self.info_label = ttk.Label(painel, text="Nenhuma imagem carregada.", wraplength=290)
        self.info_label.pack(anchor="w")

        # Canvas central com scrollbars
        visual.rowconfigure(0, weight=1)
        visual.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(visual, bg="#171717", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        scroll_y = ttk.Scrollbar(visual, orient="vertical", command=self.canvas.yview)
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x = ttk.Scrollbar(visual, orient="horizontal", command=self.canvas.xview)
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=scroll_x.set, yscrollcommand=scroll_y.set)
        self.canvas.bind("<Configure>", self.on_canvas_resize)

        self.canvas_image_id = None
        self.tk_image = None

        # Status bar
        status = ttk.Frame(self.root, padding=(10, 4))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(status, text="Pronto")
        self.status_label.grid(row=0, column=0, sticky="w")

        self.progress = ttk.Progressbar(status, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=1, sticky="e")

        # Estado inicial
        primeira_categoria = next(iter(self.filtros))
        self.categoria_var.set(primeira_categoria)
        self.combo_filtro["values"] = self.filtros[primeira_categoria]
        self.filtro_var.set(self.filtros[primeira_categoria][0])
        self.configurar_parametros()
        self.atualizar_botoes()

    def configurar_atalhos(self):
        self.root.bind("<Control-o>", lambda _e: self.abrir_imagem())
        self.root.bind("<Control-s>", lambda _e: self.salvar_imagem())
        self.root.bind("<Control-Shift-S>", lambda _e: self.salvar_como())
        self.root.bind("<Control-z>", lambda _e: self.desfazer())
        self.root.bind("<Control-y>", lambda _e: self.refazer())
        self.root.bind("<Return>", lambda e: self.aplicar_filtro()
                       if not isinstance(e.widget, (ttk.Entry, ttk.Spinbox, ttk.Combobox)) else None)
        self.root.bind("<Escape>", lambda _e: self.descartar_preview())

    # ================================================================
    # Arquivos
    # ================================================================

    def abrir_imagem(self):
        if self.processando:
            return
        self.cancelar_preview_agendado()
        caminho = filedialog.askopenfilename(
            title="Abrir imagem",
            filetypes=[
                ("Imagens", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if not caminho:
            return

        try:
            dados = np.fromfile(caminho, dtype=np.uint8)
            imagem = cv2.imdecode(dados, cv2.IMREAD_COLOR)
            if imagem is None:
                raise ValueError("Formato inválido ou imagem corrompida.")

            self.original = imagem.copy()
            self.atual = imagem.copy()
            self.preview = None
            self.caminho_atual = caminho
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.zoom_combo.set("Ajustar")
            self.preview_job_id += 1

            self.atualizar_canvas()
            self.atualizar_info()
            self.atualizar_botoes()
            self.set_status("Imagem aberta")

            if self.live_preview.get():
                self.agendar_preview()

        except Exception as erro:
            messagebox.showerror("Erro", f"Não foi possível abrir a imagem.\n\n{erro}")

    def salvar_imagem(self):
        if self.atual is None:
            return
        if not self.caminho_atual:
            self.salvar_como()
            return
        self._salvar_em(self.caminho_atual)

    def salvar_como(self):
        if self.atual is None:
            return

        caminho = filedialog.asksaveasfilename(
            title="Salvar imagem como",
            defaultextension=".png",
            filetypes=[
                ("PNG", "*.png"),
                ("JPEG", "*.jpg *.jpeg"),
                ("WebP", "*.webp"),
                ("BMP", "*.bmp"),
            ],
        )
        if caminho:
            self._salvar_em(caminho)

    def _salvar_em(self, caminho):
        try:
            ext = "." + caminho.rsplit(".", 1)[-1].lower() if "." in caminho else ".png"
            if ext == ".jpeg":
                ext = ".jpg"
            ok, buffer = cv2.imencode(ext, self.atual)
            if not ok:
                raise ValueError("O OpenCV não conseguiu codificar a imagem.")
            buffer.tofile(caminho)
            self.caminho_atual = caminho
            self.set_status("Imagem aplicada salva. A prévia só é salva depois de Aplicar filtro.")
        except Exception as erro:
            messagebox.showerror("Erro ao salvar", str(erro))

    # ================================================================
    # Combinação de imagens
    # ================================================================

    def abrir_composicao(self):
        """Abre uma segunda imagem e mostra as opções de composição OpenCV."""
        if self.atual is None:
            messagebox.showinfo("Combinar imagens", "Abra a imagem principal primeiro.")
            return

        caminho = filedialog.askopenfilename(
            title="Escolha a segunda imagem",
            filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"),
                       ("Todos os arquivos", "*.*")],
        )
        if not caminho:
            return

        try:
            dados = np.fromfile(caminho, dtype=np.uint8)
            segunda = cv2.imdecode(dados, cv2.IMREAD_COLOR)
            if segunda is None:
                raise ValueError("Formato inválido ou imagem corrompida.")
        except Exception as erro:
            messagebox.showerror("Combinar imagens", f"Não foi possível abrir a segunda imagem.\n\n{erro}")
            return

        janela = tk.Toplevel(self.root)
        janela.title("Combinar imagens")
        janela.transient(self.root)
        janela.resizable(False, False)
        janela.grab_set()

        corpo = ttk.Frame(janela, padding=16)
        corpo.pack(fill="both", expand=True)
        h1, w1 = self.atual.shape[:2]
        h2, w2 = segunda.shape[:2]
        ttk.Label(corpo, text="Composição com OpenCV", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            corpo,
            text=(f"Imagem principal: {w1} × {h1}\n"
                  f"Segunda imagem: {w2} × {h2}\n\n"
                  "A segunda imagem será redimensionada para a resolução da principal."),
            justify="left",
        ).pack(anchor="w", pady=(5, 14))

        operacao = tk.StringVar(value="Mistura (alpha)")
        alpha = tk.DoubleVar(value=50)
        ttk.Label(corpo, text="Operação").pack(anchor="w")
        combo = ttk.Combobox(
            corpo, textvariable=operacao, state="readonly", width=30,
            values=[
                "Soma saturada", "Mistura (alpha)", "Subtração", "Diferença absoluta",
                "Multiplicar", "Screen", "AND (bit a bit)", "OR (bit a bit)", "XOR (bit a bit)",
            ],
        )
        combo.pack(fill="x", pady=(3, 10))

        linha_alpha = ttk.Frame(corpo)
        ttk.Label(linha_alpha, text="Transparência da segunda imagem").pack(anchor="w")
        escala = ttk.Scale(linha_alpha, from_=0, to=100, variable=alpha)
        escala.pack(side="left", fill="x", expand=True, pady=(3, 0))
        texto_alpha = ttk.Label(linha_alpha, width=5)
        texto_alpha.pack(side="left", padx=(8, 0))
        linha_alpha.pack(fill="x", pady=(0, 14))

        def atualizar_alpha(*_):
            texto_alpha.config(text=f"{alpha.get():.0f}%")

        def atualizar_estado(*_):
            estado = "normal" if operacao.get() == "Mistura (alpha)" else "disabled"
            escala.state(["!disabled"] if estado == "normal" else ["disabled"])
            atualizar_alpha()

        alpha.trace_add("write", atualizar_alpha)
        operacao.trace_add("write", atualizar_estado)
        atualizar_estado()

        acoes = ttk.Frame(corpo)
        acoes.pack(fill="x")
        ttk.Button(acoes, text="Cancelar", command=janela.destroy).pack(side="right")
        ttk.Button(
            acoes, text="Aplicar", command=lambda: self.iniciar_composicao(
                segunda, operacao.get(), alpha.get(), janela
            ),
        ).pack(side="right", padx=(0, 8))

    @staticmethod
    def combinar_imagens(primeira, segunda, operacao, alpha):
        """Aplica operações aritméticas/lógicas de composição do OpenCV."""
        base = EditorOpenCV.garantir_bgr(primeira)
        if segunda.shape[:2] != base.shape[:2]:
            segunda = cv2.resize(segunda, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_AREA)

        if operacao == "Soma saturada":
            return cv2.add(base, segunda)
        if operacao == "Mistura (alpha)":
            peso_segunda = min(1.0, max(0.0, alpha / 100.0))
            return cv2.addWeighted(base, 1.0 - peso_segunda, segunda, peso_segunda, 0)
        if operacao == "Subtração":
            return cv2.subtract(base, segunda)
        if operacao == "Diferença absoluta":
            return cv2.absdiff(base, segunda)
        if operacao == "Multiplicar":
            return cv2.multiply(base, segunda, scale=1 / 255.0)
        if operacao == "Screen":
            return 255 - cv2.multiply(255 - base, 255 - segunda, scale=1 / 255.0)
        if operacao == "AND (bit a bit)":
            return cv2.bitwise_and(base, segunda)
        if operacao == "OR (bit a bit)":
            return cv2.bitwise_or(base, segunda)
        if operacao == "XOR (bit a bit)":
            return cv2.bitwise_xor(base, segunda)
        raise ValueError(f"Operação não implementada: {operacao}")

    def iniciar_composicao(self, segunda, operacao, alpha, janela):
        if self.processando:
            return
        janela.destroy()
        self.cancelar_preview_agendado()
        self.processando = True
        self.set_processando(True, f"Combinando imagens: {operacao}...")
        base = self.atual.copy()
        future = self.executor.submit(self.combinar_imagens, base, segunda, operacao, float(alpha))
        self.root.after(30, self.verificar_future_composicao, future, operacao)

    def verificar_future_composicao(self, future, operacao):
        if not future.done():
            self.root.after(30, self.verificar_future_composicao, future, operacao)
            return
        try:
            resultado = future.result()
            self.guardar_historico()
            self.atual = resultado
            self.preview = None
            self.preview_job_id += 1
            self.atualizar_canvas()
            self.atualizar_info()
            self.set_status(f"Imagens combinadas: {operacao}")
        except Exception as erro:
            messagebox.showerror("Erro ao combinar", str(erro))
        finally:
            self.processando = False
            self.set_processando(False)

    # ================================================================
    # Histórico
    # ================================================================

    def guardar_historico(self):
        if self.atual is None:
            return
        self.undo_stack.append(self.atual.copy())
        while sum(i.nbytes for i in self.undo_stack) > 256 * 1024 * 1024 and len(self.undo_stack) > 1:
            self.undo_stack.pop(0)
        if len(self.undo_stack) > self.max_historico:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def desfazer(self):
        if not self.undo_stack or self.processando:
            return
        self.cancelar_preview_agendado()
        self.redo_stack.append(self.atual.copy())
        self.atual = self.undo_stack.pop()
        self.preview = None
        self.preview_job_id += 1
        self.atualizar_canvas()
        self.atualizar_info()
        self.atualizar_botoes()
        self.set_status("Desfeito")

    def refazer(self):
        if not self.redo_stack or self.processando:
            return
        self.cancelar_preview_agendado()
        self.undo_stack.append(self.atual.copy())
        self.atual = self.redo_stack.pop()
        self.preview = None
        self.preview_job_id += 1
        self.atualizar_canvas()
        self.atualizar_info()
        self.atualizar_botoes()
        self.set_status("Refeito")

    def resetar(self):
        if self.original is None or self.processando:
            return
        self.cancelar_preview_agendado()
        self.guardar_historico()
        self.atual = self.original.copy()
        self.preview = None
        self.preview_job_id += 1
        self.atualizar_canvas()
        self.atualizar_info()
        self.atualizar_botoes()
        self.set_status("Imagem restaurada")

    # ================================================================
    # Preview assíncrono
    # ================================================================

    def parametros_alterados(self, _valor=None):
        self.atualizar_texto_parametros()
        if self.live_preview.get():
            self.agendar_preview()

    def cancelar_preview_agendado(self):
        if self.debounce_id is not None:
            self.root.after_cancel(self.debounce_id)
            self.debounce_id = None
        self.preview_pendente = False

    def agendar_preview(self):
        if self.atual is None:
            return
        if not getattr(self, "aplicando", False):
            self.preview_job_id += 1
        if self.debounce_id is not None:
            self.root.after_cancel(self.debounce_id)
        self.debounce_id = self.root.after(220, self.iniciar_preview)

    def agendar_preview_imediato(self):
        if self.debounce_id is not None:
            self.root.after_cancel(self.debounce_id)
            self.debounce_id = None
        self.iniciar_preview()

    @staticmethod
    def preparar_base_preview(imagem, limite=1400):
        """Reduz imagens grandes apenas para o preview interativo."""
        h, w = imagem.shape[:2]
        maior = max(h, w)
        if maior <= limite:
            return imagem.copy()
        escala = limite / float(maior)
        return cv2.resize(
            imagem,
            (max(1, int(w * escala)), max(1, int(h * escala))),
            interpolation=cv2.INTER_AREA,
        )

    def verificar_future_preview(self, future, job_id):
        """Consulta o worker pela thread principal do Tkinter, evitando chamadas Tk no worker."""
        if future.done():
            self.finalizar_preview(future, job_id)
        else:
            self.root.after(30, self.verificar_future_preview, future, job_id)

    def iniciar_preview(self):
        self.debounce_id = None
        if self.atual is None:
            return

        if self.processando:
            self.preview_pendente = True
            return

        filtro = self.filtro_var.get()
        p1 = float(self.param1.get())
        p2 = float(self.param2.get())
        base = self.atual.copy()  # Preserva a escala do kernel e a fidelidade da prévia.

        self.preview_job_id += 1
        job_id = self.preview_job_id
        self.processando = True
        self.preview_pendente = False
        self.set_processando(True, f"Gerando preview: {filtro}...")

        future = self.executor.submit(self.processar_filtro, base, filtro, p1, p2, self.snapshot_morfologia())
        self.root.after(30, self.verificar_future_preview, future, job_id)

    def finalizar_preview(self, future, job_id):
        try:
            resultado = future.result()
            if job_id == self.preview_job_id:
                self.preview = resultado
                self.atualizar_canvas()
                self.set_status("Preview pronto")
        except Exception as erro:
            self.preview = None
            messagebox.showerror("Erro no filtro", str(erro))
        finally:
            self.processando = False
            self.set_processando(False)
            if self.preview_pendente and self.live_preview.get():
                self.preview_pendente = False
                self.root.after(20, self.iniciar_preview)

    def aplicar_filtro(self):
        if self.atual is None:
            messagebox.showinfo("Editor", "Abra uma imagem primeiro.")
            return
        if self.processando:
            self.set_status("Ainda processando. O botão será liberado quando terminar.")
            return

        self.cancelar_preview_agendado()
        filtro = self.filtro_var.get()
        p1 = float(self.param1.get())
        p2 = float(self.param2.get())
        base = self.atual.copy()

        self.preview_job_id += 1
        job_id = self.preview_job_id
        self.processando = True
        self.aplicando = True
        self.filtro_em_aplicacao = filtro
        self.set_processando(True, f"Aplicando: {filtro}...")

        future = self.executor.submit(self.processar_filtro, base, filtro, p1, p2, self.snapshot_morfologia())
        self.root.after(30, self.verificar_future_aplicacao, future, job_id)

    def verificar_future_aplicacao(self, future, job_id):
        if future.done():
            self.finalizar_aplicacao(future, job_id)
        else:
            self.root.after(30, self.verificar_future_aplicacao, future, job_id)

    def finalizar_aplicacao(self, future, job_id):
        try:
            resultado = future.result()
            if job_id == self.preview_job_id:
                self.guardar_historico()
                self.atual = resultado
                self.preview = None
                self.atualizar_canvas()
                self.atualizar_info()
                self.set_status(f"Filtro aplicado: {self.filtro_em_aplicacao}")
        except Exception as erro:
            messagebox.showerror("Erro no filtro", str(erro))
        finally:
            self.aplicando = False
            self.processando = False
            self.set_processando(False)
            self.atualizar_botoes()
            if self.preview_pendente and self.live_preview.get():
                self.preview_pendente = False
                self.root.after(20, self.iniciar_preview)

    def descartar_preview(self):
        self.cancelar_preview_agendado()
        if self.atual is None:
            return
        if not getattr(self, "aplicando", False):
            self.preview_job_id += 1
        self.preview = None
        self.atualizar_canvas()
        self.atualizar_botoes()
        self.set_status("Preview descartado")

    # ================================================================
    # Filtros e parâmetros
    # ================================================================

    def mudar_categoria(self, _evento=None):
        lista = self.filtros[self.categoria_var.get()]
        self.combo_filtro["values"] = lista
        self.filtro_var.set(lista[0])
        self.configurar_parametros()
        if self.live_preview.get():
            self.agendar_preview()

    def filtro_selecionado(self, _evento=None):
        self.configurar_parametros()
        if self.live_preview.get():
            self.agendar_preview()

    def set_slider(self, slider, variavel, minimo, maximo, valor):
        slider.configure(from_=minimo, to=maximo)
        variavel.set(valor)

    def configurar_parametros(self):
        filtro = self.filtro_var.get()

        # Default
        self.param1_label.config(text="Intensidade")
        self.param2_label.config(text="Parâmetro 2")
        self.set_slider(self.slider1, self.param1, 0, 255, 50)
        self.set_slider(self.slider2, self.param2, 0, 255, 100)
        self.slider1.state(["disabled"])
        self.slider2.state(["disabled"])

        sem_parametros = {
            "Escala de cinza", "Threshold Otsu", "Inverter cores", "Sépia",
            "Canal Azul", "Canal Verde", "Canal Vermelho", "Canal H (HSV)",
            "Canal S (HSV)", "Canal V (HSV)", "Split BGR", "Equalizar histograma",
            "CLAHE", "Sharpen", "Sharpen forte", "Detail Enhance", "Denoise",
            "Sobel X", "Sobel Y", "Sobel XY", "Laplacian", "Emboss", "Sketch",
            "Cartoon", "Flip horizontal", "Flip vertical", "Flip completo",
            "Rotacionar 90°", "Rotacionar -90°", "Rotacionar 180°",
            "Reduzir 50%", "Aumentar 200%",
        }

        if filtro in MORFOLOGIA:
            self.param1_label.config(text="Configure a matriz no botão de morfologia")
            self.param2_label.config(text="Iterações, âncora e bordas no laboratório")
        elif filtro in PARAMETROS:
            for spec, slider, var, label in zip(PARAMETROS[filtro],
                    (self.slider1, self.slider2), (self.param1, self.param2),
                    (self.param1_label, self.param2_label)):
                nome, low, high, initial = spec
                label.config(text=nome)
                self.set_slider(slider, var, low, high, initial)
                slider.state(["!disabled"])
        elif filtro in sem_parametros:
            pass
        elif filtro == "Preto e branco":
            self.param1_label.config(text="Threshold")
            self.set_slider(self.slider1, self.param1, 0, 255, 127)
            self.slider1.state(["!disabled"])
        elif filtro == "Threshold adaptativo":
            self.param1_label.config(text="Tamanho do bloco")
            self.param2_label.config(text="Constante C")
            self.set_slider(self.slider1, self.param1, 3, 51, 11)
            self.set_slider(self.slider2, self.param2, -20, 20, 2)
            self.slider1.state(["!disabled"])
            self.slider2.state(["!disabled"])
        elif filtro == "Solarizar":
            self.param1_label.config(text="Ponto de inversão")
            self.set_slider(self.slider1, self.param1, 0, 255, 128)
            self.slider1.state(["!disabled"])
        elif filtro == "Posterizar":
            self.param1_label.config(text="Níveis")
            self.set_slider(self.slider1, self.param1, 2, 32, 8)
            self.slider1.state(["!disabled"])
        elif filtro == "Brilho":
            self.param1_label.config(text="Brilho")
            self.set_slider(self.slider1, self.param1, -100, 100, 25)
            self.slider1.state(["!disabled"])
        elif filtro == "Contraste":
            self.param1_label.config(text="Contraste (%)")
            self.set_slider(self.slider1, self.param1, -80, 200, 35)
            self.slider1.state(["!disabled"])
        elif filtro == "Gamma":
            self.param1_label.config(text="Gamma × 100")
            self.set_slider(self.slider1, self.param1, 10, 300, 100)
            self.slider1.state(["!disabled"])
        elif filtro in {"Blur", "Gaussian Blur", "Median Blur"}:
            self.param1_label.config(text="Kernel")
            self.set_slider(self.slider1, self.param1, 1, 31, 5)
            self.slider1.state(["!disabled"])
        elif filtro == "Bilateral":
            self.param1_label.config(text="Diâmetro")
            self.param2_label.config(text="Sigma")
            self.set_slider(self.slider1, self.param1, 1, 25, 9)
            self.set_slider(self.slider2, self.param2, 10, 200, 75)
            self.slider1.state(["!disabled"])
            self.slider2.state(["!disabled"])
        elif filtro == "Unsharp Mask":
            self.param1_label.config(text="Força × 100")
            self.param2_label.config(text="Blur")
            self.set_slider(self.slider1, self.param1, 10, 300, 120)
            self.set_slider(self.slider2, self.param2, 1, 31, 5)
            self.slider1.state(["!disabled"])
            self.slider2.state(["!disabled"])
        elif filtro == "Canny":
            self.param1_label.config(text="Threshold mínimo")
            self.param2_label.config(text="Threshold máximo")
            self.set_slider(self.slider1, self.param1, 0, 255, 100)
            self.set_slider(self.slider2, self.param2, 0, 255, 200)
            self.slider1.state(["!disabled"])
            self.slider2.state(["!disabled"])
        elif filtro == "Pixelizar":
            self.param1_label.config(text="Tamanho dos pixels")
            self.set_slider(self.slider1, self.param1, 2, 100, 20)
            self.slider1.state(["!disabled"])
        elif filtro == "Rotação livre":
            self.param1_label.config(text="Ângulo")
            self.set_slider(self.slider1, self.param1, -180, 180, 30)
            self.slider1.state(["!disabled"])

        self.atualizar_texto_parametros()

    def atualizar_texto_parametros(self):
        self.param1_valor.config(text=f"{self.param1.get():.0f}")
        self.param2_valor.config(text=f"{self.param2.get():.0f}")

    @staticmethod
    def garantir_bgr(img):
        if img.ndim == 2:
            return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        return img

    @staticmethod
    def cinza(img):
        if img.ndim == 2:
            return img
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def impar(valor, minimo=1):
        n = max(minimo, int(round(valor)))
        if n % 2 == 0:
            n += 1
        return n

    def processar_filtro(self, img, filtro, p1, p2, morfologia=None):
        if filtro in MORFOLOGIA:
            if morfologia is None:
                k = self.impar(p1)
                morfologia = dict(kernel=np.ones((k, k), np.int8), anchor=(-1, -1),
                                  iterations=1, border="Padrão morfológico", mode="Colorida", threshold=127)
            return aplicar_morfologia(img, filtro, morfologia)
        if any(filtro in filtros for filtros in EXTRAS.values()):
            return processar_extra(img, filtro, p1, p2)
        # Cores
        if filtro == "Escala de cinza":
            return self.cinza(img)

        if filtro == "Preto e branco":
            gray = self.cinza(img)
            _, out = cv2.threshold(gray, int(p1), 255, cv2.THRESH_BINARY)
            return out

        if filtro == "Threshold Otsu":
            gray = self.cinza(img)
            _, out = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return out

        if filtro == "Threshold adaptativo":
            gray = self.cinza(img)
            bloco = self.impar(p1, 3)
            return cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, bloco, int(p2)
            )

        if filtro == "Inverter cores":
            return cv2.bitwise_not(img)

        if filtro == "Sépia":
            cor = self.garantir_bgr(img)
            matriz = np.array([
                [0.272, 0.534, 0.131],
                [0.349, 0.686, 0.168],
                [0.393, 0.769, 0.189],
            ], dtype=np.float32)
            return np.clip(cv2.transform(cor, matriz), 0, 255).astype(np.uint8)

        if filtro == "Solarizar":
            limiar = int(p1)
            return np.where(img < limiar, img, 255 - img).astype(np.uint8)

        if filtro == "Posterizar":
            niveis = max(2, int(p1))
            passo = 256 / niveis
            return (np.floor(img / passo) * passo).clip(0, 255).astype(np.uint8)

        # Canais
        if filtro in {"Canal Azul", "Canal Verde", "Canal Vermelho"}:
            cor = self.garantir_bgr(img)
            b, g, r = cv2.split(cor)
            return {"Canal Azul": b, "Canal Verde": g, "Canal Vermelho": r}[filtro]

        if filtro in {"Canal H (HSV)", "Canal S (HSV)", "Canal V (HSV)"}:
            hsv = cv2.cvtColor(self.garantir_bgr(img), cv2.COLOR_BGR2HSV)
            h, s, v = cv2.split(hsv)
            return {"Canal H (HSV)": h, "Canal S (HSV)": s, "Canal V (HSV)": v}[filtro]

        if filtro == "Split BGR":
            cor = self.garantir_bgr(img)
            b, g, r = cv2.split(cor)
            zero = np.zeros_like(b)
            azul = cv2.merge([b, zero, zero])
            verde = cv2.merge([zero, g, zero])
            vermelho = cv2.merge([zero, zero, r])
            cima = np.hstack([cor, azul])
            baixo = np.hstack([verde, vermelho])
            return np.vstack([cima, baixo])

        # Luz e contraste
        if filtro == "Brilho":
            beta = int(p1)
            if beta >= 0:
                return cv2.add(img, np.full_like(img, beta))
            return cv2.subtract(img, np.full_like(img, -beta))

        if filtro == "Contraste":
            alpha = max(0.05, 1.0 + p1 / 100.0)
            return cv2.convertScaleAbs(img, alpha=alpha, beta=0)

        if filtro == "Gamma":
            gamma = max(0.1, p1 / 100.0)
            tabela = np.array([
                ((i / 255.0) ** (1.0 / gamma)) * 255
                for i in range(256)
            ], dtype=np.uint8)
            return cv2.LUT(img, tabela)

        if filtro == "Equalizar histograma":
            if img.ndim == 2:
                return cv2.equalizeHist(img)
            ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
            ycrcb[:, :, 0] = cv2.equalizeHist(ycrcb[:, :, 0])
            return cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)

        if filtro == "CLAHE":
            clahe = cv2.createCLAHE(clipLimit=max(0.1, p1 / 10), tileGridSize=(max(2, int(p2)), max(2, int(p2))))
            if img.ndim == 2:
                return clahe.apply(img)
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            l = clahe.apply(l)
            return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)

        # Blur
        if filtro == "Blur":
            k = self.impar(p1)
            return cv2.blur(img, (k, k))

        if filtro == "Gaussian Blur":
            k = self.impar(p1)
            return cv2.GaussianBlur(img, (k, k), 0)

        if filtro == "Median Blur":
            k = self.impar(p1, 3)
            return cv2.medianBlur(img, k)

        if filtro == "Bilateral":
            return cv2.bilateralFilter(img, max(1, int(p1)), float(p2), float(p2))

        # Detalhes
        if filtro == "Sharpen":
            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
            return cv2.filter2D(img, -1, kernel)

        if filtro == "Sharpen forte":
            kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]], dtype=np.float32)
            return cv2.filter2D(img, -1, kernel)

        if filtro == "Unsharp Mask":
            k = self.impar(p2)
            blur = cv2.GaussianBlur(img, (k, k), 0)
            forca = max(0.1, p1 / 100.0)
            return cv2.addWeighted(img, 1.0 + forca, blur, -forca, 0)

        if filtro == "Detail Enhance":
            return cv2.detailEnhance(self.garantir_bgr(img), sigma_s=float(p1), sigma_r=float(p2) / 100)

        if filtro == "Denoise":
            if img.ndim == 2:
                return cv2.fastNlMeansDenoising(img, None, float(p1), 7, 21)
            return cv2.fastNlMeansDenoisingColored(img, None, float(p1), float(p1), 7, 21)

        # Bordas
        if filtro == "Canny":
            return cv2.Canny(self.cinza(img), int(min(p1, p2)), int(max(p1, p2)))

        if filtro == "Sobel X":
            sobel = cv2.Sobel(self.cinza(img), cv2.CV_64F, 1, 0, ksize=3)
            return cv2.convertScaleAbs(sobel)

        if filtro == "Sobel Y":
            sobel = cv2.Sobel(self.cinza(img), cv2.CV_64F, 0, 1, ksize=3)
            return cv2.convertScaleAbs(sobel)

        if filtro == "Sobel XY":
            gray = self.cinza(img)
            sx = cv2.convertScaleAbs(cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3))
            sy = cv2.convertScaleAbs(cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3))
            return cv2.addWeighted(sx, 0.5, sy, 0.5, 0)

        if filtro == "Laplacian":
            lap = cv2.Laplacian(self.cinza(img), cv2.CV_64F)
            return cv2.convertScaleAbs(lap)

        # Efeitos
        if filtro == "Emboss":
            kernel = np.array([[-2, -1, 0], [-1, 1, 1], [0, 1, 2]], dtype=np.float32)
            tmp = cv2.filter2D(self.garantir_bgr(img), cv2.CV_16S, kernel)
            return np.clip(tmp.astype(np.float32) + 128, 0, 255).astype(np.uint8)

        if filtro == "Sketch":
            gray = self.cinza(img)
            invertida = cv2.bitwise_not(gray)
            blur = cv2.GaussianBlur(invertida, (21, 21), 0)
            return cv2.divide(gray, cv2.bitwise_not(blur), scale=256.0)

        if filtro == "Cartoon":
            cor = self.garantir_bgr(img)
            gray = cv2.cvtColor(cor, cv2.COLOR_BGR2GRAY)
            gray = cv2.medianBlur(gray, 7)
            edges = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                cv2.THRESH_BINARY, 9, 9
            )
            smooth = cv2.bilateralFilter(cor, 9, 200, 200)
            return cv2.bitwise_and(smooth, smooth, mask=edges)

        if filtro == "Pixelizar":
            h, w = img.shape[:2]
            fator = max(2, int(p1))
            pequeno = cv2.resize(
                img,
                (max(1, w // fator), max(1, h // fator)),
                interpolation=cv2.INTER_LINEAR,
            )
            return cv2.resize(pequeno, (w, h), interpolation=cv2.INTER_NEAREST)

        # Transformações
        if filtro == "Flip horizontal":
            return cv2.flip(img, 1)
        if filtro == "Flip vertical":
            return cv2.flip(img, 0)
        if filtro == "Flip completo":
            return cv2.flip(img, -1)
        if filtro == "Rotacionar 90°":
            return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        if filtro == "Rotacionar -90°":
            return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if filtro == "Rotacionar 180°":
            return cv2.rotate(img, cv2.ROTATE_180)

        if filtro == "Rotação livre":
            h, w = img.shape[:2]
            centro = (w / 2.0, h / 2.0)
            matriz = cv2.getRotationMatrix2D(centro, p1, 1.0)

            cos = abs(matriz[0, 0])
            sin = abs(matriz[0, 1])
            novo_w = int((h * sin) + (w * cos))
            novo_h = int((h * cos) + (w * sin))

            matriz[0, 2] += (novo_w / 2.0) - centro[0]
            matriz[1, 2] += (novo_h / 2.0) - centro[1]
            return cv2.warpAffine(img, matriz, (novo_w, novo_h))

        if filtro == "Reduzir 50%":
            return cv2.resize(img, (max(1, img.shape[1] // 2), max(1, img.shape[0] // 2)), interpolation=cv2.INTER_AREA)

        if filtro == "Aumentar 200%":
            return cv2.resize(img, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

        raise ValueError(f"Filtro não implementado: {filtro}")

    # ================================================================
    # Canvas / zoom
    # ================================================================

    def imagem_para_exibir(self):
        return self.preview if self.preview is not None else self.atual

    def mostrar_original_temporario(self, _evento=None):
        if self.original is not None:
            self._renderizar(self.original)

    def restaurar_preview_temporario(self, _evento=None):
        if self.atual is not None:
            self.atualizar_canvas()

    def on_canvas_resize(self, _evento=None):
        if self.resize_debounce_id is not None:
            self.root.after_cancel(self.resize_debounce_id)
        self.resize_debounce_id = self.root.after(100, self.atualizar_canvas)

    def atualizar_canvas(self):
        self.resize_debounce_id = None
        imagem = self.imagem_para_exibir()
        if imagem is None:
            self.canvas.delete("all")
            self.canvas.create_text(
                max(250, self.canvas.winfo_width() // 2),
                max(180, self.canvas.winfo_height() // 2),
                text="Abra uma imagem para começar",
                fill="white",
                font=("Segoe UI", 18),
            )
            return
        self._renderizar(imagem)

    def _renderizar(self, imagem):
        if imagem.ndim == 2:
            rgb = cv2.cvtColor(imagem, cv2.COLOR_GRAY2RGB)
        else:
            rgb = cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB)

        h, w = rgb.shape[:2]
        modo_zoom = self.zoom_combo.get()

        if modo_zoom == "Ajustar":
            cw = max(100, self.canvas.winfo_width() - 24)
            ch = max(100, self.canvas.winfo_height() - 24)
            escala = min(cw / w, ch / h, 1.0)
        else:
            escala = float(modo_zoom.replace("%", "")) / 100.0

        novo_w = max(1, int(w * escala))
        novo_h = max(1, int(h * escala))

        pil = Image.fromarray(rgb)
        if (novo_w, novo_h) != (w, h):
            resample = Image.Resampling.LANCZOS if escala < 1 else Image.Resampling.BICUBIC
            pil = pil.resize((novo_w, novo_h), resample)

        self.tk_image = ImageTk.PhotoImage(pil)
        self.canvas.delete("all")

        canvas_w = max(self.canvas.winfo_width(), novo_w)
        canvas_h = max(self.canvas.winfo_height(), novo_h)
        x = canvas_w // 2
        y = canvas_h // 2
        self.canvas_image_id = self.canvas.create_image(x, y, image=self.tk_image, anchor="center")
        self.canvas.configure(scrollregion=(0, 0, canvas_w, canvas_h))

    # ================================================================
    # Status e controles
    # ================================================================

    def on_toggle_preview(self):
        if self.live_preview.get():
            self.agendar_preview()
        else:
            self.descartar_preview()

    def atualizar_info(self):
        if self.atual is None:
            self.info_label.config(text="Nenhuma imagem carregada.")
            return
        h, w = self.atual.shape[:2]
        canais = 1 if self.atual.ndim == 2 else self.atual.shape[2]
        memoria = self.atual.nbytes / (1024 * 1024)
        self.info_label.config(
            text=f"Resolução: {w} × {h}\nCanais: {canais}\nTipo: {self.atual.dtype}\nMemória: {memoria:.1f} MB"
        )

    def atualizar_botoes(self):
        tem_imagem = self.atual is not None
        self.btn_abrir.state(["disabled"] if self.processando else ["!disabled"])
        self.btn_salvar.state(["!disabled"] if tem_imagem else ["disabled"])
        self.btn_salvar_como.state(["!disabled"] if tem_imagem else ["disabled"])
        self.btn_combinar.state(["!disabled"] if tem_imagem and not self.processando else ["disabled"])
        self.btn_reset.state(["!disabled"] if tem_imagem else ["disabled"])
        self.btn_original.state(["!disabled"] if self.original is not None else ["disabled"])
        self.btn_undo.state(["!disabled"] if self.undo_stack else ["disabled"])
        self.btn_redo.state(["!disabled"] if self.redo_stack else ["disabled"])
        self.btn_aplicar.state(["!disabled"] if tem_imagem and not self.processando else ["disabled"])
        self.btn_preview.state(["!disabled"] if tem_imagem and not self.processando else ["disabled"])
        self.btn_descartar.state(["!disabled"] if self.preview is not None else ["disabled"])

    def set_processando(self, ativo, texto=None):
        if ativo:
            self.atualizar_botoes()
            self.progress.start(12)
            self.btn_aplicar.state(["disabled"])
            self.btn_preview.state(["disabled"])
            self.btn_combinar.state(["disabled"])
            if texto:
                self.status_label.config(text=texto)
        else:
            self.progress.stop()
            self.atualizar_botoes()

    def set_status(self, texto):
        self.status_label.config(text=texto)

    def fechar(self):
        self.cancelar_preview_agendado()
        if self.resize_debounce_id is not None:
            self.root.after_cancel(self.resize_debounce_id)
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self.executor.shutdown(wait=False)
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = EditorOpenCV(root)
    root.mainloop()
