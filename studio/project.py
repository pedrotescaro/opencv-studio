"""Portable .ocvproj files: JSON recipes and NumPy assets, never pickle/code."""

import io
import json
import os
from pathlib import Path
import tempfile
import zipfile
import math
import numpy as np
from .filters import Operation, validate_image
from .layers import layer_rect, BLEND_MODES

MAX_BYTES = 1_000_000_000


def write_project(path, original, operations):
    path = Path(path)
    validate_image(original)
    if path.suffix.lower() != ".ocvproj":
        raise ValueError("Use a extensão .ocvproj para preservar as camadas.")
    assets, seen = [], {}

    def encode(value):
        if isinstance(value, np.ndarray):
            if value.dtype.hasobject or value.dtype.kind not in "biuf":
                raise ValueError("O projeto não aceita matrizes de objetos.")
            key = id(value)
            if key not in seen:
                seen[key] = f"arrays/{len(assets)}.npy"
                assets.append(value)
            return {"__array__": seen[key]}
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, tuple):
            return {"__tuple__": [encode(item) for item in value]}
        if isinstance(value, list):
            return [encode(item) for item in value]
        if isinstance(value, dict):
            return {str(key): encode(item) for key, item in value.items()}
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise ValueError("O projeto contém um parâmetro incompatível.")

    payload = {
        "format": "opencv-studio",
        "version": 1,
        "original": encode(original),
        "operations": [
            encode(
                dict(
                    kind=op.kind,
                    params=op.params,
                    name=op.name,
                    intensity=op.intensity,
                    selection=op.selection,
                )
            )
            for op in operations
        ],
    }
    manifest = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if sum(array.nbytes for array in assets) + len(manifest) > MAX_BYTES:
        raise ValueError("O projeto excede o limite de 1 GB sem compressão.")
    descriptor, temporary = tempfile.mkstemp(
        prefix=".ocvproj-", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    try:
        with zipfile.ZipFile(
            temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=3
        ) as archive:
            archive.writestr("project.json", manifest)
            for index, array in enumerate(assets):
                with archive.open(
                    f"arrays/{index}.npy", "w", force_zip64=True
                ) as stream:
                    np.save(stream, array, allow_pickle=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def read_project(path):
    allowed = {
        "adjustments",
        "preset",
        "filter",
        "curves",
        "levels",
        "crop",
        "resize",
        "rotate",
        "flip",
        "text",
        "arithmetic",
        "region",
        "quantize",
        "color_model",
        "mask",
        "raster",
        "layer",
        "base_layer",
    }
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 10000
                or len({e.filename for e in entries}) != len(entries)
                or sum(e.file_size for e in entries) > MAX_BYTES
            ):
                raise ValueError(
                    "Arquivo de projeto muito grande ou com entradas duplicadas."
                )
            if archive.getinfo("project.json").file_size > 10_000_000:
                raise ValueError("Receita de projeto muito grande.")
            payload = json.loads(archive.read("project.json"))
            if (
                not isinstance(payload, dict)
                or payload.get("format") != "opencv-studio"
                or payload.get("version") != 1
            ):
                raise ValueError("Formato ou versão de projeto incompatível.")
            arrays = {}

            def decode(value, depth=0):
                if depth > 50:
                    raise ValueError("Estrutura de projeto inválida.")
                if isinstance(value, list):
                    return [decode(v, depth + 1) for v in value]
                if isinstance(value, dict):
                    if set(value) == {"__array__"}:
                        name = value["__array__"]
                        if (
                            not isinstance(name, str)
                            or not name.startswith("arrays/")
                            or not name.endswith(".npy")
                            or ".." in name
                            or "\\" in name
                        ):
                            raise ValueError("Referência de matriz inválida.")
                        if name not in arrays:
                            stream = io.BytesIO(archive.read(name))
                            version = np.lib.format.read_magic(stream)
                            if version not in ((1, 0), (2, 0)):
                                raise ValueError("Versão de matriz incompatível.")
                            reader = (
                                np.lib.format.read_array_header_1_0
                                if version == (1, 0)
                                else np.lib.format.read_array_header_2_0
                            )
                            shape, _, dtype = reader(stream)
                            expected = math.prod(shape) * dtype.itemsize
                            if (
                                len(shape) > 4
                                or dtype.kind not in "biuf"
                                or expected > MAX_BYTES
                                or expected > len(stream.getbuffer()) - stream.tell()
                            ):
                                raise ValueError(
                                    "Dimensões ou tipo de matriz inválido."
                                )
                            stream.seek(0)
                            array = np.load(stream, allow_pickle=False)
                            if (
                                not isinstance(array, np.ndarray)
                                or array.dtype.hasobject
                                or array.nbytes > MAX_BYTES
                            ):
                                raise ValueError("Matriz de projeto inválida.")
                            array.flags.writeable = False
                            arrays[name] = array
                        return arrays[name]
                    if set(value) == {"__tuple__"}:
                        return tuple(decode(v, depth + 1) for v in value["__tuple__"])
                    return {key: decode(v, depth + 1) for key, v in value.items()}
                return value

            original = validate_image(decode(payload["original"]))
            recipes = payload["operations"]
            if not isinstance(recipes, list) or len(recipes) > 10000:
                raise ValueError("Pilha de projeto inválida.")
            operations, ids = [], set()
            for recipe in recipes:
                decoded = decode(recipe)
                if not isinstance(decoded, dict):
                    raise ValueError("Operação de projeto inválida.")
                op = Operation(**decoded)
                if (
                    op.kind not in allowed
                    or not isinstance(op.params, dict)
                    or not isinstance(op.name, str)
                ):
                    raise ValueError("Operação de projeto incompatível.")
                if (
                    not np.isfinite(op.intensity)
                    or not 0 <= op.intensity <= 1
                    or (op.selection is not None and not isinstance(op.selection, dict))
                ):
                    raise ValueError("Intensidade ou seleção inválida.")
                if op.kind in ("layer", "base_layer"):
                    layer_id = op.params.get("id")
                    if (
                        not isinstance(layer_id, str)
                        or not layer_id
                        or layer_id in ids
                        or (op.kind == "layer" and layer_id == "base")
                        or (op.kind == "base_layer" and layer_id != "base")
                    ):
                        raise ValueError(
                            "Identificador de camada inválido ou duplicado."
                        )
                    ids.add(layer_id)
                    op.params.setdefault("name", op.name or "Camada")
                    opacity = float(op.params.get("opacity", 1))
                    if (
                        not isinstance(op.params["name"], str)
                        or not np.isfinite(opacity)
                        or not 0 <= opacity <= 1
                        or op.params.get("blend", "normal") not in BLEND_MODES
                    ):
                        raise ValueError("Propriedades de camada inválidas.")
                    if op.kind == "layer":
                        validate_image(op.params["image"])
                        layer_rect(op.params)
                operations.append(op)
            return original, operations
    except (
        zipfile.BadZipFile,
        KeyError,
        TypeError,
        OSError,
        EOFError,
        RecursionError,
        OverflowError,
    ) as exc:
        raise ValueError(
            "Não foi possível abrir o projeto: arquivo inválido ou incompleto."
        ) from exc
