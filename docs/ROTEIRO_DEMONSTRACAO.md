# Roteiro de demonstração · versão Qt

Execute na pasta `opencv-studio`. A interface atual começa em `main.py`.
Reserve cerca de 20 minutos. As imagens e o vídeo sintéticos permitem
apresentar os algoritmos sem depender da câmera; reconhecer nomes exige
fotografias de cadastro e um modelo treinado.

## Preparar no Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe gerar_demo.py
.\.venv\Scripts\python.exe main.py
```

Com o ambiente pronto, bastam os dois últimos comandos. `iniciar.ps1` também
prepara o ambiente e abre o programa. Os dados sintéticos ficam em `demo/`:
`cena.png`, `baixo_contraste.png`, `ruido.png`, `morfologia.png`, `segunda.png`
e `video_demo.avi`.

As suítes Qt e legada devem rodar em processos separados:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_qt*.py" -v
.\.venv\Scripts\python.exe tests/run_legacy.py
```

## 1. Abrir, duplicar, comparar e salvar

1. Em **Arquivo → Abrir…**, abra `demo/cena.png`.
2. Use **Arquivo → Duplicar documento**. Altere a cópia e mostre que a janela
   de origem conserva a sua edição independente.
3. Ative **Visualizar → Comparação dividida** ou a caixa de mesmo nome na
   barra superior. Arraste a divisória para comparar original e resultado.
4. Escolha um filtro, confira a prévia e use **Aplicar edição** (`Ctrl+Enter`).
5. Em **Arquivo → Exportar…**, grave PNG e reabra para conferir o resultado.
   **Salvar** usa `.ocvproj` quando há camadas; o projeto conserva as fontes.

## 2. Operações básicas e modelos de cor

1. Use **Filtros → Cores → Inverter cores**.
2. No painel **Ajustes**, altere **Brilho** e **Contraste** e aplique a edição.
3. Use **Filtros → Cores → Escala de cinza**. Para comparar operações a partir
   da mesma entrada, use **Imagem → Restaurar original**.
4. Abra **Imagem → Laboratório e medições… → Canais e cor**. Escolha RGB e
   clique em **Converter matriz**; depois escolha HSV e converta novamente.
5. Escolha **HSV** em **Histograma**. Mostre os canais, as estatísticas e
   **Exportar NPZ**, que preserva a matriz e o modelo. **Importar NPZ** recupera
   esses dados. Converta de volta para RGB para demonstrar a ida e volta.
6. Na mesma aba, escolha um canal e clique em **Exibir canal separado**.
7. Para quantizar cinza, feche o laboratório, aplique cinza no editor e reabra
   o laboratório. Defina quatro níveis e use **Quantizar origem**.

A visualização converte as matrizes para a tela: RGB e HSV podem parecer iguais
apesar de seus valores serem diferentes. No HSV de 8 bits, H usa 0–179 e S/V
usam 0–255. A ida e volta pode apresentar arredondamento.

## 3. Soma e subtração

1. Com `cena.png` aberta, entre no laboratório, aba **Aritmética**.
2. Use **Abrir segunda imagem** e escolha `demo/segunda.png`.
3. Escolha **Adição**, clique em **Executar aritmética** e compare a saída.
4. Escolha **Subtração** e execute novamente. A soma satura em 255 e a
   subtração em zero. **Mistura ponderada** permite comparar com esses métodos.
5. Use **Salvar resultado PNG** ou **Aplicar resultado ao editor**.

Se as resoluções forem diferentes, a caixa **Redimensionar segunda imagem
para alinhar** controla explicitamente o alinhamento.

## 4. Redimensionar e recortar ROI

1. No editor, use **Imagem → Redimensionar…**. Reduza a largura, mantenha a
   proporção e confirme. Confira as dimensões na barra de status e na exportação.
2. Altere o zoom para 200%: isso muda a visualização, preservando a resolução.
3. Ative **Recortar (C)**, arraste uma ROI e pressione Enter, ou use
   **Imagem → Aplicar recorte selecionado**. Demonstre **Desfazer**.

## 5. Filtragem e bordas

1. Abra `demo/ruido.png` e ative **Comparação dividida**.
2. Use **Filtros → Desfoque → Blur**, **Median Blur** e **Gaussian Blur**,
   inicialmente com janela cinco. Restaure o original entre comparações.
3. Abra `demo/cena.png`. Em **Filtros → Bordas**, compare **Sobel X**, **Sobel Y**
   e **Canny**. Comece Canny com limiares 100 e 200.
4. Aplique e exporte um resultado para mostrar que o efeito altera os pixels.

## 6. Histograma, equalização e binarização

1. Abra `demo/baixo_contraste.png` e mostre o painel **Histograma**.
2. Use **Filtros → Luz e contraste → Equalizar histograma** e compare a
   distribuição antes/depois. O laboratório permite inspecionar RGB/HSV/cinza.
3. Restaure o original e aplique **Filtros → Cores → Preto e branco**, com
   limiar 127. Compare **Threshold Otsu** e **Threshold adaptativo**,
   restaurando a origem entre operações.
4. Em uma cena colorida, mostre também **Filtros → Canais → Split BGR**.

## 7. Crescimento de regiões

1. Abra `demo/cena.png`, depois **Imagem → Laboratório e medições… → Segmentação**.
2. Marque uma semente dentro do retângulo vermelho, por exemplo X=100, Y=100.
3. Defina tolerância 15 e conectividade 4. Clique em
   **Crescer região a partir da semente**. Mostre a máscara e a contagem de pixels.
4. Compare tolerâncias e conectividade 4/8. Cada execução usa a origem do
   laboratório; a máscara anterior não vira a entrada da próxima segmentação.
5. Use **Salvar resultado PNG** para guardar a máscara ou
   **Aplicar resultado ao editor** para continuar editando.

O algoritmo inclui pixels conectados dentro da tolerância em relação à
semente. GrabCut, disponível na mesma aba, é uma segmentação adicional distinta.

## 8. Morfologia

1. Abra `demo/morfologia.png` e **Imagem → Laboratório e medições… → Morfologia**.
2. Escolha elemento retangular 3 × 3, uma iteração e modo **Binária**.
3. Execute **Erosão**, **Dilatação**, **Abertura** e **Fechamento**
   com **Executar morfologia**, comparando cada resultado com a
   origem. Mostre como o kernel altera objetos claros e falhas escuras.
4. As mesmas operações ficam em **Filtros → Morfologia** no editor.

## 9. Vídeo e câmera

1. No seletor superior, escolha **Vídeo e câmera**, abra `demo/video_demo.avi`
   e use **Reproduzir**. Escolha **Escala de cinza** ou **Canny** em **Efeito**.
2. Use **Pausar**, **Salvar frame** e **Enviar ao editor**.
3. Use **Exportar vídeo** para gerar AVI/MP4; reabra a exportação para conferir.
4. Com uma câmera disponível, use **Abrir câmera** e **Parar** para liberá-la.

A exportação completa usa arquivo de vídeo, mantém FPS e resolução, exige
medidas pares e não inclui áudio. A câmera permite capturar quadros.

## 10. Reconhecimento facial e chamada

1. Escolha **Rostos e chamada → Minha turma**. Em **Cadastro**, informe ID e nome
   e use **Importar fotos e treinar** com pelo menos duas fotos distintas por aluno,
   cada uma mostrando exatamente um rosto frontal.
2. Em **Modelo**, confira o treino. Use **Abrir foto** com outra fotografia,
   que não tenha sido usada no cadastro, e observe nome e distância LBPH.
3. Na aba **Chamada**, informe a sessão e use **Iniciar chamada**. Analise
   repetidamente um aluno reconhecido: ele deve ter uma única presença.
4. Use **Encerrar**, **Exportar CSV** e **Exportar JSON**. Confira ID, nome e
   primeira identificação nos arquivos.
5. Para chamada em vídeo, abra a câmera ou um vídeo na área **Vídeo e câmera**
   e escolha o efeito **Reconhecimento facial**, mantendo a chamada iniciada.
6. Reabra o aplicativo e confira o carregamento do cadastro e modelo salvos.

Sem cadastro, o Haar detecta faces, mas não identifica nomes nem cria presenças.
A distância LBPH não é porcentagem de confiança. Confira a chamada produzida.

Para uma demonstração pública separada da turma, execute:

```powershell
.\.venv\Scripts\python.exe preparar_faces_demo.py
```

Depois escolha **Demonstração pública · AT&T/ORL → Modelo → Abrir exemplo
público de teste**. Consulte [FACES_DEMONSTRACAO.md](FACES_DEMONSTRACAO.md)
para as partições e os resultados do experimento anteriormente documentado.
Essa base não substitui o cadastro nem a validação com os alunos reais.

Use a [matriz de requisitos Qt](REQUISITOS_QT.md) para conferir a cobertura.
