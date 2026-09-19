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

## Morfologia e elementos personalizados

1. Abra uma imagem e escolha a categoria **Morfologia**.
2. Clique em **Elemento estruturante e morfologia…**.
3. Escolha retângulo, elipse, cruz, losango, linhas ou diagonais. Defina largura e
   altura de 1 a 31 e clique em **Gerar matriz**. A forma Personalizado começa vazia.
4. Clique nas células para alternar `0 → 1 → -1`, ou arraste para pintar.
   Clique com o botão direito para definir a âncora. A borda amarela marca a âncora.
5. Escolha iterações, bordas e modo de imagem. Clique em **Usar elemento**.
6. Escolha a operação, confira a prévia e clique em **Aplicar filtro**.

As oito operações nativas estão disponíveis: erosão, dilatação, abertura,
fechamento, gradiente, top-hat, black-hat e hit-or-miss. A matriz e as opções
podem ser exportadas/importadas em JSON. Arquivos importados são validados.

Em hit-or-miss, `1` exige objeto, `-1` exige fundo e `0` ignora a posição.
A imagem é binarizada usando o limiar configurado. Nas outras operações,
somente as células `1` participam. Deve existir pelo menos uma célula `1`.
Âncora `(-1, -1)` significa centro automático; outras coordenadas começam em zero.
Referência: [OpenCV Hit-or-Miss](https://docs.opencv.org/4.x/db/d06/tutorial_hitOrMiss.html).

## Recursos

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
