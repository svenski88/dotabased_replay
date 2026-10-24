param([switch]$OneFile)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
  python -m PyInstaller --version
  if ($LASTEXITCODE -ne 0) { throw 'Install build tooling first: python -m pip install -r requirements-build.txt' }
  $bundleMode = if ($OneFile) { '--onefile' } else { '--onedir' }
  python -m PyInstaller --noconfirm --clean --windowed $bundleMode --add-data 'assets:assets' --name DotaBasedReplay app.py
  if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
  if ($OneFile) {
    Write-Host 'Built dist/DotaBasedReplay.exe'
  } else {
    Write-Host 'Built dist/DotaBasedReplay/DotaBasedReplay.exe. Distribute the entire DotaBasedReplay folder.'
  }
} finally {
  Pop-Location
}
