# Validação local — 17 de outubro de 2026

Ambiente Windows, Python 3.14.3, OpenCV contrib 4.14.0, NumPy 2.5.4 e Pillow
12.3.0, instalados no ambiente virtual `.venv` a partir de `requirements.txt`.

## Verificado

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Na primeira entrega, 81 testes passaram. A revisão terminou com **107 testes
passando em 22,330 segundos**, em 17/10/2026. A revisão ampliou a suíte com
detecção sem cadastro, persistência e validação do modelo, limiar salvo, treino
automático, importação, troca de base e captura assistida. O resultado da rodada
final está registrado no log local `validacao/testes.txt`. A suíte cobre filtros
em cor/cinza, soma/subtração saturadas, conversões, quantização, histogramas,
conectividade e tolerância de regiões, cópia independente, recorte, medições,
morfologia/GrabCut, histórico e comparação simultânea no Editor.

Os testes de Tkinter verificam navegação e estado das abas, controles na janela
mínima de 1000 × 680, preservação das ferramentas independentes e cancelamento
de callbacks ao fechar. O reconhecimento usa o LBPH real sobre recortes
sintéticos controlados; os testes conferem rejeição, persistência, CSV,
deduplicação e isolamento entre sessões enquanto um frame está em processamento.
A câmera indisponível e a liberação de seu recurso são verificadas com captura
simulada. AVI/MP4 são escritos e reabertos com codecs reais.

## Revisão facial e treinamento real

- A ausência de cadastro habilita detecção imediata; deixou de provocar o popup
  que exigia treinar o LBPH antes de analisar qualquer foto.
- O modelo salvo foi carregado em nova instância e no aplicativo integrado.
  A base de demonstração tem 30 identidades e 180 fotos de treinamento.
- O exemplo reservado `pessoa_02_09.png` foi reconhecido como DEMO-02 após
  recarregar o modelo. O exemplo `desconhecido_36_01.png` foi rejeitado.
- A chamada foi testada pela própria página: duas identificações da pessoa
  conhecida mais o exemplo desconhecido produziram uma presença, exportada
  em `validacao/chamada_demo.csv`.
- A comparação no app completo foi medida em 1000 × 680 (dois canvases de
  307 × 305) e 1280 × 820 (447 × 445). As ações globais de arquivo saem da
  tela em Faces/Vídeo; os atalhos salvam o resultado do módulo ativo.
- Cadastro, Modelo e Chamada têm abas próprias. Em alturas pequenas, a rolagem
  se limita à aba lateral necessária; os controles não ficam cortados.
- A imagem de saída do reconhecedor foi inspecionada e sua legenda foi ajustada
  para não cortar nome, ID e distância em fotos pequenas.

O [relatório público](FACES_DEMONSTRACAO.md) registra a fonte, SHA-256,
partições e métricas. No teste separado, foram 52/60 conhecidos identificados
corretamente e 39/50 desconhecidos rejeitados. As 11 falsas aceitações são
uma limitação real da demonstração e não foram ocultadas por ajuste no teste.

## Demonstração reproduzível

`gerar_demo.py` gerou cinco imagens e um vídeo sintéticos. Além da suíte, foram
produzidas saídas locais em `validacao/` e conferidos estes resultados:

| Saída | Resultado observado |
| --- | --- |
| Região do retângulo em `demo/cena.png`, semente (100,100), tolerância 0, vizinhança 4 | 34.571 pixels, iguais a 181 × 191 |
| Histogramas RGB da cena 640 × 360 | 230.400 pixels contados em cada canal |
| Redimensionamento | PNG de 320 × 180 |
| Quantização | PNG com quatro níveis por canal |
| Exportação Canny de `demo/video_demo.avi` | 60 frames, 640 × 360, 15 FPS; os 60 frames foram reabertos |

As imagens de demonstração, `.venv`, os resultados e logs locais são ignorados
pelo Git. Código, scripts, testes e documentação estão incluídos nas regras
de versionamento. O inicializador PowerShell também passou pela análise de
sintaxe, e `git diff --check` não encontrou problemas.

## Limites da evidência

- A ferramenta Computer Use não recebeu autorização para inspecionar a janela
  `pythonw`; esta rodada não inclui inspeção visual humana nem capturas da UI.
  Os controles foram conferidos por testes de geometria e comportamento.
- Uma câmera física não foi usada nesta validação.
- Não há cadastro de alunos reais: fotos próprias, calibração do limiar e
  ensaio com a turma ainda são necessários. Os testes sintéticos não medem
  acurácia de identificação de pessoas.
- O workflow de testes para Windows/Python 3.11 e 3.14 foi preparado. Sua
  execução no GitHub Actions ainda não foi verificada.

Use o [roteiro de demonstração](ROTEIRO_DEMONSTRACAO.md) para o ensaio completo
e a [matriz de requisitos](REQUISITOS.md) para conferir a cobertura do enunciado.
