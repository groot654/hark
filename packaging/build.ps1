# Builds dist\Togo (Togo.exe + togo-mcp.exe) and, if Inno Setup 6 is installed, dist\TogoSetup-<version>.exe.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"

& $python make_icon.py
& $python -m PyInstaller togo.spec --noconfirm --distpath ..\dist --workpath ..\build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$version = & $python -c "import togo; print(togo.__version__)"
$iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if ($iscc) {
    & $iscc "/DAppVersion=$version" togo.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
    Write-Host "Installer: dist\TogoSetup-$version.exe"
} else {
    Write-Host "Built dist\Togo. To make an installer too, install Inno Setup 6 (winget install JRSoftware.InnoSetup) and run this again."
}
