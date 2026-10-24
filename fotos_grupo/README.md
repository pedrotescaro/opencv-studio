# Fotos do grupo

O scanner do aplicativo usa somente as três identidades de `integrantes.json`:

| Integrante | Pasta | Fotos de cadastro iniciais |
| --- | --- | --- |
| Pedro Antônio Silvestre Tescaro | `pedro_antonio_silvestre_tescaro/` | 7 |
| Guilherme Alves de Campos | `guilherme_alves_de_campos/` | 6 |
| Paulo Henrique Leal dos Santos | `paulo_henrique_leal_dos_santos/` | 6 |

As fotografias foram fornecidas pelo grupo. **As imagens nestas três pastas e
em `teste/grupo.jpeg` são versionadas no repositório público, conforme solicitado.**
O programa não faz upload automático; novas fotos só são publicadas por commit/push.

## Adicionar fotos e treinar

1. Abra **Rostos e chamada → Cadastro** e selecione o integrante.
2. Clique em **Abrir pasta de fotos** e coloque as fotos diretamente nessa pasta.
3. Use **Atualizar contagem de fotos** e **Treinar com as fotos do grupo**.
4. Aguarde a confirmação dos três integrantes. O processamento ocorre em segundo plano.

Use JPG/JPEG, PNG, BMP, TIFF ou WebP. Cada foto precisa mostrar um único rosto
frontal detectável. São necessárias ao menos duas fotos distintas por pessoa;
copiar a mesma foto com outros nomes não aumenta o cadastro. Varie iluminação,
expressão, distância e use também imagens nas condições da câmera que fará a chamada.
Imagens inválidas são informadas com o nome do arquivo, sem substituir um treino anterior.

Pelo terminal, na raiz do projeto:

```powershell
.\.venv\Scripts\python.exe treinar_grupo.py
.\.venv\Scripts\python.exe main.py --faces
```

No primeiro treinamento, o programa baixa os modelos oficiais YuNet e SFace do
OpenCV Zoo (cerca de 37 MB), confere seus SHA-256 e os guarda em `.modelos_faces/`.
Após isso, cadastro e reconhecimento funcionam localmente. As redes já são
pré-treinadas: o cadastro extrai descritores das fotos do grupo e cria a galeria
para comparação, sem retreinar os pesos da rede neural.

O cadastro derivado, descritores e chamadas ficam em `.dados_faces_grupo_sface/`,
fora do Git. Modificar, remover ou adicionar fotos invalida a correspondência do
modelo; treine novamente. A demonstração AT&T/ORL e o cadastro antigo permanecem
separados e não são usados pelo scanner do grupo.

## Câmera ao vivo e chamada

- **Abrir câmera ao vivo** abre o módulo Vídeo, seleciona reconhecimento facial
  e inicia a transmissão contínua da câmera escolhida (normalmente índice 0).
- Na aba **Chamada**, informe a aula e clique em **Iniciar chamada ao vivo**.
  Uma identidade aceita gera uma presença por sessão. O botão **Encerrar** fecha
  a sessão; use **Exportar CSV/JSON** para a lista.
- **Desligar câmera**, no módulo Vídeo, libera o dispositivo. **Pausar câmera**
  congela a prévia, mantendo a conexão; **Retomar câmera** continua a transmissão.
- Fotos abertas, quadros pausados, arquivos de vídeo e exportações podem ser
  reconhecidos, mas não registram presença na chamada ao vivo.

## Comparação e limitações

YuNet detecta o rosto e os pontos usados no alinhamento. SFace extrai um descritor
e o compara com os exemplos cadastrados. A distância mostrada é `1 - similaridade
de cosseno`: quanto menor, mais semelhantes. O limite inicial é 0,637, equivalente
à similaridade 0,363 da documentação OpenCV, com margem mínima de 0,05 entre
os dois integrantes mais próximos. Uma comparação insuficiente ou ambígua vira
**Desconhecido**. Isso não é uma probabilidade nem uma garantia de identidade.

Referência: [detecção e reconhecimento DNN no OpenCV](https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html).
Modelos e licenças: [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
e [SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface).

Somente três nomes podem sair do cadastro, mas ainda podem ocorrer falsos
reconhecimentos de outras pessoas. Não há prova de vida: apresentar uma foto ou
vídeo à câmera pode enganar a chamada. Confira as presenças antes de utilizá-las.

## Fotos separadas

`teste/grupo.jpeg` foi reservada para avaliação e não participa do cadastro.
O arquivo `preparacao.json` registra a seleção inicial das 27 fotos individuais:
19 usadas e oito separadas em `revisar/` localmente, por detecções pequenas ou
múltiplas. Os originais em Downloads foram preservados. A pasta `revisar/` não
entra no treinamento nem no Git. Novas fotos não são filtradas silenciosamente:
o treinamento exige corrigir os arquivos problemáticos apresentados na mensagem.
