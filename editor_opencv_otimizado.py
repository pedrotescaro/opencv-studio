import sys
import subprocess
import importlib.util
from pathlib import Path


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
from editor_recorte import JanelaRecorte
from editor_medicao import JanelaMedicao
from editor_interface import AbaFerramenta
from concurrent.futures import ThreadPoolExecutor


from editor_recursos import (RecursosEditor, MORFOLOGIA, EXTRAS, PARAMETROS,
                             aplicar_morfologia, processar_extra)


class EditorOpenCV(RecursosEditor):
    def __init__(self, root):
        self.root = root
        if getattr(root, "_editor_abas", None) is not None:
            root._editor_abas.destroy()
        root._editor_app = self
        self.encerrando = self.sincronizando_abas = False
        self.paginas = {}
        self.nomes_abas = ("Editor", "Recorte", "Medições", "Segmentação", "Morfologia", "Composição")
        self.inicializar_recursos()
        self.root.title("OpenCV Studio")
        self.root.geometry("1280x820")
        self.root.minsize(1000, 680)

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
        self.live_preview = tk.BooleanVar(value=False)
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
        from editor_layout import construir_interface
        construir_interface(self)

    def criar_placeholder(self, titulo):
        pagina = ttk.Frame(self.abas, padding=30)
        pagina.placeholder = True
        pagina.columnconfigure(0, weight=1)
        pagina.rowconfigure(0, weight=1)
        pagina.rowconfigure(2, weight=1)
        centro = ttk.Frame(pagina)
        centro.grid(row=1, column=0)
        ttk.Label(centro, text=titulo, style="Title.TLabel").pack(pady=(0, 10))
        if titulo == "Segmentação":
            texto = "Primeiro selecione uma região na aba Medições.\nFeche o contorno e clique em Segmentar ROI."
            acao, comando = "Selecionar uma região", self.abrir_medicao
        elif titulo == "Composição":
            texto = "Combine a imagem atual com uma segunda imagem.\nEscolha a operação e ajuste a mistura."
            acao, comando = "Escolher segunda imagem", self.abrir_composicao
        elif titulo == "Morfologia":
            texto = "Desenhe ou ajuste o elemento estruturante.\nUse a matriz em um filtro da categoria Morfologia."
            acao, comando = "Editar elemento", self.editar_kernel
        else:
            texto = "Abra uma imagem para usar esta ferramenta.\nSua seleção ficará disponível ao alternar entre abas."
            acao, comando = "Abrir imagem", self.abrir_imagem
        ttk.Label(centro, text=texto, justify="center", style="Muted.TLabel").pack(pady=(0, 18))
        ttk.Button(centro, text=acao, command=comando, style="Accent.TButton").pack()
        self.paginas[titulo] = pagina
        indice = self.nomes_abas.index(titulo)
        self.abas.insert(indice if indice < len(self.abas.tabs()) else "end", pagina, text=titulo)
        return pagina

    def registrar_aba(self, pagina):
        antiga = self.paginas.get(pagina.titulo)
        self.sincronizando_abas = True
        try:
            if antiga is not None and antiga.winfo_exists():
                antiga.destroy()
                placeholder = self.paginas.get(pagina.titulo)
                if placeholder is not antiga and placeholder is not None and placeholder.winfo_exists():
                    placeholder.destroy()
            self.paginas[pagina.titulo] = pagina
            indice = self.nomes_abas.index(pagina.titulo)
            self.abas.insert(indice if indice < len(self.abas.tabs()) else "end", pagina, text=pagina.titulo)
            self.abas.select(pagina)
        finally:
            self.sincronizando_abas = False

    def aba_removida(self, pagina):
        if self.paginas.get(pagina.titulo) is pagina:
            if pagina.titulo == "Medições":
                segmentacao = self.paginas.get("Segmentação")
                if isinstance(segmentacao, AbaFerramenta):
                    segmentacao.destroy()
            self.criar_placeholder(pagina.titulo)
            if not self.sincronizando_abas:
                self.selecionar_aba(pagina.retorno)

    def selecionar_aba(self, titulo):
        pagina = self.paginas.get(titulo)
        if pagina is not None and pagina.winfo_exists():
            self.abas.select(pagina)

    def aba_selecionada(self, _evento=None):
        if self.encerrando or self.sincronizando_abas or not self.abas.select():
            return
        pagina = self.root.nametowidget(self.abas.select())
        if not getattr(pagina, "placeholder", False):
            return
        titulo = self.abas.tab(pagina, "text")
        if titulo == "Morfologia":
            self.editar_kernel()
        elif self.atual is not None and not self.processando:
            if titulo == "Recorte":
                self.abrir_recorte()
            elif titulo == "Medições":
                self.abrir_medicao()

    def sincronizar_ferramentas(self):
        # Uma seleção pertence à imagem que a originou, inclusive sua resolução.
        self.sincronizando_abas = True
        mudou = False
        try:
            for pagina in list(self.paginas.values()):
                if isinstance(pagina, AbaFerramenta) and pagina.origem is not None and pagina.origem is not self.atual:
                    pagina.destroy()
                    mudou = True
        finally:
            self.sincronizando_abas = False
        if mudou:
            self.selecionar_aba("Editor")

    def atalho_local(self, acao, evento):
        if isinstance(evento.widget, (ttk.Entry, ttk.Spinbox, ttk.Combobox, tk.Entry, tk.Text)):
            return
        pagina = self.root.nametowidget(self.abas.select())
        if pagina is self.paginas["Editor"]:
            if acao == "enter":
                self.aplicar_filtro()
            else:
                self.descartar_preview()
        else:
            handler = getattr(pagina, f"ao_{acao}", None)
            if handler is not None:
                handler()
        return "break"

    def configurar_atalhos(self):
        self.root.bind("<Control-o>", lambda _e: self.abrir_imagem())
        self.root.bind("<Control-s>", lambda _e: self.salvar_imagem())
        self.root.bind("<Control-Shift-S>", lambda _e: self.salvar_como())
        self.root.bind("<Control-z>", lambda e: self.atalho_historico(e))
        self.root.bind("<Control-y>", lambda e: self.atalho_historico(e, refazer=True))
        self.root.bind("<Return>", lambda e: self.atalho_local("enter", e))
        self.root.bind("<Escape>", lambda e: self.atalho_local("escape", e))
        self.root.bind("<Control-Tab>", lambda e: self.alternar_aba(1))
        self.root.bind("<Control-Shift-Tab>", lambda e: self.alternar_aba(-1))

    def alternar_aba(self, direcao):
        indice = self.abas.index(self.abas.select())
        self.abas.select((indice + direcao) % len(self.abas.tabs()))
        return "break"

    def atalho_historico(self, evento, refazer=False):
        if isinstance(evento.widget, (ttk.Entry, ttk.Spinbox, ttk.Combobox, tk.Entry, tk.Text)):
            return
        pagina = self.root.nametowidget(self.abas.select())
        if pagina is self.paginas["Editor"]:
            self.refazer() if refazer else self.desfazer()
        elif isinstance(pagina, JanelaMedicao) and not refazer:
            pagina.remover_ponto()
        return "break"

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
            self.selecionar_aba("Editor")
            self.set_status("Imagem aberta")

            if self.live_preview.get():
                self.agendar_preview()

        except Exception as erro:
            messagebox.showerror("Erro", f"Não foi possível abrir a imagem.\n\n{erro}")

    def abrir_medicao(self):
        if self.atual is None or self.processando:
            return
        self.descartar_preview()
        if getattr(self, "_imagem_medicoes", None) is not self.atual:
            self._imagem_medicoes = self.atual
            self._dados_medicoes = {}
        existente = self.paginas.get("Medições")
        if isinstance(existente, AbaFerramenta) and existente.origem is self.atual:
            existente.lift()
        else:
            JanelaMedicao(self.root, self.atual, self._dados_medicoes)

    def abrir_recorte(self):
        if self.atual is None or self.processando:
            return
        self.descartar_preview()
        existente = self.paginas.get("Recorte")
        if isinstance(existente, AbaFerramenta) and existente.origem is self.atual:
            existente.lift()
        else:
            JanelaRecorte(self.root, self.atual, self.aplicar_recorte)

    def aplicar_recorte(self, resultado, pixels):
        self.cancelar_preview_agendado()
        self.guardar_historico()
        self.atual = resultado
        self.preview = None
        self.preview_job_id += 1
        self.atualizar_canvas()
        self.atualizar_info()
        self.atualizar_botoes()
        self.set_status(f"Recorte aplicado: {pixels:,} pixels na forma selecionada")

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
        if self.processando:
            return
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

        janela = AbaFerramenta(self.root, "Composição", origem=self.atual)

        corpo = ttk.Frame(janela, padding=16)
        corpo.pack(anchor="n", fill="x", padx=80, pady=30)
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
        if self.filtro_var.get() in MORFOLOGIA:
            self.morfologia["iterations"] = max(1, min(30, int(round(self.param1.get()))))
            self.morfologia["threshold"] = max(0, min(255, int(round(self.param2.get()))))
            self.atualizar_resumo_kernel()
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

        future = self.executor.submit(self.processar_filtro, base, filtro, p1, p2, self.opcoes_morfologia_processamento())
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

        if filtro in MORFOLOGIA and not self.morfologia_ativa.get():
            self.descartar_preview()
            self.set_status("Morfologia desligada: nenhuma alteração aplicada.")
            return

        self.preview_job_id += 1
        job_id = self.preview_job_id
        self.processando = True
        self.aplicando = True
        self.filtro_em_aplicacao = filtro
        self.set_processando(True, f"Aplicando: {filtro}...")

        future = self.executor.submit(self.processar_filtro, base, filtro, p1, p2, self.opcoes_morfologia_processamento())
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
            self.param1_label.config(text="Iterações")
            self.set_slider(self.slider1, self.param1, 1, 30, self.morfologia["iterations"])
            self.slider1.state(["!disabled"])
            self.param2_label.config(text="Limiar da imagem binária")
            self.set_slider(self.slider2, self.param2, 0, 255, self.morfologia["threshold"])
            if filtro == "Hit-or-miss" or self.morfologia["mode"] == "Binária":
                self.slider2.state(["!disabled"])
            if not self.morfologia_ativa.get():
                self.slider1.state(["disabled"])
                self.slider2.state(["disabled"])
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

    def atualizar_controles_filtro(self):
        if hasattr(self, "ajustes"):
            if self.filtro_var.get() in MORFOLOGIA:
                self.morfologia_box.pack(fill="x", before=self.chk_preview, pady=6)
            else:
                self.morfologia_box.pack_forget()
            for numero in (1, 2):
                for widget in (getattr(self, f"param{numero}_label"), getattr(self, f"slider{numero}"), getattr(self, f"param{numero}_valor")):
                    widget.pack_forget()
            for numero in (1, 2):
                slider = getattr(self, f"slider{numero}")
                if not slider.instate(["disabled"]):
                    getattr(self, f"param{numero}_label").pack(anchor="w", pady=(8, 2))
                    slider.pack(fill="x")
                    getattr(self, f"param{numero}_valor").pack(anchor="e")
            if all(getattr(self, f"slider{numero}").instate(["disabled"]) for numero in (1, 2)):
                self.ajustes.pack_forget()
            else:
                self.ajustes.pack(fill="x", before=self.chk_preview)

    def atualizar_texto_parametros(self):
        self.param1_valor.config(text=f"{self.param1.get():.0f}")
        self.param2_valor.config(text=f"{self.param2.get():.0f}")
        self.atualizar_controles_filtro()

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
            if morfologia is not None and not morfologia.get("enabled", True):
                return img.copy()
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
            self.canvas.create_window(max(250, self.canvas.winfo_width()//2),
                max(180, self.canvas.winfo_height()//2), window=self.boas_vindas, anchor="center")
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

        self.tk_image = ImageTk.PhotoImage(pil, master=self.canvas)
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
        self.sincronizar_ferramentas()
        if self.atual is None:
            self.info_label.config(text="Nenhuma imagem carregada.")
            return
        h, w = self.atual.shape[:2]
        nome = Path(self.caminho_atual).name if self.caminho_atual else "Imagem atual"
        self.imagem_label.config(text=f"{nome}  ·  {w} × {h} pixels")
        canais = 1 if self.atual.ndim == 2 else self.atual.shape[2]
        memoria = self.atual.nbytes / (1024 * 1024)
        self.info_label.config(
            text=f"Resolução: {w} × {h}\nPixels: {w * h:,} ({w * h / 1e6:.2f} MP)\nCanais: {canais}\nTipo: {self.atual.dtype}\nMemória: {memoria:.1f} MB"
        )

    def atualizar_botoes(self):
        tem_imagem = self.atual is not None
        self.btn_recorte.state(["!disabled"] if tem_imagem and not self.processando else ["disabled"])
        self.btn_medicao.state(["!disabled"] if tem_imagem and not self.processando else ["disabled"])
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
        self.encerrando = True
        for pagina in list(self.paginas.values()):
            if isinstance(pagina, AbaFerramenta):
                pagina.destroy()
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
