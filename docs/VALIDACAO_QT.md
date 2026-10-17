# Validação da versão desktop Qt

Executada no Windows em 17/10/2026, com Python 3.14.3, PySide6 6.12.0,
OpenCV contrib 4.14.0, NumPy 2.5.4 e Pillow 12.3.0.

## Evidência automatizada

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_qt*.py" -v
.\.venv\Scripts\python.exe tests/run_legacy.py
```

O CI executa Qt e o legado Tk em processos distintos. Isso mantém os mesmos
238 testes. Os workers antigos também podem disparar a coleta de ciclos de
variáveis Tk já fechadas; elas exigem a thread principal. O runner legado
desativa apenas a coleta automática de ciclos durante a suíte e chama
`gc.collect()` na thread principal entre os casos, sem suprimir exceções nem
retirar testes. A falha `Tcl_AsyncDelete` foi reproduzida nas duas versões do
CI antes desse ajuste. A aplicação Qt continua sendo testada também com
imports Tk proibidos.

Resultado inicial: **183 testes passaram**, sendo **76 da implementação Qt** e
107 de regressão dos algoritmos e interfaces anteriores. Os testes incluem
subcasos; o catálogo de 104 filtros é percorrido integralmente. A extensão de
camadas elevou o total para 205. A extensão de seleção e menu de contexto
elevou o total para 227. O painel compacto e os bloqueios elevam o total para
**238 testes: 131 Qt e 107 legados**.

| Suíte Qt | Quantidade | Comportamentos verificados |
| --- | ---: | --- |
| `test_qt_core.py` | 19 | Todos os filtros em BGR/cinza/BGRA; 11 ajustes; cinco presets; intensidade/seleção; alfa; curvas/níveis; Unicode; formatos; geometria; 140 estados de histórico; prévia limitada |
| `test_qt_canvas.py` | 13 | Eventos reais de roda/teclado/mouse; zoom ancorado e limites; pan; seleção e recorte; comparação; conta-gotas; drag/drop; área visível |
| `test_qt_advanced.py` | 22 | Cadastro e treino LBPH; chamadas; carregamento assíncrono; efeitos/exportação real de vídeo; cancelamento; cor/NPZ; GrabCut; crescimento; medições/CSV; morfologia/JSON; fechamento durante processamento |
| `test_qt_services.py` | 9 | Equivalência dos serviços extraídos; compatibilidade de modelos e chamadas; vídeo real; execução completa da janela com imports Tk/legados proibidos |
| `test_qt_window.py` | 13 | UI e receita integradas; seleção ao reeditar; desfazer/refazer; exportação integral; falhas de arquivo; níveis inválidos; widgets numéricos; workers responsivos e descarte de resultados antigos |
| `test_qt_selection.py` | 22 | Máscaras combinadas e suaves, gestos, alças, nudge, menu e atalhos, coordenadas da camada, cópia/corte, alfa, preenchimento/contorno, prévias, projeto, histórico e retornos obsoletos |
| `test_qt_layer_panel.py` | 11 | Olho e teclado, renomear, preenchimento, bloqueios de pixels/alfa/posição/total, rodapé fixo, propriedades, visibilidade dos docks, geometria mínima e compatibilidade de projetos |
| `test_qt_layers.py` | 22 | Composição alfa, modos de mesclagem, geometria, preview, projetos portáteis, arquivo inválido, importação por arraste, pilha, propriedades, duplicação, canvas e exportação |

Três regressões receberam reprodução específica: exportações com a primeira
renderização artificialmente atrasada conservam a ordem; presets voltam à
resolução total após a prévia; Escape descarta a prévia e limpa a seleção.

O Ruff passou na verificação de nomes/imports dos módulos novos e testes Qt.
`git diff --check`, compilação dos módulos e análise sintática do iniciador
PowerShell também passaram. Os 29 arquivos Python da aplicação e do preparo
facial foram analisados com a gramática Python 3.10. O runtime 3.10 não está
instalado neste computador; a execução local foi em 3.14. A matriz GitHub Actions
executa em Windows com Python 3.10/3.14; o PR mostra o resultado do commit publicado.

## Revisão visual no Windows

A aplicação foi renderizada com o backend Qt Windows e fonte Segoe UI.
Capturas foram feitas pelo próprio `QWidget.grab()` da aplicação de validação.
O backend offscreen foi reservado aos testes de comportamento.

Foram inspecionados editor, comparação dividida, filtros, curvas/histograma,
histórico e reconhecimento facial. As janelas de 1440×900 e 980×660 pixels
lógicos mantiveram o layout. Em 980×660, o canvas ficou com 632×483 e o editor
numérico interno com 72 pixels; controles extensos usam rolagem nos painéis.

Artefatos locais em `validacao/`, não versionados: `qt-editor-final.png`,
`qt-editor-980.png`, `qt-curvas-final.png`, `qt-rostos-final.png`,
`qt-layout-final.json` e `testes-completos-final.txt`.
A imagem de frutas é a [amostra oficial do OpenCV](https://github.com/opencv/opencv/blob/4.x/samples/data/fruits.jpg).

Na atualização dos ícones de edição, os 13 testes de janela/worker passaram
novamente. A inspeção Qt Windows confirmou os cinco ícones no menu Editar e
desfazer/refazer na barra superior, inclusive em 980×660. As ações foram
acionadas para conferir o histórico e são desabilitadas fora do editor.
Capturas locais: `qt-icones-menu.png` e `qt-icones-980.png`.

A cobertura foi estendida a todos os menus: 149 entradas com ícone, incluindo
submenus e os 104 filtros; a lista lateral também exibe os ícones dos filtros.
A comparação dividida possui ícone no menu e no controle superior, com estados
sincronizados. O ícone de aplicar edição foi conferido como branco nos dois
botões. Nova inspeção visual Windows em 1440×900/980×660 e os 13 testes da
janela passaram. Evidências locais: `qt-icones-completos.json`, `qt-menu-0.png`,
`qt-menu-2.png`, `qt-menu-4.png` e `qt-icones-completos-980.png`.

O painel Filtros recebeu divisória vertical ajustável entre lista e parâmetros,
sem o teto anterior de 260 pixels. Um arraste real com QTest alterou as alturas
de 199 para 244 e depois 194 pixels. Os controles de destacar/encaixar e fechar
agora têm ícones de 18 pixels e alvos de 28×28. Foram exercitados destacar,
encaixar, fechar, recuperar pelo menu e duplo clique no cabeçalho. A interface
continuou em 980×660; os 13 testes da janela passaram. Evidência local em
`qt-filtros-altura.json` e `qt-filtros-altura-depois.png`.

## Camadas e redimensionamento horizontal

A extensão de camadas acrescenta 22 testes, totalizando 205 com as regressões
anteriores. Os testes verificam composição com alfa por valores conhecidos,
clipping, redimensionamento sem bordas escuras, mesclagem, transformações antigas,
importação por arraste na lista e nas propriedades, ordem, duplicação independente,
visibilidade, opacidade, movimento no canvas como um único estado de histórico,
desfazer/refazer, exportação e reabertura de projeto portátil. Arquivos corrompidos
e dimensões NumPy forjadas são rejeitados antes de alocar suas matrizes.

A inspeção Qt Windows com três camadas confirmou largura de painel de 330 para
430 e depois 365 pixels por arraste da alça no cabeçalho. O projeto reabriu com
as três camadas e o layout permaneceu em 980×660, sem sobreposição dos docks.
Artefatos locais: `qt-camadas-final.png`, `qt-camadas-980.png`,
`qt-filtros-redimensionaveis.png` e `qt-camadas-final.json`.

## Seleção e menu de contexto

A suíte de seleção acrescenta 22 testes. Os valores de pixels confirmam que
copiar usa a fonte da camada ativa, que os ajustes globais não são duplicados,
que o corte gera transparência real no fundo e que seleção, preenchimento e
apagamento são mapeados após resize, crop e rotação. O projeto reabre máscaras
suaves, edições do fundo e as camadas; a prévia respeita seu limite de tamanho.
Também foram exercitados soma/subtração/interseção com modificadores, movimento,
alças, Enter/Esc, setas, Ctrl+J, estados e ícones do menu, máscara PNG,
refinamento assíncrono com aplicar/cancelar, transformação numérica da camada,
desfazer/refazer e descarte de uma ação quando o documento muda.

No backend Qt Windows, uma seleção retangular recebeu uma subtração elíptica,
o menu real foi aberto sobre a foto e a ação Camada via cópia foi acionada com
mouse. A nova camada manteve o buraco transparente. O arraste das alças e Esc
restauraram a seleção, sem modificar a original. Menu e layout foram conferidos
em 1440×900 e 980×660. Evidências locais: `qt-menu-selecao-1440.png`,
`qt-menu-selecao-980.png`, `qt-selecao-combinada.png`,
`qt-selecao-transformar.png`, `qt-selecao-980.png` e `qt-selecao.json`.

## Painel compacto conforme a referência

O painel de camadas agora permanece separado dos docks com abas. As linhas têm
40 pixels e exibem olho, miniatura, nome e cadeado. Foram exercitados visibilidade
por clique e Espaço, renomear, preenchimento, desfazer/refazer, bloqueios,
criar/duplicar/excluir e propriedades. Os testes puros verificam a multiplicação
de cobertura, preservação do alfa, recusa das edições bloqueadas e projetos v3
com leitura das versões anteriores.

A inspeção Qt Windows confirmou duas linhas visíveis em 980×660, lista com
rolagem própria, rodapé fixo e propriedades em uma janela independente. Os
bloqueios de posição e edição são aplicados pelo controlador, além de
aparecerem nos controles. Artefatos locais: `qt-painel-camadas-1440.png`,
`qt-camadas-compactas-1440.png`, `qt-camadas-compactas-980.png`,
`qt-camadas-propriedades-980.png` e `qt-camadas-compactas.json`.

## Treino facial realmente executado

Depois de extrair os serviços sem Tk, foi executado novamente:

```powershell
.\.venv\Scripts\python.exe preparar_faces_demo.py --offline
```

O ZIP local teve seu SHA-256 conferido. O Haar detectou uma face nas 400 fotos
da AT&T/ORL. O LBPH foi treinado com 180 fotos de 30 pessoas; a calibração e
o teste usaram outras fotos. O modelo e o limiar ficam persistidos e carregam
automaticamente no painel Qt.

No teste separado, identificou corretamente 52/60 conhecidos e rejeitou 39/50
desconhecidos. Houve oito rejeições de conhecidos e onze falsas aceitações de
desconhecidos. A foto de teste DEMO-02 foi reconhecida também no painel Qt,
com distância 46,81. Fonte, partições e resultados por foto constam em
[FACES_DEMONSTRACAO.md](FACES_DEMONSTRACAO.md).

## Limites da verificação

- Câmera física e reconhecimento dos alunos reais não foram ensaiados.
- As onze falsas aceitações impedem considerar a demonstração uma validação
  de chamada confiável. O cadastro da turma exige fotos próprias e avaliação.
- O editor trabalha em 8 bits. Entradas de 16 bits são convertidas; a exportação
  de vídeo não inclui áudio. Histórico e receita são mantidos durante a sessão.
- A prévia reduzida aproxima filtros espaciais. Salvar/exportar renderiza a
  resolução total. Resultados científicos do laboratório entram como etapas
  raster; devem ser recalculados quando mudam ajustes anteriores relevantes.

Os testes automatizados cobrem os fluxos indicados acima. A inspeção visual
não equivale a executar manualmente cada botão em todo hardware possível.
