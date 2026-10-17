# OpenCV Studio · Qt

Editor desktop em **PySide6**, Python 3.10+, OpenCV contrib e NumPy. Tema carvão,
canvas com transparência, edição não destrutiva, 104 filtros, ferramentas de
visão computacional, vídeo/câmera e reconhecimento facial com chamada local.

## Executar

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Ou execute `powershell -ExecutionPolicy Bypass -File .\iniciar.ps1`.
O comando antigo `python editor_opencv_otimizado.py` também abre a interface Qt.
Nenhum widget Tk, `cv2.imshow` ou trackbar OpenCV é criado pelo aplicativo novo.

```powershell
.\.venv\Scripts\python.exe main.py caminho\foto.png
.\.venv\Scripts\python.exe main.py --faces
```

Use apenas **opencv-contrib-python** neste ambiente; não misture os pacotes
OpenCV normais/headless, pois todos fornecem o mesmo módulo `cv2`.

## Estrutura e arquitetura

```text
main.py                       ponto de entrada Qt
studio/
  canvas.py                   zoom, pan, seleção, comparação e pixels visíveis
  selection_canvas.py         contorno animado, gestos e transformação com alças
  selection.py                máscaras, combinação, refinamento e preenchimento
  selection_edits.py          edição de pixels na camada ativa, cópia e corte
  filters.py                  ajustes, presets e pipeline de operações
  legacy_filters.py           catálogo anterior preservado sem widgets
  document.py                 original imutável e receita de edição
  history.py                  estados de operações, undo/redo sem limite fixo
  io.py                       leitura Unicode, alfa e exportação com qualidade
  layers.py                   composição alfa, mesclagem e coordenadas de camadas
  project.py                  projetos .ocvproj portáteis, com receita e imagens
  workers.py                  render assíncrono, debounce e coalescência de pedidos
  faces.py                    interface Qt de cadastro/modelo/chamada
  video.py                    interface Qt de câmera/arquivo/exportação
  science.py                  morfologia, segmentação, cor, composição e medições
  advanced_jobs.py            jobs e conversão de imagens das áreas avançadas
  services/                   algoritmos puros: faces, vídeo, cor e segmentação
  ui/
    window.py                 menus, docks e coordenação do documento
    widgets.py                sliders numéricos, histogramas e curvas
    theme.py                  paleta, métricas Qt e ícones vetoriais
    layers.py                 lista de camadas, importação por arraste e propriedades
    layer_actions.py          comandos de camadas e integração com histórico/canvas
    project_actions.py        abertura e gravação assíncrona de projetos
    selection_actions.py      menu de contexto, seleção e comandos de pixels
preparar_faces_demo.py         treino público com partições verificáveis
iniciar.ps1                   ambiente e inicialização no Windows
tests/test_qt_*.py             processamento, canvas e integração Qt
```

A UI altera uma lista de `Operation`; `Document` preserva a imagem original e
`History` guarda snapshots da receita. Cada render reconstrói a saída a partir
da original. Não há cópia integral da imagem por estado de ajuste. Operandos
raster introduzidos pelo laboratório são compartilhados como buffers imutáveis.
O limite do histórico é a memória disponível, sem corte artificial em 25 estados.

Os algoritmos de faces, vídeo, segmentação e medição foram extraídos para
serviços independentes. A aplicação Qt não importa Tkinter nem os módulos
de interface anteriores. Os arquivos `editor_*.py`
continuam disponíveis para regressão dos algoritmos e migração dos dados.

## Espaço de trabalho

- Menu **Arquivo, Editar, Imagem, Filtros, Visualizar**.
- Ferramentas vetoriais à esquerda; canvas no centro; docks à direita.
- **Ajustes**, **Filtros**, **Histograma** e **Camadas** têm abas; **Histórico**
  fica abaixo. Arraste, destaque, redimensione ou feche os docks. **Visualizar →
  Painéis** os recupera. O mesmo espaço atende janelas pequenas por rolagem local.
- No painel **Filtros**, arraste a barra horizontal entre a lista e os parâmetros
  para aumentar ou diminuir a altura da lista. Os parâmetros têm rolagem própria.
  Os botões do cabeçalho permitem destacar/encaixar e fechar cada painel.
- Para mudar a largura, arraste a pequena alça vertical à esquerda do título
  do painel para a esquerda ou direita. Os separadores entre docks também são visíveis.
- Use o seletor superior para alternar **Editor**, **Vídeo e câmera**, **Rostos e
  chamada**. O laboratório abre pelo ícone inferior da barra de ferramentas ou
  por **Imagem → Laboratório e medições**.

Cada ajuste possui slider, valor numérico editável e reset próprio. A prévia
parte da original, com resolução reduzida enquanto o slider é arrastado e
renderização total ao soltar ou concluir a edição numérica. Pedidos antigos são
coalescidos; trabalhos pesados ficam fora da thread da interface.

**Aplicar edição** confirma a prévia na pilha; **Descartar** volta à receita
confirmada. Exportar inclui a prévia e processa a resolução total. O painel
Histórico permite clicar em estados anteriores. Em **Pilha de edições**, é
possível remover uma operação ou reeditar ajustes/filtros/curvas/níveis sem
mudar a imagem original nem a ordem da receita.

## Canvas e atalhos

| Ação | Gesto / atalho |
| --- | --- |
| Zoom 5%–3200%, ancorado no cursor | Roda do mouse |
| Mover a imagem | Botão do meio ou Espaço + arrastar |
| Ajustar à área disponível | Ctrl+0 |
| Tamanho real | Ctrl+1 |
| Ampliar / reduzir | Ctrl++, Ctrl+= / Ctrl+- |
| Ver a original enquanto segura | tecla \ |
| Dividir antes/depois | Comparação dividida; arraste a divisória |
| Mover / recortar / retângulo / elipse | V / C / M / E |
| Conta-gotas / texto | I / T |
| Confirmar recorte | Enter ou Recortar |
| Limpar seleção | Ctrl+D |
| Selecionar tudo / inverter seleção | Ctrl+A / Ctrl+Shift+I |
| Adicionar / subtrair / intersectar áreas | Shift / Alt / Shift+Alt + arrastar |
| Mover seleção / mover 10 pixels | Arrastar dentro da seleção; setas / Shift+setas |
| Copiar / cortar seleção para nova camada | Ctrl+J / Ctrl+Shift+J |
| Criar camada transparente | Ctrl+Shift+N |
| Transformar camada sobreposta | Ctrl+T |
| Apagar pixels selecionados da camada ativa | Delete |
| Aplicar edição | Ctrl+Enter |
| Desfazer / refazer | Ctrl+Z / Ctrl+Shift+Z |
| Abrir / salvar / salvar como | Ctrl+O / Ctrl+S / Ctrl+Shift+S |
| Adicionar imagens como camadas | Ctrl+Alt+O |
| Abrir projeto com camadas | Ctrl+Shift+O |

Em alta ampliação os pixels são nítidos; na redução há suavização. O paint do
canvas envia apenas a região visível ao Qt, sem criar um bitmap gigante para
3200%. O padrão xadrez representa transparência. A posição e a cor sob o cursor,
resolução e zoom aparecem na barra de status.

Seleções retangulares/elípticas limitam os ajustes e filtros. O recorte tem
proporções Livre, 1:1, 4:3, 3:2, 16:9 e 9:16. Texto suporta acentos e cor escolhida.
Girar, espelhar, redimensionar e duplicar ficam em **Imagem/Arquivo**.

## Seleção e menu de contexto

Clique com o **botão direito sobre a foto** para abrir o menu de seleção e
camadas, com ícones e estados habilitados conforme o documento. As mesmas
opções ficam em **Editar → Seleção e camadas**. Sem seleção, ainda é possível
criar uma camada transparente, importar uma imagem e preencher a camada ativa.

Retângulos e elipses têm contorno preto/branco animado, sem tingir a imagem.
Combine áreas com Shift (adicionar), Alt (subtrair) e Shift+Alt (interseção).
Arraste dentro da seleção para movê-la. **Transformar seleção** mostra oito
alças: arraste-as para redimensionar, Enter confirma e Esc restaura a seleção
anterior. As setas movem um pixel; Shift+setas movem dez.

**Modificar** permite expandir, contrair, criar borda, suavizar e aplicar difusão.
**Refinar arestas** combina suavização, difusão e expansão/contração, com prévia
assíncrona e cancelamento. Salvar/carregar seleção usa máscara PNG em tons de
cinza; tons intermediários mantêm a cobertura parcial da borda.

**Camada via cópia**, **Camada por corte**, **Preencher**, **Traçar contorno**
e **Apagar pixels** trabalham na **camada ativa**. Uma camada opaca acima pode
encobrir a alteração no fundo. A seleção é convertida às coordenadas da fonte,
inclusive após redimensionar, recortar ou girar o documento. As ações de pixels
entram no histórico; corte preserva transparência, e as imagens fonte editadas
ficam no projeto .ocvproj. A original do documento permanece imutável. Novos
projetos usam o formato versão 2; os projetos anteriores (versão 1) continuam
abrindo nesta versão do editor.

**Transformação livre da camada** abre controles numéricos de posição X/Y e
largura/altura, com prévia e cancelar/aplicar. As alças no canvas transformam a
seleção; para deslocar a camada, use a ferramenta Mover. O fundo conserva o
seu tamanho; duplique-o para transformar como uma camada sobreposta. Camadas
anteriores a um resultado científico rasterizado não podem ser editadas por
essas ações, pois esse resultado substitui sua composição; o menu desabilita
as ações nesse caso.

## Camadas e projetos

Abra a aba **Camadas**, use **Adicionar imagens como camadas…** ou arraste
arquivos para o painel. O botão com imagens empilhadas na barra superior faz
a mesma importação. Sem documento aberto, a primeira imagem vira o fundo.
As demais são centralizadas e ajustadas para caber na área da imagem original.

A primeira linha é a camada da frente. Arraste as linhas ou use as setas para
mudar sua ordem. As caixas de seleção mostram/ocultam; duplo clique renomeia;
os botões duplicam e removem. O fundo permanece na base, com visibilidade e
opacidade ajustáveis. Há mesclagem **Normal, Multiplicar, Tela e Sobrepor**.

Selecione a camada, escolha **Mover (V)** e arraste sua imagem no canvas.
Espaço+arraste e botão do meio continuam movendo a visualização. Os campos
X/Y e largura/altura ficam abaixo da lista, com opção de manter a proporção;
role o painel para acessar as propriedades em janelas menores. Desfazer/refazer
incluem importação, ordem, posição, tamanho, opacidade e visibilidade.

Os ajustes e filtros gerais são reaplicados à composição completa. As imagens
das camadas permanecem separadas e imutáveis na receita. Duplicar o documento
preserva as camadas em uma janela independente.

Com camadas, **Salvar (Ctrl+S)** grava um projeto **.ocvproj**, com as imagens
e os ajustes dentro do arquivo. **Arquivo → Abrir projeto com camadas…**
recupera a edição sem depender dos arquivos de origem. O formato usa JSON e
matrizes NumPy sem pickle, com gravação por substituição atômica e limite de
1 GB sem compressão. O histórico de desfazer permanece restrito à sessão.

Use **Exportar** para gerar PNG/JPG/WEBP/TIFF com as camadas visíveis reunidas
em uma imagem. A exportação não substitui o salvamento do projeto. PNG/WEBP/TIFF
preservam transparência; o formato de projeto é próprio do Studio, sem suporte PSD.

## Ajustes e filtros

Brilho, contraste, exposição, saturação, vibração, temperatura, matiz, nitidez,
sombras, luzes e gama. Curvas permitem criar/mover pontos e remover pontos
intermediários com o botão direito. Níveis têm preto, branco e gama.

O catálogo preserva todos os 99 filtros anteriores e acrescenta Vinheta, Grão
de filme, Glitch/RGB shift, Duotone e HDR. Inclui cinza, sépia, negativo,
gaussiano, movimento, box blur, mediana, bilateral, unsharp, Canny, Sobel,
Laplaciano, emboss, cartoon, lápis, pixelização, CLAHE, threshold, Otsu,
adaptativo, posterização, separação de canais e oito operações morfológicas.
Todos têm intensidade de mistura; os parâmetros relevantes aparecem ao selecionar.

Os presets **Cinematic, Vintage, B&W Contrast, Cyberpunk e Warm Film** preenchem
combinações reais de ajustes. O histograma acompanha a saída, desconsiderando
pixels totalmente transparentes.

## Laboratório acadêmico

O laboratório conserva uma cópia independente da imagem aplicada e permite:
composição aritmética, conversão BGR/RGB/HSV/cinza com NPZ real, análise de canais,
quantização, crescimento por semente, GrabCut, contagem exata de máscaras,
medições geométricas/polígonos, escala física e CSV, além de kernel morfológico
personalizado com âncora, borda, modo e importação/exportação JSON.

Resultados do laboratório são inseridos como uma etapa raster independente na
receita; a original e o histórico continuam preservados. Ao mudar ajustes
anteriores a essa etapa, refaça o cálculo científico para atualizar sua máscara.
O detalhamento por requisito está em [REQUISITOS_QT.md](docs/REQUISITOS_QT.md).

## Rostos, modelo treinado e chamada

O módulo Qt reutiliza o cadastro pessoal `.dados_faces/` e a demonstração
`.dados_faces_demo/`. Sem cadastro, o Haar já detecta faces; identificar nomes
exige as amostras correspondentes. Fotos, modelos, limiar e chamadas são locais.
O modelo salvo valida os hashes das amostras e é carregado automaticamente.

Para preparar a demonstração pública:

```powershell
.\.venv\Scripts\python.exe preparar_faces_demo.py
.\.venv\Scripts\python.exe main.py --faces
```

A base AT&T/ORL permanece separada da turma. Treino, calibração e teste usam
fotos distintas. O experimento teve 52/60 conhecidos corretamente identificados
e 39/50 desconhecidos rejeitados, com 11 falsas aceitações. Veja a fonte,
protocolo e limites em [FACES_DEMONSTRACAO.md](docs/FACES_DEMONSTRACAO.md).

Cadastre ID/nome e fotos distintas, treine/atualize o modelo e inicie uma sessão
para registrar as identificações aceitas uma vez por ID. Exporte CSV/JSON.
A distância LBPH não é confiança percentual; a chamada precisa ser revisada.

## Vídeo

Arquivos e câmera possuem reprodução/pausa/parada, efeitos, antes/depois,
exportação de frame, envio ao editor e exportação de arquivo completo em
segundo plano. O reconhecimento usa o mesmo modelo do módulo Rostos. Câmera e
codecs são liberados ao trocar fonte ou fechar. A exportação AVI/MP4 não inclui
áudio; os codecs usados exigem dimensões pares. A câmera permite frames e
reconhecimento ao vivo; a exportação completa parte de um arquivo.

## Testar

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_qt_*.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Os testes Qt usam a plataforma offscreen. Para inspeção visual no Windows,
use o backend normal: o backend offscreen deste host não carrega todas as fontes
instaladas. A suíte antiga permanece como regressão dos algoritmos; ela exige
Tkinter apenas para seus testes legados, não para criar a UI nova.

PNG/WEBP/TIFF preservam alfa; JPEG usa composição em fundo branco. Entradas de
16 bits são convertidas para o espaço de trabalho de 8 bits. Prévia reduzida
aproxima filtros locais; exportação reaplica todos os parâmetros na resolução
total. Confira máscaras e medições antes de utilizar seus resultados.
