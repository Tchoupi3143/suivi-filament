#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Construit dist/SuiviLoyers-mac-<version>.zip : l'application « Suivi Loyers.app »
(à glisser dans Applications) et son mode d'emploi.

    python3 build.py

Bibliothèque standard uniquement ; les droits d'exécution sont conservés dans le zip.
L'icône (src/AppIcon.icns, src/icone.png) est générée depuis macos/icone.svg.
"""
import os
import plistlib
import zipfile

RACINE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(RACINE, "dist")
DATE_FIXE = (2026, 1, 1, 0, 0, 0)


def r(*p):
    return os.path.join(RACINE, *p)


def ajouter(z, chemin, source=None, contenu=None, executable=False):
    info = zipfile.ZipInfo(chemin, DATE_FIXE)
    info.compress_type = zipfile.ZIP_DEFLATED
    if source:
        with open(source, "rb") as f:
            contenu = f.read()
    info.external_attr = (0o100755 if executable else 0o100644) << 16
    z.writestr(info, contenu)


def dossier(z, chemin):
    info = zipfile.ZipInfo(chemin.rstrip("/") + "/", DATE_FIXE)
    info.external_attr = (0o40755 << 16) | 0x10
    z.writestr(info, b"")


def version():
    with open(r("macos", "Info.plist"), "rb") as f:
        return plistlib.load(f)["CFBundleShortVersionString"]


def app_mac(v):
    out = os.path.join(DIST, f"SuiviLoyers-mac-{v}.zip")
    base = "Suivi Loyers/Suivi Loyers.app/Contents/"
    with zipfile.ZipFile(out, "w") as z:
        for d in ("Suivi Loyers", base[:-1], base + "MacOS", base + "Resources"):
            dossier(z, d)
        ajouter(z, base + "Info.plist", r("macos", "Info.plist"))
        ajouter(z, base + "PkgInfo", contenu=b"APPL????")
        ajouter(z, base + "MacOS/SuiviLoyers", r("macos", "SuiviLoyers"), executable=True)
        for f in sorted(os.listdir(r("src"))):
            if f.endswith((".py", ".html", ".icns", ".png")):
                ajouter(z, base + "Resources/" + f, r("src", f))
        with open(r("README.md"), "rb") as f:
            ajouter(z, "Suivi Loyers/LISEZMOI.md", contenu=f.read().replace(b"(../LICENSE)", b"(LICENSE)"))
        ajouter(z, "Suivi Loyers/LICENSE", r("..", "LICENSE"))
    return out


if __name__ == "__main__":
    os.makedirs(DIST, exist_ok=True)
    chemin = app_mac(version())
    print(f"{os.path.relpath(chemin, RACINE)}  ({os.path.getsize(chemin) // 1024} Ko)")
