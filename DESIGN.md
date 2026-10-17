# Espaço de trabalho de fotografia

Modo Operate, desktop Qt. A direção é explicitamente definida pelo usuário:
carvão, tipografia uniforme, controles compactos e uma única cor de ação azul.

- Canvas `#1e1e1e`, painéis `#252526`, elevação neutra `#2d2d30`.
- Texto `#e4e4e7`, secundário `#aaaab4`, ação e seleção `#3478cb`.
- Família Segoe UI, corpo 12 px Qt, títulos de painel 12–16 px.
- Espaçamento base 4 px; grupos 8/12/16 px; cantos de controles 4 px.
- Menus Arquivo, Editar, Imagem, Filtros, Visualizar. Ferramentas visuais à
  esquerda, documentos no centro e docks recolhíveis/flutuantes à direita.
- Ajustes, Filtros, Histograma/Curvas e Histórico dividem abas no grupo superior.
  Camadas fica em um dock próprio abaixo, sempre disponível. Linhas compactas
  mostram olho, miniatura, nome e cadeado; mesclagem/opacidade/preenchimento e
  bloqueios ficam no topo, ações no rodapé fixo. Posição e tamanho abrem em uma
  janela de propriedades. Os docks podem ser destacados, redimensionados,
  rearranjados ou ocultados por Visualizar.
- Estado ativo, foco e ações primárias usam azul. Histogramas podem usar as
  cores dos canais por seu significado analítico, não como decoração.
- Sem barras OpenCV nem `imshow`. Nenhuma janela Tk é criada na aplicação Qt.
- Zoom, coordenadas e dimensões ficam na barra de status. Checker indica alfa.
- Rostos e Vídeo são espaços de trabalho independentes selecionados no topo;
  laboratório consolida composição, modelos de cor, morfologia e medições.
