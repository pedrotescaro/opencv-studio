"""Operações adicionais e editor visual de elementos estruturantes."""
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import cv2
import numpy as np

MORFOLOGIA = {
    "Erosão": cv2.MORPH_ERODE, "Dilatação": cv2.MORPH_DILATE,
    "Opening": cv2.MORPH_OPEN, "Closing": cv2.MORPH_CLOSE,
    "Gradiente morfológico": cv2.MORPH_GRADIENT,
    "Top-hat": cv2.MORPH_TOPHAT, "Black-hat": cv2.MORPH_BLACKHAT,
    "Hit-or-miss": cv2.MORPH_HITMISS,
}
FORMAS = ("Retângulo", "Elipse", "Cruz", "Losango", "Linha horizontal",
          "Linha vertical", "Diagonal", "Diagonal inversa", "Personalizado")
BORDAS = {"Padrão morfológico": cv2.BORDER_CONSTANT,
          "Replicar": cv2.BORDER_REPLICATE, "Refletir": cv2.BORDER_REFLECT_101,
          "Constante preta": cv2.BORDER_CONSTANT, "Constante branca": cv2.BORDER_CONSTANT}
EXTRAS = {
    "Cores": ["Saturação", "Matiz", "Temperatura"],
    "Luz e contraste": ["Normalizar"],
    "Bordas": ["Scharr X", "Scharr Y", "Magnitude do gradiente"],
    "Efeitos": ["Estilização", "Lápis cinza", "Lápis colorido", "Preservar bordas"],
    "Segmentação": ["Threshold inverso", "Threshold truncado", "Threshold to-zero",
                    "Threshold to-zero inverso", "Threshold Triangle", "Adaptativo médio",
                    "Distância L1", "Distância L2", "Distância xadrez", "Contornos"],
    "Desfoque": ["Desfoque de movimento"],
}
MAPAS = {"Mapa " + name.title(): getattr(cv2, "COLORMAP_" + name)
         for name in ("AUTUMN", "BONE", "JET", "WINTER", "RAINBOW", "OCEAN", "SUMMER",
                      "SPRING", "COOL", "HSV", "PINK", "HOT", "PARULA", "MAGMA",
                      "INFERNO", "PLASMA", "VIRIDIS", "CIVIDIS", "TWILIGHT",
                      "TWILIGHT_SHIFTED", "TURBO", "DEEPGREEN")
         if hasattr(cv2, "COLORMAP_" + name)}
EXTRAS["Mapas de cores"] = list(MAPAS)
# Rótulo, mínimo, máximo e valor inicial dos controles.
PARAMETROS = {
    "Saturação": [("Saturação (%)", 0, 300, 120)],
    "Matiz": [("Deslocamento (graus)", -180, 180, 30)],
    "Temperatura": [("Frio ← → quente", -100, 100, 20)],
    "Desfoque de movimento": [("Comprimento", 1, 51, 9), ("Ângulo", -180, 180, 0)],
    "CLAHE": [("Limite × 10", 1, 100, 20), ("Grade", 2, 32, 8)],
    "Denoise": [("Força", 1, 40, 10)],
    "Detail Enhance": [("Sigma espacial", 1, 100, 10), ("Sigma de cor (%)", 1, 100, 15)],
    "Contornos": [("Limiar binário", 0, 255, 127), ("Espessura", 1, 10, 2)],
}
for _name in ("Threshold inverso", "Threshold truncado", "Threshold to-zero", "Threshold to-zero inverso"):
    PARAMETROS[_name] = [("Limiar", 0, 255, 127)]
PARAMETROS["Adaptativo médio"] = [("Bloco (ímpar)", 3, 51, 11), ("Constante C", -20, 20, 2)]
for _name in ("Estilização", "Lápis cinza", "Lápis colorido", "Preservar bordas"):
    PARAMETROS[_name] = [("Sigma espacial", 1, 200, 60), ("Sigma de cor (%)", 1, 100, 30)]


def criar_kernel(forma, largura, altura):
    if not (1 <= largura <= 31 and 1 <= altura <= 31):
        raise ValueError("As dimensões devem estar entre 1 e 31.")
    if forma in ("Retângulo", "Elipse", "Cruz"):
        tipo = {"Retângulo": cv2.MORPH_RECT, "Elipse": cv2.MORPH_ELLIPSE, "Cruz": cv2.MORPH_CROSS}[forma]
        return cv2.getStructuringElement(tipo, (largura, altura)).astype(np.int8)
    y, x = np.indices((altura, largura))
    if forma == "Losango":
        return ((abs(x - largura // 2) / max(1, largura // 2) +
                 abs(y - altura // 2) / max(1, altura // 2)) <= 1).astype(np.int8)
    k = np.zeros((altura, largura), np.int8)
    if forma == "Linha horizontal":
        k[altura // 2, :] = 1
    elif forma == "Linha vertical":
        k[:, largura // 2] = 1
    elif forma in ("Diagonal", "Diagonal inversa"):
        cv2.line(k, (0, 0 if forma == "Diagonal" else altura - 1),
                 (largura - 1, altura - 1 if forma == "Diagonal" else 0), 1, 1)
    else:
        raise ValueError("Forma desconhecida.")
    return k


def validar_morfologia(config):
    k = np.asarray(config["kernel"])
    if k.ndim != 2 or not all(1 <= n <= 31 for n in k.shape):
        raise ValueError("A matriz precisa ter entre 1 e 31 linhas e colunas.")
    if not np.isin(k, [-1, 0, 1]).all() or not np.any(k == 1):
        raise ValueError("Use apenas -1, 0 e 1, com pelo menos uma célula 1.")
    anchor = tuple(config["anchor"])
    if len(anchor) != 2 or any(type(v) is not int for v in anchor):
        raise ValueError("A âncora deve conter dois inteiros.")
    if anchor != (-1, -1) and not (0 <= anchor[0] < k.shape[1] and 0 <= anchor[1] < k.shape[0]):
        raise ValueError("A âncora deve estar dentro da matriz.")
    if type(config["iterations"]) is not int or not 1 <= config["iterations"] <= 30:
        raise ValueError("Use entre 1 e 30 iterações.")
    if config["border"] not in BORDAS or config["mode"] not in ("Colorida", "Cinza", "Binária"):
        raise ValueError("Modo de imagem ou borda inválidos.")
    if type(config["threshold"]) is not int or not 0 <= config["threshold"] <= 255:
        raise ValueError("O limiar deve estar entre 0 e 255.")
    return dict(config, kernel=k.astype(np.int8), anchor=anchor)


def aplicar_morfologia(img, filtro, config):
    c = validar_morfologia(config)
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    source = img if c["mode"] == "Colorida" else gray
    if c["mode"] == "Binária" or filtro == "Hit-or-miss":
        source = cv2.threshold(gray, c["threshold"], 255, cv2.THRESH_BINARY)[1]
    kernel = c["kernel"] if filtro == "Hit-or-miss" else (c["kernel"] == 1).astype(np.uint8)
    kwargs = dict(anchor=c["anchor"], iterations=c["iterations"], borderType=BORDAS[c["border"]])
    if c["border"].startswith("Constante"):
        value = 255 if c["border"] == "Constante branca" else 0
        kwargs["borderValue"] = (value,) * 4
    return cv2.morphologyEx(source, MORFOLOGIA[filtro], kernel, **kwargs)


def processar_extra(img, filtro, p1, p2):
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cor = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img
    if filtro in MAPAS:
        return cv2.applyColorMap(gray, MAPAS[filtro])
    if filtro == "Normalizar":
        return cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    if filtro in ("Saturação", "Matiz"):
        hsv = cv2.cvtColor(cor, cv2.COLOR_BGR2HSV)
        if filtro == "Matiz":
            hsv[:, :, 0] = (hsv[:, :, 0].astype(np.int16) + int(p1 / 2)) % 180
        else:
            hsv[:, :, 1] = np.clip(hsv[:, :, 1].astype(float) * p1 / 100, 0, 255)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    if filtro == "Temperatura":
        return np.clip(cor.astype(np.float32) + np.array([-p1, 0, p1]), 0, 255).astype(np.uint8)
    thresholds = {"Threshold inverso": cv2.THRESH_BINARY_INV, "Threshold truncado": cv2.THRESH_TRUNC,
                  "Threshold to-zero": cv2.THRESH_TOZERO, "Threshold to-zero inverso": cv2.THRESH_TOZERO_INV,
                  "Threshold Triangle": cv2.THRESH_BINARY | cv2.THRESH_TRIANGLE}
    if filtro in thresholds:
        return cv2.threshold(gray, p1, 255, thresholds[filtro])[1]
    if filtro == "Adaptativo médio":
        return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY,
                                     max(3, int(p1) | 1), p2)
    if filtro.startswith("Distância "):
        mode = {"Distância L1": cv2.DIST_L1, "Distância L2": cv2.DIST_L2, "Distância xadrez": cv2.DIST_C}[filtro]
        binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        dist = cv2.distanceTransform(binary, mode, 3)
        return cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if filtro == "Contornos":
        binary = cv2.threshold(gray, p1, 255, cv2.THRESH_BINARY)[1]
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        return cv2.drawContours(cor.copy(), contours, -1, (50, 220, 120), max(1, int(p2)))
    if filtro in ("Scharr X", "Scharr Y", "Magnitude do gradiente"):
        sx = cv2.Scharr(gray, cv2.CV_32F, 1, 0)
        sy = cv2.Scharr(gray, cv2.CV_32F, 0, 1)
        return cv2.convertScaleAbs(sx if filtro == "Scharr X" else sy if filtro == "Scharr Y" else cv2.magnitude(sx, sy))
    if filtro == "Desfoque de movimento":
        n = max(1, int(p1) | 1)
        kernel = np.zeros((n, n), np.float32)
        kernel[n // 2] = 1
        kernel = cv2.warpAffine(kernel, cv2.getRotationMatrix2D((n // 2, n // 2), p2, 1), (n, n))
        return cv2.filter2D(img, -1, kernel / max(float(kernel.sum()), 1e-8))
    if filtro == "Estilização":
        return cv2.stylization(cor, sigma_s=p1, sigma_r=p2 / 100)
    if filtro in ("Lápis cinza", "Lápis colorido"):
        return cv2.pencilSketch(cor, sigma_s=p1, sigma_r=p2 / 100, shade_factor=0.05)[int(filtro == "Lápis colorido")]
    if filtro == "Preservar bordas":
        return cv2.edgePreservingFilter(cor, flags=1, sigma_s=p1, sigma_r=p2 / 100)
    raise ValueError(f"Filtro adicional desconhecido: {filtro}")


class RecursosEditor:
    def inicializar_recursos(self):
        self.morfologia = dict(kernel=np.ones((3, 3), np.int8), anchor=(-1, -1),
                               iterations=1, border="Padrão morfológico", mode="Colorida", threshold=127)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef2f7")
        style.configure("TLabel", background="#eef2f7", foreground="#223047", font=("Segoe UI", 10))
        style.configure("TButton", padding=(8, 6), font=("Segoe UI", 10))
        style.configure("Accent.TButton", background="#2563eb", foreground="white")
        style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("disabled", "#a8b3c5")])

    def adicionar_recursos_interface(self, painel):
        self.busca = tk.StringVar()
        ttk.Label(painel, text="Buscar em todos os filtros").pack(anchor="w")
        entry = ttk.Entry(painel, textvariable=self.busca)
        entry.pack(fill="x", pady=(2, 4))
        entry.bind("<KeyRelease>", self.buscar_filtros)
        self.resultados = tk.Listbox(painel, height=4, exportselection=False, font=("Segoe UI", 10))
        self.resultados.bind("<<ListboxSelect>>", self.escolher_busca)
        self.btn_kernel = ttk.Button(painel, text="Elemento estruturante e morfologia…", command=self.editar_kernel)
        self.btn_kernel.pack(fill="x", pady=4)
        self.resumo_kernel = ttk.Label(painel, wraplength=280)
        self.resumo_kernel.pack(fill="x", pady=(0, 5))
        self.atualizar_resumo_kernel()

    def buscar_filtros(self, _event=None):
        import unicodedata
        def normalizar(s):
            return "".join(c for c in unicodedata.normalize("NFD", s.casefold()) if not unicodedata.combining(c))
        termo = normalizar(self.busca.get().strip())
        self.resultados.delete(0, "end")
        if not termo:
            self.resultados.pack_forget()
            return
        for lista in self.filtros.values():
            for filtro in lista:
                if termo in normalizar(filtro):
                    self.resultados.insert("end", filtro)
        self.resultados.pack(fill="x", before=self.btn_kernel)

    def escolher_busca(self, _event=None):
        if not self.resultados.curselection():
            return
        filtro = self.resultados.get(self.resultados.curselection()[0])
        categoria = next(c for c, itens in self.filtros.items() if filtro in itens)
        self.categoria_var.set(categoria)
        self.combo_filtro["values"] = self.filtros[categoria]
        self.filtro_var.set(filtro)
        self.filtro_selecionado()

    def atualizar_resumo_kernel(self):
        c = self.morfologia
        h, w = c["kernel"].shape
        self.resumo_kernel.config(text=f"Morfologia: {w} × {h} • {c['iterations']} iteração(ões) • {c['mode']}")

    def snapshot_morfologia(self):
        return dict(self.morfologia, kernel=self.morfologia["kernel"].copy())

    def editar_kernel(self):
        if getattr(self, "janela_kernel", None) is not None and self.janela_kernel.winfo_exists():
            self.janela_kernel.lift()
            return
        win = self.janela_kernel = tk.Toplevel(self.root)
        win.title("Laboratório de morfologia • elemento estruturante")
        win.geometry("820x680")
        win.minsize(780, 650)
        win.transient(self.root)
        win.grab_set()
        box = ttk.Frame(win, padding=16)
        box.pack(fill="both", expand=True)
        draft = self.snapshot_morfologia()
        matrix = draft["kernel"]
        h, w = matrix.shape
        variables = {"largura": tk.StringVar(value=w), "altura": tk.StringVar(value=h),
                     "forma": tk.StringVar(value="Personalizado"),
                     **{key: tk.StringVar(value=draft[key]) for key in ("iterations", "threshold", "border", "mode")},
                     "x": tk.StringVar(value=draft["anchor"][0]), "y": tk.StringVar(value=draft["anchor"][1])}
        ttk.Label(box, text="Desenhe seu elemento estruturante", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(box, text="Clique: 0 → 1 → -1. Arraste para pintar. Clique direito define a âncora.\n"
                  "1 = objeto; 0 = ignorar; -1 = fundo (somente Hit-or-miss). Nas outras operações, -1 é ignorado.").pack(anchor="w", pady=8)
        top = ttk.Frame(box)
        top.pack(fill="x")
        ttk.Combobox(top, textvariable=variables["forma"], values=FORMAS, state="readonly", width=20).pack(side="left")
        for key, label in (("largura", "Largura"), ("altura", "Altura")):
            ttk.Label(top, text=label).pack(side="left", padx=(8, 3))
            ttk.Spinbox(top, from_=1, to=31, width=4, textvariable=variables[key]).pack(side="left")
        canvas = tk.Canvas(box, width=720, height=240, bg="#172235", highlightthickness=0)
        canvas.pack(fill="both", expand=True, pady=10)
        paint = {"value": 1}
        def geometry():
            rows, cols = matrix.shape
            size = min((canvas.winfo_width() - 8) / cols, (canvas.winfo_height() - 8) / rows, 42)
            return size, (canvas.winfo_width() - cols * size) / 2, (canvas.winfo_height() - rows * size) / 2
        def draw(_event=None):
            canvas.delete("all")
            size, ox, oy = geometry()
            try:
                ax, ay = int(variables["x"].get()), int(variables["y"].get())
            except ValueError:
                ax, ay = -1, -1
            if (ax, ay) == (-1, -1):
                ay, ax = matrix.shape[0] // 2, matrix.shape[1] // 2
            for y, row in enumerate(matrix):
                for x, value in enumerate(row):
                    left, up = ox + x * size, oy + y * size
                    canvas.create_rectangle(left, up, left + size, up + size,
                        fill={0: "#344258", 1: "#3b82f6", -1: "#e77937"}[int(value)],
                        outline="#ffe477" if (x, y) == (ax, ay) else "#172235",
                        width=3 if (x, y) == (ax, ay) else 1)
                    if size >= 18:
                        canvas.create_text(left + size / 2, up + size / 2, text=str(value), fill="white")
        def cell(event, drag=False, anchor=False):
            size, ox, oy = geometry()
            x, y = int(np.floor((event.x - ox) / size)), int(np.floor((event.y - oy) / size))
            if 0 <= y < matrix.shape[0] and 0 <= x < matrix.shape[1]:
                if anchor:
                    variables["x"].set(x)
                    variables["y"].set(y)
                else:
                    if not drag:
                        paint["value"] = {0: 1, 1: -1, -1: 0}[int(matrix[y, x])]
                    matrix[y, x] = paint["value"]
                    variables["forma"].set("Personalizado")
                draw()
        canvas.bind("<Configure>", draw)
        canvas.bind("<Button-1>", cell)
        canvas.bind("<B1-Motion>", lambda e: cell(e, drag=True))
        canvas.bind("<Button-3>", lambda e: cell(e, anchor=True))
        def generate():
            nonlocal matrix
            try:
                w, h = int(variables["largura"].get()), int(variables["altura"].get())
                if not (1 <= w <= 31 and 1 <= h <= 31):
                    raise ValueError("Dimensões: 1 a 31.")
                forma = variables["forma"].get()
                matrix = np.zeros((h, w), np.int8) if forma == "Personalizado" else criar_kernel(forma, w, h)
                variables["x"].set(-1)
                variables["y"].set(-1)
                draw()
            except ValueError as exc:
                messagebox.showerror("Dimensões inválidas", str(exc), parent=win)
        ttk.Button(top, text="Gerar matriz", command=generate).pack(side="left", padx=8)
        opts = ttk.Frame(box)
        opts.pack(fill="x")
        for i, (key, label, low, high) in enumerate((("iterations", "Iterações", 1, 30),
                 ("threshold", "Limiar binário", 0, 255), ("x", "Âncora X", -1, 30), ("y", "Âncora Y", -1, 30))):
            ttk.Label(opts, text=label).grid(row=0, column=i, sticky="w", padx=4)
            ttk.Spinbox(opts, from_=low, to=high, width=10, textvariable=variables[key], command=draw).grid(row=1, column=i, padx=4)
        ttk.Label(box, text="Âncora (-1, -1) = centro automático. Coordenadas começam em zero.").pack(anchor="w", pady=6)
        bottom = ttk.Frame(box)
        bottom.pack(fill="x", pady=4)
        for key, label, values in (("mode", "Imagem", ("Colorida", "Cinza", "Binária")), ("border", "Borda", tuple(BORDAS))):
            ttk.Label(bottom, text=label).pack(side="left", padx=4)
            ttk.Combobox(bottom, textvariable=variables[key], values=values, state="readonly", width=23).pack(side="left")
        ttk.Label(box, text="Hit-or-miss sempre usa imagem binária. O limiar define os pixels brancos.\n"
                  "As configurações são usadas em todas as operações da categoria Morfologia.").pack(anchor="w", pady=8)
        def config():
            return validar_morfologia(dict(kernel=matrix.copy(), anchor=(int(variables["x"].get()), int(variables["y"].get())),
                iterations=int(variables["iterations"].get()), threshold=int(variables["threshold"].get()),
                mode=variables["mode"].get(), border=variables["border"].get()))
        def save():
            try:
                c = config()
                path = filedialog.asksaveasfilename(parent=win, defaultextension=".json", filetypes=[("Elemento estruturante", "*.json")])
                if path:
                    c["kernel"] = c["kernel"].tolist()
                    with open(path, "w", encoding="utf-8") as out:
                        json.dump(c, out, ensure_ascii=False, indent=2)
            except (ValueError, OSError) as exc:
                messagebox.showerror("Não foi possível exportar", str(exc), parent=win)
        def load():
            nonlocal matrix
            path = filedialog.askopenfilename(parent=win, filetypes=[("Elemento estruturante", "*.json")])
            if not path:
                return
            try:
                with open(path, encoding="utf-8") as source:
                    c = validar_morfologia(json.load(source))
                matrix = c["kernel"].copy()
                for key in ("iterations", "threshold", "border", "mode"):
                    variables[key].set(c[key])
                for key, value in zip(("x", "y", "altura", "largura"), (*c["anchor"], *matrix.shape)):
                    variables[key].set(value)
                variables["forma"].set("Personalizado")
                draw()
            except (ValueError, OSError, KeyError, TypeError) as exc:
                messagebox.showerror("Arquivo inválido", str(exc), parent=win)
        def confirm():
            try:
                self.morfologia = config()
            except ValueError as exc:
                messagebox.showerror("Configuração inválida", str(exc), parent=win)
                return
            self.atualizar_resumo_kernel()
            if self.filtro_var.get() in MORFOLOGIA and self.live_preview.get():
                self.agendar_preview()
            win.destroy()
        buttons = ttk.Frame(box)
        buttons.pack(fill="x", pady=4)
        ttk.Button(buttons, text="Importar JSON", command=load).pack(side="left", padx=3)
        ttk.Button(buttons, text="Exportar JSON", command=save).pack(side="left", padx=3)
        ttk.Button(buttons, text="Cancelar", command=win.destroy).pack(side="right", padx=3)
        ttk.Button(buttons, text="Usar elemento", style="Accent.TButton", command=confirm).pack(side="right", padx=3)
        win.bind("<Return>", lambda e: (confirm(), "break")[-1])
        win.bind("<Escape>", lambda e: (win.destroy(), "break")[-1])
