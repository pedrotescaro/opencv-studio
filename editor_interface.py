"""Componentes visuais compartilhados e ferramentas hospedadas em abas."""
import tkinter as tk
from tkinter import ttk

FUNDO = "#f2f5f8"
SUPERFICIE = "#ffffff"
CANVAS = "#dfe6ed"
TEXTO = "#203047"
SUAVE = "#52647a"


def configurar_estilo(root):
    root.configure(bg=FUNDO)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background=FUNDO)
    style.configure("Card.TFrame", background=SUPERFICIE)
    style.configure("Brand.TLabel", background=SUPERFICIE, foreground="#172b45", font=("Segoe UI", 16, "bold"))
    style.configure("HeaderMuted.TLabel", background=SUPERFICIE, foreground=SUAVE, font=("Segoe UI", 9))
    style.configure("Panel.TFrame", background=SUPERFICIE)
    style.configure("Panel.TLabel", background=SUPERFICIE, foreground=TEXTO)
    style.configure("Status.TLabel", foreground="#1e5b46", background="#e5f2eb", padding=(10, 5), font=("Segoe UI", 9))
    style.configure("TLabel", background=FUNDO, foreground=TEXTO, font=("Segoe UI", 10))
    style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
    style.configure("Section.TLabel", font=("Segoe UI", 11, "bold"))
    style.configure("Muted.TLabel", foreground=SUAVE)
    style.configure("TButton", padding=(10, 6), font=("Segoe UI", 10), background=SUPERFICIE,
                    foreground=TEXTO, borderwidth=1, relief="flat")
    style.map("TButton", background=[("active", "#e7edf7")], foreground=[("disabled", "#9aa5b5")])
    style.configure("Accent.TButton", background="#2563eb", foreground="white", borderwidth=0)
    style.map("Accent.TButton", background=[("disabled", "#c9d4e8"), ("active", "#1d4ed8")],
              foreground=[("disabled", "#ffffff")])
    style.configure("Quiet.TButton", padding=(7, 5), background=FUNDO, foreground=SUAVE, borderwidth=0)
    style.configure("TNotebook", background=FUNDO, borderwidth=0, bordercolor=FUNDO, tabmargins=(0, 8, 0, 8))
    style.configure("TNotebook.Tab", padding=(10, 9), background=FUNDO, foreground=SUAVE,
                    font=("Segoe UI", 10), bordercolor=FUNDO, lightcolor=FUNDO, darkcolor=FUNDO)
    style.map("TNotebook.Tab", background=[("selected", SUPERFICIE)],
              foreground=[("selected", "#2563eb")], padding=[("selected", (10, 9))])
    style.configure("TEntry", padding=6, fieldbackground=SUPERFICIE, bordercolor="#d9e0eb")
    style.configure("TCombobox", padding=5, fieldbackground=SUPERFICIE, background=SUPERFICIE)
    style.map("TCombobox", fieldbackground=[("readonly", SUPERFICIE)])
    style.configure("TSpinbox", padding=4, fieldbackground=SUPERFICIE)
    style.configure("TCheckbutton", background=FUNDO, foreground=TEXTO, padding=(0, 4))
    style.configure("TLabelframe", background=FUNDO, bordercolor="#d9e0eb", relief="solid")
    style.configure("TLabelframe.Label", background=FUNDO, foreground=SUAVE, font=("Segoe UI", 10))
    style.configure("Treeview", background=SUPERFICIE, fieldbackground=SUPERFICIE, foreground=TEXTO,
                    rowheight=30, borderwidth=0, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", background="#edf1f7", foreground=SUAVE,
                    padding=(8, 7), font=("Segoe UI", 10, "bold"), relief="flat")
    style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", TEXTO)])
    style.configure("TScrollbar", background="#cbd5e1", troughcolor=FUNDO, borderwidth=0, arrowsize=13)
    style.configure("Horizontal.TProgressbar", background="#2563eb", troughcolor="#e3eaf5", borderwidth=0)


class AbaFerramenta(ttk.Frame):
    """Uma ferramenta ocupa uma página do Notebook, nunca uma janela modal."""
    def __init__(self, parent, titulo, origem=None, retorno="Editor"):
        root = parent.winfo_toplevel()
        notebook = getattr(root, "_editor_abas", None)
        if notebook is None:
            notebook = ttk.Notebook(root)
            notebook.pack(fill="both", expand=True)
            root._editor_abas = notebook
        super().__init__(notebook, padding=8)
        self.notebook, self.titulo, self.origem, self.retorno = notebook, titulo, origem, retorno
        self.editor = getattr(root, "_editor_app", None)
        if self.editor is not None:
            self.editor.registrar_aba(self)
        else:
            notebook.add(self, text=titulo)
            notebook.select(self)

    def lift(self, *_args):
        if self.winfo_exists():
            titulo = self.editor.titulo_aba(self.titulo) if self.editor is not None else self.titulo
            self.notebook.add(self, text=titulo)
            self.notebook.select(self)

    def withdraw(self):
        # Oculta a página sem descartar seu estado (também útil em testes).
        self.notebook.hide(self)

    def destroy(self):
        if not self.winfo_exists():
            return
        editor = self.editor
        super().destroy()
        if editor is not None and not getattr(editor, "encerrando", False):
            editor.aba_removida(self)


class VisualizacaoRedimensionavel(ttk.Frame):
    """Imagem e controles separados por uma divisória visível e arrastável."""
    def __init__(self, parent, orient="vertical", controles_primeiro=False):
        super().__init__(parent)
        self.orient = orient
        self.controles_primeiro = controles_primeiro
        self.expandida = False
        self.posicao = None
        self.inicializada = False
        barra = ttk.Frame(self, padding=(4, 0, 4, 4))
        barra.pack(fill="x")
        ttk.Label(barra, text="Arraste a divisória para ajustar o espaço da imagem", style="Muted.TLabel").pack(side="left")
        self.botao_expandir = ttk.Button(barra, text="Expandir imagem", command=self.alternar)
        self.botao_expandir.pack(side="right")
        self.divisao = tk.PanedWindow(self, orient=orient, bg="#cbd5e1", borderwidth=0,
            sashwidth=10, sashrelief="flat", showhandle=True, handlesize=8,
            sashcursor="sb_v_double_arrow" if orient == "vertical" else "sb_h_double_arrow",
            opaqueresize=True)
        self.divisao.pack(fill="both", expand=True)
        self.visual = ttk.Frame(self.divisao)
        self.painel_controles = ttk.Frame(self.divisao, width=300, height=120)
        if orient == "vertical":
            # Mesmo com o painel reduzido, todas as ações continuam acessíveis.
            self.rolagem = tk.Canvas(self.painel_controles, height=120, bg=FUNDO, highlightthickness=0)
            scroll = ttk.Scrollbar(self.painel_controles, command=self.rolagem.yview)
            scroll.pack(side="right", fill="y")
            self.rolagem.pack(fill="both", expand=True)
            self.rolagem.configure(yscrollcommand=scroll.set)
            self.controles = ttk.Frame(self.rolagem)
            item = self.rolagem.create_window((0, 0), window=self.controles, anchor="nw")
            self.controles.bind("<Configure>", lambda e: self.rolagem.configure(scrollregion=self.rolagem.bbox("all")))
            self.rolagem.bind("<Configure>", lambda e: self.rolagem.itemconfigure(item, width=e.width))
            rolar_em(self.winfo_toplevel(), self.painel_controles, self.rolagem)
        else:
            self.controles = self.painel_controles
        for painel in ((self.painel_controles, self.visual) if controles_primeiro else (self.visual, self.painel_controles)):
            self.divisao.add(painel, minsize=70 if orient == "vertical" else 160,
                stretch="always" if painel == self.visual else "never")
        self.divisao.bind("<Map>", self._iniciar, add="+")

    def _iniciar(self, _evento=None):
        if self.inicializada:
            return
        self.inicializada = True
        self.after_idle(self._posicionar_inicial)

    def _posicionar_inicial(self):
        if not self.winfo_exists() or self.expandida:
            return
        tamanho = self.divisao.winfo_height() if self.orient == "vertical" else self.divisao.winfo_width()
        pedido = self.controles.winfo_reqheight() if self.orient == "vertical" else 300
        controles = min(max(80, pedido), int(tamanho * .45))
        posicao = controles if self.controles_primeiro else tamanho - controles - 10
        self.divisao.sash_place(0, posicao if self.orient == "horizontal" else 0,
                              posicao if self.orient == "vertical" else 0)

    def alternar(self):
        if self.expandida:
            opts = dict(minsize=70 if self.orient == "vertical" else 160, stretch="never")
            if self.controles_primeiro:
                opts["before"] = self.visual
            self.divisao.add(self.painel_controles, **opts)
            self.divisao.update_idletasks()
            if self.posicao is not None:
                self.divisao.sash_place(0, *self.posicao)
            self.botao_expandir.configure(text="Expandir imagem")
        else:
            self.posicao = self.divisao.sash_coord(0)
            self.divisao.forget(self.painel_controles)
            self.botao_expandir.configure(text="Mostrar controles")
        self.expandida = not self.expandida


def rolar_em(root, container, canvas):
    """Roda do mouse limitada ao painel sob o ponteiro, sem interferir no canvas."""
    def rolar(event):
        widget = event.widget
        if isinstance(widget, (ttk.Combobox, ttk.Spinbox, ttk.Entry, ttk.Treeview)):
            return
        while widget is not None:
            if widget == container:
                canvas.yview_scroll(-int(event.delta/120), "units")
                return "break"
            widget = getattr(widget, "master", None)
    binding = root.bind("<MouseWheel>", rolar, add="+")
    def limpar(event):
        if event.widget == container:
            root.unbind("<MouseWheel>", binding)
    container.bind("<Destroy>", limpar, add="+")
