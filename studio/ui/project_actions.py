"""Asynchronous project I/O, distinct from flattened image export."""

from pathlib import Path
from copy import deepcopy
from PySide6.QtWidgets import QFileDialog
from studio.filters import render_pipeline
from studio.project import read_project, write_project


class ProjectActions:
    def open_project(self, path=None, confirmed=False):
        if not isinstance(path, (str, Path)):
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Abrir projeto com camadas",
                "",
                "Projeto OpenCV Studio (*.ocvproj)",
            )
        if not path or (not confirmed and not self._confirm_discard()):
            return
        self._load_generation += 1
        generation = self._load_generation
        self.status("Abrindo projeto com camadas…")

        def load():
            original, operations = read_project(path)
            render_pipeline(
                original, operations
            )  # Validate before replacing a document.
            return original, operations

        def loaded(result):
            if generation != self._load_generation:
                return
            original, operations = result
            self.open_array(original)
            if operations:
                self.document.set_operations(operations, "Projeto carregado")
            self.project_path = str(path)
            self.modified = False
            self.name_label.setText(Path(path).name + "  ")
            self._update_history()
            self.request_render(False)
            self.layer_dock.show()
            self.layer_dock.raise_()

        self._job(load, loaded)

    def save_project(self, save_as=False):
        if self.document.original is None or not self.apply_draft():
            return
        path = self.project_path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Salvar projeto com camadas",
                path or "composicao.ocvproj",
                "Projeto OpenCV Studio (*.ocvproj)",
            )
        if not path:
            return
        if not Path(path).suffix:
            path += ".ocvproj"
        self._save_project(path)

    def _save_project(self, path):
        if self.document.original is None or not self.apply_draft():
            return
        original = self.document.original
        operations = deepcopy(self.document.operations)
        entry = self.document.history.entries[self.document.history.index]
        self.status("Salvando projeto com camadas…")

        def saved(result):
            if self.document.original is original:
                self.project_path = str(result)
                self.name_label.setText(Path(result).name + "  ")
                if self.document.history.entries[self.document.history.index] is entry:
                    self.modified = False
            self.status(f"Projeto salvo: {result}")

        self._job(
            lambda: write_project(path, original, operations),
            saved,
            pool=self.export_pool,
        )
