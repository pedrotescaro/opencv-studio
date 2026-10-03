# OpenCV Studio

Editor de imagens em Python, com interface Tkinter em português, 99 filtros,
prévia assíncrona, comparação com o original, zoom, composição e desfazer/refazer.

## Executar

```powershell
python -m pip install -r requirements.txt
python editor_opencv_otimizado.py
```

O Python precisa incluir Tkinter. Ao executar o editor, dependências ausentes
também podem ser instaladas automaticamente, como na versão anterior.

## Interface e navegação

O editor reúne **Editor**, **Recorte**, **Medições**, **Segmentação**,
**Morfologia** e **Composição** em abas na mesma janela. As abas mantêm as
seleções e os resultados ao alternar entre ferramentas. Ctrl+Tab avança e
Ctrl+Shift+Tab volta. Nenhuma ferramenta bloqueia a navegação com uma janela modal;
os seletores nativos de arquivos e mensagens continuam sendo diálogos.

Clique em **Abrir imagem** para começar. Na aba Editor, busque um filtro,
confira com **Ver prévia** e confirme com **Aplicar filtro**. A prévia automática
é opcional e começa desligada: abrir uma foto mostra a imagem original.
A interface exibe apenas os parâmetros usados pelo filtro escolhido e mostra
as opções de morfologia somente nessa categoria.

Nas abas, Enter executa a ação local (aplicar recorte, fechar contorno ou
executar segmentação) e não interfere quando você digita em um campo. Escape
limpa a seleção de recorte/medição ou descarta a prévia na aba Editor.
Ctrl+Z/Ctrl+Y controlam o histórico na aba Editor; Ctrl+Z volta um ponto na
aba Medições. Zoom e barras de rolagem ajudam a trabalhar com detalhes.
Nas abas **Editor**, **Recorte**, **Medições** e **Segmentação**, arraste a
divisória com a alça entre a imagem e os controles para ajustar o tamanho dos
painéis. **Expandir imagem** recolhe os controles; **Mostrar controles** restaura
o painel e sua divisão anterior. No zoom **Ajustar**, a imagem acompanha o
espaço disponível automaticamente. O redimensionamento mantém as seleções e
não altera a resolução original nem a contagem de pixels. Os controles de
recorte e medição têm rolagem para continuar acessíveis quando o painel é reduzido.
Em Medições, **Resultados — mostrar / ocultar** recolhe a tabela para dar
mais espaço à imagem; a tabela abre ao adicionar uma medição. A escala física
e os ajustes avançados da segmentação também podem ser recolhidos.

Alterar a imagem aplicada ou abrir outra foto reinicia as ferramentas que
dependem dela, evitando resultados baseados em uma imagem antiga. Exporte
medições e máscaras antes de trocar/editar a imagem. A matriz morfológica
permanece configurada. O editor usa cores claras, ações principais em azul
e painéis com rolagem; redimensione a janela para ganhar espaço de trabalho.

## Morfologia e elementos personalizados

O laboratório fica na aba **Morfologia**. Em janelas pequenas, use
as barras de rolagem ou a roda do mouse para acessar o conteúdo. Os botões de
importar, exportar, cancelar e usar o elemento permanecem no rodapé fixo.

- Desmarque **Usar matriz personalizada** para usar o elemento padrão 3 × 3,
  com âncora central, sem perder a matriz desenhada. Reative para recuperá-la.
- Desmarque **Ativar filtro morfológico** para desligar completamente o efeito.
  A prévia mantém a imagem e Aplicar não cria alterações nem histórico.
  Os filtros de outras categorias continuam funcionando normalmente.

1. Abra uma imagem e escolha a categoria **Morfologia**.
2. Abra a aba **Morfologia** ou clique em **Editar elemento estruturante →**.
3. Escolha retângulo, elipse, cruz, losango, linhas ou diagonais. Defina largura e
   altura de 1 a 31 e clique em **Gerar matriz**. A forma Personalizado começa vazia.
4. Clique nas células para alternar `0 → 1 → -1`, ou arraste para pintar.
   Clique com o botão direito para definir a âncora. A borda amarela marca a âncora.
5. Escolha iterações, bordas e modo de imagem. Clique em **Usar elemento**.
6. Escolha a operação, confira a prévia e clique em **Aplicar filtro**.

A seleção de uma forma pronta atualiza a matriz imediatamente. Se alterar as
dimensões de uma matriz personalizada, gere e desenhe a nova matriz antes de
confirmar. Iterações e limiar também podem ser ajustados no painel principal;
o limiar fica habilitado para o modo binário e para Hit-or-miss.

As oito operações nativas estão disponíveis: erosão, dilatação, abertura,
fechamento, gradiente, top-hat, black-hat e hit-or-miss. A matriz e as opções
podem ser exportadas/importadas em JSON. Arquivos importados são validados.

Em hit-or-miss, `1` exige objeto, `-1` exige fundo e `0` ignora a posição.
A imagem é binarizada usando o limiar configurado. Nas outras operações,
somente as células `1` participam. Deve existir pelo menos uma célula `1`.
Âncora `(-1, -1)` significa centro automático; outras coordenadas começam em zero.
No Hit-or-miss, as bordas constantes são consideradas também no complemento
da imagem, preservando os padrões que encostam nos limites.
Referência: [OpenCV Hit-or-Miss](https://docs.opencv.org/4.x/db/d06/tutorial_hitOrMiss.html).

## Recursos

### Medir áreas de objetos

1. Abra a foto e escolha a aba **Medições**.
2. Escolha **Polígono**, clique ao redor do contorno visível do objeto e clique
   em **Fechar contorno** (ou use o botão direito). **Voltar um ponto** permite
   corrigir o traçado. Em **Desenho livre**, arraste ao redor do objeto e solte
   para fechar o contorno. As formas geométricas também estão disponíveis.
3. Aumente o zoom para marcar detalhes. Use as barras de rolagem ou arraste com
   o botão do meio para mover a imagem. A contagem sempre usa a resolução original.
4. Dê um nome e clique em **Adicionar medição**. Repita para cada objeto.
   A tabela mostra pixels, área em px² e percentual da imagem para cada objeto.
5. Use **Exportar medições CSV** para guardar os resultados.

Um pixel selecionado corresponde a 1 px². São contados os centros dos pixels
dentro do contorno, incluindo centros na borda; contornos cruzados usam a regra
par/ímpar. A contagem é exata para a seleção desenhada, cuja precisão ao representar
o objeto depende do contorno escolhido. Canais de cor não multiplicam a área.
As medições não alteram a imagem e são mantidas ao fechar/reabrir essa janela
enquanto a imagem aplicada não mudar. Abra uma nova medição após editar a imagem;
exporte os resultados antes de mudar de imagem ou fechar o aplicativo.

Para estimar cm² ou m², abra **Configurar escala física (opcional)**,
clique em **Marcar referência (2 cliques)** e marque as
extremidades de um comprimento conhecido, informe a distância e a unidade e clique
em **Calibrar**. A fórmula é `área = pixels × (distância real / distância em pixels)²`.
Sem uma referência conhecida, a foto só fornece área em pixels. A área física
é uma estimativa da projeção visível, não da superfície 3D nem da base oculta.
Perspectiva e objetos em profundidades diferentes exigem referências/calibrações
específicas; uma escala uniforme não garante medidas físicas exatas nessa situação.

### Segmentar objetos e medir a máscara final

Na aba **Medições**, desenhe e feche a região de
interesse (ROI) e clique em **Segmentar ROI…** para abrir a aba **Segmentação**.
A ROI pode abranger um ou mais
objetos. Ela é uma indicação inicial; o GrabCut refina a separação entre objeto
e fundo. Deixe contexto de fundo ao redor dos objetos.

O botão **Executar fluxo completo** aplica, nesta ordem:

1. **Filtro bilateral:** suaviza texturas preservando bordas, com diâmetro e
   sigmas de cor e espaço ajustáveis.
2. **ROI manual:** usa o contorno selecionado na resolução original.
3. **Erosão e dilatação:** o núcleo erodido é objeto certo, a ROI é objeto provável,
   a faixa dilatada é fundo provável e a área externa é fundo certo. O elemento
   elíptico e as iterações são ajustáveis; zero iterações desliga a operação.
4. **GrabCut:** segmenta usando as quatro classes da máscara e o número de
   iterações configurado, em segundo plano para manter a interface utilizável.
5. **Máscara binária:** converte os rótulos de objeto para branco e de fundo
   para preto.
6. **Fechamento morfológico:** reduz pequenas descontinuidades, respeitando as
   sementes certas. Tamanho e iterações são ajustáveis; zero desliga o fechamento.
7. **Componentes conexos:** usa vizinhança de oito pixels e remove componentes
   abaixo da área mínima. **Manter apenas o maior** é opcional; deixe desmarcado
   para medir vários objetos. Essa limpeza pode remover pequenas sementes isoladas.
8. **Contagem de pixels:** mede cada componente e o total na máscara final.
   Os buracos pretos não contam como área; a contagem não usa a área geométrica
   dos contornos nem o retângulo externo da ROI.
9. **Contornos e sobreposição:** exibe a região segmentada em verde e os contornos
   em amarelo sobre a foto original, com a numeração dos componentes.

Use **Ver sementes** para conferir as classes: branco = objeto certo, preto =
fundo certo, amarelo = objeto provável e azul = fundo provável. Se o núcleo da
ROI inclui fundo, aumente a erosão ou pinte correções com os pincéis de objeto
e fundo certos/prováveis. As marcas manuais prevalecem sobre as sementes
morfológicas. O raio do pincel é medido em pixels da imagem original.
**Limpar marcas manuais** recupera as sementes geradas pela ROI.
Abra **Ajustes avançados** para personalizar os parâmetros do fluxo; a
configuração inicial permite executar sem preencher todos os campos.

O menu **Visualização** permite inspecionar as etapas. Use zoom e rolagem para
conferir detalhes; com o pincel **Navegar**, arraste para mover a imagem.
Alterar parâmetros ou marcas invalida a prévia e a área anterior: execute
novamente antes de salvar ou adicionar o resultado.

Confira a máscara final e selecione os componentes na tabela. Clique em
**Adicionar às medições** para registrar uma área por objeto, com a escala física
opcional já configurada na janela de medições. **Salvar máscara PNG** exporta
a imagem binária na resolução original; **Salvar sobreposição PNG** guarda a
conferência visual. A imagem aplicada no editor permanece intacta.
O GrabCut é semiautomático e depende da ROI e das sementes escolhidas; revise
a sobreposição antes de aceitar a segmentação.

### Recorte e contagem de pixels

Abra uma imagem e escolha a aba **Recorte**.
Escolha retângulo, quadrado, elipse, círculo ou losango e arraste sobre a imagem.
O botão **Aplicar recorte** confirma; **Voltar ao editor** fecha a aba sem recortar.
Escape limpa a seleção. A aba tem zoom e rolagem para ajustes precisos.
O recorte usa a imagem aplicada, descartando a prévia de filtro pendente.
Use **Desfazer/Refazer** para reverter ou recuperar o recorte e **Salvar como**
para gravar uma cópia.

A janela mostra a quantidade exata de pixels dentro da forma, contando os centros
dos pixels, e as dimensões do recorte. Elipse, círculo e losango deixam pretos os
pixels externos à forma dentro do arquivo retangular, sem transparência.
O painel também mostra o total de pixels da imagem (largura × altura) e megapixels;
os canais de cor não multiplicam essa contagem.

- Busca por nome, sem diferenciar acentos, em todas as categorias.
- Ajustes de cor e iluminação, CLAHE e redução de ruído parametrizáveis.
- Desfoques, movimento, Sobel, Scharr, Canny e magnitude do gradiente.
- Limiarização, contornos, mapas de distância e 22 mapas de cores.
- Estilização, lápis, cartoon, preservação de bordas e transformações.
- Painel lateral rolável e processamento em segundo plano.
- Ctrl+O abre; Ctrl+S salva; Ctrl+Shift+S salva como; Ctrl+Z/Ctrl+Y desfaz/refaz.
- Enter aplica; Escape descarta a prévia.

**Salvar grava a imagem aplicada, não a prévia.** Use Aplicar antes de salvar.
A prévia usa a resolução real para que operações locais, como morfologia,
tenham o mesmo resultado na aplicação. Fotos grandes podem levar mais tempo.
O histórico guarda até 25 estados e limita as cópias anteriores a aproximadamente
256 MiB, preservando pelo menos o último estado.

O catálogo cobre efeitos e operações de edição; não representa toda a API cv2.
Vídeo, calibração, redes neurais e outros recursos de visão computacional não
são filtros deste editor. A abertura converte arquivos para BGR de 8 bits:
transparência e profundidade de 16 bits não são preservadas nesta versão.
