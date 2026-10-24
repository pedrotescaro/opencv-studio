# Grupo e câmera ao vivo — validação de 24/10/2026

O aplicativo passa a usar o grupo configurado em `fotos_grupo/integrantes.json`:
Pedro Antônio Silvestre Tescaro, Guilherme Alves de Campos e Paulo Henrique Leal
dos Santos. O scanner compara somente essas três identidades.

## Entrega

- Pastas individuais com 19 fotos de cadastro fornecidas pelo grupo: Pedro 7,
  Guilherme 6 e Paulo 6. A seleção e os motivos de separação dos oito arquivos
  restantes estão em `fotos_grupo/preparacao.json`; os originais foram preservados.
- Cadastro YuNet + SFace persistido localmente, usando extração de descritores
  de uma rede pré-treinada. Pesos oficiais verificados por SHA-256, baixados
  somente quando um treinamento explícito os exige.
- Botão de câmera com reprodução contínua, pausa/retomada, reconexão e liberação
  ao desligar. Chamadas usam somente o processamento da câmera ao vivo.
- Fotos, arquivos de vídeo, quadros pausados e exportações não registram presença.
- Fontes modificadas ou cadastro fora das três identidades impedem reconhecimento
  até novo treinamento. Falha no treino preserva o conjunto anterior e chamadas.

## Evidência executada

| Verificação | Resultado |
| --- | --- |
| Suíte Qt completa | 152 testes aprovados, sem falhas. |
| Regressão legada e serviços novos | 127 testes aprovados, sem falhas. |
| Treinamento com fotos reais | 3 integrantes, 19 fotos distintas. |
| Foto coletiva fora do cadastro | Três rostos detectados; IDs PEDRO, GUILHERME e PAULO retornados. |
| Câmera física 0 | 640×480; 8 quadros lidos, 4 conteúdos distintos, dispositivo liberado. |
| Interface nativa | Scanner aberto em estado Ao vivo, original/processado visíveis; Desligar câmera confirmou desconexão. |

O resultado detalhado da foto está em `fotos_grupo/teste/avaliacao.json`. Ela foi
reservada antes de cadastrar os descritores, sem fazer parte do treino. O limiar
inicial 0,637 e margem 0,05 são fixos; não foram relaxados para aceitar a foto.

A avaliação de uma única foto coletiva não mede taxa de acerto em sala. A câmera
foi validada para captura real e integração, sem um ensaio com os três integrantes
presentes fisicamente. Testes de deduplicação/exportação usam IDs controlados.
Não há prova de vida; uma foto ou vídeo mostrado à câmera pode enganar a chamada.

## Reproduzir

```powershell
.\.venv\Scripts\python.exe treinar_grupo.py
.\.venv\Scripts\python.exe main.py --faces
```

Use **Abrir câmera ao vivo** para o scanner, ou **Chamada → Iniciar chamada ao vivo**.
As instruções para adicionar fotos estão em [Fotos do grupo](../fotos_grupo/README.md).
