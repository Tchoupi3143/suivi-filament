#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Construit les paquets à distribuer dans dist/ :

  SuiviFilament-app-mac-<version>.zip      application « Suivi Filament.app »
  SuiviFilament-scripts-mac-<version>.zip  version ligne de commande + installeur macOS
  SuiviFilament-scripts-windows-<version>.zip

    python3 build.py

Bibliothèque standard uniquement. Les droits d'exécution sont conservés dans les zips
(indispensable pour que macOS lance l'application et les scripts).
"""
import os
import plistlib
import zipfile

RACINE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(RACINE, "dist")
DATE_FIXE = (2026, 1, 1, 0, 0, 0)          # zips reproductibles


def r(*p):
    return os.path.join(RACINE, *p)


def ajouter(z, chemin_zip, source=None, contenu=None, executable=False):
    info = zipfile.ZipInfo(chemin_zip, DATE_FIXE)
    info.compress_type = zipfile.ZIP_DEFLATED
    if source:
        executable = executable or os.access(source, os.X_OK)
        with open(source, "rb") as f:
            contenu = f.read()
    info.external_attr = ((0o100755 if executable else 0o100644) << 16)
    z.writestr(info, contenu)


def dossier(z, chemin_zip):
    info = zipfile.ZipInfo(chemin_zip.rstrip("/") + "/", DATE_FIXE)
    info.external_attr = (0o40755 << 16) | 0x10
    z.writestr(info, b"")


def version():
    with open(r("macos", "app", "Info.plist"), "rb") as f:
        return plistlib.load(f)["CFBundleShortVersionString"]


def app_mac(v):
    out = os.path.join(DIST, f"SuiviFilament-app-mac-{v}.zip")
    base = "Suivi Filament/Suivi Filament.app/Contents/"
    with zipfile.ZipFile(out, "w") as z:
        for d in ("Suivi Filament", base[:-1], base + "MacOS", base + "Resources"):
            dossier(z, d)
        ajouter(z, base + "Info.plist", r("macos", "app", "Info.plist"))
        ajouter(z, base + "PkgInfo", contenu=b"APPL????")
        ajouter(z, base + "MacOS/SuiviFilament", r("macos", "app", "SuiviFilament"), executable=True)
        for f in sorted(os.listdir(r("src"))):
            if f.endswith((".py", ".html", ".json", ".icns")):
                ajouter(z, base + "Resources/" + f, r("src", f))
        ajouter(z, "Suivi Filament/LISEZMOI.md", r("docs", "macos-app.md"))
    return out


def scripts_mac(v):
    out = os.path.join(DIST, f"SuiviFilament-scripts-mac-{v}.zip")
    with zipfile.ZipFile(out, "w") as z:
        dossier(z, "SuiviFilament-mac")
        for f in ("installer.command", "bobines", "Bobines.command"):
            ajouter(z, "SuiviFilament-mac/" + f, r("macos", "scripts", f), executable=True)
        for f in ("suivi_filament.py", "configurer_slicer.py"):
            ajouter(z, "SuiviFilament-mac/" + f, r("src", f), executable=True)
        ajouter(z, "SuiviFilament-mac/LISEZMOI.md", r("docs", "macos-scripts.md"))
    return out


def scripts_windows(v):
    out = os.path.join(DIST, f"SuiviFilament-scripts-windows-{v}.zip")
    with zipfile.ZipFile(out, "w") as z:
        dossier(z, "SuiviFilament-windows")
        ajouter(z, "SuiviFilament-windows/suivi_filament.py", r("src", "suivi_filament.py"))
        ajouter(z, "SuiviFilament-windows/bobines.bat", r("windows", "bobines.bat"))
        ajouter(z, "SuiviFilament-windows/LISEZMOI.md", r("docs", "windows.md"))
    return out


if __name__ == "__main__":
    os.makedirs(DIST, exist_ok=True)
    v = version()
    for fabrique in (app_mac, scripts_mac, scripts_windows):
        chemin = fabrique(v)
        print(f"{os.path.relpath(chemin, RACINE)}  ({os.path.getsize(chemin) // 1024} Ko)")
