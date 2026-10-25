"""Identidade da janela no Shell do Windows, sem dependências além de ctypes.

QIcon define a imagem da janela; estas propriedades também informam ao Shell
qual ícone e comando representam o aplicativo hospedado pelo Python.
"""

from contextlib import contextmanager
import ctypes
from pathlib import Path
import sys
from uuid import UUID


class _GUID(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(UUID(value).bytes_le)


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _COUNTED_POINTER(ctypes.Structure):
    _fields_ = [("count", ctypes.c_uint32), ("pointer", ctypes.c_void_p)]


class _VALUE(ctypes.Union):
    _fields_ = [
        ("pwszVal", ctypes.c_wchar_p),
        ("counted", _COUNTED_POINTER),
        ("number", ctypes.c_uint64),
    ]


class _PROPVARIANT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("vt", ctypes.c_uint16),
        ("reserved1", ctypes.c_uint16),
        ("reserved2", ctypes.c_uint16),
        ("reserved3", ctypes.c_uint16),
        ("value", _VALUE),
    ]


_FMTID = "9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"
_IID_STORE = "886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"
_PROPERTIES = {
    "relaunch_command": 2,
    "icon_resource": 3,
    "display_name": 4,
    # Setting ID last tells the taskbar to refresh the completed properties.
    "app_id": 5,
}
_HRESULT = ctypes.c_int32
_VT_EMPTY = 0
_VT_LPWSTR = 31
_RPC_E_CHANGED_MODE = 0x80010106


def _check_hresult(result, operation):
    if result < 0:
        code = result & 0xFFFFFFFF
        error = OSError(f"{operation}: HRESULT 0x{code:08X}")
        error.hresult = code
        raise error


def _method(pointer, index, result_type, *arguments):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
    prototype = ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *arguments)
    return prototype(table.contents[index])


@contextmanager
def _property_store(hwnd):
    """Each caller owns its COM apartment reference and interface lifetime."""
    handle = ctypes.c_void_p(getattr(hwnd, "value", hwnd))
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [ctypes.c_void_p]
    user32.IsWindow.restype = ctypes.c_int
    if not user32.IsWindow(handle):
        raise ctypes.WinError(1400)  # ERROR_INVALID_WINDOW_HANDLE

    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole32.CoInitializeEx.restype = _HRESULT
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.PropVariantClear.argtypes = [ctypes.POINTER(_PROPVARIANT)]
    ole32.PropVariantClear.restype = _HRESULT
    initialized = ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    if initialized < 0 and initialized & 0xFFFFFFFF != _RPC_E_CHANGED_MODE:
        _check_hresult(initialized, "CoInitializeEx")
    pointer = ctypes.c_void_p()
    try:
        shell32 = ctypes.WinDLL("shell32")
        shell32.SHGetPropertyStoreForWindow.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)
        ]
        shell32.SHGetPropertyStoreForWindow.restype = _HRESULT
        interface = _GUID.parse(_IID_STORE)
        _check_hresult(
            shell32.SHGetPropertyStoreForWindow(handle, ctypes.byref(interface), ctypes.byref(pointer)),
            "SHGetPropertyStoreForWindow",
        )
        if not pointer:
            raise OSError("SHGetPropertyStoreForWindow: interface ausente")
        yield pointer, ole32
    finally:
        if pointer:
            _method(pointer, 2, ctypes.c_uint32)(pointer)  # IUnknown::Release
        if initialized >= 0:
            ole32.CoUninitialize()


def _write_properties(hwnd, values):
    with _property_store(hwnd) as (store, _):
        set_value = _method(
            store, 6, _HRESULT, ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT)
        )
        for name, pid in _PROPERTIES.items():
            key = _PROPERTYKEY(_GUID.parse(_FMTID), pid)
            variant = _PROPVARIANT()
            value = values[name]
            buffer = None
            if value is not None:
                buffer = ctypes.create_unicode_buffer(value)
                variant.vt = _VT_LPWSTR
                variant.pwszVal = ctypes.cast(buffer, ctypes.c_wchar_p)
            # SetValue copies synchronously. This input buffer belongs to Python,
            # so PropVariantClear must not free it with the COM allocator.
            _check_hresult(
                set_value(store, ctypes.byref(key), ctypes.byref(variant)),
                f"IPropertyStore.SetValue({name})",
            )


def set_window_identity(hwnd, *, app_id, icon_path, relaunch_command, display_name="OpenCV Studio"):
    """Set relaunch metadata and then the explicit AppUserModelID on a window."""
    if sys.platform != "win32":
        return
    values = {
        "app_id": app_id,
        "icon_resource": f"{Path(icon_path).resolve()},0",
        "relaunch_command": relaunch_command,
        "display_name": display_name,
    }
    if any(not isinstance(value, str) or not value or "\0" in value for value in values.values()):
        raise ValueError("A identidade da janela exige textos não vazios e sem caracteres NUL.")
    _write_properties(hwnd, values)


def clear_window_identity(hwnd):
    """Release Shell properties before the owning native window is destroyed."""
    if sys.platform == "win32":
        _write_properties(hwnd, dict.fromkeys(_PROPERTIES))


def read_window_identity(hwnd):
    """Read actual native properties; missing values are represented by None."""
    if sys.platform != "win32":
        return {}
    result = {}
    with _property_store(hwnd) as (store, ole32):
        get_value = _method(
            store, 5, _HRESULT, ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT)
        )
        for name, pid in _PROPERTIES.items():
            key = _PROPERTYKEY(_GUID.parse(_FMTID), pid)
            variant = _PROPVARIANT()
            try:
                _check_hresult(
                    get_value(store, ctypes.byref(key), ctypes.byref(variant)),
                    f"IPropertyStore.GetValue({name})",
                )
                if variant.vt == _VT_EMPTY:
                    result[name] = None
                elif variant.vt == _VT_LPWSTR:
                    result[name] = variant.pwszVal
                else:
                    raise OSError(f"IPropertyStore.GetValue({name}): tipo inesperado VT={variant.vt}")
            finally:
                ole32.PropVariantClear(ctypes.byref(variant))
    return result
