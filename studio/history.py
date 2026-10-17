"""Unbounded edit history stores recipes instead of full image copies."""

from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass


@dataclass
class HistoryEntry:
    label: str
    operations: list


class History:
    def __init__(self):
        self.entries: list[HistoryEntry] = [HistoryEntry("Original", [])]
        self.index = 0

    @property
    def can_undo(self):
        return self.index > 0

    @property
    def can_redo(self):
        return self.index < len(self.entries) - 1

    @property
    def current(self):
        return deepcopy(self.entries[self.index].operations)

    def reset(self, label="Original"):
        self.entries = [HistoryEntry(label, [])]
        self.index = 0

    def push(self, operations, label):
        del self.entries[self.index + 1 :]
        self.entries.append(HistoryEntry(str(label), deepcopy(operations)))
        self.index = len(self.entries) - 1

    def undo(self):
        if not self.can_undo:
            return False
        self.index -= 1
        return True

    def redo(self):
        if not self.can_redo:
            return False
        self.index += 1
        return True

    def jump(self, index):
        if not 0 <= int(index) < len(self.entries):
            return False
        self.index = int(index)
        return True
