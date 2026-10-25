"""Entrada do aplicativo Qt. Execute: python main.py."""

import argparse
import sys
from pathlib import Path


def main():
    from studio.branding import application_icon, configure_platform_identity

    configure_platform_identity()
    from PySide6.QtGui import QFont, QPalette, QColor
    from PySide6.QtWidgets import QApplication
    from studio.ui.window import MainWindow
    from studio.ui.theme import STYLE

    parser = argparse.ArgumentParser(description="OpenCV Studio Qt")
    parser.add_argument("image", nargs="?", help="Imagem opcional para abrir")
    parser.add_argument(
        "--faces", action="store_true", help="Abrir área de rostos e chamada"
    )
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("OpenCV Studio")
    app.setOrganizationName("OpenCV Studio")
    app.setWindowIcon(application_icon())
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLE)
    palette = app.palette()
    for role, color in (
        (QPalette.ColorRole.Window, "#252526"),
        (QPalette.ColorRole.Base, "#1e1e1e"),
        (QPalette.ColorRole.Text, "#e4e4e7"),
        (QPalette.ColorRole.WindowText, "#e4e4e7"),
        (QPalette.ColorRole.Highlight, "#3478cb"),
        (QPalette.ColorRole.HighlightedText, "#ffffff"),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    window = MainWindow()
    window.show()
    if args.image:
        window.open_path(str(Path(args.image).resolve()))
    if args.faces:
        window.set_workspace(2)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
