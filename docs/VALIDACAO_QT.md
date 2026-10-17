# Validação da versão desktop Qt

Executada no Windows em 17/10/2026, com Python 3.14.3, PySide6 6.12.0,
OpenCV contrib 4.14.0, NumPy 2.5.4 e Pillow 12.3.0.

## Evidência automatizada

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Resultado final: **183 testes passaram**, sendo **76 da implementação Qt** e
107 de regressão dos algoritmos e interfaces anteriores. Os testes incluem
subcasos; o catálogo de 104 filtros é percorrido integralmente.

| Suíte Qt | Quantidade | Comportamentos verificados |
| --- | ---: | --- |
| `test_qt_core.py` | 19 | Todos os filtros em BGR/cinza/BGRA; 11 ajustes; cinco presets; intensidade/seleção; alfa; curvas/níveis; Unicode; formatos; geometria; 140 estados de histórico; prévia limitada |
| `test_qt_canvas.py` | 13 | Eventos reais de roda/teclado/mouse; zoom ancorado e limites; pan; seleção e recorte; comparação; conta-gotas; drag/drop; área visível |
| `test_qt_advanced.py` | 22 | Cadastro e treino LBPH; chamadas; carregamento assíncrono; efeitos/exportação real de vídeo; cancelamento; cor/NPZ; GrabCut; crescimento; medições/CSV; morfologia/JSON; fechamento durante processamento |
| `test_qt_services.py` | 9 | Equivalência dos serviços extraídos; compatibilidade de modelos e chamadas; vídeo real; execução completa da janela com imports Tk/legados proibidos |
| `test_qt_window.py` | 13 | UI e receita integradas; seleção ao reeditar; desfazer/refazer; exportação integral; falhas de arquivo; níveis inválidos; widgets numéricos; workers responsivos e descarte de resultados antigos |

Três regressões receberam reprodução específica: exportações com a primeira
renderização artificialmente atrasada conservam a ordem; presets voltam à
resolução total após a prévia; Escape descarta a prévia e limpa a seleção.

O Ruff passou na verificação de nomes/imports dos módulos novos e testes Qt.
`git diff --check`, compilação dos módulos e análise sintática do iniciador
PowerShell também passaram. Os 24 arquivos Python da aplicação e do preparo
facial foram analisados com a gramática Python 3.10. O runtime 3.10 não está
instalado neste computador; a execução local foi em 3.14. A matriz GitHub Actions
foi configurada para 3.10/3.14, mas não foi executada remotamente nesta entrega.

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
