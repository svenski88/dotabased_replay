param([switch]$OneFile)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
  python scripts/build_parser.py
  if ($LASTEXITCODE -ne 0) { throw 'Native replay parser build failed' }
  python -m PyInstaller --version
  if ($LASTEXITCODE -ne 0) { throw 'Install build tooling first: python -m pip install -r requirements-build.txt' }
  $bundleMode = if ($OneFile) { '--onefile' } else { '--onedir' }
  python -m PyInstaller --noconfirm --clean --windowed $bundleMode --icon 'assets/brand/replay.ico' --add-data 'assets:assets' --add-data 'third_party:third_party' --add-binary 'bin/replay-parser.exe:bin' --name DotaBasedReplay app.py
  if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
  if ($OneFile) {
    Write-Host 'Built dist/DotaBasedReplay.exe'
  } else {
    Write-Host 'Built dist/DotaBasedReplay/DotaBasedReplay.exe. Distribute the entire DotaBasedReplay folder.'
  }
} finally {
  Pop-Location
}
