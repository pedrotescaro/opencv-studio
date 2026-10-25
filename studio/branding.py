"""Identidade visual compartilhada pelo aplicativo e suas janelas."""

from pathlib import Path
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

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
