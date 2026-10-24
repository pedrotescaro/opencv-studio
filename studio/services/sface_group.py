"""YuNet + SFace: descritores de fotos do grupo, sem ajuste da rede pré-treinada."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import threading
import urllib.request

import cv2
import numpy as np

from .faces import BancoFaces, ErroFaces, MotorFaces, ResultadoFace, ler_imagem, normalizar_face, validar_imagem
from .group_faces import (
    ROOT, GROUP_FOLDER, ResultadoTreinoGrupo, carregar_integrantes, inventariar_fotos,
    _LOCK, _validar_cadastro_grupo,
)

GROUP_DATA_FOLDER = ROOT / ".dados_faces_grupo_sface"
MODEL_FOLDER = ROOT / ".modelos_faces"
MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "face_detection_yunet", "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4", 232589
    ),
    "face_recognition_sface_2021dec.onnx": (
        "face_recognition_sface", "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79", 38696353
    ),
}
_FILES = ("amostras", "alunos.json", "descritores_sface.npz", "sface.json", "sface_config.json")
_MODEL_CACHE = {}
DEFAULT_DISTANCE = 0.637  # OpenCV SFace cosine similarity >= 0.363.
MIN_MARGIN = 0.05


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def preparar_modelos(pasta=MODEL_FOLDER, *, baixar=False):
    """Valida modelos oficiais; apenas treino explícito permite download."""
    pasta = Path(pasta)
    with _LOCK:
        for filename, (model, expected, size) in MODELS.items():
            path = pasta / filename
            valid = False
            if path.is_file():
                stat = path.stat()
                signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                valid = stat.st_size == size and (
                    _MODEL_CACHE.get(path.resolve()) == signature or _hash(path) == expected
                )
                if valid:
                    _MODEL_CACHE[path.resolve()] = signature
            if valid:
                continue
            if not baixar:
                raise ErroFaces("Modelos YuNet/SFace ausentes ou inválidos. Clique em Treinar com as fotos do grupo para prepará-los.")
            pasta.mkdir(parents=True, exist_ok=True)
            url = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/{model}/{filename}"
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    contents = response.read(size + 1)
                if len(contents) != size or hashlib.sha256(contents).hexdigest() != expected:
                    raise ErroFaces(f"O arquivo oficial {filename} não corresponde ao SHA-256 esperado.")
                with tempfile.NamedTemporaryFile(dir=pasta, suffix=".download", delete=False) as output:
                    temp_path = Path(output.name)
                    output.write(contents)
                try:
                    temp_path.replace(path)
                finally:
                    temp_path.unlink(missing_ok=True)
            except OSError as exc:
                raise ErroFaces(f"Não foi possível preparar {filename}: {exc}. Confira a conexão e tente treinar novamente.") from exc
        return pasta


class _SFaceEngine:
    def __init__(self, model_folder=MODEL_FOLDER):
        folder = preparar_modelos(model_folder)
        self.detector = cv2.FaceDetectorYN.create(
            str(folder / "face_detection_yunet_2023mar.onnx"), "", (320, 320), 0.8, 0.3, 5000
        )
        self.recognizer = cv2.FaceRecognizerSF.create(
            str(folder / "face_recognition_sface_2021dec.onnx"), ""
        )

    def detect(self, image):
        validar_imagem(image)
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        scale = min(1.0, 960 / max(image.shape[:2]))
        work = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else image
        self.detector.setInputSize((work.shape[1], work.shape[0]))
        _, faces = self.detector.detect(work)
        return work, ([] if faces is None else faces), scale

    def descriptor(self, image, face):
        aligned = self.recognizer.alignCrop(image, face)
        feature = np.asarray(self.recognizer.feature(aligned), np.float32).reshape(-1)
        norm = np.linalg.norm(feature)
        if feature.size != 128 or not np.isfinite(feature).all() or norm <= 0:
            raise ErroFaces("Não foi possível obter um descritor SFace válido desta foto.")
        return feature / norm, aligned


def _manifest(destino):
    try:
        data = json.loads((Path(destino) / "sface.json").read_text(encoding="utf-8"))
        if data.get("versao") != 1 or data.get("algoritmo") != "SFace":
            raise ValueError("modelo incompatível")
        return data
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        raise ErroFaces("O grupo ainda não foi preparado com SFace. Clique em Treinar com as fotos do grupo.") from exc


def verificar_fontes_grupo(pasta=GROUP_FOLDER, destino=GROUP_DATA_FOLDER):
    with _LOCK:
        manifest = _manifest(destino)
        inventory = inventariar_fotos(pasta)
        if manifest.get("assinatura") != inventory.assinatura or manifest.get("integrantes") != inventory.integrantes:
            raise ErroFaces("As fotos ou os integrantes mudaram. Treine o grupo novamente.")
        return True


class MotorSFace(MotorFaces):
    """Comparação por cosseno com rejeição por distância e ambiguidade."""

    def __init__(self, banco, pasta, features, labels, *, model_folder=MODEL_FOLDER):
        self.banco = banco
        self.pasta_fontes = Path(pasta)
        self.lock = threading.RLock()
        self.modelo = features
        self.labels = labels
        self.engine = _SFaceEngine(model_folder)
        self.arquivo_config = banco.pasta / "sface_config.json"
        self.limiar = DEFAULT_DISTANCE
        self.status_modelo = f"SFace pronto: 3 integrantes, {len(labels)} fotos. Rede pré-treinada; comparação por descritores."
        if self.arquivo_config.exists():
            try:
                value = json.loads(self.arquivo_config.read_text(encoding="utf-8"))["distancia_maxima"]
                self.definir_limiar(value, persistir=False)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ErroFaces("Limiar SFace inválido. Treine o grupo novamente.") from exc

    def _check(self):
        verificar_fontes_grupo(self.pasta_fontes, self.banco.pasta)
        self.banco.atualizar_do_disco()
        _validar_cadastro_grupo(self.banco, carregar_integrantes(self.pasta_fontes))
        if self.modelo is None:
            raise ErroFaces("Treine o grupo antes de identificar.")

    @property
    def pronto(self):
        with _LOCK, self.lock, self.banco.lock:
            try:
                self._check()
                return True
            except (ErroFaces, OSError):
                return False

    def preparar_modelo(self):
        return self.pronto

    garantir_modelo = preparar_modelo

    def definir_limiar(self, valor, *, persistir=True):
        try:
            value = float(valor)
        except (TypeError, ValueError):
            raise ErroFaces("Use uma distância SFace entre 0,01 e 1.") from None
        if not np.isfinite(value) or not 0.01 <= value <= 1:
            raise ErroFaces("Use uma distância SFace entre 0,01 e 1.")
        with _LOCK, self.lock:
            if persistir:
                _json(self.arquivo_config, {"versao": 1, "distancia_maxima": value})
            self.limiar = value

    def detectar(self, imagem):
        with self.lock:
            _, faces, scale = self.engine.detect(imagem)
            return [tuple(int(round(float(v) / scale)) for v in face[:4]) for face in faces]

    def reconhecer(self, imagem):
        with _LOCK, self.lock, self.banco.lock:
            self._check()
            work, faces, scale = self.engine.detect(imagem)
            output = []
            for face in faces:
                feature, _ = self.engine.descriptor(work, face)
                similarities = self.modelo @ feature
                ranking = sorted(
                    ((float(np.max(similarities[self.labels == code])), code) for code in self.banco.alunos),
                    reverse=True,
                )
                score, code = ranking[0]
                distance = float(np.clip(1.0 - score, 0.0, 2.0))
                accepted = distance <= self.limiar and score - ranking[1][0] >= MIN_MARGIN
                box = tuple(int(round(float(v) / scale)) for v in face[:4])
                output.append(ResultadoFace(code if accepted else None,
                    self.banco.alunos[code]["nome"] if accepted else "Desconhecido", distance, box))
            return output


def carregar_grupo_treinado(pasta=GROUP_FOLDER, destino=GROUP_DATA_FOLDER, *, model_folder=MODEL_FOLDER):
    with _LOCK:
        destino = Path(destino)
        verificar_fontes_grupo(pasta, destino)
        inventory = inventariar_fotos(pasta)
        bank = BancoFaces(destino)
        _validar_cadastro_grupo(bank, inventory.integrantes)
        manifest = _manifest(destino)
        path = destino / "descritores_sface.npz"
        try:
            if _hash(path) != manifest["descritores_sha256"]:
                raise ValueError("hash de descritores inválido")
            with np.load(path, allow_pickle=False) as arrays:
                features = arrays["features"].copy()
                labels = arrays["labels"].copy()
            expected = set(bank.alunos)
            if (features.ndim != 2 or features.shape[1] != 128 or labels.ndim != 1
                    or len(features) != len(labels) or labels.dtype.kind != "U"
                    or set(labels) != expected or any(np.sum(labels == code) < 2 for code in expected)
                    or not np.isfinite(features).all() or not np.allclose(np.linalg.norm(features, axis=1), 1, atol=1e-4)):
                raise ValueError("descritores inválidos")
        except (OSError, ValueError, KeyError) as exc:
            raise ErroFaces("Descritores SFace inválidos. Treine o grupo novamente.") from exc
        motor = MotorSFace(bank, pasta, features, labels, model_folder=model_folder)
        return ResultadoTreinoGrupo(bank, motor, inventory)


def _publish(stage, destino):
    destino.mkdir(parents=True, exist_ok=True)
    backup = stage.parent / "anterior"
    backup.mkdir()
    moved, published = [], []
    try:
        for name in _FILES:
            if (destino / name).exists():
                (destino / name).replace(backup / name)
                moved.append(name)
        for name in _FILES:
            (stage / name).replace(destino / name)
            published.append(name)
    except OSError:
        for name in reversed(published):
            (destino / name).replace(stage / name)
        for name in reversed(moved):
            (backup / name).replace(destino / name)
        raise


def treinar_grupo(pasta=GROUP_FOLDER, destino=GROUP_DATA_FOLDER, *, limiar=None, model_folder=MODEL_FOLDER):
    """Gera embeddings das fotos e mantém a rede SFace original intacta."""
    pasta, destino = Path(pasta).resolve(), Path(destino).resolve()
    protected = {(ROOT / name).resolve() for name in (".dados_faces", ".dados_faces_demo", ".dados_faces_grupo")}
    if destino in protected or destino == pasta or destino in pasta.parents or pasta in destino.parents:
        raise ErroFaces("Use uma pasta de modelo SFace separada das fotos e dos cadastros anteriores.")
    with _LOCK:
        inventory = inventariar_fotos(pasta)
        missing = [person["nome"] for person in inventory.integrantes if len(inventory.fotos[person["id"]]) < 2]
        if missing:
            raise ErroFaces("Adicione pelo menos duas fotos diferentes de: " + "; ".join(missing))
        if destino.exists() and any((destino / name).exists() for name in _FILES) and not (destino / "sface.json").exists():
            raise ErroFaces("O destino contém outro cadastro. Escolha uma pasta exclusiva para SFace.")
        preparar_modelos(model_folder, baixar=True)
        engine = _SFaceEngine(model_folder)
        distance = DEFAULT_DISTANCE if limiar is None else limiar
        if limiar is None and (destino / "sface_config.json").exists():
            try:
                distance = json.loads((destino / "sface_config.json").read_text())["distancia_maxima"]
            except (OSError, ValueError, KeyError):
                pass
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix=".sface-grupo-", dir=destino.parent) as temporary:
                stage = Path(temporary) / "novo"
                bank = BancoFaces(stage)
                vectors, labels = [], []
                for person in inventory.integrantes:
                    faces, unique = [], set()
                    for path in inventory.fotos[person["id"]]:
                        work, detected, _ = engine.detect(ler_imagem(path))
                        if len(detected) != 1:
                            raise ErroFaces(f"{person['nome']} / {path.name}: detectados {len(detected)} rostos; use uma foto individual.")
                        vector, aligned = engine.descriptor(work, detected[0])
                        digest = hashlib.sha256(normalizar_face(aligned).tobytes()).digest()
                        if digest in unique:
                            continue
                        unique.add(digest)
                        vectors.append(vector)
                        labels.append(person["id"])
                        faces.append(aligned)
                    if len(faces) < 2:
                        raise ErroFaces(f"{person['nome']}: use pelo menos duas fotos distintas, não cópias da mesma imagem.")
                    bank.cadastrar(person["id"], person["nome"], faces)
                np.savez_compressed(stage / "descritores_sface.npz", features=np.asarray(vectors, np.float32), labels=np.asarray(labels))
                _json(stage / "sface.json", {"versao": 1, "algoritmo": "SFace", "assinatura": inventory.assinatura,
                    "integrantes": inventory.integrantes, "arquivos": inventory.arquivos,
                    "descritores_sha256": _hash(stage / "descritores_sface.npz"), "margem_minima": MIN_MARGIN,
                    "modelos_sha256": {name: data[1] for name, data in MODELS.items()}})
                check = carregar_grupo_treinado(pasta, stage, model_folder=model_folder)
                check.motor.definir_limiar(distance)
                verificar_fontes_grupo(pasta, stage)
                _publish(stage, destino)
            return carregar_grupo_treinado(pasta, destino, model_folder=model_folder)
        except (OSError, cv2.error) as exc:
            raise ErroFaces(f"Não foi possível preparar SFace: {exc}") from exc
