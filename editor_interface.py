"""Componentes visuais compartilhados e ferramentas hospedadas em abas."""
import tkinter as tk
from tkinter import ttk

FUNDO = "#f4f6fa"
SUPERFICIE = "#ffffff"
CANVAS = "#e8edf4"
TEXTO = "#203047"
SUAVE = "#68778d"


def configurar_estilo(root):
    root.configure(bg=FUNDO)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background=FUNDO)
    style.configure("Card.TFrame", background=SUPERFICIE)
    style.configure("TLabel", background=FUNDO, foreground=TEXTO, font=("Segoe UI", 10))
    style.configure("Title.TLabel", font=("Segoe UI", 19, "bold"))
    style.configure("Section.TLabel", font=("Segoe UI", 11, "bold"))
    style.configure("Muted.TLabel", foreground=SUAVE)
    style.configure("TButton", padding=(12, 7), font=("Segoe UI", 10), background=SUPERFICIE,
                    foreground=TEXTO, borderwidth=1, relief="flat")
    style.map("TButton", background=[("active", "#e7edf7")], foreground=[("disabled", "#9aa5b5")])
    style.configure("Accent.TButton", background="#2563eb", foreground="white", borderwidth=0)
    style.map("Accent.TButton", background=[("disabled", "#c9d4e8"), ("active", "#1d4ed8")],
              foreground=[("disabled", "#ffffff")])
    style.configure("TNotebook", background=FUNDO, borderwidth=0, bordercolor=FUNDO, tabmargins=(0, 0, 0, 8))
    style.configure("TNotebook.Tab", padding=(18, 9), background=FUNDO, foreground=SUAVE,
                    font=("Segoe UI", 10), bordercolor=FUNDO, lightcolor=FUNDO, darkcolor=FUNDO)
    style.map("TNotebook.Tab", background=[("selected", SUPERFICIE)],
              foreground=[("selected", "#2563eb")], padding=[("selected", (18, 9))])
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
            self.notebook.add(self, text=self.titulo)
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
