# Cobertura dos requisitos na versão Qt

Entrada: `python main.py`. Todas as interfaces desta versão usam PySide6.
Os três espaços de trabalho são Editor, Vídeo e câmera, Rostos e chamada.

| Requisito | Onde executar | Implementação |
| --- | --- | --- |
| Abrir e salvar imagens | Arquivo; arrastar arquivo no canvas | `studio/io.py`, Unicode, PNG/JPG/BMP/WEBP/TIFF, qualidade de exportação |
| Duplicação independente | Arquivo → Duplicar documento | Render total em worker e nova janela com matriz independente |
| Original e processada simultâneas | Comparação dividida | Divisória arrastável no canvas; tecla `\` exibe original enquanto pressionada |
| Inversão | Filtros → Cores → Inverter cores | Operação com intensidade e seleção opcional |
| Brilho e contraste | Ajustes | Sliders numéricos, reset e pilha não destrutiva |
| Adição e subtração | Imagem → Laboratório → Composição | Saturação OpenCV, alinhamento da segunda imagem explícito |
| Escala de cinza | Filtros → Cores → Escala de cinza | Preserva alfa; mistura e seleção opcionais |
| RGB e HSV | Laboratório → Canais e cor | Matriz e modelo explícitos, conversão reversível e NPZ |
| Redimensionamento | Imagem → Redimensionar | Resolução real e opção de proporção; independente do zoom |
| Recorte ROI | Ferramenta C e Enter/Recortar | Livre ou proporções fixas; desfazer preserva original |
| Média, mediana e gaussiano | Filtros → Desfoque | Blur, Median Blur, Gaussian Blur com janela configurável |
| Sobel e Canny | Filtros → Bordas | Direções de Sobel, limiares Canny e intensidade |
| Histograma | Dock Histograma; Laboratório → Canais e cor | Ao vivo; distribuição RGB, HSV ou cinza no laboratório |
| Equalização | Filtros → Luz e contraste → Equalizar histograma | Cinza ou luminância em cor; CLAHE também disponível |
| Splitting e análise | Filtros → Canais; Laboratório → Canais e cor | Canais B/G/R/H/S/V, min/máx/média/desvio e histogramas |
| Limiar fixo | Filtros → Cores → Preto e branco | Limiar editável; filtros inversos/truncados também preservados |
| Adaptativo e Otsu | Filtros → Cores | Threshold adaptativo e Threshold Otsu |
| Quantização | Posterizar; Laboratório → Canais e cor | Níveis ajustáveis e redução real dos valores |
| Crescimento de regiões | Laboratório → Segmentação | Semente pelo canvas ou X/Y, tolerância e vizinhança 4/8 |
| Erosão/dilatação/abertura/fechamento | Filtros → Morfologia; Laboratório → Morfologia | Oito operações, matriz personalizada, âncora, borda, modo e JSON |
| Reconhecimento facial | Seletor → Rostos e chamada | Haar pré-treinado para detecção, LBPH para identidades cadastradas |
| Chamada automatizada | Rostos e chamada → Chamada | Identificações aceitas deduplicadas por ID, JSON persistido e CSV |
| Vídeo | Seletor → Vídeo e câmera | Arquivo/câmera, efeitos, pausa/parada, frame e exportação total |

## Recursos anteriores preservados

O catálogo dos 99 filtros anteriores foi migrado integralmente para
`studio/legacy_filters.py`, sem widgets. O catálogo novo possui 104 filtros.
As cinco adições são vinheta, grão de filme, glitch/RGB shift, duotone e HDR.

Composição conserva mistura ponderada, diferença, multiplicação, Screen e
AND/OR/XOR, além de adição/subtração. O laboratório mantém a contagem de pixels
nas seleções geométricas, polígonos e desenho livre, retorno de pontos, escala
física e CSV. A escala estima a projeção visível e exige referência apropriada.

O GrabCut conserva ROI, filtro bilateral, sementes erodidas/dilatadas, quatro
classes de pincel, fechamento, limpeza por componentes, máscara, sobreposição
e inspeção das etapas. GrabCut não substitui crescimento de regiões.

As matrizes morfológicas permitem `−1/0/1`, tamanho, forma inicial, âncora,
iterações, bordas e modo; sua importação/exportação JSON é validada.

## Arquitetura e limites explícitos

Os ajustes fotográficos, filtros, geometria, texto, curvas e níveis são receitas
reaplicadas sobre a original. A seleção fica armazenada em cada operação. O
histórico armazena estados de receitas sem limite fixo. Exportar grava um raster
na resolução total; o arquivo de imagem não é um projeto com a receita embutida.
Para continuar editando as fontes separadas, salve o projeto .ocvproj. O painel
Camadas permite importar por arraste, sobrepor, ordenar, duplicar, remover,
renomear, mover, redimensionar, ocultar e mesclar imagens, com desfazer/refazer.

Os resultados científicos aceitos no laboratório são etapas raster imutáveis;
refaça esse processamento quando mudar uma etapa anterior que influencia sua
análise. O histórico e a imagem original continuam disponíveis.

O espaço de trabalho é de 8 bits; entradas de 16 bits são convertidas. Arquivos
com alfa permanecem transparentes em PNG/WEBP/TIFF; JPEG compõe no branco.
Prévias reduzidas aproximam kernels espaciais; a exportação usa os parâmetros
na resolução real. Vídeos exportados não incluem áudio.

O reconhecimento da base pública continua sendo uma demonstração acadêmica,
com erros medidos no [relatório de treinamento](FACES_DEMONSTRACAO.md). Não
representa cadastro dos alunos nem comprova chamada real confiável. Câmera
física e desempenho com a turma exigem ensaio próprio.

As referências do enunciado, preservadas em [REQUISITOS.md](REQUISITOS.md),
fundamentam o conteúdo acadêmico. A integração e validação Qt estão documentadas
em [VALIDACAO_QT.md](VALIDACAO_QT.md).
