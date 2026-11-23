param([switch]$OneFile, [string]$Version)
$ErrorActionPreference = 'Stop'
$metadataFolder = $null
Push-Location $PSScriptRoot
try {
  $metadataArgs = @()
  if ($Version) {
    $versionName = python -c 'import sys; from scripts.package_release import version_name; print(version_name(sys.argv[1]))' $Version
    if ($LASTEXITCODE -ne 0) { throw 'Invalid build version' }
    $metadataFolder = New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString()))
    $metadataPath = Join-Path $metadataFolder.FullName 'build-info.json'
    @{ version = $versionName } | ConvertTo-Json -Compress | Set-Content -LiteralPath $metadataPath -Encoding utf8
    $metadataArgs = @('--add-data', "${metadataPath}:.")
  }
  python scripts/build_parser.py
  if ($LASTEXITCODE -ne 0) { throw 'Native replay parser build failed' }
  python scripts/collect_inference_licenses.py
  if ($LASTEXITCODE -ne 0) { throw 'Inference license collection failed; install requirements-build.txt' }
  python -m PyInstaller --version
  if ($LASTEXITCODE -ne 0) { throw 'Install build tooling first: python -m pip install -r requirements-build.txt' }
  $bundleMode = if ($OneFile) { '--onefile' } else { '--onedir' }
  python -m PyInstaller --noconfirm --clean --windowed $bundleMode --icon 'assets/brand/replay.ico' --add-data 'assets:assets' --add-data 'models:models' --add-data 'third_party:third_party' --add-binary 'bin/replay-parser.exe:bin' @metadataArgs --collect-all lightgbm --exclude-module sklearn --exclude-module matplotlib --exclude-module PIL --name DotaBasedReplay app.py
  if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
  if ($OneFile) {
    Write-Host 'Built dist/DotaBasedReplay.exe'
  } else {
    Write-Host 'Built dist/DotaBasedReplay/DotaBasedReplay.exe. Distribute the entire DotaBasedReplay folder.'
  }
} finally {
  if ($metadataFolder) {
    if (Test-Path -LiteralPath $metadataPath) { Remove-Item -LiteralPath $metadataPath }
    Remove-Item -LiteralPath $metadataFolder.FullName
  }
  Pop-Location
}
