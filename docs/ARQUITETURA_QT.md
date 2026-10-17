# Arquivos e contratos da aplicação

## Fluxo principal

`main.py` cria o QApplication, aplica o tema e abre `MainWindow`. A janela
constrói o canvas, os docks e os espaços de trabalho. A leitura é assíncrona;
`Document.open` mantém uma cópia imutável da original.

Cada ação gera uma `Operation(kind, params, name, intensity, selection)`.
`Document` mantém a lista confirmada; os controles acrescentam uma receita de
prévia sem alterar essa lista. Aplicar confirma um novo estado em `History`.
Desfazer, refazer e clicar no histórico substituem a receita atual.

`RenderController` mantém um job ativo e somente o último pedido pendente.
A geração identifica resultados obsoletos, que são descartados. O worker chama
`render_pipeline` sem acessar widgets. O retorno atualiza QImage, histograma e
dimensões na thread Qt. Exportação reaplica a receita na resolução total.
Uma fila serial dedicada conserva a ordem de exportação da janela, mesmo se
o primeiro salvamento exigir processamento mais demorado.

## Código completo por responsabilidade

| Arquivo | Classes/funções principais |
| --- | --- |
| `main.py` | `main`: argumentos, QApplication, paleta e inicialização |
| `studio/ui/window.py` | `MainWindow`: menus, docks, documento e coordenação |
| `studio/ui/theme.py` | `STYLE`, `icon`: métricas e ícones desenhados em Qt |
| `studio/ui/widgets.py` | `AdjustmentControl`, `HistogramWidget`, `CurveWidget` |
| `studio/selection.py` | Máscaras imutáveis, combinação, morfologia, difusão e preenchimento alfa |
| `studio/selection_canvas.py` | Gestos, contorno animado com cache e transformação de seleção com oito alças |
| `studio/selection_edits.py` | Seleção em coordenadas da fonte; cópia/corte, preenchimento, contorno e apagar |
| `studio/ui/selection_actions.py` | Menu de contexto, atalhos, máscara PNG e diálogos de prévia |
| `studio/canvas.py` | `ImageCanvas`: coordenadas imagem/viewport, pintura e ferramentas |
| `studio/filters.py` | `Operation`, `ADJUSTMENTS`, `FILTERS`, `PRESETS`, `apply_operation`, `render_pipeline`, `output_size` |
| `studio/legacy_filters.py` | Catálogo e algoritmos anteriores, migrados sem UI |
| `studio/document.py` | `Document`: original imutável, receita e histórico |
| `studio/history.py` | `History`, `HistoryEntry`: estados de operações ilimitados |
| `studio/io.py` | `read_image`, `write_image`: formatos, Unicode e alfa |
| `studio/layers.py` | Composição alfa correta, mesclagem, clipping e geometria de camadas |
| `studio/project.py` | Receitas JSON e imagens NumPy em projeto portátil, sem pickle |
| `studio/ui/layers.py` | `LayerPanel`, `LayerList`: propriedades e importação por arraste |
| `studio/ui/layer_actions.py` | `LayerActions`: comandos, prévia e histórico das camadas |
| `studio/ui/project_actions.py` | `ProjectActions`: I/O assíncrono de .ocvproj |
| `studio/workers.py` | `Job`, `RenderController`: execução e coalescência |
| `studio/faces.py` | `FacePanel`: cadastro, treino, modelo, análise e chamada |
| `studio/video.py` | `VideoPanel`: arquivo/câmera, reprodução, efeitos e exportação |
| `studio/science.py` | `ScienceDialog`: composição, cor, segmentação, medições e morfologia |
| `studio/advanced_jobs.py` | Jobs compartilhados e conversão NumPy → imagem Qt |
| `studio/services/faces.py` | Banco de amostras, normalização, modelo LBPH persistente e chamada |
| `studio/services/video.py` | Captura, efeitos e exportação com cancelamento |
| `studio/services/color.py` | Conversão real de canais, histograma, quantização e crescimento |
| `studio/services/geometry.py` | Máscaras, recortes, medições e escala física |
| `studio/services/segmentation.py` | Sementes, GrabCut, componentes e máscaras |

Os serviços não importam Tkinter nem as interfaces antigas. A migração mantém
o formato dos cadastros, modelos e chamadas existentes; os módulos antigos são
mantidos somente para regressão dos algoritmos.

## Canvas

O canvas guarda imagens QImage, escala e deslocamento. Converte o viewport para
um retângulo na imagem e desenha somente essa origem. Em zoom alto o Qt usa
nearest; na redução, transformação suavizada. O checker é uma textura pequena,
não um bitmap proporcional à resolução da imagem.

O zoom usa a coordenada sob o cursor para recompor o deslocamento. Pan aceita
botão do meio e Espaço+arraste. Seleções informam forma, retângulo e dimensões
de origem. Áreas combinadas, invertidas ou suavizadas usam uma máscara de 8 bits
imutável, com retângulo envolvente. O pipeline redimensiona essa cobertura também
na prévia reduzida. O cache dos contornos é invalidado quando a seleção muda;
o timer de 90 ms altera apenas a fase do tracejado e para com o canvas oculto.
Shift/Alt combinam áreas; mover/transformar conserva a forma e permite cancelar.

Ações de pixels usam a inversa da geometria posterior à camada para projetar a
seleção do canvas em sua fonte. `base_layer.image` permite editar o fundo sem
alterar `Document.original`; a prévia reduz esse operando. Cópia/corte gera uma
fonte BGRA imutável acima da camada ativa, antes dos ajustes globais, evitando
aplicá-los duas vezes. Jobs conferem original, geração, estado de histórico e
identidade da seleção antes de aceitar o retorno. A refinagem também rejeita
retornos anteriores ao último pedido ou posteriores ao cancelamento.

## Dados e concorrência

O histórico compartilha operandos raster imutáveis, em vez de multiplicar a
imagem por cada alteração de slider. Pode crescer até o limite de RAM, sem um
número máximo artificial de estados. Esse histórico é da sessão.

Operações `base_layer` e `layer` são reconstruídas antes dos ajustes gerais.
Cada camada conserva fonte, ID, nome, posição, tamanho, opacidade, visibilidade
e modo de mesclagem. A prévia usa as mesmas coordenadas, escaladas para sua
resolução. Ao arrastar, a inversa das transformações posteriores converte o
deslocamento do canvas para a camada; a liberação confirma um estado de histórico.

O projeto .ocvproj guarda a original e a receita atual com todos os operandos
de imagem. A leitura limita tamanho, estrutura e tipos antes de carregar as
matrizes; não extrai caminhos nem executa objetos. O salvamento usa temporário
e substituição atômica. A versão 3 preserva também preenchimento e bloqueios;
a leitura continua aceitando projetos das versões 1 e 2. A versão explícita
impede que editores antigos abram a nova receita ignorando esses dados.
Exportação produz uma composição raster independente.

Faces usam os diretórios pessoais/demo existentes, hashes de amostras e modelo
persistente. O reconhecedor protege os acessos ao modelo; o processamento do
vídeo não acessa widgets. Mudanças de fonte/efeito têm gerações próprias para
evitar publicar frames antigos. Exportações usam temporário e substituição
do destino somente quando completas.

O laboratório recebe uma cópia independente. Aceitar sua saída acrescenta uma
etapa raster à receita; fechar enquanto processa invalida callbacks. As medições
e máscaras são calculadas em pixels de origem, independentemente do zoom.

## Executar e verificar

```powershell
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_qt_*.py" -v
```

O código está nos arquivos reais do repositório, sem geradores necessários para
executar e sem tarefas pendentes ou botões fictícios. A matriz de aceitação e
as limitações são apresentadas em [REQUISITOS_QT.md](REQUISITOS_QT.md).


## Painel compacto de camadas

`LayerDelegate` desenha olho, miniatura com xadrez, nome elidido e cadeado em
linhas de 40 pixels, mantendo edição do nome e reordenação do QListWidget.
Ícones ficam em cache; o cache de miniaturas retém apenas as fontes atuais.
O grupo superior de docks inclui Histórico; Camadas ocupa um dock independente.
Os percentuais numéricos compactos e bloqueios ficam fixos no topo, com ações
fixas na base e rolagem somente na lista. Propriedades usa uma janela Qt Tool
não modal para não comprimir a lista em 980×660.

Preenchimento e opacidade multiplicam o alfa no compositor. Os bloqueios são
metadados de cada operação e integram snapshots/projetos. Controladores recusam
alterações de geometria/remoção/aparência conforme o bloqueio, e a edição de
pixels valida o contrato também no serviço puro. O bloqueio de transparência
restaura o alfa da fonte e preserva pixels totalmente transparentes. Bloqueios
não impedem copiar e não alteram os filtros globais da composição.
