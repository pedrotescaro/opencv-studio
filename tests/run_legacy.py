"""Run every legacy regression while collecting Tk cycles on the main thread.

Destroying a Tk widget does not necessarily release Python reference cycles.
An image-processing worker can otherwise trigger their collection and destroy
the Tcl interpreter on the wrong thread. No test or exception is suppressed.
"""

import gc
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class MainThreadCollectionResult(unittest.TextTestResult):
    def startTest(self, test):
        # The previous test case has now left its suite, so its widget cycles
        # can be finalized here instead of during a NumPy allocation in a worker.
        gc.collect()
        super().startTest(test)


def main():
    automatic_collection = gc.isenabled()
    gc.disable()
    try:
        suite = unittest.defaultTestLoader.discover(
            str(ROOT / "tests"), pattern="test_[!q]*.py"
        )
        if not suite.countTestCases():
            raise RuntimeError("Nenhum teste de regressão foi encontrado.")
        result = unittest.TextTestRunner(
            verbosity=2, resultclass=MainThreadCollectionResult
        ).run(suite)
        gc.collect()
        return 0 if result.wasSuccessful() else 1
    finally:
        if automatic_collection:
            gc.enable()


if __name__ == "__main__":
    sys.exit(main())
