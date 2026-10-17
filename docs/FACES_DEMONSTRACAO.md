# Demonstração facial treinada e verificada

A demonstração usa fotografias reais da **AT&T Database of Faces**, antiga ORL,
disponibilizada pelo [arquivo oficial de Cambridge](https://www.cl.cam.ac.uk/research/dtg/attarchive/facedatabase.html).
São 400 fotografias, dez de cada uma de 40 pessoas, produzidas entre 1992 e 1994.
A página oficial solicita crédito a **AT&T Laboratories Cambridge**. Ela não apresenta
uma licença Creative Commons; este projeto usa os arquivos somente na demonstração
local e não distribui fotografias ou modelo no repositório.

Os nomes **Pessoa demonstração 01** a **Pessoa demonstração 30** são rótulos anônimos.
Essas pessoas não são alunos cadastrados. O banco de demonstração fica em
`.dados_faces_demo/`, separado do cadastro pessoal `.dados_faces/`.

## Preparar e abrir

No PowerShell, na pasta do projeto:

```powershell
.\.venv\Scripts\python.exe preparar_faces_demo.py
powershell -ExecutionPolicy Bypass -File .\iniciar.ps1
```

No seletor superior, abra **Rostos e chamada**, selecione **Demonstração pública · AT&T/ORL**
e abra a aba **Modelo** para usar **Abrir exemplo público de teste**. Escolher **Minha turma**
restaura o banco pessoal. Se o cadastro pessoal estiver vazio e a base já estiver
preparada, a demonstração é carregada automaticamente e identificada no seletor.
O início do aplicativo não faz download de fotografias.

Para refazer a avaliação sem rede, depois do primeiro preparo:

```powershell
.\.venv\Scripts\python.exe preparar_faces_demo.py --offline
```

Arquivos úteis, todos locais e ignorados no Git:

| Arquivo | Conteúdo |
| --- | --- |
| `.dados_faces_demo/relatorio.json` | Protocolo, limiar, métricas e resultado de cada foto de teste |
| `.dados_faces_demo/modelo_lbph.yml` | Modelo LBPH efetivamente treinado |
| `.dados_faces_demo/modelo_lbph.json` | Manifesto e hashes conferidos antes de carregar o modelo |
| `.dados_faces_demo/teste/pessoa_02_09.png` | Foto conhecida que não participou do treino |
| `.dados_faces_demo/teste/desconhecido_36_01.png` | Foto de pessoa que não foi cadastrada |

O ZIP é obtido do [endereço oficial](https://www.cl.cam.ac.uk/Research/DTG/attarchive/pub/data/att_faces.zip).
O script fixa o SHA-256 observado desse arquivo em 17/10/2026:
`509d763bd2276aa054d260d7f1000e8be212738134f2f83d8ff13bc2adf1c8ec`.
Esse hash foi fixado pelo projeto; não é um checksum publicado por Cambridge.
Downloads com hash diferente são rejeitados. O script lê somente os 400 PGM
esperados em memória, sem extrair caminhos fornecidos pelo ZIP.

## Protocolo sem usar o teste no treinamento

Os índices de pessoas e fotos são fixos e registrados no relatório:

| Conjunto | Pessoas | Fotos por pessoa | Total |
| --- | --- | --- | --- |
| Treino | 01–30 | 01–06 | 180 |
| Calibração de conhecidos | 01–30 | 07–08 | 60 |
| Calibração de desconhecidos | 31–35 | 01–10 | 50 |
| Teste de conhecidos | 01–30 | 09–10 | 60 |
| Teste de desconhecidos | 36–40 | 01–10 | 50 |

O limiar é escolhido somente na calibração, pela maior média entre identificação
correta dos conhecidos e rejeição de desconhecidos. Empates favorecem o menor
limiar. O teste usa outras fotos dos conhecidos e pessoas desconhecidas diferentes
das da calibração. Nenhuma fotografia do teste vira amostra cadastrada.

Cada PGM original de 92×112 é ampliado duas vezes e recebe borda de 40 pixels,
cinza de intensidade 30. Essa preparação deixa espaço ao redor do rosto para
o detector Haar. Ele encontrou exatamente uma face em **400 de 400 fotos** na
execução com OpenCV 4.14.0. O treino e a avaliação usam o recorte produzido pelo
Haar real, seguido da normalização de 128×128 e equalização do módulo facial.
Não há caixas de detecção simuladas, cópias de fotos de treino nos testes nem
geração de rostos sintéticos neste experimento.

## Resultados obtidos em 17/10/2026

O LBPH foi treinado com **180 fotografias reais de 30 pessoas**. O limiar calibrado
foi **61,20421965**. A distância LBPH é uma medida de diferença, não uma porcentagem
de confiança.

| Avaliação | Resultado |
| --- | --- |
| Calibração: conhecidos identificados corretamente | 50/60 (83,33%) |
| Calibração: desconhecidos rejeitados | 50/50 (100%) |
| Teste: conhecidos identificados corretamente | 52/60 (86,67%) |
| Teste: conhecidos rejeitados | 8/60 (13,33%) |
| Teste: conhecidos com identidade errada aceita | 0/60 |
| Teste: desconhecidos rejeitados | 39/50 (78%) |
| Teste: desconhecidos aceitos incorretamente | 11/50 (22%) |

O relatório registra também uma política alternativa calculada apenas na
calibração: maximizar identificações corretas, permitindo até 4% de falsas
aceitações de desconhecidos na calibração. Ela selecionou limiar 63,3435,
com 51/60 conhecidos corretos e 49/50 desconhecidos rejeitados na calibração.
No teste, aceitou 53/60 conhecidos corretamente, atribuiu uma identidade errada
e rejeitou somente 31/50 desconhecidos. Essa política não melhorou a rejeição
no holdout e **não foi adotada como padrão**. O resultado ilustra por que um
limiar calibrado em poucas pessoas não garante segurança para rostos novos.

As duas fotos usadas nos botões de exemplo são fixas, e suas previsões também
passam pelo detector Haar e pelo reconhecedor da interface:

- `pessoa_02_09.png`: reconhecida como **Pessoa demonstração 02 / DEMO-02**,
  distância 46,8075.
- `desconhecido_36_01.png`: **Desconhecido**, distância 75,3815.

Também foi executado o diagnóstico de fornecer o PGM inteiro diretamente ao
classificador treinado com recortes Haar: apenas 4/60 conhecidos foram aceitos
corretamente e 56/60 foram rejeitados. Isso evidencia que o enquadramento precisa
ser consistente entre cadastro e reconhecimento. A interface utiliza o detector
Haar nas fotos e no vídeo.

O modelo persistido foi carregado em uma nova instância do motor, que restaurou
o limiar calibrado e reconheceu novamente a foto de teste DEMO-02.

## Limites práticos

Este resultado demonstra integração e treinamento reais em uma base pequena e
controlada. **As onze falsas aceitações de desconhecidos impedem tratar essa
demonstração como prova de chamada automática confiável.** Para identificar os
alunos, selecione **Minha turma**, cadastre fotos distintas dos alunos e
avalie com fotos novas nas condições da câmera da sala. Confira cada presença.
Fotos de webcam, variação real de iluminação e resistência a apresentação de
foto/vídeo de outra pessoa ainda não foram validadas.

Referência da base: Samaria, F.; Harter, A. *Parameterisation of a stochastic model
for human face identification*. 2nd IEEE Workshop on Applications of Computer
Vision, Sarasota, 1994. A página oficial disponibiliza o artigo.
