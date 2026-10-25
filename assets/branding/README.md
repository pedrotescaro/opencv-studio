# Identidade do OpenCV Studio

O monograma azul foi fornecido pelo autor do projeto. O arquivo `logo.png`
preserva integralmente o PNG original e sua transparência.

| Arquivo | Uso |
| --- | --- |
| `logo.png` | Logo principal e README; imagem original. |
| `app-icon.png` | Monograma centralizado em uma área transparente de 512×512. |
| `app-icon.ico` | Ícone desktop em 16, 20, 24, 32, 40, 48, 64, 128 e 256 pixels. |
| `favicon.ico` | Favicon em 16, 32 e 48 pixels. |
| `favicon.png` | Favicon PNG de 32×32. |

Os ícones apenas ajustam escala e margem transparente do desenho fornecido.
O aplicativo Qt usa o ICO na janela e a mesma identidade no cabeçalho e na
barra de tarefas do Windows, por `studio/branding.py`.

Não existe uma interface web neste repositório. Para reutilizar o favicon em
uma página, copie os arquivos e ajuste os caminhos dos elementos HTML:

```html
<link rel="icon" href="favicon.ico" sizes="16x16 32x32 48x48">
<link rel="icon" href="favicon.png" type="image/png" sizes="32x32">
```

O projeto é executado com Python. Ao criar futuramente um executável com
PyInstaller, use `--icon assets/branding/app-icon.ico` e inclua a pasta
`assets/branding` nos recursos do pacote. O ícone de um executável Python
instalado no sistema não é modificado por esta configuração.
