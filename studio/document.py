"""Image source, operation recipe and unlimited reversible document history."""

from __future__ import annotations
from copy import deepcopy
from .filters import Operation, render_pipeline, validate_image
from .history import History


class Document:
    def __init__(self):
        self.original = None
        self.operations: list[Operation] = []
        self.path = None
        self.history = History()
        self.saved_index = 0

    @property
    def label(self):
        return self.history.entries[self.history.index].label

    @property
    def modified(self):
        return self.history.index != self.saved_index

    def open(self, image, path=None):
        validate_image(image)
        self.original = image.copy()
        self.original.flags.writeable = False
        self.operations = []
        self.path = str(path) if path is not None else None
        self.history.reset()
        self.saved_index = 0

    def _require_image(self):
        if self.original is None:
            raise ValueError("Abra uma imagem antes de editar.")

    def commit(self, operation):
        self._require_image()
        self.set_operations(
            self.operations + [operation], operation.name or operation.kind
        )

    def set_operations(self, operations, label="Editar"):
        self._require_image()
        if any(not isinstance(op, Operation) for op in operations):
            raise TypeError("A pilha deve conter operações válidas.")
        self.operations = deepcopy(list(operations))
        if self.saved_index > self.history.index:
            self.saved_index = -1
        self.history.push(self.operations, label)

    def undo(self):
        changed = self.history.undo()
        if changed:
            self.operations = self.history.current
        return changed

    def redo(self):
        changed = self.history.redo()
        if changed:
            self.operations = self.history.current
        return changed

    def jump(self, index):
        changed = self.history.jump(index)
        if changed:
            self.operations = self.history.current
        return changed

    def render(self, max_size=None):
        self._require_image()
        return render_pipeline(self.original, self.operations, max_size)

    def mark_saved(self, path=None):
        if path is not None:
            self.path = str(path)
        self.saved_index = self.history.index

    def duplicate(self):
        self._require_image()
        copy = Document()
        copy.open(self.original)
        copy.operations = deepcopy(self.operations)
        copy.history = deepcopy(self.history)
        copy.saved_index = -1
        return copy
