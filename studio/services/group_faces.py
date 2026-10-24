"""Treino local do grupo a partir das três pastas declaradas no repositório.

As fotos originais são a fonte de verdade. O cadastro gerado é substituído por
inteiro depois da validação e do treino, sem misturar a turma antiga ou a demo.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
import threading

from .faces import BancoFaces, ErroFaces, MotorFaces, ler_imagem, normalizar_face


ROOT = Path(__file__).resolve().parents[2]
GROUP_FOLDER = ROOT / "fotos_grupo"
GROUP_DATA_FOLDER = ROOT / ".dados_faces_grupo"
EXTENSOES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
ARQUIVO_FONTES = "fontes_grupo.json"
_GERADOS = (
    "amostras", "alunos.json", "modelo_lbph.yml", "modelo_lbph.json",
    "config_faces.json", ARQUIVO_FONTES,
)
_LOCK = threading.RLock()
_INVENTARIOS = {}


@dataclass
class InventarioGrupo:
    pasta: Path
    integrantes: list[dict]
    fotos: dict[str, list[Path]]
    assinatura: str
    arquivos: list[dict]

    @property
    def total_fotos(self):
        return sum(len(fotos) for fotos in self.fotos.values())


@dataclass
class ResultadoTreinoGrupo:
    banco: BancoFaces
    motor: MotorFaces
    inventario: InventarioGrupo

    @property
    def total_fotos(self):
        return sum(len(aluno["amostras"]) for aluno in self.banco.alunos.values())

    @property
    def total_pessoas(self):
        return len(self.banco.alunos)

    @property
    def assinatura(self):
        return self.inventario.assinatura


def carregar_integrantes(pasta=GROUP_FOLDER):
    """Lê a whitelist: exatamente três IDs, nomes e pastas diretas distintas."""
    pasta = Path(pasta).resolve()
    try:
        dados = json.loads((pasta / "integrantes.json").read_text(encoding="utf-8"))
        pessoas = dados["integrantes"]
        if dados.get("versao") != 1 or not isinstance(pessoas, list) or len(pessoas) != 3:
            raise ValueError("declare exatamente os três integrantes")
        resultado, ids, pastas = [], set(), set()
        for item in pessoas:
            if not isinstance(item, dict):
                raise ValueError("integrante inválido")
            values = [item.get(chave) for chave in ("id", "nome", "pasta")]
            if any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError("cada integrante precisa de id, nome e pasta")
            codigo, nome, subpasta = (v.strip() for v in values)
            if len(codigo) > 80 or len(nome) > 160 or any(ord(c) < 32 for c in codigo + nome):
                raise ValueError("ID ou nome inválido")
            if (subpasta in (".", "..") or "/" in subpasta or "\\" in subpasta
                    or ":" in subpasta or Path(subpasta).name != subpasta):
                raise ValueError("use apenas uma pasta direta para cada integrante")
            if codigo in ids or subpasta.casefold() in pastas:
                raise ValueError("IDs e pastas não podem se repetir")
            if (pasta / subpasta).resolve().parent != pasta:
                raise ValueError("a pasta do integrante deve ficar dentro de fotos_grupo")
            ids.add(codigo)
            pastas.add(subpasta.casefold())
            resultado.append({"id": codigo, "nome": nome, "pasta": subpasta})
        return resultado
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ErroFaces(f"Não foi possível ler integrantes.json: {exc}") from exc


def _estado_fontes(pasta, integrantes):
    """Stat é barato; nomes e ctime também detectam inclusão, remoção e troca."""
    fotos, estado = {}, []
    for pessoa in integrantes:
        folder = pasta / pessoa["pasta"]
        if folder.exists() and not folder.is_dir():
            raise ErroFaces(f"{pessoa['pasta']} precisa ser uma pasta de fotografias.")
        paths = sorted(
            (p for p in folder.iterdir() if p.suffix.lower() in EXTENSOES),
            key=lambda p: p.name.casefold(),
        ) if folder.exists() else []
        fotos[pessoa["id"]] = []
        for path in paths:
            if not path.is_file() or path.resolve().parent != folder.resolve():
                raise ErroFaces(f"Foto inválida ou fora da pasta do integrante: {path.name}.")
            stat = path.stat()
            estado.append((pessoa["id"], path.name, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
            fotos[pessoa["id"]].append(path)
    config = (pasta / "integrantes.json").stat()
    estado_config = (config.st_size, config.st_mtime_ns, config.st_ctime_ns)
    return fotos, (json.dumps(integrantes, sort_keys=True), estado_config, tuple(estado))


def inventariar_fotos(pasta=GROUP_FOLDER):
    """Retorna também pastas vazias; só o treinamento exige fotos suficientes.

    A assinatura usa conteúdo e caminhos relativos. O cache evita reler os bytes
    de todas as fotos a cada quadro quando nomes e metadados continuam iguais.
    """
    pasta = Path(pasta).resolve()
    with _LOCK:
        integrantes = carregar_integrantes(pasta)
        try:
            fotos, estado = _estado_fontes(pasta, integrantes)
            cached = _INVENTARIOS.get(pasta)
            if cached is not None and cached[0] == estado:
                arquivos, assinatura = cached[1:]
            else:
                arquivos = [
                    {"pessoa": pessoa["id"], "arquivo": path.relative_to(pasta).as_posix(),
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                    for pessoa in integrantes for path in fotos[pessoa["id"]]
                ]
                serializado = json.dumps(
                    {"integrantes": integrantes, "arquivos": arquivos},
                    ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")
                assinatura = hashlib.sha256(serializado).hexdigest()
                if len(_INVENTARIOS) >= 64:
                    _INVENTARIOS.clear()
                _INVENTARIOS[pasta] = (estado, arquivos, assinatura)
            return InventarioGrupo(pasta, integrantes, fotos, assinatura, list(arquivos))
        except OSError as exc:
            raise ErroFaces(f"Não foi possível ler as fotos do grupo: {exc}") from exc


def _ler_fontes(destino):
    try:
        dados = json.loads((Path(destino) / ARQUIVO_FONTES).read_text(encoding="utf-8"))
        if not isinstance(dados, dict) or dados.get("versao") != 1:
            raise ValueError("formato incompatível")
        return dados
    except (OSError, ValueError, TypeError) as exc:
        raise ErroFaces("O grupo ainda não foi treinado. Adicione fotos às três pastas e clique em Treinar grupo.") from exc


def verificar_fontes_grupo(pasta=GROUP_FOLDER, destino=GROUP_DATA_FOLDER):
    """True se o treino corresponde às fontes atuais; caso contrário, ErroFaces."""
    with _LOCK:
        fontes = _ler_fontes(destino)
        inventario = inventariar_fotos(pasta)
        if (fontes.get("assinatura") != inventario.assinatura
                or fontes.get("integrantes") != inventario.integrantes):
            raise ErroFaces("As fotos ou os integrantes do grupo mudaram. Clique em Treinar grupo novamente.")
        return True


def _validar_cadastro_grupo(banco, integrantes):
    esperados = {p["id"]: p["nome"] for p in integrantes}
    atual = {codigo: aluno["nome"] for codigo, aluno in banco.alunos.items()}
    if atual != esperados:
        raise ErroFaces("O cadastro gerado não corresponde aos três integrantes. Treine o grupo novamente.")


class MotorGrupo(MotorFaces):
    """Nunca reconhece usando fotos removidas ou um cadastro fora da whitelist."""

    def __init__(self, banco, pasta):
        self.pasta_fontes = Path(pasta).resolve()
        super().__init__(banco)

    def _verificar_grupo(self):
        verificar_fontes_grupo(self.pasta_fontes, self.banco.pasta)
        self.banco.atualizar_do_disco()
        _validar_cadastro_grupo(self.banco, carregar_integrantes(self.pasta_fontes))

    # All entry points that can reach group validation take the publication lock
    # before MotorFaces acquires its own locks. The base methods nest through
    # preparar_modelo/_exigir_treino; reversing this order can deadlock a camera
    # worker against a concurrent reload or training job.
    @property
    def pronto(self):
        with _LOCK:
            return super().pronto

    def prever_face(self, face, caixa=None):
        with _LOCK:
            return super().prever_face(face, caixa)

    def reconhecer(self, imagem):
        with _LOCK:
            return super().reconhecer(imagem)

    def treinar(self):
        with _LOCK, self.lock, self.banco.lock:
            self._verificar_grupo()
            return super().treinar()

    def preparar_modelo(self):
        with _LOCK, self.lock, self.banco.lock:
            try:
                self._verificar_grupo()
            except ErroFaces as exc:
                self.modelo, self.rotulos = None, {}
                self.status_modelo = str(exc)
                return False
            return super().preparar_modelo()

    garantir_modelo = preparar_modelo

    def _exigir_treino(self):
        with _LOCK:
            self._verificar_grupo()
            super()._exigir_treino()


def carregar_grupo_treinado(pasta=GROUP_FOLDER, destino=GROUP_DATA_FOLDER):
    """Carrega somente um treino cuja origem ainda coincide com as três pastas."""
    with _LOCK:
        verificar_fontes_grupo(pasta, destino)
        inventario = inventariar_fotos(pasta)
        banco = BancoFaces(destino)
        _validar_cadastro_grupo(banco, inventario.integrantes)
        motor = MotorGrupo(banco, pasta)
        if not motor.preparar_modelo():
            raise ErroFaces(motor.status_modelo)
        return ResultadoTreinoGrupo(banco, motor, inventario)


def _publicar_treino(stage, destino):
    """Troca apenas arquivos gerados, preservando chamadas e qualquer outro dado.

    Em falha, restaura todos os arquivos anteriores. O lock impede os leitores
    deste serviço de observar um cadastro parcialmente publicado.
    """
    destino.mkdir(parents=True, exist_ok=True)
    backup = stage.parent / "anterior"
    backup.mkdir()
    movidos, publicados = [], []
    try:
        for nome in _GERADOS:
            old = destino / nome
            if old.exists():
                old.replace(backup / nome)
                movidos.append(nome)
        for nome in _GERADOS:
            (stage / nome).replace(destino / nome)
            publicados.append(nome)
    except OSError:
        for nome in reversed(publicados):
            (destino / nome).replace(stage / nome)
        for nome in reversed(movidos):
            (backup / nome).replace(destino / nome)
        raise


def treinar_grupo(pasta=GROUP_FOLDER, destino=GROUP_DATA_FOLDER, *, limiar=None):
    """Valida todas as fotos, treina LBPH e publica o conjunto completo.

    Exige duas faces normalizadas distintas por integrante. Duplicatas não
    contam como novas amostras. O limiar padrão 60 não é uma taxa de confiança.
    """
    pasta, destino = Path(pasta).resolve(), Path(destino).resolve()
    protegidos = {(ROOT / ".dados_faces").resolve(), (ROOT / ".dados_faces_demo").resolve()}
    if (destino in protegidos or destino == pasta or destino in pasta.parents
            or pasta in destino.parents):
        raise ErroFaces("Use um destino separado para o modelo do grupo; a turma, a demo e as fotos originais são preservadas.")
    with _LOCK:
        inventario = inventariar_fotos(pasta)
        faltantes = [p["nome"] for p in inventario.integrantes if len(inventario.fotos[p["id"]]) < 2]
        if faltantes:
            raise ErroFaces("Adicione pelo menos duas fotos diferentes de cada integrante. Faltam fotos de: " + "; ".join(faltantes) + ".")
        if destino.exists() and any((destino / name).exists() for name in _GERADOS) and not (destino / ARQUIVO_FONTES).exists():
            raise ErroFaces("O destino já contém outro cadastro. Escolha uma pasta exclusiva para o grupo.")
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix=".treino-grupo-", dir=destino.parent) as temporary:
                stage = Path(temporary) / "novo"
                banco = BancoFaces(stage)
                if limiar is None:
                    limiar = MotorFaces(BancoFaces(destino)).limiar
                motor = MotorFaces(banco, limiar=limiar)
                for pessoa in inventario.integrantes:
                    faces = []
                    for path in inventario.fotos[pessoa["id"]]:
                        imagem = ler_imagem(path)
                        caixas = motor.detectar(imagem)
                        if len(caixas) != 1:
                            raise ErroFaces(f"{pessoa['nome']} / {path.name}: detectados {len(caixas)} rostos; use uma foto com exatamente um rosto frontal.")
                        x, y, w, h = caixas[0]
                        faces.append(imagem[y:y + h, x:x + w].copy())
                    if len({normalizar_face(face).tobytes() for face in faces}) < 2:
                        raise ErroFaces(f"{pessoa['nome']}: são necessárias pelo menos duas fotos diferentes; cópias da mesma face não contam.")
                    banco.cadastrar(pessoa["id"], pessoa["nome"], faces)
                motor.definir_limiar(limiar)
                motor.treinar()
                if not all((stage / name).exists() for name in _GERADOS if name != ARQUIVO_FONTES):
                    raise ErroFaces("O treino terminou, mas não foi possível guardar o modelo. O cadastro anterior foi preservado.")
                if inventariar_fotos(pasta).assinatura != inventario.assinatura:
                    raise ErroFaces("As fotos mudaram durante o treino. Aguarde a cópia terminar e tente novamente.")
                fontes = {"versao": 1, "assinatura": inventario.assinatura,
                          "integrantes": inventario.integrantes, "arquivos": inventario.arquivos,
                          "fotos_origem": inventario.total_fotos,
                          "amostras_treinadas": sum(len(a["amostras"]) for a in banco.alunos.values())}
                (stage / ARQUIVO_FONTES).write_text(json.dumps(fontes, ensure_ascii=False, indent=2), encoding="utf-8")
                # Valida o modelo serializado antes de substituir o cadastro ativo.
                carregar_grupo_treinado(pasta, stage)
                _publicar_treino(stage, destino)
            return carregar_grupo_treinado(pasta, destino)
        except OSError as exc:
            raise ErroFaces(f"Não foi possível guardar o treino do grupo: {exc}") from exc
