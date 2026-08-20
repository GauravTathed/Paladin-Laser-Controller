$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        py -3 -m venv .venv
    }
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -e . pyinstaller
    & $venvPython -m PyInstaller --noconfirm --clean --onefile --windowed --name PaladinLaserController run_paladin_controller.py
    Write-Host "Built: $projectRoot\dist\PaladinLaserController.exe"
}
finally {
    Pop-Location
}

