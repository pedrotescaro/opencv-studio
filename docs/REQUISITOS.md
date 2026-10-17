# Matriz de requisitos — projeto final de Visão Computacional

O OpenCV Studio reúne as operações em funções Python e em abas de uma janela Tkinter. A seleção de uma aba, categoria e filtro constitui o menu de interação. O arquivo de entrada é `editor_opencv_otimizado.py`; os módulos de processamento podem ser chamados pelos testes sem iniciar a janela principal.

Esta matriz mostra onde demonstrar cada requisito do enunciado. Uma operação disponível no código não comprova sua qualidade em qualquer imagem, câmera ou população. A conferência visual dos resultados faz parte da demonstração.

## Entrada, saída e visualização

| Requisito | Caminho na interface | Comportamento a demonstrar |
| --- | --- | --- |
| Abrir e ler arquivos | **Abrir imagem** | Carrega uma imagem de arquivo e informa resolução, canais e tipo. Arquivos inválidos devem produzir uma mensagem. |
| Duplicar para processamento independente | **Laboratório → Duplicar / restaurar cópia → Executar na cópia** | Ao abrir, cria uma cópia de trabalho separada da imagem aplicada; a operação restaura essa cópia. Alterar o resultado não altera a base preservada. |
| Mostrar original e resultado simultaneamente | **Editor → Lado a lado**; também **Laboratório** | O Editor exibe o original junto da imagem aplicada ou prévia. O Laboratório exibe a base e a cópia processada. O botão **Segure para comparar** oferece uma comparação temporária adicional. |
| Gravar imagens | **Salvar**, **Salvar como…** e exportação no **Laboratório** | Salva o resultado aplicado. A prévia pendente no Editor precisa ser aplicada antes de salvar. PNG evita perdas adicionais de compressão na demonstração. |

## Operações básicas

| Requisito | Caminho na interface | Implementação / interpretação |
| --- | --- | --- |
| Inversão de cores | **Editor → Cores → Inverter cores** | Complementa os valores de 8 bits: `255 - valor`. |
| Brilho | **Editor → Luz e contraste → Brilho** | Adiciona ou subtrai um deslocamento com saturação no intervalo 0–255. |
| Contraste | **Editor → Luz e contraste → Contraste** | Multiplica a intensidade por um fator positivo; valores fora do intervalo são saturados. |
| Adição de imagens | **Composição → Soma saturada** | Opera pixel a pixel; `250 + 20` resulta em `255`. A segunda imagem é ajustada à resolução da principal. |
| Subtração de imagens | **Composição → Subtração** | Calcula principal menos segunda com saturação em zero; `10 - 20` resulta em `0`. **Diferença absoluta** é uma operação adicional. |
| Níveis de cinza | **Editor → Cores → Escala de cinza** | Converte a imagem colorida para uma matriz de intensidade. |
| RGB e HSV | **Laboratório → Converter modelo de cor → Destino → Executar na cópia** | Converte entre BGR, RGB e HSV com o modelo explícito. A visualização reconstrói as cores; **Exportar matriz NPZ** preserva os valores e o modelo. **Enviar ao editor** faz a conversão de volta para BGR. |
| Redimensionamento | **Laboratório → Redimensionar → Executar na cópia**; também **Editor → Transformar → Reduzir 50% / Aumentar 200%** | Altera largura e altura da matriz e do arquivo exportado. **Manter proporção pela largura** calcula a altura; desmarque para informar ambas as dimensões. O seletor **Zoom** altera somente a visualização. |
| Recorte de ROI | **Recorte → selecionar forma → Aplicar recorte** | Recorta a imagem aplicada na resolução original. Formas não retangulares deixam preto o exterior da forma dentro do arquivo retangular. |

## Filtragem, realce e intensidade

| Requisito | Caminho na interface | Comportamento a demonstrar |
| --- | --- | --- |
| Média | **Editor → Desfoque → Blur** | Média local em uma janela ajustável. |
| Mediana | **Editor → Desfoque → Median Blur** | Mediana local, útil para demonstrar redução de ruído de impulso. |
| Gaussiano | **Editor → Desfoque → Gaussian Blur** | Suavização com pesos gaussianos. |
| Sobel | **Editor → Bordas → Sobel X / Sobel Y / Sobel XY** | Derivadas nas direções horizontal e vertical e combinação das respostas. |
| Canny | **Editor → Bordas → Canny** | Detecção de bordas com dois limiares ajustáveis. |
| Criar e exibir histogramas | **Laboratório → Histograma → RGB / HSV / Cinza** | Distribuição das intensidades por canal do resultado. A soma das contagens de cada canal deve corresponder ao número de pixels; trocar o espaço do gráfico não muda a imagem. |
| Equalizar histograma | **Editor → Luz e contraste → Equalizar histograma** | Em cinza, equaliza a intensidade; em cor, equaliza a luminância Y em YCrCb e reconverte. Use o histograma para comparar a distribuição. |
| Separar e analisar canais | **Editor → Canais** e **Laboratório** | Exibe canais B, G, R e H, S, V. **Split BGR** monta uma composição visual dos canais. |
| Binarização fixa | **Editor → Cores → Preto e branco** | Classifica cada pixel segundo o limiar configurado. |
| Binarização adaptativa | **Editor → Cores → Threshold adaptativo** | Calcula limiares locais; bloco ímpar e constante C são ajustáveis. |
| Método de Otsu | **Editor → Cores → Threshold Otsu** | Estima um limiar global a partir da distribuição de intensidades. |
| Quantização | **Laboratório → Quantizar níveis → Executar na cópia**; também **Editor → Cores → Posterizar** | Reduz o número de níveis de cada canal. O Laboratório permite de 2 a 256 níveis; converte RGB/HSV para BGR antes de quantizar. Para demonstrar cinza, converta antes para **Cinza** ou aplique **Escala de cinza** no Editor. |

## Segmentação e morfologia

| Requisito | Caminho na interface | Comportamento a demonstrar |
| --- | --- | --- |
| Crescimento de regiões | **Laboratório → Crescimento de regiões → Executar na cópia** | Parte da semente X/Y, indicada por campos ou clique, e cresce por vizinhança 4 ou 8. Usa uma tolerância fixa por canal BGR ou cinza em relação ao pixel semente. A saída é uma máscara binária; regiões desconectadas ficam fora mesmo que tenham a mesma cor. |
| Erosão | **Editor → Morfologia → Erosão** | Reduz regiões claras segundo o elemento estruturante. |
| Dilatação | **Editor → Morfologia → Dilatação** | Expande regiões claras segundo o elemento estruturante. |
| Abertura | **Editor → Morfologia → Opening** | Erosão seguida de dilatação; pode remover pequenos objetos claros. |
| Fechamento | **Editor → Morfologia → Closing** | Dilatação seguida de erosão; pode preencher pequenas falhas escuras. |
| Elemento estruturante | **Morfologia → Usar elemento** | Define forma, dimensões, âncora, iterações, bordas e processamento colorido/cinza/binário. Volte ao Editor para aplicar a operação. |

A aba **Segmentação** oferece ainda um fluxo com ROI manual, filtro bilateral, sementes morfológicas, GrabCut, limpeza por componentes e exportação de máscara/sobreposição. Esse fluxo é um recurso adicional: GrabCut e crescimento de regiões são algoritmos distintos. A máscara final, e não o retângulo externo da seleção, determina a contagem de pixels.

## Vídeo e reconhecimento facial

| Requisito | Caminho na interface | Critério de demonstração |
| --- | --- | --- |
| Entrada e processamento de vídeo | **Vídeo → Abrir vídeo / Abrir câmera** | Reproduz arquivos ou captura quadros de câmera e aplica o efeito selecionado. A reprodução oferece **Reproduzir**, **Pausar** e **Parar**. |
| Gravação de vídeo processado | **Vídeo → Exportar vídeo** | Exporta o arquivo inteiro processado em MP4 (`mp4v`) ou AVI (`MJPG`), com resolução e FPS da origem e sem áudio. **Salvar frame** exporta um quadro; câmera permite salvar quadros, não exportar um vídeo completo. |
| Detecção facial | **Faces → Abrir foto → Detectar rostos** | O Haar pré-treinado localiza faces imediatamente, inclusive com o cadastro vazio; o resultado informa Rosto detectado e não cria presenças. |
| Reconhecimento facial | **Faces → Cadastro → Adicionar fotos da pessoa**; depois **Reconhecer rostos** | Duas ou mais fotos distintas por pessoa habilitam o treino automático em segundo plano. O modelo e o limiar são salvos e carregados nas próximas aberturas. **Modelo → Atualizar treinamento** permite atualizar manualmente. A identificação também funciona no módulo Vídeo. |
| Treino em base pública | **Faces → Demonstração AT&T → Modelo → Testar foto da demonstração** | O script `preparar_faces_demo.py` prepara o banco público e mantém treino, calibração e teste separados. As identidades de estudo ficam separadas do cadastro da turma. Veja o relatório do experimento. |
| Chamada automatizada — desafio adicional | **Faces → Chamada → Iniciar chamada / Encerrar chamada / Exportar CSV** | Acumula presenças aceitas na sessão e exporta CSV. Uma pessoa identificada repetidamente tem uma única presença por chamada. |

Detecção e reconhecimento não são equivalentes. O LBPH compara padrões de textura com amostras cadastradas. Sua distância não é uma probabilidade nem um percentual de confiança: valores menores indicam maior semelhança. O cadastro pessoal, as amostras, o modelo e as configurações ficam em `.dados_faces/`; chamadas ficam em `.dados_faces/chamadas/`. O cache valida parâmetros, IDs, nomes e o conteúdo das fotos antes de reutilizar o treino. O banco público usa `.dados_faces_demo/` e limiar calibrado próprio. O [relatório do treino](FACES_DEMONSTRACAO.md) registra tanto acertos quanto falsas aceitações de desconhecidos; a implementação acadêmica não comprova chamada confiável da turma nem verifica presença física/liveness.

## Organização modular

| Arquivo | Responsabilidade |
| --- | --- |
| `editor_opencv_otimizado.py` | Janela principal, catálogo, estado, filtros, histórico e composição. |
| `editor_layout.py` / `editor_interface.py` | Construção da interface, abas, painéis e estilos. |
| `editor_recorte.py` | Limites, máscaras geométricas e aplicação de ROI. |
| `editor_medicao.py` | Seleções, contagem de pixels, escala opcional e medições CSV. |
| `editor_recursos.py` | Elementos estruturantes, morfologia e filtros adicionais. |
| `editor_segmentacao.py` | Fluxo GrabCut, sementes e componentes conexos. |
| `editor_laboratorio.py` | `converter_cor`, `redimensionar`, `quantizar`, `histogramas`, `crescer_regiao` e cópia independente com comparação. |
| `editor_faces.py` | `BancoFaces`, `MotorFaces`, `Chamada` e interface de cadastro/reconhecimento. |
| `editor_video.py` | `FonteVideo`, `aplicar_efeito`, `exportar_arquivo_video` e interface de reprodução/câmera. |
| `gerar_demo.py` | Geração reproduzível de imagens e vídeo sintéticos para a apresentação. |

O [roteiro de demonstração](ROTEIRO_DEMONSTRACAO.md) percorre os requisitos e os arquivos de demonstração.

## Limitações e evidência esperada

- As imagens do editor são de 8 bits, em cinza ou BGR. Transparência e profundidade de 16 bits não são preservadas na leitura convencional.
- O histórico do Editor permite desfazer/refazer, mas não substitui salvar o trabalho. Mudanças da imagem aplicada invalidam seleções de ferramentas que dependiam da matriz anterior.
- As operações do Laboratório se acumulam sobre o resultado. Use **Duplicar / restaurar cópia** antes de comparar parâmetros a partir da mesma entrada. Depois do crescimento de regiões, restaure a cópia para não executar a próxima segmentação sobre a própria máscara.
- A conversão HSV de 8 bits usa H em 0–179 e S/V em 0–255. Uma conversão de ida e volta pode apresentar pequenas diferenças de arredondamento; não prometa igualdade exata para qualquer cor.
- Uma imagem visual dos canais HSV não é uma fotografia RGB. Preserve o espaço de cor na análise e reconverta para exibir a cor interpretada.
- A exportação de vídeo não preserva áudio. O processamento por quadro pode reduzir a fluidez da prévia; a exportação usa o FPS informado pelo arquivo. Os codecs exigem dimensões pares, verificadas antes de exportar. O vídeo original é protegido contra sobrescrita pela exportação.
- Recorte, segmentação e crescimento de regiões dependem da seleção, tolerância e imagem. Revise a máscara, inclusive buracos e vazamentos.
- Arquivos sintéticos permitem verificar comportamento conhecido. Eles não medem desempenho de reconhecimento facial, precisão clínica ou generalização em cenas reais.
- Testes automatizados de processamento, execução da interface e uso de uma câmera real são evidências diferentes. Registre quais foram executadas no ambiente da apresentação.

## Referências acadêmicas do enunciado

As obras abaixo foram fornecidas como material de estudo. A lista não implica reprodução integral dos exemplos, treinamento com dados dessas obras ou validação experimental segundo seus resultados.

- ANTONELLO, A. *Introdução à Visão Computacional com Python e OpenCV 3*. [PDF disponibilizado pelo autor](https://cv.antonello.com.br/wp-content/uploads/2017/02/Livro-Introdu%C3%A7%C3%A3o-a-Vis%C3%A3o-Computacional-com-Python-e-OpenCV-3.pdf).
- BARELLI, F. *Introdução à Visão Computacional: Uma abordagem prática com Python e OpenCV*. Casa do Código, 2018. ISBN 9788594188588. [Google Books](https://books.google.com.br/books?id=CA5ZDwAAQBAJ).
- MOLLOSI, Mariana et al. *Sistema de Detecção e Contagem de Alunos em Sala de Aula utilizando Inteligência Artificial e Processamento de Vídeo: Implementação e análise de técnicas de deep learning para reconhecimento e contagem de pessoas*. IGUAZU SCIENCE, v. 3, n. 7, p. 107–115, 2025. [Artigo disponibilizado pela revista](https://publicacoes.uniguacu.com.br/index.php/iguazu/article/view/173/133).
- GONZALEZ, Rafael C.; WOODS, Richard E. *Processamento de imagens digitais*. Editora Blucher, 2000.
