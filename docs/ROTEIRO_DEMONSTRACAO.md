# Roteiro de demonstração

Este roteiro usa imagens e vídeo sintéticos para demonstrar as operações sem depender de downloads, câmera ou dados pessoais. Reserve aproximadamente 15 minutos para as operações de imagem e 5 minutos para vídeo e reconhecimento facial. A demonstração facial exige um cadastro local separado com fotografias fornecidas pelos participantes.

## Preparar e iniciar no Windows

Na pasta do projeto, execute no PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe gerar_demo.py
.\.venv\Scripts\python.exe editor_opencv_otimizado.py
```

Se o ambiente virtual já existir e as dependências estiverem instaladas, comece pela geração dos arquivos. Feche a janela para encerrar o programa. Para interromper uma execução pelo terminal, use `Ctrl+C`.

Antes da apresentação, teste a abertura do programa, a pasta de saída e os arquivos da demonstração no mesmo computador que será usado. Para executar a suíte de testes:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Testes de Tkinter precisam de uma sessão gráfica. Um resultado automático aprovado não substitui conferir as imagens exportadas e a câmera quando ela fizer parte da apresentação.

O gerador cria os seguintes arquivos em `demo/`:

| Arquivo | Uso |
| --- | --- |
| `cena.png` | Cores, canais, bordas, ROI e crescimento de regiões. |
| `baixo_contraste.png` | Histograma, equalização e limiarização. |
| `ruido.png` | Comparação de média, mediana e gaussiano. |
| `morfologia.png` | Erosão, dilatação, abertura e fechamento. |
| `segunda.png` | Soma, subtração e mistura de imagens. |
| `video_demo.avi` | Reprodução, processamento e exportação de vídeo. |

## 1. Entrada, cópia e comparação

1. Clique em **Abrir imagem** e escolha `demo/cena.png`.
2. Mostre a resolução e os canais no painel de informações.
3. Abra **Laboratório**. A imagem aplicada é copiada para uma área de trabalho independente. Em **Operação**, escolha **Duplicar / restaurar cópia** e clique em **Executar na cópia**. Escolha **Quantizar níveis**, informe 4 e execute para produzir uma alteração visível.
4. Mostre a referência e o resultado lado a lado. Explique que são matrizes independentes: processar a cópia preserva a referência.
5. Clique em **Salvar resultado PNG**, escolha um nome novo e abra o arquivo salvo para conferir.

As operações do Laboratório se acumulam sobre o resultado à direita. Use **Duplicar / restaurar cópia → Executar na cópia** para voltar à base à esquerda. O Editor só recebe o resultado quando você clica em **Enviar ao editor**.

Frase de apoio: “Ler uma imagem produz uma matriz. A cópia cria outro conjunto de pixels, permitindo experimentar sem modificar a referência.”

## 2. Cor, brilho, contraste e quantização

No **Editor**, escolha a categoria e o filtro; use **Ver prévia** e **Aplicar filtro**. Entre operações que devem partir da mesma entrada, use **Restaurar original**.

1. **Cores → Inverter cores**: mostre o negativo.
2. **Luz e contraste → Brilho**: teste um deslocamento positivo e um negativo.
3. **Luz e contraste → Contraste**: aumente o fator e mostre a saturação nas regiões claras.
4. **Cores → Escala de cinza**: mostre a mudança para um canal.
5. Sobre a versão em cinza, aplique **Cores → Posterizar**, com 4 níveis. Compare os patamares com o gradiente contínuo original.
6. Restaure a imagem colorida e abra **Laboratório**. Escolha **Converter modelo de cor**, selecione **HSV** em **Destino** e clique em **Executar na cópia**. Selecione **HSV** no campo **Histograma** para inspecionar H/S/V e use **Exportar matriz NPZ** para guardar esses valores e modelo. Converta novamente escolhendo **RGB** em **Destino**. A visualização reconstrói as cores da representação escolhida; ela pode parecer igual mesmo quando os valores da matriz mudam.
7. Clique em **Enviar ao editor** para reconverter o resultado para BGR e incluí-lo no histórico.

Frase de apoio: “Em HSV, H representa matiz, S saturação e V valor. No formato de 8 bits usado pelo OpenCV, H vai de 0 a 179 e S/V de 0 a 255.”

## 3. Aritmética de duas imagens

1. Abra a cena colorida como imagem principal.
2. Selecione **Composição → Escolher segunda imagem** e abra `demo/segunda.png`.
3. Escolha **Soma saturada** e aplique. A soma fica limitada a 255 por canal.
4. Restaure o original, repita com **Subtração** e mostre que valores negativos ficam em zero.
5. Se houver tempo, mostre **Mistura (alpha)** para distinguir média ponderada de soma saturada.

A segunda imagem é redimensionada para a resolução da principal antes da operação. Isso deve ser mencionado se as resoluções forem diferentes.

## 4. Dimensões e ROI

1. Abra **Laboratório**, escolha **Redimensionar**, informe uma largura menor e clique em **Executar na cópia**. **Manter proporção pela largura** calcula a altura; desmarque para escolher largura e altura independentemente.
2. Confirme as dimensões do resultado e do PNG exportado. Clique em **Enviar ao editor** para continuar com essa cópia no Editor.
3. No Editor, altere **Zoom** para 200% e mostre que essa ação não altera a resolução.
4. Abra **Recorte**, escolha **Retângulo**, arraste a ROI e clique em **Aplicar recorte**.
5. Mostre a resolução e a contagem de pixels após o recorte. Use **Desfazer** para recuperar a imagem.

Frase de apoio: “Redimensionar muda a matriz; ampliar o zoom muda apenas como a matriz aparece na tela. Recortar seleciona uma parte dessa matriz.”

## 5. Filtragem e bordas

Ative **Lado a lado** no Editor para manter original e prévia/resultado visíveis
durante as comparações abaixo.

1. Abra `demo/ruido.png`.
2. Aplique **Desfoque → Blur**, **Median Blur** e **Gaussian Blur**, restaurando o original entre comparações. Use uma janela de 5 pixels para começar.
3. Compare detalhes, bordas e ruído remanescente. A mediana é especialmente útil para o ruído de impulso presente na amostra.
4. Abra `demo/cena.png` e aplique **Bordas → Sobel X** e **Sobel Y**.
5. Restaure o original e aplique **Canny**, começando com limiares 100 e 200.

Frase de apoio: “Os filtros suavizam segundo regras diferentes. Sobel mede variações direcionais; Canny produz um mapa de bordas com dois limiares.”

## 6. Histogramas, equalização e binarização

1. Abra `demo/baixo_contraste.png`.
2. Em **Laboratório**, escolha **Cinza** em **Histograma** e observe a faixa estreita de intensidades. O gráfico está abaixo da comparação; mostra o resultado da cópia.
3. No Editor, aplique **Luz e contraste → Equalizar histograma**. Abra novamente o Laboratório para inspecionar a distribuição do resultado.
4. Aplique **Cores → Preto e branco**, começando com limiar 127.
5. Restaure o original e demonstre **Threshold Otsu**.
6. Restaure e demonstre **Threshold adaptativo**, com bloco 11 e C igual a 2. Compare a classificação em áreas com iluminação diferente.
7. Na cena colorida, use **Canais → Split BGR**. Restaure o original antes de aplicar **Canal H (HSV)** para mostrar canais com significados distintos.

Frase de apoio: “Exibir o histograma mede a distribuição. Equalizar transforma os valores a partir dessa distribuição. Binarizar reduz a saída a duas classes.”

## 7. Crescimento de regiões

1. Abra `demo/cena.png` e entre em **Laboratório**.
2. Em **Operação**, escolha **Crescimento de regiões**. Selecione uma semente dentro de um objeto homogêneo pelos campos **Semente X / Y** ou por clique na imagem do resultado. Comece com **Tolerância** 15 e **Vizinhança** 4; clique em **Executar na cópia**.
3. Observe a máscara e a quantidade de pixels selecionados. Escolha **Duplicar / restaurar cópia** e execute para recuperar a cena antes de cada comparação. Retorne a **Crescimento de regiões**, aumente a tolerância e execute para mostrar eventual vazamento ao fundo.
4. Compare as vizinhanças 4 e 8 usando regiões que se tocam somente pela diagonal, quando a amostra permitir. Restaure a cópia antes de cada execução; a saída anterior já é uma máscara, não a cena colorida.
5. Clique em **Salvar resultado PNG** para exportar a máscara e confira preto/branco e resolução.

Frase de apoio: “A semente inicia a busca. A tolerância é medida por canal contra a cor fixa da semente, e a vizinhança determina a conexão. Um objeto distante de mesma cor não entra apenas por ter a mesma intensidade.”

Opcional: demonstre o fluxo **Medições → selecionar ROI → Fechar contorno → Segmentar ROI… → Executar fluxo completo**. Mostre as sementes, a máscara e a sobreposição. Explique que esse fluxo usa GrabCut e é adicional ao crescimento de regiões.

## 8. Morfologia

1. Abra `demo/morfologia.png`.
2. Vá a **Morfologia**, escolha elemento retangular 3 × 3, uma iteração e modo **Binária**; clique em **Usar elemento**.
3. No Editor, escolha a categoria **Morfologia** e aplique **Erosão**. Compare a redução dos objetos claros.
4. Restaure o original e aplique **Dilatação**.
5. Restaure e aplique **Opening** (abertura), observando a remoção de pequenos pontos claros.
6. Restaure e aplique **Closing** (fechamento), observando pequenas falhas escuras.

Frase de apoio: “O resultado depende da forma e do tamanho do elemento estruturante. Abertura é erosão seguida de dilatação; fechamento usa a ordem inversa.”

## 9. Vídeo

1. Entre em **Vídeo**, clique em **Abrir vídeo** e escolha `demo/video_demo.avi`.
2. Clique em **Reproduzir** e escolha **Escala de cinza** ou **Canny** em **Efeito**. Use **Pausar** para inspecionar um quadro e **Salvar frame** para exportar PNG/JPEG.
3. Clique em **Exportar vídeo**, escolha um arquivo MP4 ou AVI e aguarde a conclusão. O arquivo inteiro é processado com o efeito escolhido.
4. Abra o arquivo exportado para verificar o efeito e a reprodução.
5. Opcional: informe **Índice da câmera**, clique em **Abrir câmera**, mostre alguns quadros e use **Parar** para liberar o dispositivo. O botão **Parar** também reinicia um arquivo no primeiro quadro.

O vídeo sintético deve ser o caminho principal da apresentação. O acesso à câmera depende de dispositivo, permissões e de ela não estar ocupada por outro programa. A exportação mantém resolução e FPS da origem, exige dimensões pares e não inclui áudio. MP4 usa `mp4v`; AVI usa `MJPG`. Câmera permite salvar quadros; a exportação de vídeo completo trabalha com um arquivo de origem.

## 10. Reconhecimento facial e chamada

Prepare a base pública com `.\.venv\Scripts\python.exe preparar_faces_demo.py`.
As fotografias e o modelo ficam separados do cadastro pessoal, com crédito
AT&T Laboratories Cambridge. O [relatório do treino](FACES_DEMONSTRACAO.md)
descreve a divisão entre treino, calibração e teste e os erros encontrados.

1. Abra **Faces**, selecione **Demonstração AT&T** na barra superior e aguarde o carregamento do modelo salvo.
2. Na aba lateral **Modelo**, clique em **Testar foto da demonstração**. A imagem `pessoa_02_09.png` ficou fora do treino e deve mostrar DEMO-02.
3. Use **Abrir foto** e escolha `.dados_faces_demo/teste/desconhecido_36_01.png`. O exemplo deve mostrar **Desconhecido**. Explique também as falsas aceitações observadas no conjunto completo de testes.
4. Na aba **Chamada**, clique em **Iniciar chamada**. Analise o exemplo conhecido duas vezes e confira uma única presença. Use **Encerrar chamada** e **Exportar CSV**.
5. Feche e reabra o programa: o modelo salvo é carregado, sem exigir novo treino. Não altere o limiar para aumentar artificialmente os acertos da foto que já está em teste.
6. Selecione **Minha turma**. Sem cadastro, abra uma foto para demonstrar a detecção imediata: a saída informa **Rosto detectado**, sem nome nem presença.
7. Para os alunos reais, na aba **Cadastro**, preencha ID/nome e use **Adicionar fotos da pessoa**. Duas fotos distintas por pessoa iniciam o preparo automático. A câmera aberta na aba Vídeo também pode fornecer amostras. Separe fotos novas para testar e confira as presenças antes de usar uma chamada real.

Frase de apoio: “O detector encontra regiões com aparência de face. O reconhecedor compara essas regiões com as pessoas cadastradas. A chamada registra as identificações aceitas nesta sessão.”

A demonstração usa pessoas anônimas da base pública, não os alunos. A distância
LBPH não é percentual de confiança. O teste completo teve falsas aceitações
de desconhecidos, registradas no relatório; a presença exportada exige revisão.
O sistema não verifica presença física/liveness.

## Evidências para entregar

Guarde os arquivos em uma pasta de saída escolhida para a apresentação:

- PNG do original e de uma cópia processada; captura da comparação simultânea.
- PNG redimensionado e recortado, com dimensões visíveis.
- Comparação dos três filtros e dos mapas Sobel/Canny.
- Histograma antes/depois, binarização e quantização.
- Máscara de crescimento de regiões e resultados de abertura/fechamento.
- Vídeo exportado e reaberto.
- CSV de chamada e captura de reconhecimento, quando houver cadastro real ensaiado.
- Saída da suíte de testes executada no ambiente final.

Na conclusão da apresentação, associe cada resultado ao método e indique parâmetros que alteraram a resposta. A [matriz de requisitos](REQUISITOS.md) permite conferir que todas as técnicas do enunciado foram percorridas.
