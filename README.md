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
  filters.py                  ajustes, presets e pipeline de operações
  legacy_filters.py           catálogo anterior preservado sem widgets
  document.py                 original imutável e receita de edição
  history.py                  estados de operações, undo/redo sem limite fixo
  io.py                       leitura Unicode, alfa e exportação com qualidade
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
- **Ajustes**, **Filtros** e **Histograma** (com curvas e níveis) têm abas; **Histórico**
  fica abaixo. Arraste, destaque, redimensione ou feche os docks. **Visualizar →
  Painéis** os recupera. O mesmo espaço atende janelas pequenas por rolagem local.
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
| Aplicar edição | Ctrl+Enter |
| Desfazer / refazer | Ctrl+Z / Ctrl+Shift+Z |
| Abrir / salvar / salvar como | Ctrl+O / Ctrl+S / Ctrl+Shift+S |

Em alta ampliação os pixels são nítidos; na redução há suavização. O paint do
canvas envia apenas a região visível ao Qt, sem criar um bitmap gigante para
3200%. O padrão xadrez representa transparência. A posição e a cor sob o cursor,
resolução e zoom aparecem na barra de status.

Seleções retangulares/elípticas limitam os ajustes e filtros. O recorte tem
proporções Livre, 1:1, 4:3, 3:2, 16:9 e 9:16. Texto suporta acentos e cor escolhida.
Girar, espelhar, redimensionar e duplicar ficam em **Imagem/Arquivo**.

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
