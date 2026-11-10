# João de Barro — instala o que falta e sobe o servidor neste computador (Windows).
#   Botão direito > "Executar com o PowerShell", ou:  powershell -ExecutionPolicy Bypass -File .\iniciar.ps1
# Rodar de novo só sobe o servidor (o que já está instalado é reaproveitado).
param([switch]$SemNavegador)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$raiz = $PSScriptRoot

function Tem($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function AtualizarPath {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Instalar($id, $nome) {
    if (-not (Tem "winget")) { throw "$nome não está instalado e o winget não existe neste Windows. Instale $nome manualmente e rode de novo." }
    Write-Host "Instalando $nome..." -ForegroundColor Cyan
    winget install --id $id -e --accept-source-agreements --accept-package-agreements --silent | Out-Null
    AtualizarPath
}

# O "python" da Microsoft Store é só um atalho para a loja: não serve.
function PythonBom {
    $c = Get-Command python -ErrorAction SilentlyContinue
    if (-not $c -or $c.Source -like "*WindowsApps*") { return $false }
    $v = & python -c "import sys; print(sys.version_info >= (3, 11))" 2>$null
    return ($v -eq "True")
}

Write-Host "== 1/5 Python e Node ==" -ForegroundColor Yellow
if (-not (PythonBom)) { Instalar "Python.Python.3.12" "Python 3.12" }
if (-not (PythonBom)) { throw "Python 3.11+ não encontrado. Feche esta janela, abra outra e rode de novo (o PATH só atualiza em janela nova)." }
if (-not (Tem "node")) { Instalar "OpenJS.NodeJS.LTS" "Node.js" }
if (-not (Tem "node")) { throw "Node.js não encontrado. Feche esta janela, abra outra e rode de novo." }
Write-Host ("Python " + (& python --version) + " | Node " + (& node --version))

Write-Host "== 2/5 servidor (bibliotecas) ==" -ForegroundColor Yellow
$venv = Join-Path $raiz "backend\.venv"
$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) { & python -m venv $venv }
$marca = Join-Path $venv ".instalado"
$req = Join-Path $raiz "backend\requirements.txt"
if (-not (Test-Path $marca) -or (Get-Item $req).LastWriteTime -gt (Get-Item $marca).LastWriteTime) {
    & $py -m pip install --disable-pip-version-check -q -r $req
    if ($LASTEXITCODE -ne 0) { throw "pip falhou" }
    Set-Content $marca (Get-Date)
}
Write-Host "ok"

Write-Host "== 3/5 tela ==" -ForegroundColor Yellow
$dist = Join-Path $raiz "frontend\dist-joaodebarro\index.html"
if (-not (Test-Path $dist)) {
    Push-Location (Join-Path $raiz "frontend")
    & npm.cmd install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm install falhou" }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "build da tela falhou" }
    Pop-Location
}
Write-Host "ok"

Write-Host "== 4/5 conta do avaliador ==" -ForegroundColor Yellow
Push-Location (Join-Path $raiz "backend")
$dono = & $py -c "from lovable.avaliacao import db; db.init(); print(db.setting('dono_email') or '')"
if (-not $dono) {
    $email = Read-Host "E-mail do avaliador (vai ser o login)"
    $senha = Read-Host "Senha (mínimo 6 caracteres)"
    & $py criar_usuario.py $email $senha
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "não foi possível criar a conta" }
} else { Write-Host "avaliador: $dono (para trocar a senha: backend\.venv\Scripts\python backend\criar_usuario.py email senha)" }

# Coletor (.exe) para o botão "Baixar o Coletor" da tela: vem da página de Releases do GitHub.
$exe = Join-Path $raiz "data\avaliacao\coletor\joaodebarro-coletor.exe"
if (-not (Test-Path $exe)) {
    try {
        New-Item -ItemType Directory -Force (Split-Path $exe) | Out-Null
        Write-Host "baixando o Coletor (70 MB)..."
        Invoke-WebRequest "https://github.com/DaniloSoares22121/joao-de-barro/releases/latest/download/joaodebarro-coletor.exe" -OutFile $exe -UseBasicParsing
    } catch { Write-Host "AVISO: não baixei o Coletor ($($_.Exception.Message)). Dá para rodar pelo código: veja o README." -ForegroundColor DarkYellow }
}

if (-not (Test-Path "C:\Program Files\LibreOffice\program\soffice.exe") -and -not (Tem "soffice")) {
    Write-Host "AVISO: LibreOffice não instalado. O laudo sai em Word e planilha, mas SEM o PDF. Para ter o PDF: winget install TheDocumentFoundation.LibreOffice" -ForegroundColor DarkYellow
}
$envArq = Join-Path $raiz ".env"
$temChave = [bool]$env:ANTHROPIC_API_KEY -or ((Test-Path $envArq) -and [bool](Select-String -Path $envArq -Pattern "^ANTHROPIC_API_KEY=." -Quiet))
if (-not $temChave -and -not (Test-Path (Join-Path $HOME ".claude"))) {
    Write-Host "AVISO: a IA ainda não está configurada. Ponha ANTHROPIC_API_KEY no arquivo .env (copie de .env.exemplo) ou faça login no Claude Code neste PC. Sem isso a tela abre, mas o laudo não é gerado." -ForegroundColor DarkYellow
}

Write-Host "== 5/5 subindo ==" -ForegroundColor Yellow
Write-Host "Abra http://127.0.0.1:8870  (Ctrl+C para parar)" -ForegroundColor Green
if (-not $SemNavegador) { Start-Process "http://127.0.0.1:8870" }
& $py run.py
Pop-Location
