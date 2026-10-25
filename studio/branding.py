"""Identidade visual compartilhada pelo aplicativo e suas janelas."""

from pathlib import Path
import logging
import subprocess
import sys


APP_ID = "OpenCVStudio.Desktop"
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
BRAND_FOLDER = RESOURCE_ROOT / "assets" / "branding"
LOGO_PATH = BRAND_FOLDER / "logo.png"
ICON_PATH = BRAND_FOLDER / "app-icon.ico"


def application_icon():
    from PySide6.QtGui import QIcon

    icon = QIcon(str(ICON_PATH))
    return icon if not icon.isNull() else QIcon(str(BRAND_FOLDER / "app-icon.png"))


def configure_platform_identity():
    """Dá à janela uma identidade própria na barra de tarefas do Windows."""
    if sys.platform == "win32":
        import ctypes

        setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        result = setter(APP_ID)
        if result < 0:
            raise OSError(f"Não foi possível configurar a identidade Windows: 0x{result & 0xffffffff:08X}")


def relaunch_command():
    """O Windows deve reabrir o aplicativo com seu ambiente e caminho corretos."""
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([sys.executable])
    runtime = Path(sys.executable)
    windowed = runtime.with_name("pythonw.exe")
    if sys.platform == "win32" and windowed.is_file():
        runtime = windowed
    return subprocess.list2cmdline([str(runtime), str(RESOURCE_ROOT / "main.py")])


def configure_window_identity(window):
    """Associa o ICO ao grupo da barra, além do ícone da barra de título Qt."""
    if sys.platform != "win32":
        return None
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() != "windows":
        return None  # O backend de testes offscreen não fornece um HWND real.
    from .windows_branding import set_window_identity

    hwnd = int(window.winId())
    try:
        set_window_identity(
            hwnd, app_id=APP_ID, icon_path=ICON_PATH,
            relaunch_command=relaunch_command(), display_name="OpenCV Studio",
        )
    except OSError:
        logging.getLogger(__name__).exception("Falha ao associar o ícone à barra de tarefas")
        return None
    return hwnd


def release_window_identity(hwnd):
    if hwnd is not None and sys.platform == "win32":
        from .windows_branding import clear_window_identity

        try:
            clear_window_identity(hwnd)
        except OSError:
            logging.getLogger(__name__).exception("Falha ao liberar as propriedades da janela")
