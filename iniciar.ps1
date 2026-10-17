$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv .venv
    } else {
        & python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o ambiente Python. Instale Python 3.10 ou mais recente.' }
}
& $taskPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependências. Confira a conexão e a versão do Python.' }
& $taskPython -c "import cv2, PySide6; assert hasattr(cv2, 'face'), 'Recrie .venv: o módulo contrib é obrigatório para reconhecimento facial.'"
if ($LASTEXITCODE -ne 0) { throw 'Ambiente incompleto; consulte README.md.' }
& $taskPython main.py
