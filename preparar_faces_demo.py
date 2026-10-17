r"""Treina e avalia uma demonstração LOCAL de LBPH com a base oficial AT&T/ORL.

Execução manual: .\.venv\Scripts\python.exe preparar_faces_demo.py
As fotografias, o cadastro e o modelo ficam em .dados_faces_demo, ignorado no Git.
Nunca lê ou altera o cadastro pessoal .dados_faces. Não é executado no startup.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import urllib.request
import zipfile

import cv2
import numpy as np

from studio.services.faces import (
    BancoFaces,
    ErroFaces,
    MotorFaces,
    normalizar_face,
    salvar_imagem,
)


RAIZ = Path(__file__).resolve().parent
PASTA_DEMO = RAIZ / ".dados_faces_demo"
FONTE = "https://www.cl.cam.ac.uk/research/dtg/attarchive/facedatabase.html"
URL = "https://www.cl.cam.ac.uk/Research/DTG/attarchive/pub/data/att_faces.zip"
# Hash do arquivo obtido diretamente do arquivo oficial de Cambridge em 17/10/2026.
# É uma verificação fixada pelo projeto; o publicador não fornece SHA-256 na página.
SHA256 = "509d763bd2276aa054d260d7f1000e8be212738134f2f83d8ff13bc2adf1c8ec"
LIMITE_DOWNLOAD = 8_000_000


def verificar_arquivo(dados):
    if hashlib.sha256(dados).hexdigest() != SHA256:
        raise ErroFaces(
            "O ZIP AT&T/ORL não confere com o SHA-256 esperado. Não será utilizado."
        )
    return dados


def obter_arquivo(caminho, offline=False):
    caminho = Path(caminho)
    if caminho.exists():
        return verificar_arquivo(caminho.read_bytes())
    if offline:
        raise ErroFaces(
            "O ZIP oficial ainda não está no cache. Execute uma vez sem --offline."
        )
    print("Baixando 3,8 MB da base oficial AT&T/ORL de Cambridge...", flush=True)
    requisicao = urllib.request.Request(
        URL, headers={"User-Agent": "OpenCV-Studio/1.0 academic-demo"}
    )
    with urllib.request.urlopen(requisicao, timeout=30) as resposta:
        dados = resposta.read(LIMITE_DOWNLOAD + 1)
    if len(dados) > LIMITE_DOWNLOAD:
        raise ErroFaces(
            "O download ultrapassou o limite esperado. Nenhuma imagem foi carregada."
        )
    verificar_arquivo(dados)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(dados)
    return dados


def ler_base(dados):
    """Lê apenas os 400 PGM esperados em memória; não extrai caminhos do ZIP."""
    imagens = {}
    with zipfile.ZipFile(io.BytesIO(dados)) as arquivo:
        esperados = {f"s{s}/{i}.pgm" for s in range(1, 41) for i in range(1, 11)}
        nomes = arquivo.namelist()
        if len(nomes) != len(set(nomes)) or not esperados.issubset(nomes):
            raise ErroFaces("A estrutura do ZIP AT&T/ORL é incompatível.")
        for pessoa in range(1, 41):
            for foto in range(1, 11):
                nome = f"s{pessoa}/{foto}.pgm"
                if arquivo.getinfo(nome).file_size > 100_000:
                    raise ErroFaces("Um recorte do ZIP excedeu o tamanho esperado.")
                imagem = cv2.imdecode(
                    np.frombuffer(arquivo.read(nome), np.uint8), cv2.IMREAD_GRAYSCALE
                )
                if (
                    imagem is None
                    or imagem.shape != (112, 92)
                    or imagem.dtype != np.uint8
                ):
                    raise ErroFaces(
                        f"A imagem {nome} não tem o formato original esperado."
                    )
                imagens[pessoa, foto] = imagem
    return imagens


def particionar():
    """Índices fixos: calibração nunca vê o holdout nem suas pessoas desconhecidas."""
    return {
        "treino": [(s, i) for s in range(1, 31) for i in range(1, 7)],
        "calibracao_conhecidos": [(s, i) for s in range(1, 31) for i in (7, 8)],
        "calibracao_desconhecidos": [
            (s, i) for s in range(31, 36) for i in range(1, 11)
        ],
        "teste_conhecidos": [(s, i) for s in range(1, 31) for i in (9, 10)],
        "teste_desconhecidos": [(s, i) for s in range(36, 41) for i in range(1, 11)],
    }


def preparar_foto(imagem):
    """Enquadra o pequeno PGM para o Haar, sem gerar rostos ou alterar a identidade."""
    ampliada = cv2.resize(imagem, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(ampliada, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=30)


def selecionar_limiar(conhecidos, desconhecidos):
    """Maximiza média(acerto conhecido, rejeição desconhecido), só na calibração.

    Em empate escolhe o menor limiar (mais restritivo). A distância não é uma
    probabilidade. Cada item contém esperado, previsto e distancia, sem holdout.
    """
    if not conhecidos or not desconhecidos:
        raise ErroFaces("A calibração exige exemplos conhecidos e desconhecidos.")
    distancias = [item["distancia"] for item in conhecidos + desconhecidos]
    if not all(math.isfinite(d) and d >= 0 for d in distancias):
        raise ErroFaces("A calibração recebeu uma distância inválida.")
    candidatos = sorted({0.000001, *(d for d in distancias if d > 0)})

    def nota(limiar):
        acertos = sum(
            item["esperado"] == item["previsto"] and item["distancia"] <= limiar
            for item in conhecidos
        ) / len(conhecidos)
        rejeicoes = sum(item["distancia"] > limiar for item in desconhecidos) / len(
            desconhecidos
        )
        return (acertos + rejeicoes) / 2

    return max(candidatos, key=lambda limiar: (nota(limiar), -limiar))


def resumir(conhecidos, desconhecidos, limiar):
    corretos = sum(
        item["esperado"] == item["previsto"] and item["distancia"] <= limiar
        for item in conhecidos
    )
    rejeitados = sum(item["distancia"] > limiar for item in conhecidos)
    rejeicoes = sum(item["distancia"] > limiar for item in desconhecidos)
    return {
        "conhecidos": len(conhecidos),
        "conhecidos_corretos": corretos,
        "conhecidos_rejeitados": rejeitados,
        "conhecidos_identidade_errada": len(conhecidos) - corretos - rejeitados,
        "taxa_identificacao_correta": corretos / len(conhecidos),
        "desconhecidos": len(desconhecidos),
        "desconhecidos_rejeitados": rejeicoes,
        "desconhecidos_aceitos_incorretamente": len(desconhecidos) - rejeicoes,
        "taxa_rejeicao_desconhecidos": rejeicoes / len(desconhecidos),
    }


def selecionar_limiar_com_limite(conhecidos, desconhecidos, taxa_maxima=0.04):
    """Política alternativa, calculada só na calibração, sem mudar o padrão."""
    candidatos = sorted(
        {
            0.000001,
            *(
                item["distancia"]
                for item in conhecidos + desconhecidos
                if item["distancia"] > 0
            ),
        }
    )
    validos = [
        valor
        for valor in candidatos
        if sum(item["distancia"] <= valor for item in desconhecidos)
        / len(desconhecidos)
        <= taxa_maxima
    ]
    return max(
        validos,
        key=lambda valor: (
            sum(
                item["esperado"] == item["previsto"] and item["distancia"] <= valor
                for item in conhecidos
            ),
            -sum(item["distancia"] <= valor for item in desconhecidos),
            -valor,
        ),
    )


def preparar(offline=False):
    caminho_zip = PASTA_DEMO / "fonte" / "att_faces.zip"
    imagens = ler_base(obter_arquivo(caminho_zip, offline=offline))
    banco = BancoFaces(PASTA_DEMO)
    motor = MotorFaces(banco, limiar=1_000_000)
    partes = particionar()
    esperados = {f"DEMO-{s:02}" for s in range(1, 31)}
    if banco.alunos and set(banco.alunos) != esperados:
        raise ErroFaces(
            "A pasta de demonstração contém outro cadastro. Use o cadastro pessoal para suas fotos."
        )

    print("Localizando as faces com o detector Haar real (400 fotos)...", flush=True)
    fotos, recortes = {}, {}
    for chave, imagem in imagens.items():
        fotos[chave] = preparar_foto(imagem)
        caixas = motor.detectar(fotos[chave])
        if len(caixas) != 1:
            raise ErroFaces(
                f"Haar encontrou {len(caixas)} faces em s{chave[0]}/{chave[1]}.pgm. Não usará caixa inventada."
            )
        x, y, w, h = caixas[0]
        recortes[chave] = fotos[chave][y : y + h, x : x + w]

    for pessoa in range(1, 31):
        codigo = f"DEMO-{pessoa:02}"
        amostras = [recortes[pessoa, i] for i in range(1, 7)]
        if codigo not in banco.alunos:
            banco.cadastrar(codigo, f"Pessoa demonstração {pessoa:02}", amostras)
        else:
            if banco.alunos[codigo]["nome"] != f"Pessoa demonstração {pessoa:02}":
                raise ErroFaces(
                    f"O nome de {codigo} foi alterado. O script não substituirá um cadastro modificado."
                )
            existentes = {
                hashlib.sha256(banco.ler_amostra(nome).tobytes()).hexdigest()
                for nome in banco.alunos[codigo]["amostras"]
            }
            verificacao = {
                hashlib.sha256(normalizar_face(face).tobytes()).hexdigest()
                for face in amostras
            }
            if existentes != verificacao:
                raise ErroFaces(
                    f"As amostras locais de {codigo} não correspondem ao split de treino. Nada será substituído."
                )

    print(
        "Treinando LBPH: 30 pessoas, 180 fotografias; holdout separado...", flush=True
    )
    quantidade, pessoas = motor.treinar()

    def prever(chaves, recorte_haar=True):
        resultados = []
        for pessoa, foto in chaves:
            entrada = recortes[pessoa, foto] if recorte_haar else imagens[pessoa, foto]
            resultado = motor.prever_face(entrada)
            resultados.append(
                {
                    "origem": f"s{pessoa}/{foto}.pgm",
                    "pessoa": pessoa,
                    "foto": foto,
                    "esperado": f"DEMO-{pessoa:02}" if pessoa <= 30 else None,
                    "previsto": resultado.codigo,
                    "distancia": resultado.distancia,
                }
            )
        return resultados

    conhecidos_cal = prever(partes["calibracao_conhecidos"])
    desconhecidos_cal = prever(partes["calibracao_desconhecidos"])
    limiar = selecionar_limiar(conhecidos_cal, desconhecidos_cal)
    conhecidos = prever(partes["teste_conhecidos"])
    desconhecidos = prever(partes["teste_desconhecidos"])
    limiar_limite = selecionar_limiar_com_limite(conhecidos_cal, desconhecidos_cal)
    diagnostico = resumir(
        prever(partes["teste_conhecidos"], False),
        prever(partes["teste_desconhecidos"], False),
        limiar,
    )
    motor.definir_limiar(limiar)

    # Os testes incluem todas as fotos holdout; nenhuma foto de teste vira cadastro.
    (PASTA_DEMO / "teste").mkdir(exist_ok=True)
    for pessoa, foto in partes["teste_conhecidos"] + partes["teste_desconhecidos"]:
        prefixo = "pessoa" if pessoa <= 30 else "desconhecido"
        salvar_imagem(
            PASTA_DEMO / "teste" / f"{prefixo}_{pessoa:02}_{foto:02}.png",
            fotos[pessoa, foto],
        )

    # Fixture fixa conhecida e primeiro desconhecido do holdout (sem seleção por resultado).
    exemplos = {
        "conhecido": "teste/pessoa_02_09.png",
        "desconhecido": "teste/desconhecido_36_01.png",
    }
    relatorio = {
        "versao": 1,
        "tipo": "demonstracao_academica_AT&T_ORL",
        "fonte": FONTE,
        "download": URL,
        "sha256_zip": SHA256,
        "credito": "AT&T Laboratories Cambridge / antigo Olivetti Research Laboratory",
        "termos": "Página oficial disponibiliza a base e solicita crédito. Fotos e modelo permanecem locais; não redistribuídos pelo projeto.",
        "opencv": cv2.__version__,
        "fotos_dataset": len(imagens),
        "preprocessamento": "PGM original 92x112 -> ampliação cúbica 2x -> borda cinza30 de40px -> Haar real -> recorte -> normalização MotorFaces",
        "haar_fotos_com_uma_face": len(recortes),
        "pessoas_treinadas": pessoas,
        "fotos_treino": quantidade,
        "limiar_lbph": limiar,
        "criterio_limiar": "Maior média entre identificação correta conhecida e rejeição desconhecida na calibração; empate favorece menor limiar.",
        "particoes": {
            nome: [f"s{s}/{i}.pgm" for s, i in chaves]
            for nome, chaves in partes.items()
        },
        "calibracao": resumir(conhecidos_cal, desconhecidos_cal, limiar),
        "teste": resumir(conhecidos, desconhecidos, limiar),
        "politica_alternativa_falsa_aceitacao_calibracao_ate_4_porcento": {
            "limiar_lbph": limiar_limite,
            "criterio": "Maior identificação correta na calibração, sujeita a falsas aceitações desconhecidas <=4%; empate favorece menos falsas aceitações e menor limiar. Não altera o padrão.",
            "calibracao": resumir(conhecidos_cal, desconhecidos_cal, limiar_limite),
            "teste": resumir(conhecidos, desconhecidos, limiar_limite),
        },
        "diagnostico_recorte_original_sem_haar": diagnostico,
        "resultados_calibracao": conhecidos_cal + desconhecidos_cal,
        "resultados_teste": conhecidos + desconhecidos,
        "exemplos": exemplos,
        "limitacoes": [
            "Base pequena, antiga, controlada, com pessoas anonimizadas. Não contém alunos da disciplina.",
            "Avaliação usa pessoas conhecidas em fotos diferentes, além de 5 pessoas inéditas como desconhecidas.",
            "Fotos de webcam, condições reais e resistência a foto/vídeo de outra pessoa não foram validadas.",
            "LBPH pode aceitar pessoas não cadastradas. Revise toda presença antes de usar uma chamada real.",
            "O diagnóstico sem Haar usa um enquadramento diferente do treino e não mede a mesma tarefa.",
        ],
    }
    (PASTA_DEMO / "relatorio.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PASTA_DEMO / "FONTE_E_CREDITOS.txt").write_text(
        f"AT&T Laboratories Cambridge\n{FONTE}\n{URL}\nSHA-256 observado: {SHA256}\n"
        "Uso local para demonstração acadêmica. Não são alunos. Não redistribuir os arquivos pelo repositório.\n"
        "Samaria, F.; Harter, A. Parameterisation of a stochastic model for human face identification. WACV, 1994.\n",
        encoding="utf-8",
    )
    # Demonstração final atravessa Haar e o mesmo reconhecedor usado pela interface.
    relatorio["verificacao_exemplos"] = {}
    for nome, arquivo in exemplos.items():
        imagem = cv2.imdecode(
            np.frombuffer((PASTA_DEMO / arquivo).read_bytes(), np.uint8),
            cv2.IMREAD_COLOR,
        )
        resultados = motor.reconhecer(imagem)
        relatorio["verificacao_exemplos"][nome] = [
            {
                "codigo": item.codigo,
                "nome": item.nome,
                "distancia": item.distancia,
                "caixa": list(item.caixa) if item.caixa is not None else None,
            }
            for item in resultados
        ]
    (PASTA_DEMO / "relatorio.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "pasta": str(PASTA_DEMO),
                "limiar_lbph": limiar,
                "teste": relatorio["teste"],
                "exemplos": relatorio["verificacao_exemplos"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return relatorio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Usa somente o ZIP local, com SHA-256 verificado.",
    )
    args = parser.parse_args()
    try:
        preparar(offline=args.offline)
    except (ErroFaces, OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Não foi possível preparar a demonstração: {exc}\n")


if __name__ == "__main__":
    main()
