# Gera dist\joaodebarro-coletor.exe. Use -Publicar para copiar para data\avaliacao\coletor\.
param([switch]$Publicar)
# Erros de comandos nativos são checados por $LASTEXITCODE (pip escreve avisos no stderr).
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
python -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip falhou" }
python -m PyInstaller --noconfirm --onefile --noconsole --name joaodebarro-coletor joaodebarro_coletor.py
if ($LASTEXITCODE -ne 0) { throw "pyinstaller falhou" }
$exe = Join-Path $PSScriptRoot "dist\joaodebarro-coletor.exe"
if (-not (Test-Path $exe)) { throw "exe nao gerado" }
if ($Publicar) {
    $destino = Join-Path $PSScriptRoot "..\data\avaliacao\coletor"
    New-Item -ItemType Directory -Force $destino | Out-Null
    Copy-Item $exe $destino -Force
    Write-Host "Publicado em $destino"
}
Write-Host "OK: $exe"
