"""Unicode-safe raster I/O. The editing working space is eight-bit BGR/BGRA."""

from pathlib import Path
import cv2
import numpy as np
from .filters import validate_image

SUPPORTED_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".pgm",
)


def read_image(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError("O arquivo de imagem não foi encontrado.")
    try:
        encoded = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    except (OSError, cv2.error) as exc:
        raise ValueError("Não foi possível ler o arquivo de imagem.") from exc
    if image is None or not image.size:
        raise ValueError("Arquivo inválido ou formato de imagem não suportado.")
    # Fixed-range conversion preserves relative intensities for 16-bit TIFF/PNG.
    if image.dtype == np.uint16:
        image = np.rint(image.astype(np.float32) / 257).astype(np.uint8)
    elif np.issubdtype(image.dtype, np.floating):
        image = np.rint(np.clip(np.nan_to_num(image), 0, 1) * 255).astype(np.uint8)
    elif image.dtype != np.uint8:
        raise ValueError("Profundidade de cor não suportada.")
    return validate_image(image)


def write_image(path, image, quality=95, matte=(255, 255, 255)):
    validate_image(image)
    path = Path(path)
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("Escolha PNG, JPG, BMP, WEBP ou TIFF.")
    quality = int(np.clip(quality, 1, 100))
    source = image
    if (
        image.ndim == 3
        and image.shape[2] == 4
        and extension not in (".png", ".webp", ".tif", ".tiff")
    ):
        alpha = image[:, :, 3:4].astype(np.float32) / 255
        source = (
            np.rint(image[:, :, :3] * alpha + np.asarray(matte) * (1 - alpha))
            .clip(0, 255)
            .astype(np.uint8)
        )
    params = []
    if extension in (".jpg", ".jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    elif extension == ".webp":
        params = [cv2.IMWRITE_WEBP_QUALITY, quality]
    elif extension == ".png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 6]
    try:
        success, encoded = cv2.imencode(extension, source, params)
        if not success:
            raise ValueError("O codificador não conseguiu gravar a imagem.")
        encoded.tofile(str(path))
    except (cv2.error, OSError) as exc:
        raise ValueError(f"Não foi possível salvar a imagem: {exc}") from exc
    return path
