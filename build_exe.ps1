# Baut Fisch-Bot DE als Standalone-EXE.
# Nutzung:  powershell -ExecutionPolicy Bypass -File build_exe.ps1
$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([string]$Description, [scriptblock]$Command)
    Write-Host "==> $Description" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Fehlgeschlagen: $Description (Exit-Code $LASTEXITCODE)"
    }
}

# 1) Python 3.13 muss vorhanden sein.
Invoke-Checked "Pruefe Python 3.13" { py -3.13 --version }

# 2) WizWalker IMMER zuerst aus dem development-Branch neu installieren,
#    da die Fishing-Signaturen darauf basieren.
Invoke-Checked "Installiere WizWalker (development branch, erzwungen)" {
    py -3.13 -m pip install --upgrade --force-reinstall `
        "https://github.com/Vindaloniak/wizwalker/archive/refs/heads/development.zip"
}

# 3) Restliche Abhaengigkeiten (inkl. PyInstaller) installieren.
Invoke-Checked "Installiere restliche Abhaengigkeiten" {
    py -3.13 -m pip install --upgrade PyQt6 requests loguru memobj pyinstaller
}

# 4) Alte Build-Artefakte entfernen.
foreach ($dir in @("build", "dist")) {
    if (Test-Path $dir) {
        Remove-Item -Recurse -Force $dir
    }
}
if (Test-Path "FischBotDE.spec") {
    Remove-Item -Force "FischBotDE.spec"
}

# 5) EXE bauen. --uac-admin sorgt dafuer, dass Windows automatisch nach
#    Administratorrechten fragt (noetig fuer den Speicherzugriff).
Invoke-Checked "Baue EXE mit PyInstaller" {
    py -3.13 -m PyInstaller `
        --noconfirm `
        --onefile `
        --windowed `
        --uac-admin `
        --name "FischBotDE" `
        --collect-all wizwalker `
        --collect-all memobj `
        --collect-all loguru `
        gui.py
}

Write-Host ""
Write-Host "Fertig! Die EXE liegt unter dist\FischBotDE.exe" -ForegroundColor Green
