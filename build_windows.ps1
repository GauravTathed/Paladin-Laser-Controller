$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        py -3 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the build environment.' }
    }
    & $venvPython -m pip install -e . pyinstaller
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the build dependencies.' }
    & $venvPython -m PyInstaller --noconfirm --clean --onefile --windowed --name PaladinLaserController run_paladin_controller.py
    if ($LASTEXITCODE -ne 0) { throw 'Could not build the Windows executable.' }
    $dist = Join-Path $projectRoot 'dist'
    $exe = Join-Path $dist 'PaladinLaserController.exe'
    $bundle = Join-Path $dist 'Paladin-Door-Feed-Windows.zip'
    Compress-Archive -LiteralPath $exe, (Join-Path $projectRoot 'setup-door-feed.ps1') -DestinationPath $bundle -Force
    Get-FileHash -LiteralPath $exe, $bundle -Algorithm SHA256 |
        ForEach-Object { "$($_.Hash.ToLowerInvariant())  $(Split-Path -Leaf $_.Path)" } |
        Set-Content -LiteralPath (Join-Path $dist 'SHA256SUMS.txt') -Encoding ascii
    Write-Host "Built Windows release assets in $dist"
}
finally {
    Pop-Location
}

