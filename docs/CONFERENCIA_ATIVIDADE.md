# Conferência do projeto final

Conferência realizada em 22/10/2026 na versão Qt, com entrada em `main.py`.

## Resultado

Todos os requisitos obrigatórios do enunciado possuem implementação modular
e acesso pela interface. Não foi encontrada uma técnica obrigatória ausente.
O desafio adicional também tem implementação: cadastro de identidades, treino
LBPH, identificação em foto/vídeo e chamada deduplicada com exportação CSV/JSON.
Para demonstrá-lo com os alunos reais, ainda é necessário cadastrar suas
fotografias e avaliar o resultado com imagens novas ou câmera.

| Grupo do enunciado | Recursos conferidos no código |
| --- | --- |
| Entrada, saída e visualização | Abrir, duplicar documento independente, comparação dividida, salvar/exportar. |
| Operações básicas | Inversão, brilho/contraste, adição/subtração saturadas, cinza, matrizes RGB/HSV, redimensionamento, ROI. |
| Filtros e realce | Média, mediana, gaussiano, Sobel e Canny. |
| Histograma e intensidade | Histogramas, equalização, separação/estatísticas de canais, limiar fixo, adaptativo, Otsu e quantização. |
| Segmentação e morfologia | Crescimento de regiões por semente; erosão, dilatação, abertura e fechamento. |
| Reconhecimento facial | Detecção Haar e identificação LBPH com cadastro e modelo locais persistidos. |
| Desafio adicional | Sessão de chamada, uma presença por ID, encerramento e exportação CSV/JSON. |
| Imagens e vídeo | Processamento de arquivo/câmera, efeitos, quadros e exportação de vídeo. |

Os caminhos de cada função estão em [REQUISITOS_QT.md](REQUISITOS_QT.md).
O [roteiro de apresentação](ROTEIRO_DEMONSTRACAO.md) foi atualizado para os
menus e botões da interface Qt atual.

## Correções desta conferência

- O histograma HSV do laboratório esticava os 180 valores de H até a marca
  255. A curva agora usa o mesmo eixo de intensidade dos demais canais e
  identifica a faixa H=0–179. Um teste verifica que os valores 90 de H, S e V
  ocupam a mesma posição horizontal.
- O README da pasta superior agora aponta para a versão completa em
  `opencv-studio`, evitando executar por engano o editor Tkinter anterior.
- Foram corrigidos comandos de teste e caminhos de interface no roteiro e na
  matriz de requisitos. As suítes Qt e legada rodam em processos separados.
- Foi preparado o ambiente virtual local e gerada a pasta `demo`, com cinco
  imagens e um vídeo sintéticos para apresentação.

## Validação executada

Ambiente: Windows, Python 3.12.14, OpenCV contrib 4.14.0, NumPy 2.5.4,
Pillow 12.3.0 e PySide6 6.12.0. A suíte Qt foi executada novamente após a
correção do histograma.

| Suíte | Resultado |
| --- | --- |
| `python -m unittest discover -s tests -p "test_qt*.py" -v` | 132 testes encontrados, 131 aprovados e um ignorado; nenhuma falha. |
| `python tests/run_legacy.py` | 107 testes aprovados; nenhuma falha. |
| Total | 238 aprovados e um ignorado, de 239 testes encontrados. |

O teste ignorado exige o banco público AT&T/ORL, ausente neste ambiente.
O treino/predição LBPH e sua persistência foram exercitados com dados de teste;
a chamada foi verificada com identificações controladas. Isso verifica o fluxo
do programa, sem medir a taxa de acerto com pessoas reais. A avaliação pública
anterior registrada em [FACES_DEMONSTRACAO.md](FACES_DEMONSTRACAO.md) não foi
reexecutada nesta conferência.

A interface foi exercitada pelos testes Qt com backend offscreen. Não foi
realizado nesta conferência um ensaio manual com câmera física ou com a turma.
As exportações de vídeo não preservam áudio; o editor trabalha em oito bits.
