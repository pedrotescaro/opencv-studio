"""Treina o reconhecimento do grupo usando somente fotos fornecidas por vocês."""

import argparse

from studio.services.faces import ErroFaces
from studio.services.sface_group import GROUP_DATA_FOLDER, GROUP_FOLDER, treinar_grupo


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fotos", default=str(GROUP_FOLDER), help="Pasta que contém integrantes.json e as três subpastas de fotos")
    parser.add_argument("--destino", default=str(GROUP_DATA_FOLDER), help="Destino local do cadastro e modelo gerados")
    parser.add_argument("--limiar", type=float, default=None, help="Distância SFace máxima (1 - similaridade); padrão 0.637")
    args = parser.parse_args(argv)
    try:
        resultado = treinar_grupo(args.fotos, args.destino, limiar=args.limiar)
    except ErroFaces as exc:
        print(f"Não foi possível treinar: {exc}")
        return 1
    print(f"Treino concluído: {resultado.total_pessoas} integrantes, {resultado.total_fotos} fotos distintas.")
    print(f"Modelo local: {resultado.banco.pasta}")
    print("Teste com fotos novas e com a câmera; este treino não mede precisão nem comprova presença física.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
