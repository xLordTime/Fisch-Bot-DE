# Update-Hinweise (immer vor einem Release pruefen)

## Version 1.3.1 - UI-Politur
- [ ] Tabwechsel gleiten in beide Richtungen.
- [ ] Fischmotiv erscheint als Fenstersymbol und ist im Onefile-Build enthalten.
- [ ] Numerische Settings-Werte sind linksbuendig; erfolgreicher Hook waehlt den Client fuer Fishing aus.

## Version 1.3.0 - UI-Refresh
- [ ] Alle sechs Tabs pruefen: Hook, Fishing, Settings, Themes, Log und Credits.
- [ ] Fishing-Schalter startet und stoppt den Bot; Standardzustand ist Aus.
- [ ] Auto-Update ist standardmaessig aktiviert und die Auswahl bleibt nach Neustart erhalten.
- [ ] Alle drei Themes wechseln und bleiben nach Neustart ausgewaehlt.
- [ ] Erweiterte Wartezeiten starten eingeklappt; Tooltips sind nur in Settings sichtbar.
- [ ] Log-Export startet im nativen Downloads-Ordner.

Diese Liste musst du bei **jedem** Release beachten, damit die Auto-Update-Funktion
in der GUI (`updater.py`) funktioniert und die Nutzer eine funktionierende EXE bekommen.

## 1. Version erhoehen
- [ ] `CURRENT_VERSION` in `version.py` erhoehen (z.B. `1.0.0` -> `1.0.1`).
- [ ] Der GitHub-Release-**Tag** muss zur Version passen, z.B. Tag `v1.0.1` fuer `CURRENT_VERSION = "1.0.1"`.
- [ ] Nur hoehere Versionsnummern werden von `updater.is_newer()` als Update erkannt
      (Format `MAJOR.MINOR.PATCH`, rein numerisch vergleichen).

## 2. WizWalker-Abhaengigkeit pruefen
- [ ] Vor jedem Build sicherstellen, dass der WizWalker-development-Branch aktuell und
      kompatibel ist (Spiel-Patches/Signaturen koennen sich nach einem Wizard101-Update
      aendern).
- [ ] `build_exe.ps1` ausfuehren - das Skript installiert WizWalker **zwingend neu**
      (`pip install --upgrade --force-reinstall ".../development.zip"`), bevor die EXE
      gebaut wird. Diesen Schritt nicht manuell ueberspringen.
- [ ] Nach dem Build kurz gegen ein laufendes Wizard101-Fenster testen (Hook-Tab -> Hooken,
      Start, ein paar Fische fangen, Stop, Enthooken).
- [ ] pip meldet beim Installieren evtl. einen Versionskonflikt zwischen `wizwalker`
      (will `pefile<2024`/`regex<2025`) und `memobj` (will neuere `pefile`/`regex`).
      Das ist nur eine Resolver-**Warnung**, kein Fehler - Build und Bot funktionieren
      trotzdem (so getestet beim v1.0.0-Release).
- [ ] Falls auf dem Build-Rechner kein Python 3.13 installiert ist, faellt
      `build_exe.ps1` automatisch auf 3.12 zurueck.

## 3. Build
- [ ] `powershell -ExecutionPolicy Bypass -File build_exe.ps1` lokal auf einem sauberen
      Python-3.13-Setup laufen lassen.
- [ ] `FischBotDE.ico` muss vorhanden sein und aus dem aktuellen App-Icon erstellt worden sein;
      das Build-Skript bettet es in die EXE ein.
- [ ] Pruefen, dass `dist\FischBotDE.exe` existiert und startet (inkl. UAC-Admin-Prompt).
- [ ] `settings.json` im Build-Ordner loeschen/ignorieren, damit sie nicht versehentlich
      mit hochgeladen wird (enthaelt lokale Nutzereinstellungen).

## 4. GitHub Release
- [ ] Release auf https://github.com/xLordTime/Fisch-Bot-DE erstellen.
- [ ] Tag-Name exakt wie in Schritt 1 (`vX.Y.Z`).
- [ ] **`FischBotDE.exe` als Release-Asset hochladen** - ohne eine `.exe` im Release
      findet `updater.py` kein Downloadlink und kann nicht automatisch aktualisieren.
- [ ] Release-Notes (Changelog) in das Release-Textfeld schreiben - wird den Nutzern im
      Update-Dialog angezeigt.
- [ ] Release **nicht** als "Draft" oder "Pre-release" markieren, sonst taucht es nicht
      als "latest" in der GitHub-API auf (`/releases/latest`), die `updater.py` abfragt.

## 5. Nach dem Release
- [ ] Mit einer alten EXE-Version testen, ob der Update-Check (Button oder Autostart)
      das neue Release findet und der Download/Neustart funktioniert.
- [ ] Falls sich das Patch-Format grundlegend geaendert hat (neue Settings-Felder etc.),
      pruefen ob alte `settings.json`-Dateien noch kompatibel geladen werden (fehlende
      Felder fallen in `gui.py` automatisch auf Standardwerte zurueck).
- [ ] Dauerhafte Nutzerdaten immer ueber `app_paths.py` unter
      `%LOCALAPPDATA%\FischBotDE` speichern; keine Daten neben der EXE ablegen.
