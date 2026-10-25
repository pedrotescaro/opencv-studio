"""Real Shell property roundtrips on an owned, hidden native Windows window."""

import ctypes
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from studio.windows_branding import (
    _PROPVARIANT,
    _PROPERTYKEY,
    clear_window_identity,
    read_window_identity,
    set_window_identity,
)


@unittest.skipUnless(sys.platform == "win32", "Propriedades nativas do Shell Windows")
class WindowsBrandingTests(unittest.TestCase):
    def setUp(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.CreateWindowExW.argtypes = [
            ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        self.user32.CreateWindowExW.restype = ctypes.c_void_p
        self.user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        self.user32.DestroyWindow.restype = ctypes.c_int
        self.hwnd = self.user32.CreateWindowExW(
            0, "STATIC", "OpenCV Studio test (hidden)", 0,
            0, 0, 10, 10, None, None, None, None,
        )
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.temporary = tempfile.TemporaryDirectory(prefix="opencv_ícone ")
        self.icon = Path(self.temporary.name) / "monograma azul ç.ico"
        self.command = subprocess.list2cmdline([
            sys.executable, str(Path(self.temporary.name) / "ação principal.py")
        ])

    def tearDown(self):
        clear_window_identity(self.hwnd)
        self.user32.DestroyWindow(self.hwnd)
        self.temporary.cleanup()

    def test_native_property_types_have_windows_abi_sizes(self):
        self.assertEqual(ctypes.sizeof(_PROPERTYKEY), 20)
        self.assertEqual(ctypes.sizeof(_PROPVARIANT), 24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)
        self.assertEqual(_PROPVARIANT.value.offset, 8)

    def test_real_shell_roundtrip_preserves_unicode_paths_and_relaunch_command(self):
        set_window_identity(
            self.hwnd, app_id="OpenCVStudio.TestWindow", icon_path=self.icon,
            relaunch_command=self.command, display_name="OpenCV Studio · Visão",
        )
        self.assertEqual(read_window_identity(self.hwnd), {
            "app_id": "OpenCVStudio.TestWindow",
            "icon_resource": f"{self.icon.resolve()},0",
            "relaunch_command": self.command,
            "display_name": "OpenCV Studio · Visão",
        })

    def test_clearing_removes_all_properties_and_allows_reapplication(self):
        set_window_identity(
            self.hwnd, app_id="OpenCVStudio.TestWindow", icon_path=self.icon,
            relaunch_command=self.command,
        )
        clear_window_identity(self.hwnd)
        self.assertEqual(set(read_window_identity(self.hwnd).values()), {None})
        set_window_identity(
            self.hwnd, app_id="OpenCVStudio.TestWindow2", icon_path=self.icon,
            relaunch_command=self.command,
        )
        self.assertEqual(read_window_identity(self.hwnd)["app_id"], "OpenCVStudio.TestWindow2")

    def test_invalid_native_handle_raises_without_access_violation(self):
        for operation in (
            lambda: read_window_identity(0),
            lambda: clear_window_identity(0),
            lambda: set_window_identity(0, app_id="OpenCVStudio.TestWindow", icon_path=self.icon,
                                        relaunch_command=self.command),
        ):
            with self.subTest(operation=operation), self.assertRaises(OSError):
                operation()

    def test_invalid_strings_do_not_partially_replace_existing_identity(self):
        set_window_identity(
            self.hwnd, app_id="OpenCVStudio.TestWindow", icon_path=self.icon,
            relaunch_command=self.command,
        )
        before = read_window_identity(self.hwnd)
        with self.assertRaises(ValueError):
            set_window_identity(
                self.hwnd, app_id="OpenCVStudio.TestWindow2", icon_path=self.icon,
                relaunch_command="bad\0command",
            )
        self.assertEqual(read_window_identity(self.hwnd), before)


if __name__ == "__main__":
    unittest.main()
